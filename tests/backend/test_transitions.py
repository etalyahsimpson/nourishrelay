"""Quantity lifecycle: cancellation release-once, failure before/after
collection, receipt rules, delivered-vs-received semantics, donation
terminalization."""

from __future__ import annotations

from datetime import timedelta

from conftest import DEMO
from helpers import create_published_donation, donation_payload, org_id_by_name, tomorrow_window


def _setup_accepted(api, db_conn, qty="25.000") -> tuple[str, str]:
    donation_id = create_published_donation(api, donation_payload(quantity_kg=qty))
    from datetime import datetime, timedelta, timezone

    expiry = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    api.login(DEMO["coordinator"])
    r = api.post("/api/v1/reservations", json={
        "donation_id": donation_id,
        "recipient_org_id": org_id_by_name(db_conn, "Northside Community Kitchen"),
        "quantity_kg": qty,
        "proposal_expires_at": expiry,
    }, key=f"setup-{donation_id[:8]}")
    reservation_id = r.json()["id"]
    api.login(DEMO["northside"])
    r = api.post(f"/api/v1/reservations/{reservation_id}/accept", json={"accepted": True},
                 key=f"setup-acc-{donation_id[:8]}")
    assert r.status_code == 200
    return donation_id, reservation_id


def _assign_pickup(api, donation_id: str, reservation_id: str) -> str:
    api.login(DEMO["transport"])
    start, end, _ = tomorrow_window()
    r = api.post("/api/v1/pickups", json={
        "reservation_id": reservation_id,
        "pickup_window_start": (start + timedelta(hours=1)).isoformat(),
        "pickup_window_end": end.isoformat(),
    }, key=f"pickup-{reservation_id[:8]}")
    assert r.status_code == 201, r.text[:300]
    return r.json()["id"]


def test_cancel_before_collection_releases_exactly_once(api, db_conn):
    donation_id, reservation_id = _setup_accepted(api, db_conn, "30.000")
    before = db_conn.execute(
        "SELECT status FROM donations WHERE id = %s", (donation_id,)
    ).fetchone()[0]
    assert before == "FULLY_RESERVED"  # 30 of 30 kg committed
    api.login(DEMO["coordinator"])
    r = api.post(f"/api/v1/reservations/{reservation_id}/cancel",
                 json={"reason": "test cancel"}, key="cancel-1")
    assert r.status_code == 200
    released = db_conn.execute(
        "SELECT released_at FROM reservations WHERE id = %s", (reservation_id,)
    ).fetchone()[0]
    assert released is not None
    r2 = api.post(f"/api/v1/reservations/{reservation_id}/cancel",
                  json={"reason": "second"}, key="cancel-2")
    assert r2.status_code == 409
    status = db_conn.execute(
        "SELECT status FROM donations WHERE id = %s", (donation_id,)
    ).fetchone()[0]
    assert status == "AVAILABLE"  # committed stock restored


def test_failure_before_collection_releases_stock(api, db_conn):
    donation_id, reservation_id = _setup_accepted(api, db_conn)
    pickup_id = _assign_pickup(api, donation_id, reservation_id)
    api.login(DEMO["transport"])
    r = api.post(f"/api/v1/pickups/{pickup_id}/events",
                 json={"event_type": "FAILED", "reason": "vehicle breakdown"},
                 key="fail-1")
    assert r.status_code == 200
    assert r.json()["reservation_state"] == "FAILED"
    row = db_conn.execute(
        "SELECT failure_stage, released_at FROM reservations WHERE id = %s",
        (reservation_id,),
    ).fetchone()
    assert row[0] == "BEFORE_COLLECTION"
    assert row[1] is not None
    status = db_conn.execute(
        "SELECT status FROM donations WHERE id = %s", (donation_id,)
    ).fetchone()[0]
    assert status == "AVAILABLE"


def test_failure_after_collection_does_not_release_stock(api, db_conn):
    donation_id, reservation_id = _setup_accepted(api, db_conn)
    pickup_id = _assign_pickup(api, donation_id, reservation_id)
    api.login(DEMO["transport"])
    r = api.post(f"/api/v1/pickups/{pickup_id}/events",
                 json={"event_type": "COLLECTED", "quantity_kg": "25.000"},
                 key="collect-1")
    assert r.status_code == 200
    r = api.post(f"/api/v1/pickups/{pickup_id}/events",
                 json={"event_type": "FAILED",
                       "reason": "cold-chain breach after collection"},
                 key="fail-after-1")
    assert r.status_code == 200
    assert r.json()["reservation_state"] == "FAILED"
    row = db_conn.execute(
        "SELECT failure_stage, released_at FROM reservations WHERE id = %s",
        (reservation_id,),
    ).fetchone()
    assert row[0] == "AFTER_COLLECTION"
    assert row[1] is None  # never released: collected food is not reoffered
    status = db_conn.execute(
        "SELECT status FROM donations WHERE id = %s", (donation_id,)
    ).fetchone()[0]
    # stock stays consumed (not reoffered); with nothing received the donation
    # terminalizes as EXPIRED (no verified receipt) even before the deadline
    assert status == "EXPIRED"


def test_collected_cannot_exceed_accepted_amount(api, db_conn):
    donation_id, reservation_id = _setup_accepted(api, db_conn)
    pickup_id = _assign_pickup(api, donation_id, reservation_id)
    api.login(DEMO["transport"])
    r = api.post(f"/api/v1/pickups/{pickup_id}/events",
                 json={"event_type": "COLLECTED", "quantity_kg": "30.000"},
                 key="over-1")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "QUANTITY_EXCEEDS_RESERVATION"


def test_receipt_rules(api, db_conn):
    donation_id, reservation_id = _setup_accepted(api, db_conn)
    pickup_id = _assign_pickup(api, donation_id, reservation_id)
    api.login(DEMO["transport"])
    api.post(f"/api/v1/pickups/{pickup_id}/events",
             json={"event_type": "COLLECTED", "quantity_kg": "25.000"}, key="rc-1")
    api.post(f"/api/v1/pickups/{pickup_id}/events",
             json={"event_type": "DELIVERED"}, key="rc-2")

    api.login(DEMO["northside"])
    # shortfall without a reason rejected
    r = api.post(f"/api/v1/pickups/{pickup_id}/receipt",
                 json={"received_quantity_kg": "20.000"}, key="rc-3")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "REASON_REQUIRED"
    # receipt exceeding collected rejected
    r = api.post(f"/api/v1/pickups/{pickup_id}/receipt",
                 json={"received_quantity_kg": "26.000"}, key="rc-4")
    assert r.status_code == 422
    # valid shortfall receipt with reason
    r = api.post(f"/api/v1/pickups/{pickup_id}/receipt",
                 json={"received_quantity_kg": "20.000",
                       "exception_reason": "5 kg damaged in transit"}, key="rc-5")
    assert r.status_code == 201
    assert r.json()["reservation_state"] == "RECEIVED"
    # duplicate receipt rejected (unique per pickup)
    r = api.post(f"/api/v1/pickups/{pickup_id}/receipt",
                 json={"received_quantity_kg": "20.000",
                       "exception_reason": "dup"}, key="rc-6")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ALREADY_RECEIVED"
    # donation closed after verified receipt
    status = db_conn.execute(
        "SELECT status FROM donations WHERE id = %s", (donation_id,)
    ).fetchone()[0]
    assert status == "CLOSED"


def test_receipt_requires_delivered_pickup(api, db_conn):
    donation_id, reservation_id = _setup_accepted(api, db_conn)
    pickup_id = _assign_pickup(api, donation_id, reservation_id)
    api.login(DEMO["northside"])
    r = api.post(f"/api/v1/pickups/{pickup_id}/receipt",
                 json={"received_quantity_kg": "25.000"}, key="rd-1")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "STATE_CONFLICT"


def test_delivered_is_not_received_until_receipt(api, db_conn):
    donation_id, reservation_id = _setup_accepted(api, db_conn)
    pickup_id = _assign_pickup(api, donation_id, reservation_id)
    api.login(DEMO["transport"])
    api.post(f"/api/v1/pickups/{pickup_id}/events",
             json={"event_type": "COLLECTED", "quantity_kg": "25.000"}, key="dv-1")
    api.post(f"/api/v1/pickups/{pickup_id}/events",
             json={"event_type": "DELIVERED"}, key="dv-2")
    state = db_conn.execute(
        "SELECT state FROM reservations WHERE id = %s", (reservation_id,)
    ).fetchone()[0]
    assert state == "DELIVERED"  # not RECEIVED
    row = db_conn.execute(
        "SELECT COUNT(*) FROM receipts WHERE pickup_id = %s", (pickup_id,)
    ).fetchone()[0]
    assert row == 0
    status = db_conn.execute(
        "SELECT status FROM donations WHERE id = %s", (donation_id,)
    ).fetchone()[0]
    assert status == "FULLY_RESERVED"  # still open until receipt confirms
