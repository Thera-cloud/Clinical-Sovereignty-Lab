"""
Me-2-Me Platinum — Migration Service
Manages the organic-to-inorganic transition (living → avatar).
Supports gradual transfer, parallel running, and final transition.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app.models.me2me import ConsentLevel, MigrationPhase, MigrationRecord
from app.services.me2me.constants import (
    MIGRATION_MIN_CRYSTAL_QUALITY,
    MIGRATION_MIN_DATA_COMPLETENESS,
    MIGRATION_PARALLEL_RUNNING_DAYS,
)

logger = logging.getLogger("me2me.migration")


class MigrationService:
    """
    Manages the organic-to-inorganic transition.

    Phases:
    1. Gradual Transfer — member begins delegating to avatar
    2. Parallel Running — both member and avatar active
    3. Final Transition — avatar becomes primary
    """

    def __init__(
        self,
        consent_service=None,
        vault=None,
        crystallizer=None,
        avatar_service=None,
        db_pool=None,
    ):
        self._consent = consent_service
        self._vault = vault
        self._crystallizer = crystallizer
        self._avatar = avatar_service
        self._db = db_pool

    async def initiate_migration(
        self,
        user_id: str,
        trigger: str = "manual",
        guardian_id: Optional[str] = None,
    ) -> Optional[MigrationRecord]:
        """Initiate the organic-to-inorganic migration process."""
        # Verify INTERACT consent
        if self._consent:
            has_consent = await self._consent.check_consent(
                user_id, ConsentLevel.INTERACT
            )
            if not has_consent:
                logger.warning("Migration denied: no INTERACT consent for user %s", user_id)
                return None

        # Assess readiness
        readiness = await self._assess_readiness(user_id)

        record = MigrationRecord(
            user_id=user_id,
            phase=MigrationPhase.GRADUAL_TRANSFER,
            started_at=datetime.utcnow(),
            trigger=trigger,
            guardian_id=guardian_id,
            data_completeness_score=readiness.get("data_completeness", 0.0),
            crystal_quality_score=readiness.get("crystal_quality", 0.0),
            avatar_readiness_score=readiness.get("avatar_readiness", 0.0),
        )

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO me2me_migrations
                        (migration_id, user_id, phase, started_at, trigger,
                         data_completeness_score, crystal_quality_score, avatar_readiness_score, guardian_id)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                        record.migration_id, user_id, record.phase.value,
                        record.started_at, trigger,
                        record.data_completeness_score, record.crystal_quality_score,
                        record.avatar_readiness_score, guardian_id,
                    )
            except Exception as e:
                logger.error("Migration initiation persistence failed: %s", e)

        logger.info(
            "Migration initiated: user=%s trigger=%s readiness=%.2f",
            user_id, trigger, record.avatar_readiness_score,
        )
        return record

    async def advance_phase(self, migration_id: str) -> Optional[MigrationRecord]:
        """Advance to the next migration phase."""
        record = await self._get_migration(migration_id)
        if not record:
            return None

        phase_order = [
            MigrationPhase.GRADUAL_TRANSFER,
            MigrationPhase.PARALLEL_RUNNING,
            MigrationPhase.FINAL_TRANSITION,
            MigrationPhase.COMPLETE,
        ]

        current_idx = phase_order.index(record.phase)
        if current_idx >= len(phase_order) - 1:
            return record  # Already complete

        next_phase = phase_order[current_idx + 1]

        # Enforce readiness thresholds before advancing to FINAL_TRANSITION or COMPLETE
        if next_phase in (MigrationPhase.FINAL_TRANSITION, MigrationPhase.COMPLETE):
            readiness = await self._assess_readiness(record.user_id)
            crystal_q = readiness.get("crystal_quality", 0.0)
            data_c = readiness.get("data_completeness", 0.0)

            if crystal_q < MIGRATION_MIN_CRYSTAL_QUALITY:
                logger.warning(
                    "Migration advance blocked: crystal_quality=%.2f < %.2f (user=%s)",
                    crystal_q, MIGRATION_MIN_CRYSTAL_QUALITY, record.user_id,
                )
                return record  # Don't advance

            if data_c < MIGRATION_MIN_DATA_COMPLETENESS:
                logger.warning(
                    "Migration advance blocked: data_completeness=%.2f < %.2f (user=%s)",
                    data_c, MIGRATION_MIN_DATA_COMPLETENESS, record.user_id,
                )
                return record  # Don't advance

        record.phase = next_phase

        if record.phase == MigrationPhase.COMPLETE:
            record.completed_at = datetime.utcnow()
            # Activate avatar
            if self._avatar:
                await self._avatar.activate_avatar(record.user_id)

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    await conn.execute(
                        """UPDATE me2me_migrations SET phase = $1, completed_at = $2
                        WHERE migration_id = $3""",
                        record.phase.value, record.completed_at, migration_id,
                    )
            except Exception as e:
                logger.error("Migration phase advance failed: %s", e)

        logger.info("Migration phase advanced: id=%s phase=%s", migration_id, record.phase.value)
        return record

    async def _assess_readiness(self, user_id: str) -> Dict[str, float]:
        """Assess readiness for migration."""
        result = {
            "data_completeness": 0.0,
            "crystal_quality": 0.0,
            "avatar_readiness": 0.0,
        }

        if self._vault:
            integrity = await self._vault.check_integrity(user_id)
            imprint_count = integrity.get("imprint_count", 0)
            crystal_count = integrity.get("crystal_count", 0)
            result["data_completeness"] = min(imprint_count / 500, 1.0)
            result["crystal_quality"] = min(crystal_count / 3, 1.0)

        result["avatar_readiness"] = (
            result["data_completeness"] * 0.4
            + result["crystal_quality"] * 0.6
        )

        return result

    async def _get_migration(self, migration_id: str) -> Optional[MigrationRecord]:
        if not self._db:
            return None
        try:
            async with self._db.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM me2me_migrations WHERE migration_id = $1",
                    migration_id,
                )
                if row:
                    return MigrationRecord(
                        migration_id=row["migration_id"],
                        user_id=row["user_id"],
                        phase=MigrationPhase(row["phase"]),
                        started_at=row.get("started_at"),
                        completed_at=row.get("completed_at"),
                        trigger=row.get("trigger", "manual"),
                    )
        except Exception as e:
            logger.error("Migration query failed: %s", e)
        return None
