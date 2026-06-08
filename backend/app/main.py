"""FastAPI application entry point: app factory, middleware, and router registration."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.sync import router as sync_router
from app.core.config import get_settings, settings
from app.core.database import check_database_connection, close_database

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup: validate config, optional DB check. Shutdown: dispose connection pool."""
    # Re-run settings validation at startup (redirect allowlist, secrets, Fernet key).
    cfg = get_settings()
    logger.info(
        "Security config OK: frontend redirect allowlisted, encryption key separate from JWT"
    )

    if cfg.db_check_on_startup:
        await check_database_connection()
        logger.info("Database connection verified at startup")

    yield

    await close_database()
    logger.info("Database connection pool closed")


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth")
app.include_router(sync_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe — confirms the API process is running."""
    return {"status": "ok", "app": settings.app_name}
