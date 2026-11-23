"""Auth contract: 401 anonymous, generic 401 bad credentials, cookies/CSRF,
logout, /me hygiene, login rate limiting."""

from __future__ import annotations

import httpx

from conftest import DEMO


def test_anonymous_requests_rejected(api):
    r = api.get("/api/v1/donations")
    assert r.status_code == 401
    body = r.json()["error"]
    assert body["code"] == "UNAUTHENTICATED"
    assert body["request_id"]


def test_login_bad_credentials_generic_401(api):
    r = api.client.post("/api/v1/auth/login",
                        json={"email": "ghost@demo.nourishrelay.example", "password": "wrong"})
    assert r.status_code == 401
    assert "Invalid email or password." == r.json()["error"]["message"]
    # no hint about which part failed / account existence
    r2 = api.client.post("/api/v1/auth/login",
                         json={"email": DEMO["donor"], "password": "wrong"})
    assert r2.status_code == 401
    assert r2.json()["error"]["code"] == "UNAUTHENTICATED"


def test_login_sets_http_only_session_and_csrf_cookie(api):
    r = api.client.post("/api/v1/auth/login",
                        json={"email": DEMO["donor"], "password": "demo-password"})
    assert r.status_code == 200
    session = r.cookies.get("nourishrelay_session")
    csrf = r.cookies.get("nourishrelay_csrf")
    assert session and csrf
    set_cookie = r.headers.get_list("set-cookie") if hasattr(r.headers, "get_list") else [r.headers.get("set-cookie", "")]
    raw = "; ".join(str(c) for c in r.headers.get_list("set-cookie")) if hasattr(r.headers, "get_list") else str(r.headers)
    assert "httponly" in raw.lower()
    assert "samesite=lax" in raw.lower()
    user = r.json()["user"]
    assert user["role"] == "donor"
    assert user["email"] == DEMO["donor"]
    assert "password_hash" not in user and "password" not in user


def test_me_returns_server_derived_identity(api):
    api.login(DEMO["coordinator"])
    r = api.get("/api/v1/auth/me")
    assert r.status_code == 200
    user = r.json()["user"]
    assert user["role"] == "coordinator"
    assert user["organization_id"] is None or user["organization_id"]
    assert "password_hash" not in user


def test_logout_clears_session(api):
    api.login(DEMO["donor"])
    r = api.post("/api/v1/auth/logout", key="logout-1")
    assert r.status_code == 204
    r = api.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_login_rate_limit(api):
    email = "ratelimit-probe@demo.nourishrelay.example"
    for _ in range(10):
        r = api.client.post("/api/v1/auth/login",
                            json={"email": email, "password": "nope"})
        assert r.status_code == 401
    r = api.client.post("/api/v1/auth/login", json={"email": email, "password": "nope"})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "RATE_LIMITED"


def test_mutation_without_csrf_rejected(api):
    api.login(DEMO["donor"])
    r = api.client.post("/api/v1/donations", json={"category": "produce"})
    # raw client request -> no X-CSRF-Token header
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "CSRF_TOKEN_INVALID"
