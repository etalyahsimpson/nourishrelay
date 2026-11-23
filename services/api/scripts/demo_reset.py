#!/usr/bin/env python
"""demo-reset: reinitialize the SYNTHETIC demonstration database.

Truncates all business tables in the current DATABASE_URL database and
re-applies the seed scenario. Safe ONLY because this project's database is
dedicated synthetic demonstration data (see data/synthetic/README.md);
the script refuses to run unless the seed marker/schema is present, and it
never touches files or other databases. Requires explicit invocation —
nothing in the API or workers calls it automatically.

Usage: DATABASE_URL=... python services/api/scripts/demo_reset.py
Exit codes: 0 reset+seed complete; 1 failure.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # services/api

import psycopg  # noqa: E402

TABLES = [
    "audit_records", "events", "receipts", "pickups", "reservations",
    "donation_revisions", "donations", "recipient_profiles", "users",
    "organizations",
]


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("demo_reset: DATABASE_URL is required", file=sys.stderr)
        return 1
    with psycopg.connect(url, autocommit=True) as conn:
        try:
            marker = conn.execute(
                "SELECT COUNT(*) FROM schema_migrations"
            ).fetchone()
        except psycopg.errors.UndefinedTable:
            print(
                "demo_reset: schema_migrations missing — run scripts/migrate.py first",
                file=sys.stderr,
            )
            return 1
        if marker[0] == 0:
            print(
                "demo_reset: no migrations recorded — run scripts/migrate.py first",
                file=sys.stderr,
            )
            return 1
        tables = ", ".join(TABLES)
        conn.execute(f"TRUNCATE TABLE {tables} CASCADE")
        print("demo_reset: synthetic demonstration tables truncated")
    # Re-seed via the canonical seed script.
    import runpy

    runpy.run_path(str(Path(__file__).resolve().parent / "seed.py"), run_name="__main__")
    print("demo_reset: synthetic demonstration scenario restored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
