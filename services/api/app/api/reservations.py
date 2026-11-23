"""Reservation endpoints: propose (coordinator), accept/decline (recipient),
cancel (coordinator), plus role-scoped lists."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query

from .. import db
from ..dependencies import CurrentUser, enforce_csrf, get_current_user
from ..domain.clock import utcnow
from ..domain.idempotency import require_idempotency_key
from ..domain import reservations as res_domain
from ..errors import ApiError
from ..schemas.reservation import (
    AcceptReservationRequest,
    CancelReservationRequest,
    DeclineReservationRequest,
    ReservationCreate,
    ReservationListResponse,
)
from ..views import RESERVATION_SELECT, reservation_available_kg, reservation_row

router = APIRouter(prefix="/reservations", tags=["reservations"])


@router.post("", status_code=201)
def create_reservation(
    body: ReservationCreate,
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(enforce_csrf),
    idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    if user.role not in {"coordinator", "admin"}:
        raise ApiError(403, "FORBIDDEN", "Only coordinators can propose reservations.")
    key = require_idempotency_key(idempotency_key)
    now = utcnow()
    with db.tx() as conn:
        result = res_domain.propose_reservation(
            conn,
            actor=user,
            donation_id=body.donation_id,
            recipient_org_id=body.recipient_org_id,
            quantity_kg=body.quantity_kg,
            proposal_expires_at=body.proposal_expires_at,
            now=now,
            idempotency_key=key,
        )
    return result


@router.post("/{reservation_id}/accept")
def accept_reservation(
    reservation_id: str,
    body: AcceptReservationRequest,
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(enforce_csrf),
    idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    key = require_idempotency_key(idempotency_key)
    now = utcnow()
    with db.tx() as conn:
        return res_domain.accept_reservation(
            conn, actor=user, reservation_id=reservation_id,
            now=now, idempotency_key=key,
        )


@router.post("/{reservation_id}/decline")
def decline_reservation(
    reservation_id: str,
    body: DeclineReservationRequest,
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(enforce_csrf),
    idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    key = require_idempotency_key(idempotency_key)
    now = utcnow()
    with db.tx() as conn:
        return res_domain.decline_reservation(
            conn, actor=user, reservation_id=reservation_id,
            reason=body.reason, now=now, idempotency_key=key,
        )


@router.post("/{reservation_id}/cancel")
def cancel_reservation(
    reservation_id: str,
    body: CancelReservationRequest,
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(enforce_csrf),
    idempotency_key: str = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    key = require_idempotency_key(idempotency_key)
    now = utcnow()
    with db.tx() as conn:
        return res_domain.cancel_reservation(
            conn, actor=user, reservation_id=reservation_id,
            reason=body.reason, now=now, idempotency_key=key,
        )


@router.get("", response_model=ReservationListResponse)
def list_reservations(
    state: str | None = Query(default=None),
    donation_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    clauses: list[str] = []
    params: list = []
    if user.role == "recipient":
        clauses.append("r.recipient_org_id = %s")
        params.append(user.organization_id)
    elif user.role == "donor":
        clauses.append("d.donor_org_id = %s")
        params.append(user.organization_id)
    elif user.role == "transport":
        raise ApiError(403, "FORBIDDEN", "Transport users work from the pickups queue.")
    elif user.role not in {"coordinator", "admin", "analyst"}:
        raise ApiError(403, "FORBIDDEN", "Role cannot list reservations.")
    if state:
        state = state.strip().upper()
        valid = {
            "PROPOSED", "ACCEPTED", "DECLINED", "CANCELLED", "EXPIRED",
            "PICKUP_ASSIGNED", "COLLECTED", "DELIVERED", "RECEIVED", "FAILED",
        }
        if state not in valid:
            raise ApiError(422, "INVALID_FILTER", f"state must be one of {sorted(valid)}")
        clauses.append("r.state = %s")
        params.append(state)
    if donation_id:
        clauses.append("r.donation_id = %s")
        params.append(donation_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with db.tx() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM reservations r JOIN donations d ON d.id = r.donation_id {where}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            RESERVATION_SELECT + f" {where} ORDER BY r.created_at DESC, r.id LIMIT %s OFFSET %s",
            params + [limit, offset],
        ).fetchall()
        items = []
        for r in rows:
            item = reservation_row(r)
            item["donation_available_kg"] = reservation_available_kg(conn, item["donation_id"])
            item["allowed_actions"] = _allowed_actions(user, item)
            items.append(item)
    return {"items": items, "total": int(total), "limit": limit, "offset": offset}


def _allowed_actions(user: CurrentUser, reservation: dict) -> list[str]:
    actions: list[str] = []
    state = reservation["state"]
    if user.role == "recipient" and reservation["recipient_org_id"] == user.organization_id:
        if state == "PROPOSED":
            actions = ["accept", "decline"]
    if user.role in {"coordinator", "admin"}:
        if state in ("PROPOSED", "ACCEPTED", "PICKUP_ASSIGNED"):
            actions.append("cancel")
    if user.role in {"transport", "coordinator", "admin"} and state == "ACCEPTED":
        actions.append("assign_pickup")
    return actions
