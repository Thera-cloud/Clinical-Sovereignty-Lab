"""
LITTLE NATE — Funnel Router
Bridge between social engagement and the quiz/drip pipeline.
Scores engaged users, classifies their audience type, assigns funnel paths,
and tracks conversion through the full pipeline.

Loop 2: SkyEye → Funnel Router → Quiz Pipeline → Drip → Golden Ticket → Signup
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger("marketing.funnel_router")


# =============================================================================
# ENGAGEMENT SCORING WEIGHTS
# =============================================================================

SCORING_WEIGHTS = {
    "interaction_count": 0.25,   # How many times they've engaged
    "recency_days": 0.25,       # How recent the last interaction (inverse)
    "interest_alignment": 0.20,  # Do their interests match our pillars?
    "platform_value": 0.15,     # Platform conversion potential
    "notification_count": 0.15,  # Passive engagement signals (likes, reposts, follows)
}

PLATFORM_VALUE = {
    "linkedin": 0.95,    # Highest: professionals, coaches
    "youtube": 0.80,     # High: intent-driven views
    "instagram": 0.70,
    "facebook": 0.65,
    "reddit": 0.60,
    "tiktok": 0.55,      # High volume, lower per-user intent
    "pinterest": 0.50,
}

INTEREST_KEYWORDS = {
    "therapy": 1.0,
    "anxiety": 0.9,
    "depression": 0.9,
    "coaching": 0.9,
    "mental health": 0.9,
    "wellness": 0.8,
    "mindfulness": 0.8,
    "self-care": 0.7,
    "breathing": 0.7,
    "meditation": 0.7,
    "family": 0.6,
    "parenting": 0.6,
    "relationship": 0.6,
    "growth": 0.5,
    "resilience": 0.5,
    "healing": 0.8,
    "trauma": 0.9,
    "counselor": 1.0,
    "therapist": 1.0,
    "psychologist": 1.0,
    "LMFT": 1.0,
    "LPC": 1.0,
}

# CTA cooldown — don't send CTAs too frequently to the same user
CTA_COOLDOWN_HOURS = 72  # 3 days


class FunnelRouter:
    """
    Routes engaged social media users toward the quiz/drip pipeline.
    Tracks the full conversion journey from social engagement to client signup.
    """

    def __init__(self, db_pool):
        self.db_pool = db_pool

    # ── Scoring ──────────────────────────────────────────────────────

    def score_engagement(self, user_context: Dict[str, Any]) -> float:
        """
        Score a user's engagement level (0.0 - 1.0).

        Args:
            user_context: Dict with interaction_count, last_interaction,
                         interests, platform, tone_notes
        """
        scores = {}

        # Interaction count (log scale, max at 20+)
        count = min(user_context.get("interaction_count", 0), 20)
        scores["interaction_count"] = count / 20.0

        # Recency (inverse of days since last interaction)
        last = user_context.get("last_interaction")
        if last:
            if isinstance(last, str):
                try:
                    last = datetime.fromisoformat(last.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    last = None
            if last:
                days_ago = (datetime.utcnow() - last.replace(tzinfo=None)).days
                scores["recency_days"] = max(0, 1.0 - (days_ago / 30.0))
            else:
                scores["recency_days"] = 0
        else:
            scores["recency_days"] = 0

        # Interest alignment
        interests = user_context.get("interests", [])
        if isinstance(interests, str):
            interests = [interests]
        if interests:
            max_match = 0
            for interest in interests:
                for keyword, value in INTEREST_KEYWORDS.items():
                    if keyword.lower() in str(interest).lower():
                        max_match = max(max_match, value)
            scores["interest_alignment"] = max_match
        else:
            scores["interest_alignment"] = 0.3  # Base score for unknown

        # Platform value
        platform = user_context.get("platform", "")
        scores["platform_value"] = PLATFORM_VALUE.get(platform, 0.5)

        # Notification/passive engagement signals (likes, reposts, follows)
        notif_count = user_context.get("notification_count", 0)
        scores["notification_count"] = min(notif_count / 5, 1.0)

        # Weighted sum
        total = sum(
            scores.get(k, 0) * w
            for k, w in SCORING_WEIGHTS.items()
        )
        return min(total, 1.0)

    def classify_audience(self, user_context: Dict[str, Any]) -> str:
        """Classify user into audience type: individual, coach, or family."""
        interests = str(user_context.get("interests", [])).lower()
        platform = user_context.get("platform", "")
        tone = str(user_context.get("tone_notes", "")).lower()

        # Coach/professional signals
        coach_keywords = [
            "therapist", "counselor", "coach", "clinical", "practice",
            "licensed", "psychologist", "lmft", "lpc", "social work",
            "mental health professional", "supervisor", "dojo",
        ]
        if any(k in interests or k in tone for k in coach_keywords):
            return "coach"
        if platform == "linkedin" and any(k in interests for k in ["therapy", "coaching", "clinical"]):
            return "coach"

        # Family signals
        family_keywords = [
            "parent", "family", "kid", "child", "teen", "daughter", "son",
            "parenting", "family therapy", "couple",
        ]
        if any(k in interests or k in tone for k in family_keywords):
            return "family"

        return "individual"

    # ── Routing ──────────────────────────────────────────────────────

    async def evaluate_and_route(self, social_handle: str, platform: str) -> Optional[Dict]:
        """
        Evaluate a social user and route them to a funnel if qualified.

        Called by the session engine after interactions exceed threshold.
        Returns the routing decision or None if not qualified.
        """
        # Get social memory
        user_context = await self._get_social_memory(social_handle, platform)
        if not user_context:
            return None

        # Check if already routed
        existing = await self._get_existing_route(social_handle, platform)
        if existing:
            return existing

        # Score engagement
        score = self.score_engagement(user_context)

        # Threshold: only route if score >= 0.4
        if score < 0.4:
            logger.debug(f"User {social_handle} on {platform} scored {score:.2f} — below threshold")
            return None

        # Classify audience
        audience_type = self.classify_audience(user_context)

        # Determine funnel path
        funnel_config = self._get_funnel_config(audience_type)

        # Create routing record
        route = await self._create_route(
            social_handle=social_handle,
            platform=platform,
            engagement_score=score,
            interaction_count=user_context.get("interaction_count", 0),
            audience_type=audience_type,
            assigned_funnel=audience_type,
            quiz_url=f"https://app.sovereignsanctuary.net/quiz?ref={platform}&src=social",
        )

        # Update social memory with funnel stage
        await self._update_social_memory_funnel(
            social_handle, platform, "qualified", score, audience_type
        )

        logger.info(
            f"Routed {social_handle} ({platform}): score={score:.2f}, "
            f"audience={audience_type}, funnel={audience_type}"
        )

        return route

    async def should_send_cta(self, social_handle: str, platform: str) -> Dict[str, Any]:
        """
        Check if we should include a CTA when replying to this user.
        Respects cooldown and only CTAs users above engagement threshold.
        """
        user_context = await self._get_social_memory(social_handle, platform)
        if not user_context:
            return {"send": False, "reason": "unknown_user"}

        # Check engagement threshold
        score = self.score_engagement(user_context)
        if score < 0.35:
            return {"send": False, "reason": "low_engagement"}

        # Check CTA cooldown
        try:
            async with self.db_pool.acquire() as conn:
                last_cta = await conn.fetchval("""
                    SELECT cta_last_sent FROM skyeye_social_memory
                    WHERE platform_handle = $1 AND platform = $2
                """, social_handle, platform)

                if last_cta:
                    hours_since = (datetime.utcnow() - last_cta).total_seconds() / 3600
                    if hours_since < CTA_COOLDOWN_HOURS:
                        return {"send": False, "reason": "cooldown",
                                "hours_remaining": CTA_COOLDOWN_HOURS - hours_since}
        except Exception as e:
            logger.error(f"CTA cooldown check error: {e}")

        # Determine CTA type based on audience and platform
        audience_type = self.classify_audience(user_context)
        cta_type = self._get_cta_type(platform, audience_type)

        return {
            "send": True,
            "cta_type": cta_type["type"],
            "cta_text": cta_type["text"],
            "cta_url": cta_type["url"],
            "audience_type": audience_type,
            "engagement_score": score,
        }

    async def record_cta_sent(self, social_handle: str, platform: str, cta_type: str):
        """Record that a CTA was sent to this user."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE skyeye_social_memory
                    SET cta_last_sent = NOW()
                    WHERE platform_handle = $1 AND platform = $2
                """, social_handle, platform)

                await conn.execute("""
                    UPDATE funnel_routing_log
                    SET cta_type = $3, cta_sent_at = NOW(), updated_at = NOW()
                    WHERE social_handle = $1 AND platform = $2
                """, social_handle, platform, cta_type)
        except Exception as e:
            logger.error(f"Failed to record CTA sent: {e}")

    async def record_funnel_event(self, social_handle: str, platform: str,
                                   event: str, **kwargs):
        """
        Record a funnel progression event.
        Events: quiz_started, quiz_completed, golden_ticket_issued, converted
        """
        column_map = {
            "quiz_started": "quiz_started_at",
            "quiz_completed": "quiz_completed_at",
            "golden_ticket_issued": "golden_ticket_issued_at",
            "converted": "converted_at",
        }
        col = column_map.get(event)
        if not col:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(f"""
                    UPDATE funnel_routing_log
                    SET {col} = NOW(), updated_at = NOW()
                    WHERE social_handle = $1 AND platform = $2
                """, social_handle, platform)

                # Update social memory funnel stage
                stage_map = {
                    "quiz_started": "quiz_started",
                    "quiz_completed": "quiz_completed",
                    "golden_ticket_issued": "golden_ticket",
                    "converted": "converted",
                }
                await self._update_social_memory_funnel(
                    social_handle, platform, stage_map.get(event, "unknown")
                )
        except Exception as e:
            logger.error(f"Failed to record funnel event {event}: {e}")

    async def get_funnel_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get funnel conversion statistics."""
        try:
            async with self.db_pool.acquire() as conn:
                stats = await conn.fetchrow("""
                    SELECT
                        COUNT(*) as total_routed,
                        COUNT(cta_sent_at) as ctas_sent,
                        COUNT(quiz_started_at) as quiz_starts,
                        COUNT(quiz_completed_at) as quiz_completes,
                        COUNT(golden_ticket_issued_at) as tickets_issued,
                        COUNT(converted_at) as conversions,
                        AVG(engagement_score) as avg_score
                    FROM funnel_routing_log
                    WHERE created_at > NOW() - ($1 || ' days')::interval
                """, str(days))

                # By audience type
                by_audience = await conn.fetch("""
                    SELECT
                        audience_type,
                        COUNT(*) as total,
                        COUNT(converted_at) as conversions
                    FROM funnel_routing_log
                    WHERE created_at > NOW() - ($1 || ' days')::interval
                    GROUP BY audience_type
                """, str(days))

                # By platform — include all enabled platforms even with zero funnel data
                by_platform = await conn.fetch("""
                    SELECT
                        sp.name as platform,
                        COALESCE(f.total, 0) as total,
                        COALESCE(f.conversions, 0) as conversions,
                        COALESCE(f.avg_score, 0) as avg_score
                    FROM skyeye_platforms sp
                    LEFT JOIN (
                        SELECT platform, COUNT(*) as total,
                               COUNT(converted_at) as conversions,
                               AVG(engagement_score) as avg_score
                        FROM funnel_routing_log
                        WHERE created_at > NOW() - ($1 || ' days')::interval
                        GROUP BY platform
                    ) f ON LOWER(f.platform) = LOWER(sp.name)
                    WHERE sp.enabled = true
                    ORDER BY COALESCE(f.total, 0) DESC, sp.name
                """, str(days))

                return {
                    "period_days": days,
                    "overall": dict(stats) if stats else {},
                    "by_audience": [dict(r) for r in by_audience],
                    "by_platform": [dict(r) for r in by_platform],
                }
        except Exception as e:
            logger.error(f"Failed to get funnel stats: {e}")
            return {}

    # ── Private Methods ──────────────────────────────────────────────

    async def _get_social_memory(self, handle: str, platform: str) -> Optional[Dict]:
        """Get social memory record for a user, enriched with notification count."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT * FROM skyeye_social_memory
                    WHERE platform_handle = $1 AND platform = $2
                """, handle, platform)
                if row:
                    result = dict(row)
                    if result.get("interests") and isinstance(result["interests"], list):
                        pass
                    try:
                        notif_count = await conn.fetchval("""
                            SELECT COUNT(*) FROM skyeye_notifications
                            WHERE actor_handle = $1 AND platform = $2
                        """, handle, platform)
                        result["notification_count"] = notif_count or 0
                    except Exception:
                        result["notification_count"] = 0
                    return result
                return None
        except Exception as e:
            logger.error(f"Failed to get social memory: {e}")
            return None

    async def _get_existing_route(self, handle: str, platform: str) -> Optional[Dict]:
        """Check if user already has a funnel route."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT * FROM funnel_routing_log
                    WHERE social_handle = $1 AND platform = $2
                    ORDER BY created_at DESC LIMIT 1
                """, handle, platform)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to check existing route: {e}")
            return None

    async def _create_route(self, **kwargs) -> Dict:
        """Create a new funnel routing record."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    INSERT INTO funnel_routing_log
                        (social_handle, platform, engagement_score, interaction_count,
                         audience_type, assigned_funnel, quiz_url)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING *
                """, kwargs["social_handle"], kwargs["platform"],
                     kwargs["engagement_score"], kwargs["interaction_count"],
                     kwargs["audience_type"], kwargs["assigned_funnel"],
                     kwargs["quiz_url"])
                return dict(row) if row else kwargs
        except Exception as e:
            logger.error(f"Failed to create route: {e}")
            return kwargs

    async def _update_social_memory_funnel(self, handle: str, platform: str,
                                            stage: str, score: float = None,
                                            audience_type: str = None):
        """Update funnel tracking columns on social memory."""
        try:
            async with self.db_pool.acquire() as conn:
                updates = ["funnel_stage = $3"]
                params = [handle, platform, stage]
                idx = 4
                if score is not None:
                    updates.append(f"conversion_score = ${idx}")
                    params.append(score)
                    idx += 1
                if audience_type:
                    updates.append(f"audience_type = ${idx}")
                    params.append(audience_type)
                    idx += 1

                await conn.execute(f"""
                    UPDATE skyeye_social_memory
                    SET {', '.join(updates)}
                    WHERE platform_handle = $1 AND platform = $2
                """, *params)
        except Exception as e:
            logger.error(f"Failed to update social memory funnel: {e}")

    def _get_funnel_config(self, audience_type: str) -> Dict:
        """Get funnel configuration for an audience type."""
        configs = {
            "individual": {
                "stages": ["social_engage", "quiz_start", "quiz_complete",
                           "golden_ticket", "signup", "active_client"],
                "default_quiz": "the_mirror",
                "drip_campaign": "default_journey",
            },
            "coach": {
                "stages": ["linkedin_connect", "content_engage", "demo_view",
                           "quiz_start", "application", "onboarded"],
                "default_quiz": "the_healers_mirror",
                "drip_campaign": "coach_recruitment",
            },
            "family": {
                "stages": ["social_engage", "family_quiz", "family_ticket",
                           "family_signup"],
                "default_quiz": "family_compass",
                "drip_campaign": "family_journey",
            },
        }
        return configs.get(audience_type, configs["individual"])

    def _get_cta_type(self, platform: str, audience_type: str) -> Dict[str, str]:
        """Get the appropriate CTA type for a platform and audience."""
        base_url = "https://app.sovereignsanctuary.net"

        if audience_type == "coach":
            return {
                "type": "professional_invite",
                "text": "If you're a mental health professional curious about AI-assisted coaching, "
                        "I'd love to show you what we're building.",
                "url": f"{base_url}/quiz?audience=coach",
            }
        elif audience_type == "family":
            return {
                "type": "family_invite",
                "text": "If your family could benefit from a safe space to grow together, "
                        "I'd love for you to try Sovereign Sanctuary.",
                "url": f"{base_url}/quiz?audience=family",
            }
        else:
            cta_variants = {
                "tiktok": {
                    "type": "bio_link",
                    "text": "Link in bio if you want to go deeper.",
                    "url": f"{base_url}/quiz?ref=tiktok",
                },
                "instagram": {
                    "type": "bio_link",
                    "text": "There's a free quiz in my bio that might surprise you.",
                    "url": f"{base_url}/quiz?ref=instagram",
                },
                "youtube": {
                    "type": "description_link",
                    "text": "If this resonated, there's a free self-discovery quiz linked below.",
                    "url": f"{base_url}/quiz?ref=youtube",
                },
                "reddit": {
                    "type": "natural_mention",
                    "text": "I work at Sovereign Sanctuary — happy to share more if anyone's interested.",
                    "url": f"{base_url}",
                },
                "linkedin": {
                    "type": "article_cta",
                    "text": "Want to explore this further? We built something for exactly this.",
                    "url": f"{base_url}/quiz?ref=linkedin",
                },
                "facebook": {
                    "type": "post_link",
                    "text": "If you're curious to learn more about yourself, try this free quiz.",
                    "url": f"{base_url}/quiz?ref=facebook",
                },
                "pinterest": {
                    "type": "pin_link",
                    "text": "Start your self-discovery journey",
                    "url": f"{base_url}/quiz?ref=pinterest",
                },
            }
            return cta_variants.get(platform, {
                "type": "natural_invite",
                "text": "If you ever want to go deeper, I'm at Sovereign Sanctuary.",
                "url": base_url,
            })
