"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import auth, planner, progress, subjects, teams
from app.api.services import Forbidden, NotFound, ServiceError
from app.core.config import settings
from app.db.session import init_db
from app.engine.extraction.extractors import SUPPORTED_EXTENSIONS
from app.engine.llm import llm_client
from app.planner.rules import (
    BREAK_MINUTES,
    MAX_BLOCK_MINUTES,
    MAX_DAILY_STUDY_MINUTES,
    MAX_PACKAGE_MINUTES,
    MIN_BLOCK_MINUTES,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")

DESCRIPTION = """
Study Intelligence Platform.

Turns uploaded notes (PDF / DOCX / TXT) into structured study intelligence,
workable packages of at most 90 minutes, and an executable study plan.

The Study Intelligence Engine may use the Gemini API for content structuring.
**The Planner Engine is always deterministic Python - no LLM is involved in
scheduling, priority scoring, time estimation or work distribution.**
"""


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    provider = llm_client.active_provider
    logger.info("Database ready. Knowledge-extraction provider: %s", provider)
    if provider == "none":
        logger.info(
            "No GEMINI_API_KEY or LOCAL_LLM_URL set - using the deterministic "
            "structural analyser. Everything still works offline."
        )
    try:
        yield
    finally:
        await llm_client.aclose()


app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

prefix = settings.api_prefix
app.include_router(auth.router, prefix=prefix)
app.include_router(subjects.router, prefix=prefix)
app.include_router(planner.router, prefix=prefix)
app.include_router(progress.router, prefix=prefix)
app.include_router(teams.router, prefix=prefix)
app.include_router(teams.subject_router, prefix=prefix)


@app.exception_handler(ServiceError)
async def service_error_handler(_request: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.exception_handler(NotFound)
async def not_found_handler(_request: Request, exc: NotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(Forbidden)
async def forbidden_handler(_request: Request, exc: Forbidden) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", ())[1:]) or "request"
    return JSONResponse(
        status_code=422,
        content={"detail": f"{field}: {first.get('msg', 'invalid value')}"},
    )


@app.exception_handler(StarletteHTTPException)
async def http_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "docs": "/docs",
        "api": prefix,
    }


@app.get(f"{prefix}/health", tags=["meta"])
def health() -> dict:
    return {
        "status": "ok",
        "llm_provider": llm_client.active_provider,
        "supported_uploads": sorted(SUPPORTED_EXTENSIONS),
        "planner_rules": {
            "max_daily_minutes": MAX_DAILY_STUDY_MINUTES,
            "block_minutes": [MIN_BLOCK_MINUTES, MAX_BLOCK_MINUTES],
            "break_minutes_after_blocks": BREAK_MINUTES,
            "max_package_minutes": MAX_PACKAGE_MINUTES,
            "llm_used": False,
        },
    }
