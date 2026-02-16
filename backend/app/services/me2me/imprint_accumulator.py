"""
Me-2-Me Platinum — Imprint Accumulator
Continuously absorbs all member data: sessions, homework, journals,
voice notes, milestones. Feeds the Identity Crystallizer.
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.me2me import ConsentLevel, ImprintEntry
from app.services.me2me.constants import IMPRINT_BATCH_SIZE, IMPRINT_SOURCES

logger = logging.getLogger("me2me.imprint_accumulator")


class ImprintAccumulator:
    """
    Continuously absorbs member data from all sources.
    Respects consent level (minimum: OBSERVE).
    """

    def __init__(self, consent_service=None, vault=None, db_pool=None, ingestion_safety=None):
        self._consent = consent_service
        self._vault = vault
        self._db = db_pool
        self._ingestion_safety = ingestion_safety
        self._buffer: Dict[str, List[ImprintEntry]] = {}

    async def absorb(
        self,
        user_id: str,
        source: str,
        content: str,
        themes: Optional[List[str]] = None,
        emotions: Optional[List[str]] = None,
        c_emo: float = 0.0,
        gamma: float = 0.0,
        voice_biometrics: Optional[Dict[str, float]] = None,
    ) -> Optional[ImprintEntry]:
        """Absorb a new imprint from any source."""
        # Check consent
        if self._consent:
            has_consent = await self._consent.check_consent(
                user_id, ConsentLevel.OBSERVE
            )
            if not has_consent:
                return None

        # Validate source against known imprint sources
        if source not in IMPRINT_SOURCES:
            logger.warning("Unknown imprint source '%s' for user %s — allowing but flagging", source, user_id)

        # Ingestion safety scan
        if self._ingestion_safety:
            try:
                scan_result = await self._ingestion_safety.scan_content(content)
                if scan_result and scan_result.get("flagged"):
                    logger.warning(
                        "Imprint flagged by ingestion safety: user=%s source=%s reason=%s",
                        user_id, source, scan_result.get("reason", "unknown"),
                    )
                    # Still store but mark as flagged through escalation
            except Exception as e:
                logger.warning("Ingestion safety scan failed: %s", e)

        content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]

        entry = ImprintEntry(
            user_id=user_id,
            source=source,
            content_hash=content_hash,
            themes=themes or [],
            emotions=emotions or [],
            voice_biometrics=voice_biometrics,
            c_emo_at_capture=c_emo,
            gamma_at_capture=gamma,
        )

        # Store raw content for DB flush (not in model to avoid over-exposure)
        entry._raw_content = content

        # Buffer for batch processing
        if user_id not in self._buffer:
            self._buffer[user_id] = []
        self._buffer[user_id].append(entry)

        # Flush when buffer is full
        if len(self._buffer[user_id]) >= IMPRINT_BATCH_SIZE:
            await self.flush(user_id)

        # Store in vault
        if self._vault:
            await self._vault.store_imprint(
                user_id=user_id,
                data=entry.model_dump(),
                source=source,
            )

        return entry

    async def flush(self, user_id: str) -> int:
        """Flush buffered imprints to persistent storage."""
        entries = self._buffer.pop(user_id, [])
        if not entries:
            return 0

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    for entry in entries:
                        await conn.execute(
                            """INSERT INTO me2me_imprint_entries
                            (entry_id, user_id, source, content, content_hash, themes, emotions,
                             voice_biometrics, c_emo_at_capture, gamma_at_capture, processed)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, FALSE)
                            ON CONFLICT (entry_id) DO NOTHING""",
                            entry.entry_id, entry.user_id, entry.source,
                            getattr(entry, "_raw_content", ""),
                            entry.content_hash,
                            json.dumps(entry.themes),
                            json.dumps(entry.emotions),
                            json.dumps(entry.voice_biometrics) if entry.voice_biometrics else None,
                            entry.c_emo_at_capture, entry.gamma_at_capture,
                        )
            except Exception as e:
                logger.error("Imprint flush failed: %s", e)
                # Re-buffer on failure
                self._buffer[user_id] = entries
                return 0

        logger.info("Imprints flushed: user=%s count=%d", user_id, len(entries))
        return len(entries)

    async def flush_all(self) -> int:
        """Flush all buffered imprints for all users."""
        total = 0
        for user_id in list(self._buffer.keys()):
            total += await self.flush(user_id)
        return total

    async def get_unprocessed_count(self, user_id: str) -> int:
        """Get the count of unprocessed imprints for a user."""
        if not self._db:
            return len(self._buffer.get(user_id, []))
        try:
            async with self._db.acquire() as conn:
                return await conn.fetchval(
                    "SELECT COUNT(*) FROM me2me_imprint_entries WHERE user_id = $1 AND processed = FALSE",
                    user_id,
                ) or 0
        except Exception:
            return 0
