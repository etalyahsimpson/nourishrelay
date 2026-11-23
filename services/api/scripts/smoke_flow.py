#!/usr/bin/env python
"""NourishRelay smoke workflow — one complete donor→receipt cycle over real HTTP.

Steps (all against the running API):
 1. health check
 2. donor login; create + publish a 25.000 kg produce donation (window tomorrow)
 3. coordinator login; compute matches; assert expected eligibility shape
    (eligible and excluded recipients with reasons)
 4. coordinator proposes 25.000 kg to the demo Northside kitchen
 5. recipient accepts atomically; assert stock math (available 25 -> 0)
 6. transport creates pickup, collects 25.000 kg, delivers
 7. recipient confirms receipt of 25.000 kg (no exception: equal to collected)
 8. donation detail is CLOSED with a RECEIVED reservation
 9. operations report reflects the new receipt; CSV export returns text/csv

Uses ONLY synthetic demo accounts from data/synthetic/seed-organizations.json.
Exit codes: 0 = workflow verified; 1 = a step or assertion failed.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor

DEMO_PASSWORD = "demo-password"
DONOR = "donor@metro.demo.nourishrelay.example"
RECIPIENT = "recipient@northside.demo.nourishrelay.example"
RECIPIENT_NOT_TARGET = "recipient@riverside.demo.nourishrelay.example"
COORDINATOR = "coordinator@relay.demo.nourishrelay.example"
TRANSPORT = "transport@swiftcollective.demo.nourishrelay.example"


class Client:
    def __init__(self, api_url: str) -> None:
        self.api = api_url.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.jar))
        self.csrf: str | None = None
        self.status = 0
        self.body: dict = {}

    def request(self, method: str, path: str, body: dict | None = None,
                headers: dict[str, str] | None = None, raw: bool = False):
        data = None
        hdrs = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        if headers:
            hdrs.update(headers)
        if method not in ("GET", "HEAD") and self.csrf:
            hdrs.setdefault("X-CSRF-Token", self.csrf)
        req = Request(self.api + path, data=data, method=method, headers=hdrs)
        try:
            resp = self.opener.open(req, timeout=30)
            self.status = resp.status
            payload = resp.read()
            ctype = resp.headers.get("content-type", "")
            if raw:
                self.body = payload.decode("utf-8", "replace")
                return self.status, self.body, ctype
            self.body = json.loads(payload or b"{}")
            return self.status, self.body, ctype
        except HTTPError as e:
            self.status = e.code
            payload = e.read()
            try:
                self.body = json.loads(payload or b"{}")
            except json.JSONDecodeError:
                self.body = {"raw": payload.decode("utf-8", "replace")}
            return self.status, self.body, e.headers.get("content-type", "")

    def login(self, email: str, password: str = DEMO_PASSWORD) -> dict:
        self.jar.clear()
        self.csrf = None
        status, body, _ = self.request("POST", "/api/v1/auth/login",
                                       {"email": email, "password": password})
        assert status == 200, f"login {email} -> {status}: {body}"
        for cookie in self.jar:
            if cookie.name == "nourishrelay_csrf":
                self.csrf = cookie.value
        assert self.csrf, "login did not set the CSRF cookie"
        return body

    def key(self) -> str:
        return f"smoke-{uuid.uuid4()}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8000")
    args = parser.parse_args()
    c = Client(args.api_url)
    step = 0

    def ok(label: str) -> None:
        nonlocal step
        step += 1
        print(f"[{step:02d}] OK  {label}")

    try:
        # 1) health
        status, body, _ = c.request("GET", "/api/v1/health")
        assert status == 200 and body["service"] == "nourishrelay-api", body
        ok("api health")

        # 2) donor creates + publishes a donation for tomorrow 10:00–12:00 UTC
        tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
        start = datetime.combine(tomorrow, datetime.min.time().replace(hour=10), tzinfo=timezone.utc)
        c.login(DONOR)
        status, body, _ = c.request("POST", "/api/v1/donations", {
            "category": "produce",
            "quantity_kg": "25.000",
            "handling_tags": ["ambient"],
            "pickup_start": start.isoformat(),
            "pickup_end": (start + timedelta(hours=2)).isoformat(),
            "deadline": (start + timedelta(hours=1, minutes=30)).isoformat(),
            "location_label": "Demo District A — Metro Grocery Exchange smoke run",
            "notes": "Created by the automated smoke workflow.",
        })
        assert status == 201, body
        donation_id = body["id"]
        assert body["status"] == "DRAFT" and body["available_kg"] == "25.000", body
        ok(f"donation created (DRAFT, 25.000 kg available): {donation_id}")

        status, body, _ = c.request("POST", f"/api/v1/donations/{donation_id}/publish",
                                    {"attested": True},
                                    {"Idempotency-Key": c.key()})
        assert status == 200 and body["status"] == "AVAILABLE", body
        ok("donation published (AVAILABLE)")

        # 3) coordinator computes matches
        c.login(COORDINATOR)
        status, body, _ = c.request("GET", f"/api/v1/donations/{donation_id}/matches")
        assert status == 200, body
        eligible = {e["recipient_name"]: e for e in body["eligible"]}
        excluded = {x["recipient_name"]: x for x in body["excluded"]}
        assert "Northside Community Kitchen" in eligible, body
        assert eligible["Northside Community Kitchen"]["max_feasible_kg"] == "25.000", body
        assert "Hillside Community Center" in excluded and "CATEGORY_NOT_ACCEPTED" in \
            excluded["Hillside Community Center"]["reasons"], body
        assert "Eastview Pantry" in eligible, body
        ok(f"matches: {len(body['eligible'])} eligible / {len(body['excluded'])} excluded with reasons")

        # 4) coordinator proposes 25.000 kg to Northside
        northside_org = eligible["Northside Community Kitchen"]["recipient_id"]
        status, body, _ = c.request("POST", "/api/v1/reservations", {
            "donation_id": donation_id,
            "recipient_org_id": northside_org,
            "quantity_kg": "25.000",
            "proposal_expires_at": (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(),
        }, {"Idempotency-Key": c.key()})
        assert status == 201 and body["state"] == "PROPOSED", body
        reservation_id = body["id"]
        assert body["donation_available_kg"] == "25.000", body  # proposals do not reserve stock
        ok("proposal created (PROPOSED — no stock committed)")

        # 5) recipient accepts atomically
        c.login(RECIPIENT)
        status, body, _ = c.request("POST", f"/api/v1/reservations/{reservation_id}/accept",
                                    {"accepted": True}, {"Idempotency-Key": c.key()})
        assert status == 200 and body["state"] == "ACCEPTED", body
        assert body["donation_available_kg"] == "0.000", body
        assert body["reserved_quantity_kg"] == "25.000", body
        ok("recipient accepted atomically (available 25.000 -> 0.000)")

        # wrong-recipient attempt stays opaque
        c.login(RECIPIENT_NOT_TARGET)
        status, body, _ = c.request("POST", f"/api/v1/reservations/{reservation_id}/accept",
                                    {"accepted": True}, {"Idempotency-Key": c.key()})
        assert status == 404, (status, body)
        ok("other recipient cannot accept (opaque 404)")
        c.login(RECIPIENT)

        # 6) transport assigns pickup, collects, delivers
        c.login(TRANSPORT)
        status, body, _ = c.request("POST", "/api/v1/pickups", {
            "reservation_id": reservation_id,
            "pickup_window_start": (start + timedelta(hours=1)).isoformat(),
            "pickup_window_end": (start + timedelta(hours=2)).isoformat(),
        }, {"Idempotency-Key": c.key()})
        assert status == 201 and body["status"] == "SCHEDULED", body
        pickup_id = body["id"]
        ok("pickup scheduled")

        status, body, _ = c.request("POST", f"/api/v1/pickups/{pickup_id}/events",
                                    {"event_type": "COLLECTED", "quantity_kg": "25.000"},
                                    {"Idempotency-Key": c.key()})
        assert status == 200 and body["reservation_state"] == "COLLECTED", body
        ok("collected 25.000 kg (<= accepted 25.000)")

        status, body, _ = c.request("POST", f"/api/v1/pickups/{pickup_id}/events",
                                    {"event_type": "DELIVERED"},
                                    {"Idempotency-Key": c.key()})
        assert status == 200 and body["reservation_state"] == "DELIVERED", body
        ok("delivered (recorded delivery, not yet a receipt)")

        # 7) recipient confirms receipt
        c.login(RECIPIENT)
        status, body, _ = c.request("POST", f"/api/v1/pickups/{pickup_id}/receipt",
                                    {"received_quantity_kg": "25.000"},
                                    {"Idempotency-Key": c.key()})
        assert status == 201 and body["reservation_state"] == "RECEIVED", body
        ok("receipt confirmed 25.000 kg")

        # 8) donation detail is CLOSED with RECEIVED reservation
        c.login(DONOR)
        status, body, _ = c.request("GET", f"/api/v1/donations/{donation_id}")
        assert status == 200 and body["status"] == "CLOSED", body
        assert any(r["state"] == "RECEIVED" for r in body["reservations"]), body
        ok("donation CLOSED after verified receipt")

        # 9) operations report + CSV
        c.login(COORDINATOR)
        now = datetime.now(timezone.utc)
        # 'Z' suffix avoids '+' encoding issues in query strings.
        fmt = lambda dt: dt.isoformat().replace("+00:00", "Z")
        q = f"from={fmt(now - timedelta(days=7))}&to={fmt(now + timedelta(days=2))}"
        status, body, _ = c.request("GET", f"/api/v1/reports/operations?{q}")
        assert status == 200, body
        assert Decimal(body["received_kg"]) >= Decimal("25.000"), body
        assert Decimal(body["offered_kg"]) >= Decimal("25.000"), body
        ok(f"report: offered {body['offered_kg']} kg, received {body['received_kg']} kg")
        status, text, ctype = c.request("GET", f"/api/v1/reports/operations.csv?{q}", raw=True)
        assert status == 200 and "text/csv" in ctype, (status, ctype)
        assert "received_kg" in text
        ok("CSV export with text/csv content type")

        print(f"SMOKE WORKFLOW PASSED ({step} steps) — donor→publish→match→propose→accept→pickup→collect→deliver→receipt→report")
        return 0
    except AssertionError as exc:
        print(f"SMOKE WORKFLOW FAILED at step {step + 1}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
