"""Organizations and recipient profiles (coordinator/admin platform views)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query

from .. import db
from ..dependencies import CurrentUser, require_roles
from ..domain.clock import local_date_of, utcnow
from ..domain.queries import one as qone
from ..errors import ApiError
from ..schemas.auth import OrganizationListResponse, RecipientCapacitySummary, RecipientListResponse, RecipientProfileSummary
from ..views import _dec_str  # canonical quantity formatting

router = APIRouter(tags=["organizations"])


@router.get("/organizations", response_model=OrganizationListResponse)
def list_organizations(
    kind: str | None = Query(default=None, description="donor|recipient|transport|platform"),
    verified: bool | None = Query(default=None),
    user: CurrentUser = Depends(require_roles("coordinator", "admin", "analyst")),
) -> dict:
    clauses = ["TRUE"]
    params: list = []
    if kind:
        if kind not in {"donor", "recipient", "transport", "platform"}:
            raise ApiError(422, "INVALID_FILTER", "kind must be a valid organization kind")
        clauses.append("o.kind = %s")
        params.append(kind)
    if verified is not None:
        clauses.append("o.verified = %s")
        params.append(verified)
    with db.tx() as conn:
        rows = conn.execute(
            f"""
            SELECT o.id, o.name, o.kind, o.verified, o.service_area, o.created_at
            FROM organizations o WHERE {' AND '.join(clauses)}
            ORDER BY o.created_at, o.id
            """,
            params,
        ).fetchall()
    items = [
        {
            "id": str(r[0]), "name": r[1], "kind": r[2], "verified": r[3],
            "service_area": r[4], "created_at": r[5],
        }
        for r in rows
    ]
    return {"items": items, "total": len(items)}


@router.get("/recipients", response_model=RecipientListResponse)
def list_recipients(
    user: CurrentUser = Depends(require_roles("coordinator", "admin", "analyst")),
) -> dict:
    now = utcnow()
    with db.tx() as conn:
        rows = conn.execute(
            """
            SELECT o.id, o.name, o.verified, o.service_area,
                   rp.accepted_categories, rp.max_kg_per_day,
                   rp.handling_acknowledged, rp.receiving_start, rp.receiving_end,
                   rp.timezone, rp.active
            FROM organizations o
            JOIN recipient_profiles rp ON rp.organization_id = o.id
            ORDER BY o.name
            """
        ).fetchall()
        items = []
        for r in rows:
            org_id, tz = str(r[0]), r[9]
            target_date = local_date_of(now, tz or "UTC")
            usage = qone(
                conn,
                "matching.sql",
                "recipient_day_capacity_usage",
                {"recipient_org_id": org_id, "tz": tz or "UTC", "receiving_date": target_date},
            )
            max_day = r[5]
            committed = _dec_str(usage[0])
            if max_day is None:
                remaining, status = None, "UNKNOWN"
            else:
                rem = Decimal(str(max_day)) - Decimal(str(usage[0]))
                remaining, status = _dec_str(rem), ("OK" if rem > 0 else "EXHAUSTED")
            items.append(
                RecipientProfileSummary(
                    organization_id=org_id,
                    name=r[1],
                    verified=r[2],
                    active=r[10],
                    accepted_categories=list(r[4] or []),
                    handling_acknowledged=list(r[6] or []),
                    receiving_start=r[7].strftime("%H:%M"),
                    receiving_end=r[8].strftime("%H:%M"),
                    timezone=tz or "UTC",
                    service_area=r[3],
                    capacity=RecipientCapacitySummary(
                        date=target_date.isoformat(),
                        max_kg_per_day=_dec_str(max_day) if max_day is not None else None,
                        committed_kg=committed,
                        remaining_kg=remaining,
                        capacity_status=status,
                    ),
                ).model_dump()
            )
    return {"items": items, "total": len(items), "as_of": now}
