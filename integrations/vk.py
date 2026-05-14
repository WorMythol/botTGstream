"""VK API integration for live stream detection."""
from __future__ import annotations

import re
from typing import Optional

import aiohttp
import structlog

from integrations.base import BasePlatformIntegration, PlatformCheckResult, StreamInfo

logger = structlog.get_logger(__name__)

_VK_API = "https://api.vk.com/method"


class VKIntegration(BasePlatformIntegration):
    """VK API client for live stream monitoring."""

    def __init__(
        self,
        access_token: str,
        api_version: str,
        http_session: aiohttp.ClientSession,
    ) -> None:
        self._token = access_token
        self._v = api_version
        self._session = http_session

    # ── Public interface ──────────────────────────────────────────────────────

    async def check_live(self, platform_id: str) -> PlatformCheckResult:
        """Check if VK community/user has an active live stream.

        platform_id: numeric group/user ID (positive = user, negative = group).
        """
        try:
            owner_id = int(platform_id)
            result = await self._api_call(
                "video.get",
                owner_id=owner_id,
                count=10,
                filters="live",
            )
            items = result.get("items", [])
            live_items = [v for v in items if v.get("live") == 1]
            if not live_items:
                return PlatformCheckResult(is_live=False)

            video = live_items[0]
            video_id = video.get("id")
            owner = video.get("owner_id", owner_id)
            url = f"https://vk.com/video{owner}_{video_id}"
            stream = StreamInfo(
                platform="vk",
                platform_stream_id=f"{owner}_{video_id}",
                streamer_platform_id=platform_id,
                title=video.get("title", ""),
                url=url,
                viewer_count=video.get("spectators"),
                thumbnail_url=video.get("photo_800") or video.get("photo_320"),
            )
            return PlatformCheckResult(is_live=True, stream=stream)

        except aiohttp.ClientError as exc:
            logger.warning("vk.http_error", platform_id=platform_id, error=str(exc))
            return PlatformCheckResult(is_live=False, error=str(exc))
        except Exception as exc:
            logger.exception("vk.unexpected_error", platform_id=platform_id)
            return PlatformCheckResult(is_live=False, error=str(exc))

    async def resolve_url(self, url: str) -> Optional[str]:
        """Parse VK community/user URL → owner ID as string.

        Supports:
          https://vk.com/club123456
          https://vk.com/publicSHORTNAME
          https://vk.com/id123456
        """
        try:
            m_id = re.search(r"vk\.com/(?:club|public)(\d+)", url)
            if m_id:
                return str(-int(m_id.group(1)))  # groups have negative IDs

            m_uid = re.search(r"vk\.com/id(\d+)", url)
            if m_uid:
                return m_uid.group(1)

            # Short name — resolve via API
            m_short = re.search(r"vk\.com/([\w.]+)", url)
            if m_short:
                screen_name = m_short.group(1)
                result = await self._api_call("utils.resolveScreenName", screen_name=screen_name)
                obj_type = result.get("type")
                obj_id = result.get("object_id")
                if obj_type == "group" and obj_id:
                    return str(-obj_id)
                if obj_type == "user" and obj_id:
                    return str(obj_id)
            return None
        except Exception:
            logger.exception("vk.resolve_url_error", url=url)
            return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _api_call(self, method: str, **params) -> dict:
        params.update({"access_token": self._token, "v": self._v})
        async with self._session.get(f"{_VK_API}/{method}", params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()
        if "error" in data:
            err = data["error"]
            raise RuntimeError(f"VK API error {err.get('error_code')}: {err.get('error_msg')}")
        return data.get("response", {})
