"""Server-owned clock and time helpers.

The API never trusts client-supplied "now": every state transition stamps
with `utcnow()` from this module. Tests (and the seed script) substitute a
deterministic clock by monkeypatching `utcnow` — documented behavior, and the
reason every domain function takes `now` as an explicit parameter.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def utcnow() -> datetime:
    """Authoritative current time (UTC, timezone-aware)."""
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    """Coerce an aware datetime to UTC; assume UTC for naive input."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def local_date_of(value_utc: datetime, tz_name: str) -> date:
    """The calendar date of a UTC instant inside the given IANA timezone."""
    return value_utc.astimezone(zoneinfo_or_utc(tz_name)).date()


def zoneinfo_or_utc(tz_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo("UTC")


def receiving_overlap_minutes(
    pickup_start_utc: datetime,
    pickup_end_utc: datetime,
    receiving_start: time,
    receiving_end: time,
    tz_name: str,
) -> float:
    """Total overlap minutes between a half-open UTC pickup window and the
    recipient's daily receiving hours (interpreted in the recipient's
    timezone). Any positive overlap across the days the window spans counts.
    """
    tz = zoneinfo_or_utc(tz_name)
    start = ensure_utc(pickup_start_utc).astimezone(tz)
    end = ensure_utc(pickup_end_utc).astimezone(tz)
    if end <= start:
        return 0.0
    total = 0.0
    day = start.date()
    while day <= end.date():
        rs = datetime.combine(day, receiving_start, tzinfo=tz)
        re = datetime.combine(day, receiving_end, tzinfo=tz)
        lo = max(start, rs)
        hi = min(end, re)
        if hi > lo:
            total += (hi - lo).total_seconds() / 60.0
        day += timedelta(days=1)
    return total


def minutes_between(earlier: datetime, later: datetime) -> float:
    return (ensure_utc(later) - ensure_utc(earlier)).total_seconds() / 60.0
