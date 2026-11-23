#!/usr/bin/env python
"""Idempotent synthetic demo seed for NourishRelay.

Loads data/synthetic/seed-organizations.json and materializes:
- organizations, demo users (bcrypt-hashed public demo password),
  recipient profiles (deterministic UUIDs derived from fixed slugs);
- live donations with windows relative to the current clock (the scenario
  never goes stale);
- one pending proposal for the recipient queue;
- completed historical flows (proposal -> accept -> pickup -> collect ->
  deliver -> receipt / failure / cancellation) written THROUGH the same
  domain functions the API uses, with a deterministic historic clock — so
  events, audit rows and state history are genuine records of real code
  paths, not fabricated JSON.

Re-running the seed is a no-op (marker event SEED_APPLIED). The entire seed
runs in ONE PostgreSQL transaction: all-or-nothing.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # services/api

from app import db  # noqa: E402
from app.dependencies import CurrentUser  # noqa: E402
from app.domain import pickups as pickup_domain  # noqa: E402
from app.domain import reservations as res_domain  # noqa: E402
from app.domain.clock import ensure_utc, utcnow  # noqa: E402
from app.domain.idempotency import record_audit, record_event  # noqa: E402
from app.domain.transitions import close_donation_if_terminal, transition_donation  # noqa: E402
from app.security import hash_password  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "data" / "synthetic" / "seed-organizations.json"
NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # RFC4122 namespace


def det_id(kind: str, key: str) -> str:
    return str(uuid.uuid5(NS, f"nourishrelay:{kind}:{key}"))


def main() -> int:
    database_url = _require_database_url()
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    password_hash = hash_password(fixture["meta"]["demo_password"])
    orgs_by_slug = {o["slug"]: o for o in fixture["organizations"]}
    users_by_email = {u["email"]: u for u in fixture["users"]}
    org_ids = {slug: det_id("org", slug) for slug in orgs_by_slug}
    user_ids = {email: det_id("user", email) for email in users_by_email}
    donor_email_by_org = {
        u["org"]: u["email"] for u in fixture["users"] if u["role"] == "donor"
    }
    recipient_email_by_org = {
        u["org"]: u["email"] for u in fixture["users"] if u["role"] == "recipient"
    }

    db.init_pool(database_url)
    now = utcnow()
    # Anchor live donation windows to 10:00 UTC tomorrow so pickup windows
    # always overlap the demo recipients' receiving hours (06:00–20:00 UTC).
    tomorrow = (now + timedelta(days=1)).date()
    anchor = datetime.combine(tomorrow, dtime(10, 0), tzinfo=timezone.utc)

    with db.tx() as conn:
        if conn.execute(
            "SELECT 1 FROM events WHERE event_type = 'SEED_APPLIED' AND idempotency_key = 'seed:v1'"
        ).fetchone():
            print("seed: already applied (marker found); nothing to do")
            db.close_pool()
            return 0
        # --- organizations -------------------------------------------------
        for slug, org in orgs_by_slug.items():
            conn.execute(
                """
                INSERT INTO organizations (id, name, kind, verified, service_area, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (org_ids[slug], org["name"], org["kind"], org["verified"],
                 org.get("service_area"), now - timedelta(days=30)),
            )

        # --- users ---------------------------------------------------------
        for email, u in users_by_email.items():
            conn.execute(
                """
                INSERT INTO users (id, organization_id, display_name, email,
                                    password_hash, role, active, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s)
                ON CONFLICT (email) DO NOTHING
                """,
                (user_ids[email], org_ids.get(u["org"]), u["display_name"], email,
                 password_hash, u["role"], now - timedelta(days=30)),
            )

        # --- recipient profiles --------------------------------------------
        for profile in fixture["recipient_profiles"]:
            conn.execute(
                """
                INSERT INTO recipient_profiles (organization_id, accepted_categories,
                     max_kg_per_day, handling_acknowledged, receiving_start,
                     receiving_end, timezone, active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
                ON CONFLICT (organization_id) DO NOTHING
                """,
                (
                    org_ids[profile["org"]],
                    profile["accepted_categories"],
                    Decimal(profile["max_kg_per_day"]),
                    profile["handling_acknowledged"],
                    profile["receiving_start"],
                    profile["receiving_end"],
                    profile.get("timezone", "UTC"),
                ),
            )

        def actor_of(email: str) -> CurrentUser:
            u = users_by_email[email]
            return CurrentUser(
                id=user_ids[email], role=u["role"],
                organization_id=org_ids.get(u["org"]),
                display_name=u["display_name"], email=email,
            )
        # --- live donations --------------------------------------------------
        coordinator = actor_of("coordinator@relay.demo.nourishrelay.example")
        for spec in fixture["active_donations"]:
            donation_id = det_id("donation", spec["key"])
            donor_email = spec["created_by"]
            pickup_start = anchor + timedelta(hours=spec["pickup_start_offset_hours"])
            pickup_end = anchor + timedelta(hours=spec["pickup_end_offset_hours"])
            deadline = anchor + timedelta(hours=spec["deadline_offset_hours"])
            conn.execute(
                """
                INSERT INTO donations (id, donor_org_id, created_by, category,
                     quantity_kg, handling_tags, pickup_start, pickup_end,
                     deadline, status, location_label, notes, created_at,
                     updated_at, published_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    donation_id, org_ids[spec["donor_org"]], user_ids[donor_email],
                    spec["category"], Decimal(spec["quantity_kg"]), spec["handling_tags"],
                    pickup_start, pickup_end, deadline,
                    "AVAILABLE" if spec.get("publish") else "DRAFT",
                    spec["location_label"], spec.get("notes"), now, now,
                    now if spec.get("publish") else None,
                ),
            )
            record_event(
                conn, aggregate_type="donation", aggregate_id=donation_id,
                actor_id=user_ids[donor_email], event_type="DONATION_CREATED",
                idempotency_key=f"seed:{spec['key']}:create",
                request_hash=None,
                response_result={"id": donation_id, "status": "DRAFT"},
                payload={"quantity_kg": spec["quantity_kg"]}, occurred_at=now,
            )
            if spec.get("publish"):
                record_event(
                    conn, aggregate_type="donation", aggregate_id=donation_id,
                    actor_id=user_ids[donor_email], event_type="DONATION_PUBLISHED",
                    idempotency_key=f"seed:{spec['key']}:publish", request_hash=None,
                    response_result={"id": donation_id, "status": "AVAILABLE"},
                    payload={"attested": True}, occurred_at=now,
                )
                record_audit(
                    conn, actor_id=user_ids[donor_email],
                    organization_id=org_ids[spec["donor_org"]],
                    action="donation.publish", resource_type="donation",
                    resource_id=donation_id, outcome="available",
                    safe_summary={"quantity_kg": spec["quantity_kg"]}, occurred_at=now,
                )

        # --- pending proposal (recipient queue) -------------------------------
        for spec in fixture["pending_proposals"]:
            donation_id = det_id("donation", spec["donation_key"])
            res_domain.propose_reservation(
                conn,
                actor=coordinator,
                donation_id=donation_id,
                recipient_org_id=org_ids[spec["recipient_org"]],
                quantity_kg=Decimal(spec["quantity_kg"]),
                proposal_expires_at=now + timedelta(hours=spec["proposal_expires_offset_hours"]),
                now=now,
                idempotency_key=f"seed:{spec['donation_key']}:proposal",
            )

        # --- historical flows (recorded through real domain code) -----------
        for flow in fixture["history_flows"]:
            # 10:00 UTC on the flow's day keeps windows inside receiving hours.
            flow_day = (now - timedelta(days=flow["days_ago"])).date()
            flow_now = datetime.combine(flow_day, dtime(10, 0), tzinfo=timezone.utc)
            donation_id = det_id("donation", flow["key"])
            donor_email = donor_email_by_org[flow["donor_org"]]
            pickup_start = flow_now
            pickup_end = flow_now + timedelta(hours=2)
            deadline = flow_now + timedelta(minutes=90)
            conn.execute(
                """
                INSERT INTO donations (id, donor_org_id, created_by, category,
                     quantity_kg, handling_tags, pickup_start, pickup_end,
                     deadline, status, location_label, notes, created_at,
                     updated_at, published_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'AVAILABLE', %s, NULL,
                        %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    donation_id, org_ids[flow["donor_org"]], user_ids[donor_email],
                    flow["category"], Decimal(flow["quantity_kg"]), flow["handling_tags"],
                    pickup_start, pickup_end, deadline, flow["location_label"],
                    flow_now - timedelta(minutes=30), flow_now - timedelta(minutes=30),
                    flow_now - timedelta(minutes=30),
                ),
            )
            step_i = 0
            for step in flow["steps"]:
                step_i += 1
                at = flow_now + timedelta(hours=float(step.get("hours_after_start", 0.5)))
                if step["type"] == "proposal":
                    result = res_domain.propose_reservation(
                        conn, actor=coordinator, donation_id=donation_id,
                        recipient_org_id=org_ids[step["recipient_org"]],
                        quantity_kg=Decimal(step["quantity_kg"]),
                        proposal_expires_at=at + timedelta(hours=2),
                        now=at, idempotency_key=f"seed:{flow['key']}:propose:{step_i}",
                    )
                    if step.get("outcome") == "accepted":
                        recipient = actor_of(recipient_email_by_org[step["recipient_org"]])
                        res_domain.accept_reservation(
                            conn, actor=recipient, reservation_id=result["id"],
                            now=at + timedelta(minutes=15),
                            idempotency_key=f"seed:{flow['key']}:accept:{step_i}",
                        )
                    elif step.get("outcome") == "declined":
                        recipient = actor_of(recipient_email_by_org[step["recipient_org"]])
                        res_domain.decline_reservation(
                            conn, actor=recipient, reservation_id=result["id"],
                            reason=step.get("decline_reason"), now=at,
                            idempotency_key=f"seed:{flow['key']}:decline:{step_i}",
                        )
                elif step["type"] == "pickup":
                    reservation_id = _latest_reservation(conn, donation_id, org_ids[step["recipient_org"]])
                    transport = actor_of("transport@swiftcollective.demo.nourishrelay.example")
                    pickup = pickup_domain.create_pickup(
                        conn, actor=transport, reservation_id=reservation_id,
                        assigned_transport_org_id=org_ids[step["assigned_transport"]],
                        pickup_window_start=flow_now + timedelta(hours=1),
                        pickup_window_end=flow_now + timedelta(hours=2),
                        now=at,
                        idempotency_key=f"seed:{flow['key']}:pickup:{step_i}",
                    )
                    if step.get("failed"):
                        pickup_domain.record_pickup_event(
                            conn, actor=transport, pickup_id=pickup["id"],
                            event_type="FAILED", occurred_at=None,
                            quantity_kg=None, reason=step.get("failure_reason"),
                            now=at + timedelta(minutes=30),
                            idempotency_key=f"seed:{flow['key']}:fail:{step_i}",
                        )
                    elif step.get("failed_after_collection"):
                        pickup_domain.record_pickup_event(
                            conn, actor=transport, pickup_id=pickup["id"],
                            event_type="COLLECTED", occurred_at=None,
                            quantity_kg=Decimal(step["collected_kg"]), reason=None,
                            now=at + timedelta(minutes=30),
                            idempotency_key=f"seed:{flow['key']}:collect:{step_i}",
                        )
                        pickup_domain.record_pickup_event(
                            conn, actor=transport, pickup_id=pickup["id"],
                            event_type="FAILED", occurred_at=None, quantity_kg=None,
                            reason=step.get("failure_reason"),
                            now=at + timedelta(minutes=45),
                            idempotency_key=f"seed:{flow['key']}:fail:{step_i}",
                        )
                    else:
                        pickup_domain.record_pickup_event(
                            conn, actor=transport, pickup_id=pickup["id"],
                            event_type="COLLECTED", occurred_at=None,
                            quantity_kg=Decimal(step["collected_kg"]), reason=None,
                            now=at + timedelta(minutes=30),
                            idempotency_key=f"seed:{flow['key']}:collect:{step_i}",
                        )
                        pickup_domain.record_pickup_event(
                            conn, actor=transport, pickup_id=pickup["id"],
                            event_type="DELIVERED", occurred_at=None, quantity_kg=None,
                            reason=None, now=at + timedelta(hours=float(step.get("delivered_hours_after", 1))),
                            idempotency_key=f"seed:{flow['key']}:deliver:{step_i}",
                        )
                        recipient_email = recipient_email_by_org[step["recipient_org"]]
                        pickup_domain.record_receipt(
                            conn, actor=actor_of(recipient_email), pickup_id=pickup["id"],
                            received_quantity_kg=Decimal(step["receipt_kg"]),
                            exception_reason=step.get("receipt_exception"),
                            now=at + timedelta(hours=float(step.get("delivered_hours_after", 1)), minutes=10),
                            idempotency_key=f"seed:{flow['key']}:receipt:{step_i}",
                        )
                elif step["type"] == "cancellation":
                    reservation_id = _latest_reservation(conn, donation_id, None)
                    res_domain.cancel_reservation(
                        conn, actor=coordinator, reservation_id=reservation_id,
                        reason=step.get("reason"), now=at,
                        idempotency_key=f"seed:{flow['key']}:cancel:{step_i}",
                    )
                elif step["type"] == "close":
                    # Close sweeps run after the flow's deadline has passed.
                    close_at = flow_now + timedelta(hours=2)
                    if step.get("mode") == "withdrawn":
                        transition_donation(
                            conn, donation_id, ("DRAFT", "AVAILABLE"), "WITHDRAWN",
                            now=close_at, actor_label="seed",
                        )
                    else:
                        close_donation_if_terminal(conn, donation_id, now=close_at)

        # --- marker ---------------------------------------------------------
        record_event(
            conn, aggregate_type="seed", aggregate_id="00000000-0000-4000-8000-0000000000aa",
            actor_id=None, event_type="SEED_APPLIED", idempotency_key="seed:v1",
            request_hash=None, response_result={"seeded": True},
            payload={"fixture": "data/synthetic/seed-organizations.json"}, occurred_at=now,
        )
        record_audit(
            conn, actor_id=None, organization_id=None, action="seed.apply",
            resource_type="database", resource_id=None, outcome="seeded",
            safe_summary={"fixture": "seed-organizations.json"}, occurred_at=now,
        )

    db.close_pool()
    print("seed: applied synthetic demonstration scenario (idempotent marker recorded)")
    return 0


def _latest_reservation(conn, donation_id: str, recipient_org_id) -> str:
    row = conn.execute(
        """
        SELECT id FROM reservations
        WHERE donation_id = %s AND (%s::uuid IS NULL OR recipient_org_id = %s)
        ORDER BY created_at DESC LIMIT 1
        """,
        (donation_id, recipient_org_id, recipient_org_id),
    ).fetchone()
    return str(row[0])


def _require_database_url() -> str:
    import os

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("seed: DATABASE_URL is required", file=sys.stderr)
        raise SystemExit(2)
    return url


if __name__ == "__main__":
    raise SystemExit(main())
