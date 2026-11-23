"""Matching engine: individual exclusion reasons, deterministic ranking,
zero-history neutrality, unknown inputs never auto-approved."""

from __future__ import annotations

from decimal import Decimal

from conftest import DEMO
from helpers import create_published_donation, donation_payload


def _matches(api, donation_id: str) -> dict:
    api.login(DEMO["coordinator"])
    r = api.get(f"/api/v1/donations/{donation_id}/matches")
    assert r.status_code == 200
    return r.json()


def _by_name(result: dict, name: str) -> dict | None:
    for e in result["eligible"]:
        if e["recipient_name"] == name:
            return e
    for x in result["excluded"]:
        if x["recipient_name"] == name:
            return x
    return None


def test_match_example_scenario_120kg(api, db_conn):
    """The specification's worked example: 120kg produce; Northside 80,
    Riverside 40 eligible with partial feasibility; Hillside excluded by
    category; Eastview eligible (produce+ambient)."""
    donation_id = create_published_donation(
        api, donation_payload(quantity_kg="120.000"))
    result = _matches(api, donation_id)
    northside = _by_name(result, "Northside Community Kitchen")
    riverside = _by_name(result, "Riverside Shelter")
    hillside = _by_name(result, "Hillside Community Center")
    eastview = _by_name(result, "Eastview Pantry")
    assert northside and riverside and eastview
    assert northside["max_feasible_kg"] == "80.000"
    assert riverside["max_feasible_kg"] == "60.000"
    assert eastview["max_feasible_kg"] == "40.000"
    assert hillside is not None and "CATEGORY_NOT_ACCEPTED" in hillside["reasons"]
    assert result["weights"] == {"capacity": 0.40, "reliability": 0.30,
                                 "fairness": 0.20, "same_area": 0.10}


def test_match_exclusion_handling_not_acknowledged(api):
    """Cold-chain donation excludes recipients that have not acknowledged the
    requires_cold handling tag."""
    donation_id = create_published_donation(
        api, donation_payload(category="dairy", handling_tags=["requires_cold"]))
    result = _matches(api, donation_id)
    northside = _by_name(result, "Northside Community Kitchen")   # acks cold
    riverside = _by_name(result, "Riverside Shelter")             # acks cold
    eastview = _by_name(result, "Eastview Pantry")                # ambient only
    assert northside is not None and "HANDLING_NOT_ACKNOWLEDGED" in eastview["reasons"]
    assert riverside is not None


def test_match_window_overlap_required(api, db_conn):
    """A donation whose window does not overlap receiving hours excludes
    everyone (seeded recipients have receiving hours 06:00-20:00 UTC max)."""
    from datetime import datetime, timedelta, timezone

    day = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = datetime.combine(day, datetime.min.time().replace(hour=23), tzinfo=timezone.utc)
    api.login(DEMO["donor"])
    payload = donation_payload(
        pickup_start=start.isoformat(),
        pickup_end=(start + timedelta(hours=2)).isoformat(),
        deadline=(start + timedelta(minutes=90)).isoformat(),
    )
    r = api.post("/api/v1/donations", json=payload)
    assert r.status_code == 201
    donation_id = r.json()["id"]
    api.post(f"/api/v1/donations/{donation_id}/publish", json={"attested": True}, key="mw-1")
    result = _matches(api, donation_id)
    assert result["eligible"] == []
    for x in result["excluded"]:
        assert "RECEIVING_WINDOW_MISMATCH" in x["reasons"] or x["reasons"] == ["RECEIVING_WINDOW_MISMATCH"]


def test_match_deadline_passed_excludes_all(api, db_conn):
    """Past-deadline donations are not open for matching."""
    donation_id = create_published_donation(api)
    db_conn.execute(
        """UPDATE donations SET pickup_start = now() - interval '3 hours',
           deadline = now() - interval '2 hours', pickup_end = now() - interval '1 hour'
           WHERE id = %s""",
        (donation_id,),
    )
    db_conn.commit()
    result = _matches(api, donation_id)
    assert result["eligible"] == []
    assert all("DEADLINE_PASSED" in x["reasons"] for x in result["excluded"])


def test_match_daily_capacity_exhausted(api, db_conn):
    """After Northside accepts 80 kg for a day, its feasibility is exhausted
    for another donation on the SAME receiving day."""
    from datetime import datetime, timedelta, timezone

    donation_a = create_published_donation(api, donation_payload(quantity_kg="80.000"))
    org_row = db_conn.execute(
        "SELECT id FROM organizations WHERE name = 'Northside Community Kitchen'"
    ).fetchone()
    northside_org = str(org_row[0])
    expiry = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    api.login(DEMO["coordinator"])
    r = api.post("/api/v1/reservations", json={
        "donation_id": donation_a, "recipient_org_id": northside_org,
        "quantity_kg": "80.000", "proposal_expires_at": expiry,
    }, key="cap-1")
    reservation_id = r.json()["id"]
    api.login(DEMO["northside"])
    r = api.post(f"/api/v1/reservations/{reservation_id}/accept", json={"accepted": True},
                 key="cap-2")
    assert r.status_code == 200

    # same receiving day (same start date) donation
    donation_b = create_published_donation(api, donation_payload(quantity_kg="20.000"))
    result = _matches(api, donation_b)
    northside = _by_name(result, "Northside Community Kitchen")
    assert "DAILY_CAPACITY_EXHAUSTED" in northside["reasons"]


def test_match_capacity_unknown_excluded(api, db_conn):
    """A recipient without a daily capacity profile is never silently
    eligible (REQUIRES_HUMAN_REVIEW semantics: CAPACITY_UNKNOWN exclusion)."""
    donation_id = create_published_donation(api)
    db_conn.execute("UPDATE recipient_profiles SET max_kg_per_day = NULL WHERE organization_id = "
                    "(SELECT id FROM organizations WHERE name = 'Eastview Pantry')")
    db_conn.commit()
    result = _matches(api, donation_id)
    eastview = _by_name(result, "Eastview Pantry")
    assert "CAPACITY_UNKNOWN" in eastview["reasons"]
    assert result["eligible"], "other recipients unaffected"


def test_match_ranking_deterministic_and_stable(api):
    donation_id = create_published_donation(api)
    first = _matches(api, donation_id)
    second = _matches(api, donation_id)
    names1 = [e["recipient_id"] for e in first["eligible"]]
    names2 = [e["recipient_id"] for e in second["eligible"]]
    assert names1 == names2  # same inputs -> identical order (tie-break by UUID)
    # every eligible entry carries a full score breakdown with weights
    for e in first["eligible"]:
        assert abs(sum(f["contribution"] for f in e["score_breakdown"]) - e["score"]) < 1e-3
        for f in e["score_breakdown"]:
            assert f["known"] is True or f["normalized"] == 0.5


def test_match_zero_history_neutral_reliability(api, db_conn):
    """Recipients with fewer than 3 concluded pickups get a neutral 0.5
    reliability, flagged NOT_AVAILABLE (known=false), never a fake ratio."""
    donation_id = create_published_donation(api)
    result = _matches(api, donation_id)
    eastview = _by_name(result, "Eastview Pantry")  # seeded: no pickup history
    assert eastview["zero_history"] is True
    reliability = [f for f in eastview["score_breakdown"] if f["factor"] == "reliability"][0]
    assert reliability["known"] is False
    assert reliability["raw"] is None
    assert reliability["normalized"] == 0.5


def test_match_requires_coordinator_role(api):
    api.login(DEMO["northside"])
    r = api.get("/api/v1/donations")
    items = api.get("/api/v1/donations?limit=5").json()["items"]
    donation_id = items[0]["id"]
    r = api.get(f"/api/v1/donations/{donation_id}/matches")
    assert r.status_code == 403


def test_matches_endpoint_matches_after_partial_accept(api, db_conn):
    """Re-running matching after acceptance shows reduced availability."""
    from datetime import datetime, timedelta, timezone

    donation_id = create_published_donation(api, donation_payload(quantity_kg="120.000"))
    org_row = db_conn.execute(
        "SELECT id FROM organizations WHERE name = 'Northside Community Kitchen'"
    ).fetchone()
    northside_org = str(org_row[0])
    expiry = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
    api.login(DEMO["coordinator"])
    r = api.post("/api/v1/reservations", json={
        "donation_id": donation_id, "recipient_org_id": northside_org,
        "quantity_kg": "80.000", "proposal_expires_at": expiry,
    }, key="rm-1")
    reservation_id = r.json()["id"]
    api.login(DEMO["northside"])
    api.post(f"/api/v1/reservations/{reservation_id}/accept", json={"accepted": True}, key="rm-2")
    result = _matches(api, donation_id)
    assert result["available_kg"] == "40.000"
    northside = _by_name(result, "Northside Community Kitchen")
    assert "DAILY_CAPACITY_EXHAUSTED" in northside["reasons"]
    riverside = _by_name(result, "Riverside Shelter")
    assert riverside is not None and Decimal(riverside["max_feasible_kg"]) <= 40
