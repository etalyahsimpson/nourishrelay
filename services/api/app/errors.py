"""Canonical error envelope and API exception types.

Every non-2xx response the API produces has the shape:

    {"error": {"code": ..., "message": ..., "details": {...}, "request_id": ...}}

Handlers in main.py map ApiError, RequestValidationError and generic
HTTPException to this envelope. No stack traces or cross-tenant details ever
leave the process.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request


class ApiError(Exception):
    """Domain error carrying an HTTP status, stable code and safe details."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}

    def envelope(self, request_id: str) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "request_id": request_id,
            }
        }


def request_id_of(request: Request) -> str:
    """Echo client-supplied X-Request-Id when present, else generate one."""
    rid = request.headers.get("x-request-id", "").strip()
    return rid if rid else request.state.request_id  # set by middleware
