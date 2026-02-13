"""
LITTLE NATE — Marketing Brain (Strategy Engine)
Persistent strategic context that drives all marketing decisions.
This is Little Nate's marketing "mind" — an evolving playbook of
content pillars, target audiences, funnels, benchmarks, and growth strategy.

The Marketing Brain reads performance data from SkyEye, drip campaigns,
quizzes, and Golden Tickets, then writes strategy context into content
generation, funnel routing, and Big Nate Chat conversations.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiohttp
from app.config import settings

logger = logging.getLogger("marketing.brain")


# =============================================================================
# STRATEGY ANALYSIS PROMPT
# =============================================================================

STRATEGY_REVIEW_PROMPT = """You are Little Nate's Marketing Intelligence.
Analyze the following performance data and current playbook, then recommend
strategic adjustments. Be specific, data-driven, and actionable.

Format your response as JSON with these keys:
- content_pillar_adjustments: [{pillar, current_weight, recommended_weight, reason}]
- content_mix_changes: [{platform, changes, reason}]
- new_opportunities: [{description, platform, priority, expected_impact}]
- campaigns_to_pause: [{campaign, reason}]
- campaigns_to_scale: [{campaign, reason}]
- collaboration_suggestions: [{target, platform, approach}]
- funnel_optimizations: [{funnel, stage, suggestion}]
- top_insight: string (the single most important strategic insight)
"""


class MarketingBrain:
    """
    Little Nate's persistent strategic context — the marketing playbook.
    Reads performance data, analyzes trends, proposes strategy changes.
    """

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self._playbook_cache: Optional[Dict] = None
        self._cache_time: Optional[float] = None
        self._cache_ttl = 300  # 5 minutes

    # ── Playbook CRUD ────────────────────────────────────────────────

    async def get_playbook(self) -> Dict[str, Any]:
        """Get the current marketing playbook."""
        import time
        if self._playbook_cache and self._cache_time:
            if (time.time() - self._cache_time) < self._cache_ttl:
                return self._playbook_cache

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM marketing_playbook ORDER BY id LIMIT 1"
                )
                if not row:
                    return {}
                playbook = {
                    "id": row["id"],
                    "content_pillars": json.loads(row["content_pillars"]) if isinstance(row["content_pillars"], str) else row["content_pillars"],
                    "target_audiences": json.loads(row["target_audiences"]) if isinstance(row["target_audiences"], str) else row["target_audiences"],
                    "conversion_funnels": json.loads(row["conversion_funnels"]) if isinstance(row["conversion_funnels"], str) else row["conversion_funnels"],
                    "performance_benchmarks": json.loads(row["performance_benchmarks"]) if isinstance(row["performance_benchmarks"], str) else row["performance_benchmarks"],
                    "competitive_notes": json.loads(row["competitive_notes"]) if isinstance(row["competitive_notes"], str) else row["competitive_notes"],
                    "active_campaigns": json.loads(row["active_campaigns"]) if isinstance(row["active_campaigns"], str) else row["active_campaigns"],
                    "regional_focus": json.loads(row["regional_focus"]) if isinstance(row["regional_focus"], str) else row["regional_focus"],
                    "collaboration_targets": json.loads(row["collaboration_targets"]) if isinstance(row["collaboration_targets"], str) else row["collaboration_targets"],
                    "content_mix": json.loads(row["content_mix"]) if isinstance(row["content_mix"], str) else row["content_mix"],
                    "posting_schedule": json.loads(row["posting_schedule"]) if isinstance(row["posting_schedule"], str) else row["posting_schedule"],
                    "last_strategy_review": row["last_strategy_review"].isoformat() if row["last_strategy_review"] else None,
                    "version": row["version"],
                    "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                }
                self._playbook_cache = playbook
                import time as _t
                self._cache_time = _t.time()
                return playbook
        except Exception as e:
            logger.error(f"Failed to get playbook: {e}")
            return {}

    async def update_playbook(self, updates: Dict[str, Any]) -> bool:
        """Update specific fields of the playbook."""
        try:
            async with self.db_pool.acquire() as conn:
                # Build dynamic update
                set_clauses = ["updated_at = NOW()", "version = version + 1"]
                params = []
                idx = 1
                jsonb_fields = [
                    "content_pillars", "target_audiences", "conversion_funnels",
                    "performance_benchmarks", "competitive_notes", "active_campaigns",
                    "regional_focus", "collaboration_targets", "content_mix",
                    "posting_schedule"
                ]
                for key, value in updates.items():
                    if key in jsonb_fields:
                        set_clauses.append(f"{key} = ${idx}::jsonb")
                        params.append(json.dumps(value))
                        idx += 1
                    elif key == "last_strategy_review":
                        set_clauses.append(f"last_strategy_review = ${idx}")
                        params.append(value)
                        idx += 1

                if len(params) == 0:
                    return False

                query = f"UPDATE marketing_playbook SET {', '.join(set_clauses)} WHERE id = 1"
                await conn.execute(query, *params)
                self._playbook_cache = None  # Invalidate cache
                return True
        except Exception as e:
            logger.error(f"Failed to update playbook: {e}")
            return False

    # ── Strategy Methods ─────────────────────────────────────────────

    async def get_content_strategy(self, platform: str) -> Dict[str, Any]:
        """
        Get content strategy for a specific platform.
        Returns: recommended topic, pillar, CTA type, timing.
        """
        playbook = await self.get_playbook()
        if not playbook:
            return {"pillar": "daily_wins", "topic": "general wellness", "cta": None}

        # Get platform content mix
        content_mix = playbook.get("content_mix", {}).get(platform, {})
        audiences = playbook.get("target_audiences", {}).get(platform, {})
        schedule = playbook.get("posting_schedule", {}).get(platform, {})

        # Get pillar performance
        pillars = playbook.get("content_pillars", [])
        pillar_map = {p["name"]: p for p in pillars if isinstance(p, dict)}

        # Select pillar based on weighted mix + performance adjustment
        import random
        weighted_choices = []
        for pillar_name, weight in content_mix.items():
            perf = pillar_map.get(pillar_name, {}).get("avg_engagement", 0)
            # Boost high-performing pillars slightly
            adjusted_weight = weight * (1 + min(perf, 0.5))
            weighted_choices.append((pillar_name, adjusted_weight))

        if not weighted_choices:
            selected_pillar = "daily_wins"
        else:
            total = sum(w for _, w in weighted_choices)
            r = random.random() * total
            cumulative = 0
            selected_pillar = weighted_choices[0][0]
            for name, weight in weighted_choices:
                cumulative += weight
                if r <= cumulative:
                    selected_pillar = name
                    break

        # Determine CTA (every ~3rd post should have one)
        cta_decision = await self._should_include_cta(platform)

        return {
            "pillar": selected_pillar,
            "pillar_description": pillar_map.get(selected_pillar, {}).get("description", ""),
            "target_audience": audiences,
            "schedule": schedule,
            "include_cta": cta_decision.get("include", False),
            "cta_type": cta_decision.get("type"),
            "cta_url": cta_decision.get("url"),
        }

    async def get_conversion_strategy(self, user_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Determine the best conversion funnel for an engaged user.

        Args:
            user_context: Dict with platform, handle, interaction_count, interests, tone_notes

        Returns:
            Dict with funnel_path, quiz_id, cta_approach, urgency
        """
        playbook = await self.get_playbook()
        funnels = playbook.get("conversion_funnels", {})

        # Classify audience type based on interests and platform
        audience_type = self._classify_audience(user_context)

        # Get funnel config
        funnel = funnels.get(audience_type, funnels.get("individual", {}))
        default_quiz = funnel.get("default_quiz", "the_mirror")
        drip_campaign = funnel.get("drip_campaign", "default_journey")

        # Calculate urgency based on engagement
        interaction_count = user_context.get("interaction_count", 0)
        if interaction_count >= 10:
            urgency = "high"
        elif interaction_count >= 5:
            urgency = "medium"
        else:
            urgency = "low"

        # Determine CTA approach
        platform = user_context.get("platform", "")
        if platform == "linkedin":
            cta_approach = "professional_demo"
        elif platform in ("tiktok", "instagram"):
            cta_approach = "bio_link"
        elif platform == "reddit":
            cta_approach = "genuine_recommendation"
        else:
            cta_approach = "natural_invite"

        return {
            "audience_type": audience_type,
            "funnel_path": funnel.get("stages", []),
            "default_quiz": default_quiz,
            "drip_campaign": drip_campaign,
            "urgency": urgency,
            "cta_approach": cta_approach,
            "quiz_url": f"https://app.sovereignsanctuary.net/quiz?ref={platform}",
        }

    async def propose_campaign(self, target_audience: str, objective: str,
                                platform: str = "all") -> Dict[str, Any]:
        """
        Draft a new campaign proposal.
        Returns a structured proposal for Big Nate approval.
        """
        playbook = await self.get_playbook()

        proposal = {
            "action_type": "launch_campaign",
            "title": f"Campaign: {objective[:60]}",
            "description": f"Targeting {target_audience} on {platform}. Objective: {objective}",
            "parameters": {
                "target_audience": target_audience,
                "objective": objective,
                "platform": platform,
                "content_pillars": [p["name"] for p in playbook.get("content_pillars", [])[:3]],
                "estimated_duration_days": 14,
                "proposed_content_count": 10,
            },
            "status": "proposed",
            "proposed_by": "little_nate",
        }

        # Store in marketing_actions
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    INSERT INTO marketing_actions
                        (proposed_by, action_type, title, description, parameters, status)
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                    RETURNING id
                """, proposal["proposed_by"], proposal["action_type"],
                     proposal["title"], proposal["description"],
                     json.dumps(proposal["parameters"]), proposal["status"])
                proposal["id"] = row["id"]
        except Exception as e:
            logger.error(f"Failed to store campaign proposal: {e}")

        return proposal

    async def evaluate_results(self, campaign_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Analyze performance across all channels or a specific campaign.
        Returns structured performance report.
        """
        try:
            async with self.db_pool.acquire() as conn:
                # Platform performance
                platforms = await conn.fetch("""
                    SELECT name, followers, engagement, posts
                    FROM skyeye_platforms WHERE enabled = TRUE
                """)

                # Funnel metrics
                funnel_stats = await conn.fetchrow("""
                    SELECT
                        COUNT(*) as total_routed,
                        COUNT(quiz_started_at) as quiz_starts,
                        COUNT(quiz_completed_at) as quiz_completes,
                        COUNT(converted_at) as conversions
                    FROM funnel_routing_log
                    WHERE created_at > NOW() - INTERVAL '7 days'
                """)

                # Content performance
                content_stats = await conn.fetchrow("""
                    SELECT
                        COUNT(*) FILTER (WHERE status = 'posted') as posted,
                        COUNT(*) FILTER (WHERE status = 'draft') as pending,
                        COUNT(*) FILTER (WHERE status = 'failed') as failed
                    FROM skyeye_content_queue
                    WHERE created_at > NOW() - INTERVAL '7 days'
                """)

                # Prospect pipeline
                prospect_stats = await conn.fetchrow("""
                    SELECT
                        COUNT(*) as total_prospects,
                        COUNT(*) FILTER (WHERE status = 'active_journey') as active,
                        COUNT(*) FILTER (WHERE status = 'converted') as converted
                    FROM prospects
                """)

                return {
                    "period": "7_days",
                    "platforms": [dict(p) for p in platforms] if platforms else [],
                    "funnel": dict(funnel_stats) if funnel_stats else {},
                    "content": dict(content_stats) if content_stats else {},
                    "prospects": dict(prospect_stats) if prospect_stats else {},
                    "generated_at": datetime.utcnow().isoformat(),
                }
        except Exception as e:
            logger.error(f"Failed to evaluate results: {e}")
            return {"error": str(e)}

    async def review_playbook(self) -> Dict[str, Any]:
        """
        Run a full strategy review. Analyzes all performance data
        and proposes playbook updates. Called weekly by the session engine.
        """
        playbook = await self.get_playbook()
        results = await self.evaluate_results()

        if not playbook or not results:
            return {"status": "skipped", "reason": "No data available"}

        # Build analysis prompt
        analysis_data = {
            "current_playbook": {
                "content_pillars": playbook.get("content_pillars", []),
                "content_mix": playbook.get("content_mix", {}),
                "target_audiences": playbook.get("target_audiences", {}),
            },
            "performance_7d": results,
        }

        prompt = (
            f"{STRATEGY_REVIEW_PROMPT}\n\n"
            f"DATA:\n{json.dumps(analysis_data, indent=2, default=str)}\n\n"
            f"Provide your strategic analysis as JSON."
        )

        # Call Azure OpenAI for strategy analysis
        analysis = await self._call_azure_openai(prompt)

        # Parse the response
        try:
            # Try to extract JSON from the response
            if analysis:
                # Find JSON in the response
                start = analysis.find("{")
                end = analysis.rfind("}") + 1
                if start >= 0 and end > start:
                    strategy = json.loads(analysis[start:end])
                else:
                    strategy = {"top_insight": analysis, "raw": True}
            else:
                strategy = {"error": "No response from AI"}
        except json.JSONDecodeError:
            strategy = {"top_insight": analysis or "Analysis failed", "raw": True}

        # Update last review timestamp
        await self.update_playbook({"last_strategy_review": datetime.utcnow()})

        # Store as a marketing action for visibility
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO marketing_actions
                        (proposed_by, action_type, title, description, parameters, status)
                    VALUES ('little_nate', 'strategy_review', 'Weekly Strategy Review',
                            $1, $2::jsonb, 'completed')
                """, strategy.get("top_insight", "Review completed"),
                     json.dumps(strategy, default=str))
        except Exception as e:
            logger.error(f"Failed to log strategy review: {e}")

        return strategy

    async def get_chat_context(self) -> str:
        """
        Build rich context for Big Nate Chat.
        Returns a summary of current strategy, metrics, and pending proposals.
        """
        playbook = await self.get_playbook()
        results = await self.evaluate_results()

        try:
            async with self.db_pool.acquire() as conn:
                # Get pending proposals
                pending = await conn.fetch("""
                    SELECT title, description, action_type, proposed_at
                    FROM marketing_actions
                    WHERE status = 'proposed'
                    ORDER BY proposed_at DESC LIMIT 5
                """)

                # Get recent completed actions
                recent = await conn.fetch("""
                    SELECT title, result, completed_at
                    FROM marketing_actions
                    WHERE status = 'completed'
                    ORDER BY completed_at DESC LIMIT 3
                """)
        except Exception as e:
            logger.error(f"Failed to get chat context: {e}")
            pending = []
            recent = []

        # Build context string
        lines = ["\n\n--- MARKETING INTELLIGENCE CONTEXT ---"]

        # Playbook summary
        pillars = playbook.get("content_pillars", [])
        if pillars:
            top_pillars = sorted(pillars, key=lambda p: p.get("avg_engagement", 0), reverse=True)[:3]
            lines.append(f"\nTop content pillars: {', '.join(p['name'] for p in top_pillars)}")

        # Performance snapshot
        if results and not results.get("error"):
            platforms = results.get("platforms", [])
            if platforms:
                total_followers = sum(p.get("followers", 0) or 0 for p in platforms)
                lines.append(f"Total followers across platforms: {total_followers}")

            funnel = results.get("funnel", {})
            if funnel:
                lines.append(
                    f"Funnel (7d): {funnel.get('total_routed', 0)} routed, "
                    f"{funnel.get('quiz_starts', 0)} quiz starts, "
                    f"{funnel.get('conversions', 0)} conversions"
                )

            content = results.get("content", {})
            if content:
                lines.append(
                    f"Content (7d): {content.get('posted', 0)} posted, "
                    f"{content.get('pending', 0)} pending"
                )

        # Pending proposals
        if pending:
            lines.append(f"\nPending proposals ({len(pending)}):")
            for p in pending:
                lines.append(f"  - [{p['action_type']}] {p['title']}")

        # Recent actions
        if recent:
            lines.append(f"\nRecent completed actions:")
            for r in recent:
                lines.append(f"  - {r['title']}")

        lines.append("--- END MARKETING CONTEXT ---\n")
        return "\n".join(lines)

    async def record_growth_snapshot(self) -> bool:
        """Record daily growth metrics snapshot."""
        try:
            async with self.db_pool.acquire() as conn:
                # Platform metrics
                platforms = await conn.fetch("""
                    SELECT name, followers, engagement, posts
                    FROM skyeye_platforms WHERE enabled = TRUE
                """)
                platform_metrics = {
                    p["name"]: {
                        "followers": p["followers"] or 0,
                        "engagement_rate": float(p["engagement"] or 0),
                        "posts": p["posts"] or 0,
                    }
                    for p in platforms
                }

                # Funnel metrics
                funnel_row = await conn.fetchrow("""
                    SELECT
                        COUNT(*) as routed,
                        COUNT(quiz_started_at) as quiz_starts,
                        COUNT(quiz_completed_at) as quiz_completes,
                        COUNT(converted_at) as conversions
                    FROM funnel_routing_log
                    WHERE created_at::date = CURRENT_DATE
                """)
                funnel_metrics = dict(funnel_row) if funnel_row else {}

                # Totals
                totals = await conn.fetchrow("""
                    SELECT
                        (SELECT COUNT(*) FROM prospects) as total_prospects,
                        (SELECT COUNT(*) FROM users WHERE role = 'client') as total_clients,
                        (SELECT COUNT(*) FROM users WHERE role = 'coach') as total_coaches
                """)

                await conn.execute("""
                    INSERT INTO growth_snapshots
                        (snapshot_date, snapshot_type, platform_metrics,
                         funnel_metrics, total_prospects, total_clients, total_coaches)
                    VALUES (CURRENT_DATE, 'daily', $1::jsonb, $2::jsonb, $3, $4, $5)
                    ON CONFLICT (snapshot_date, snapshot_type) DO UPDATE
                    SET platform_metrics = EXCLUDED.platform_metrics,
                        funnel_metrics = EXCLUDED.funnel_metrics,
                        total_prospects = EXCLUDED.total_prospects,
                        total_clients = EXCLUDED.total_clients,
                        total_coaches = EXCLUDED.total_coaches
                """, json.dumps(platform_metrics), json.dumps(funnel_metrics),
                     totals["total_prospects"] if totals else 0,
                     totals["total_clients"] if totals else 0,
                     totals["total_coaches"] if totals else 0)
                return True
        except Exception as e:
            logger.error(f"Failed to record growth snapshot: {e}")
            return False

    # ── Private Methods ──────────────────────────────────────────────

    async def _should_include_cta(self, platform: str) -> Dict[str, Any]:
        """Determine if the next post should include a CTA."""
        try:
            async with self.db_pool.acquire() as conn:
                # Count recent posts with and without CTAs
                recent = await conn.fetchrow("""
                    SELECT
                        COUNT(*) as total,
                        COUNT(cta_type) as with_cta
                    FROM skyeye_content_queue
                    WHERE platform = $1
                      AND status = 'posted'
                      AND created_at > NOW() - INTERVAL '3 days'
                """, platform)

                total = recent["total"] if recent else 0
                with_cta = recent["with_cta"] if recent else 0

                # Target: ~1 in 3-5 posts should have a CTA
                if total < 3 or (total > 0 and with_cta / total < 0.25):
                    cta_types = {
                        "tiktok": ("bio_link", "https://app.sovereignsanctuary.net/quiz"),
                        "instagram": ("bio_link", "https://app.sovereignsanctuary.net/quiz"),
                        "youtube": ("description_link", "https://app.sovereignsanctuary.net/quiz"),
                        "reddit": ("natural_mention", "https://app.sovereignsanctuary.net"),
                        "linkedin": ("article_cta", "https://app.sovereignsanctuary.net/quiz"),
                        "facebook": ("post_link", "https://app.sovereignsanctuary.net/quiz"),
                        "pinterest": ("pin_link", "https://app.sovereignsanctuary.net"),
                    }
                    cta_type, cta_url = cta_types.get(platform, ("natural_mention", "https://app.sovereignsanctuary.net"))
                    return {"include": True, "type": cta_type, "url": cta_url}

                return {"include": False}
        except Exception as e:
            logger.error(f"CTA decision error: {e}")
            return {"include": False}

    def _classify_audience(self, user_context: Dict[str, Any]) -> str:
        """Classify a user into an audience type based on their context."""
        interests = user_context.get("interests", [])
        platform = user_context.get("platform", "")
        tone = user_context.get("tone_notes", "").lower()

        # Coach/therapist signals
        coach_signals = ["therapy", "counseling", "coaching", "clinical", "practice",
                         "licensed", "therapist", "psychologist", "LMFT", "LPC",
                         "social work", "mental health professional"]
        if platform == "linkedin" or any(s in str(interests).lower() for s in coach_signals):
            if any(s in str(interests).lower() for s in coach_signals):
                return "coach"

        # Family signals
        family_signals = ["parent", "family", "kid", "child", "teen", "daughter", "son"]
        if any(s in str(interests).lower() for s in family_signals):
            return "family"

        return "individual"

    async def _call_azure_openai(self, prompt: str) -> Optional[str]:
        """Call Azure OpenAI chat completions for strategy analysis."""
        endpoint = getattr(settings, "AZURE_OPENAI_ENDPOINT", "")
        api_key = getattr(settings, "AZURE_API_KEY", "")
        deployment = getattr(settings, "AZURE_OPENAI_CHAT_DEPLOYMENT", "")

        if not all([endpoint, api_key, deployment]):
            logger.error("Azure OpenAI not configured for marketing brain")
            return None

        url = (
            f"{endpoint}/openai/deployments/{deployment}"
            f"/chat/completions?api-version=2024-06-01"
        )
        headers = {"Content-Type": "application/json", "api-key": api_key}
        payload = {
            "messages": [
                {"role": "system", "content": "You are a marketing strategy analyst for an AI therapy platform."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 2000,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            return choices[0].get("message", {}).get("content", "")
                    else:
                        error_text = await resp.text()
                        logger.error(f"Azure OpenAI error ({resp.status}): {error_text[:200]}")
                        return None
        except Exception as e:
            logger.error(f"Azure OpenAI call failed: {e}")
            return None

    # ── Action Management ────────────────────────────────────────────

    async def get_pending_actions(self) -> List[Dict]:
        """Get all pending marketing actions."""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT * FROM marketing_actions
                    WHERE status IN ('proposed', 'approved', 'executing')
                    ORDER BY
                        CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
                             WHEN 'normal' THEN 2 WHEN 'low' THEN 3 END,
                        proposed_at DESC
                """)
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Failed to get pending actions: {e}")
            return []

    async def approve_action(self, action_id: int, approved_by: str = "big_nate") -> bool:
        """Approve a proposed marketing action."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE marketing_actions
                    SET status = 'approved', approved_at = NOW(), approved_by = $2
                    WHERE id = $1 AND status = 'proposed'
                """, action_id, approved_by)
                return True
        except Exception as e:
            logger.error(f"Failed to approve action {action_id}: {e}")
            return False

    async def reject_action(self, action_id: int, reason: str = "") -> bool:
        """Reject a proposed marketing action."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE marketing_actions
                    SET status = 'rejected', rejection_reason = $2, completed_at = NOW()
                    WHERE id = $1 AND status = 'proposed'
                """, action_id, reason)
                return True
        except Exception as e:
            logger.error(f"Failed to reject action {action_id}: {e}")
            return False

    async def complete_action(self, action_id: int, result: Dict = None) -> bool:
        """Mark an action as completed."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE marketing_actions
                    SET status = 'completed', completed_at = NOW(),
                        result = $2::jsonb
                    WHERE id = $1
                """, action_id, json.dumps(result or {}))
                return True
        except Exception as e:
            logger.error(f"Failed to complete action {action_id}: {e}")
            return False
