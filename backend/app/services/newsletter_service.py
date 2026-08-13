"""Newsletter topics + source_type crystal stamp. ENABLE_COACH_NEWSLETTER."""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, Iterable, List, Optional

from app.services.crystal_domains import normalize_domain
from app.services.google_workspace_service import FlagOff

SOURCE_TYPE = "newsletter"


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


async def record_topics(
    db_pool,
    topics: Iterable[str],
    *,
    domain: str = "marketing",
) -> int:
    if not _flag_on("ENABLE_COACH_NEWSLETTER"):
        raise FlagOff("ENABLE_COACH_NEWSLETTER")
    if db_pool is None:
        return 0
    domain = normalize_domain(domain)
    n = 0
    async with db_pool.acquire() as conn:
        for raw in topics:
            topic = (raw or "").strip()[:200]
            if not topic:
                continue
            await conn.execute(
                """
                INSERT INTO content_topics (topic, domain)
                VALUES ($1, $2)
                ON CONFLICT (topic) DO UPDATE SET domain = COALESCE(content_topics.domain, EXCLUDED.domain)
                """,
                topic,
                domain,
            )
            n += 1
    return n


async def stamp_source_crystal(
    db_pool,
    *,
    text: str,
    domain: str = "marketing",
    source_type: str = SOURCE_TYPE,
) -> Optional[str]:
    if not _flag_on("ENABLE_COACH_NEWSLETTER"):
        raise FlagOff("ENABLE_COACH_NEWSLETTER")
    body = (text or "").strip()
    if not body or db_pool is None:
        return None
    domain = normalize_domain(domain)
    digest = hashlib.sha256(f"{domain}:{source_type}:{body}".encode()).hexdigest()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO nate_intelligence_crystals
              (crystal_text, domain, scope, topics, source_count,
               confidence, content_hash, source_type, created_at)
            VALUES ($1, $2, 'admin_only', $3, 2, 0.50, $4, $5, NOW())
            ON CONFLICT (content_hash) DO NOTHING
            """,
            body[:4000],
            domain,
            [source_type],
            digest,
            source_type,
        )
    return digest
