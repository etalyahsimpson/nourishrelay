"""Shared pytest fixtures: real PostgreSQL test database, migrated + seeded,
and a real uvicorn API server under test (HTTP-level, concurrency-capable).

Session scope:
- creates/drops a dedicated `nourishrelay_test` database (never the demo db)
- applies the versioned migrations and starts `uvicorn` against it

Function scope:
- truncates business tables and re-applies the idempotent seed per test, so
  every test starts from the documented synthetic demo scenario

Tests never touch the developer demo database. The API server is a real OS
process, so row-locking/concurrency tests exercise true parallel requests.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "services" / "api"
TESTS_BACKEND = REPO_ROOT / "tests" / "backend"

TRUNCATE_TABLES = [
    "audit_records", "events", "receipts", "pickups", "reservations",
    "donation_revisions", "donations", "recipient_profiles", "users",
    "organizations",
]


def _admin_url() -> str:
    url = os.environ.get("TEST_ADMIN_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL (or TEST_ADMIN_DATABASE_URL) must point at PostgreSQL")
    return url


def _test_url() -> str:
    url = _admin_url()
    # swap the database name to nourishrelay_test
    if "?" in url:  # socket-uri style: postgresql://user:@/db?host=/dir
        base, query = url.split("?", 1)
        base = base.rstrip("/")
        base = base.rsplit("/", 1)[0] + "/nourishrelay_test"
        return base + "?" + query
    base = url.rstrip("/")
    return base.rsplit("/", 1)[0] + "/nourishrelay_test"


def _create_test_database() -> str:
    admin_url = _admin_url()
    test_url = _test_url()
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS nourishrelay_test")
        conn.execute("CREATE DATABASE nourishrelay_test")
    return test_url


def _run(args: list[str], env_extra: dict[str, str]) -> None:
    env = dict(os.environ)
    env.update(env_extra)
    result = subprocess.run(
        args, cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0:
        pytest.fail(f"subprocess failed ({args[-1]}): {result.stderr[-2000:]}")


@pytest.fixture(scope="session")
def test_db_url() -> str:
    return _create_test_database()


@pytest.fixture(scope="session")
def api_server(test_db_url: str) -> str:
    """Real uvicorn server on a fixed test port; URL returned."""
    port = int(os.environ.get("TEST_API_PORT", "8110"))
    env = dict(os.environ)
    env.update(
        DATABASE_URL=test_db_url,
        SESSION_SECRET="test-session-secret-not-for-any-real-deployment",
        DEMO_MODE="true",
        WEB_PUBLIC_ORIGIN="http://localhost:3000",
        API_PUBLIC_ORIGIN=f"http://localhost:{port}",
        LOG_LEVEL="WARNING",
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        cwd=API_ROOT,
        env=env,
        stdout=open("/tmp/test-api-server.log", "ab"),
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                r = httpx.get(base + "/api/v1/health", timeout=2)
                if r.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            pytest.fail("test API server never became healthy")
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def migrated_db(test_db_url: str) -> str:
    _run([sys.executable, "scripts/migrate.py"], {"DATABASE_URL": test_db_url})
    return test_db_url


class Api:
    """Thin HTTP client with cookie session, CSRF and idempotency helpers."""

    def __init__(self, base_url: str) -> None:
        self.base = base_url
        self.client = httpx.Client(base_url=base_url, timeout=30)

    def close(self) -> None:
        self.client.close()

    def login(self, email: str, password: str = "demo-password") -> dict:
        self.client.cookies.clear()
        r = self.client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, f"login {email} -> {r.status_code}: {r.text[:300]}"
        return r.json()["user"]

    def req(self, method: str, path: str, *, json: dict | None = None,
            key: str | None = None, csrf: bool = True) -> httpx.Response:
        headers: dict[str, str] = {}
        if key:
            headers["Idempotency-Key"] = key
        if csrf and method.upper() not in ("GET", "HEAD"):
            token = self.client.cookies.get("nourishrelay_csrf")
            if token:
                headers["X-CSRF-Token"] = token
        return self.client.request(method, path, json=json, headers=headers)

    def get(self, path: str, **kw) -> httpx.Response:
        return self.req("GET", path, **kw)

    def post(self, path: str, json: dict | None = None, **kw) -> httpx.Response:
        return self.req("POST", path, json=json, **kw)


@pytest.fixture
def fresh_db(migrated_db: str, api_server: str) -> str:
    """Truncate business tables + re-seed the demo scenario for each test."""
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        conn.execute("TRUNCATE TABLE " + ", ".join(TRUNCATE_TABLES) + " CASCADE")
    _run([sys.executable, "scripts/seed.py"], {"DATABASE_URL": migrated_db})
    return migrated_db


@pytest.fixture
def api(fresh_db: str, api_server: str) -> Api:
    client = Api(api_server)
    yield client
    client.close()


@pytest.fixture
def db_conn(fresh_db: str):
    """Direct PostgreSQL connection for deterministic clock manipulation."""
    conn = psycopg.connect(fresh_db)
    yield conn
    conn.rollback()
    conn.close()


DEMO = {
    "donor": "donor@metro.demo.nourishrelay.example",
    "donor2": "donor@harvestlane.demo.nourishrelay.example",
    "northside": "recipient@northside.demo.nourishrelay.example",
    "riverside": "recipient@riverside.demo.nourishrelay.example",
    "eastview": "recipient@eastview.demo.nourishrelay.example",
    "hillside": "recipient@hillside.demo.nourishrelay.example",
    "transport": "transport@swiftcollective.demo.nourishrelay.example",
    "coordinator": "coordinator@relay.demo.nourishrelay.example",
    "analyst": "analyst@relay.demo.nourishrelay.example",
    "admin": "admin@relay.demo.nourishrelay.example",
}
