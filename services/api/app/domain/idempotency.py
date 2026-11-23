"""Idempotency and event recording.

Contract (spec §4.3): mutation endpoints require an `Idempotency-Key` header.
For a given (actor, event_type, key):
- same request fingerprint  -> replay the stored response, no second mutation
- different fingerprint      -> 409 IDEMPOTENCY_KEY_REUSE

Storage is the `events` table in PostgreSQL with
UNIQUE(actor_id, event_type, idempotency_key) (plus a partial unique index for
system/worker events where actor_id IS NULL), so retries across worker
restarts are safe. A worker failure can never make a committed reservation
disappear; it can never double-apply either.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from ..errors import ApiError
from ..security import fingerprint_request


def require_idempotency_key(header_value: Optional[str]) -> str:
    key = (header_value or "").strip()
    if not key:
        raise ApiError(
            400,
            "IDEMPOTENCY_KEY_REQUIRED",
            "Send a unique Idempotency-Key header for this action.",
        )
    if len(key) > 200:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key too long.")
    return key


def find_event(
    conn, actor_id: Optional[str], event_type: str, key: str
) -> Optional[dict]:
    """Return an existing recorded event, or None."""
    row = conn.execute(
        """
        SELECT id, actor_id, event_type, idempotency_key, request_hash,
               response_json, occurred_at
        FROM events
        WHERE actor_id IS NOT DISTINCT FROM %s
          AND event_type = %s
          AND idempotency_key = %s
        """,
        (actor_id, event_type, key),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "actor_id": str(row[1]) if row[1] else None,
        "event_type": row[2],
        "idempotency_key": row[3],
        "request_hash": row[4],
        "response_json": row[5],
        "occurred_at": row[6],
    }


def check_replay(
    conn, actor_id: Optional[str], event_type: str, key: str, payload: Any
) -> Optional[dict]:
    """Raise on key reuse with a different payload; return replayed result.

    Returns the decoded result dict when this exact request was already
    processed, or None when the caller should proceed with the mutation.
    """
    existing = find_event(conn, actor_id, event_type, key)
    if existing is None:
        return None
    current_hash = fingerprint_request(payload)
    if existing["request_hash"] != current_hash:
        raise ApiError(
            409,
            "IDEMPOTENCY_KEY_REUSE",
            "This Idempotency-Key was already used with a different request body.",
        )
    stored = existing["response_json"] or {}
    return stored.get("result")


def record_event(
    conn,
    *,
    aggregate_type: str,
    aggregate_id: str,
    actor_id: Optional[str],
    event_type: str,
    idempotency_key: str,
    request_hash: Optional[str],
    response_result: dict,
    payload: dict | None = None,
    occurred_at=None,
) -> None:
    """Insert an event row; idempotent via the unique constraints.

    If the exact (actor, event_type, key) already exists (concurrent double
    submit), the insert is skipped — the earlier committed result wins.
    """
    conn.execute(
        """
        INSERT INTO events (id, aggregate_type, aggregate_id, actor_id, event_type,
                             idempotency_key, request_hash, response_json, payload, occurred_at)
        VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now()))
        ON CONFLICT DO NOTHING
        """,
        (
            aggregate_type,
            aggregate_id,
            actor_id,
            event_type,
            idempotency_key,
            request_hash,
            json.dumps({"result": response_result}, default=str),
            json.dumps(payload or {}, default=str),
            occurred_at,
        ),
    )


def record_audit(
    conn,
    *,
    actor_id: Optional[str],
    organization_id: Optional[str],
    action: str,
    resource_type: str,
    resource_id: Optional[str],
    outcome: str,
    safe_summary: dict | None = None,
    occurred_at=None,
) -> None:
    """Append-only audit row inside the caller's transaction. No secrets."""
    conn.execute(
        """
        INSERT INTO audit_records (id, actor_id, organization_id, action,
                                   resource_type, resource_id, outcome,
                                   safe_summary, created_at)
        VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now()))
        """,
        (
            actor_id,
            organization_id,
            action,
            resource_type,
            resource_id,
            outcome,
            json.dumps(safe_summary or {}, default=str),
            occurred_at,
        ),
    )


def load_events_for_aggregate(conn, aggregate_type: str, aggregate_id: str) -> list[dict]:
    """Safe event history for a donation/reservation/pickup (UI timelines)."""
    rows = conn.execute(
        """
        SELECT e.id, e.actor_id, u.display_name AS actor_name, e.event_type,
               e.payload, e.occurred_at
        FROM events e LEFT JOIN users u ON u.id = e.actor_id
        WHERE e.aggregate_type = %s AND e.aggregate_id = %s
        ORDER BY e.occurred_at ASC
        """,
        (aggregate_type, aggregate_id),
    ).fetchall()
    return [
        {
            "id": str(r[0]),
            "actor_id": str(r[1]) if r[1] else None,
            "actor_name": r[2],
            "event_type": r[3],
            "payload": r[4] or {},
            "occurred_at": r[5],
        }
        for r in rows
    ]
