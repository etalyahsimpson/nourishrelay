"""Shared test helpers (donation creation, org lookups)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def tomorrow_window(start_hour: int = 10, length_hours: int = 2, days: int = 1):
    """A UTC pickup window that overlaps the demo recipients' receiving hours."""
    day = datetime.now(timezone.utc).date() + timedelta(days=days)
    start = datetime.combine(day, datetime.min.time().replace(hour=start_hour), tzinfo=timezone.utc)
    return start, start + timedelta(hours=length_hours), start + timedelta(minutes=90)


def donation_payload(**overrides) -> dict:
    start, end, deadline = tomorrow_window()
    payload = {
        "category": "produce",
        "quantity_kg": "25.000",
        "handling_tags": ["ambient"],
        "pickup_start": start.isoformat(),
        "pickup_end": end.isoformat(),
        "deadline": deadline.isoformat(),
        "location_label": "Test District A — helper",
        "notes": "helper donation",
    }
    payload.update(overrides)
    for k in ("pickup_start", "pickup_end", "deadline"):
        if isinstance(payload.get(k), datetime):
            payload[k] = payload[k].isoformat()
    return payload


def create_published_donation(api, payload: dict | None = None) -> str:
    """Create + publish a donation as the Metro donor; returns its id."""
    api.login("donor@metro.demo.nourishrelay.example")
    body = payload or donation_payload()
    r = api.post("/api/v1/donations", json=body)
    assert r.status_code == 201, r.text[:300]
    donation_id = r.json()["id"]
    r = api.post(f"/api/v1/donations/{donation_id}/publish", json={"attested": True},
                 key=f"publish-{donation_id}")
    assert r.status_code == 200, r.text[:300]
    return donation_id


def org_id_by_name(db_conn, name: str) -> str:
    row = db_conn.execute("SELECT id FROM organizations WHERE name = %s", (name,)).fetchone()
    assert row is not None, f"organization {name!r} missing"
    return str(row[0])
