"""Row -> response-dict builders shared by routers.

Quantities are always rendered as exact 3-decimal strings; datetimes as
aware UTC datetimes (FastAPI serializes RFC3339). No password hashes, no
cross-tenant fields.
"""

from __future__ import annotations

from decimal import Decimal

from .domain.transitions import committed_kg, norm_uuids

_COMMITTED_SQL = """
SELECT COALESCE(SUM(r.quantity_kg), 0) FROM reservations r
WHERE r.donation_id = %s
  AND (r.state IN ('ACCEPTED','PICKUP_ASSIGNED','COLLECTED','DELIVERED','RECEIVED')
       OR (r.state = 'FAILED' AND r.failure_stage = 'AFTER_COLLECTION'))
"""


def _dec_str(value) -> str:
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return str(d.quantize(Decimal("0.001")))


DONATION_SELECT = """
SELECT d.id, d.donor_org_id, d.created_by, d.category, d.quantity_kg,
       d.handling_tags, d.pickup_start, d.pickup_end, d.deadline, d.status,
       d.location_label, d.notes, d.version, d.created_at, d.updated_at,
       d.published_at, o.name AS donor_org_name, o.service_area AS donor_service_area,
       COALESCE((
           SELECT SUM(r.quantity_kg) FROM reservations r
           WHERE r.donation_id = d.id
             AND (r.state IN ('ACCEPTED','PICKUP_ASSIGNED','COLLECTED','DELIVERED','RECEIVED')
                  OR (r.state = 'FAILED' AND r.failure_stage = 'AFTER_COLLECTION'))
       ), 0) AS committed_kg
FROM donations d
JOIN organizations o ON o.id = d.donor_org_id
"""

_DONATION_KEYS = [
    "id", "donor_org_id", "created_by", "category", "quantity_kg",
    "handling_tags", "pickup_start", "pickup_end", "deadline", "status",
    "location_label", "notes", "version", "created_at", "updated_at",
    "published_at", "donor_org_name", "donor_service_area", "committed_kg",
]


def donation_row(conn, row):
    d = norm_uuids(dict(zip(_DONATION_KEYS, row)))
    qty = Decimal(str(d["quantity_kg"]))
    committed = Decimal(str(d.pop("committed_kg")))
    d["quantity_kg"] = _dec_str(qty)
    d["committed_kg"] = _dec_str(committed)
    d["available_kg"] = _dec_str(max(qty - committed, Decimal("0")))
    return d


def donation_summary(conn, row) -> dict:
    d = donation_row(conn, row)
    return d


RESERVATION_SELECT = """
SELECT r.id, r.donation_id, r.recipient_org_id, r.proposed_by, r.quantity_kg,
       r.state, r.failure_stage, r.proposal_expires_at, r.accepted_at,
       r.released_at, r.decline_reason, r.cancel_reason, r.failure_reason,
       r.created_at, r.updated_at,
       d.category AS donation_category, d.status AS donation_status,
       d.pickup_start, d.pickup_end, d.deadline,
       od.name AS donor_org_name, od.id AS donor_org_id2,
       rc.name AS recipient_org_name,
       COALESCE((
           SELECT SUM(r2.quantity_kg) FROM reservations r2
           WHERE r2.donation_id = r.donation_id
             AND (r2.state IN ('ACCEPTED','PICKUP_ASSIGNED','COLLECTED','DELIVERED','RECEIVED')
                  OR (r2.state = 'FAILED' AND r2.failure_stage = 'AFTER_COLLECTION'))
       ), 0) AS committed_kg,
       d.quantity_kg AS donation_quantity_kg
FROM reservations r
JOIN donations d ON d.id = r.donation_id
JOIN organizations od ON od.id = d.donor_org_id
JOIN organizations rc ON rc.id = r.recipient_org_id
"""

_RESERVATION_KEYS = [
    "id", "donation_id", "recipient_org_id", "proposed_by", "quantity_kg",
    "state", "failure_stage", "proposal_expires_at", "accepted_at",
    "released_at", "decline_reason", "cancel_reason", "failure_reason",
    "created_at", "updated_at", "donation_category", "donation_status",
    "pickup_start", "pickup_end", "deadline", "donor_org_name", "donor_org_id2",
    "recipient_org_name", "committed_kg", "donation_quantity_kg",
]


def reservation_row(row) -> dict:
    d = norm_uuids(dict(zip(_RESERVATION_KEYS, row)))
    d.pop("donor_org_id2")
    d.pop("committed_kg")
    d.pop("donation_quantity_kg")
    d["quantity_kg"] = _dec_str(d["quantity_kg"])
    return d


def reservation_available_kg(conn, donation_id: str) -> str:
    row = conn.execute(_COMMITTED_SQL, (donation_id,)).fetchone()
    qty = conn.execute(
        "SELECT quantity_kg FROM donations WHERE id = %s", (donation_id,)
    ).fetchone()
    return _dec_str(max(Decimal(str(qty[0])) - Decimal(str(row[0])), Decimal("0")))


PICKUP_SELECT = """
SELECT p.id, p.reservation_id, p.assigned_transport_org_id,
       p.pickup_window_start, p.pickup_window_end, p.status,
       p.collected_quantity_kg, p.collected_at, p.delivered_at,
       p.failure_reason, p.created_at, p.updated_at,
       r.state AS reservation_state, r.recipient_org_id, r.quantity_kg,
       d.category AS donation_category, d.donor_org_id,
       od.name AS donor_org_name, rc.name AS recipient_org_name,
       tr.name AS transport_org_name
FROM pickups p
JOIN reservations r ON r.id = p.reservation_id
JOIN donations d ON d.id = r.donation_id
JOIN organizations od ON od.id = d.donor_org_id
JOIN organizations rc ON rc.id = r.recipient_org_id
LEFT JOIN organizations tr ON tr.id = p.assigned_transport_org_id
"""

_PICKUP_KEYS = [
    "id", "reservation_id", "assigned_transport_org_id",
    "pickup_window_start", "pickup_window_end", "status",
    "collected_quantity_kg", "collected_at", "delivered_at",
    "failure_reason", "created_at", "updated_at",
    "reservation_state", "recipient_org_id", "quantity_kg",
    "donation_category", "donor_org_id", "donor_org_name",
    "recipient_org_name", "transport_org_name",
]


def pickup_row(row, receipt_row=None) -> dict:
    d = norm_uuids(dict(zip(_PICKUP_KEYS, row)))
    d["quantity_kg"] = _dec_str(d.pop("quantity_kg"))
    d.pop("donor_org_id")
    d["collected_quantity_kg"] = _dec_str(d["collected_quantity_kg"]) if d["collected_quantity_kg"] is not None else None
    d["receipt"] = receipt_summary(receipt_row) if receipt_row else None
    return d


def receipt_summary(row) -> dict | None:
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "pickup_id": str(row[1]),
        "recipient_user_id": str(row[2]),
        "received_quantity_kg": _dec_str(row[3]),
        "exception_reason": row[4],
        "confirmed_at": row[5],
    }


RECEIPT_SELECT = """
SELECT rc.id, rc.pickup_id, rc.recipient_user_id, rc.received_quantity_kg,
       rc.exception_reason, rc.confirmed_at
FROM receipts rc
"""
