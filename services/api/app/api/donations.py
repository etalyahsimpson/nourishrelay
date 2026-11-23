"""Donation lifecycle endpoints: create, edit (optimistic), publish,
withdraw, list/detail with derived availability, and match computation."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, Query, Request

from .. import db
from ..dependencies import CurrentUser, enforce_csrf, get_current_user, require_roles
from ..domain.clock import ensure_utc, utcnow
from ..domain.idempotency import (
    check_replay,
    load_events_for_aggregate,
    record_audit,
    record_event,
    require_idempotency_key,
)
from ..domain.matching import compute_matches
from ..domain.reservations import _dec_str
from ..domain.transitions import committed_kg, recompute_donation_status, transition_donation
from ..errors import ApiError
from ..schemas.donation import (
    DonationCreate,
    DonationDetail,
    DonationListResponse,
    DonationUpdate,
    MatchListResponse,
    PublishRequest,
    WithdrawRequest,
)
from ..security import fingerprint_request as fingerprint_of
from ..views import DONATION_SELECT, donation_row

router = APIRouter(prefix="/donations", tags=["donations"])

PUBLISH_EVENT = "DONATION_PUBLISHED"
WITHDRAW_EVENT = "DONATION_WITHDRAWN"

_DONATION_STATUSES = {
    "DRAFT", "AVAILABLE", "PARTIALLY_RESERVED", "FULLY_RESERVED",
    "CLOSED", "EXPIRED", "WITHDRAWN",
}


def _validate_window(pickup_start: datetime, pickup_end: datetime, deadline: datetime, now) -> None:
    if not (pickup_start < pickup_end):
        raise ApiError(422, "INVALID_WINDOW", "pickup_start must be before pickup_end.")
    if not (pickup_start < deadline <= pickup_end):
        raise ApiError(422, "INVALID_WINDOW", "deadline must lie inside (pickup_start, pickup_end].")
    if pickup_start <= now:
        raise ApiError(422, "WINDOW_IN_PAST", "pickup_start must be in the future.")


@router.post("", status_code=201)
def create_donation(
    body: DonationCreate,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(enforce_csrf),
) -> dict:
    now = utcnow()
    if user.role != "donor" or not user.organization_id:
        raise ApiError(403, "FORBIDDEN", "Only donor organizations can create donations.")
    pickup_start = ensure_utc(body.pickup_start)
    pickup_end = ensure_utc(body.pickup_end)
    deadline = ensure_utc(body.deadline)
    _validate_window(pickup_start, pickup_end, deadline, now)

    donation_id = str(uuid.uuid4())
    with db.tx() as conn:
        conn.execute(
            """
            INSERT INTO donations (id, donor_org_id, created_by, category, quantity_kg,
                                   handling_tags, pickup_start, pickup_end, deadline,
                                   status, location_label, notes, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'DRAFT', %s, %s, %s, %s)
            """,
            (
                donation_id, user.organization_id, user.id, body.category,
                str(body.quantity_kg), body.handling_tags, pickup_start, pickup_end,
                deadline, body.location_label, body.notes, now, now,
            ),
        )
        record_event(
            conn, aggregate_type="donation", aggregate_id=donation_id, actor_id=user.id,
            event_type="DONATION_CREATED", idempotency_key=f"create:{donation_id}",
            request_hash=fingerprint_of({"id": donation_id}),
            response_result={"id": donation_id, "status": "DRAFT"},
            payload={"quantity_kg": str(body.quantity_kg), "category": body.category},
            occurred_at=now,
        )
        record_audit(
            conn, actor_id=user.id, organization_id=user.organization_id,
            action="donation.create", resource_type="donation", resource_id=donation_id,
            outcome="draft", safe_summary={"quantity_kg": str(body.quantity_kg)},
            occurred_at=now,
        )
        row = conn.execute(DONATION_SELECT + " WHERE d.id = %s", (donation_id,)).fetchone()
        payload = donation_row(conn, row)
    return payload


def _editable_check(conn, donation: dict, now) -> None:
    committed = committed_kg(conn, str(donation["id"]))
    if committed > 0:
        raise ApiError(
            409, "COMMITTED_INVENTORY",
            "Donations with committed stock can no longer be edited.",
        )
    if donation["status"] not in ("DRAFT", "AVAILABLE"):
        raise ApiError(409, "STATE_CONFLICT", f"Cannot edit a {donation['status']} donation.")
    if donation["deadline"] <= now:
        raise ApiError(409, "STATE_CONFLICT", "Donation deadline has passed.")


@router.patch("/{donation_id}")
def update_donation(
    donation_id: str,
    body: DonationUpdate,
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(enforce_csrf),
) -> dict:
    now = utcnow()
    with db.tx() as conn:
        row = conn.execute(
            DONATION_SELECT + " WHERE d.id = %s FOR UPDATE", (donation_id,)
        ).fetchone()
        if row is None:
            raise ApiError(404, "NOT_FOUND", "Donation not found.")
        donation = donation_row(conn, row)
        if donation["donor_org_id"] != user.organization_id or user.role != "donor":
            # Opaque 404: do not confirm other tenants' donation existence.
            raise ApiError(404, "NOT_FOUND", "Donation not found.")
        if donation["version"] != body.version:
            raise ApiError(
                409, "STALE_VERSION",
                "The donation changed since you loaded it. Refresh and retry.",
                {"current_version": donation["version"]},
            )
        _editable_check(conn, donation, now)

        before = {
            "category": donation["category"],
            "quantity_kg": donation["quantity_kg"],
            "handling_tags": donation["handling_tags"],
            "pickup_start": donation["pickup_start"].isoformat(),
            "pickup_end": donation["pickup_end"].isoformat(),
            "deadline": donation["deadline"].isoformat(),
            "location_label": donation["location_label"],
            "notes": donation["notes"],
        }
        new_pickup_start = ensure_utc(body.pickup_start) if body.pickup_start else donation["pickup_start"]
        new_pickup_end = ensure_utc(body.pickup_end) if body.pickup_end else donation["pickup_end"]
        new_deadline = ensure_utc(body.deadline) if body.deadline else donation["deadline"]
        new_qty = Decimal(str(body.quantity_kg)) if body.quantity_kg else Decimal(donation["quantity_kg"])
        _validate_window(new_pickup_start, new_pickup_end, new_deadline, now)

        new_version = donation["version"] + 1
        after = {
            "category": body.category or donation["category"],
            "quantity_kg": str(new_qty),
            "handling_tags": body.handling_tags if body.handling_tags is not None else donation["handling_tags"],
            "pickup_start": new_pickup_start.isoformat(),
            "pickup_end": new_pickup_end.isoformat(),
            "deadline": new_deadline.isoformat(),
            "location_label": body.location_label or donation["location_label"],
            "notes": body.notes if body.notes is not None else donation["notes"],
        }
        conn.execute(
            """
            UPDATE donations SET category=%s, quantity_kg=%s, handling_tags=%s,
                   pickup_start=%s, pickup_end=%s, deadline=%s, location_label=%s,
                   notes=%s, version=%s, updated_at=%s
            WHERE id = %s
            """,
            (
                after["category"], str(new_qty), after["handling_tags"],
                new_pickup_start, new_pickup_end, new_deadline,
                after["location_label"], after["notes"], new_version, now, donation_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO donation_revisions (id, donation_id, version, actor_id,
                                            before_json, after_json, changed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (str(uuid.uuid4()), donation_id, new_version, user.id,
             _json(before), _json(after), now),
        )
        record_event(
            conn, aggregate_type="donation", aggregate_id=donation_id, actor_id=user.id,
            event_type="DONATION_EDITED", idempotency_key=f"edit:{donation_id}:{new_version}",
            request_hash=fingerprint_of(after),
            response_result={"version": new_version},
            payload=after, occurred_at=now,
        )
        record_audit(
            conn, actor_id=user.id, organization_id=user.organization_id,
            action="donation.edit", resource_type="donation", resource_id=donation_id,
            outcome="edited", safe_summary={"version": new_version}, occurred_at=now,
        )
        row = conn.execute(DONATION_SELECT + " WHERE d.id = %s", (donation_id,)).fetchone()
        return donation_row(conn, row)


def _json(value: dict) -> str:
    import json

    return json.dumps(value, default=str)


@router.post("/{donation_id}/publish")
def publish_donation(
    donation_id: str,
    body: PublishRequest,
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(enforce_csrf),
    idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    key = require_idempotency_key(idempotency_key)
    now = utcnow()
    payload = {"attested": True}
    with db.tx() as conn:
        replay = check_replay(conn, user.id, PUBLISH_EVENT, key, payload)
        if replay is not None:
            return replay
        row = conn.execute(
            DONATION_SELECT + " WHERE d.id = %s FOR UPDATE", (donation_id,)
        ).fetchone()
        if row is None:
            raise ApiError(404, "NOT_FOUND", "Donation not found.")
        donation = donation_row(conn, row)
        if user.role != "donor" or donation["donor_org_id"] != user.organization_id:
            raise ApiError(404, "NOT_FOUND", "Donation not found.")
        replay = check_replay(conn, user.id, PUBLISH_EVENT, key, payload)
        if replay is not None:
            return replay
        if donation["status"] == "AVAILABLE":
            return {"id": donation_id, "status": "AVAILABLE", "published_at": donation["published_at"]}
        if donation["status"] != "DRAFT":
            raise ApiError(
                409, "STATE_CONFLICT", f"Cannot publish a {donation['status']} donation."
            )
        if donation["deadline"] <= now:
            raise ApiError(409, "STATE_CONFLICT", "Deadline already passed; cannot publish.")
        conn.execute(
            "UPDATE donations SET status='AVAILABLE', published_at=%s, updated_at=%s WHERE id=%s",
            (now, now, donation_id),
        )
        result = {"id": donation_id, "status": "AVAILABLE", "published_at": now}
        record_event(
            conn, aggregate_type="donation", aggregate_id=donation_id, actor_id=user.id,
            event_type=PUBLISH_EVENT, idempotency_key=key,
            request_hash=fingerprint_of(payload), response_result=result,
            payload={"attested": True}, occurred_at=now,
        )
        record_audit(
            conn, actor_id=user.id, organization_id=user.organization_id,
            action="donation.publish", resource_type="donation", resource_id=donation_id,
            outcome="available", safe_summary={"attested": True}, occurred_at=now,
        )
        return result


@router.post("/{donation_id}/withdraw")
def withdraw_donation(
    donation_id: str,
    body: WithdrawRequest,
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(enforce_csrf),
    idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    key = require_idempotency_key(idempotency_key)
    now = utcnow()
    payload = {"reason": body.reason or ""}
    with db.tx() as conn:
        replay = check_replay(conn, user.id, WITHDRAW_EVENT, key, payload)
        if replay is not None:
            return replay
        row = conn.execute(
            DONATION_SELECT + " WHERE d.id = %s FOR UPDATE", (donation_id,)
        ).fetchone()
        if row is None:
            raise ApiError(404, "NOT_FOUND", "Donation not found.")
        donation = donation_row(conn, row)
        owns = user.role == "donor" and donation["donor_org_id"] == user.organization_id
        platform = user.role in {"coordinator", "admin"}
        if not (owns or platform):
            raise ApiError(404, "NOT_FOUND", "Donation not found.")
        replay = check_replay(conn, user.id, WITHDRAW_EVENT, key, payload)
        if replay is not None:
            return replay
        if donation["status"] == "WITHDRAWN":
            return {"id": donation_id, "status": "WITHDRAWN"}  # idempotent repeat
        committed = committed_kg(conn, donation_id)
        if committed > 0:
            raise ApiError(
                409, "COMMITTED_INVENTORY",
                "Committed stock cannot be withdrawn; cancel the outstanding reservations first.",
                {"committed_kg": _dec_str(committed)},
            )
        if donation["status"] not in ("DRAFT", "AVAILABLE"):
            raise ApiError(409, "STATE_CONFLICT", f"Cannot withdraw a {donation['status']} donation.")
        transition_donation(
            conn, donation_id, ("DRAFT", "AVAILABLE"), "WITHDRAWN", now=now,
            actor_label=user.role,
        )
        result = {"id": donation_id, "status": "WITHDRAWN"}
        record_event(
            conn, aggregate_type="donation", aggregate_id=donation_id, actor_id=user.id,
            event_type=WITHDRAW_EVENT, idempotency_key=key,
            request_hash=fingerprint_of(payload), response_result=result,
            payload=payload, occurred_at=now,
        )
        record_audit(
            conn, actor_id=user.id, organization_id=user.organization_id,
            action="donation.withdraw", resource_type="donation", resource_id=donation_id,
            outcome="withdrawn", safe_summary={"reason": body.reason or ""}, occurred_at=now,
        )
        return result


@router.get("", response_model=DonationListResponse)
def list_donations(
    request: Request,
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
    donation_status: str | None = Query(default=None, deprecated=False),
    donor_org_id: str | None = Query(default=None, alias="donor_org_id"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    status = status or donation_status
    if status is not None and status.upper() not in _DONATION_STATUSES:
        raise ApiError(422, "INVALID_FILTER", f"status must be one of {sorted(_DONATION_STATUSES)}")
    clauses: list[str] = []
    params: list = []
    if user.role == "donor":
        clauses = ["d.donor_org_id = %s"]
        params = [user.organization_id]
    elif user.role == "recipient":
        clauses = ["d.status IN ('AVAILABLE','PARTIALLY_RESERVED','FULLY_RESERVED')"]
    elif user.role == "transport":
        raise ApiError(403, "FORBIDDEN", "Transport users work from the pickups queue.")
    else:
        # coordinator/admin/analyst see all published donations
        clauses = ["d.status <> 'DRAFT'"]
    if category:
        clauses.append("d.category = %s")
        params.append(category.strip().lower())
    if status:
        clauses.append("d.status = %s")
        params.append(status.upper())
    if donor_org_id and user.role in {"coordinator", "admin", "analyst"}:
        clauses.append("d.donor_org_id = %s")
        params.append(donor_org_id)
    where = " AND ".join(clauses)
    with db.tx() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM donations d JOIN organizations o ON o.id = d.donor_org_id WHERE {where}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            DONATION_SELECT + f" WHERE {where} ORDER BY d.pickup_start ASC, d.created_at DESC LIMIT %s OFFSET %s",
            params + [limit, offset],
        ).fetchall()
        items = [donation_row(conn, r) for r in rows]
    return {"items": items, "total": int(total), "limit": limit, "offset": offset}


def _load_donation_or_404(conn, donation_id: str, user: CurrentUser) -> dict:
    row = conn.execute(DONATION_SELECT + " WHERE d.id = %s", (donation_id,)).fetchone()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Donation not found.")
    donation = donation_row(conn, row)
    is_owner = user.role == "donor" and donation["donor_org_id"] == user.organization_id
    is_platform = user.role in {"coordinator", "admin", "analyst"}
    is_recipient = user.role == "recipient"
    if is_recipient:
        if donation["status"] not in ("AVAILABLE", "PARTIALLY_RESERVED", "FULLY_RESERVED"):
            raise ApiError(404, "NOT_FOUND", "Donation not found.")
    elif not (is_owner or is_platform):
        raise ApiError(404, "NOT_FOUND", "Donation not found.")
    return donation


@router.get("/{donation_id}")
def donation_detail(
    donation_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    now = utcnow()
    with db.tx() as conn:
        donation = _load_donation_or_404(conn, donation_id, user)
        revisions = conn.execute(
            """
            SELECT dr.version, dr.actor_id, dr.changed_at, dr.before_json, dr.after_json
            FROM donation_revisions dr WHERE dr.donation_id = %s
            ORDER BY dr.version ASC
            """,
            (donation_id,),
        ).fetchall()
        if user.role == "recipient":
            reservation_rows = conn.execute(
                """
                SELECT r.id, r.state, r.quantity_kg, r.recipient_org_id, r.created_at
                FROM reservations r
                WHERE r.donation_id = %s AND r.recipient_org_id = %s
                ORDER BY r.created_at
                """,
                (donation_id, user.organization_id),
            ).fetchall()
        else:
            reservation_rows = conn.execute(
                """
                SELECT r.id, r.state, r.quantity_kg, r.recipient_org_id, r.created_at
                FROM reservations r WHERE r.donation_id = %s ORDER BY r.created_at
                """,
                (donation_id,),
            ).fetchall()
        timeline = load_events_for_aggregate(conn, "donation", donation_id)
    reservations = [
        {
            "id": str(r[0]), "state": r[1], "quantity_kg": _dec_str(r[2]),
            "recipient_org_id": str(r[3]), "created_at": r[4],
        }
        for r in reservation_rows
    ]
    committed = Decimal(donation["committed_kg"])
    allowed = []
    if user.role == "donor" and donation["donor_org_id"] == user.organization_id:
        if donation["status"] == "DRAFT":
            allowed += ["edit", "publish", "withdraw"]
        elif donation["status"] == "AVAILABLE" and committed == 0:
            allowed += ["edit", "withdraw"]
    if user.role in {"coordinator", "admin"} and donation["status"] in ("AVAILABLE", "PARTIALLY_RESERVED"):
        allowed += ["match", "propose"]
    detail = dict(donation)
    detail["revisions"] = [
        {
            "version": r[0], "actor_id": str(r[1]), "changed_at": r[2],
            "before": r[3], "after": r[4],
        }
        for r in revisions
    ]
    detail["reservations"] = reservations
    detail["allowed_actions"] = allowed
    detail["available_transitions"] = _donation_transitions(donation, committed)
    detail["timeline"] = timeline
    return detail


def _donation_transitions(donation: dict, committed: Decimal) -> list[str]:
    status = donation["status"]
    if status == "DRAFT":
        return ["AVAILABLE", "WITHDRAWN"]
    if status == "AVAILABLE":
        return ["PARTIALLY_RESERVED", "FULLY_RESERVED", "WITHDRAWN", "EXPIRED"]
    if status == "PARTIALLY_RESERVED":
        return ["FULLY_RESERVED", "EXPIRED"]
    if status == "FULLY_RESERVED":
        return ["CLOSED", "EXPIRED"]
    return []


@router.get("/{donation_id}/matches", response_model=MatchListResponse)
def donation_matches(
    donation_id: str,
    user: CurrentUser = Depends(require_roles("coordinator", "admin")),
) -> dict:
    now = utcnow()
    with db.tx() as conn:
        row = conn.execute(DONATION_SELECT + " WHERE d.id = %s", (donation_id,)).fetchone()
        if row is None:
            raise ApiError(404, "NOT_FOUND", "Donation not found.")
        donation = donation_row(conn, row)
        if donation["status"] == "DRAFT":
            raise ApiError(409, "DONATION_NOT_AVAILABLE", "Draft donations have no matches yet.")
        return compute_matches(conn, donation, now)
