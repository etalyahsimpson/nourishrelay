"""Operations reporting: JSON and CSV (authorized scopes only)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from .. import db
from ..dependencies import CurrentUser, get_current_user
from ..domain.clock import utcnow
from ..domain import reporting
from ..errors import ApiError
from ..schemas.report import OperationsReport

router = APIRouter(prefix="/reports", tags=["reports"])


def _resolve_scope(user: CurrentUser, organization_id: str | None) -> tuple[str | None, str | None]:
    """Coordinator/analyst/admin may report globally or per organization; org
    users are pinned to their own organization (server-side)."""
    if user.role in {"coordinator", "analyst", "admin"}:
        if organization_id:
            return organization_id, _org_name(organization_id)
        return None, None
    if user.role in {"donor", "recipient", "transport"}:
        if organization_id and organization_id != user.organization_id:
            raise ApiError(403, "FORBIDDEN", "Organization users can only report on their own organization.")
        return user.organization_id, _org_name(user.organization_id)
    raise ApiError(403, "FORBIDDEN", "Role cannot read reports.")


def _org_name(org_id: str) -> str | None:
    with db.tx() as conn:
        row = conn.execute("SELECT name FROM organizations WHERE id = %s", (org_id,)).fetchone()
    return row[0] if row else None


@router.get("/operations", response_model=OperationsReport)
def operations(
    frm: datetime = Query(alias="from", description="Window start (UTC, inclusive)"),
    to: datetime = Query(description="Window end (UTC, exclusive)"),
    organization_id: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    org_id, org_name = _resolve_scope(user, organization_id)
    now = utcnow()
    try:
        with db.tx() as conn:
            return reporting.operations_report(
                conn, from_dt=frm, to_dt=to, org_id=org_id, org_name=org_name, now=now
            )
    except ValueError as exc:
        raise ApiError(422, "INVALID_WINDOW", str(exc))


@router.get("/operations.csv")
def operations_csv(
    frm: datetime = Query(alias="from"),
    to: datetime = Query(description="Window end (UTC, exclusive)"),
    organization_id: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
) -> PlainTextResponse:
    org_id, org_name = _resolve_scope(user, organization_id)
    now = utcnow()
    try:
        with db.tx() as conn:
            report = reporting.operations_report(
                conn, from_dt=frm, to_dt=to, org_id=org_id, org_name=org_name, now=now
            )
    except ValueError as exc:
        raise ApiError(422, "INVALID_WINDOW", str(exc))
    csv_text = reporting.operations_csv(report)
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={
            "content-disposition": 'attachment; filename="nourishrelay-operations.csv"',
            "x-content-type-options": "nosniff",
        },
    )
