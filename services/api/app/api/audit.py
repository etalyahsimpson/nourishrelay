"""Append-only audit trail (coordinator/admin, filtered, redacted)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from .. import db
from ..dependencies import CurrentUser, require_roles
from ..schemas.report import AuditListResponse

router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=AuditListResponse)
def list_audit(
    actor_id: str | None = Query(default=None),
    organization_id: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    action: str | None = Query(default=None),
    frm: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_roles("coordinator", "admin")),
) -> dict:
    clauses: list[str] = []
    params: list = []
    if actor_id:
        clauses.append("a.actor_id = %s")
        params.append(actor_id)
    if organization_id:
        clauses.append("a.organization_id = %s")
        params.append(organization_id)
    if resource_type:
        clauses.append("a.resource_type = %s")
        params.append(resource_type.strip().lower())
    if action:
        clauses.append("a.action = %s")
        params.append(action.strip().lower())
    if frm:
        clauses.append("a.created_at >= %s")
        params.append(frm)
    if to:
        clauses.append("a.created_at < %s")
        params.append(to)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with db.tx() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM audit_records a {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT a.id, a.actor_id, u.display_name, u.role, a.organization_id,
                   a.action, a.resource_type, a.resource_id, a.outcome,
                   a.safe_summary, a.created_at
            FROM audit_records a LEFT JOIN users u ON u.id = a.actor_id
            {where}
            ORDER BY a.created_at DESC, a.id
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        ).fetchall()
    items = [
        {
            "id": str(r[0]),
            "actor_id": str(r[1]) if r[1] else None,
            "actor_display_name": r[2],
            "actor_role": r[3],
            "organization_id": str(r[4]) if r[4] else None,
            "action": r[5],
            "resource_type": r[6],
            "resource_id": str(r[7]) if r[7] else None,
            "outcome": r[8],
            "safe_summary": r[9] or {},
            "created_at": r[10],
        }
        for r in rows
    ]
    return {"items": items, "total": int(total), "limit": limit, "offset": offset}
