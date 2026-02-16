"""
SOVEREIGN SWARM — Graduated Autonomy Manager (S8)
Manages Fibre autonomy levels: observation → restricted → autonomous.
Handles promotion/demotion criteria and audit trail.

Applied Solution S8: Graduated Autonomy in Action.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.solutions import AutonomyAuditTrail, AutonomyLevel

logger = logging.getLogger("autonomy_manager")


# =============================================================================
# PROMOTION / DEMOTION CRITERIA
# =============================================================================

PROMOTION_CRITERIA = {
    # observation → restricted
    (AutonomyLevel.OBSERVATION, AutonomyLevel.RESTRICTED): {
        "min_proposals": 50,
        "min_approval_rate": 0.85,
        "min_coherence_impact": 0.0,
        "min_member_feedback": 0.7,
    },
    # restricted → autonomous
    (AutonomyLevel.RESTRICTED, AutonomyLevel.AUTONOMOUS): {
        "min_proposals": 100,
        "min_approval_rate": 0.92,
        "min_coherence_impact": 0.1,
        "min_member_feedback": 0.8,
        "min_successful_actions": 50,
    },
}

DEMOTION_CRITERIA = {
    # Any level can demote
    "max_failure_rate": 0.15,
    "max_negative_coherence_events": 3,
    "max_member_complaints": 2,
    "review_window_days": 30,
}


class AutonomyManager:
    """
    Manages the graduated autonomy lifecycle for all Fibres.
    Fibres start at OBSERVATION and can be promoted through
    RESTRICTED to AUTONOMOUS based on performance metrics.
    """

    def __init__(self, fibre_manager=None, db_pool=None):
        self._fibre_manager = fibre_manager
        self._db = db_pool
        self._audit_cache: Dict[str, AutonomyAuditTrail] = {}

    # -------------------------------------------------------------------------
    # AUTONOMY EVALUATION
    # -------------------------------------------------------------------------

    async def evaluate_promotion(
        self, fibre_id: str
    ) -> Optional[AutonomyLevel]:
        """
        Evaluate whether a Fibre qualifies for promotion.
        Returns the new level if promoted, None otherwise.
        """
        audit = await self._get_audit_trail(fibre_id)
        if not audit:
            return None

        current = audit.current_level
        if current == AutonomyLevel.AUTONOMOUS:
            return None  # Already at top

        # Determine target level
        if current == AutonomyLevel.OBSERVATION:
            target = AutonomyLevel.RESTRICTED
        else:
            target = AutonomyLevel.AUTONOMOUS

        criteria = PROMOTION_CRITERIA.get((current, target))
        if not criteria:
            return None

        # Check all criteria
        if audit.total_proposals < criteria["min_proposals"]:
            return None

        approval_rate = (
            audit.approved_proposals / max(audit.total_proposals, 1)
        )
        if approval_rate < criteria["min_approval_rate"]:
            return None

        avg_coherence = (
            sum(audit.coherence_impact_scores) / max(len(audit.coherence_impact_scores), 1)
            if audit.coherence_impact_scores else 0.0
        )
        if avg_coherence < criteria["min_coherence_impact"]:
            return None

        avg_feedback = (
            sum(audit.member_feedback_scores) / max(len(audit.member_feedback_scores), 1)
            if audit.member_feedback_scores else 0.0
        )
        if avg_feedback < criteria["min_member_feedback"]:
            return None

        # For autonomous: also need successful actions
        if target == AutonomyLevel.AUTONOMOUS:
            if audit.successful_actions < criteria.get("min_successful_actions", 50):
                return None

        # Promote
        await self._promote_fibre(fibre_id, audit, current, target)
        return target

    async def evaluate_demotion(
        self, fibre_id: str
    ) -> Optional[AutonomyLevel]:
        """
        Evaluate whether a Fibre should be demoted.
        Returns the new level if demoted, None otherwise.
        """
        audit = await self._get_audit_trail(fibre_id)
        if not audit:
            return None

        current = audit.current_level
        if current == AutonomyLevel.OBSERVATION:
            return None  # Already at bottom

        # Check failure rate
        total_actions = audit.total_autonomous_actions
        if total_actions > 0:
            failure_rate = audit.failed_actions / total_actions
            if failure_rate > DEMOTION_CRITERIA["max_failure_rate"]:
                target = AutonomyLevel.OBSERVATION
                await self._demote_fibre(fibre_id, audit, current, target, "high_failure_rate")
                return target

        # Check negative coherence events
        recent_negative = sum(
            1 for score in audit.coherence_impact_scores[-10:]
            if score < 0
        )
        if recent_negative >= DEMOTION_CRITERIA["max_negative_coherence_events"]:
            target = AutonomyLevel.OBSERVATION
            await self._demote_fibre(fibre_id, audit, current, target, "negative_coherence")
            return target

        return None

    # -------------------------------------------------------------------------
    # PROPOSAL RECORDING
    # -------------------------------------------------------------------------

    async def record_proposal(
        self,
        fibre_id: str,
        approved: bool,
        coherence_impact: float = 0.0,
        member_feedback: Optional[float] = None,
    ) -> AutonomyAuditTrail:
        """Record a Fibre's proposal and its outcome."""
        audit = await self._get_or_create_audit(fibre_id)
        audit.total_proposals += 1
        if approved:
            audit.approved_proposals += 1
        else:
            audit.rejected_proposals += 1

        audit.coherence_impact_scores.append(coherence_impact)
        if member_feedback is not None:
            audit.member_feedback_scores.append(member_feedback)

        await self._persist_audit(audit)
        return audit

    async def record_autonomous_action(
        self,
        fibre_id: str,
        successful: bool,
        coherence_impact: float = 0.0,
    ) -> AutonomyAuditTrail:
        """Record an autonomous action taken by a promoted Fibre."""
        audit = await self._get_or_create_audit(fibre_id)
        audit.total_autonomous_actions += 1
        if successful:
            audit.successful_actions += 1
        else:
            audit.failed_actions += 1

        audit.coherence_impact_scores.append(coherence_impact)
        await self._persist_audit(audit)
        return audit

    # -------------------------------------------------------------------------
    # INTERNAL TRANSITIONS
    # -------------------------------------------------------------------------

    async def _promote_fibre(
        self,
        fibre_id: str,
        audit: AutonomyAuditTrail,
        from_level: AutonomyLevel,
        to_level: AutonomyLevel,
    ) -> None:
        """Execute a Fibre promotion."""
        audit.current_level = to_level
        audit.promotion_history.append({
            "from": from_level.value,
            "to": to_level.value,
            "timestamp": datetime.utcnow().isoformat(),
            "proposals_at_promotion": audit.total_proposals,
            "approval_rate": audit.approved_proposals / max(audit.total_proposals, 1),
        })
        await self._persist_audit(audit)

        # Notify fibre manager
        if self._fibre_manager:
            try:
                await self._fibre_manager.update_fibre_autonomy(
                    fibre_id=fibre_id, level=to_level.value
                )
            except Exception as e:
                logger.warning("Fibre manager autonomy update failed: %s", e)

        logger.info(
            "Fibre promoted: %s %s → %s (proposals=%d, approval=%.2f)",
            fibre_id, from_level.value, to_level.value,
            audit.total_proposals,
            audit.approved_proposals / max(audit.total_proposals, 1),
        )

    async def _demote_fibre(
        self,
        fibre_id: str,
        audit: AutonomyAuditTrail,
        from_level: AutonomyLevel,
        to_level: AutonomyLevel,
        reason: str,
    ) -> None:
        """Execute a Fibre demotion."""
        audit.current_level = to_level
        audit.demotion_history.append({
            "from": from_level.value,
            "to": to_level.value,
            "timestamp": datetime.utcnow().isoformat(),
            "reason": reason,
        })
        await self._persist_audit(audit)

        if self._fibre_manager:
            try:
                await self._fibre_manager.update_fibre_autonomy(
                    fibre_id=fibre_id, level=to_level.value
                )
            except Exception as e:
                logger.warning("Fibre manager autonomy update failed: %s", e)

        logger.warning(
            "Fibre demoted: %s %s → %s reason=%s",
            fibre_id, from_level.value, to_level.value, reason,
        )

    # -------------------------------------------------------------------------
    # DATA ACCESS
    # -------------------------------------------------------------------------

    async def _get_audit_trail(self, fibre_id: str) -> Optional[AutonomyAuditTrail]:
        """Get the audit trail for a fibre."""
        if fibre_id in self._audit_cache:
            return self._audit_cache[fibre_id]

        if not self._db:
            return None

        try:
            async with self._db.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM fibre_autonomy_audit WHERE fibre_id = $1",
                    fibre_id,
                )
                if row:
                    audit = AutonomyAuditTrail(
                        fibre_id=row["fibre_id"],
                        fibre_type=row.get("fibre_type", ""),
                        current_level=AutonomyLevel(row.get("current_level", "observation")),
                        total_proposals=row.get("total_proposals", 0),
                        approved_proposals=row.get("approved_proposals", 0),
                        rejected_proposals=row.get("rejected_proposals", 0),
                        total_autonomous_actions=row.get("total_autonomous_actions", 0),
                        successful_actions=row.get("successful_actions", 0),
                        failed_actions=row.get("failed_actions", 0),
                    )
                    self._audit_cache[fibre_id] = audit
                    return audit
        except Exception as e:
            logger.error("Audit trail query failed: %s", e)
        return None

    async def _get_or_create_audit(self, fibre_id: str) -> AutonomyAuditTrail:
        """Get or create an audit trail for a fibre."""
        audit = await self._get_audit_trail(fibre_id)
        if not audit:
            audit = AutonomyAuditTrail(fibre_id=fibre_id)
            self._audit_cache[fibre_id] = audit
        return audit

    async def _persist_audit(self, audit: AutonomyAuditTrail) -> None:
        """Persist the audit trail to the database."""
        self._audit_cache[audit.fibre_id] = audit
        if not self._db:
            return
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO fibre_autonomy_audit (
                        fibre_id, fibre_type, current_level,
                        total_proposals, approved_proposals, rejected_proposals,
                        total_autonomous_actions, successful_actions, failed_actions,
                        updated_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                    ON CONFLICT (fibre_id) DO UPDATE SET
                        current_level = EXCLUDED.current_level,
                        total_proposals = EXCLUDED.total_proposals,
                        approved_proposals = EXCLUDED.approved_proposals,
                        rejected_proposals = EXCLUDED.rejected_proposals,
                        total_autonomous_actions = EXCLUDED.total_autonomous_actions,
                        successful_actions = EXCLUDED.successful_actions,
                        failed_actions = EXCLUDED.failed_actions,
                        updated_at = NOW()
                    """,
                    audit.fibre_id, audit.fibre_type, audit.current_level.value,
                    audit.total_proposals, audit.approved_proposals, audit.rejected_proposals,
                    audit.total_autonomous_actions, audit.successful_actions, audit.failed_actions,
                )
        except Exception as e:
            logger.error("Audit persistence failed: %s", e)
