"""Security matrix: cross-tenant opacity, role enforcement, coordinator
impersonation, audit access, no secrets in errors, envelope shape."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import DEMO
from helpers import create_published_donation, donation_payload, org_id_by_name, tomorrow_window
from datetime import timedelta as TD


def _setup_proposal(api, db_conn):
    donation_id = create_published_donation(api)
    expiry = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    api.login(DEMO["coordinator"])
    org = org_id_by_name(db_conn, "Northside Community Kitchen")
    r = api.post("/api/v1/reservations", json={
        "donation_id": donation_id, "recipient_org_id": org,
        "quantity_kg": "25.000", "proposal_expires_at": expiry,
    }, key="sec-1")
    return donation_id, r.json()["id"]


def test_proposed_is_not_committed_stock(api, db_conn):
    donation_id, reservation_id = _setup_proposal(api, db_conn)
    row = db_conn.execute(
        "SELECT status FROM donations WHERE id = %s", (donation_id,)
    ).fetchone()
    assert row[0] == "AVAILABLE"  # proposal did not reserve
    api.get("/api/v1/donations?limit=1")
    r = api.get(f"/api/v1/donations/{donation_id}")
    assert r.json()["available_kg"] == "25.000"


def test_wrong_recipient_cannot_accept_opaque(api, db_conn):
    donation_id, reservation_id = _setup_proposal(api, db_conn)
    api.login(DEMO["riverside"])
    r = api.post(f"/api/v1/reservations/{reservation_id}/accept",
                 json={"accepted": True}, key="sec-2")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
    state = db_conn.execute(
        "SELECT state FROM reservations WHERE id = %s", (reservation_id,)
    ).fetchone()[0]
    assert state == "PROPOSED"


def test_coordinator_cannot_impersonate_acceptance(api, db_conn):
    donation_id, reservation_id = _setup_proposal(api, db_conn)
    api.login(DEMO["coordinator"])
    r = api.post(f"/api/v1/reservations/{reservation_id}/accept",
                 json={"accepted": True}, key="sec-3")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


def test_donor_cannot_propose(api, db_conn):
    donation_id, _ = _setup_proposal(api, db_conn)
    api.login(DEMO["donor"])
    expiry = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    r = api.post("/api/v1/reservations", json={
        "donation_id": donation_id,
        "recipient_org_id": org_id_by_name(db_conn, "Riverside Shelter"),
        "quantity_kg": "10.000", "proposal_expires_at": expiry,
    }, key="sec-4")
    assert r.status_code == 403


def test_donor_cannot_accept_own_donation_for_recipient(api, db_conn):
    """Donor cannot allocate their own donation without coordinator control."""
    donation_id = create_published_donation(api)
    api.login(DEMO["donor"])
    expiry = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    r = api.post("/api/v1/reservations", json={
        "donation_id": donation_id,
        "recipient_org_id": org_id_by_name(db_conn, "Northside Community Kitchen"),
        "quantity_kg": "5.000", "proposal_expires_at": expiry,
    }, key="sec-5")
    assert r.status_code == 403


def test_cross_tenant_reservation_detail_hidden(api, db_conn):
    """Recipients cannot list/see other tenants' reservations (listing is
    org-scoped) and donation detail shows only their own reservations."""
    donation_id, _ = _setup_proposal(api, db_conn)
    api.login(DEMO["riverside"])
    r = api.get("/api/v1/reservations?limit=100")
    items = r.json()["items"]
    assert all(i["recipient_org_name"] == "Riverside Shelter" for i in items)
    r = api.get(f"/api/v1/donations/{donation_id}")
    assert r.status_code == 200
    assert r.json()["reservations"] == []  # northside's proposal hidden


def test_transport_can_only_see_assigned_pickups(api, db_conn):
    donation_id, reservation_id = _setup_proposal(api, db_conn)
    api.login(DEMO["northside"])
    api.post(f"/api/v1/reservations/{reservation_id}/accept", json={"accepted": True},
             key="sec-6")
    api.login(DEMO["transport"])
    start, end, _ = tomorrow_window()
    pickup = api.post("/api/v1/pickups", json={
        "reservation_id": reservation_id,
        "pickup_window_start": (start + TD(hours=1)).isoformat(),
        "pickup_window_end": end.isoformat(),
    }, key="sec-7").json()
    r = api.get("/api/v1/pickups?limit=100")
    items = r.json()["items"]
    assert items and all(
        i["assigned_transport_org_name"] == "Swift Collective Volunteer Transport"
        for i in items
    )
    assert any(i["id"] == pickup["id"] for i in items)


def test_audit_requires_coordinator_or_admin(api):
    api.login(DEMO["northside"])
    r = api.get("/api/v1/audit")
    assert r.status_code == 403
    api.login(DEMO["donor"])
    r = api.get("/api/v1/audit")
    assert r.status_code == 403
    api.login(DEMO["coordinator"])
    r = api.get("/api/v1/audit?limit=10")
    assert r.status_code == 200
    entries = r.json()["items"]
    assert entries
    entry = entries[0]
    assert set(entry) >= {"id", "action", "resource_type", "outcome",
                          "safe_summary", "created_at"}
    assert "password" not in str(entry).lower()
    assert "hash" not in str(entry).lower()


def test_organizations_requires_platform_role(api):
    api.login(DEMO["donor"])
    r = api.get("/api/v1/organizations")
    assert r.status_code == 403
    api.login(DEMO["coordinator"])
    r = api.get("/api/v1/organizations")
    assert r.status_code == 200
    assert r.json()["total"] >= 8
    r = api.get("/api/v1/recipients")
    assert r.status_code == 200
    assert r.json()["total"] == 4


def test_no_secrets_or_stack_traces_in_errors(api):
    api.login(DEMO["donor"])
    r = api.post("/api/v1/donations", json={"category": "produce"})  # invalid body
    assert r.status_code in (422,)
    text = r.text
    assert "Traceback" not in text
    assert "password_hash" not in text
    assert "SESSION_SECRET" not in text


def test_ready_reports_worker_separately(api):
    r = api.get("/api/v1/ready")
    assert r.status_code in (200, 503)
    deps = r.json()["dependencies"]
    assert "postgres" in deps and "worker" in deps  # worker reported separately
