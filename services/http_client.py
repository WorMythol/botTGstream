"""Shared aiohttp ClientSession and Twitch client singletons.

All platform integrations (polling, discord, streamer_service) share one
ClientSession to avoid exhausting OS file descriptors with short-lived sessions.

Usage:
    from services.http_client import get_http_session, close_http_session
    http = get_http_session()       # always returns the same instance
    await close_http_session()      # called once on bot shutdown
"""
from __future__ import annotations

from typing import Optional

import aiohttp
import structlog

from config import settings

logger = structlog.get_logger(__name__)

_http_session: Optional[aiohttp.ClientSession] = None
_twitch_client = None  # TwitchIntegration — imported lazily to avoid circular deps at module load


def get_http_session() -> aiohttp.ClientSession:
    """Return the shared aiohttp ClientSession, creating it on first call."""
    global _http_session
    if _http_session is None or _http_session.closed:
        timeout = aiohttp.ClientTimeout(total=settings.REQUEST_TIMEOUT)
        _http_session = aiohttp.ClientSession(timeout=timeout)
        logger.debug("http_client.session_created", timeout=settings.REQUEST_TIMEOUT)
    return _http_session


def get_twitch_client():
    """Return the shared TwitchIntegration instance (lazy-init)."""
    global _twitch_client
    if _twitch_client is None:
        from integrations import TwitchIntegration
        _twitch_client = TwitchIntegration(
            client_id=settings.TWITCH_CLIENT_ID,
            client_secret=settings.TWITCH_CLIENT_SECRET,
            http_session=get_http_session(),
        )
        logger.debug("http_client.twitch_client_created")
    return _twitch_client


async def close_http_session() -> None:
    """Close the shared aiohttp session — call once on bot shutdown."""
    global _http_session
    if _http_session and not _http_session.closed:
        await _http_session.close()
        _http_session = None
        logger.debug("http_client.session_closed")
