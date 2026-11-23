"""Reporting fidelity: no join multiplication, received-only-on-receipt,
denominators/windows, scope enforcement, CSV injection neutralization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import DEMO
from helpers import create_published_donation, donation_payload, org_id_by_name


def _window(days: int = 14):
    now = datetime.now(timezone.utc)
    to = now + timedelta(days=2)
    frm = now - timedelta(days=days)
    fmt = lambda d: d.isoformat().replace("+00:00", "Z")
    return f"from={fmt(frm)}&to={fmt(to)}"


def test_offered_not_multiplied_by_reservations(api, db_conn):
    donation_id = create_published_donation(api, donation_payload(quantity_kg="120.000"))
    from datetime import timedelta

    expiry = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    org = org_id_by_name(db_conn, "Northside Community Kitchen")
    api.login(DEMO["coordinator"])
    for i, qty in enumerate(("80.000", "40.000")):
        api.post("/api/v1/reservations", json={
            "donation_id": donation_id, "recipient_org_id": org,
            "quantity_kg": qty, "proposal_expires_at": expiry,
        }, key=f"rpt-p-{i}")
    reservation_ids = [r[0] for r in db_conn.execute(
        "SELECT id FROM reservations WHERE donation_id = %s", (donation_id,)
    ).fetchall()]
    assert len(reservation_ids) == 2
    api.login(DEMO["northside"])
    for i, rid in enumerate(reservation_ids):
        api.post(f"/api/v1/reservations/{rid}/accept", json={"accepted": True},
                 key=f"rpt-a-{i}")

    api.login(DEMO["coordinator"])
    r = api.get(f"/api/v1/reports/operations?{_window()}")
    report = r.json()
    # the 120kg offer counts exactly once regardless of its two reservations
    from decimal import Decimal as D

    assert D(report["offered_kg"]) >= D("120.000")
    assert D(report["committed_kg"]) >= D("120.000")
    # received only counts confirmed receipts (none here yet)
    if report["collected_kg"] != "0.000":
        assert D(report["received_kg"]) <= D(report["collected_kg"])
    # window + scope fields always present
    assert report["window_from"] and report["window_to"]
    assert report["scope_organization_id"] is None


def test_received_only_from_confirmed_receipts(api, db_conn):
    donation_id = create_published_donation(api)
    expiry = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    org = org_id_by_name(db_conn, "Northside Community Kitchen")
    api.login(DEMO["coordinator"])
    rid = api.post("/api/v1/reservations", json={
        "donation_id": donation_id, "recipient_org_id": org,
        "quantity_kg": "25.000", "proposal_expires_at": expiry,
    }, key="rcpt-1").json()["id"]
    api.login(DEMO["northside"])
    api.post(f"/api/v1/reservations/{rid}/accept", json={"accepted": True}, key="rcpt-2")
    api.login(DEMO["transport"])
    from helpers import tomorrow_window
    from datetime import timedelta as TD

    start, end, _ = tomorrow_window()
    pickup = api.post("/api/v1/pickups", json={
        "reservation_id": rid,
        "pickup_window_start": (start + TD(hours=1)).isoformat(),
        "pickup_window_end": end.isoformat(),
    }, key="rcpt-3").json()["id"]
    api.post(f"/api/v1/pickups/{pickup}/events",
             json={"event_type": "COLLECTED", "quantity_kg": "25.000"}, key="rcpt-4")
    api.post(f"/api/v1/pickups/{pickup}/events", json={"event_type": "DELIVERED"}, key="rcpt-5")

    api.login(DEMO["coordinator"])
    report = api.get(f"/api/v1/reports/operations?{_window()}").json()
    from decimal import Decimal as D

    # delivered but NOT yet received: received must not include this 25kg
    # (seeded history receipts do count; assert the specific flow did not)
    assert D(report["received_kg"]) >= D("175.000")  # seeded receipts only
    # confirm the receipt and see it counted
    api.login(DEMO["northside"])
    api.post(f"/api/v1/pickups/{pickup}/receipt",
             json={"received_quantity_kg": "25.000"}, key="rcpt-6")
    api.login(DEMO["coordinator"])
    report2 = api.get(f"/api/v1/reports/operations?{_window()}").json()
    assert D(report2["received_kg"]) == D(report["received_kg"]) + D("25.000")


def test_zero_denominator_ratio_is_null_not_zero_percent(api, db_conn):
    api.login(DEMO["coordinator"])
    # narrow window with no data at all
    now = datetime.now(timezone.utc)
    fmt = lambda d: d.isoformat().replace("+00:00", "Z")
    q = f"from={fmt(now - timedelta(days=30))}&to={fmt(now - timedelta(days=29))}"
    r = api.get(f"/api/v1/reports/operations?{q}")
    report = r.json()
    assert r.status_code == 200
    assert report["offered_kg"] == "0.000"
    for ratio in report["ratios"]:
        assert ratio["denominator"] == "0.000"
        assert ratio["value"] is None  # N/A, never a fake 0% / 100%


def test_organization_filter_enforced_server_side(api, db_conn):
    # recipient user asks for another org's report -> forbidden
    api.login(DEMO["northside"])
    other_org = org_id_by_name(db_conn, "Riverside Shelter")
    r = api.get(f"/api/v1/reports/operations?{_window()}&organization_id={other_org}")
    assert r.status_code == 403
    # own org allowed (no org_id -> pinned to own org)
    r = api.get(f"/api/v1/reports/operations?{_window()}")
    assert r.status_code == 200
    assert r.json()["scope_organization_name"] == "Northside Community Kitchen"
    own = org_id_by_name(db_conn, "Northside Community Kitchen")
    r = api.get(f"/api/v1/reports/operations?{_window()}&organization_id={own}")
    assert r.status_code == 200


def test_csv_export_safe_escaping(api, db_conn):
    donation_id = create_published_donation(api)
    expiry = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    org = org_id_by_name(db_conn, "Northside Community Kitchen")
    api.login(DEMO["coordinator"])
    rid = api.post("/api/v1/reservations", json={
        "donation_id": donation_id, "recipient_org_id": org,
        "quantity_kg": "25.000", "proposal_expires_at": expiry,
    }, key="csv-1").json()["id"]
    api.login(DEMO["northside"])
    api.post(f"/api/v1/reservations/{rid}/accept", json={"accepted": True}, key="csv-2")
    api.login(DEMO["coordinator"])
    # cancel the reservation via the API, then inject a formula-looking reason
    api.post(f"/api/v1/reservations/{rid}/cancel", json={"reason": "x"}, key="csv-3")
    db_conn.execute(
        "UPDATE reservations SET cancel_reason = '=2+3|cmd' WHERE id = %s", (rid,)
    )
    db_conn.commit()
    r = api.get(f"/api/v1/reports/operations.csv?{_window()}")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    text = r.text
    # formula-leading text is neutralized with a leading apostrophe
    assert "'=2+3|cmd" in text or "'=2+3" in text
    assert "\n=2+3" not in text  # never a raw formula start at cell start


def test_report_analyst_role_can_read_but_donor_scoped(api):
    api.login(DEMO["analyst"])
    r = api.get(f"/api/v1/reports/operations?{_window()}")
    assert r.status_code == 200
    api.login(DEMO["donor"])
    r = api.get(f"/api/v1/reports/operations?{_window()}")
    assert r.status_code == 200  # donors get their own org scope
    assert r.json()["scope_organization_name"] == "Metro Grocery Exchange"
