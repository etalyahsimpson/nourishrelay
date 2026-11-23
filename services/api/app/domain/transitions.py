"""State machines, stock derivation and lifecycle transitions.

Reservation lifecycle:
    PROPOSED -> ACCEPTED -> PICKUP_ASSIGNED -> COLLECTED -> DELIVERED -> RECEIVED
    terminal: DECLINED, CANCELLED, EXPIRED, FAILED (with failure_stage)

Donation lifecycle:
    DRAFT -> AVAILABLE -> PARTIALLY_RESERVED / FULLY_RESERVED -> CLOSED
    or EXPIRED / WITHDRAWN when eligible

committed_kg counts reservation quantity in ACCEPTED, PICKUP_ASSIGNED,
COLLECTED, DELIVERED, RECEIVED and FAILED(failure_stage=AFTER_COLLECTION).
PROPOSED/DECLINED/CANCELLED/EXPIRED and FAILED(BEFORE_COLLECTION) do not count.
available_kg = quantity_kg - committed_kg, never below zero.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from ..errors import ApiError
from .clock import ensure_utc


def norm_uuids(data: dict) -> dict:
    """Normalize psycopg-returned uuid.UUID values to plain strings so
    identity comparisons (str org/user ids) are reliable everywhere."""
    return {
        k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in data.items()
    }


# States that hold (or permanently consumed) donor stock.
STOCK_HELD_STATES = ("ACCEPTED", "PICKUP_ASSIGNED", "COLLECTED", "DELIVERED", "RECEIVED")

# States counted toward a recipient's daily receiving capacity.
CAPACITY_STATES = ("ACCEPTED", "PICKUP_ASSIGNED", "COLLECTED", "DELIVERED", "RECEIVED")

RESERVATION_TERMINAL = ("DECLINED", "CANCELLED", "EXPIRED", "FAILED", "RECEIVED")

DONATION_ACTIVE = ("AVAILABLE", "PARTIALLY_RESERVED", "FULLY_RESERVED")


def reservation_holds_stock(state: str, failure_stage: str | None) -> bool:
    if state == "FAILED":
        # Food already collected is never automatically reoffered.
        return failure_stage == "AFTER_COLLECTION"
    return state in STOCK_HELD_STATES


def committed_kg(conn, donation_id: str) -> Decimal:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(r.quantity_kg), 0) FROM reservations r
        WHERE r.donation_id = %s
          AND (r.state = ANY(%s) OR (r.state = 'FAILED' AND r.failure_stage = 'AFTER_COLLECTION'))
        """,
        (donation_id, list(STOCK_HELD_STATES)),
    ).fetchone()
    return Decimal(row[0])


def available_kg(conn, donation_row: tuple) -> Decimal:
    """donation_row: (id, quantity_kg) or dict-like with those fields."""
    if isinstance(donation_row, dict):
        d_id, qty = donation_row["id"], donation_row["quantity_kg"]
    else:
        d_id, qty = donation_row[0], donation_row[1]
    return max(Decimal(qty) - committed_kg(conn, str(d_id)), Decimal("0"))


def recompute_donation_status(conn, donation_id: str, *, now) -> str:
    """Derive AVAILABLE / PARTIALLY_RESERVED / FULLY_RESERVED; leave terminal
    donation states (CLOSED/EXPIRED/WITHDRAWN) untouched."""
    row = conn.execute(
        "SELECT status, quantity_kg FROM donations WHERE id = %s FOR UPDATE",
        (donation_id,),
    ).fetchone()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Donation not found.")
    status, qty = row
    if status in ("DRAFT", "CLOSED", "EXPIRED", "WITHDRAWN"):
        return status
    committed = committed_kg(conn, donation_id)
    if committed <= 0:
        new_status = "AVAILABLE"
    elif committed < Decimal(qty):
        new_status = "PARTIALLY_RESERVED"
    else:
        new_status = "FULLY_RESERVED"
    if new_status != status:
        conn.execute(
            "UPDATE donations SET status = %s, updated_at = %s WHERE id = %s",
            (new_status, now, donation_id),
        )
    return new_status


# --- Guarded transition helpers -------------------------------------------


def transition_donation(conn, donation_id: str, from_statuses: tuple[str, ...], to_status: str, *, now, actor_label: str) -> None:
    row = conn.execute(
        "SELECT status FROM donations WHERE id = %s FOR UPDATE",
        (donation_id,),
    ).fetchone()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Donation not found.")
    if row[0] not in from_statuses:
        raise ApiError(
            409,
            "STATE_CONFLICT",
            f"Donation cannot move from {row[0]} to {to_status} (attempt by {actor_label}).",
        )
    conn.execute(
        "UPDATE donations SET status = %s, updated_at = %s WHERE id = %s",
        (to_status, now, donation_id),
    )


def all_reservations_terminal(conn, donation_id: str) -> bool:
    row = conn.execute(
        """
        SELECT COUNT(*) FROM reservations
        WHERE donation_id = %s AND state <> ALL(%s)
        """,
        (donation_id, list(RESERVATION_TERMINAL)),
    ).fetchone()
    return row[0] == 0


def any_receipt_exists(conn, donation_id: str) -> bool:
    row = conn.execute(
        """
        SELECT COUNT(*) FROM receipts
        JOIN pickups ON pickups.id = receipts.pickup_id
        JOIN reservations ON reservations.id = pickups.reservation_id
        WHERE reservations.donation_id = %s
        """,
        (donation_id,),
    ).fetchone()
    return row[0] > 0


def close_donation_if_terminal(conn, donation_id: str, *, now) -> str | None:
    """Terminalize a donation whose reservations are all terminal, but only
    when either the deadline has passed (remaining stock can no longer be
    offered) or every kilogram is in a terminal consumed/received state.

    CLOSED when at least one receipt was confirmed, EXPIRED otherwise.
    Returns the new status, or None when not (yet) closable. Safe to re-run.
    """
    row = conn.execute(
        "SELECT status, deadline, quantity_kg FROM donations WHERE id = %s FOR UPDATE",
        (donation_id,),
    ).fetchone()
    if row is None:
        return None
    status, deadline, quantity = row
    if status not in DONATION_ACTIVE:
        return None
    if not all_reservations_terminal(conn, donation_id):
        return None
    committed = committed_kg(conn, donation_id)
    deadline_passed = ensure_utc(deadline) <= now
    fully_consumed = committed >= Decimal(str(quantity))
    if not (deadline_passed or fully_consumed):
        return None  # still offerable stock before deadline: stay open
    new_status = "CLOSED" if any_receipt_exists(conn, donation_id) else "EXPIRED"
    conn.execute(
        "UPDATE donations SET status = %s, updated_at = %s WHERE id = %s",
        (new_status, now, donation_id),
    )
    return new_status


def reservation_guarded_update(
    conn,
    reservation_id: str,
    expected_states: tuple[str, ...],
    new_state: str,
    *,
    now,
    extra_sets: dict[str, object] = {},
) -> dict:
    """Update the reservation state only from expected_states, under row lock.

    Raises 409 STATE_CONFLICT when the reservation already moved — the honest
    answer to a stale/late acceptance, cancellation or expiry race.
    """
    sets = " ".join([f", {k} = %s" for k in extra_sets])
    sql = f"""
        UPDATE reservations
        SET state = %s, updated_at = %s{sets}
        WHERE id = %s AND state = ANY(%s)
        RETURNING id, state, quantity_kg, donation_id, recipient_org_id
    """
    row = conn.execute(
        sql,
        [new_state, now] + list(extra_sets.values()) + [reservation_id, list(expected_states)],
    ).fetchone()
    if row is None:
        current = conn.execute(
            "SELECT state FROM reservations WHERE id = %s", (reservation_id,)
        ).fetchone()
        if current is None:
            raise ApiError(404, "NOT_FOUND", "Reservation not found.")
        raise ApiError(
            409,
            "STATE_CONFLICT",
            f"Reservation already moved to {current[0]}; cannot apply {new_state}.",
        )
    return {
        "id": str(row[0]),
        "state": row[1],
        "quantity_kg": row[2],
        "donation_id": str(row[3]),
        "recipient_org_id": str(row[4]),
    }
