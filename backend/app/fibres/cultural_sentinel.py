"""
SOVEREIGN SWARM — Cultural Sentinel Fibre
Monitors SkyEye data for a specific cultural context.
Produces cultural coherence observations for the Wisdom Mesh.

Phase 3E — second operational Fibre type.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.fibres.base_fibre import BaseFibre
from app.models.fibre import FibreConfig, FibreResult, FibreTask, FibreType


class CulturalSentinelFibre(BaseFibre):
    """
    Cultural Sentinel — monitors a specific cultural context for emotional patterns.

    Capabilities:
        - Monitor SkyEye data filtered by cultural context
        - Detect emotional pattern shifts in public discourse
        - Calculate cultural incoherence signals
        - Report observations to Wisdom Mesh
        - Contribute to Layer 4 (Cultural) coherence measurement
    """

    def __init__(self, config: FibreConfig, **kwargs):
        super().__init__(config=config, **kwargs)
        self._cultural_context = config.wisdom_seed.get("cultural_context", "general")
        self._platforms = config.wisdom_seed.get("platforms", ["tiktok", "instagram", "reddit"])
        self._observation_history: List[Dict] = []

    async def _execute_impl(self, task: FibreTask) -> FibreResult:
        """
        Execute a cultural monitoring task.
        Task types:
            - scan_sentiment: Scan platform sentiment for cultural context
            - detect_shift: Detect emotional pattern shifts
            - calculate_incoherence: Calculate cultural incoherence index
            - report: Generate cultural intelligence report
        """
        task_type = task.task_type
        payload = task.payload

        if task_type == "scan_sentiment":
            return await self._scan_sentiment(task, payload)
        elif task_type == "detect_shift":
            return await self._detect_shift(task, payload)
        elif task_type == "calculate_incoherence":
            return await self._calculate_incoherence(task, payload)
        elif task_type == "report":
            return await self._generate_report(task, payload)
        else:
            return FibreResult(
                task_id=task.task_id,
                fibre_id=self.fibre_id,
                success=False,
                output={"error": f"Unknown task type: {task_type}"},
            )

    async def _scan_sentiment(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Scan platform sentiment for cultural context."""
        platforms = payload.get("platforms", self._platforms)
        hours = payload.get("hours", 24)

        sentiment_data = {}
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    for platform in platforms:
                        rows = await conn.fetch("""
                            SELECT content_type,
                                   COUNT(*) as count,
                                   AVG(COALESCE((metadata::jsonb->>'sentiment')::float, 0.5)) as avg_sentiment
                            FROM skyeye_activity
                            WHERE platform = $1
                              AND created_at > NOW() - ($2 || ' hours')::interval
                            GROUP BY content_type
                            ORDER BY count DESC
                        """, platform, str(hours))

                        sentiment_data[platform] = {
                            "themes": [
                                {"type": r["content_type"], "count": r["count"],
                                 "sentiment": float(r["avg_sentiment"] or 0.5)}
                                for r in rows
                            ],
                            "overall_sentiment": float(
                                sum(r["avg_sentiment"] or 0.5 for r in rows) / max(len(rows), 1)
                            ),
                        }
            except Exception as e:
                sentiment_data["error"] = str(e)

        self._observation_history.append({
            "type": "sentiment_scan",
            "context": self._cultural_context,
            "data": sentiment_data,
            "timestamp": datetime.utcnow().isoformat(),
        })

        return FibreResult(
            task_id=task.task_id,
            fibre_id=self.fibre_id,
            success=True,
            output={
                "cultural_context": self._cultural_context,
                "platforms_scanned": platforms,
                "period_hours": hours,
                "sentiment_data": sentiment_data,
            },
            tokens_used=200,
            ethical_compliance=1.0,
            self_alignment_score=1.0,
        )

    async def _detect_shift(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Detect emotional pattern shifts over time."""
        if len(self._observation_history) < 2:
            return FibreResult(
                task_id=task.task_id,
                fibre_id=self.fibre_id,
                success=True,
                output={"shift_detected": False, "reason": "Insufficient observation history"},
                tokens_used=50,
            )

        # Compare current vs previous sentiment
        current = self._observation_history[-1].get("data", {})
        previous = self._observation_history[-2].get("data", {})

        shifts = []
        for platform in current:
            if platform in previous and isinstance(current[platform], dict) and isinstance(previous[platform], dict):
                curr_sent = current[platform].get("overall_sentiment", 0.5)
                prev_sent = previous[platform].get("overall_sentiment", 0.5)
                delta = curr_sent - prev_sent

                if abs(delta) > 0.1:
                    shifts.append({
                        "platform": platform,
                        "delta": round(delta, 4),
                        "direction": "positive" if delta > 0 else "negative",
                        "current": round(curr_sent, 4),
                        "previous": round(prev_sent, 4),
                    })

        return FibreResult(
            task_id=task.task_id,
            fibre_id=self.fibre_id,
            success=True,
            output={
                "shift_detected": len(shifts) > 0,
                "shifts": shifts,
                "cultural_context": self._cultural_context,
            },
            tokens_used=100,
        )

    async def _calculate_incoherence(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Calculate the Cultural Incoherence Index."""
        # External: latest sentiment scan
        external_score = 0.5
        if self._observation_history:
            latest = self._observation_history[-1].get("data", {})
            scores = []
            for platform_data in latest.values():
                if isinstance(platform_data, dict):
                    scores.append(platform_data.get("overall_sentiment", 0.5))
            if scores:
                external_score = sum(scores) / len(scores)

        # Internal: coherence measurements
        internal_score = 0.5
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    row = await conn.fetchrow("""
                        SELECT AVG(score) as avg
                        FROM coherence_measurements
                        WHERE layer = 'individual'
                          AND measured_at > NOW() - INTERVAL '7 days'
                    """)
                    if row and row["avg"]:
                        internal_score = float(row["avg"])
            except Exception:
                pass

        gap = internal_score - external_score
        incoherence_index = abs(gap)

        return FibreResult(
            task_id=task.task_id,
            fibre_id=self.fibre_id,
            success=True,
            output={
                "cultural_context": self._cultural_context,
                "internal_score": round(internal_score, 4),
                "external_score": round(external_score, 4),
                "gap": round(gap, 4),
                "incoherence_index": round(incoherence_index, 4),
            },
            tokens_used=150,
        )

    async def _generate_report(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Generate a cultural intelligence report."""
        report = {
            "cultural_context": self._cultural_context,
            "monitored_platforms": self._platforms,
            "observation_count": len(self._observation_history),
            "fibre_name": self.name,
            "alignment": self.alignment_scores,
            "generated_at": datetime.utcnow().isoformat(),
        }

        # Include latest observations
        if self._observation_history:
            report["latest_observation"] = self._observation_history[-1]

        # Log as insight
        if self.db_pool:
            try:
                from app.services.strategic_memory import StrategicMemoryService
                memory = StrategicMemoryService(self.db_pool)
                await memory.log_insight(
                    title=f"Cultural report: {self._cultural_context}",
                    body=json.dumps(report, default=str),
                    domain="cultural",
                    confidence=0.6,
                    tags=["cultural", self._cultural_context, "sentinel"],
                    source_fibre_id=self.fibre_id,
                    source_type="fibre",
                )
            except Exception:
                pass

        return FibreResult(
            task_id=task.task_id,
            fibre_id=self.fibre_id,
            success=True,
            output={"report": report},
            tokens_used=200,
        )

    async def observe(self) -> Dict[str, Any]:
        """Periodic observation cycle — scan and report."""
        return {
            "fibre_id": str(self.fibre_id),
            "name": self.name,
            "observation_type": "cultural_sentinel",
            "cultural_context": self._cultural_context,
            "platforms": self._platforms,
            "observations_collected": len(self._observation_history),
            "timestamp": datetime.utcnow().isoformat(),
        }
