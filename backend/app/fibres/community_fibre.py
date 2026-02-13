"""
SOVEREIGN SWARM — Community Fibre
Group facilitation and community coherence monitoring.

Phase 5D.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.fibres.base_fibre import BaseFibre
from app.models.fibre import FibreConfig, FibreResult, FibreTask, FibreType


class CommunityFibre(BaseFibre):
    """
    Community Fibre — monitors and facilitates community-level coherence.

    Capabilities:
        - Monitor community coherence metrics
        - Identify emerging community themes
        - Facilitate group interactions
        - Track community growth and engagement
        - Feed Layer 3 (Community) coherence measurements
    """

    def __init__(self, config: FibreConfig, **kwargs):
        super().__init__(config=config, **kwargs)
        self._community_id = config.wisdom_seed.get("community_id", "default")
        self._observation_history: List[Dict] = []

    async def _execute_impl(self, task: FibreTask) -> FibreResult:
        """
        Execute community management tasks.
        Task types:
            - monitor_health: Check community coherence health
            - identify_themes: Detect emerging community themes
            - engagement_report: Generate engagement metrics report
            - growth_analysis: Analyze community growth patterns
        """
        task_type = task.task_type
        payload = task.payload

        if task_type == "monitor_health":
            return await self._monitor_health(task, payload)
        elif task_type == "identify_themes":
            return await self._identify_themes(task, payload)
        elif task_type == "engagement_report":
            return await self._engagement_report(task, payload)
        elif task_type == "growth_analysis":
            return await self._growth_analysis(task, payload)
        else:
            return FibreResult(
                task_id=task.task_id, fibre_id=self.fibre_id,
                success=False, output={"error": f"Unknown task type: {task_type}"},
            )

    async def _monitor_health(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Monitor community coherence health."""
        health = {"community_id": self._community_id}

        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    # Family count (proxy for community size)
                    row = await conn.fetchrow("SELECT COUNT(DISTINCT id) as cnt FROM families")
                    health["family_count"] = row["cnt"] if row else 0

                    # Active users (last 30 days)
                    row = await conn.fetchrow("""
                        SELECT COUNT(DISTINCT user_id) as cnt
                        FROM sessions
                        WHERE started_at > NOW() - INTERVAL '30 days'
                    """)
                    health["active_users_30d"] = row["cnt"] if row else 0

                    # Community coherence (if available)
                    row = await conn.fetchrow("""
                        SELECT score, measured_at
                        FROM coherence_measurements
                        WHERE layer = 'community'
                        ORDER BY measured_at DESC LIMIT 1
                    """)
                    if row:
                        health["community_coherence"] = round(float(row["score"]), 4)
                        health["last_measured"] = row["measured_at"].isoformat()
                    else:
                        health["community_coherence"] = None
                        health["note"] = "Community coherence not yet measured (threshold: 50 families)"

            except Exception as e:
                health["error"] = str(e)

        self._observation_history.append({
            "type": "health_check",
            "data": health,
            "timestamp": datetime.utcnow().isoformat(),
        })

        return FibreResult(
            task_id=task.task_id, fibre_id=self.fibre_id,
            success=True, output={"health": health}, tokens_used=150,
        )

    async def _identify_themes(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Detect emerging community themes from session data."""
        themes = []
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT COALESCE(strength, growth_area) as theme, COUNT(*) as cnt
                        FROM nate_insights
                        WHERE created_at > NOW() - INTERVAL '7 days'
                          AND (strength IS NOT NULL OR growth_area IS NOT NULL)
                        GROUP BY COALESCE(strength, growth_area)
                        ORDER BY cnt DESC
                        LIMIT 10
                    """)
                    themes = [{"theme": r["theme"], "frequency": r["cnt"]} for r in rows]
            except Exception as e:
                themes = [{"error": str(e)}]

        return FibreResult(
            task_id=task.task_id, fibre_id=self.fibre_id,
            success=True, output={"themes": themes}, tokens_used=100,
        )

    async def _engagement_report(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Generate community engagement metrics."""
        days = payload.get("days", 30)
        report = {"period_days": days}

        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    # Session metrics
                    row = await conn.fetchrow(f"""
                        SELECT COUNT(*) as sessions,
                               COUNT(DISTINCT user_id) as unique_users
                        FROM sessions
                        WHERE started_at > NOW() - ('{days} days')::interval
                    """)
                    if row:
                        report["total_sessions"] = row["sessions"]
                        report["unique_users"] = row["unique_users"]
                        report["sessions_per_user"] = round(row["sessions"] / max(row["unique_users"], 1), 2)

                    # Quiz engagement
                    row = await conn.fetchrow(f"""
                        SELECT COUNT(*) as responses
                        FROM quiz_responses
                        WHERE created_at > NOW() - ('{days} days')::interval
                    """)
                    report["quiz_responses"] = row["responses"] if row else 0
            except Exception as e:
                report["error"] = str(e)

        return FibreResult(
            task_id=task.task_id, fibre_id=self.fibre_id,
            success=True, output={"engagement": report}, tokens_used=150,
        )

    async def _growth_analysis(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Analyze community growth patterns."""
        growth = {}
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    # User growth by month
                    rows = await conn.fetch("""
                        SELECT DATE_TRUNC('month', created_at) as month,
                               COUNT(*) as new_users
                        FROM users
                        WHERE created_at > NOW() - INTERVAL '6 months'
                        GROUP BY month
                        ORDER BY month
                    """)
                    growth["monthly_new_users"] = [
                        {"month": r["month"].isoformat(), "count": r["new_users"]}
                        for r in rows
                    ]

                    # Total counts
                    row = await conn.fetchrow("SELECT COUNT(*) as cnt FROM users")
                    growth["total_users"] = row["cnt"] if row else 0

                    row = await conn.fetchrow("SELECT COUNT(*) as cnt FROM families")
                    growth["total_families"] = row["cnt"] if row else 0
            except Exception as e:
                growth["error"] = str(e)

        return FibreResult(
            task_id=task.task_id, fibre_id=self.fibre_id,
            success=True, output={"growth": growth}, tokens_used=150,
        )

    async def observe(self) -> Dict[str, Any]:
        """Periodic observation — community pulse."""
        return {
            "fibre_id": str(self.fibre_id),
            "name": self.name,
            "observation_type": "community",
            "community_id": self._community_id,
            "observations": len(self._observation_history),
            "timestamp": datetime.utcnow().isoformat(),
        }
