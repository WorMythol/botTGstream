"""Twitch Helix API integration with OAuth client credentials and rate-limit handling."""
from __future__ import annotations

import re
import time
from typing import Optional

import aiohttp
import structlog

from integrations.base import BasePlatformIntegration, PlatformCheckResult, StreamInfo

logger = structlog.get_logger(__name__)

_TWITCH_AUTH = "https://id.twitch.tv/oauth2/token"
_TWITCH_API = "https://api.twitch.tv/helix"


class TwitchIntegration(BasePlatformIntegration):
    """Twitch Helix API client with automatic OAuth token management."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        http_session: aiohttp.ClientSession,
        access_token: Optional[str] = None,
        token_expires_at: Optional[float] = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = http_session
        self._access_token = access_token
        self._token_expires_at = token_expires_at or 0.0
        self._rate_limit_reset: float = 0.0

    # ── Public interface ──────────────────────────────────────────────────────

    async def check_live(self, platform_id: str) -> PlatformCheckResult:
        """Check if Twitch user is currently live. platform_id = Twitch login name."""
        try:
            await self._ensure_token()
            headers = {
                "Client-Id": self._client_id,
                "Authorization": f"Bearer {self._access_token}",
            }
            params = {"user_login": platform_id}
            async with self._session.get(
                f"{_TWITCH_API}/streams", headers=headers, params=params
            ) as resp:
                self._parse_rate_limit_headers(resp.headers)
                if resp.status == 429:
                    reset = float(resp.headers.get("Ratelimit-Reset", time.time() + 60))
                    self._rate_limit_reset = reset
                    logger.warning("twitch.rate_limited", reset_at=reset)
                    return PlatformCheckResult(is_live=False, error="rate_limited")
                resp.raise_for_status()
                data = await resp.json()

            streams = data.get("data", [])
            if not streams:
                return PlatformCheckResult(is_live=False)

            s = streams[0]
            stream = StreamInfo(
                platform="twitch",
                platform_stream_id=s["id"],
                streamer_platform_id=platform_id,
                title=s.get("title", ""),
                url=f"https://www.twitch.tv/{platform_id}",
                viewer_count=s.get("viewer_count"),
                thumbnail_url=self._thumb_url(s.get("thumbnail_url", ""), 320, 180),
                started_at=s.get("started_at"),
            )
            return PlatformCheckResult(is_live=True, stream=stream)

        except aiohttp.ClientError as exc:
            logger.warning("twitch.http_error", platform_id=platform_id, error=str(exc))
            return PlatformCheckResult(is_live=False, error=str(exc))
        except Exception as exc:
            logger.exception("twitch.unexpected_error", platform_id=platform_id)
            return PlatformCheckResult(is_live=False, error=str(exc))

    async def resolve_url(self, url: str) -> Optional[str]:
        """Parse Twitch channel URL → login name (lowercase)."""
        m = re.search(r"twitch\.tv/([\w]+)", url)
        if not m:
            return None
        login = m.group(1).lower()
        # Verify the user exists
        try:
            await self._ensure_token()
            headers = {
                "Client-Id": self._client_id,
                "Authorization": f"Bearer {self._access_token}",
            }
            async with self._session.get(
                f"{_TWITCH_API}/users",
                headers=headers,
                params={"login": login},
            ) as resp:
                if not resp.ok:
                    return None
                data = await resp.json()
            users = data.get("data", [])
            return users[0]["login"] if users else None
        except Exception:
            logger.exception("twitch.resolve_url_error", url=url)
            return None

    # ── Token management ──────────────────────────────────────────────────────

    async def _ensure_token(self) -> None:
        """Refresh OAuth app access token if expired or missing."""
        if self._access_token and time.time() < self._token_expires_at - 60:
            return
        async with self._session.post(
            _TWITCH_AUTH,
            params={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
            },
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        logger.info("twitch.token_refreshed")

    def get_token_state(self) -> tuple[Optional[str], float]:
        return self._access_token, self._token_expires_at

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _thumb_url(template: str, width: int, height: int) -> str:
        return template.replace("{width}", str(width)).replace("{height}", str(height))

    def _parse_rate_limit_headers(self, headers: "aiohttp.CIMultiDictProxy[str]") -> None:
        remaining = headers.get("Ratelimit-Remaining")
        if remaining is not None and int(remaining) < 5:
            reset = float(headers.get("Ratelimit-Reset", time.time() + 60))
            self._rate_limit_reset = reset
            logger.warning("twitch.rate_limit_low", remaining=remaining)

    @property
    def is_rate_limited(self) -> bool:
        return time.time() < self._rate_limit_reset
