"""
SOVEREIGN SWARM — Community Early Warning System (S5)
Manages community-level early warning events and coach notifications.

Applied Solution S5: Cultural Sentinel Community Early Warning.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.solutions import (
    CommunityEarlyWarning,
    CulturalSignal,
    MemberImpactAssessment,
)

logger = logging.getLogger("community_warning")


class CommunityWarningService:
    """
    Manages community-level early warning events.
    Aggregates member impact assessments, notifies coaches,
    and tracks outcomes.
    """

    def __init__(
        self,
        member_matching=None,
        notifications=None,
        sovereign_mind=None,
        db_pool=None,
    ):
        self._matching = member_matching
        self._notifications = notifications
        self._sovereign_mind = sovereign_mind
        self._db = db_pool
        self._active_warnings: Dict[str, CommunityEarlyWarning] = {}

    async def process_signal(
        self, signal: CulturalSignal
    ) -> CommunityEarlyWarning:
        """
        Process a cultural signal into a community warning.
        Matches to members, determines severity, notifies coaches.
        """
        # Match signal to affected members
        affected = []
        if self._matching:
            affected = await self._matching.match_signal_to_members(signal)

        # Determine severity based on affected count
        severity = self._determine_severity(affected)

        # Pre-fetch coach assignments for affected members
        self._coach_lookup = {}
        if self._db and affected:
            try:
                member_ids = [m.member_id for m in affected]
                async with self._db.acquire() as conn:
                    rows = await conn.fetch(
                        """SELECT id, assigned_coach_id, family_id
                           FROM users WHERE id = ANY($1::uuid[])""",
                        member_ids,
                    )
                    family_ids = set()
                    for row in rows:
                        uid = str(row["id"])
                        coach = row.get("assigned_coach_id")
                        self._coach_lookup[uid] = str(coach) if coach else "unassigned"
                        fid = row.get("family_id")
                        if fid:
                            family_ids.add(str(fid))
            except Exception as e:
                logger.warning("Coach lookup query failed: %s", e)
                family_ids = set()
        else:
            family_ids = set()

        # Group by coach
        coach_alerts = self._group_by_coach(affected)

        # Count affected families (from DB data, with fallback)
        family_count = len(family_ids) if family_ids else len(set(
            m.member_id.split("-")[0] for m in affected  # Approximate fallback
        ))

        warning = CommunityEarlyWarning(
            signal=signal,
            affected_members=affected,
            total_families_affected=family_count,
            severity=severity,
            coach_alerts=coach_alerts,
        )

        # Generate platform response recommendation
        if self._sovereign_mind:
            try:
                context = {
                    "signal_type": signal.signal_type,
                    "description": signal.description,
                    "affected_count": len(affected),
                    "severity": severity,
                }
                response = await self._sovereign_mind.generate(
                    prompt="Generate a platform response recommendation for a community warning",
                    context=context,
                )
                warning.recommended_platform_response = response
            except Exception as e:
                logger.warning("Platform response generation failed: %s", e)

        # Notify coaches
        await self._send_coach_notifications(warning)

        # Persist
        self._active_warnings[warning.warning_id] = warning
        await self._persist_warning(warning)

        logger.info(
            "Community warning: signal=%s severity=%s affected=%d coaches=%d",
            signal.signal_id, severity, len(affected), len(coach_alerts),
        )

        return warning

    def _determine_severity(self, affected: List[MemberImpactAssessment]) -> str:
        """Determine warning severity based on member impact."""
        if not affected:
            return "advisory"
        high_impact = sum(
            1 for a in affected
            if a.predicted_impact_severity in ("critical", "high")
        )
        if high_impact > 10:
            return "urgent"
        if high_impact > 5:
            return "warning"
        if high_impact > 0:
            return "watch"
        return "advisory"

    def _group_by_coach(
        self, affected: List[MemberImpactAssessment]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group affected members by their assigned coach."""
        coach_map: Dict[str, List[Dict[str, Any]]] = {}

        # Pre-fetch coach assignments from member_coach_map (populated by process_signal)
        coach_lookup = getattr(self, "_coach_lookup", {})

        for member in affected:
            entry = {
                "member_id": member.member_id,
                "impact_severity": member.predicted_impact_severity,
                "match_confidence": member.match_confidence,
                "recommended_action": member.recommended_coach_action,
            }
            coach_id = coach_lookup.get(member.member_id, "unassigned")
            coach_map.setdefault(coach_id, []).append(entry)
        return coach_map

    async def _send_coach_notifications(
        self, warning: CommunityEarlyWarning
    ) -> None:
        """Send notifications to all affected coaches."""
        if not self._notifications:
            return

        for coach_id, members in warning.coach_alerts.items():
            if coach_id == "unassigned":
                continue
            try:
                await self._notifications.send_notification(
                    user_id=coach_id,
                    notification_type="community_warning",
                    title=f"Community Alert: {warning.severity.upper()}",
                    body=(
                        f"{len(members)} of your clients may be affected by a "
                        f"{warning.signal.signal_type if warning.signal else 'cultural'} event. "
                        f"Check your briefings for details."
                    ),
                    channel="urgent" if warning.severity in ("warning", "urgent") else "push",
                )
            except Exception as e:
                logger.warning("Coach notification failed: %s (coach=%s)", e, coach_id)

    async def _persist_warning(self, warning: CommunityEarlyWarning) -> None:
        """Persist the warning to the database."""
        if not self._db:
            return
        try:
            async with self._db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO community_warnings (
                        warning_id, signal_id, affected_members,
                        total_families_affected, severity, coach_alerts
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    warning.warning_id,
                    warning.signal.signal_id if warning.signal else None,
                    json.dumps([m.model_dump() for m in warning.affected_members], default=str),
                    warning.total_families_affected,
                    warning.severity,
                    json.dumps(warning.coach_alerts, default=str),
                )
        except Exception as e:
            logger.error("Warning persistence failed: %s", e)

    def get_active_warnings(self) -> List[CommunityEarlyWarning]:
        """Get all active community warnings."""
        return list(self._active_warnings.values())
