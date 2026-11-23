"""Atomic inventory safety against REAL concurrent HTTP acceptances.

The specification's gate: concurrent ACCEPT of 80kg and 80kg against a 120kg
offer must never commit more than 120kg; one side receives 409
STOCK_CONFLICT; the follow-up 80+40 succeeds. Runs against actual
PostgreSQL row locks via a real uvicorn server (see conftest.py).
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from conftest import DEMO
from helpers import create_published_donation, donation_payload, org_id_by_name


def _propose(api, db_conn, donation_id: str, org_name: str, qty: str) -> str:
    api.login(DEMO["coordinator"])
    expiry = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    r = api.post("/api/v1/reservations", json={
        "donation_id": donation_id,
        "recipient_org_id": org_id_by_name(db_conn, org_name),
        "quantity_kg": qty,
        "proposal_expires_at": expiry,
    }, key=f"propose-{donation_id[:8]}-{org_name}-{qty}")
    assert r.status_code == 201, r.text[:300]
    return r.json()["id"]


def _concurrent_accept(base_url: str, email: str, reservation_id: str, key: str,
                       out: dict) -> None:
    import httpx

    client = httpx.Client(base_url=base_url, timeout=60)
    try:
        client.post("/api/v1/auth/login",
                    json={"email": email, "password": "demo-password"})
        csrf = client.cookies.get("nourishrelay_csrf")
        r = client.post(f"/api/v1/reservations/{reservation_id}/accept",
                        json={"accepted": True},
                        headers={"Idempotency-Key": key, "X-CSRF-Token": csrf})
        out[key] = (r.status_code, r.json())
    finally:
        client.close()


def test_concurrent_accept_cannot_oversubscribe_120kg(api, db_conn, api_server):
    donation_id = create_published_donation(
        api, donation_payload(quantity_kg="120.000", category="canned"))
    res_north = _propose(api, db_conn, donation_id, "Northside Community Kitchen", "80.000")
    res_river = _propose(api, db_conn, donation_id, "Riverside Shelter", "80.000")

    out: dict = {}
    threads = [
        threading.Thread(target=_concurrent_accept,
                         args=(api_server, DEMO["northside"], res_north, "acc-north-80", out)),
        threading.Thread(target=_concurrent_accept,
                         args=(api_server, DEMO["riverside"], res_river, "acc-river-80", out)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = sorted(code for code, _ in out.values())
    assert statuses == [200, 409], out
    conflicts = [body for code, body in out.values() if code == 409]
    assert conflicts
    assert all(c["error"]["code"] == "STOCK_CONFLICT" for c in conflicts)
    assert all(c["error"]["details"].get("available_kg") == "40.000" for c in conflicts)

    # actual committed stock never exceeds the offered 120 kg
    committed = db_conn.execute(
        """
        SELECT COALESCE(SUM(quantity_kg), 0) FROM reservations
        WHERE donation_id = %s AND state IN ('ACCEPTED','PICKUP_ASSIGNED','COLLECTED','DELIVERED','RECEIVED')
        """,
        (donation_id,),
    ).fetchone()[0]
    # exactly the winning 80.000 kg is committed — never more than offered
    assert committed == 80
    row = db_conn.execute(
        "SELECT status FROM donations WHERE id = %s", (donation_id,)
    ).fetchone()
    assert row[0] == "PARTIALLY_RESERVED"


def test_concurrent_accept_80_plus_40_succeeds(api, db_conn, api_server):
    donation_id = create_published_donation(
        api, donation_payload(quantity_kg="120.000", category="canned"))
    res_north = _propose(api, db_conn, donation_id, "Northside Community Kitchen", "80.000")
    res_river = _propose(api, db_conn, donation_id, "Riverside Shelter", "40.000")

    out: dict = {}
    threads = [
        threading.Thread(target=_concurrent_accept,
                         args=(api_server, DEMO["northside"], res_north, "acc-80", out)),
        threading.Thread(target=_concurrent_accept,
                         args=(api_server, DEMO["riverside"], res_river, "acc-40", out)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(code == 200 for code, _ in out.values()), out
    committed = db_conn.execute(
        """
        SELECT COALESCE(SUM(quantity_kg), 0) FROM reservations
        WHERE donation_id = %s AND state IN ('ACCEPTED','PICKUP_ASSIGNED','COLLECTED','DELIVERED','RECEIVED')
        """,
        (donation_id,),
    ).fetchone()[0]
    assert committed == 120


def test_many_concurrent_accepts_20x_against_120kg(api, db_conn, api_server):
    """Fixed profile: 20 concurrent acceptance attempts (6kg each) against a
    120kg offer — at most 20 succeed; committed never exceeds 120kg."""
    donation_id = create_published_donation(
        api, donation_payload(quantity_kg="120.000", category="canned"))
    # 'canned' is accepted by northside, riverside and hillside
    orgs = ["Northside Community Kitchen", "Riverside Shelter",
            "Hillside Community Center"]
    proposals = []
    for i in range(20):
        org = orgs[i % len(orgs)]
        proposals.append(_propose(api, db_conn, donation_id, org, "6.000"))

    # capacity constraints will also reject some (max_kg_per_day), which is
    # correct hard-constraint behavior; the stock invariant must still hold.
    out: dict = {}
    threads = []
    emails = [DEMO["northside"], DEMO["riverside"], DEMO["hillside"]]
    for i, reservation_id in enumerate(proposals):
        threads.append(threading.Thread(
            target=_concurrent_accept,
            args=(api_server, emails[i % 3], reservation_id, f"acc20-{i}", out)))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    committed = db_conn.execute(
        """
        SELECT COALESCE(SUM(quantity_kg), 0) FROM reservations
        WHERE donation_id = %s AND state IN ('ACCEPTED','PICKUP_ASSIGNED','COLLECTED','DELIVERED','RECEIVED')
        """,
        (donation_id,),
    ).fetchone()[0]
    assert committed <= 120
    successes = sum(1 for code, _ in out.values() if code == 200)
    conflicts = sum(1 for code, body in out.values() if code == 409)
    assert successes + conflicts == 20
    assert committed == 6 * successes  # every success is a 6kg acceptance


def test_same_reservation_double_accept_race(api, db_conn, api_server):
    """Two concurrent acceptances of the SAME proposal: exactly one commits."""
    donation_id = create_published_donation(api)
    reservation_id = _propose(api, db_conn, donation_id, "Northside Community Kitchen", "25.000")
    out: dict = {}
    threads = [
        threading.Thread(target=_concurrent_accept,
                         args=(api_server, DEMO["northside"], reservation_id, "same-1", out)),
        threading.Thread(target=_concurrent_accept,
                         args=(api_server, DEMO["northside"], reservation_id, "same-2", out)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    codes = sorted(code for code, _ in out.values())
    assert codes == [200, 409]
    state = db_conn.execute(
        "SELECT state FROM reservations WHERE id = %s", (reservation_id,)
    ).fetchone()[0]
    assert state == "ACCEPTED"
