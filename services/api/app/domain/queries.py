"""Named-query loader for the checked-in canonical SQL files.

`services/api/sql/matching.sql` and `services/api/sql/reports.sql` are the
authoritative SQL for matching inputs and report math. This module parses the
`-- name: <query_name>` sections and caches them; a missing file or duplicate
name fails fast at first use (caught by tests).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

_SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
_cache: Dict[str, Dict[str, str]] = {}


def _parse(text: str) -> Dict[str, str]:
    queries: Dict[str, str] = {}
    current_name: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("-- name:"):
            if current_name is not None:
                queries[current_name] = "\n".join(current_lines).strip()
            current_name = stripped.split(":", 1)[1].strip()
            current_lines = []
        elif current_name is not None:
            current_lines.append(line)
    if current_name is not None:
        queries[current_name] = "\n".join(current_lines).strip()
    for name, sql in queries.items():
        if not sql:
            raise RuntimeError(f"named query {name!r} has no SQL body")
    return queries


def named_queries(filename: str) -> Dict[str, str]:
    if filename not in _cache:
        path = _SQL_DIR / filename
        if not path.exists():
            raise RuntimeError(f"canonical SQL file missing: {path}")
        parsed = _parse(path.read_text(encoding="utf-8"))
        _cache[filename] = parsed
    return _cache[filename]


def one(conn, filename: str, name: str, params: dict):
    row = conn.execute(named_queries(filename)[name], params).fetchone()
    return row


def run(conn, filename: str, name: str, params: dict):
    return conn.execute(named_queries(filename)[name], params).fetchall()
