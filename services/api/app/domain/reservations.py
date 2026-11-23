"""Reservation service: proposals, atomic acceptance, decline and cancellation.

Atomic acceptance contract (spec §4.3):
1. `SELECT ... FOR UPDATE` on the donation row serializes every acceptance
   against the same donation (concurrent 80kg+80kg against 120kg cannot both
   commit).
2. Inside the same transaction the committed stock is recomputed and compared
   to the requested quantity — STOCK_CONFLICT (409) carries the actual
   remaining availability.
3. Recipient eligibility (verification, category, handling, receiving-window
   overlap, daily capacity) is re-checked under the same locks; capacity uses
   a transaction-scoped advisory lock on (recipient, receiving date) so that
   same-day concurrent acceptances serialize.
4. The reservation row itself is transitioned with a guarded UPDATE
   (`WHERE state = 'PROPOSED'`), so late/double acceptances fail with 409.
5. Events + audit rows are written in the same transaction; idempotent replay
   of an identical (actor, key, payload) returns the stored result.

Proposals do NOT reserve stock: only acceptance commits quantity.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from ..dependencies import CurrentUser
from ..errors import ApiError
from ..security import fingerprint_request as fingerprint_of
from . import queries
from .clock import ensure_utc, local_date_of, receiving_overlap_minutes
from .idempotency import check_replay, record_audit, record_event
from .matching import donation_level_checks
from .transitions import (
    DONATION_ACTIVE,
    committed_kg,
    norm_uuids,
    recompute_donation_status,
    reservation_guarded_update,
)

ACCEPT_EVENT = "RESERVATION_ACCEPTED"
PROPOSE_EVENT = "RESERVATION_PROPOSED"
DECLINE_EVENT = "RESERVATION_DECLINED"
CANCEL_EVENT = "RESERVATION_CANCELLED"


def _dec_str(value: Decimal | str | float) -> str:
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return str(d.quantize(Decimal("0.001")))


def _load_donation(conn, donation_id: str, for_update: bool = False):
    sql = """
        SELECT d.id, d.donor_org_id, d.created_by, d.category, d.quantity_kg,
               d.handling_tags, d.pickup_start, d.pickup_end, d.deadline,
               d.status, d.location_label, d.notes, d.version,
               d.created_at, d.updated_at, d.published_at,
               o.name AS donor_org_name, o.service_area AS donor_service_area
        FROM donations d JOIN organizations o ON o.id = d.donor_org_id
        WHERE d.id = %s
    """
    if for_update:
        sql = sql.replace("WHERE d.id = %s", "WHERE d.id = %s FOR UPDATE")
    row = conn.execute(sql, (donation_id,)).fetchone()
    if row is None:
        return None
    keys = [
        "id", "donor_org_id", "created_by", "category", "quantity_kg",
        "handling_tags", "pickup_start", "pickup_end", "deadline",
        "status", "location_label", "notes", "version",
        "created_at", "updated_at", "published_at",
        "donor_org_name", "donor_service_area",
    ]
    return norm_uuids(dict(zip(keys, row)))


def _load_reservation(conn, reservation_id: str, for_update: bool = False):
    sql = """
        SELECT r.id, r.donation_id, r.recipient_org_id, r.proposed_by,
               r.quantity_kg, r.state, r.failure_stage, r.proposal_expires_at,
               r.accepted_at, r.released_at, r.decline_reason, r.cancel_reason,
               r.failure_reason, r.created_at, r.updated_at
        FROM reservations r WHERE r.id = %s
    """
    if for_update:
        sql = sql.replace("WHERE r.id = %s", "WHERE r.id = %s FOR UPDATE")
    row = conn.execute(sql, (reservation_id,)).fetchone()
    if row is None:
        return None
    keys = [
        "id", "donation_id", "recipient_org_id", "proposed_by",
        "quantity_kg", "state", "failure_stage", "proposal_expires_at",
        "accepted_at", "released_at", "decline_reason", "cancel_reason",
        "failure_reason", "created_at", "updated_at",
    ]
    return norm_uuids(dict(zip(keys, row)))


def _load_recipient(conn, recipient_org_id: str):
    row = conn.execute(
        """
        SELECT o.id, o.name, o.verified, o.service_area,
               rp.accepted_categories, rp.max_kg_per_day,
               rp.handling_acknowledged, rp.receiving_start, rp.receiving_end,
               rp.timezone, rp.active
        FROM organizations o
        LEFT JOIN recipient_profiles rp ON rp.organization_id = o.id
        WHERE o.id = %s AND o.kind = 'recipient'
        """,
        (recipient_org_id,),
    ).fetchone()
    if row is None:
        return None
    keys = [
        "id", "name", "verified", "service_area", "accepted_categories",
        "max_kg_per_day", "handling_acknowledged", "receiving_start",
        "receiving_end", "timezone", "active",
    ]
    d = norm_uuids(dict(zip(keys, row)))
    if d["max_kg_per_day"] is not None:
        d["max_kg_per_day"] = Decimal(str(d["max_kg_per_day"]))
    return d


def _eligibility_reasons(donation: dict, recipient: dict, now: datetime) -> list[str]:
    """The same hard filters the matching engine applies — re-run under locks
    at acceptance so a stale proposal cannot commit ineligible quantity."""
    reasons: list[str] = []
    if not recipient["verified"]:
        reasons.append("RECIPIENT_NOT_VERIFIED")
    if not recipient["active"] or recipient["accepted_categories"] is None:
        reasons.append("RECIPIENT_INACTIVE")
    if donation["category"] not in (recipient["accepted_categories"] or []):
        reasons.append("CATEGORY_NOT_ACCEPTED")
    missing = [t for t in donation["handling_tags"] if t not in (recipient["handling_acknowledged"] or [])]
    if missing:
        reasons.append("HANDLING_NOT_ACKNOWLEDGED")
    try:
        overlap = receiving_overlap_minutes(
            donation["pickup_start"], donation["pickup_end"],
            recipient["receiving_start"], recipient["receiving_end"],
            recipient["timezone"] or "UTC",
        )
    except Exception:
        overlap = 0.0
    if overlap <= 0:
        reasons.append("RECEIVING_WINDOW_MISMATCH")
    if donation["deadline"] <= now:
        reasons.append("DEADLINE_PASSED")
    return reasons


def propose_reservation(
    conn,
    *,
    actor: CurrentUser,
    donation_id: str,
    recipient_org_id: str,
    quantity_kg: Decimal | str,
    proposal_expires_at: datetime,
    now: datetime,
    idempotency_key: str,
) -> dict:
    quantity_kg = quantity_kg if isinstance(quantity_kg, Decimal) else Decimal(str(quantity_kg))
    payload = {
        "donation_id": str(donation_id),
        "recipient_org_id": str(recipient_org_id),
        "quantity_kg": _dec_str(quantity_kg),
    }
    replay = check_replay(conn, actor.id, PROPOSE_EVENT, idempotency_key, payload)
    if replay is not None:
        return replay

    if ensure_utc(proposal_expires_at) <= now:
        raise ApiError(422, "INVALID_WINDOW", "proposal_expires_at must be in the future.")

    donation = _load_donation(conn, str(donation_id))
    if donation is None:
        raise ApiError(404, "NOT_FOUND", "Donation not found.")
    level = donation_level_checks(donation, now)
    if level:
        raise ApiError(409, "DONATION_NOT_AVAILABLE", f"Donation is not open for proposals: {', '.join(level)}.")

    recipient = _load_recipient(conn, str(recipient_org_id))
    if recipient is None:
        raise ApiError(422, "INVALID_RECIPIENT", "Recipient organization not found.")

    reasons = _eligibility_reasons(donation, recipient, now)
    if recipient["max_kg_per_day"] is None:
        reasons.append("CAPACITY_UNKNOWN")
    if reasons:
        raise ApiError(
            422, "ELIGIBILITY_VIOLATION", "Recipient is not eligible for this donation.",
            {"reasons": reasons},
        )

    available = max(Decimal(str(donation["quantity_kg"])) - committed_kg(conn, str(donation["id"])), Decimal("0"))
    if quantity_kg > available:
        raise ApiError(
            409, "STOCK_CONFLICT", "The requested quantity is no longer available.",
            {"available_kg": _dec_str(available)},
        )

    reservation_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO reservations (id, donation_id, recipient_org_id, proposed_by,
                                  quantity_kg, state, proposal_expires_at,
                                  created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, 'PROPOSED', %s, %s, %s)
        """,
        (
            reservation_id, str(donation_id), str(recipient_org_id), actor.id,
            str(quantity_kg), ensure_utc(proposal_expires_at), now, now,
        ),
    )
    result = {
        "id": reservation_id,
        "donation_id": str(donation_id),
        "recipient_org_id": str(recipient_org_id),
        "quantity_kg": _dec_str(quantity_kg),
        "state": "PROPOSED",
        "proposal_expires_at": ensure_utc(proposal_expires_at),
        "donation_available_kg": _dec_str(available),
    }
    record_event(
        conn,
        aggregate_type="reservation",
        aggregate_id=reservation_id,
        actor_id=actor.id,
        event_type=PROPOSE_EVENT,
        idempotency_key=idempotency_key,
        request_hash=fingerprint_of(payload),
        response_result=result,
        payload={"quantity_kg": _dec_str(quantity_kg), "recipient_org_id": str(recipient_org_id)},
        occurred_at=now,
    )
    record_audit(
        conn,
        actor_id=actor.id,
        organization_id=actor.organization_id,
        action="reservation.propose",
        resource_type="reservation",
        resource_id=reservation_id,
        outcome="proposed",
        safe_summary={"quantity_kg": _dec_str(quantity_kg), "donation_id": str(donation_id)},
        occurred_at=now,
    )
    return result


def accept_reservation(
    conn,
    *,
    actor: CurrentUser,
    reservation_id: str,
    now: datetime,
    idempotency_key: str,
) -> dict:
    payload = {"accepted": True}
    replay = check_replay(conn, actor.id, ACCEPT_EVENT, idempotency_key, payload)
    if replay is not None:
        return replay

    if actor.role != "recipient" or not actor.organization_id:
        raise ApiError(403, "FORBIDDEN", "Only the target recipient organization can accept a proposal.")

    # Resolve donation first for a deterministic lock order (donation → reservation).
    brief = conn.execute(
        "SELECT donation_id FROM reservations WHERE id = %s", (str(reservation_id),)
    ).fetchone()
    if brief is None:
        raise ApiError(404, "NOT_FOUND", "Reservation not found.")

    donation = _load_donation(conn, brief[0], for_update=True)
    if donation is None:
        raise ApiError(404, "NOT_FOUND", "Reservation not found.")
    reservation = _load_reservation(conn, str(reservation_id), for_update=True)

    if reservation["recipient_org_id"] != actor.organization_id:
        # Opaque: do not confirm other tenants' proposal existence.
        raise ApiError(404, "NOT_FOUND", "Reservation not found.")

    # Post-lock replay re-check (covers the concurrent duplicate case).
    replay = check_replay(conn, actor.id, ACCEPT_EVENT, idempotency_key, payload)
    if replay is not None:
        return replay

    if reservation["state"] != "PROPOSED":
        raise ApiError(
            409, "STATE_CONFLICT", f"Reservation already moved to {reservation['state']}."
        )
    if reservation["proposal_expires_at"] is not None and reservation["proposal_expires_at"] <= now:
        raise ApiError(409, "EXPIRED", "This proposal has expired.")

    if donation["status"] not in DONATION_ACTIVE or donation["deadline"] <= now:
        raise ApiError(409, "DONATION_NOT_AVAILABLE", "The donation is no longer open.")

    recipient = _load_recipient(conn, reservation["recipient_org_id"])
    reasons = _eligibility_reasons(donation, recipient, now) if recipient else ["RECIPIENT_INACTIVE"]
    if reasons:
        raise ApiError(
            422, "ELIGIBILITY_VIOLATION", "Recipient is not eligible for this donation.",
            {"reasons": reasons},
        )

    # Stock re-check under the donation row lock.
    quantity = Decimal(str(reservation["quantity_kg"]))
    committed = committed_kg(conn, str(donation["id"]))
    available = max(Decimal(str(donation["quantity_kg"])) - committed, Decimal("0"))
    if quantity > available:
        raise ApiError(
            409, "STOCK_CONFLICT", "The requested quantity is no longer available.",
            {"available_kg": _dec_str(available)},
        )

    # Daily capacity re-check, serialized per (recipient, receiving day).
    receiving_date = local_date_of(donation["pickup_start"], recipient["timezone"] or "UTC")
    if recipient["max_kg_per_day"] is not None:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (f"capacity:{recipient['id']}:{receiving_date.isoformat()}",),
        )
        usage_row = queries.one(
            conn,
            "matching.sql",
            "recipient_day_capacity_usage",
            {
                "recipient_org_id": recipient["id"],
                "tz": recipient["timezone"] or "UTC",
                "receiving_date": receiving_date,
            },
        )
        used = Decimal(str(usage_row[0]))
        if used + quantity > recipient["max_kg_per_day"]:
            raise ApiError(
                409,
                "CAPACITY_CONFLICT",
                "Daily receiving capacity would be exceeded.",
                {
                    "max_kg_per_day": _dec_str(recipient["max_kg_per_day"]),
                    "committed_kg": _dec_str(used),
                    "receiving_date": receiving_date.isoformat(),
                },
            )

    reservation_guarded_update(
        conn, str(reservation_id), ("PROPOSED",), "ACCEPTED",
        now=now, extra_sets={"accepted_at": now},
    )
    new_status = recompute_donation_status(conn, str(donation["id"]), now=now)
    available_after = max(Decimal(str(donation["quantity_kg"])) - committed_kg(conn, str(donation["id"])), Decimal("0"))

    result = {
        "id": str(reservation_id),
        "state": "ACCEPTED",
        "reserved_quantity_kg": _dec_str(quantity),
        "donation_id": str(donation["id"]),
        "donation_status": new_status,
        "donation_available_kg": _dec_str(available_after),
    }
    record_event(
        conn,
        aggregate_type="reservation",
        aggregate_id=str(reservation_id),
        actor_id=actor.id,
        event_type=ACCEPT_EVENT,
        idempotency_key=idempotency_key,
        request_hash=fingerprint_of(payload),
        response_result=result,
        payload={"quantity_kg": _dec_str(quantity)},
        occurred_at=now,
    )
    record_audit(
        conn,
        actor_id=actor.id,
        organization_id=actor.organization_id,
        action="reservation.accept",
        resource_type="reservation",
        resource_id=str(reservation_id),
        outcome="accepted",
        safe_summary={"quantity_kg": _dec_str(quantity), "donation_id": str(donation["id"])},
        occurred_at=now,
    )
    return result


def decline_reservation(
    conn, *, actor: CurrentUser, reservation_id: str, reason: Optional[str],
    now: datetime, idempotency_key: str,
) -> dict:
    payload = {"reason": reason or ""}
    replay = check_replay(conn, actor.id, DECLINE_EVENT, idempotency_key, payload)
    if replay is not None:
        return replay
    if actor.role != "recipient" or not actor.organization_id:
        raise ApiError(403, "FORBIDDEN", "Only the target recipient organization can decline a proposal.")
    reservation = _load_reservation(conn, str(reservation_id), for_update=True)
    if reservation is None or reservation["recipient_org_id"] != actor.organization_id:
        raise ApiError(404, "NOT_FOUND", "Reservation not found.")
    replay = check_replay(conn, actor.id, DECLINE_EVENT, idempotency_key, payload)
    if replay is not None:
        return replay
    moved = reservation_guarded_update(
        conn, str(reservation_id), ("PROPOSED",), "DECLINED",
        now=now, extra_sets={"decline_reason": reason},
    )
    recompute_donation_status(conn, reservation["donation_id"], now=now)
    result = {"id": str(reservation_id), "state": "DECLINED"}
    record_event(
        conn, aggregate_type="reservation", aggregate_id=str(reservation_id),
        actor_id=actor.id, event_type=DECLINE_EVENT, idempotency_key=idempotency_key,
        request_hash=fingerprint_of(payload), response_result=result,
        payload={"reason": reason or ""}, occurred_at=now,
    )
    record_audit(
        conn, actor_id=actor.id, organization_id=actor.organization_id,
        action="reservation.decline", resource_type="reservation",
        resource_id=str(reservation_id), outcome="declined",
        safe_summary={"reason": reason or ""}, occurred_at=now,
    )
    return result


def cancel_reservation(
    conn, *, actor: CurrentUser, reservation_id: str, reason: Optional[str],
    now: datetime, idempotency_key: str,
) -> dict:
    payload = {"reason": reason or ""}
    replay = check_replay(conn, actor.id, CANCEL_EVENT, idempotency_key, payload)
    if replay is not None:
        return replay
    if actor.role not in {"coordinator", "admin"}:
        raise ApiError(403, "FORBIDDEN", "Only coordinators or admins can cancel reservations.")
    brief = conn.execute(
        "SELECT donation_id FROM reservations WHERE id = %s", (str(reservation_id),)
    ).fetchone()
    if brief is None:
        raise ApiError(404, "NOT_FOUND", "Reservation not found.")
    _load_donation(conn, brief[0], for_update=True)  # deterministic lock order
    reservation = _load_reservation(conn, str(reservation_id), for_update=True)
    replay = check_replay(conn, actor.id, CANCEL_EVENT, idempotency_key, payload)
    if replay is not None:
        return replay
    if reservation["state"] in {"COLLECTED", "DELIVERED", "RECEIVED"} or (
        reservation["state"] == "FAILED" and reservation["failure_stage"] == "AFTER_COLLECTION"
    ):
        raise ApiError(
            409, "STATE_CONFLICT",
            "Collection already happened; cancelling after collection is not allowed.",
        )
    moved = reservation_guarded_update(
        conn, str(reservation_id), ("PROPOSED", "ACCEPTED", "PICKUP_ASSIGNED"), "CANCELLED",
        now=now, extra_sets={"cancel_reason": reason, "released_at": now},
    )
    # Acceptances were committed stock; cancellation releases exactly once
    # (guarded UPDATE above), before collection only (state guard).
    recompute_donation_status(conn, reservation["donation_id"], now=now)
    result = {"id": str(reservation_id), "state": "CANCELLED", "released_at": now}
    record_event(
        conn, aggregate_type="reservation", aggregate_id=str(reservation_id),
        actor_id=actor.id, event_type=CANCEL_EVENT, idempotency_key=idempotency_key,
        request_hash=fingerprint_of(payload), response_result=result,
        payload={"reason": reason or ""}, occurred_at=now,
    )
    record_audit(
        conn, actor_id=actor.id, organization_id=actor.organization_id,
        action="reservation.cancel", resource_type="reservation",
        resource_id=str(reservation_id), outcome="cancelled",
        safe_summary={"reason": reason or "", "released": reservation["state"] in ("ACCEPTED", "PICKUP_ASSIGNED")},
        occurred_at=now,
    )
    return result
