"""Health and readiness endpoints (no auth)."""

from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel

from .. import db
from ..config import get_settings

router = APIRouter(tags=["health"])


class HealthBody(BaseModel):
    status: str
    service: str


class ReadyBody(BaseModel):
    status: str
    service: str
    dependencies: dict


@router.get("/health", response_model=HealthBody)
def health() -> dict:
    """Liveness: the API process responds at all."""
    return {"status": "ok", "service": "nourishrelay-api"}


@router.get("/ready", response_model=ReadyBody)
def ready(response: Response) -> dict:
    """Readiness: PostgreSQL reachable; Redis/worker reported separately."""
    deps: dict[str, str] = {}
    ok = True
    try:
        db.ping()
        deps["postgres"] = "ok"
    except Exception:
        deps["postgres"] = "unreachable"
        ok = False
    settings = get_settings()
    if settings.redis_url:
        try:
            import redis as redis_lib

            client = redis_lib.Redis.from_url(settings.redis_url, socket_timeout=2)
            client.ping()
            client.close()
            deps["redis"] = "ok"
        except Exception:
            deps["redis"] = "unavailable"
            ok = ok  # broker outage degrades expiry timing, not correctness
    else:
        deps["redis"] = "not configured"
    try:
        with db.tx() as conn:
            row = conn.execute(
                """
                SELECT occurred_at FROM events
                WHERE aggregate_type = 'worker' AND event_type = 'WORKER_TICK'
                ORDER BY occurred_at DESC LIMIT 1
                """
            ).fetchone()
        deps["worker"] = f"last tick {row[0].isoformat()}" if row else "no tick recorded yet"
    except Exception:
        deps["worker"] = "unknown"
    status = "ok" if ok else "unavailable"
    if not ok:
        response.status_code = 503
    return {"status": status, "service": "nourishrelay-api", "dependencies": deps}
