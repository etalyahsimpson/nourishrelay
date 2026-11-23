#!/usr/bin/env python
"""Versioned SQL migration runner for NourishRelay.

Applies services/api/migrations/*.sql in lexicographic version order inside
the transaction each file declares, and records (version, sha256 checksum,
applied_at, duration) in schema_migrations. Re-runs are idempotent: applied
versions are skipped; a checksum mismatch on an applied version is a hard
error (drift detection).

Usage: DATABASE_URL=... python services/api/scripts/migrate.py
Exit codes: 0 success / already current; 1 failure.
"""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # services/api

import psycopg  # noqa: E402

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url, autocommit=True)


def applied_versions(conn: psycopg.Connection) -> dict[str, str]:
    try:
        rows = conn.execute(
            "SELECT version, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    except psycopg.errors.UndefinedTable:
        return {}


def _strip_transaction_control(sql: str) -> str:
    """Files carry their own BEGIN/COMMIT so they remain runnable via psql;
    the runner wraps each file in its own managed transaction instead."""
    lines = []
    for line in sql.splitlines():
        stripped = line.strip().upper().rstrip(";")
        if stripped in {"BEGIN", "START TRANSACTION", "COMMIT", "END TRANSACTION", "ROLLBACK"}:
            continue
        lines.append(line)
    return "\n".join(lines)


def main() -> int:
    database_url = _require_database_url()
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print("migrate: no migration files found", file=sys.stderr)
        return 1
    with connect(database_url) as conn:
        current = applied_versions(conn)
        applied_now = 0
        for path in files:
            version = path.name.split(".", 1)[0]
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            if version in current:
                if current[version] != checksum:
                    print(
                        f"migrate: checksum drift for {version} "
                        "(recorded file was modified after being applied)",
                        file=sys.stderr,
                    )
                    return 1
                print(f"migrate: {version} already applied (checksum ok)")
                continue
            started = time.monotonic()
            with conn.transaction():
                conn.execute(_strip_transaction_control(sql))
                conn.execute(
                    """
                    INSERT INTO schema_migrations (version, checksum, applied_at, duration_ms)
                    VALUES (%s, %s, now(), 0)
                    """,
                    (version, checksum),
                )
            duration_ms = int((time.monotonic() - started) * 1000)
            conn.execute(
                "UPDATE schema_migrations SET duration_ms = %s WHERE version = %s",
                (duration_ms, version),
            )
            print(f"migrate: applied {version} ({path.name}) in {duration_ms} ms")
            applied_now += 1
        if not applied_now:
            print("migrate: database already current")
    return 0


def _require_database_url() -> str:
    import os

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("migrate: DATABASE_URL is required", file=sys.stderr)
        raise SystemExit(2)
    return url


if __name__ == "__main__":
    raise SystemExit(main())
