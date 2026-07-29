"""Deduped SkyEye social draft handoff from marketing_content parents.

Uses unique (parent_marketing_content_id, platform) from migration 296.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("nate.growth.skyeye_handoff")

DEFAULT_PLATFORMS = ("x", "linkedin")


def _clip_for_platform(platform: str, title: str, body: str) -> str:
    text = f"{title}\n\n{body}".strip()
    if platform == "x":
        return text[:260]
    if platform == "linkedin":
        return text[:2800]
    return text[:1000]


async def enqueue_social_children(
    db_pool,
    *,
    parent_content_id: int,
    title: str,
    body: str,
    platforms: Optional[Sequence[str]] = None,
    generated_by: str = "growth_factory",
) -> List[Dict[str, Any]]:
    """Insert draft rows into skyeye_content_queue; skip existing parent+platform."""
    plats = list(platforms or DEFAULT_PLATFORMS)
    created: List[Dict[str, Any]] = []
    async with db_pool.acquire() as conn:
        for platform in plats:
            platform = (platform or "").strip().lower()
            if not platform or platform in ("blog", "email", "newsletter"):
                continue
            content = _clip_for_platform(platform, title, body)
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO skyeye_content_queue (
                        platform, content_text, content_type, status, priority,
                        generated_by, parent_marketing_content_id,
                        created_at, updated_at
                    ) VALUES ($1, $2, 'post', 'draft', 'normal', $3, $4, NOW(), NOW())
                    ON CONFLICT (parent_marketing_content_id, platform)
                        WHERE parent_marketing_content_id IS NOT NULL
                    DO NOTHING
                    RETURNING id, platform, status
                    """,
                    platform,
                    content,
                    generated_by,
                    int(parent_content_id),
                )
                if row:
                    created.append(
                        {
                            "id": row["id"],
                            "platform": row["platform"],
                            "status": row["status"],
                        }
                    )
            except Exception as e:
                # Partial unique indexes: some PG versions need explicit constraint name.
                # Fallback: check-then-insert.
                logger.warning(
                    "skyeye handoff insert conflict/fallback for %s/%s: %s",
                    parent_content_id,
                    platform,
                    e,
                )
                existing = await conn.fetchval(
                    """
                    SELECT id FROM skyeye_content_queue
                    WHERE parent_marketing_content_id = $1 AND platform = $2
                    LIMIT 1
                    """,
                    int(parent_content_id),
                    platform,
                )
                if existing:
                    continue
                try:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO skyeye_content_queue (
                            platform, content_text, content_type, status, priority,
                            generated_by, parent_marketing_content_id,
                            created_at, updated_at
                        ) VALUES ($1, $2, 'post', 'draft', 'normal', $3, $4, NOW(), NOW())
                        RETURNING id, platform, status
                        """,
                        platform,
                        content,
                        generated_by,
                        int(parent_content_id),
                    )
                    if row:
                        created.append(
                            {
                                "id": row["id"],
                                "platform": row["platform"],
                                "status": row["status"],
                            }
                        )
                except Exception as e2:
                    logger.warning("skyeye handoff failed: %s", e2)
    return created
