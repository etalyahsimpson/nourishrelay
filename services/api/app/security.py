"""Session security: bcrypt password hashing, signed JWT session cookies,
CSRF double-submit tokens and a bounded login attempt limiter.

Choices (documented in docs/DECISIONS.md):
- bcrypt (pinned adapter) for synthetic demo account password hashing;
  no custom cryptography is authored here.
- PyJWT HS256 with the process/session secret; claims carry only ids/expiry.
- Cookies: HttpOnly + SameSite=Lax + Secure (when origin is https) — session
  tokens are never placed in localStorage.
- CSRF: double-submit cookie pattern — a non-HttpOnly `nourishrelay_csrf`
  cookie must be echoed by the `X-CSRF-Token` header on every authenticated
  state-changing request (constant-time comparison).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from .config import get_settings

SESSION_COOKIE = "nourishrelay_session"
CSRF_COOKIE = "nourishrelay_csrf"
CSRF_HEADER = "x-csrf-token"
_BCRYPT_ROUNDS = 12


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("ascii")


def verify_password(plain: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def issue_session_token(user_id: str, role: str, organization_id: str | None, ttl_seconds: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "role": role,
        "org": str(organization_id) if organization_id else None,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(claims, settings.session_secret, algorithm="HS256")


def verify_session_token(token: str) -> dict[str, Any] | None:
    """Return claims for a valid, unexpired token; None otherwise."""
    settings = get_settings()
    try:
        claims = jwt.decode(token, settings.session_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if "sub" not in claims or "role" not in claims:
        return None
    return claims


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_tokens_match(cookie_token: str | None, header_token: str | None) -> bool:
    if not cookie_token or not header_token:
        return False
    return hmac.compare_digest(cookie_token, header_token)


def session_cookie_attributes(max_age: int) -> dict[str, Any]:
    settings = get_settings()
    return {
        "key": SESSION_COOKIE,
        "max_age": max_age,
        "httponly": True,
        "samesite": "lax",
        "secure": settings.cookie_secure,
        "path": "/",
    }


# --- Login attempt limiter (in-memory, demo-scaled) ------------------------


class LoginLimiter:
    """Small bounded limiter for failed demo login attempts.

    Keyed by (email, client ip). Not shared state — per process; adequate for
    the demo threat model and documented as such (single-instance deployment).
    """

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._failures: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, now: float, entries: list[float]) -> list[float]:
        return [t for t in entries if now - t < self.window]

    def register_failure(self, email: str, ip: str) -> None:
        now = time.monotonic()
        with self._lock:
            key = (email.lower(), ip)
            entries = self._prune(now, self._failures.get(key, []))
            entries.append(now)
            self._failures[key] = entries

    def is_blocked(self, email: str, ip: str) -> bool:
        now = time.monotonic()
        with self._lock:
            entries = self._prune(now, self._failures.get((email.lower(), ip), []))
            self._failures[(email.lower(), ip)] = entries
            return len(entries) >= self.max_attempts

    def reset(self, email: str, ip: str) -> None:
        with self._lock:
            self._failures.pop((email.lower(), ip), None)


_login_limiter: LoginLimiter | None = None


def get_login_limiter() -> LoginLimiter:
    global _login_limiter
    if _login_limiter is None:
        settings = get_settings()
        _login_limiter = LoginLimiter(
            settings.login_rate_limit, settings.login_rate_window_seconds
        )
    return _login_limiter


def fingerprint_request(payload: Any) -> str:
    """Canonical JSON fingerprint for idempotency replay comparison."""
    canonical = hashlib.sha256()
    canonical.update(_canonical_json(payload).encode("utf-8"))
    return canonical.hexdigest()


def _canonical_json(value: Any) -> str:
    import json

    def sort_part(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: sort_part(v[k]) for k in sorted(v)}
        if isinstance(v, list):
            return [sort_part(x) for x in v]
        if isinstance(v, (datetime,)):
            return v.astimezone(timezone.utc).isoformat()
        return v

    return json.dumps(sort_part(value), separators=(",", ":"), ensure_ascii=False)
