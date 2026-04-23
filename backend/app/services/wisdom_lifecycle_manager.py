"""
Wisdom Lifecycle Manager — extraction queue → Night School + promoted crystals.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


def schedule_wisdom_extraction_after_conversation(
    db_pool,
    hardware_id: str,
    crystal_text: str,
    user_uuid_str: Optional[str],
    domain: str,
    origin_surface: str,
    confidence: float,
) -> None:
    """Fire-and-forget extraction after a new conversation crystal is forged."""

    async def _run() -> None:
        try:
            mgr = WisdomLifecycleManager(db_pool, None)
            src = "sanctuary" if origin_surface == "family_sanctuary" else "conversation"
            await mgr.extract_wisdom(
                src,
                crystal_text,
                user_id=user_uuid_str,
                domain=domain,
                confidence=float(confidence),
            )
        except Exception as e:
            logger.debug("wisdom extraction after conversation (non-fatal): %s", e)

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        logger.debug("schedule_wisdom_extraction_after_conversation: no running loop")


class WisdomLifecycleManager:
    def __init__(self, db_pool, night_school=None):
        self.db = db_pool
        self.night_school = night_school
        self._night_school_lazy = None

    def _ensure_night_school(self):
        if self.night_school is not None:
            return self.night_school
        if self._night_school_lazy is not None:
            return self._night_school_lazy
        try:
            from app.websocket.bridge_server import NightSchool

            root = Path(os.environ.get("DATA_DIR", "/app/data")) / "Vaults"
            self._night_school_lazy = NightSchool(root)
        except Exception as e:
            logger.warning("WisdomLifecycleManager: NightSchool unavailable: %s", e)
            self._night_school_lazy = None
        return self._night_school_lazy

    def _parse_user_uuid(self, user_id: Optional[str]) -> Optional[UUID]:
        if not user_id:
            return None
        try:
            return UUID(str(user_id).strip())
        except (ValueError, TypeError):
            return None

    async def extract_wisdom(
        self,
        source: str,
        content: str,
        user_id: str = None,
        domain: str = "clinical",
        confidence: float = 0.5,
    ) -> Optional[str]:
        """
        Extract a wisdom entry from a therapeutic interaction.
        Sources include: sanctuary, coaching, assessment, session_summary,
        conversation, classroom.
        """
        if not self.db or not (content or "").strip():
            return None
        uid = self._parse_user_uuid(user_id)
        insight_type = f"wisdom_{(source or 'unknown')[:40]}"
        eff = float(confidence)
        try:
            async with self.db.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO wisdom_extractions (
                        user_id, family_id, session_id, insight_type, content,
                        effectiveness_score, source, domain, confidence, status
                    )
                    VALUES ($1, NULL, NULL, $2, $3, $4, $5, $6, $4, 'pending')
                    RETURNING id::text
                    """,
                    uid,
                    insight_type,
                    (content or "").strip()[:20000],
                    eff,
                    (source or "unknown")[:64],
                    (domain or "clinical")[:64],
                )
                return row["id"] if row else None
        except Exception as e:
            logger.warning("extract_wisdom failed: %s", e)
            return None

    def _learning_entry_id_after_add(self, ns, content: str) -> Optional[str]:
        h = hashlib.md5(content.encode()).hexdigest()
        p = ns.learnings_file
        if not p.exists():
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                learnings = json.load(f)
        except Exception:
            return None
        if not isinstance(learnings, list):
            return None
        for e in reversed(learnings):
            if isinstance(e, dict) and e.get("content_hash") == h:
                return str(e.get("id")) if e.get("id") is not None else None
        return None

    async def absorb_wisdom(
        self,
        extraction_id: str,
        absorbed_by: str = "system",
    ) -> bool:
        """
        Absorb an extracted wisdom into the active knowledge base.
        Promotes status to 'absorbed', pushes to Night School JSON,
        creates a high-confidence crystal, updates row metadata.
        """
        if not self.db or not extraction_id:
            return False
        try:
            eid = UUID(str(extraction_id).strip())
        except (ValueError, TypeError):
            return False

        ns = self._ensure_night_school()
        try:
            async with self.db.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        """
                        SELECT id, user_id, content, domain, source, confidence, status
                        FROM wisdom_extractions
                        WHERE id = $1
                        FOR UPDATE
                        """,
                        eid,
                    )
                    if not row or (row["status"] or "").lower() != "pending":
                        return False

                    content = (row["content"] or "").strip()
                    if not content:
                        return False

                    domain = (row["domain"] or "clinical")[:50]
                    src_tag = (row["source"] or "wisdom")[:64]

                    user_uuid = row["user_id"]
                    user_ref: Optional[str] = None
                    if user_uuid:
                        user_ref = await conn.fetchval(
                            """
                            SELECT COALESCE(NULLIF(TRIM(hardware_id), ''), NULLIF(TRIM(username), ''), id::text)
                            FROM users WHERE id = $1
                            """,
                            user_uuid,
                        )

                    night_entry_id: Optional[str] = None
                    if ns:
                        try:
                            ns.add_learning(
                                content=content[:4000],
                                source=f"WISDOM_{src_tag}",
                                filename=f"wisdom_{eid}.txt",
                                category=domain[:128] if domain else "general",
                            )
                            night_entry_id = self._learning_entry_id_after_add(ns, content[:4000])
                        except Exception as e:
                            logger.warning("absorb_wisdom add_learning: %s", e)

                    crystal_key: Optional[str] = None
                    try:
                        from app.websocket.crystal_recall_bridge import crystallize_wisdom_absorption

                        crystal_key = await crystallize_wisdom_absorption(
                            self.db,
                            user_ref or "",
                            content,
                            domain=domain,
                            extraction_id=str(eid),
                            absorption_source=src_tag,
                        )
                    except Exception as e:
                        logger.warning("absorb_wisdom crystal: %s", e)

                    await conn.execute(
                        """
                        UPDATE wisdom_extractions
                        SET status = 'absorbed',
                            absorbed_at = NOW(),
                            absorbed_by = $2,
                            crystal_id = COALESCE($3, crystal_id),
                            night_school_entry_id = COALESCE($4, night_school_entry_id),
                            approved = TRUE
                        WHERE id = $1
                        """,
                        eid,
                        (absorbed_by or "system")[:256],
                        crystal_key,
                        night_entry_id,
                    )
                    return True
        except Exception as e:
            logger.warning("absorb_wisdom failed: %s", e)
            return False

    async def reject_wisdom(
        self,
        extraction_id: str,
        rejected_by: str,
        reason: str,
    ) -> bool:
        if not self.db or not extraction_id:
            return False
        try:
            eid = UUID(str(extraction_id).strip())
        except (ValueError, TypeError):
            return False
        try:
            async with self.db.acquire() as conn:
                rid = await conn.fetchval(
                    """
                    UPDATE wisdom_extractions
                    SET status = 'rejected',
                        rejection_reason = $2,
                        absorbed_by = $3
                    WHERE id = $1 AND status = 'pending'
                    RETURNING id
                    """,
                    eid,
                    (reason or "")[:4000],
                    (rejected_by or "admin")[:256],
                )
                return rid is not None
        except Exception as e:
            logger.warning("reject_wisdom failed: %s", e)
            return False

    async def get_extraction_queue(self, status: str = "pending") -> List[Dict[str, Any]]:
        if not self.db:
            return []
        st = (status or "pending").lower()
        if st not in ("pending", "absorbed", "rejected", "expired"):
            st = "pending"
        try:
            async with self.db.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id::text AS id, source, content, domain,
                           user_id::text AS user_id, confidence, status,
                           extracted_at, absorbed_at, absorbed_by,
                           crystal_id, night_school_entry_id, rejection_reason
                    FROM wisdom_extractions
                    WHERE status = $1
                    ORDER BY extracted_at ASC
                    LIMIT 500
                    """,
                    st,
                )
                out: List[Dict[str, Any]] = []
                for r in rows:
                    d = dict(r)
                    for k, v in list(d.items()):
                        if hasattr(v, "isoformat"):
                            d[k] = v.isoformat()
                    out.append(d)
                return out
        except Exception as e:
            logger.warning("get_extraction_queue failed: %s", e)
            return []

    async def auto_absorb_high_confidence(self) -> int:
        """
        Auto-absorb pending rows with confidence > 0.8 pending over 24h.
        """
        if not self.db:
            return 0
        try:
            async with self.db.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id::text AS id
                    FROM wisdom_extractions
                    WHERE status = 'pending'
                      AND confidence > 0.8
                      AND extracted_at < NOW() - INTERVAL '24 hours'
                    ORDER BY extracted_at ASC
                    LIMIT 50
                    """
                )
            n = 0
            for r in rows:
                eid = r["id"]
                if await self.absorb_wisdom(eid, absorbed_by="auto_absorb_high_confidence"):
                    n += 1
            if n:
                logger.info("auto_absorb_high_confidence: absorbed %s row(s)", n)
            return n
        except Exception as e:
            logger.warning("auto_absorb_high_confidence failed: %s", e)
            return 0
