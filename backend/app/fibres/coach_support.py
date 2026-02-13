"""
SOVEREIGN SWARM — Coach Support Fibre
Augments human coaches with real-time pattern analysis,
intervention suggestions, and transgenerational context.

Phase 5D.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.fibres.base_fibre import BaseFibre
from app.models.fibre import FibreConfig, FibreResult, FibreTask, FibreType


class CoachSupportFibre(BaseFibre):
    """
    Coach Support Fibre — real-time augmentation for human coaches.

    Capabilities:
        - Pre-session brief: client history, patterns, recommended focus areas
        - In-session support: real-time pattern detection, intervention suggestions
        - Post-session analysis: coherence changes, key moments, follow-up recommendations
        - Transgenerational context: family patterns relevant to current client
    """

    def __init__(self, config: FibreConfig, **kwargs):
        super().__init__(config=config, **kwargs)
        self._coach_id = config.wisdom_seed.get("coach_id")
        self._client_ids = config.wisdom_seed.get("client_ids", [])

    async def _execute_impl(self, task: FibreTask) -> FibreResult:
        """
        Execute coach support tasks.
        Task types:
            - pre_session_brief: Generate pre-session briefing
            - intervention_suggestion: Suggest therapeutic interventions
            - post_session_analysis: Analyze completed session
            - family_context: Provide transgenerational context for a client
        """
        task_type = task.task_type
        payload = task.payload

        if task_type == "pre_session_brief":
            return await self._pre_session_brief(task, payload)
        elif task_type == "intervention_suggestion":
            return await self._intervention_suggestion(task, payload)
        elif task_type == "post_session_analysis":
            return await self._post_session_analysis(task, payload)
        elif task_type == "family_context":
            return await self._family_context(task, payload)
        else:
            return FibreResult(
                task_id=task.task_id, fibre_id=self.fibre_id,
                success=False, output={"error": f"Unknown task type: {task_type}"},
            )

    async def _pre_session_brief(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Generate a pre-session brief for the coach."""
        client_id = payload.get("client_id")
        if not client_id:
            return FibreResult(
                task_id=task.task_id, fibre_id=self.fibre_id,
                success=False, output={"error": "client_id required"},
            )

        brief = {"client_id": client_id}

        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    # Client info
                    client = await conn.fetchrow(
                        "SELECT name, tier FROM users WHERE id = $1", client_id
                    )
                    if client:
                        brief["client_name"] = client["name"]
                        brief["tier"] = client["tier"]

                    # Recent sessions
                    sessions = await conn.fetch("""
                        SELECT id, started_at, ended_at
                        FROM sessions WHERE user_id = $1
                        ORDER BY started_at DESC LIMIT 5
                    """, client_id)
                    brief["recent_sessions"] = len(sessions)
                    brief["last_session"] = sessions[0]["started_at"].isoformat() if sessions else None

                    # Coherence trajectory
                    coherence = await conn.fetch("""
                        SELECT score, measured_at
                        FROM coherence_measurements
                        WHERE user_id = $1 AND layer = 'individual'
                        ORDER BY measured_at DESC LIMIT 10
                    """, client_id)
                    if coherence:
                        scores = [float(c["score"]) for c in coherence]
                        brief["current_coherence"] = round(scores[0], 4)
                        brief["coherence_trend"] = "improving" if len(scores) >= 2 and scores[0] > scores[-1] else "stable"

                    # Recent insights
                    insights = await conn.fetch("""
                        SELECT strength, growth_area, insight_text
                        FROM nate_insights WHERE user_id = $1
                        ORDER BY created_at DESC LIMIT 3
                    """, client_id)
                    brief["recent_themes"] = [
                        i["strength"] or i["growth_area"]
                        for i in insights
                        if i["strength"] or i["growth_area"]
                    ]

            except Exception as e:
                brief["error"] = str(e)

        brief["recommended_focus"] = self._suggest_focus(brief)
        brief["generated_at"] = datetime.utcnow().isoformat()

        return FibreResult(
            task_id=task.task_id, fibre_id=self.fibre_id,
            success=True, output={"brief": brief}, tokens_used=300,
        )

    async def _intervention_suggestion(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Suggest therapeutic interventions based on real-time session data."""
        client_id = payload.get("client_id")
        session_context = payload.get("session_context", "")

        suggestions = []
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    # Check latest nevedal metrics
                    metrics = await conn.fetchrow("""
                        SELECT c_emo, biometrics, cee_window
                        FROM nevedal_metrics
                        WHERE user_id = $1
                        ORDER BY recorded_at DESC LIMIT 1
                    """, client_id)

                    if metrics:
                        c_emo = float(metrics["c_emo"]) if metrics["c_emo"] else 0.5
                        biometrics = metrics["biometrics"] or {}
                        stress = float(biometrics.get("voice_stress", 0.3)) if isinstance(biometrics, dict) else 0.3

                        if c_emo > 0.7:
                            suggestions.append("Client showing high coherence — consider deepening work")
                        if stress > 0.7:
                            suggestions.append("Elevated stress detected — consider grounding exercise")
                        if metrics.get("cee_window"):
                            suggestions.append("CEE window detected — this is a key therapeutic moment")
            except Exception:
                pass

        return FibreResult(
            task_id=task.task_id, fibre_id=self.fibre_id,
            success=True,
            output={"suggestions": suggestions, "client_id": client_id},
            tokens_used=200,
        )

    async def _post_session_analysis(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Analyze a completed session."""
        session_id = payload.get("session_id")
        analysis = {"session_id": session_id}

        if self.db_pool and session_id:
            try:
                async with self.db_pool.acquire() as conn:
                    session = await conn.fetchrow(
                        "SELECT * FROM sessions WHERE id = $1", session_id
                    )
                    if session:
                        analysis["duration_minutes"] = (
                            (session["ended_at"] - session["started_at"]).total_seconds() / 60
                            if session.get("ended_at") and session.get("started_at") else 0
                        )
                        analysis["user_id"] = session["user_id"]

                    # CEE events during session
                    metrics = await conn.fetch("""
                        SELECT c_emo, cee_window, biometrics
                        FROM nevedal_metrics
                        WHERE session_id = $1
                        ORDER BY recorded_at
                    """, str(session_id))

                    if metrics:
                        cee_count = sum(1 for m in metrics if m.get("cee_window"))
                        analysis["cee_events"] = cee_count
                        analysis["avg_coherence"] = round(
                            float(sum(m["c_emo"] for m in metrics if m["c_emo"]) / max(len(metrics), 1)), 4
                        )
            except Exception as e:
                analysis["error"] = str(e)

        return FibreResult(
            task_id=task.task_id, fibre_id=self.fibre_id,
            success=True, output={"analysis": analysis}, tokens_used=250,
        )

    async def _family_context(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Provide transgenerational context for a client."""
        client_id = payload.get("client_id")
        context = {"client_id": client_id}

        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    user = await conn.fetchrow(
                        "SELECT family_id FROM users WHERE id = $1", client_id
                    )
                    if user and user["family_id"]:
                        from app.services.pattern_engine import TransgenerationalPatternEngine
                        engine = TransgenerationalPatternEngine(self.db_pool)
                        context["family_analysis"] = await engine.full_analysis(user["family_id"])
            except Exception as e:
                context["error"] = str(e)

        return FibreResult(
            task_id=task.task_id, fibre_id=self.fibre_id,
            success=True, output={"context": context}, tokens_used=400,
        )

    @staticmethod
    def _suggest_focus(brief: Dict) -> List[str]:
        """Suggest focus areas based on pre-session data."""
        focus = []
        coherence = brief.get("current_coherence", 0.5)
        trend = brief.get("coherence_trend", "stable")

        if coherence < 0.4:
            focus.append("Stabilization and grounding — low coherence baseline")
        elif coherence > 0.7:
            focus.append("Deepening work — high coherence supports exploration")

        if trend == "improving":
            focus.append("Build on momentum — client is trending positively")

        themes = brief.get("recent_themes", [])
        if themes:
            focus.append(f"Continue exploring: {', '.join(themes[:3])}")

        return focus or ["General check-in and rapport building"]

    async def observe(self) -> Dict[str, Any]:
        """Periodic observation — monitor coach workload and client status."""
        return {
            "fibre_id": str(self.fibre_id),
            "name": self.name,
            "observation_type": "coach_support",
            "coach_id": self._coach_id,
            "client_count": len(self._client_ids),
            "timestamp": datetime.utcnow().isoformat(),
        }
