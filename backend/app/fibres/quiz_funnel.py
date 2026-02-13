"""
SOVEREIGN SWARM — Quiz Funnel Fibre
Autonomous quiz creation, CTA optimization, and funnel management.

Phase 5D.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.fibres.base_fibre import BaseFibre
from app.models.fibre import FibreConfig, FibreResult, FibreTask, FibreType


class QuizFunnelFibre(BaseFibre):
    """
    Quiz Funnel Fibre — manages the quiz-to-conversion pipeline.

    Capabilities:
        - Autonomous quiz creation targeting specific audiences
        - CTA optimization based on conversion data
        - Funnel performance analysis
        - A/B testing of quiz variants
    """

    def __init__(self, config: FibreConfig, **kwargs):
        super().__init__(config=config, **kwargs)
        self._quiz_history: List[Dict] = []

    async def _execute_impl(self, task: FibreTask) -> FibreResult:
        """
        Execute quiz funnel tasks.
        Task types:
            - create_quiz: Design a new quiz
            - optimize_cta: Optimize call-to-action
            - analyze_funnel: Analyze conversion funnel
            - ab_test_quiz: Create quiz A/B test variants
        """
        task_type = task.task_type
        payload = task.payload

        if task_type == "create_quiz":
            return await self._create_quiz(task, payload)
        elif task_type == "optimize_cta":
            return await self._optimize_cta(task, payload)
        elif task_type == "analyze_funnel":
            return await self._analyze_funnel(task, payload)
        elif task_type == "ab_test_quiz":
            return await self._ab_test_quiz(task, payload)
        else:
            return FibreResult(
                task_id=task.task_id, fibre_id=self.fibre_id,
                success=False, output={"error": f"Unknown task type: {task_type}"},
            )

    async def _create_quiz(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Design a new quiz for a target audience."""
        target_audience = payload.get("target_audience", "general")
        quiz_title = payload.get("title", f"Assessment for {target_audience}")
        question_count = payload.get("questions", 8)

        quiz_design = {
            "title": quiz_title,
            "target_audience": target_audience,
            "question_count": question_count,
            "funnel": payload.get("funnel", "individual"),
            "designed_by": f"quiz_funnel_fibre_{self.fibre_id}",
            "created_at": datetime.utcnow().isoformat(),
        }

        # Create quiz via quiz_factory if available
        if self.db_pool:
            try:
                from app.services.quiz_factory import QuizFactory
                factory = QuizFactory(self.db_pool)
                # Use factory's generation capability
                quiz_design["status"] = "ready_for_creation"
            except Exception:
                quiz_design["status"] = "designed"

        self._quiz_history.append(quiz_design)

        # Log as insight
        if self.db_pool:
            try:
                from app.services.strategic_memory import StrategicMemoryService
                memory = StrategicMemoryService(self.db_pool)
                await memory.log_insight(
                    title=f"New quiz designed: {quiz_title}",
                    body=f"Target: {target_audience}, Questions: {question_count}",
                    domain="marketing",
                    confidence=0.7,
                    tags=["quiz", "funnel", target_audience],
                    source_fibre_id=self.fibre_id,
                    source_type="fibre",
                )
            except Exception:
                pass

        return FibreResult(
            task_id=task.task_id, fibre_id=self.fibre_id,
            success=True, output={"quiz_design": quiz_design}, tokens_used=400,
        )

    async def _optimize_cta(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Optimize call-to-action based on conversion data."""
        quiz_id = payload.get("quiz_id")

        cta_data = {"quiz_id": quiz_id}
        if self.db_pool and quiz_id:
            try:
                async with self.db_pool.acquire() as conn:
                    # Get quiz response stats (score computed from JSONB responses)
                    row = await conn.fetchrow("""
                        SELECT COUNT(*) as responses,
                               COUNT(CASE WHEN jsonb_array_length(
                                   COALESCE(responses->'answers', '[]'::jsonb)
                               ) >= 7 THEN 1 END) as high_scores
                        FROM quiz_responses
                        WHERE quiz_id = $1
                    """, quiz_id)

                    if row:
                        total = row["responses"] or 0
                        high = row["high_scores"] or 0
                        cta_data["total_responses"] = total
                        cta_data["high_score_rate"] = round(high / max(total, 1), 4)

                        # Suggest CTA optimization
                        if total > 10 and high / max(total, 1) < 0.3:
                            cta_data["recommendation"] = "Simplify quiz — low completion/high score rate"
                        elif total < 5:
                            cta_data["recommendation"] = "Increase quiz visibility — low response volume"
                        else:
                            cta_data["recommendation"] = "Funnel performing well"
            except Exception as e:
                cta_data["error"] = str(e)

        return FibreResult(
            task_id=task.task_id, fibre_id=self.fibre_id,
            success=True, output={"cta_optimization": cta_data}, tokens_used=200,
        )

    async def _analyze_funnel(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Analyze the quiz-to-conversion funnel."""
        funnel_data = {}
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    # Quiz completion rates
                    quizzes = await conn.fetch("""
                        SELECT q.id, q.title, COUNT(qr.id) as responses
                        FROM quizzes q
                        LEFT JOIN quiz_responses qr ON q.id = qr.quiz_id
                        GROUP BY q.id, q.title
                        ORDER BY responses DESC
                    """)
                    funnel_data["quizzes"] = [
                        {"id": q["id"], "title": q["title"], "responses": q["responses"]}
                        for q in quizzes
                    ]

                    # Prospect conversion
                    row = await conn.fetchrow("""
                        SELECT COUNT(*) as total_prospects,
                               COUNT(CASE WHEN user_id IS NOT NULL THEN 1 END) as converted
                        FROM prospects
                    """)
                    if row:
                        total = row["total_prospects"] or 0
                        converted = row["converted"] or 0
                        funnel_data["conversion_rate"] = round(converted / max(total, 1), 4)
                        funnel_data["total_prospects"] = total
                        funnel_data["converted"] = converted
            except Exception as e:
                funnel_data["error"] = str(e)

        return FibreResult(
            task_id=task.task_id, fibre_id=self.fibre_id,
            success=True, output={"funnel_analysis": funnel_data}, tokens_used=200,
        )

    async def _ab_test_quiz(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Create A/B test variants for a quiz."""
        base_quiz_id = payload.get("quiz_id")
        variants = payload.get("variants", 2)

        test_plan = {
            "base_quiz_id": base_quiz_id,
            "variants": variants,
            "test_duration_days": payload.get("duration_days", 14),
            "metric": "completion_to_conversion_rate",
            "status": "planned",
        }

        return FibreResult(
            task_id=task.task_id, fibre_id=self.fibre_id,
            success=True, output={"ab_test": test_plan}, tokens_used=150,
        )

    async def observe(self) -> Dict[str, Any]:
        """Periodic observation — monitor funnel health."""
        return {
            "fibre_id": str(self.fibre_id),
            "name": self.name,
            "observation_type": "quiz_funnel",
            "quizzes_designed": len(self._quiz_history),
            "timestamp": datetime.utcnow().isoformat(),
        }
