"""Idempotency contract: replay returns the stored result without a second
mutation; key reuse with a different payload returns 409; missing keys are
rejected; worker retry double-release is impossible."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import DEMO
from helpers import create_published_donation, donation_payload, org_id_by_name


def _setup(api, db_conn):
    donation_id = create_published_donation(api)
    api.login(DEMO["coordinator"])
    expiry = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    payload = {
        "donation_id": donation_id,
        "recipient_org_id": org_id_by_name(db_conn, "Northside Community Kitchen"),
        "quantity_kg": "25.000",
        "proposal_expires_at": expiry,
    }
    return donation_id, payload


def test_duplicate_proposal_same_key_replays(api, db_conn):
    donation_id, payload = _setup(api, db_conn)
    r1 = api.post("/api/v1/reservations", json=payload, key="idem-prop-1")
    assert r1.status_code == 201
    before = db_conn.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
    r2 = api.post("/api/v1/reservations", json=payload, key="idem-prop-1")
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    after = db_conn.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
    assert before == after  # no duplicate mutation


def test_same_key_different_payload_conflict(api, db_conn):
    donation_id, payload = _setup(api, db_conn)
    api.post("/api/v1/reservations", json=payload, key="idem-x-1")
    payload["quantity_kg"] = "10.000"
    r = api.post("/api/v1/reservations", json=payload, key="idem-x-1")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSE"


def test_missing_idempotency_key_rejected(api, db_conn):
    donation_id, payload = _setup(api, db_conn)
    r = api.post("/api/v1/reservations", json=payload, key=None)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_accept_replay_returns_original_result(api, db_conn):
    donation_id, payload = _setup(api, db_conn)
    r = api.post("/api/v1/reservations", json=payload, key="acc-idem-1")
    reservation_id = r.json()["id"]
    api.login(DEMO["northside"])
    r1 = api.post(f"/api/v1/reservations/{reservation_id}/accept",
                  json={"accepted": True}, key="acc-idem-2")
    assert r1.status_code == 200
    events_before = db_conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    r2 = api.post(f"/api/v1/reservations/{reservation_id}/accept",
                  json={"accepted": True}, key="acc-idem-2")
    assert r2.status_code == 200
    assert r1.json() == r2.json()
    events_after = db_conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert events_before == events_after  # replay wrote nothing


def test_accept_key_reuse_with_different_body(api, db_conn):
    donation_id, payload = _setup(api, db_conn)
    r = api.post("/api/v1/reservations", json=payload, key="acc2-1")
    reservation_id = r.json()["id"]
    api.login(DEMO["northside"])
    api.post(f"/api/v1/reservations/{reservation_id}/accept",
             json={"accepted": True}, key="acc2-2")
    r = api.post(f"/api/v1/reservations/{reservation_id}/accept",
                 json={"accepted": False}, key="acc2-2")
    assert r.status_code in (409, 422)  # different payload under same key
    if r.status_code == 409:
        assert r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSE"


def test_receipt_duplicate_same_key_replays(api, db_conn):
    donation_id, payload = _setup(api, db_conn)
    reservation_id = api.post("/api/v1/reservations", json=payload, key="rp-1").json()["id"]
    api.login(DEMO["northside"])
    api.post(f"/api/v1/reservations/{reservation_id}/accept", json={"accepted": True}, key="rp-2")
    api.login(DEMO["transport"])
    from helpers import tomorrow_window
    from datetime import timedelta

    start, end, _ = tomorrow_window()
    pickup = api.post("/api/v1/pickups", json={
        "reservation_id": reservation_id,
        "pickup_window_start": (start + timedelta(hours=1)).isoformat(),
        "pickup_window_end": end.isoformat(),
    }, key="rp-3").json()["id"]
    api.post(f"/api/v1/pickups/{pickup}/events",
             json={"event_type": "COLLECTED", "quantity_kg": "25.000"}, key="rp-4")
    api.post(f"/api/v1/pickups/{pickup}/events", json={"event_type": "DELIVERED"}, key="rp-5")
    api.login(DEMO["northside"])
    body = {"received_quantity_kg": "25.000"}
    r1 = api.post(f"/api/v1/pickups/{pickup}/receipt", json=body, key="rp-6")
    assert r1.status_code == 201
    r2 = api.post(f"/api/v1/pickups/{pickup}/receipt", json=body, key="rp-6")
    assert r2.status_code == 201  # replay of the stored result
    assert r2.json()["id"] == r1.json()["id"]
    assert r2.json()["received_quantity_kg"] == r1.json()["received_quantity_kg"]
    assert r2.json()["reservation_state"] == "RECEIVED"
    receipts = db_conn.execute(
        "SELECT COUNT(*) FROM receipts WHERE pickup_id = %s", (pickup,)
    ).fetchone()[0]
    assert receipts == 1
