"""Application factory. Tests build isolated apps from explicit settings."""

from __future__ import annotations

import logging
import hashlib
import os
import time
import uuid
from contextlib import asynccontextmanager

# Runtime extraction is local-only; prevent model libraries from probing registries.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.routers import auth, documents, jobs, patients, reports, review
from smriti.config import BASE_DIR, Settings, load_settings
from smriti.db import create_db_engine, init_db
from smriti.observability import Diagnostics, sanitized_logging
from smriti.service import Service


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    dist = (BASE_DIR / "web" / "dist").resolve()
    if settings.upload_dir.resolve().is_relative_to(dist):
        raise ValueError("SMRITI_UPLOAD_DIR must be outside web/dist")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    init_db(settings.db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        diagnostics = app.state.diagnostics
        with sanitized_logging(diagnostics):
            service = app.state.service
            try:
                try:
                    diagnostics.start()
                except Exception:
                    # Logging availability never authorizes processing or prevents a safe shutdown.
                    diagnostics.emit("logging_degraded", component="logging", code="unavailable")
                service.start()
                diagnostics.emit("service_started", component="service")
                yield
            finally:
                try:
                    if not service.pause():
                        diagnostics.emit("cleanup_failed", component="service", cleanup_outcome="unconfirmed")
                        raise RuntimeError("Owned coordinator shutdown is unconfirmed")
                    app.state.engine.dispose()
                    diagnostics.emit("service_stopped", component="service", cleanup_outcome="confirmed")
                finally:
                    diagnostics.close()

    app = FastAPI(title="Smriti", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = create_db_engine(settings.db_path)
    app.state.diagnostics = Diagnostics(settings)
    app.state.service = Service(app.state.engine, settings, app.state.diagnostics)

    @app.middleware("http")
    async def request_diagnostics(request: Request, call_next):
        request_id = uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            response = JSONResponse(status_code=500, content={"error": {"code": "request_failed", "message": "The local request failed. Try again.", "support_id": request_id}})
        response.headers["X-Request-ID"] = request_id
        route = getattr(request.scope.get("route"), "path", "unmatched")
        # FastAPI's included-router scope can retain the route's unprefixed template.
        if request.url.path.startswith("/api/") and route.startswith("/") and not route.startswith("/api/"):
            route = "/api" + route
        if request.url.path == "/v1/models" and response.status_code == 404:
            client = request.scope.get("client") or (None, None)
            ua = request.headers.get("user-agent", "")[:1024]
            family = next((name for prefix, name in (("python-requests/", "python-requests"), ("python-httpx/", "httpx"),
                                                    ("curl/", "curl"), ("Mozilla/", "browser")) if ua.startswith(prefix)),
                          "other" if ua else "unavailable")
            app.state.diagnostics.emit("model_endpoint_not_found", component="http", request_id=request_id,
                route="/v1/models", host=client[0], port=client[1], ua_family=family,
                ua_fingerprint=hashlib.sha256(ua.encode()).hexdigest()[:16] if ua else None)
        if response.status_code >= 400 or route not in {"/health", "/api/health", "/api/jobs", "/api/jobs/{job_id}"}:
            app.state.diagnostics.emit("request_failed" if response.status_code >= 500 else "request_finished",
                component="http", request_id=request_id, method=request.method, status=response.status_code,
                route=route, duration_ms=(time.monotonic() - started) * 1000)
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_request: Request, exc: StarletteHTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            content = detail
        else:
            content = {"error": {"code": "http_error", "message": str(detail)}}
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        field = None
        if errors:
            location = errors[0].get("loc", ())
            if len(location) > 1:
                names = {"username", "password", "alias", "sex", "dob", "action", "value_num", "value_text", "unit_norm", "analyte_id", "page", "offset", "scope", "version", "category", "report_date", "title", "facility_name", "approved", "extra_redaction_boxes"}
                field = next((part for part in location[1:] if isinstance(part, str) and part in names), None)
        error = {"code": "validation_error", "message": "Malformed request"}
        if request.url.path == "/api/auth/register":
            messages = {
                "username": "Use 3–32 characters: letters, numbers, dots, underscores, or hyphens.",
                "password": "Use a password with 8–128 characters.",
                "alias": "Enter a patient alias with 1–64 characters.",
                "sex": "Choose a listed sex or leave it unrecorded.",
                "dob": "Enter a valid date of birth.",
            }
            error["message"] = messages.get(field, "Check the account fields and try again.")
        elif errors:
            raw_msg = str(errors[0].get("msg", "")).replace("Value error, ", "").strip()
            if raw_msg and raw_msg != "Field required":
                error["message"] = raw_msg
            elif field:
                error["message"] = f"Invalid or missing {field}."
        if field is not None:
            error["field"] = field
        app.state.diagnostics.emit("validation_failed", component="http", request_id=getattr(request.state, "request_id", None))
        return JSONResponse(status_code=400, content={"error": error})

    app.include_router(auth.router, prefix="/api")
    app.include_router(patients.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")
    app.include_router(review.router, prefix="/api")

    @app.get("/health")
    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "profile": settings.profile}

    @app.get("/api/system/gemini-status")
    def gemini_status() -> dict:
        if not settings.gemini_api_key or settings.demo:
            return {
                "configured": False,
                "status": "not_configured",
                "model": settings.gemini_model_id,
                "message": "Gemini API key is not configured or in demo mode.",
            }
        try:
            from google import genai
            client = genai.Client(api_key=settings.gemini_api_key)
            client.models.generate_content(model=settings.gemini_model_id, contents="ping")
            return {
                "configured": True,
                "status": "ready",
                "model": settings.gemini_model_id,
                "message": "Gemini API is active and ready.",
            }
        except Exception as exc:
            err_str = str(exc)
            if "402" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                return {
                    "configured": True,
                    "status": "credits_depleted",
                    "model": settings.gemini_model_id,
                    "message": "Prepayment credits depleted on Google AI Studio (402 Resource Exhausted). Manage project credits at https://ai.studio/projects.",
                }
            elif "429" in err_str:
                return {
                    "configured": True,
                    "status": "rate_limited",
                    "model": settings.gemini_model_id,
                    "message": "Gemini API rate limit exceeded (429).",
                }
            elif "400" in err_str or "403" in err_str or "API_KEY_INVALID" in err_str:
                return {
                    "configured": True,
                    "status": "invalid_key",
                    "model": settings.gemini_model_id,
                    "message": "Invalid or unauthorized GEMINI_API_KEY.",
                }
            return {
                "configured": True,
                "status": "connection_error",
                "model": settings.gemini_model_id,
                "message": f"Gemini API error ({type(exc).__name__}).",
            }

    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")

    return app
