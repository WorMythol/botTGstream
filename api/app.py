"""Feature 4: FastAPI application — REST layer for VK Mini App and external tooling.

Start standalone:
    uvicorn api.app:app --host 0.0.0.0 --port 8000

Or integrated with webhook mode — the bot's aiohttp app and this FastAPI app
can be merged via `app.mount()` (see bot/main.py _run_webhook for the pattern).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import health, streamers, streams
from db.database import close_db, init_db

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize / teardown DB on startup and shutdown."""
    await init_db()
    logger.info("api.db_ready")
    yield
    await close_db()
    logger.info("api.shutdown")


app = FastAPI(
    title="botTGstream API",
    description="REST interface for stream bot management and VK Mini App integration.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — adjust origins as needed for your VK Mini App domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(streamers.router)
app.include_router(streams.router)


@app.get("/")
async def root():
    return {"message": "botTGstream API", "docs": "/docs"}
