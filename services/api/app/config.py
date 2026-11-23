"""Application configuration.

All values arrive from the environment (12-factor). Demo mode permits an
ephemeral generated session secret so local development never depends on a
hard-coded secret; non-demo deployments MUST supply SESSION_SECRET.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get(
        "DATABASE_URL", "postgresql://postgres@localhost:5432/postgres"))
    redis_url: str = field(default_factory=lambda: os.environ.get("REDIS_URL", ""))
    session_secret: str = field(default_factory=lambda: os.environ.get("SESSION_SECRET", ""))
    session_ttl_seconds: int = field(default_factory=lambda: int(
        os.environ.get("SESSION_TTL_SECONDS", "43200")))  # 12h demo sessions
    web_public_origin: str = field(default_factory=lambda: os.environ.get(
        "WEB_PUBLIC_ORIGIN", "http://localhost:3000"))
    api_public_origin: str = field(default_factory=lambda: os.environ.get(
        "API_PUBLIC_ORIGIN", "http://localhost:8000"))
    demo_mode: bool = field(default_factory=lambda: _env_bool("DEMO_MODE", True))
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))
    login_rate_limit: int = field(default_factory=lambda: int(
        os.environ.get("LOGIN_RATE_LIMIT", "10")))  # failed attempts per window
    login_rate_window_seconds: int = field(default_factory=lambda: int(
        os.environ.get("LOGIN_RATE_WINDOW_SECONDS", "3600")))
    cookie_secure: bool = False
    generated_secret: bool = False


_settings: Settings | None = None


def get_settings() -> Settings:
    """Lazily build and cache settings (import-safe for tests that set env)."""
    global _settings
    if _settings is None:
        _settings = Settings()
        if not _settings.session_secret:
            if _settings.demo_mode:
                # Demo-only ephemeral secret (process-local, never persisted,
                # never hard-coded). Non-demo deployments must provide one.
                _settings.session_secret = secrets.token_urlsafe(48)
                _settings.generated_secret = True
            else:
                raise RuntimeError(
                    "SESSION_SECRET must be set to a unique random value on "
                    "non-demo deployments (see .env.example)"
                )
        _settings.cookie_secure = _settings.api_public_origin.startswith("https://")
    return _settings


def reset_settings_cache() -> None:
    """Test hook: re-read the environment on next access."""
    global _settings
    _settings = None
