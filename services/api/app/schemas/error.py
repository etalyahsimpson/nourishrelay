"""Error envelope schema (docs/OpenAPI) for every non-2xx response."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}
    request_id: str


class ErrorEnvelope(BaseModel):
    error: ErrorBody
