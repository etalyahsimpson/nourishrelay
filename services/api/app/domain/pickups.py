"""Pickup assignment, collection/delivery/failure events and receipt confirmation.

Transition rules (all guarded updates inside the caller's transaction):
- Only ACCEPTED reservations can receive a pickup (reservation -> PICKUP_ASSIGNED).
- COLLECTED: quantity_kg must be positive and cannot exceed the accepted
  reservation quantity. Collected means donor handover, not delivery.
- DELIVERED: recorded delivery, NOT a confirmed receipt.
- FAILED: before collection -> stock released exactly once (reservation
  FAILED with failure_stage=BEFORE_COLLECTION); after collection -> food is
  never automatically reoffered (failure_stage=AFTER_COLLECTION, stock stays
  consumed).
- Receipt: only the target recipient confirms; received <= collected, and a
  received quantity strictly below collected REQUIRES an exception reason.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from ..dependencies import CurrentUser
from ..errors import ApiError
from ..security import fingerprint_request as fingerprint_of
from .clock import ensure_utc
from .idempotency import check_replay, record_audit, record_event
from .transitions import (
    close_donation_if_terminal,
    norm_uuids,
    recompute_donation_status,
    reservation_guarded_update,
)

PICKUP_CREATE_EVENT = "PICKUP_CREATED"
PICKUP_EVENT = "PICKUP_EVENT"
RECEIPT_EVENT = "RECEIPT_CONFIRMED"


def _dec_str(value: Decimal | str | float) -> str:
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return str(d.quantize(Decimal("0.001")))


def _load_pickup(conn, pickup_id: str, for_update: bool = False):
    sql = """
        SELECT p.id, p.reservation_id, p.assigned_transport_org_id,
               p.pickup_window_start, p.pickup_window_end, p.status,
               p.collected_quantity_kg, p.collected_at, p.delivered_at,
               p.failure_reason, p.updated_at
        FROM pickups p WHERE p.id = %s
    """
    if for_update:
        sql = sql.replace("WHERE p.id = %s", "WHERE p.id = %s FOR UPDATE")
    row = conn.execute(sql, (str(pickup_id),)).fetchone()
    if row is None:
        return None
    keys = [
        "id", "reservation_id", "assigned_transport_org_id",
        "pickup_window_start", "pickup_window_end", "status",
        "collected_quantity_kg", "collected_at", "delivered_at",
        "failure_reason", "updated_at",
    ]
    return norm_uuids(dict(zip(keys, row)))


def _load_reservation_with_donation(conn, reservation_id: str, for_update: bool = False):
    sql = """
        SELECT r.id, r.donation_id, r.recipient_org_id, r.proposed_by,
               r.quantity_kg, r.state, r.failure_stage, r.proposal_expires_at,
               r.accepted_at, r.released_at, r.created_at, r.updated_at,
               d.pickup_start, d.pickup_end, d.deadline, d.status AS donation_status,
               d.category, d.donor_org_id
        FROM reservations r JOIN donations d ON d.id = r.donation_id
        WHERE r.id = %s
    """
    if for_update:
        sql = sql.replace("WHERE r.id = %s", "WHERE r.id = %s FOR UPDATE")
    row = conn.execute(sql, (str(reservation_id),)).fetchone()
    if row is None:
        return None
    keys = [
        "id", "donation_id", "recipient_org_id", "proposed_by",
        "quantity_kg", "state", "failure_stage", "proposal_expires_at",
        "accepted_at", "released_at", "created_at", "updated_at",
        "pickup_start", "pickup_end", "deadline", "donation_status",
        "category", "donor_org_id",
    ]
    return norm_uuids(dict(zip(keys, row)))


def create_pickup(
    conn,
    *,
    actor: CurrentUser,
    reservation_id: str,
    assigned_transport_org_id: Optional[str],
    pickup_window_start: datetime,
    pickup_window_end: datetime,
    now: datetime,
    idempotency_key: str,
) -> dict:
    payload = {
        "reservation_id": str(reservation_id),
        "assigned_transport_org_id": str(assigned_transport_org_id) if assigned_transport_org_id else None,
        "pickup_window_start": ensure_utc(pickup_window_start).isoformat(),
        "pickup_window_end": ensure_utc(pickup_window_end).isoformat(),
    }
    replay = check_replay(conn, actor.id, PICKUP_CREATE_EVENT, idempotency_key, payload)
    if replay is not None:
        return replay

    if actor.role not in {"transport", "coordinator", "admin"}:
        raise ApiError(403, "FORBIDDEN", "Only transport or platform roles can schedule pickups.")

    reservation = _load_reservation_with_donation(conn, str(reservation_id), for_update=True)
    if reservation is None:
        raise ApiError(404, "NOT_FOUND", "Reservation not found.")
    replay = check_replay(conn, actor.id, PICKUP_CREATE_EVENT, idempotency_key, payload)
    if replay is not None:
        return replay

    target_org = assigned_transport_org_id
    if actor.role == "transport":
        if not actor.organization_id:
            raise ApiError(403, "FORBIDDEN", "Transport users must belong to a transport organization.")
        if target_org and target_org != actor.organization_id:
            raise ApiError(403, "FORBIDDEN", "Transport users can only assign their own organization.")
        target_org = actor.organization_id
    if target_org:
        org = conn.execute(
            "SELECT kind FROM organizations WHERE id = %s", (target_org,)
        ).fetchone()
        if org is None or org[0] != "transport":
            raise ApiError(422, "INVALID_ORGANIZATION", "assigned_transport_org_id must be a transport organization.")

    w_start, w_end = ensure_utc(pickup_window_start), ensure_utc(pickup_window_end)
    if not (w_start < w_end):
        raise ApiError(422, "INVALID_WINDOW", "pickup_window_start must be before pickup_window_end.")
    if w_start < reservation["pickup_start"] or w_end > reservation["pickup_end"]:
        raise ApiError(
            422, "WINDOW_OUTSIDE_DONATION",
            "Pickup window must stay inside the donation's pickup window.",
            {"donation_pickup_start": reservation["pickup_start"].isoformat(),
             "donation_pickup_end": reservation["pickup_end"].isoformat()},
        )

    reservation_guarded_update(
        conn, str(reservation_id), ("ACCEPTED",), "PICKUP_ASSIGNED", now=now
    )

    pickup_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO pickups (id, reservation_id, assigned_transport_org_id,
                              pickup_window_start, pickup_window_end, status,
                              created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, 'SCHEDULED', %s, %s)
        """,
        (pickup_id, str(reservation_id), target_org, w_start, w_end, now, now),
    )
    result = {
        "id": pickup_id,
        "reservation_id": str(reservation_id),
        "reservation_state": "PICKUP_ASSIGNED",
        "assigned_transport_org_id": target_org,
        "pickup_window_start": w_start,
        "pickup_window_end": w_end,
        "status": "SCHEDULED",
    }
    record_event(
        conn, aggregate_type="pickup", aggregate_id=pickup_id, actor_id=actor.id,
        event_type=PICKUP_CREATE_EVENT, idempotency_key=idempotency_key,
        request_hash=fingerprint_of(payload), response_result=result,
        payload={"reservation_id": str(reservation_id)}, occurred_at=now,
    )
    record_audit(
        conn, actor_id=actor.id, organization_id=actor.organization_id,
        action="pickup.create", resource_type="pickup", resource_id=pickup_id,
        outcome="scheduled",
        safe_summary={"reservation_id": str(reservation_id), "transport_org_id": target_org},
        occurred_at=now,
    )
    return result


def record_pickup_event(
    conn,
    *,
    actor: CurrentUser,
    pickup_id: str,
    event_type: str,
    occurred_at: Optional[datetime],
    quantity_kg: Optional[Decimal],
    reason: Optional[str],
    now: datetime,
    idempotency_key: str,
) -> dict:
    at = ensure_utc(occurred_at) if occurred_at else now
    if at > now:
        raise ApiError(422, "INVALID_TIME", "occurred_at cannot be in the future.")
    payload = {
        "event_type": event_type,
        "occurred_at": at.isoformat(),
        "quantity_kg": str(quantity_kg) if quantity_kg is not None else None,
        "reason": reason or "",
    }
    replay = check_replay(conn, actor.id, PICKUP_EVENT, idempotency_key, payload)
    if replay is not None:
        return replay

    if actor.role not in {"transport", "coordinator", "admin"}:
        raise ApiError(403, "FORBIDDEN", "Only transport or platform roles can report pickup events.")

    pickup = _load_pickup(conn, str(pickup_id), for_update=True)
    if pickup is None:
        raise ApiError(404, "NOT_FOUND", "Pickup not found.")
    reservation = _load_reservation_with_donation(conn, pickup["reservation_id"], for_update=True)
    replay = check_replay(conn, actor.id, PICKUP_EVENT, idempotency_key, payload)
    if replay is not None:
        return replay

    if actor.role == "transport" and actor.organization_id:
        if pickup["assigned_transport_org_id"] not in (None, actor.organization_id):
            raise ApiError(404, "NOT_FOUND", "Pickup not found.")

    if event_type == "COLLECTED":
        if pickup["status"] != "SCHEDULED":
            raise ApiError(409, "STATE_CONFLICT", f"Pickup already {pickup['status']}.")
        if quantity_kg is None:
            raise ApiError(422, "QUANTITY_REQUIRED", "COLLECTED requires quantity_kg.")
        accepted_qty = Decimal(str(reservation["quantity_kg"]))
        if quantity_kg > accepted_qty:
            raise ApiError(
                422, "QUANTITY_EXCEEDS_RESERVATION",
                "Collected quantity cannot exceed the accepted reservation amount.",
                {"reserved_kg": _dec_str(accepted_qty)},
            )
        conn.execute(
            """
            UPDATE pickups
            SET status = 'COLLECTED', collected_quantity_kg = %s, collected_at = %s,
                updated_at = %s
            WHERE id = %s AND status = 'SCHEDULED'
            """,
            (str(quantity_kg), at, now, str(pickup_id)),
        )
        reservation_guarded_update(
            conn, str(pickup["reservation_id"]), ("PICKUP_ASSIGNED",), "COLLECTED", now=now
        )
        new_state = "COLLECTED"

    elif event_type == "DELIVERED":
        if pickup["status"] != "COLLECTED":
            raise ApiError(409, "STATE_CONFLICT", "Pickup must be COLLECTED before DELIVERED.")
        conn.execute(
            "UPDATE pickups SET status = 'DELIVERED', delivered_at = %s, updated_at = %s WHERE id = %s",
            (at, now, str(pickup_id)),
        )
        reservation_guarded_update(
            conn, str(pickup["reservation_id"]), ("COLLECTED",), "DELIVERED", now=now
        )
        new_state = "DELIVERED"

    elif event_type == "FAILED":
        if pickup["status"] in {"DELIVERED", "FAILED"}:
            raise ApiError(409, "STATE_CONFLICT", f"Pickup already {pickup['status']}.")
        if not reason:
            raise ApiError(422, "REASON_REQUIRED", "FAILED requires a reason.")
        stage = "BEFORE_COLLECTION" if pickup["status"] == "SCHEDULED" else "AFTER_COLLECTION"
        conn.execute(
            "UPDATE pickups SET status = 'FAILED', failure_reason = %s, updated_at = %s WHERE id = %s",
            (reason, now, str(pickup_id)),
        )
        # BEFORE_COLLECTION releases committed stock exactly once; AFTER_COLLECTION never does.
        reservation_guarded_update(
            conn,
            str(pickup["reservation_id"]),
            ("PICKUP_ASSIGNED",) if stage == "BEFORE_COLLECTION" else ("COLLECTED",),
            "FAILED",
            now=now,
            extra_sets={"failure_stage": stage, "failure_reason": reason},
        )
        if stage == "BEFORE_COLLECTION":
            # released_at is set exactly once (WHERE released_at IS NULL guard).
            conn.execute(
                "UPDATE reservations SET released_at = %s WHERE id = %s AND released_at IS NULL",
                (at, str(pickup["reservation_id"])),
            )
        new_state = "FAILED"

    else:  # pragma: no cover — schema validation guards this
        raise ApiError(422, "INVALID_EVENT", "Unsupported event_type.")

    recompute_donation_status(conn, reservation["donation_id"], now=now)
    close_donation_if_terminal(conn, reservation["donation_id"], now=now)

    result = {
        "id": str(pickup_id),
        "reservation_id": str(pickup["reservation_id"]),
        "reservation_state": new_state,
        "pickup_status": new_state if event_type != "DELIVERED" else "DELIVERED",
        "event_type": event_type,
        "occurred_at": at,
    }
    record_event(
        conn, aggregate_type="pickup", aggregate_id=str(pickup_id), actor_id=actor.id,
        event_type=PICKUP_EVENT, idempotency_key=idempotency_key,
        request_hash=fingerprint_of(payload), response_result=result,
        payload=payload, occurred_at=at,
    )
    record_audit(
        conn, actor_id=actor.id, organization_id=actor.organization_id,
        action=f"pickup.{event_type.lower()}", resource_type="pickup",
        resource_id=str(pickup_id), outcome=new_state.lower(),
        safe_summary={"reservation_id": str(pickup["reservation_id"]),
                      "quantity_kg": str(quantity_kg) if quantity_kg else None,
                      "reason": reason},
        occurred_at=at,
    )
    return result


def record_receipt(
    conn,
    *,
    actor: CurrentUser,
    pickup_id: str,
    received_quantity_kg: Decimal,
    exception_reason: Optional[str],
    now: datetime,
    idempotency_key: str,
) -> dict:
    payload = {
        "received_quantity_kg": _dec_str(received_quantity_kg),
        "exception_reason": exception_reason or "",
    }
    replay = check_replay(conn, actor.id, RECEIPT_EVENT, idempotency_key, payload)
    if replay is not None:
        return replay

    if actor.role != "recipient" or not actor.organization_id:
        raise ApiError(403, "FORBIDDEN", "Only the target recipient organization can confirm receipt.")

    pickup = _load_pickup(conn, str(pickup_id), for_update=True)
    if pickup is None:
        raise ApiError(404, "NOT_FOUND", "Pickup not found.")
    reservation = _load_reservation_with_donation(conn, pickup["reservation_id"], for_update=True)
    if reservation is None or reservation["recipient_org_id"] != actor.organization_id:
        raise ApiError(404, "NOT_FOUND", "Pickup not found.")
    replay = check_replay(conn, actor.id, RECEIPT_EVENT, idempotency_key, payload)
    if replay is not None:
        return replay

    if pickup["status"] != "DELIVERED":
        raise ApiError(409, "STATE_CONFLICT", "Receipt requires the pickup to be DELIVERED.")
    existing = conn.execute(
        "SELECT id, received_quantity_kg, exception_reason FROM receipts WHERE pickup_id = %s",
        (str(pickup_id),),
    ).fetchone()
    if existing is not None:
        raise ApiError(409, "ALREADY_RECEIVED", "This pickup already has a receipt confirmation.")

    collected = Decimal(str(pickup["collected_quantity_kg"] or 0))
    if received_quantity_kg < 0:
        raise ApiError(422, "INVALID_QUANTITY", "Received quantity cannot be negative.")
    if received_quantity_kg > collected:
        raise ApiError(
            422, "RECEIPT_EXCEEDS_COLLECTED",
            "Received quantity cannot exceed the collected quantity.",
            {"collected_kg": _dec_str(collected)},
        )
    if received_quantity_kg < collected and not exception_reason:
        raise ApiError(
            422, "REASON_REQUIRED",
            "A received quantity below the collected quantity requires an exception reason.",
        )
    if received_quantity_kg == 0 and not exception_reason:
        raise ApiError(422, "REASON_REQUIRED", "A zero receipt requires an exception reason.")

    receipt_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO receipts (id, pickup_id, recipient_user_id, received_quantity_kg,
                              exception_reason, confirmed_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (receipt_id, str(pickup_id), actor.id, str(received_quantity_kg),
         exception_reason, now),
    )
    reservation_guarded_update(
        conn, str(pickup["reservation_id"]), ("DELIVERED",), "RECEIVED", now=now
    )
    recompute_donation_status(conn, reservation["donation_id"], now=now)
    close_donation_if_terminal(conn, reservation["donation_id"], now=now)

    result = {
        "id": receipt_id,
        "pickup_id": str(pickup_id),
        "received_quantity_kg": _dec_str(received_quantity_kg),
        "exception_reason": exception_reason,
        "reservation_state": "RECEIVED",
        "confirmed_at": now,
    }
    record_event(
        conn, aggregate_type="receipt", aggregate_id=receipt_id, actor_id=actor.id,
        event_type=RECEIPT_EVENT, idempotency_key=idempotency_key,
        request_hash=fingerprint_of(payload), response_result=result,
        payload=payload, occurred_at=now,
    )
    record_audit(
        conn, actor_id=actor.id, organization_id=actor.organization_id,
        action="receipt.confirm", resource_type="receipt", resource_id=receipt_id,
        outcome="received",
        safe_summary={"received_quantity_kg": _dec_str(received_quantity_kg),
                      "exception_reason": exception_reason},
        occurred_at=now,
    )
    return result
