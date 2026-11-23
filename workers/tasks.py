"""Background tasks: proposal/donation expiry, heartbeat, simulated notifications.

Design invariants (spec §8.1, docs/DOMAIN_RULES.md):
- Every state change re-fetches the row FOR UPDATE and inspects CURRENT state
  inside the transaction — a worker retry or a duplicate beat run can never
  release stock twice (guarded UPDATEs + unique event constraints).
- PostgreSQL is authoritative; Redis only carries the schedule.
- Notifications are SIMULATED: safe event rows in the local demo database.
  No real email/SMS is ever sent, and none is claimed.
- Task functions carry their core logic in plain functions (`expire_proposals`,
  `expire_donations`, `worker_heartbeat`, `simulate_notifications`) so tests
  can invoke them deterministically without Redis, while Celery wrappers run
  the identical code in the real worker containers.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow direct invocation (python workers/tasks.py / pytest import) without
# the container PYTHONPATH: make both `app` and the `workers` package itself
# importable (the repository root is the package parent).
_REPO_ROOT = Path(__file__).resolve().parents[1]
_API_ROOT = _REPO_ROOT / "services" / "api"
for entry in (str(_API_ROOT), str(_REPO_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app import db  # noqa: E402
from app.domain.clock import utcnow  # noqa: E402
from app.domain.idempotency import record_audit, record_event  # noqa: E402
from app.domain.transitions import (  # noqa: E402
    close_donation_if_terminal,
    recompute_donation_status,
)
from workers.celery_app import celery_app  # noqa: E402

SYSTEM_ACTOR_KEY = "system"


def expire_proposals() -> dict:
    """Expire PROPOSED reservations past proposal_expires_at (releases stock —
    proposals never held any; the guard makes the transition idempotent)."""
    now = utcnow()
    expired: list[str] = []
    with db.tx() as conn:
        stale = conn.execute(
            """
            SELECT r.id, r.donation_id FROM reservations r
            WHERE r.state = 'PROPOSED' AND r.proposal_expires_at IS NOT NULL
              AND r.proposal_expires_at < %s
            ORDER BY r.proposal_expires_at
            FOR NO KEY UPDATE SKIP LOCKED
            """,
            (now,),
        ).fetchall()
        for reservation_id, donation_id in stale:
            # Lock the donation row first for the canonical lock order.
            conn.execute(
                "SELECT id FROM donations WHERE id = %s FOR UPDATE", (str(donation_id),)
            )
            row = conn.execute(
                """
                SELECT state, proposal_expires_at FROM reservations
                WHERE id = %s FOR UPDATE
                """,
                (str(reservation_id),),
            ).fetchone()
            if row is None or row[0] != "PROPOSED":
                continue  # already moved (accepted/declined/cancelled) — nothing to do
            if row[1] is None or row[1] >= now:
                continue  # re-check under lock: not actually expired
            conn.execute(
                """
                UPDATE reservations SET state = 'EXPIRED', released_at = %s,
                       updated_at = %s
                WHERE id = %s AND state = 'PROPOSED' AND released_at IS NULL
                """,
                (now, now, str(reservation_id)),
            )
            record_event(
                conn,
                aggregate_type="reservation",
                aggregate_id=str(reservation_id),
                actor_id=None,
                event_type="RESERVATION_EXPIRED",
                idempotency_key=f"expiry:{reservation_id}:{row[1].isoformat()}",
                request_hash=None,
                response_result={"id": str(reservation_id), "state": "EXPIRED"},
                payload={"reason": "proposal_expires_at passed"},
                occurred_at=now,
            )
            record_audit(
                conn,
                actor_id=None,
                organization_id=None,
                action="reservation.expire",
                resource_type="reservation",
                resource_id=str(reservation_id),
                outcome="expired",
                safe_summary={"proposal_expires_at": row[1].isoformat()},
                occurred_at=now,
            )
            recompute_donation_status(conn, str(donation_id), now=now)
            expired.append(str(reservation_id))
    return {"expired": expired, "count": len(expired)}


def expire_donations() -> dict:
    """Terminalize past-deadline donations whose reservations are all terminal
    (CLOSED when receipts exist, EXPIRED otherwise). Outstanding accepted
    reservations are honored: the donation stays open until they conclude."""
    now = utcnow()
    closed: list[str] = []
    with db.tx() as conn:
        stale = conn.execute(
            """
            SELECT d.id FROM donations d
            WHERE d.status IN ('AVAILABLE','PARTIALLY_RESERVED','FULLY_RESERVED')
              AND d.deadline < %s
            ORDER BY d.deadline
            FOR NO KEY UPDATE SKIP LOCKED
            """,
            (now,),
        ).fetchall()
        for (donation_id,) in stale:
            new_status = close_donation_if_terminal(conn, str(donation_id), now=now)
            if new_status:
                record_event(
                    conn,
                    aggregate_type="donation",
                    aggregate_id=str(donation_id),
                    actor_id=None,
                    event_type="DONATION_TERMINALIZED",
                    idempotency_key=f"terminal:{donation_id}:{new_status}",
                    request_hash=None,
                    response_result={"id": str(donation_id), "status": new_status},
                    payload={"status": new_status},
                    occurred_at=now,
                )
                record_audit(
                    conn,
                    actor_id=None,
                    organization_id=None,
                    action="donation.terminalize",
                    resource_type="donation",
                    resource_id=str(donation_id),
                    outcome=new_status.lower(),
                    safe_summary={"status": new_status},
                    occurred_at=now,
                )
                closed.append(str(donation_id))
    return {"terminalized": closed, "count": len(closed)}


def worker_heartbeat() -> dict:
    """Record a WORKER_TICK so /api/v1/ready can report worker liveness
    (best-effort; correctness never depends on it)."""
    now = utcnow()
    with db.tx() as conn:
        record_event(
            conn,
            aggregate_type="worker",
            aggregate_id="00000000-0000-4000-8000-00000000c0de",
            actor_id=None,
            event_type="WORKER_TICK",
            # minute-bucketed key: one tick per minute wins, duplicates no-op
            idempotency_key=f"tick:{now.strftime('%Y%m%dT%H%M')}",
            request_hash=None,
            response_result={"ok": True},
            payload={},
            occurred_at=now,
        )
    return {"ok": True}


def simulate_notifications() -> dict:
    """Simulated notification log for pickups happening within the next hour:
    writes a safe local event row ONLY. No email/SMS is sent (and none is
    claimed anywhere in the product or docs)."""
    from datetime import timedelta

    now = utcnow()
    horizon = now + timedelta(hours=1)
    notified: list[str] = []
    with db.tx() as conn:
        upcoming = conn.execute(
            """
            SELECT p.id, p.pickup_window_start FROM pickups p
            WHERE p.status = 'SCHEDULED'
              AND p.pickup_window_start BETWEEN %s AND %s
            ORDER BY p.pickup_window_start
            """,
            (now, horizon),
        ).fetchall()
        for pickup_id, window_start in upcoming:
            record_event(
                conn,
                aggregate_type="notification",
                aggregate_id=str(pickup_id),
                actor_id=None,
                event_type="NOTIFICATION_SIMULATED",
                idempotency_key=f"notify:{pickup_id}:{window_start.isoformat()}",
                request_hash=None,
                response_result={"simulated": True},
                payload={
                    "kind": "upcoming_pickup_reminder",
                    "pickup_window_start": window_start.isoformat(),
                    "note": "Simulated demo notification; no real channel used.",
                },
                occurred_at=now,
            )
            notified.append(str(pickup_id))
    return {"simulated_notifications": notified, "count": len(notified)}


# --- Celery task wrappers (identical logic, broker-managed execution) -------


@celery_app.task(name="workers.tasks.expire_proposals_task",
                 autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def expire_proposals_task() -> dict:
    return expire_proposals()


@celery_app.task(name="workers.tasks.expire_donations_task",
                 autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def expire_donations_task() -> dict:
    return expire_donations()


@celery_app.task(name="workers.tasks.worker_heartbeat_task")
def worker_heartbeat_task() -> dict:
    return worker_heartbeat()


@celery_app.task(name="workers.tasks.simulate_notifications_task")
def simulate_notifications_task() -> dict:
    return simulate_notifications()
