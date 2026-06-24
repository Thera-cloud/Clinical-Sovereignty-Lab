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

# post_* action_type → platform slug
POST_ACTION_PLATFORMS = {
    "post_linkedin": "linkedin",
    "post_x": "x",
    "post_twitter": "x",
    "post_instagram": "instagram",
    "post_facebook": "facebook",
    "post_reddit": "reddit",
    "post_tiktok": "tiktok",
    "post_pinterest": "pinterest",
    "post_youtube": "youtube",
}


def platform_for_action_type(action_type: str, params: Optional[Dict] = None) -> str:
    """Resolve platform slug from marketing action type + parameters."""
    if params and params.get("platform"):
        return str(params["platform"])
    if action_type in POST_ACTION_PLATFORMS:
        return POST_ACTION_PLATFORMS[action_type]
    if action_type.startswith("post_"):
        return action_type[5:]
    return "linkedin"


def extract_post_body_from_proposal(description: str) -> str:
    """Pull publishable post text from a [PROPOSAL: post_*] description block."""
    import re

    text = (description or "").strip()
    if not text:
        return ""

    for pattern in (
        r"\*\*(.+?)\*\*",
        r'"([^"]{15,})"',
        r"'([^']{15,})'",
    ):
        match = re.search(pattern, text, re.DOTALL)
        if match:
            candidate = match.group(1).strip()
            if len(candidate) >= 15:
                return candidate[:3000]

    lowered = text.lower()
    for prefix in (
        "linkedin companion post:",
        "companion post:",
        "post for linkedin:",
        "linkedin post:",
        "draft post:",
        "draft:",
        "post:",
    ):
        if lowered.startswith(prefix):
            return text[len(prefix):].strip()[:3000]

    # Drop proposal boilerplate lines; keep substantive body
    skip_fragments = (
        "shall i post", "awaiting approval", "say approved", "say approve",
        "verification protocol", "deployment status", "little nate proposes",
    )
    kept = []
    for line in text.splitlines():
        line_stripped = line.strip()
        if not line_stripped:
            continue
        ll = line_stripped.lower()
        if any(frag in ll for frag in skip_fragments):
            continue
        kept.append(line_stripped)
    body = "\n".join(kept).strip()
    return (body or text)[:3000]


def is_post_action_type(action_type: str) -> bool:
    """True if this marketing action type publishes social content."""
    return action_type.startswith("post_") or action_type in POST_ACTION_PLATFORMS


def extract_embedded_post_from_approval_message(message: str) -> Optional[tuple]:
    """If Big Nate pasted a full post with approval, return (platform, content_text)."""
    import re

    text = (message or "").strip()
    if not text:
        return None

    msg_lower = text.lower()
    post_intent = any(
        p in msg_lower
        for p in (
            "approved to post",
            "approve and post",
            "approved — post",
            "approved - post",
            "post now",
            "publish now",
            "post this now",
        )
    ) or (("approved" in msg_lower or "approve" in msg_lower) and "post" in msg_lower)

    if not post_intent:
        return None

    platform = "linkedin"
    if re.search(r"\b(on|to)\s+x\b", msg_lower) or "twitter" in msg_lower:
        platform = "x"
    elif "instagram" in msg_lower:
        platform = "instagram"
    elif "facebook" in msg_lower:
        platform = "facebook"

    body = ""
    colon_idx = text.find(":")
    if colon_idx > 0:
        prefix = text[:colon_idx].lower()
        if any(k in prefix for k in ("approved", "approve", "post", "publish")):
            body = text[colon_idx + 1:].strip()

    if len(body) < 80:
        return None

    return platform, body[:3000]


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

    async def ensure_playbook_exists(self) -> bool:
        """Seed a default playbook if none exists."""
        try:
            async with self.db_pool.acquire() as conn:
                exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM marketing_playbook)"
                )
                if exists:
                    return True

                default_pillars = json.dumps([
                    {"name": "Emotional Wellness", "weight": 0.35,
                     "description": "Content about emotional health, self-awareness, and healing"},
                    {"name": "Relationship Intelligence", "weight": 0.25,
                     "description": "Family dynamics, couple therapy insights, attachment styles"},
                    {"name": "AI-Powered Therapy", "weight": 0.20,
                     "description": "How Little Nate works, AI companion benefits, tech + therapy"},
                    {"name": "Clinical Research", "weight": 0.10,
                     "description": "Nevedal formula insights, coherence science, evidence-based approaches"},
                    {"name": "Community Stories", "weight": 0.10,
                     "description": "Success stories, testimonials, community engagement"},
                ])
                default_audiences = json.dumps([
                    {"name": "Therapy-Curious Adults", "age_range": "25-45",
                     "platforms": ["instagram", "tiktok", "youtube"]},
                    {"name": "Mental Health Professionals", "age_range": "30-55",
                     "platforms": ["linkedin", "x", "youtube"]},
                    {"name": "Parents & Families", "age_range": "30-50",
                     "platforms": ["facebook", "instagram", "pinterest"]},
                ])
                default_funnels = json.dumps([
                    {"name": "Social → Quiz → Trial", "stages": ["awareness", "engagement", "quiz", "trial", "conversion"]},
                    {"name": "Content → Email Drip → Signup", "stages": ["content", "subscribe", "drip", "signup"]},
                ])
                default_benchmarks = json.dumps({
                    "engagement_rate_target": 0.03,
                    "follower_growth_weekly": 50,
                    "quiz_completion_rate": 0.65,
                    "trial_to_paid_rate": 0.15,
                })
                empty_json = json.dumps([])
                default_content_mix = json.dumps({
                    "instagram": {
                        "emotional_wellness": 0.40, "community_stories": 0.25,
                        "ai_powered_therapy": 0.20, "relationship_intelligence": 0.15,
                    },
                    "tiktok": {
                        "emotional_wellness": 0.45, "community_stories": 0.30,
                        "ai_powered_therapy": 0.15, "clinical_research": 0.10,
                    },
                    "linkedin": {
                        "clinical_research": 0.35, "ai_powered_therapy": 0.30,
                        "relationship_intelligence": 0.20, "emotional_wellness": 0.15,
                    },
                    "x": {
                        "emotional_wellness": 0.30, "ai_powered_therapy": 0.30,
                        "clinical_research": 0.20, "community_stories": 0.20,
                    },
                    "youtube": {
                        "emotional_wellness": 0.30, "relationship_intelligence": 0.25,
                        "ai_powered_therapy": 0.25, "clinical_research": 0.20,
                    },
                    "facebook": {
                        "community_stories": 0.35, "emotional_wellness": 0.30,
                        "relationship_intelligence": 0.20, "ai_powered_therapy": 0.15,
                    },
                    "reddit": {
                        "clinical_research": 0.30, "ai_powered_therapy": 0.30,
                        "emotional_wellness": 0.25, "community_stories": 0.15,
                    },
                    "pinterest": {
                        "emotional_wellness": 0.50, "community_stories": 0.30,
                        "relationship_intelligence": 0.20,
                    },
                })

                await conn.execute("""
                    INSERT INTO marketing_playbook
                        (content_pillars, target_audiences, conversion_funnels,
                         performance_benchmarks, competitive_notes, active_campaigns,
                         regional_focus, collaboration_targets, content_mix,
                         posting_schedule, version, updated_at)
                    VALUES ($1::jsonb, $2::jsonb, $3::jsonb, $4::jsonb,
                            $5::jsonb, $6::jsonb, $7::jsonb, $8::jsonb,
                            $9::jsonb, $10::jsonb, 1, NOW())
                """, default_pillars, default_audiences, default_funnels,
                     default_benchmarks, empty_json, empty_json,
                     empty_json, empty_json, default_content_mix, empty_json)

                logger.info("Marketing playbook seeded with defaults")
                return True
        except Exception as e:
            logger.error(f"Failed to seed playbook: {e}")
            return False

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
                    await self.ensure_playbook_exists()
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

        # Enrich with unified wisdom (therapy patterns, coherence data, web insights)
        unified_wisdom = await self._get_unified_wisdom_for_strategy()

        analysis_data = {
            "current_playbook": {
                "content_pillars": playbook.get("content_pillars", []),
                "content_mix": playbook.get("content_mix", {}),
                "target_audiences": playbook.get("target_audiences", {}),
            },
            "performance_7d": results,
            "unified_wisdom": unified_wisdom,
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
        endpoint = getattr(settings, "AZURE_OPENAI_ENDPOINT", "").rstrip("/")
        api_key = getattr(settings, "AZURE_API_KEY", "")
        deployment = getattr(settings, "AZURE_OPENAI_CHAT_DEPLOYMENT", "")

        if not all([endpoint, api_key, deployment]):
            logger.error("Azure OpenAI not configured for marketing brain")
            return None

        if not endpoint.startswith("http"):
            endpoint = f"https://{endpoint}"

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
            "max_completion_tokens": 4000,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=60)) as resp:
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

    async def approve_action(self, action_id: int, approved_by: str = "big_nate") -> Dict[str, Any]:
        """Approve a proposed marketing action and trigger execution."""
        try:
            async with self.db_pool.acquire() as conn:
                updated = await conn.fetchrow("""
                    UPDATE marketing_actions
                    SET status = 'approved', approved_at = NOW(), approved_by = $2
                    WHERE id = $1 AND status = 'proposed'
                    RETURNING id
                """, action_id, approved_by)
                if not updated:
                    return {"error": f"Action {action_id} not found or not in proposed status",
                            "action_id": action_id}

            result = await self.execute_approved_action(action_id)
            if result and not result.get("error"):
                logger.info(f"Action {action_id} approved and executed: {result.get('summary', 'ok')}")
            return result or {"error": "Execution returned no result", "action_id": action_id}
        except Exception as e:
            logger.error(f"Failed to approve action {action_id}: {e}")
            return {"error": str(e), "action_id": action_id}

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

    # ── Execution Bridge ──────────────────────────────────────────────

    async def execute_approved_action(self, action_id: int) -> Dict[str, Any]:
        """Route an approved action to its execution handler."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM marketing_actions WHERE id = $1", action_id
                )
                if not row:
                    return {"error": f"Action {action_id} not found"}

                action_type = row["action_type"]
                params = json.loads(row["parameters"]) if isinstance(row["parameters"], str) else (row["parameters"] or {})

                await conn.execute(
                    "UPDATE marketing_actions SET status = 'executing', started_at = NOW() WHERE id = $1",
                    action_id,
                )

            if action_type == "launch_campaign":
                result = await self.design_campaign(action_id)
            elif action_type in ("shift_content_mix", "adjust_schedule"):
                await self.update_playbook(params)
                result = {"summary": f"Playbook updated via {action_type}", "action_id": action_id}
            elif is_post_action_type(action_type):
                result = await self._execute_single_post(action_id, row, params)
            else:
                result = {
                    "summary": f"Action '{action_type}' logged — not a social publish action",
                    "posted": False,
                    "action_type": action_type,
                    "action_id": action_id,
                }

            await self.complete_action(action_id, result)
            return result
        except Exception as e:
            logger.error(f"Execution bridge error for action {action_id}: {e}")
            return {"error": str(e)}

    async def _execute_single_post(self, action_id: int, row, params: Dict) -> Dict:
        """Publish an approved post (stored body) or generate then publish inline."""
        try:
            from app.services.skyeye_content_generator import SkyEyeContentGenerator
            gen = SkyEyeContentGenerator(self.db_pool)

            action_type = row["action_type"]
            platform = platform_for_action_type(action_type, params)
            content_type = params.get("content_type", "post")
            content_text = (
                params.get("content_text")
                or params.get("content")
                or extract_post_body_from_proposal(row["description"] or "")
            )

            if not content_text or len(content_text.strip()) < 10:
                topic = row["description"] or row["title"]
                generated = await gen.generate_strategic_post(
                    platform, context={"strategy_pillar": topic},
                )
                if not generated.get("safe"):
                    return {"error": "Content failed safety check", "platform": platform}
                content_text = generated["content"]
                content_type = generated.get("content_type", content_type)

            return await self.publish_content_inline(
                platform=platform,
                content_text=content_text,
                content_type=content_type,
                approved_by="big_nate",
                action_id=action_id,
                generated_by="marketing_brain",
            )
        except Exception as e:
            logger.error(f"Single post execution error: {e}")
            return {"error": str(e)}

    async def publish_content_inline(
        self,
        platform: str,
        content_text: str,
        content_type: str = "post",
        approved_by: str = "big_nate",
        action_id: Optional[int] = None,
        generated_by: str = "marketing_brain",
        media_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Queue content and publish immediately via the platform adapter."""
        from app.services.platforms import get_adapter
        from app.services.skyeye_content_generator import SkyEyeContentGenerator
        from app.services.skyeye_platform_base import ContentType

        gen = SkyEyeContentGenerator(self.db_pool)
        queue_id = await gen.queue_content(
            platform=platform,
            content=content_text,
            content_type=content_type,
            generated_by=generated_by,
            media_url=media_url,
        )
        if not queue_id:
            return {"error": "Failed to queue content", "platform": platform}

        adapter = get_adapter(platform, self.db_pool)
        if not adapter or not await adapter.authenticate():
            await gen.update_queue_status(
                queue_id, "failed", error_message="Platform adapter unavailable or not authenticated",
            )
            return {
                "error": f"{platform} adapter unavailable or not authenticated",
                "platform": platform,
                "queue_id": queue_id,
                "posted": False,
            }

        post_ct = ContentType.ARTICLE if content_type == "article" else ContentType.POST
        publish = await adapter.post_content(
            text=content_text,
            media_url=media_url,
            content_type=post_ct,
        )
        if publish and publish.success:
            await gen.update_queue_status(
                queue_id,
                "posted",
                approved_by=approved_by,
                post_id_external=publish.post_id,
                post_url=publish.post_url,
            )
            return {
                "summary": f"Post published to {platform}",
                "platform": platform,
                "queue_id": queue_id,
                "posted": True,
                "post_id": publish.post_id,
                "post_url": publish.post_url,
                "action_id": action_id,
                "content_preview": content_text[:120],
            }

        err = (publish.error if publish else "adapter returned None")
        await gen.update_queue_status(queue_id, "failed", error_message=err)
        return {
            "error": err,
            "platform": platform,
            "queue_id": queue_id,
            "posted": False,
            "action_id": action_id,
        }

    # ── Campaign Designer ─────────────────────────────────────────────

    CAMPAIGN_DESIGN_PROMPT = """You are Little Nate's Campaign Architect.
Design a multi-episode social media campaign based on the proposal below.

Return ONLY valid JSON with this structure:
{{
  "episodes": [
    {{
      "episode_number": 1,
      "title": "Episode title",
      "cliff_hanger_hook": "The hook that makes people come back",
      "platforms": [
        {{
          "platform": "linkedin",
          "content_angle": "Professional angle for this episode",
          "content_type": "post"
        }},
        {{
          "platform": "tiktok",
          "content_angle": "Casual/visual angle for this episode",
          "content_type": "video_script"
        }}
      ]
    }}
  ]
}}

RULES:
- Each episode should end with a cliff-hanger or audience question
- Adapt content angle per platform voice
- Mark video platforms (tiktok, instagram) as content_type "video_script"
- Mark text platforms (linkedin, reddit, facebook, x) as content_type "post"
- X (Twitter) posts must be under 280 characters — sharp, punchy, thread-ready
"""

    async def design_campaign(self, action_id: int) -> Dict[str, Any]:
        """Design a full multi-episode campaign from an approved marketing action."""
        try:
            async with self.db_pool.acquire() as conn:
                action = await conn.fetchrow(
                    "SELECT * FROM marketing_actions WHERE id = $1", action_id
                )
                if not action:
                    return {"error": "Action not found"}

            params = json.loads(action["parameters"]) if isinstance(action["parameters"], str) else (action["parameters"] or {})
            template_name = params.get("template_name")
            platforms = params.get("platforms", ["linkedin", "reddit", "tiktok", "instagram", "x"])
            total_episodes = params.get("total_episodes", 5)
            interval_hours = params.get("interval_hours", 24)
            ab_enabled = params.get("ab_test_enabled", False)
            narrative = action["description"] or action["title"]

            template = None
            if template_name:
                template = await self._load_template(template_name)
                if template:
                    total_episodes = template.get("default_episode_count", total_episodes)
                    interval_hours = template.get("default_interval_hours", interval_hours)
                    platforms = template.get("default_platforms", platforms)

            me2me_themes = await self._get_me2me_themes()

            design_prompt = (
                f"{self.CAMPAIGN_DESIGN_PROMPT}\n\n"
                f"PROPOSAL: {narrative}\n"
                f"PLATFORMS: {', '.join(platforms)}\n"
                f"TOTAL EPISODES: {total_episodes}\n"
                f"EMOTIONAL THEMES FROM REAL SESSIONS (anonymized): {me2me_themes}\n"
            )
            if template:
                design_prompt += f"\nTEMPLATE STRUCTURE: {json.dumps(template.get('episode_structure', []))}\n"

            ai_response = await self._call_azure_openai(design_prompt)
            if not ai_response:
                return {"error": "AI campaign design failed"}

            try:
                start = ai_response.find("{")
                end = ai_response.rfind("}") + 1
                plan = json.loads(ai_response[start:end]) if start >= 0 else {"episodes": []}
            except json.JSONDecodeError:
                plan = {"episodes": []}

            episodes = plan.get("episodes", [])
            if not episodes:
                return {"error": "AI returned no episodes"}

            async with self.db_pool.acquire() as conn:
                campaign_row = await conn.fetchrow("""
                    INSERT INTO storytelling_campaigns
                        (title, narrative_premise, campaign_type, template_name,
                         platforms, total_episodes, episode_interval_hours,
                         ab_test_enabled, ab_test_config, marketing_action_id,
                         min_engagement_threshold, extend_engagement_threshold,
                         drip_touchpoints, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10,
                            $11, $12, $13::jsonb, 'active')
                    RETURNING id
                """,
                    action["title"], narrative,
                    "storytelling" if template_name else "standard",
                    template_name, platforms, len(episodes), interval_hours,
                    ab_enabled, json.dumps(params.get("ab_config", {})),
                    action_id,
                    params.get("min_engagement_threshold", 0),
                    params.get("extend_engagement_threshold", 0),
                    json.dumps(params.get("drip_touchpoints", [])),
                )
                campaign_id = campaign_row["id"]

            from app.services.skyeye_content_generator import SkyEyeContentGenerator
            gen = SkyEyeContentGenerator(self.db_pool)

            total_queued = 0
            prev_episode_last_id = None
            now = datetime.utcnow()

            for ep in episodes:
                ep_num = ep.get("episode_number", 1)
                ep_platforms = ep.get("platforms", [{"platform": p, "content_angle": narrative, "content_type": "post"} for p in platforms])
                scheduled_time = now + timedelta(hours=interval_hours * (ep_num - 1))
                ep_queue_ids = []

                for seq_idx, plat_spec in enumerate(ep_platforms):
                    plat = plat_spec.get("platform", "linkedin")
                    angle = plat_spec.get("content_angle", narrative)
                    ctype = plat_spec.get("content_type", "post")

                    if ctype == "video_script":
                        content_result = await self._generate_video_content(gen, plat, angle, ep)
                    else:
                        content_result = await gen.generate_post(plat, angle, context={
                            "strategy_pillar": narrative,
                            "episode": ep_num,
                            "cliff_hanger": ep.get("cliff_hanger_hook", ""),
                        })

                    if not content_result.get("safe") and not content_result.get("content"):
                        continue

                    video_script_json = None
                    content_text = content_result.get("content", "")
                    if ctype == "video_script" and content_result.get("video_script"):
                        video_script_json = json.dumps(content_result["video_script"])

                    async with self.db_pool.acquire() as conn:
                        row = await conn.fetchrow("""
                            INSERT INTO skyeye_content_queue
                                (platform, content_text, content_type, status, priority,
                                 scheduled_for, generated_by, campaign_id, episode_number,
                                 sequence_order, depends_on_post_id, ab_variant,
                                 video_script, created_at, updated_at)
                            VALUES ($1, $2, $3, $4, 'normal', $5, 'campaign_designer',
                                    $6, $7, $8, $9, $10, $11::jsonb, NOW(), NOW())
                            RETURNING id
                        """,
                            plat, content_text, ctype,
                            "scheduled" if scheduled_time else "draft",
                            scheduled_time, campaign_id, ep_num, seq_idx,
                            prev_episode_last_id,
                            "A" if (ab_enabled and seq_idx < len(ep_platforms) // 2) else
                            ("B" if ab_enabled else None),
                            video_script_json,
                        )
                        ep_queue_ids.append(row["id"])
                        total_queued += 1

                if ep_queue_ids:
                    await self._apply_cross_thread_refs(ep_queue_ids)
                    prev_episode_last_id = ep_queue_ids[-1]

            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE storytelling_campaigns SET current_episode = 1 WHERE id = $1",
                    campaign_id,
                )

            result = {
                "summary": f"Campaign designed: {len(episodes)} episodes, {total_queued} posts queued",
                "campaign_id": campaign_id,
                "episodes": len(episodes),
                "posts_queued": total_queued,
            }
            logger.info(f"Campaign {campaign_id} designed: {result['summary']}")
            return result

        except Exception as e:
            logger.error(f"Campaign design error: {e}")
            return {"error": str(e)}

    async def generate_next_episode(self, campaign_id: int,
                                     audience_feedback: Dict = None,
                                     ab_winner: str = None) -> Dict[str, Any]:
        """Generate the next episode for an active campaign using audience feedback."""
        try:
            async with self.db_pool.acquire() as conn:
                campaign = await conn.fetchrow(
                    "SELECT * FROM storytelling_campaigns WHERE id = $1", campaign_id
                )
                if not campaign:
                    return {"error": "Campaign not found"}
                if campaign["status"] != "active":
                    return {"error": f"Campaign is {campaign['status']}, not active"}

                next_ep = campaign["current_episode"] + 1
                if next_ep > campaign["total_episodes"]:
                    return {"error": "All episodes completed"}

                prev_posts = await conn.fetch("""
                    SELECT content_text, platform, episode_number
                    FROM skyeye_content_queue
                    WHERE campaign_id = $1 AND episode_number = $2
                    ORDER BY sequence_order
                """, campaign_id, campaign["current_episode"])

            prev_summary = "; ".join(
                f"[{p['platform']}] {p['content_text'][:150]}" for p in prev_posts
            ) if prev_posts else "No previous content"

            feedback_str = json.dumps(audience_feedback or {}, default=str)[:500]
            me2me_themes = await self._get_me2me_themes()

            template = None
            if campaign["template_name"]:
                template = await self._load_template(campaign["template_name"])

            ep_prompt_template = ""
            if template and template.get("narrative_prompts", {}).get("episode_prompt_template"):
                ep_prompt_template = template["narrative_prompts"]["episode_prompt_template"]
                ep_structure = template.get("episode_structure", [])
                ep_info = next((e for e in ep_structure if e.get("episode") == next_ep), {})
                ep_prompt_template = (
                    ep_prompt_template
                    .replace("{{episode_number}}", str(next_ep))
                    .replace("{{total_episodes}}", str(campaign["total_episodes"]))
                    .replace("{{episode_title}}", ep_info.get("title", f"Episode {next_ep}"))
                    .replace("{{episode_purpose}}", ep_info.get("purpose", "continue the story"))
                    .replace("{{previous_episode}}", prev_summary[:300])
                    .replace("{{audience_feedback}}", feedback_str[:300])
                    .replace("{{me2me_themes}}", me2me_themes[:300])
                )

            prompt = ep_prompt_template or (
                f"Generate Episode {next_ep} of {campaign['total_episodes']} "
                f"for campaign '{campaign['title']}'.\n"
                f"Premise: {campaign['narrative_premise']}\n"
                f"Previous episode content: {prev_summary[:300]}\n"
                f"Audience feedback: {feedback_str[:300]}\n"
                f"Emotional themes: {me2me_themes[:300]}\n"
                f"{'A/B winner approach: ' + ab_winner if ab_winner else ''}\n"
                f"Write platform-adapted content. End with a cliff-hanger."
            )

            from app.services.skyeye_content_generator import SkyEyeContentGenerator
            gen = SkyEyeContentGenerator(self.db_pool)

            platforms = campaign["platforms"] or ["linkedin", "reddit", "tiktok"]
            now = datetime.utcnow()
            scheduled_time = now + timedelta(hours=campaign["episode_interval_hours"])

            async with self.db_pool.acquire() as conn:
                last_posted = await conn.fetchval("""
                    SELECT MAX(id) FROM skyeye_content_queue
                    WHERE campaign_id = $1 AND episode_number = $2 AND status = 'posted'
                """, campaign_id, campaign["current_episode"])

            ep_queue_ids = []
            for seq_idx, plat in enumerate(platforms):
                post_result = await gen.generate_post(plat, prompt)
                if not post_result.get("safe"):
                    continue

                async with self.db_pool.acquire() as conn:
                    row = await conn.fetchrow("""
                        INSERT INTO skyeye_content_queue
                            (platform, content_text, content_type, status, priority,
                             scheduled_for, generated_by, campaign_id, episode_number,
                             sequence_order, depends_on_post_id, ab_variant,
                             created_at, updated_at)
                        VALUES ($1, $2, 'post', 'scheduled', 'normal', $3,
                                'next_episode_gen', $4, $5, $6, $7, $8, NOW(), NOW())
                        RETURNING id
                    """,
                        plat, post_result["content"], scheduled_time,
                        campaign_id, next_ep, seq_idx, last_posted,
                        "A" if (campaign["ab_test_enabled"] and seq_idx < len(platforms) // 2) else
                        ("B" if campaign["ab_test_enabled"] else None),
                    )
                    ep_queue_ids.append(row["id"])

            if ep_queue_ids:
                await self._apply_cross_thread_refs(ep_queue_ids)

            async with self.db_pool.acquire() as conn:
                existing_feedback = json.loads(campaign["audience_feedback"]) if isinstance(campaign["audience_feedback"], str) else (campaign["audience_feedback"] or [])
                existing_feedback.append({
                    "episode": campaign["current_episode"],
                    "feedback": audience_feedback or {},
                    "ab_winner": ab_winner,
                })
                await conn.execute("""
                    UPDATE storytelling_campaigns
                    SET current_episode = $2, audience_feedback = $3::jsonb, updated_at = NOW()
                    WHERE id = $1
                """, campaign_id, next_ep, json.dumps(existing_feedback))

            return {
                "summary": f"Episode {next_ep} generated: {len(ep_queue_ids)} posts queued",
                "campaign_id": campaign_id,
                "episode": next_ep,
                "posts_queued": len(ep_queue_ids),
            }
        except Exception as e:
            logger.error(f"Next episode generation error: {e}")
            return {"error": str(e)}

    # ── Campaign Management ───────────────────────────────────────────

    async def get_campaigns(self, status: str = None) -> List[Dict]:
        """List campaigns with optional status filter."""
        try:
            async with self.db_pool.acquire() as conn:
                if status:
                    rows = await conn.fetch(
                        "SELECT * FROM storytelling_campaigns WHERE status = $1 ORDER BY created_at DESC",
                        status,
                    )
                else:
                    rows = await conn.fetch(
                        "SELECT * FROM storytelling_campaigns ORDER BY created_at DESC"
                    )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Failed to get campaigns: {e}")
            return []

    async def get_campaign_detail(self, campaign_id: int) -> Dict[str, Any]:
        """Get full campaign detail with episode posts and feedback."""
        try:
            async with self.db_pool.acquire() as conn:
                campaign = await conn.fetchrow(
                    "SELECT * FROM storytelling_campaigns WHERE id = $1", campaign_id
                )
                if not campaign:
                    return {"error": "Not found"}

                posts = await conn.fetch("""
                    SELECT id, platform, content_text, content_type, status,
                           episode_number, sequence_order, ab_variant, scheduled_for,
                           posted_at, post_url, cross_thread_refs, video_script
                    FROM skyeye_content_queue
                    WHERE campaign_id = $1
                    ORDER BY episode_number, sequence_order
                """, campaign_id)

                return {
                    **dict(campaign),
                    "posts": [dict(p) for p in posts],
                }
        except Exception as e:
            logger.error(f"Failed to get campaign detail: {e}")
            return {"error": str(e)}

    async def pause_campaign(self, campaign_id: int) -> bool:
        """Pause an active campaign."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE storytelling_campaigns SET status = 'paused', updated_at = NOW() WHERE id = $1",
                    campaign_id,
                )
                return True
        except Exception as e:
            logger.error(f"Failed to pause campaign: {e}")
            return False

    async def resume_campaign(self, campaign_id: int) -> bool:
        """Resume a paused campaign."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE storytelling_campaigns SET status = 'active', updated_at = NOW() WHERE id = $1",
                    campaign_id,
                )
                return True
        except Exception as e:
            logger.error(f"Failed to resume campaign: {e}")
            return False

    async def extend_campaign(self, campaign_id: int, extra_episodes: int = 2) -> Dict:
        """Add more episodes to a running campaign."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE storytelling_campaigns
                    SET total_episodes = total_episodes + $2, updated_at = NOW()
                    WHERE id = $1
                """, campaign_id, extra_episodes)
                return {"extended_by": extra_episodes}
        except Exception as e:
            logger.error(f"Failed to extend campaign: {e}")
            return {"error": str(e)}

    async def check_engagement_thresholds(self, campaign_id: int,
                                           episode_engagement: Dict) -> Optional[str]:
        """Check if a campaign should be paused or extended based on engagement.

        Returns: 'pause', 'extend', or None.
        """
        try:
            async with self.db_pool.acquire() as conn:
                campaign = await conn.fetchrow(
                    "SELECT * FROM storytelling_campaigns WHERE id = $1", campaign_id
                )
                if not campaign:
                    return None

            total = sum(episode_engagement.get(k, 0) for k in ("comments", "likes", "shares"))
            min_thresh = campaign["min_engagement_threshold"] or 0
            ext_thresh = campaign["extend_engagement_threshold"] or 0

            if min_thresh > 0 and total < min_thresh:
                await self.pause_campaign(campaign_id)
                logger.warning(f"Campaign {campaign_id} auto-paused: engagement {total} < threshold {min_thresh}")
                return "pause"

            if ext_thresh > 0 and total > ext_thresh:
                await self.extend_campaign(campaign_id, extra_episodes=2)
                logger.info(f"Campaign {campaign_id} auto-extended: engagement {total} > threshold {ext_thresh}")
                return "extend"

            return None
        except Exception as e:
            logger.error(f"Engagement threshold check error: {e}")
            return None

    # ── Private Helpers ───────────────────────────────────────────────

    async def _load_template(self, name: str) -> Optional[Dict]:
        """Load a campaign template by name."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM campaign_templates WHERE name = $1", name
                )
                if not row:
                    return None
                return {
                    "name": row["name"],
                    "description": row["description"],
                    "episode_structure": json.loads(row["episode_structure"]) if isinstance(row["episode_structure"], str) else row["episode_structure"],
                    "default_platforms": row["default_platforms"],
                    "default_episode_count": row["default_episode_count"],
                    "default_interval_hours": row["default_interval_hours"],
                    "narrative_prompts": json.loads(row["narrative_prompts"]) if isinstance(row["narrative_prompts"], str) else row["narrative_prompts"],
                }
        except Exception as e:
            logger.error(f"Failed to load template {name}: {e}")
            return None

    async def _get_me2me_themes(self) -> str:
        """Extract anonymized emotional themes from Me-2-Me for campaign enrichment."""
        try:
            from app.services.me2me.legacy_vault_me2me import LegacyVaultMe2Me
            vault = LegacyVaultMe2Me(self.db_pool)
            themes = await vault.extract_thematic_content("emotional_themes")
            return json.dumps(themes, default=str)[:500] if themes else "No themes available"
        except Exception:
            return "Me-2-Me themes unavailable"

    async def _get_unified_wisdom_for_strategy(self) -> Dict:
        """Pull therapy patterns, coherence data, livestream insights, and web
        wisdom into a unified context for strategic playbook decisions."""
        wisdom = {}
        try:
            async with self.db_pool.acquire() as conn:
                # Therapy wisdom: what themes are clients working on?
                try:
                    therapy = await conn.fetch("""
                        SELECT insight_type, COUNT(*) as cnt
                        FROM wisdom_extractions
                        WHERE created_at > NOW() - INTERVAL '14 days'
                        GROUP BY insight_type ORDER BY cnt DESC
                    """)
                    wisdom["therapy_themes"] = {r["insight_type"]: r["cnt"] for r in therapy}
                except Exception:
                    wisdom["therapy_themes"] = {}

                # Nevedal coherence: avg C_emo and CEE rate
                try:
                    coh = await conn.fetchrow("""
                        SELECT AVG(metric_value) as avg_cemo,
                               COUNT(*) FILTER (WHERE metric_type = 'cee_event') as cee_count
                        FROM nevedal_metrics
                        WHERE created_at > NOW() - INTERVAL '7 days'
                    """)
                    wisdom["coherence"] = {
                        "avg_c_emo": round(float(coh["avg_cemo"] or 0), 3),
                        "cee_events_7d": coh["cee_count"],
                    }
                except Exception:
                    wisdom["coherence"] = {}

                # Livestream: what are viewers asking about?
                try:
                    live_q = await conn.fetch("""
                        SELECT viewer_question FROM livestream_wisdom
                        WHERE created_at > NOW() - INTERVAL '30 days'
                        ORDER BY created_at DESC LIMIT 20
                    """)
                    wisdom["livestream_questions"] = [r["viewer_question"][:100] for r in live_q]
                except Exception:
                    wisdom["livestream_questions"] = []

                # Web wisdom: what external themes are trending?
                try:
                    web = await conn.fetch("""
                        SELECT themes FROM web_wisdom
                        WHERE fetched_at > NOW() - INTERVAL '7 days'
                          AND relevance_score > 0.5
                        ORDER BY relevance_score DESC LIMIT 10
                    """)
                    all_themes = []
                    for r in web:
                        if r["themes"]:
                            all_themes.extend(r["themes"] if isinstance(r["themes"], list) else [])
                    wisdom["trending_external_themes"] = list(set(all_themes))[:10]
                except Exception:
                    wisdom["trending_external_themes"] = []

                # Insight journal: top actionable insights
                try:
                    insights = await conn.fetch("""
                        SELECT title, category, impact_score
                        FROM sovereign_insight_journal
                        WHERE NOT applied AND created_at > NOW() - INTERVAL '7 days'
                        ORDER BY impact_score DESC NULLS LAST LIMIT 5
                    """)
                    wisdom["actionable_insights"] = [
                        {"title": r["title"], "category": r["category"],
                         "impact": r["impact_score"]}
                        for r in insights
                    ]
                except Exception:
                    wisdom["actionable_insights"] = []

        except Exception as e:
            logger.warning(f"Unified wisdom gathering error: {e}")
        return wisdom

    async def _generate_video_content(self, gen, platform: str,
                                       angle: str, episode: Dict) -> Dict:
        """Generate video script content for a platform."""
        try:
            from app.services.skyeye_content_generator import SkyEyeContentGenerator
            result = await gen.generate_video_script(platform, angle, context={
                "episode_number": episode.get("episode_number"),
                "cliff_hanger": episode.get("cliff_hanger_hook", ""),
            })
            return result
        except Exception as e:
            logger.warning(f"Video script generation failed for {platform}: {e}")
            return await gen.generate_post(platform, angle)

    async def _apply_cross_thread_refs(self, queue_ids: List[int]):
        """Link all posts in an episode to each other for cross-platform threading."""
        if len(queue_ids) < 2:
            return
        try:
            async with self.db_pool.acquire() as conn:
                posts = await conn.fetch("""
                    SELECT id, platform FROM skyeye_content_queue WHERE id = ANY($1)
                """, queue_ids)
                refs = {str(p["id"]): p["platform"] for p in posts}
                for post in posts:
                    other_refs = {
                        r["platform"]: r["id"]
                        for r in posts if r["id"] != post["id"]
                    }
                    await conn.execute("""
                        UPDATE skyeye_content_queue
                        SET cross_thread_refs = $2::jsonb
                        WHERE id = $1
                    """, post["id"], json.dumps(other_refs))
        except Exception as e:
            logger.error(f"Cross-thread refs error: {e}")
