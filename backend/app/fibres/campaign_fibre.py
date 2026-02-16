"""
SOVEREIGN SWARM — Campaign Fibre
Autonomous social media campaign management.
Takes over content generation from skyeye_content_generator.py's generate_strategic_post().
Manages per-platform campaign execution with A/B testing.

Phase 3E — first operational Fibre type.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.fibres.base_fibre import BaseFibre
from app.models.fibre import FibreConfig, FibreResult, FibreTask, FibreType


class CampaignFibre(BaseFibre):
    """
    Campaign Fibre — manages social media content campaigns.

    Capabilities:
        - Generate strategic posts per platform
        - A/B test content variants
        - Track engagement metrics
        - Adjust content strategy based on performance
        - Report to Wisdom Mesh with campaign observations
    """

    SUPPORTED_PLATFORMS = ["tiktok", "instagram", "facebook", "linkedin", "youtube", "reddit", "pinterest"]

    def __init__(self, config: FibreConfig, **kwargs):
        super().__init__(config=config, **kwargs)
        self._campaign_history: List[Dict] = []
        self._platform_stats: Dict[str, Dict] = {}

    async def _execute_impl(self, task: FibreTask) -> FibreResult:
        """
        Execute a campaign task.
        Task types:
            - generate_post: Create a strategic post for a platform
            - ab_test: Generate A/B variants for testing
            - evaluate_performance: Analyze campaign metrics
            - adjust_strategy: Modify content mix based on results
        """
        task_type = task.task_type
        payload = task.payload

        if task_type == "generate_post":
            return await self._generate_post(task, payload)
        elif task_type == "ab_test":
            return await self._ab_test(task, payload)
        elif task_type == "evaluate_performance":
            return await self._evaluate_performance(task, payload)
        elif task_type == "adjust_strategy":
            return await self._adjust_strategy(task, payload)
        else:
            return FibreResult(
                task_id=task.task_id,
                fibre_id=self.fibre_id,
                success=False,
                output={"error": f"Unknown task type: {task_type}"},
            )

    async def _generate_post(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Generate a strategic social media post."""
        platform = payload.get("platform", "tiktok")
        content_pillar = payload.get("content_pillar", "emotional_coherence")
        target_audience = payload.get("target_audience", "general")

        # Pull Standing Orders for content guidance
        standing_orders = []
        if self.db_pool:
            try:
                from app.services.strategic_memory import StrategicMemoryService
                memory = StrategicMemoryService(self.db_pool)
                orders = await memory.get_active_standing_orders()
                standing_orders = [
                    o for o in orders
                    if "content" in (o.get("domain_tags") or []) or
                       "marketing" in (o.get("domain_tags") or [])
                ]
            except Exception:
                pass

        # Generate post using existing content generator
        post_data = None
        if self.db_pool:
            try:
                from app.services.skyeye_content_generator import SkyEyeContentGenerator
                generator = SkyEyeContentGenerator(self.db_pool)
                post_data = await generator.generate_strategic_post(
                    platform=platform,
                    content_type=content_pillar,
                )
            except Exception as e:
                # Retry once before falling back
                import asyncio as _aio
                try:
                    await _aio.sleep(2)  # Brief backoff
                    generator = SkyEyeContentGenerator(self.db_pool)
                    post_data = await generator.generate_strategic_post(
                        platform=platform,
                        content_type=content_pillar,
                    )
                except Exception as retry_err:
                    # Log the error and return a status-only result (no user-facing placeholder text)
                    print(f">>> [CAMPAIGN FIBRE] Content generation failed after retry: {retry_err}")
                    post_data = {
                        "platform": platform,
                        "content_pillar": content_pillar,
                        "text": "",
                        "status": "generation_failed",
                        "error": str(e),
                        "generated_by": f"campaign_fibre_{self.fibre_id}",
                        "requires_manual_review": True,
                    }

        self._campaign_history.append({
            "task_id": str(task.task_id),
            "platform": platform,
            "pillar": content_pillar,
            "timestamp": datetime.utcnow().isoformat(),
        })

        _gen_success = not (post_data or {}).get("status") == "generation_failed"
        return FibreResult(
            task_id=task.task_id,
            fibre_id=self.fibre_id,
            success=_gen_success,
            output={
                "post": post_data or {},
                "platform": platform,
                "content_pillar": content_pillar,
                "standing_orders_applied": len(standing_orders),
            },
            tokens_used=500 if _gen_success else 0,
            ethical_compliance=1.0,
            self_alignment_score=1.0,
        )

    async def _ab_test(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Generate A/B test variants for content."""
        platform = payload.get("platform", "tiktok")
        base_content = payload.get("content", "")
        variants = payload.get("num_variants", 2)

        # Generate variants (simplified — would use AI in production)
        test_variants = []
        for i in range(variants):
            test_variants.append({
                "variant_id": f"variant_{i+1}",
                "content": f"{base_content} [Variant {i+1}]",
                "hypothesis": f"Variant {i+1} test hypothesis",
            })

        return FibreResult(
            task_id=task.task_id,
            fibre_id=self.fibre_id,
            success=True,
            output={
                "platform": platform,
                "variants": test_variants,
                "test_duration_hours": 48,
            },
            tokens_used=300,
        )

    async def _evaluate_performance(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Evaluate campaign performance metrics."""
        platform = payload.get("platform")
        days = payload.get("days", 7)

        metrics = {}
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT type, COUNT(*) as posts,
                               AVG(COALESCE((metadata::jsonb->>'engagement')::float, 0)) as avg_engagement
                        FROM skyeye_activity
                        WHERE ($1::text IS NULL OR platform = $1)
                          AND created_at > NOW() - ($2 || ' days')::interval
                        GROUP BY type
                        ORDER BY avg_engagement DESC
                    """, platform, str(days))

                    for r in rows:
                        metrics[r["type"] or "unknown"] = {
                            "posts": r["posts"],
                            "avg_engagement": float(r["avg_engagement"] or 0),
                        }
            except Exception as e:
                metrics["error"] = str(e)

        return FibreResult(
            task_id=task.task_id,
            fibre_id=self.fibre_id,
            success=True,
            output={
                "platform": platform or "all",
                "period_days": days,
                "metrics": metrics,
                "total_posts": sum(m.get("posts", 0) for m in metrics.values() if isinstance(m, dict)),
            },
            tokens_used=100,
        )

    async def _adjust_strategy(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Adjust content strategy based on performance data."""
        recommendations = payload.get("recommendations", [])

        # Log strategy adjustment as an insight
        if self.db_pool and recommendations:
            try:
                from app.services.strategic_memory import StrategicMemoryService
                memory = StrategicMemoryService(self.db_pool)
                await memory.log_insight(
                    title=f"Campaign strategy adjustment by {self.name}",
                    body=f"Recommendations: {json.dumps(recommendations)}",
                    domain="marketing",
                    confidence=0.7,
                    tags=["campaign", "strategy", "adjustment"],
                    source_fibre_id=self.fibre_id,
                    source_type="fibre",
                )
            except Exception:
                pass

        return FibreResult(
            task_id=task.task_id,
            fibre_id=self.fibre_id,
            success=True,
            output={"adjustments_applied": len(recommendations)},
            tokens_used=200,
        )

    async def observe(self) -> Dict[str, Any]:
        """
        Periodic observation — scan platform metrics and report to Wisdom Mesh.
        """
        observations = {
            "fibre_id": str(self.fibre_id),
            "name": self.name,
            "observation_type": "campaign_status",
            "campaign_history_count": len(self._campaign_history),
            "platform_stats": self._platform_stats,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Pull latest metrics
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    row = await conn.fetchrow("""
                        SELECT COUNT(*) as total_posts,
                               COUNT(DISTINCT platform) as active_platforms
                        FROM skyeye_activity
                        WHERE created_at > NOW() - INTERVAL '24 hours'
                    """)
                    if row:
                        observations["posts_24h"] = row["total_posts"]
                        observations["active_platforms"] = row["active_platforms"]
            except Exception:
                pass

        return observations
