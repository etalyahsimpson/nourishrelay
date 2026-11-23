"""Donation lifecycle: validation invariants, optimistic edits, publish
attestation, withdraw guards, role-scoped listing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import DEMO
from helpers import donation_payload, tomorrow_window


def test_donation_validation_rejects_bad_quantities(api):
    api.login(DEMO["donor"])
    for bad in ["0.000", "-5.000", "abc", "NaN"]:
        r = api.post("/api/v1/donations", json=donation_payload(quantity_kg=bad))
        assert r.status_code == 422, (bad, r.text[:200])
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_donation_validation_rejects_unsupported_category(api):
    api.login(DEMO["donor"])
    r = api.post("/api/v1/donations", json=donation_payload(category="frozen-meals"))
    assert r.status_code == 422
    # quantity unit is kg only: no unit field exists (documented kg-only MVP)


def test_donation_validation_rejects_incoherent_windows(api):
    api.login(DEMO["donor"])
    start, end, deadline = tomorrow_window()
    # deadline after pickup_end
    r = api.post("/api/v1/donations", json=donation_payload(
        deadline=(end + timedelta(hours=1)).isoformat()))
    assert r.status_code == 422
    # deadline before pickup_start
    r = api.post("/api/v1/donations", json=donation_payload(
        deadline=(start - timedelta(hours=1)).isoformat()))
    assert r.status_code == 422
    # pickup_end before pickup_start
    r = api.post("/api/v1/donations", json=donation_payload(
        pickup_end=(start - timedelta(minutes=5)).isoformat()))
    assert r.status_code == 422
    # past window
    r = api.post("/api/v1/donations", json=donation_payload(
        pickup_start=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        pickup_end=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        deadline=(datetime.now(timezone.utc) - timedelta(hours=90, minutes=1)).isoformat(),
    ))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_donation_create_and_publish_flow(api):
    api.login(DEMO["donor"])
    r = api.post("/api/v1/donations", json=donation_payload())
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "DRAFT"
    assert body["quantity_kg"] == "25.000"
    assert body["available_kg"] == "25.000"
    assert body["version"] == 1
    donation_id = body["id"]

    # publish without attestation is rejected
    r = api.post(f"/api/v1/donations/{donation_id}/publish", json={"attested": False},
                 key="pub-noattest-1")
    assert r.status_code == 422
    r = api.post(f"/api/v1/donations/{donation_id}/publish", json={}, key="pub-noattest-2")
    assert r.status_code == 422

    r = api.post(f"/api/v1/donations/{donation_id}/publish", json={"attested": True},
                 key="pub-ok-1")
    assert r.status_code == 200
    assert r.json()["status"] == "AVAILABLE"


def test_donation_edit_optimistic_version(api):
    api.login(DEMO["donor"])
    r = api.post("/api/v1/donations", json=donation_payload())
    donation_id = r.json()["id"]
    # edit with correct version
    r = api.req("PATCH", f"/api/v1/donations/{donation_id}",
                json={"version": 1, "notes": "updated notes"})
    assert r.status_code == 200
    assert r.json()["version"] == 2
    assert r.json()["notes"] == "updated notes"
    # stale version -> 409
    r = api.req("PATCH", f"/api/v1/donations/{donation_id}",
                json={"version": 1, "notes": "stale edit"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "STALE_VERSION"
    assert r.json()["error"]["details"]["current_version"] == 2


def test_donation_withdraw_guards_committed_inventory(api, db_conn):
    api.login(DEMO["donor"])
    r = api.post("/api/v1/donations", json=donation_payload())
    donation_id = r.json()["id"]
    api.post(f"/api/v1/donations/{donation_id}/publish", json={"attested": True}, key="wd-1")
    # withdraw with zero committed works and is idempotent
    r = api.post(f"/api/v1/donations/{donation_id}/withdraw", json={"reason": "quality check failed"},
                 key="wd-2")
    assert r.status_code == 200
    r2 = api.post(f"/api/v1/donations/{donation_id}/withdraw", json={"reason": "quality check failed"},
                  key="wd-3")
    assert r2.status_code == 200
    # committed guard: create fresh donation, accept a reservation against it
    donation_id2 = None
    api.login(DEMO["donor"])
    r = api.post("/api/v1/donations", json=donation_payload(quantity_kg="30.000"))
    donation_id2 = r.json()["id"]
    api.post(f"/api/v1/donations/{donation_id2}/publish", json={"attested": True}, key="wd-4")
    org_row = db_conn.execute(
        "SELECT id FROM organizations WHERE name = 'Northside Community Kitchen'"
    ).fetchone()
    api.login(DEMO["coordinator"])
    r = api.post("/api/v1/reservations", json={
        "donation_id": donation_id2,
        "recipient_org_id": str(org_row[0]),
        "quantity_kg": "30.000",
        "proposal_expires_at": (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(),
    }, key="wd-5")
    reservation_id = r.json()["id"]
    api.login(DEMO["northside"])
    r = api.post(f"/api/v1/reservations/{reservation_id}/accept", json={"accepted": True},
                 key="wd-6")
    assert r.status_code == 200
    api.login(DEMO["donor"])
    r = api.post(f"/api/v1/donations/{donation_id2}/withdraw", json={"reason": "should fail"},
                 key="wd-7")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "COMMITTED_INVENTORY"
    assert r.json()["error"]["details"]["committed_kg"] == "30.000"


def test_donation_list_role_scoping(api):
    # donor sees own donations (Metro donor has no draft; the seeded DRAFT
    # belongs to Harvest Lane, checked below)
    api.login(DEMO["donor"])
    r = api.get("/api/v1/donations?limit=100")
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(i["donor_org_name"] == "Metro Grocery Exchange" for i in items)
    api.login(DEMO["donor2"])
    r = api.get("/api/v1/donations?limit=100")
    items2 = r.json()["items"]
    assert all(i["donor_org_name"] == "Harvest Lane Market" for i in items2)
    assert any(i["status"] == "DRAFT" for i in items2)  # seeded draft exists
    # recipient sees only published open donations
    api.login(DEMO["northside"])
    r = api.get("/api/v1/donations?limit=100")
    items = r.json()["items"]
    assert items and all(
        i["status"] in ("AVAILABLE", "PARTIALLY_RESERVED", "FULLY_RESERVED") for i in items
    )
    # transport users have no donation listing
    api.login(DEMO["transport"])
    r = api.get("/api/v1/donations")
    assert r.status_code == 403
    # coordinator sees all published
    api.login(DEMO["coordinator"])
    r = api.get("/api/v1/donations?limit=100")
    assert r.json()["total"] >= 4
    # category + status filters
    r = api.get("/api/v1/donations?category=produce&limit=100")
    assert all(i["category"] == "produce" for i in r.json()["items"])
    r = api.get("/api/v1/donations?status=DRAFT&limit=100")
    assert all(i["status"] == "DRAFT" for i in r.json()["items"])


def test_donation_detail_cross_tenant_opaque_404(api, db_conn):
    api.login(DEMO["donor"])
    r = api.post("/api/v1/donations", json=donation_payload())
    donation_id = r.json()["id"]
    # DRAFT donations are invisible to recipients (opaque 404)
    api.login(DEMO["riverside"])
    r = api.get(f"/api/v1/donations/{donation_id}")
    assert r.status_code == 404
    # published donations are visible to recipients
    api.login(DEMO["donor"])
    api.post(f"/api/v1/donations/{donation_id}/publish", json={"attested": True}, key="dt-1")
    api.login(DEMO["riverside"])
    r = api.get(f"/api/v1/donations/{donation_id}")
    assert r.status_code == 200
    # withdrawn donations disappear again for recipients
    api.login(DEMO["donor"])
    api.post(f"/api/v1/donations/{donation_id}/withdraw", json={}, key="dt-2")
    api.login(DEMO["riverside"])
    r = api.get(f"/api/v1/donations/{donation_id}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
    # donor detail includes revisions/reservations structures
    api.login(DEMO["donor"])
    r = api.get(f"/api/v1/donations/{donation_id}")
    assert r.status_code == 200
    body = r.json()
    assert "revisions" in body and "reservations" in body
    assert body["status"] == "WITHDRAWN"
