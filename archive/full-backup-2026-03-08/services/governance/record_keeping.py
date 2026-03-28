"""
SOVEREIGN SWARM — Clinical Record Keeping
Manages clinical records: session notes, treatment plans,
safety plans, and compliance.

Operational Specifications §5.3 — Clinical Record Keeping.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.governance import (
    ClinicalRecord,
    ClinicalRecordKeeping,
    ClinicalRecordType,
)

logger = logging.getLogger("governance.record_keeping")


class RecordKeepingService:
    """
    Manages clinical records with compliance tracking.
    AI-generated records are flagged and require coach review.
    """

    def __init__(self, db_pool=None):
        self._db = db_pool

    async def create_record(
        self,
        record_type: ClinicalRecordType,
        user_id: str,
        content: str,
        coach_id: Optional[str] = None,
        session_id: Optional[str] = None,
        ai_generated: bool = False,
    ) -> ClinicalRecord:
        """Create a new clinical record."""
        record = ClinicalRecord(
            record_type=record_type,
            user_id=user_id,
            coach_id=coach_id,
            session_id=session_id,
            content=content,
            ai_generated=ai_generated,
        )

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO clinical_records
                        (record_id, record_type, user_id, coach_id, session_id, content, ai_generated, encrypted)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                        record.record_id, record_type.value, user_id,
                        coach_id, session_id, content, ai_generated, True,
                    )
            except Exception as e:
                logger.error("Record creation failed: %s", e)

        logger.info(
            "Clinical record created: type=%s user=%s ai=%s",
            record_type.value, user_id, ai_generated,
        )
        return record

    async def coach_review_record(
        self,
        record_id: str,
        coach_id: str,
        approved: bool = True,
        signature: Optional[str] = None,
    ) -> bool:
        """Mark a record as reviewed by a coach."""
        if not self._db:
            return False
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """UPDATE clinical_records SET
                        coach_reviewed = TRUE,
                        coach_reviewed_at = NOW(),
                        coach_signature = $1
                    WHERE record_id = $2 AND coach_id = $3""",
                    signature, record_id, coach_id,
                )
                return True
        except Exception as e:
            logger.error("Record review failed: %s", e)
            return False

    async def get_compliance_status(self, user_id: str) -> ClinicalRecordKeeping:
        """Get the compliance status for a user's records."""
        status = ClinicalRecordKeeping(user_id=user_id)

        if not self._db:
            return status

        try:
            async with self._db.acquire() as conn:
                status.total_records = await conn.fetchval(
                    "SELECT COUNT(*) FROM clinical_records WHERE user_id = $1",
                    user_id,
                ) or 0

                status.pending_coach_reviews = await conn.fetchval(
                    """SELECT COUNT(*) FROM clinical_records
                    WHERE user_id = $1 AND ai_generated = TRUE AND coach_reviewed = FALSE""",
                    user_id,
                ) or 0

                last_note = await conn.fetchval(
                    """SELECT MAX(created_at) FROM clinical_records
                    WHERE user_id = $1 AND record_type = 'session_note'""",
                    user_id,
                )
                status.last_session_note = last_note

                safety = await conn.fetchrow(
                    """SELECT created_at FROM clinical_records
                    WHERE user_id = $1 AND record_type = 'safety_plan'
                    ORDER BY created_at DESC LIMIT 1""",
                    user_id,
                )
                if safety:
                    status.safety_plan_active = True
                    status.safety_plan_last_review = safety["created_at"]

        except Exception as e:
            logger.error("Compliance query failed: %s", e)

        return status

    async def generate_session_note(
        self,
        user_id: str,
        session_id: str,
        coach_id: str,
        session_data: Dict[str, Any],
        sovereign_mind=None,
    ) -> ClinicalRecord:
        """Generate an AI-assisted session note for coach review."""
        content = ""
        if sovereign_mind:
            try:
                content = await sovereign_mind.generate(
                    prompt="Generate a clinical session note",
                    context=session_data,
                )
            except Exception as e:
                logger.warning("AI session note generation failed: %s", e)

        if not content:
            content = f"Session {session_id}: Review required."

        return await self.create_record(
            record_type=ClinicalRecordType.SESSION_NOTE,
            user_id=user_id,
            coach_id=coach_id,
            session_id=session_id,
            content=content,
            ai_generated=True,
        )
