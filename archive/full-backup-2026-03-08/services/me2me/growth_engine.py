"""
Me-2-Me Platinum — Growth Engine
Post-mortem knowledge acquisition for avatars.
New knowledge is ALWAYS clearly marked as post-transition.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.me2me import GrowthLayer
from app.services.me2me.constants import GROWTH_CLEARLY_MARKED_AS_POST, GROWTH_KNOWLEDGE_TYPES

logger = logging.getLogger("me2me.growth_engine")


class GrowthEngine:
    """
    Allows avatars to acquire new knowledge post-transition.
    All post-mortem knowledge is clearly marked and distinct from
    the original identity crystal.
    """

    def __init__(self, db_pool=None, sovereign_mind=None):
        self._db = db_pool
        self._sovereign_mind = sovereign_mind

    async def add_knowledge(
        self,
        avatar_id: str,
        knowledge_source: str,
        knowledge_type: str,
        content: str,
    ) -> GrowthLayer:
        """Add a new knowledge layer to an avatar."""
        if knowledge_type not in GROWTH_KNOWLEDGE_TYPES:
            knowledge_type = "general"

        layer = GrowthLayer(
            avatar_id=avatar_id,
            knowledge_source=knowledge_source,
            knowledge_type=knowledge_type,
            content_summary=content[:500],
            clearly_marked_as_post=GROWTH_CLEARLY_MARKED_AS_POST,
        )

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO me2me_growth_layers
                        (layer_id, avatar_id, knowledge_source, knowledge_type,
                         content_summary, clearly_marked_as_post, confidence)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        layer.layer_id, avatar_id, knowledge_source,
                        knowledge_type, layer.content_summary,
                        GROWTH_CLEARLY_MARKED_AS_POST, 0.5,
                    )
            except Exception as e:
                logger.error("Growth layer persistence failed: %s", e)

        logger.info(
            "Growth layer added: avatar=%s type=%s source=%s",
            avatar_id, knowledge_type, knowledge_source,
        )
        return layer

    async def get_growth_layers(self, avatar_id: str) -> List[GrowthLayer]:
        """Get all growth layers for an avatar."""
        if not self._db:
            return []
        try:
            async with self._db.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT * FROM me2me_growth_layers
                    WHERE avatar_id = $1
                    ORDER BY acquired_at ASC""",
                    avatar_id,
                )
                return [
                    GrowthLayer(
                        layer_id=r["layer_id"],
                        avatar_id=r["avatar_id"],
                        knowledge_source=r.get("knowledge_source", ""),
                        knowledge_type=r.get("knowledge_type", "general"),
                        content_summary=r.get("content_summary", ""),
                        clearly_marked_as_post=r.get("clearly_marked_as_post", True),
                    )
                    for r in rows
                ]
        except Exception as e:
            logger.error("Growth layers query failed: %s", e)
            return []
