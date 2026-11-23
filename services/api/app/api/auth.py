"""Demo authentication: login (JWT session cookie + CSRF token), logout, me.

Identities are SYNTHETIC demo accounts seeded by scripts/seed.py. 401 is
generic on failure (no user enumeration), login failures are rate limited.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from .. import db
from ..dependencies import CurrentUser, enforce_csrf, get_current_user
from ..domain.clock import utcnow  # noqa: F401  (imported for tests/monkeypatching)
from ..errors import ApiError
from ..security import (
    CSRF_COOKIE,
    SESSION_COOKIE as SESSION_COOKIE_NAME,
    get_login_limiter,
    new_csrf_token,
    session_cookie_attributes,
    verify_password,
    issue_session_token,
)
from ..config import get_settings
from ..schemas.auth import LoginRequest, LoginResponse, MeResponse, UserSummary

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, response: Response) -> dict:
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    limiter = get_login_limiter()
    if limiter.is_blocked(body.email, client_ip):
        raise ApiError(
            429, "RATE_LIMITED", "Too many failed sign-in attempts. Try again later."
        )
    with db.tx() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.password_hash, u.role, u.organization_id, u.active,
                   u.display_name, u.email
            FROM users u WHERE lower(u.email) = lower(%s)
            """,
            (body.email,),
        ).fetchone()
    ok = False
    user = None
    if row is not None and row[4]:
        ok = verify_password(body.password, row[1])
        user = row
    if not ok:
        limiter.register_failure(body.email, client_ip)
        # Generic 401: never reveal whether the account exists.
        raise ApiError(401, "UNAUTHENTICATED", "Invalid email or password.")

    limiter.reset(body.email, client_ip)
    token = issue_session_token(str(row[0]), row[2], str(row[3]) if row[3] else None,
                                settings.session_ttl_seconds)
    response.set_cookie(value=token, **session_cookie_attributes(settings.session_ttl_seconds))
    response.set_cookie(
        key=CSRF_COOKIE,
        value=new_csrf_token(),
        max_age=settings.session_ttl_seconds,
        httponly=False,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return {
        "user": {
            "id": str(user[0]),
            "role": user[2],
            "organization_id": str(user[3]) if user[3] else None,
            "display_name": user[5],
            "email": user[6],
        }
    }


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    user: CurrentUser = Depends(get_current_user),
    _csrf: None = Depends(enforce_csrf),
) -> None:
    """Clear the session and CSRF cookies (client discards state)."""
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return None


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"user": UserSummary(
        id=user.id, role=user.role, organization_id=user.organization_id,
        display_name=user.display_name, email=user.email,
    ).model_dump()}
