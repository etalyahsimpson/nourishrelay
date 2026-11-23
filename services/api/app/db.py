"""PostgreSQL access layer (psycopg 3 + psycopg-pool).

Transactional discipline used across the domain layer:
- Every write path uses `with pool.connection() as conn:` (transaction mode:
  implicit BEGIN, explicit commit via `transaction()` blocks or manual
  `conn.commit()`), so partial failures roll back atomically.
- Acceptance/cancellation/expiry paths additionally take
  `SELECT ... FOR UPDATE` row locks on the donation (and the reservation)
  before re-evaluating committed stock — see domain/reservations.py.
- PostgreSQL is the authoritative store. Redis is only a Celery broker.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from psycopg_pool import ConnectionPool

logger = logging.getLogger("nourishrelay.db")

_pool: ConnectionPool | None = None


def init_pool(database_url: str) -> ConnectionPool:
    """Create the global connection pool (idempotent)."""
    global _pool
    if _pool is not None:
        return _pool
    _pool = ConnectionPool(
        database_url,
        min_size=1,
        max_size=10,
        max_lifetime=1800,
        name="nourishrelay-pool",
        open=True,
    )
    logger.info("connection pool opened")
    return _pool


def get_pool() -> ConnectionPool:
    if _pool is None:
        raise RuntimeError("connection pool not initialized (init_pool not called)")
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        logger.info("connection pool closed")
        _pool = None


@contextmanager
def tx() -> Iterator:
    """Yield a pooled connection inside a transaction.

    psycopg's transaction() block issues BEGIN on first statement and COMMITs
    on success / ROLLBACKs on any exception raised inside the block.
    """
    pool = get_pool()
    with pool.connection() as conn:
        with conn.transaction():
            yield conn


def ping() -> bool:
    """Readiness probe: can we reach PostgreSQL?"""
    try:
        pool = get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception:  # pragma: no cover - depends on environment
        logger.exception("database ping failed")
        return False
