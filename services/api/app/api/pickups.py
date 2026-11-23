"""Pickup endpoints: assignment, event reporting (collect/deliver/fail),
receipt confirmation, and role-scoped queues."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Header, Query, Response

from .. import db
from ..dependencies import CurrentUser, enforce_csrf, get_current_user
from ..domain.clock import utcnow
from ..domain.idempotency import require_idempotency_key
from ..domain import pickups as pickup_domain
from ..errors import ApiError
from ..schemas.reservation import (
    PickupCreate,
    PickupEventCreate,
    PickupListResponse,
    ReceiptCreate,
)
from ..views import PICKUP_SELECT, RECEIPT_SELECT, pickup_row

router = APIRouter(prefix="/pickups", tags=["pickups"])


@router.post("", status_code=201)
def create_pickup(
    body: PickupCreate,
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(enforce_csrf),
    idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    key = require_idempotency_key(idempotency_key)
    now = utcnow()
    with db.tx() as conn:
        return pickup_domain.create_pickup(
            conn,
            actor=user,
            reservation_id=body.reservation_id,
            assigned_transport_org_id=body.assigned_transport_org_id,
            pickup_window_start=body.pickup_window_start,
            pickup_window_end=body.pickup_window_end,
            now=now,
            idempotency_key=key,
        )


@router.post("/{pickup_id}/events")
def report_pickup_event(
    pickup_id: str,
    body: PickupEventCreate,
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(enforce_csrf),
    idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    key = require_idempotency_key(idempotency_key)
    now = utcnow()
    with db.tx() as conn:
        return pickup_domain.record_pickup_event(
            conn,
            actor=user,
            pickup_id=pickup_id,
            event_type=body.event_type,
            occurred_at=body.occurred_at,
            quantity_kg=Decimal(str(body.quantity_kg)) if body.quantity_kg is not None else None,
            reason=body.reason,
            now=now,
            idempotency_key=key,
        )


@router.post("/{pickup_id}/receipt", status_code=201)
def confirm_receipt(
    pickup_id: str,
    body: ReceiptCreate,
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(enforce_csrf),
    idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    key = require_idempotency_key(idempotency_key)
    now = utcnow()
    with db.tx() as conn:
        return pickup_domain.record_receipt(
            conn,
            actor=user,
            pickup_id=pickup_id,
            received_quantity_kg=Decimal(str(body.received_quantity_kg)),
            exception_reason=body.exception_reason,
            now=now,
            idempotency_key=key,
        )


@router.get("", response_model=PickupListResponse)
def list_pickups(
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    clauses: list[str] = []
    params: list = []
    if user.role == "transport":
        if not user.organization_id:
            raise ApiError(403, "FORBIDDEN", "Transport users must belong to a transport organization.")
        clauses.append("p.assigned_transport_org_id = %s")
        params.append(user.organization_id)
    elif user.role == "recipient":
        clauses.append("r.recipient_org_id = %s")
        params.append(user.organization_id)
    elif user.role == "donor":
        clauses.append("d.donor_org_id = %s")
        params.append(user.organization_id)
    elif user.role not in {"coordinator", "admin", "analyst"}:
        raise ApiError(403, "FORBIDDEN", "Role cannot list pickups.")
    if status:
        status = status.strip().upper()
        if status not in {"SCHEDULED", "COLLECTED", "DELIVERED", "FAILED"}:
            raise ApiError(422, "INVALID_FILTER", "status must be SCHEDULED, COLLECTED, DELIVERED or FAILED")
        clauses.append("p.status = %s")
        params.append(status)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with db.tx() as conn:
        total = conn.execute(
            f"""
            SELECT COUNT(*) FROM pickups p
            JOIN reservations r ON r.id = p.reservation_id
            JOIN donations d ON d.id = r.donation_id
            {where}
            """,
            params,
        ).fetchone()[0]
        rows = conn.execute(
            PICKUP_SELECT + f" {where} ORDER BY p.pickup_window_start ASC, p.created_at DESC LIMIT %s OFFSET %s",
            params + [limit, offset],
        ).fetchall()
        items = []
        for r in rows:
            receipt = conn.execute(
                RECEIPT_SELECT + " WHERE rc.pickup_id = %s", (str(r[0]),)
            ).fetchone()
            item = pickup_row(r, receipt)
            item["allowed_actions"] = _allowed_actions(user, item)
            items.append(item)
    return {"items": items, "total": int(total), "limit": limit, "offset": offset}


def _allowed_actions(user: CurrentUser, pickup: dict) -> list[str]:
    actions: list[str] = []
    status = pickup["status"]
    can_operate = user.role in {"coordinator", "admin"} or (
        user.role == "transport"
        and user.organization_id
        and pickup["assigned_transport_org_id"] in (None, user.organization_id)
    )
    if can_operate:
        if status == "SCHEDULED":
            actions += ["collect", "fail"]
        elif status == "COLLECTED":
            actions += ["deliver", "fail"]
    if user.role == "recipient" and user.organization_id == pickup["recipient_org_id"]:
        if status == "DELIVERED":
            actions.append("receipt")
    return actions
