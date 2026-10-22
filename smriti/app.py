"""Application factory. Tests build isolated apps from explicit settings."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.routers import documents, jobs, patients
from smriti.config import BASE_DIR, Settings, load_settings
from smriti.db import create_db_engine, init_db


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    dist = (BASE_DIR / "web" / "dist").resolve()
    if settings.upload_dir.resolve().is_relative_to(dist):
        raise ValueError("SMRITI_UPLOAD_DIR must be outside web/dist")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    init_db(settings.db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        app.state.engine.dispose()

    app = FastAPI(title="Smriti", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = create_db_engine(settings.db_path)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_request: Request, exc: StarletteHTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            content = detail
        else:
            content = {"error": {"code": "http_error", "message": str(detail)}}
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError):
        errors = exc.errors()
        field = None
        if errors:
            location = errors[0].get("loc", ())
            if len(location) > 1:
                field = ".".join(str(part) for part in location[1:])
        error = {"code": "validation_error", "message": "Malformed request"}
        if field is not None:
            error["field"] = field
        return JSONResponse(status_code=400, content={"error": error})

    app.include_router(patients.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "profile": settings.profile}

    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")

    return app
