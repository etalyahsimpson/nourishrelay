"""Deterministic, explanation-producing matching engine.

`compute_matches` is a PURE function of (database state, now): no LLM, no
randomness, no learned weights. Hard eligibility constraints are evaluated
first and never overridden by scores; soft ranking only orders feasible
candidates.

Weights (chosen demonstration scoring, documented in docs/DOMAIN_RULES.md):
    capacity 0.40 | reliability 0.30 | fairness 0.20 | same_area 0.10

Unknown ranking inputs are reported as NOT_AVAILABLE (with a documented
neutral 0.5 substitution that is always visible in the response) — never
presented as confident. Ties break deterministically by recipient UUID.
"""

from __future__ import annotations

from datetime import time, timedelta
from decimal import Decimal
from typing import Any

from . import queries
from .clock import local_date_of, receiving_overlap_minutes, utcnow, zoneinfo_or_utc
from .transitions import DONATION_ACTIVE

WEIGHTS: dict[str, float] = {
    "capacity": 0.40,
    "reliability": 0.30,
    "fairness": 0.20,
    "same_area": 0.10,
}
MIN_HISTORY_EVENTS = 3
FAIRNESS_WINDOW_DAYS = 14
NEUTRAL = 0.5

REQUIRES_HUMAN_REVIEW = "REQUIRES_HUMAN_REVIEW"


def _dec(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _dec_str(value: Decimal | str | float | None) -> str | None:
    if value is None:
        return None
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return str(d.quantize(Decimal("0.001")))


def _factor(name: str, raw: Any, normalized: float, known: bool, contribution: float) -> dict:
    return {
        "factor": name,
        "raw": raw,
        "normalized": round(normalized, 4),
        "known": known,
        "weight": WEIGHTS[name],
        "contribution": round(contribution, 4),
    }


def donation_level_checks(donation_row: dict, now) -> list[str]:
    """Donation-level reasons that exclude every recipient."""
    reasons: list[str] = []
    if donation_row["status"] not in DONATION_ACTIVE:
        reasons.append("DONATION_NOT_AVAILABLE")
    if donation_row["deadline"] <= now:
        reasons.append("DEADLINE_PASSED")
    return reasons


def compute_matches(conn, donation_row: dict, now=None) -> dict:
    """Compute ranked eligible recipients + excluded recipients for a donation.

    donation_row must expose: id, status, deadline, category, quantity_kg,
    handling_tags, pickup_start, pickup_end, donor_org_id, donor_org_name,
    donor_service_area.
    """
    now = now or utcnow()
    available_kg = _dec(donation_row["available_kg"])
    level_reasons = donation_level_checks(donation_row, now)
    if available_kg <= 0 and not level_reasons:
        level_reasons.append("STOCK_EXHAUSTED")

    recipients = queries.run(conn, "matching.sql", "recipient_profiles_for_matching", {})
    rows: list[dict] = []
    for r in recipients:
        org_id, name, verified, service_area = str(r[0]), r[1], r[2], r[3]
        accepted, max_day, acked = r[4], r[5], r[6]
        recv_start, recv_end, tz, active = r[7], r[8], r[9], r[10]
        rows.append(
            {
                "id": org_id,
                "name": name,
                "verified": verified,
                "service_area": service_area,
                "accepted_categories": list(accepted or []),
                "max_kg_per_day": _dec(max_day) if max_day is not None else None,
                "handling_acknowledged": list(acked or []),
                "receiving_start": recv_start,
                "receiving_end": recv_end,
                "timezone": tz,
                "active": active,
            }
        )

    excluded: list[dict] = []
    eligible: list[dict] = []

    if level_reasons:
        # Donation-level: every recipient excluded for the same reason.
        for r in rows:
            excluded.append(
                {"recipient_id": r["id"], "recipient_name": r["name"], "reasons": list(level_reasons)}
            )
        return _response(donation_row, available_kg, eligible, excluded, now)

    # Trailing received kg (fairness input) for all candidates at once.
    since = now - timedelta(days=FAIRNESS_WINDOW_DAYS)
    for r in rows:
        recv_row = queries.one(
            conn,
            "matching.sql",
            "recipient_recent_received_kg",
            {"recipient_org_id": r["id"], "since": since, "until": now},
        )
        r["recent_received_kg"] = _dec(recv_row[0])

    for r in rows:
        reasons: list[str] = []

        # Hard filters, in order (spec §5) — never overridden by scores.
        if not r["verified"]:
            reasons.append("RECIPIENT_NOT_VERIFIED")
        if not r["active"]:
            reasons.append("RECIPIENT_INACTIVE")
        if donation_row["category"] not in r["accepted_categories"]:
            reasons.append("CATEGORY_NOT_ACCEPTED")
        missing_handling = [t for t in donation_row["handling_tags"] if t not in r["handling_acknowledged"]]
        if missing_handling:
            reasons.append("HANDLING_NOT_ACKNOWLEDGED")
        try:
            overlap_minutes = receiving_overlap_minutes(
                donation_row["pickup_start"],
                donation_row["pickup_end"],
                r["receiving_start"],
                r["receiving_end"],
                r["timezone"],
            )
        except Exception:
            reasons.append("RECIPIENT_PROFILE_UNKNOWN")
            overlap_minutes = 0.0
        if overlap_minutes <= 0:
            reasons.append("RECEIVING_WINDOW_MISMATCH")

        receiving_date = local_date_of(donation_row["pickup_start"], r["timezone"])
        capacity_known = r["max_kg_per_day"] is not None and r["max_kg_per_day"] > 0
        remaining_kg = None
        if not capacity_known and r["max_kg_per_day"] is None:
            reasons.append("CAPACITY_UNKNOWN")  # REQUIRES_HUMAN_REVIEW treatment
        if capacity_known:
            usage_row = queries.one(
                conn,
                "matching.sql",
                "recipient_day_capacity_usage",
                {
                    "recipient_org_id": r["id"],
                    "tz": r["timezone"],
                    "receiving_date": receiving_date,
                },
            )
            remaining_kg = max(_dec(r["max_kg_per_day"]) - _dec(usage_row[0]), Decimal("0"))
            if remaining_kg <= 0:
                reasons.append("DAILY_CAPACITY_EXHAUSTED")

        if reasons:
            excluded.append(
                {"recipient_id": r["id"], "recipient_name": r["name"], "reasons": reasons}
            )
            continue

        max_feasible = min(available_kg, remaining_kg if remaining_kg is not None else available_kg)
        eligible.append(
            {
                "recipient": r,
                "max_feasible_kg": max_feasible,
                "overlap_minutes": overlap_minutes,
                "remaining_kg": remaining_kg,
                "receiving_date": receiving_date,
            }
        )

    # ---- Soft ranking on feasible candidates only ----
    total_recent = sum((e["recipient"]["recent_received_kg"] for e in eligible), Decimal("0"))

    for e in eligible:
        r = e["recipient"]
        breakdown: list[dict] = []

        # capacity: fraction of the day's capacity still remaining
        if r["max_kg_per_day"] and r["max_kg_per_day"] > 0:
            cap_norm = float(min(e["remaining_kg"] / r["max_kg_per_day"], Decimal("1")))
            breakdown.append(
                _factor("capacity", _dec_str(e["remaining_kg"]), cap_norm, True, WEIGHTS["capacity"] * cap_norm)
            )
        else:  # unreachable (capacity unknown recipients are excluded)
            breakdown.append(
                _factor("capacity", None, NEUTRAL, False, WEIGHTS["capacity"] * NEUTRAL)
            )

        # reliability: on-time pickup ratio when >= MIN_HISTORY_EVENTS concluded
        rel_row = queries.one(
            conn, "matching.sql", "recipient_pickup_reliability", {"recipient_org_id": r["id"]}
        )
        on_time, collected, failed = rel_row[0], rel_row[1], rel_row[2]
        concluded = collected + failed
        if concluded >= MIN_HISTORY_EVENTS:
            rel_norm = on_time / concluded
            rel_raw = f"{on_time}/{concluded}"
            breakdown.append(
                _factor("reliability", rel_raw, rel_norm, True, WEIGHTS["reliability"] * rel_norm)
            )
        else:
            breakdown.append(
                _factor("reliability", None, NEUTRAL, False, WEIGHTS["reliability"] * NEUTRAL)
            )

        # fairness: recently underallocated organizations first
        if total_recent > 0:
            fair_norm = float((total_recent - r["recent_received_kg"]) / total_recent)
        else:
            fair_norm = 1.0  # no allocations in window: all equally underallocated
        breakdown.append(
            _factor(
                "fairness",
                _dec_str(r["recent_received_kg"]),
                fair_norm,
                True,
                WEIGHTS["fairness"] * fair_norm,
            )
        )

        # same_area: deterministic service-area LABEL equality (not road distance)
        same = (
            donation_row["donor_service_area"] is not None
            and r["service_area"] is not None
            and donation_row["donor_service_area"].strip().lower() == r["service_area"].strip().lower()
        )
        area_norm = 1.0 if same else 0.0
        breakdown.append(
            _factor("same_area", r["service_area"], area_norm, True, WEIGHTS["same_area"] * area_norm)
        )

        score = sum(f["contribution"] for f in breakdown)
        e["score"] = round(score, 4)
        e["breakdown"] = breakdown

    eligible.sort(key=lambda e: (-e["score"], e["recipient"]["id"]))

    eligible_payload = [
        {
            "recipient_id": e["recipient"]["id"],
            "recipient_name": e["recipient"]["name"],
            "max_feasible_kg": _dec_str(e["max_feasible_kg"]),
            "score": e["score"],
            "score_breakdown": e["breakdown"],
            "reasons": [
                f"category '{donation_row['category']}' accepted",
                f"handling covers all {len(donation_row['handling_tags'])} declared tag(s)",
                f"receiving window overlap {e['overlap_minutes']:.0f} min on {e['receiving_date'].isoformat()}",
                (
                    f"capacity remaining {_dec_str(e['remaining_kg'])} kg of {_dec_str(e['recipient']['max_kg_per_day'])} kg/day"
                    if e["recipient"]["max_kg_per_day"] is not None
                    else "capacity profile unknown (human review)"
                ),
                (
                    f"reliability from {MIN_HISTORY_EVENTS}+ concluded pickups"
                    if any(f["factor"] == "reliability" and f["known"] for f in e["breakdown"])
                    else "insufficient pickup history: neutral reliability (NOT_AVAILABLE)"
                ),
                "demonstration scoring only — never a transport or food-safety guarantee",
            ],
            "zero_history": not any(
                f["factor"] == "reliability" and f["known"] for f in e["breakdown"]
            ),
        }
        for e in eligible
    ]
    excluded_payload = [
        {"recipient_id": x["recipient_id"], "recipient_name": x["recipient_name"], "reasons": x["reasons"]}
        for x in excluded
    ]
    return _response(donation_row, available_kg, eligible_payload, excluded_payload, now)


def _response(donation_row, available_kg, eligible, excluded, now) -> dict:
    return {
        "donation_id": str(donation_row["id"]),
        "available_kg": _dec_str(available_kg),
        "weights": dict(WEIGHTS),
        "eligible": eligible,
        "excluded": excluded,
        "generated_at": now,
        "note": (
            "Deterministic constraint-first matching with explanation. Hard "
            "constraints (verification, category, handling, receiving-window "
            "overlap, capacity, deadline, stock) always outrank the soft score. "
            "Scores are chosen demonstration weights, not a guarantee of safe "
            "transport or food safety."
        ),
    }
