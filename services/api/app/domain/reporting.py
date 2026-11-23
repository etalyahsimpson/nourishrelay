"""Operations reporting — computed strictly from recorded events/tables.

Definitions (all kg, half-open [from, to) UTC windows, documented in
docs/DOMAIN_RULES.md §reports):
- offered_kg: donations published for pickup windows starting in the window
  (each donation counted once — reservations never multiply offered totals).
- committed_kg: stock currently held on those donations (ACCEPTED..RECEIVED
  plus FAILED after-collection), a snapshot at report time.
- collected_kg: pickups with collected_at in the window.
- received_kg: CONFIRMED receipts only (delivered is never mislabeled as
  received).
- median pickup lead time: proposal creation -> collection, only where both
  exist, else null (never fabricated).
Ratios carry numerator and denominator; a zero denominator yields null
(rendered "N/A"), never 0% or 100%.

CSV export neutralizes spreadsheet formula injection (=, +, -, @, TAB, CR,
LF leading characters) per docs/THREAT_MODEL.md.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from . import queries
from .clock import ensure_utc


def _dec_str(value) -> str:
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value))
        return str(d.quantize(Decimal("0.001")))
    except (InvalidOperation, ValueError, TypeError):
        return "0.000"


def _ratio(label: str, numerator: Decimal, denominator: Decimal, unit: str = "kg") -> dict:
    value = None
    if denominator > 0:
        value = str((numerator / denominator).quantize(Decimal("0.0001")))
    return {
        "label": label,
        "numerator": _dec_str(numerator),
        "denominator": _dec_str(denominator),
        "value": value,
        "unit": unit,
    }


def operations_report(
    conn, *, from_dt: datetime, to_dt: datetime, org_id: Optional[str],
    org_name: Optional[str], now: datetime,
) -> dict:
    if to_dt <= from_dt:
        raise ValueError("report window end must be after start")
    params = {"from": ensure_utc(from_dt), "to": ensure_utc(to_dt), "org_id": org_id}

    offered = queries.one(conn, "reports.sql", "report_offered", params)
    committed = queries.one(conn, "reports.sql", "report_committed", params)
    collected = queries.one(conn, "reports.sql", "report_collected", params)
    received = queries.one(conn, "reports.sql", "report_received", params)
    reservations_count = queries.one(conn, "reports.sql", "report_reservations_count", params)[0]
    failures = queries.one(conn, "reports.sql", "report_failures", params)[0]
    cancellations = queries.one(conn, "reports.sql", "report_cancellations", params)[0]
    median = queries.one(conn, "reports.sql", "report_median_pickup_lead_minutes", params)[0]
    cancellation_reasons = queries.run(conn, "reports.sql", "report_cancellation_reasons", params)
    failure_reasons = queries.run(conn, "reports.sql", "report_failure_reasons", params)
    categories = queries.run(conn, "reports.sql", "report_categories", params)

    offered_kg, offers = Decimal(offered[0]), int(offered[1])
    committed_kg = Decimal(committed[0])
    collected_kg, pickups_count = Decimal(collected[0]), int(collected[1])
    received_kg, receipt_count = Decimal(received[0]), int(received[1])

    return {
        "window_from": ensure_utc(from_dt),
        "window_to": ensure_utc(to_dt),
        "scope_organization_id": org_id,
        "scope_organization_name": org_name,
        "offered_kg": _dec_str(offered_kg),
        "committed_kg": _dec_str(committed_kg),
        "collected_kg": _dec_str(collected_kg),
        "received_kg": _dec_str(received_kg),
        "offers": offers,
        "reservations": int(reservations_count),
        "pickups": pickups_count,
        "failures": int(failures),
        "cancellations": int(cancellations),
        "median_pickup_lead_time_minutes": round(float(median), 1) if median is not None else None,
        "ratios": [
            _ratio("collected / offered", collected_kg, offered_kg),
            _ratio("received / collected", received_kg, collected_kg),
            _ratio("received / offered", received_kg, offered_kg),
        ],
        "cancellation_reasons": [
            {"kind": r[0], "count": int(r[1]), "quantity_kg": None} for r in cancellation_reasons
        ],
        "failure_reasons": [
            {"kind": r[0], "count": int(r[1]), "quantity_kg": _dec_str(r[2])} for r in failure_reasons
        ],
        "categories": [
            {"category": r[0], "offers": int(r[1]), "offered_kg": _dec_str(r[2])} for r in categories
        ],
        "note": (
            "All figures derive from recorded transactions in this synthetic "
            "demonstration database. Ratios include numerator and denominator; "
            "null means the denominator is zero (N/A), not 0% or 100%."
        ),
    }


# --- CSV export -------------------------------------------------------------


def _csv_cell(value) -> str:
    s = "" if value is None else str(value)
    # Neutralize spreadsheet formula injection first.
    if s and s[0] in "=+-@\t\r":
        s = "'" + s
    # Quote when needed; double any embedded quotes.
    if any(ch in s for ch in ',"\r\n'):
        s = '"' + s.replace('"', '""') + '"'
    return s


def operations_csv(report: dict) -> str:
    """Render the operations report as a safely-escaped CSV document."""
    lines: list[str] = []

    def row(*cells) -> None:
        lines.append(",".join(_csv_cell(c) for c in cells))

    window = f'{report["window_from"].isoformat()} to {report["window_to"].isoformat()}'
    scope = report.get("scope_organization_name") or "all organizations (platform scope)"

    row("section", "metric", "value", "unit", "window_utc", "scope")
    row("window", "window_start", report["window_from"].isoformat(), "UTC", window, scope)
    row("window", "window_end", report["window_to"].isoformat(), "UTC", window, scope)
    row("quantity", "offered_kg", report["offered_kg"], "kg", window, scope)
    row("quantity", "committed_kg", report["committed_kg"], "kg", window, scope)
    row("quantity", "collected_kg", report["collected_kg"], "kg", window, scope)
    row("quantity", "received_kg", report["received_kg"], "kg", window, scope)
    row("count", "offers", report["offers"], "count", window, scope)
    row("count", "reservations", report["reservations"], "count", window, scope)
    row("count", "pickups", report["pickups"], "count", window, scope)
    row("count", "failures", report["failures"], "count", window, scope)
    row("count", "cancellations", report["cancellations"], "count", window, scope)
    row(
        "count", "median_pickup_lead_time_minutes",
        report["median_pickup_lead_time_minutes"] if report["median_pickup_lead_time_minutes"] is not None else "N/A",
        "minutes", window, scope,
    )
    for ratio in report["ratios"]:
        row(
            "ratio", ratio["label"],
            ratio["value"] if ratio["value"] is not None else "N/A",
            f'{ratio["unit"]} (numerator {ratio["numerator"]}, denominator {ratio["denominator"]})',
            window, scope,
        )
    for cat in report["categories"]:
        row("category", cat["category"], cat["offered_kg"], f'kg ({cat["offers"]} offers)', window, scope)
    for item in report["cancellation_reasons"]:
        row("cancellation_reason", item["kind"], item["count"], "count", window, scope)
    for item in report["failure_reasons"]:
        row("failure_reason", item["kind"], item["count"], f'count ({item["quantity_kg"]} kg)', window, scope)
    row("note", "provenance", report["note"], "-", window, scope)
    return "\r\n".join(lines) + "\r\n"
