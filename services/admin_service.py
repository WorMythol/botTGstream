"""Admin-level business logic extracted from bot handlers.

Keeps admin.py handlers thin: they parse input, call this service, send a reply.

Public API:
  AdminService.export_streams_csv(days)           → (bytes, record_count)
  AdminService.upsert_api_credential(...)         → None  (raises ValueError on bad config)
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from db.models import ApiCredential, Platform, PlatformStream, Stream, StreamStatus, Streamer

logger = structlog.get_logger(__name__)


class AdminService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Feature 8: CSV export ─────────────────────────────────────────────────

    async def export_streams_csv(self, days: int = 30) -> Tuple[bytes, int]:
        """Export stream history as CSV bytes (UTF-8 BOM for Excel compatibility).

        Returns:
            (csv_bytes, record_count)
        """
        days = max(1, min(days, 365))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        result = await self._session.execute(
            select(Stream)
            .options(
                selectinload(Stream.streamer),
                selectinload(Stream.platform_streams),
            )
            .where(Stream.started_at >= cutoff)
            .order_by(Stream.started_at.desc())
        )
        streams = list(result.scalars().all())

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=[
            "stream_id", "streamer", "status", "started_at", "ended_at",
            "duration_min", "peak_viewers", "platforms",
        ])
        writer.writeheader()

        for s in streams:
            duration_min: Optional[float] = None
            if s.started_at and s.ended_at:
                duration_min = round(
                    (s.ended_at - s.started_at).total_seconds() / 60, 1
                )
            platforms = ", ".join(
                sorted({ps.platform.value for ps in (s.platform_streams or [])})
            )
            writer.writerow({
                "stream_id": s.id,
                "streamer": s.streamer.display_name if s.streamer else "",
                "status": s.status.value,
                "started_at": s.started_at.strftime("%Y-%m-%d %H:%M:%S") if s.started_at else "",
                "ended_at": s.ended_at.strftime("%Y-%m-%d %H:%M:%S") if s.ended_at else "",
                "duration_min": duration_min if duration_min is not None else "",
                "peak_viewers": s.peak_viewer_count or "",
                "platforms": platforms,
            })

        csv_bytes = output.getvalue().encode("utf-8-sig")  # BOM so Excel opens correctly
        logger.info("admin.csv_export", days=days, records=len(streams))
        return csv_bytes, len(streams)

    # ── Update API credentials ────────────────────────────────────────────────

    async def upsert_api_credential(
        self,
        platform: Platform,
        key_name: str,
        key_value: str,
        updated_by: int,
    ) -> None:
        """Encrypt and upsert an API credential in the database.

        Raises:
            ValueError: if ENCRYPTION_KEY is not configured.
        """
        if not settings.ENCRYPTION_KEY:
            raise ValueError(
                "ENCRYPTION_KEY is not configured. Generate one with:\n"
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )

        from cryptography.fernet import Fernet
        fernet = Fernet(settings.ENCRYPTION_KEY.encode())
        encrypted = fernet.encrypt(key_value.encode()).decode()

        result = await self._session.execute(
            select(ApiCredential).where(
                ApiCredential.platform == platform,
                ApiCredential.key_name == key_name,
            )
        )
        cred = result.scalar_one_or_none()
        if cred:
            cred.key_value = encrypted
            cred.updated_by = updated_by
        else:
            cred = ApiCredential(
                platform=platform,
                key_name=key_name,
                key_value=encrypted,
                updated_by=updated_by,
            )
            self._session.add(cred)

        await self._session.flush()
        logger.info(
            "api_credential.upserted",
            platform=platform.value,
            key_name=key_name,
            updated_by=updated_by,
        )
