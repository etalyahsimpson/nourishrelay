"""FastAPI application assembly: routers, canonical error envelope,
CORS (configured origin only), request ids, session cookie auth."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db
from .api import audit, auth, donations, health, organizations, pickups, reports, reservations
from .config import get_settings
from .errors import ApiError

logging.basicConfig(level=None, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("nourishrelay.api")
settings = get_settings()
logging.getLogger().setLevel(settings.log_level.upper())


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.generated_secret:
        logger.warning("DEMO_MODE: using an ephemeral generated SESSION_SECRET (per-process)")
    db.init_pool(settings.database_url)
    if not db.ping():
        logger.error("database unreachable at startup")
        raise RuntimeError("database unreachable at startup")
    logger.info("api startup complete (demo_mode=%s)", settings.demo_mode)
    try:
        yield
    finally:
        db.close_pool()


app = FastAPI(
    title="NourishRelay API",
    version="0.1.0",
    description=(
        "Food recovery coordination for SYNTHETIC demonstration organizations. "
        "Portfolio demonstration — not for real food-safety or dispatch decisions. "
        "Session auth: HttpOnly signed cookie (login), CSRF double-submit header on mutations, "
        "Idempotency-Key on state-changing actions."
    ),
    lifespan=lifespan,
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url=None,
)

# CORS: only the configured web origin (never wildcard credentials).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_public_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "HEAD", "OPTIONS"],
    allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token", "X-Request-Id"],
    expose_headers=["X-Request-Id"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex[:16]
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response


def _envelope(code: str, message: str, details: dict, request: Request) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": getattr(request.state, "request_id", "") or "",
        }
    }


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status, content=_envelope(exc.code, exc.message, exc.details, request))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    # Collapse pydantic validation errors into the canonical envelope.
    details: dict = {"fields": []}
    for err in exc.errors():
        loc = [str(x) for x in err.get("loc", []) if x != "body"]
        details["fields"].append({"field": ".".join(loc) or "body", "issue": err.get("msg", "invalid value")})
    return JSONResponse(
        status_code=422,
        content=_envelope("VALIDATION_ERROR", "Request validation failed.", details, request),
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
    code = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(
        exc.status_code, "HTTP_ERROR"
    )
    return JSONResponse(status_code=exc.status_code, content=_envelope(code, detail, {}, request))


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=_envelope("INTERNAL_ERROR", "An unexpected error occurred.", {}, request),
    )


app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(organizations.router, prefix="/api/v1")
app.include_router(donations.router, prefix="/api/v1")
app.include_router(reservations.router, prefix="/api/v1")
app.include_router(pickups.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
