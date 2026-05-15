"""YouTube Data API v3 integration with quota-aware polling.

Quota strategy:
  - search.list (eventType=live) costs 100 units — used only when no known live video.
  - videos.list costs 1 unit — used to verify an already-known live video is still live.
  - Daily budget tracked in PollingState; polling halts if threshold exceeded.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

import aiohttp
import structlog

from config import settings
from integrations.base import BasePlatformIntegration, PlatformCheckResult, StreamInfo

logger = structlog.get_logger(__name__)

_YT_BASE = "https://www.googleapis.com/youtube/v3"
_SEARCH_QUOTA_COST = 100
_VIDEOS_QUOTA_COST = 1


class YouTubeIntegration(BasePlatformIntegration):
    """YouTube Data API v3 client."""

    def __init__(self, api_key: str, session: aiohttp.ClientSession) -> None:
        self._api_key = api_key
        self._session = session

    # ── Public interface ──────────────────────────────────────────────────────

    async def check_live(
        self,
        platform_id: str,
        known_video_id: Optional[str] = None,
    ) -> PlatformCheckResult:
        """Check if YouTube channel is live.

        Uses videos.list (1 unit) when we already know a live video ID;
        falls back to search.list (100 units) when no known video.
        """
        try:
            if known_video_id:
                return await self._check_known_video(platform_id, known_video_id)
            return await self._search_live(platform_id)
        except aiohttp.ClientError as exc:
            logger.warning("youtube.http_error", platform_id=platform_id, error=str(exc))
            return PlatformCheckResult(is_live=False, error=str(exc))
        except Exception as exc:
            logger.exception("youtube.unexpected_error", platform_id=platform_id)
            return PlatformCheckResult(is_live=False, error=str(exc))

    async def resolve_url(self, url: str) -> Optional[str]:
        """Parse YouTube channel URL → channel ID."""
        # Handle /channel/UCxxxxxx form directly
        m = re.search(r"youtube\.com/channel/(UC[\w-]{22})", url)
        if m:
            return m.group(1)

        # Handle /@handle or /user/name — resolve via API
        handle = None
        m2 = re.search(r"youtube\.com/@([\w.-]+)", url)
        if m2:
            handle = m2.group(1)
        m3 = re.search(r"youtube\.com/user/([\w.-]+)", url)
        if m3:
            handle = m3.group(1)
        m4 = re.search(r"youtube\.com/c/([\w.-]+)", url)
        if m4:
            handle = m4.group(1)

        if handle:
            return await self._resolve_handle(handle)
        return None

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _search_live(self, channel_id: str) -> PlatformCheckResult:
        """Search for live broadcasts on the channel (costs 100 quota units)."""
        params = {
            "part": "id,snippet",
            "channelId": channel_id,
            "eventType": "live",
            "type": "video",
            "key": self._api_key,
        }
        async with self._session.get(f"{_YT_BASE}/search", params=params) as resp:
            if resp.status == 403:
                data = await resp.json()
                reason = data.get("error", {}).get("errors", [{}])[0].get("reason", "")
                if "quotaExceeded" in reason:
                    logger.error("youtube.quota_exceeded")
                    return PlatformCheckResult(is_live=False, error="quotaExceeded", quota_cost=_SEARCH_QUOTA_COST)
                raise aiohttp.ClientResponseError(resp.request_info, resp.history, status=403)
            resp.raise_for_status()
            data = await resp.json()

        items = data.get("items", [])
        if not items:
            return PlatformCheckResult(is_live=False, quota_cost=_SEARCH_QUOTA_COST)

        video_id = items[0]["id"]["videoId"]
        snippet = items[0]["snippet"]
        stream_url = f"https://www.youtube.com/watch?v={video_id}"

        stream = StreamInfo(
            platform="youtube",
            platform_stream_id=video_id,
            streamer_platform_id=channel_id,
            title=snippet.get("title", ""),
            url=stream_url,
            thumbnail_url=snippet.get("thumbnails", {}).get("high", {}).get("url"),
        )
        return PlatformCheckResult(is_live=True, stream=stream, quota_cost=_SEARCH_QUOTA_COST)

    async def _check_known_video(self, channel_id: str, video_id: str) -> PlatformCheckResult:
        """Verify a known video is still live (costs 1 quota unit)."""
        params = {
            "part": "snippet,liveStreamingDetails",
            "id": video_id,
            "key": self._api_key,
        }
        async with self._session.get(f"{_YT_BASE}/videos", params=params) as resp:
            # FIX M-8: mirror quota-exceeded check from _search_live
            if resp.status == 403:
                data = await resp.json()
                reason = data.get("error", {}).get("errors", [{}])[0].get("reason", "")
                if "quotaExceeded" in reason:
                    logger.error("youtube.quota_exceeded_on_videos_list")
                    return PlatformCheckResult(is_live=False, error="quotaExceeded", quota_cost=_VIDEOS_QUOTA_COST)
                raise aiohttp.ClientResponseError(resp.request_info, resp.history, status=403)
            resp.raise_for_status()
            data = await resp.json()

        items = data.get("items", [])
        if not items:
            return PlatformCheckResult(is_live=False, quota_cost=_VIDEOS_QUOTA_COST)

        item = items[0]
        broadcast_status = (
            item.get("snippet", {}).get("liveBroadcastContent", "none")
        )
        if broadcast_status != "live":
            return PlatformCheckResult(is_live=False, quota_cost=_VIDEOS_QUOTA_COST)

        lsd = item.get("liveStreamingDetails", {})
        stream = StreamInfo(
            platform="youtube",
            platform_stream_id=video_id,
            streamer_platform_id=channel_id,
            title=item["snippet"].get("title", ""),
            url=f"https://www.youtube.com/watch?v={video_id}",
            viewer_count=int(lsd.get("concurrentViewers", 0)) or None,
            thumbnail_url=item["snippet"].get("thumbnails", {}).get("high", {}).get("url"),
            started_at=lsd.get("actualStartTime"),
        )
        return PlatformCheckResult(is_live=True, stream=stream, quota_cost=_VIDEOS_QUOTA_COST)

    async def _resolve_handle(self, handle: str) -> Optional[str]:
        """Resolve a YouTube handle/username to channel ID via forHandle."""
        params = {"part": "id", "forHandle": handle, "key": self._api_key}
        async with self._session.get(f"{_YT_BASE}/channels", params=params) as resp:
            if not resp.ok:
                return None
            data = await resp.json()
        items = data.get("items", [])
        return items[0]["id"] if items else None
