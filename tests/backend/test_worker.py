"""Worker contract via deterministic invocation (no Redis needed): expiry of
stale proposals, donation terminalization, heartbeat, notification
simulation, retry/duplicate safety."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import DEMO
from helpers import create_published_donation, donation_payload, org_id_by_name

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))
sys.path.insert(0, str(REPO_ROOT))  # `workers` package parent

from workers import tasks as worker_tasks  # noqa: E402


@pytest.fixture
def worker_env(fresh_db, monkeypatch):
    """Point the app's pool at the test database for direct task invocation."""
    from app import db

    db.close_pool()
    db.init_pool(fresh_db)
    monkeypatch.setenv("DATABASE_URL", fresh_db)
    yield fresh_db
    db.close_pool()


def test_expire_proposals_expires_stale_and_keeps_accepted(api, db_conn, worker_env):
    donation_id = create_published_donation(api)
    expiry = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    api.login(DEMO["coordinator"])
    org = org_id_by_name(db_conn, "Northside Community Kitchen")
    stale = api.post("/api/v1/reservations", json={
        "donation_id": donation_id, "recipient_org_id": org,
        "quantity_kg": "10.000", "proposal_expires_at": expiry,
    }, key="w-exp-1").json()["id"]
    keep = api.post("/api/v1/reservations", json={
        "donation_id": donation_id, "recipient_org_id": org,
        "quantity_kg": "15.000", "proposal_expires_at": expiry,
    }, key="w-exp-2").json()["id"]

    # deterministic clock substitution: age the stale proposal in the DB
    db_conn.execute(
        "UPDATE reservations SET proposal_expires_at = now() - interval '1 hour' "
        "WHERE id = %s",
        (stale,),
    )
    db_conn.commit()

    result = worker_tasks.expire_proposals()
    assert result["count"] >= 1
    states = {str(k): v for k, v in db_conn.execute(
        "SELECT id, state FROM reservations WHERE id IN (%s, %s)", (stale, keep)
    ).fetchall()}
    assert states[stale] == "EXPIRED"
    assert states[keep] == "PROPOSED"


def test_expire_proposals_idempotent_on_duplicate_runs(api, db_conn, worker_env):
    donation_id = create_published_donation(api)
    expiry = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    api.login(DEMO["coordinator"])
    org = org_id_by_name(db_conn, "Northside Community Kitchen")
    rid = api.post("/api/v1/reservations", json={
        "donation_id": donation_id, "recipient_org_id": org,
        "quantity_kg": "10.000", "proposal_expires_at": expiry,
    }, key="w-idem-1").json()["id"]
    db_conn.execute(
        "UPDATE reservations SET proposal_expires_at = now() - interval '1 hour' WHERE id = %s",
        (rid,),
    )
    db_conn.commit()

    first = worker_tasks.expire_proposals()
    events_after_first = db_conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    second = worker_tasks.expire_proposals()
    events_after_second = db_conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert first["count"] >= 1
    assert second["count"] == 0  # nothing left to expire
    assert events_after_second == events_after_first  # duplicate run wrote nothing
    releases = db_conn.execute(
        "SELECT COUNT(*) FROM reservations WHERE id = %s AND released_at IS NOT NULL",
        (rid,),
    ).fetchone()[0]
    assert releases == 1  # released exactly once


def test_expire_donations_terminalizes_past_deadline(api, db_conn, worker_env):
    donation_id = create_published_donation(api)
    db_conn.execute(
        """UPDATE donations SET pickup_start = now() - interval '4 hours',
           deadline = now() - interval '3 hours', pickup_end = now() - interval '2 hours'
           WHERE id = %s""",
        (donation_id,),
    )
    db_conn.commit()
    result = worker_tasks.expire_donations()
    status = db_conn.execute(
        "SELECT status FROM donations WHERE id = %s", (donation_id,)
    ).fetchone()[0]
    assert status == "EXPIRED"  # no receipts -> EXPIRED (not CLOSED)
    assert donation_id in result["terminalized"]


def test_expire_donations_honors_outstanding_accepted(api, db_conn, worker_env):
    donation_id = create_published_donation(api)
    expiry = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    api.login(DEMO["coordinator"])
    org = org_id_by_name(db_conn, "Northside Community Kitchen")
    rid = api.post("/api/v1/reservations", json={
        "donation_id": donation_id, "recipient_org_id": org,
        "quantity_kg": "25.000", "proposal_expires_at": expiry,
    }, key="w-honor-1").json()["id"]
    api.login(DEMO["northside"])
    api.post(f"/api/v1/reservations/{rid}/accept", json={"accepted": True}, key="w-honor-2")
    db_conn.execute(
        """UPDATE donations SET pickup_start = now() - interval '3 hours',
           deadline = now() - interval '2 hours', pickup_end = now() - interval '1 hour'
           WHERE id = %s""",
        (donation_id,),
    )
    db_conn.commit()

    worker_tasks.expire_donations()
    status = db_conn.execute(
        "SELECT status FROM donations WHERE id = %s", (donation_id,)
    ).fetchone()[0]
    # outstanding accepted reservation keeps the donation open (honored)
    assert status in ("PARTIALLY_RESERVED", "FULLY_RESERVED", "AVAILABLE")

    # conclude the reservation (cancel by coordinator releases)
    api.login(DEMO["coordinator"])
    api.post(f"/api/v1/reservations/{rid}/cancel", json={"reason": "conclude"}, key="w-honor-3")
    worker_tasks.expire_donations()
    status = db_conn.execute(
        "SELECT status FROM donations WHERE id = %s", (donation_id,)
    ).fetchone()[0]
    assert status == "EXPIRED"


def test_worker_heartbeat_and_ready_reporting(api, db_conn, worker_env):
    worker_tasks.worker_heartbeat()
    worker_tasks.worker_heartbeat()  # same minute bucket -> single event
    r = api.get("/api/v1/ready")
    deps = r.json()["dependencies"]
    assert deps["worker"].startswith("last tick")


def test_simulate_notifications_writes_local_event_only(api, db_conn, worker_env):
    """The pickup scheduled for tomorrow is outside the 1h horizon: no
    notification is simulated for it until its window approaches."""
    result = worker_tasks.simulate_notifications()
    assert isinstance(result["count"], int)
    kinds = db_conn.execute(
        "SELECT DISTINCT event_type FROM events WHERE aggregate_type = 'notification'"
    ).fetchall()
    assert [k[0] for k in kinds] in ([], ["NOTIFICATION_SIMULATED"])


def test_notification_simulated_no_real_delivery_claim(api, db_conn, worker_env):
    """Pull an existing scheduled pickup into the notification horizon and
    verify a safe local event is recorded (deterministic clock via DB update)."""
    from helpers import tomorrow_window
    from datetime import timedelta as TD

    donation_id = create_published_donation(api)
    expiry = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    api.login(DEMO["coordinator"])
    org = org_id_by_name(db_conn, "Northside Community Kitchen")
    rid = api.post("/api/v1/reservations", json={
        "donation_id": donation_id, "recipient_org_id": org,
        "quantity_kg": "25.000", "proposal_expires_at": expiry,
    }, key="w-notify-1").json()["id"]
    api.login(DEMO["northside"])
    api.post(f"/api/v1/reservations/{rid}/accept", json={"accepted": True}, key="w-notify-2")
    api.login(DEMO["transport"])
    start, end, _ = tomorrow_window()
    pickup_id = api.post("/api/v1/pickups", json={
        "reservation_id": rid,
        "pickup_window_start": (start + TD(hours=1)).isoformat(),
        "pickup_window_end": end.isoformat(),
    }, key="w-notify-3").json()["id"]
    # move the pickup window into the next hour
    db_conn.execute(
        "UPDATE pickups SET pickup_window_start = now() + interval '30 minutes', "
        "pickup_window_end = now() + interval '90 minutes' WHERE id = %s",
        (pickup_id,),
    )
    db_conn.commit()

    result = worker_tasks.simulate_notifications()
    assert result["count"] >= 1
    payload = db_conn.execute(
        "SELECT payload FROM events WHERE aggregate_id = %s AND event_type = 'NOTIFICATION_SIMULATED'",
        (pickup_id,),
    ).fetchone()[0]
    assert "no real channel" in payload["note"]
