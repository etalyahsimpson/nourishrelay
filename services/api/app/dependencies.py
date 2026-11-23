"""FastAPI dependencies: session identity, role/organization guards, CSRF."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Callable, Iterable

from fastapi import Cookie, Depends, Header, Request

from . import db
from .errors import ApiError
from .security import CSRF_COOKIE, CSRF_HEADER, csrf_tokens_match, verify_session_token

# Roles that act on behalf of the platform rather than a member organization.
PLATFORM_ROLES = {"coordinator", "admin", "analyst"}


@dataclass(frozen=True)
class CurrentUser:
    id: str
    role: str
    organization_id: str | None
    display_name: str
    email: str


def get_current_user(
    request: Request,
    nourishrelay_session: Annotated[str | None, Cookie()] = None,
) -> CurrentUser:
    """Resolve the signed-in user from the session cookie (server-owned)."""
    if not nourishrelay_session:
        raise ApiError(401, "UNAUTHENTICATED", "Sign in to continue.")
    claims = verify_session_token(nourishrelay_session)
    if not claims:
        raise ApiError(401, "UNAUTHENTICATED", "Session invalid or expired.")
    user_id = claims["sub"]
    with db.tx() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.role, u.organization_id, u.display_name, u.email,
                   o.kind AS org_kind
            FROM users u LEFT JOIN organizations o ON o.id = u.organization_id
            WHERE u.id = %s AND u.active
            """,
            (user_id,),
        ).fetchone()
    if row is None:
        raise ApiError(401, "UNAUTHENTICATED", "Session no longer valid.")
    return CurrentUser(
        id=str(row[0]),
        role=row[1],
        organization_id=str(row[2]) if row[2] else None,
        display_name=row[3],
        email=row[4],
    )


def enforce_csrf(
    request: Request,
    nourishrelay_csrf: Annotated[str | None, Cookie()] = None,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> None:
    """Double-submit CSRF check for authenticated state-changing requests."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if not csrf_tokens_match(nourishrelay_csrf, x_csrf_token):
        raise ApiError(403, "CSRF_TOKEN_INVALID", "Missing or invalid CSRF token.")


def require_roles(*roles: str) -> Callable:
    """Dependency factory limiting the route to the given roles."""

    allowed = set(roles)

    def checker(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role not in allowed:
            raise ApiError(403, "FORBIDDEN", "Your role cannot perform this action.")
        return user

    return checker


def require_platform(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    """Coordinator/admin/analyst platform view (org-independent)."""
    if user.role not in {"coordinator", "admin", "analyst"}:
        raise ApiError(403, "FORBIDDEN", "Platform role required.")
    return user


def require_org_role(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    """User must belong to an organization (all non-platform roles)."""
    if user.organization_id is None:
        raise ApiError(403, "FORBIDDEN", "An organization membership is required.")
    return user


def opaque_404() -> ApiError:
    """Uniform not-found for resources the caller may not know about."""
    return ApiError(404, "NOT_FOUND", "Resource not found.")
