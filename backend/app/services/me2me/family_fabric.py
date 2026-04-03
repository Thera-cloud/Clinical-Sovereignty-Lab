"""
Me-2-Me Platinum — Family Fabric
Cross-avatar family connection management.
Links related avatars and enables family-level interactions.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.me2me import FamilyFabric

logger = logging.getLogger("me2me.family_fabric")


class FamilyFabricService:
    """
    Manages cross-avatar family connections.
    Links related avatars, tracks shared memories,
    and enables transgenerational family interactions.
    """

    def __init__(self, consent_service=None, db_pool=None):
        self._consent = consent_service
        self._db = db_pool

    async def create_fabric(
        self, family_id: str, member_avatars: Dict[str, str]
    ) -> FamilyFabric:
        """Create a new family fabric linking multiple avatars."""
        fabric = FamilyFabric(
            family_id=family_id,
            member_avatars=member_avatars,
        )

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO me2me_family_fabrics
                        (fabric_id, family_id, member_avatars)
                        VALUES ($1, $2, $3::jsonb)""",
                        fabric.fabric_id, family_id, json.dumps(member_avatars, default=str),
                    )
            except Exception as e:
                logger.error("Fabric creation failed: %s", e)

        logger.info("Family fabric created: family=%s avatars=%d",
                     family_id, len(member_avatars))
        return fabric

    async def add_shared_memory(
        self,
        fabric_id: str,
        memory: Dict[str, Any],
    ) -> bool:
        """Add a shared memory to the family fabric."""
        if not self._db:
            return False
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """UPDATE me2me_family_fabrics
                    SET shared_memories = COALESCE(shared_memories, '[]'::jsonb) || $1::jsonb
                    WHERE fabric_id = $2""",
                    json.dumps([memory], default=str),
                    fabric_id,
                )
                return True
        except Exception as e:
            logger.error("Shared memory addition failed: %s", e)
            return False

    async def record_transgenerational_pattern(
        self,
        pattern_id: str,
        pattern_name: str,
        description: str,
        confidence: float = 0.5,
    ) -> bool:
        # SOVEREIGN-VOICE: P5-004 — write detected transgenerational patterns
        if not self._db:
            return False
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """INSERT INTO transgenerational_patterns
                        (pattern_id, pattern_name, description, families_observed, confidence)
                       VALUES ($1, $2, $3, 1, $4)
                       ON CONFLICT (pattern_id) DO UPDATE SET
                        families_observed = transgenerational_patterns.families_observed + 1,
                        confidence = GREATEST(transgenerational_patterns.confidence, EXCLUDED.confidence)""",
                    pattern_id, pattern_name, description, confidence,
                )
                return True
        except Exception as e:
            logger.warning("Transgenerational pattern write failed: %s", e)
            return False

    async def get_fabric(self, family_id: str) -> Optional[FamilyFabric]:
        """Get the family fabric for a family."""
        if not self._db:
            return None
        try:
            async with self._db.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM me2me_family_fabrics WHERE family_id = $1",
                    family_id,
                )
                if row:
                    return FamilyFabric(
                        fabric_id=row["fabric_id"],
                        family_id=row["family_id"],
                        member_avatars=row.get("member_avatars", {}),
                    )
        except Exception as e:
            logger.error("Fabric query failed: %s", e)
        return None
