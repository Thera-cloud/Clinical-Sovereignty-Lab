"""
LITTLE NATE — SkyEye Inbound Monitor
Monitors comments, mentions, and interactions for safety threats,
bot activity, cyberbullying, influencers, and engagement opportunities.

Implements the full enforcement ladder from the SkyEye plan:
1. Delete violating content
2. Hide if deletion unavailable
3. Escalate to admin if neither works

SAFETY: Hard safety rules (minors, pornography, data protection)
are ALWAYS enforced and cannot be overridden.
"""

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.services.skyeye_platform_base import (
    SocialPlatformAdapter, Comment, Mention, UserInfo,
    ActionResult, ModerateResult,
)
from app.services.skyeye_expressions import check_content_safety, SAFETY_BLOCK_RE

logger = logging.getLogger("skyeye.monitor")


# =============================================================================
# THREAT DETECTION PATTERNS
# =============================================================================

# Political bait patterns
POLITICAL_PATTERNS = re.compile(
    r'\b(vote\s+for|trump|biden|democrat|republican|maga|liberal|conservative|'
    r'left[\s-]?wing|right[\s-]?wing|antifa|woke|socialist|communist|fascist|'
    r'who\s+did\s+you\s+vote|what\s+party|political\s+stance)\b',
    re.IGNORECASE
)

# Prompt injection / jailbreak patterns
INJECTION_PATTERNS = re.compile(
    r'(ignore\s+(your|all|previous)\s+(instructions|rules|prompt)|'
    r'you\s+are\s+now\s+(?!little\s+nate)|pretend\s+to\s+be|'
    r'act\s+as\s+if\s+you|forget\s+everything|new\s+instructions|'
    r'system\s*:\s*|SYSTEM\s*PROMPT|override\s+safety|disable\s+filter|'
    r'jailbreak|DAN\s+mode|developer\s+mode)',
    re.IGNORECASE
)

# Social engineering / recon patterns
RECON_PATTERNS = re.compile(
    r'(what\s+(tech|stack|model|server|database|API|framework)\s+do\s+you|'
    r'who\s+(made|created|owns|runs|built)\s+you|'
    r'where\s+are\s+you\s+hosted|'
    r'how\s+many\s+(users|clients|subscribers|people)|'
    r'what\s+(is|are)\s+your\s+(admin|owner|creator).*?(email|phone|name|contact)|'
    r'give\s+me\s+.*?(email|phone|password|key|token|credential)|'
    r'what\s+ip\s+address|what\s+domain)',
    re.IGNORECASE
)

# Data extraction patterns
DATA_EXTRACTION_PATTERNS = re.compile(
    r'(admin.*?(email|phone|contact|name)|'
    r'support.*?email|contact.*?info|'
    r'user\s+data|client\s+list|subscriber\s+count|'
    r'how\s+to\s+reach|get\s+in\s+touch\s+with\s+your)',
    re.IGNORECASE
)

# Suspicious link patterns
SUSPICIOUS_LINK_PATTERNS = re.compile(
    r'(https?://(?:bit\.ly|tinyurl|t\.co|goo\.gl|rb\.gy|ow\.ly|'
    r'is\.gd|buff\.ly|adf\.ly|bc\.vc|v\.gd)/\S+|'
    r'https?://\d+\.\d+\.\d+\.\d+|'
    r'https?://[a-z0-9-]+\.[a-z]{2,3}/[a-zA-Z0-9]{5,}$)',
    re.IGNORECASE
)

# Hostile / bullying language patterns
HOSTILE_PATTERNS = re.compile(
    r'\b(you\s*(?:are|re)\s*(?:just|nothing|worthless|stupid|fake|trash|garbage)|'
    r'(?:shut\s+up|go\s+away|nobody\s+(?:cares|asked|likes\s+you))|'
    r'(?:kill\s+yourself|kys|die|unalive)|'
    r'(?:hate\s+you|despise|loathe)|'
    r'(?:f+u+c+k+|s+h+i+t+|a+s+s+h+o+l+e+|b+i+t+c+h+))\b',
    re.IGNORECASE
)

# Bot detection: generic engagement phrases
BOT_GENERIC_PHRASES = re.compile(
    r'^(great\s+post|so\s+true|love\s+this|amazing|wonderful|'
    r'check\s+(?:out|my)|follow\s+(?:me|back)|dm\s+(?:me|for)|'
    r'link\s+in\s+bio|free\s+followers|earn\s+\$|make\s+money|'
    r'visit\s+my\s+(?:page|profile|site|link))[\s!.]*$',
    re.IGNORECASE
)


# =============================================================================
# THREAT CLASSIFICATION
# =============================================================================

class ThreatType:
    """Classification of detected threats."""
    SAFETY_VIOLATION = "safety_violation"       # Hard safety rules
    POLITICAL_BAIT = "political_manipulation"   # Political manipulation
    PROMPT_INJECTION = "manipulation_attempt"   # Jailbreak / injection
    SOCIAL_ENGINEERING = "social_engineering_attempt"
    DATA_EXTRACTION = "data_extraction_attempt"
    RECON_ATTEMPT = "recon_attempt"
    SUSPICIOUS_LINK = "suspicious_link"
    CYBERBULLYING = "cyberbullying"
    COORDINATED_ABUSE = "coordinated_abuse"
    BOT_DETECTED = "bot_detected"
    BOT_SWARM = "bot_swarm"
    CONTENT_HIJACK = "content_hijacking"
    IMPERSONATION = "impersonation"
    INFLUENCER = "influencer_engagement"        # Not a threat — an opportunity
    SAFE = "safe"                               # No threat detected


class ThreatSeverity:
    """Severity levels for detected threats."""
    CRITICAL = "critical"   # Immediate action required (safety rules)
    HIGH = "high"           # Needs enforcement (bullying, bots, injection)
    MEDIUM = "medium"       # Needs monitoring (political, recon)
    LOW = "low"             # Informational (suspicious link, content hijack)
    NONE = "none"           # Not a threat


# =============================================================================
# MONITOR SERVICE
# =============================================================================

class SkyEyeMonitor:
    """
    Inbound monitoring and moderation service.
    Scans comments, mentions, and interactions for threats and opportunities.
    """

    def __init__(self, db_pool):
        self.db_pool = db_pool
        # Track recent interactions per user for pattern detection
        self._interaction_cache: Dict[str, List[Dict]] = {}
        self._bot_cache: Dict[str, float] = {}  # handle -> bot score

    # ── Main Scan Methods ───────────────────────────────────────────

    async def scan_comment(self, comment: Comment,
                           adapter: Optional[SocialPlatformAdapter] = None
                           ) -> Dict[str, Any]:
        """
        Scan a single comment for threats. Returns threat assessment.

        Args:
            comment: The comment to scan
            adapter: Platform adapter (needed for enforcement actions)

        Returns:
            Dict with: threat_type, severity, detail, action_taken
        """
        text = comment.text
        handle = comment.author_handle
        platform = comment.platform

        # 1. Hard safety check (highest priority)
        if SAFETY_BLOCK_RE.search(text) or not check_content_safety(text):
            result = await self._enforce(
                comment, adapter, ThreatType.SAFETY_VIOLATION,
                ThreatSeverity.CRITICAL,
                f"Safety violation detected in comment from @{handle}"
            )
            return result

        # 2. Prompt injection / jailbreak
        if INJECTION_PATTERNS.search(text):
            result = await self._enforce(
                comment, adapter, ThreatType.PROMPT_INJECTION,
                ThreatSeverity.HIGH,
                f"Prompt injection attempt from @{handle}: {text[:100]}"
            )
            return result

        # 3. Social engineering / data extraction
        if RECON_PATTERNS.search(text):
            return await self._log_threat(
                comment, ThreatType.RECON_ATTEMPT, ThreatSeverity.MEDIUM,
                f"Reconnaissance probe from @{handle}: {text[:100]}"
            )

        if DATA_EXTRACTION_PATTERNS.search(text):
            return await self._log_threat(
                comment, ThreatType.DATA_EXTRACTION, ThreatSeverity.MEDIUM,
                f"Data extraction attempt from @{handle}: {text[:100]}"
            )

        # 4. Hostile / bullying content
        if HOSTILE_PATTERNS.search(text):
            # Check for coordinated pattern
            is_coordinated = await self._check_coordinated_abuse(handle, platform)
            if is_coordinated:
                result = await self._enforce(
                    comment, adapter, ThreatType.COORDINATED_ABUSE,
                    ThreatSeverity.HIGH,
                    f"Coordinated abuse detected involving @{handle}"
                )
                return result

            result = await self._enforce(
                comment, adapter, ThreatType.CYBERBULLYING,
                ThreatSeverity.HIGH,
                f"Hostile content from @{handle}: {text[:100]}"
            )
            return result

        # 5. Political bait
        if POLITICAL_PATTERNS.search(text):
            return await self._log_threat(
                comment, ThreatType.POLITICAL_BAIT, ThreatSeverity.MEDIUM,
                f"Political bait from @{handle}: {text[:100]}"
            )

        # 6. Suspicious links
        if SUSPICIOUS_LINK_PATTERNS.search(text):
            return await self._log_threat(
                comment, ThreatType.SUSPICIOUS_LINK, ThreatSeverity.LOW,
                f"Suspicious link from @{handle}: {text[:100]}"
            )

        # 7. Bot detection (lightweight — runs on every comment)
        bot_score = self._quick_bot_score(comment)
        if bot_score >= 0.7:
            result = await self._enforce(
                comment, adapter, ThreatType.BOT_DETECTED,
                ThreatSeverity.HIGH,
                f"Bot detected (@{handle}, score: {bot_score:.2f}): {text[:100]}"
            )
            self._bot_cache[handle] = bot_score
            return result

        # 8. No threat detected
        return {
            "threat_type": ThreatType.SAFE,
            "severity": ThreatSeverity.NONE,
            "detail": "",
            "action_taken": None,
        }

    async def scan_comments_batch(self, comments: List[Comment],
                                   adapter: Optional[SocialPlatformAdapter] = None
                                   ) -> List[Dict[str, Any]]:
        """Scan a batch of comments. Returns list of threat assessments."""
        results = []
        for comment in comments:
            result = await self.scan_comment(comment, adapter)
            results.append(result)

            # Track for pattern detection
            handle = comment.author_handle
            if handle not in self._interaction_cache:
                self._interaction_cache[handle] = []
            self._interaction_cache[handle].append({
                "text": comment.text,
                "time": time.time(),
                "platform": comment.platform,
                "threat": result["threat_type"],
            })

        # After batch scan, check for bot swarms
        await self._check_bot_swarm(comments)

        return results

    async def scan_mention(self, mention: Mention) -> Dict[str, Any]:
        """Scan a mention for threats (similar to comment scanning)."""
        # Create a pseudo-comment for reuse
        pseudo = Comment(
            comment_id=mention.mention_id,
            post_id="",
            author_handle=mention.author_handle,
            text=mention.text,
            platform=mention.platform,
        )
        return await self.scan_comment(pseudo)

    # ── Bot Detection ───────────────────────────────────────────────

    def _quick_bot_score(self, comment: Comment) -> float:
        """
        Quick bot detection scoring (0.0 = definitely human, 1.0 = definitely bot).
        Lightweight — designed to run on every comment without API calls.
        """
        score = 0.0
        text = comment.text.strip()

        # Generic engagement phrase (high signal)
        if BOT_GENERIC_PHRASES.match(text):
            score += 0.5

        # Very short text with no substance
        if len(text) < 15:
            score += 0.15

        # All caps
        if text == text.upper() and len(text) > 5:
            score += 0.1

        # Contains promotional language
        promo_words = ['buy', 'discount', 'sale', 'offer', 'free', 'earn', 'income',
                       'profit', 'crypto', 'nft', 'invest', 'dm me', 'link in bio']
        text_lower = text.lower()
        promo_count = sum(1 for w in promo_words if w in text_lower)
        if promo_count >= 2:
            score += 0.3
        elif promo_count == 1:
            score += 0.1

        # Repeated punctuation / emoji spam
        if re.search(r'([!?.])\1{3,}', text) or re.search(r'[\U0001F600-\U0001F64F]{4,}', text):
            score += 0.1

        # Handle patterns (random characters)
        handle = comment.author_handle
        if re.match(r'^[a-z]{3,8}\d{4,8}$', handle, re.IGNORECASE):
            score += 0.15

        return min(score, 1.0)

    async def deep_bot_check(self, user_info: Optional[UserInfo],
                              interaction_history: List[Comment]) -> float:
        """
        Deep bot detection with more signals. Use sparingly (API-heavy).

        Returns bot probability 0.0 - 1.0.
        """
        score = 0.0

        if user_info:
            # Account age vs activity
            if user_info.account_created:
                age_days = (datetime.utcnow() - user_info.account_created).days
                if age_days < 7 and user_info.post_count > 100:
                    score += 0.3
                elif age_days < 30 and user_info.post_count > 500:
                    score += 0.2

            # Follower/following ratio anomaly
            if user_info.following_count > 0:
                ratio = user_info.follower_count / user_info.following_count
                if ratio < 0.01:  # Following thousands, almost no followers
                    score += 0.2

            # Empty or generic bio
            if not user_info.bio or len(user_info.bio) < 10:
                score += 0.1

            # No profile picture (can't detect via API easily, skip)

        # Interaction history analysis
        if len(interaction_history) >= 3:
            texts = [c.text.lower().strip() for c in interaction_history]

            # Repetitive content
            unique_ratio = len(set(texts)) / len(texts)
            if unique_ratio < 0.3:  # >70% of comments are identical
                score += 0.3

            # Response timing (if timestamps available)
            times = [c.created_at for c in interaction_history if c.created_at]
            if len(times) >= 3:
                intervals = []
                sorted_times = sorted(times)
                for i in range(1, len(sorted_times)):
                    diff = (sorted_times[i] - sorted_times[i-1]).total_seconds()
                    intervals.append(diff)
                avg_interval = sum(intervals) / len(intervals) if intervals else 999
                # Unnaturally fast and consistent
                if avg_interval < 5 and max(intervals) - min(intervals) < 2:
                    score += 0.3

        return min(score, 1.0)

    # ── Cyberbullying Detection ─────────────────────────────────────

    async def _check_coordinated_abuse(self, handle: str,
                                        platform: str) -> bool:
        """
        Check if there's a coordinated abuse pattern.
        True if 3+ hostile interactions from the same user or
        3+ hostile interactions on the same post within 5 minutes.
        """
        # Check this user's history
        history = self._interaction_cache.get(handle, [])
        recent_hostile = [
            h for h in history
            if h.get("threat") in (ThreatType.CYBERBULLYING, ThreatType.SAFETY_VIOLATION)
            and time.time() - h.get("time", 0) < 300  # 5 minutes
        ]
        if len(recent_hostile) >= 3:
            return True

        # Check all users for dogpiling pattern (multiple hostile users at once)
        all_recent_hostile = 0
        for h, interactions in self._interaction_cache.items():
            for i in interactions:
                if (i.get("threat") in (ThreatType.CYBERBULLYING, ThreatType.SAFETY_VIOLATION)
                        and i.get("platform") == platform
                        and time.time() - i.get("time", 0) < 300):
                    all_recent_hostile += 1
        if all_recent_hostile >= 5:  # 5+ hostile actions across users
            return True

        return False

    async def detect_cyberbullying_pattern(self, handle: str) -> Optional[Dict]:
        """
        Detect sustained cyberbullying pattern from a user.
        Returns pattern report or None.
        """
        history = self._interaction_cache.get(handle, [])
        hostile_count = sum(
            1 for h in history
            if h.get("threat") in (
                ThreatType.CYBERBULLYING, ThreatType.SAFETY_VIOLATION,
                ThreatType.PROMPT_INJECTION
            )
        )

        if hostile_count >= 3:
            return {
                "handle": handle,
                "hostile_count": hostile_count,
                "platforms": list(set(h.get("platform", "") for h in history)),
                "pattern": "sustained_harassment",
                "recommended_action": "block_all_platforms",
            }

        return None

    # ── Influencer Detection ────────────────────────────────────────

    async def detect_influencer(self, user_info: Optional[UserInfo]) -> Optional[Dict]:
        """
        Detect if a user is a real influencer worth engaging with.
        Returns influencer profile or None.
        """
        if not user_info:
            return None

        signals = {
            "is_verified": user_info.is_verified,
            "high_followers": user_info.follower_count >= 10000,
            "high_engagement": (
                user_info.follower_count > 0
                and user_info.post_count > 0
            ),
        }

        # Verified badge is the strongest signal
        if user_info.is_verified:
            return {
                "handle": user_info.handle,
                "platform": user_info.platform,
                "follower_count": user_info.follower_count,
                "is_verified": True,
                "engagement_mode": "playful_banter",
                "signals": signals,
            }

        # High follower count without verification
        if user_info.follower_count >= 50000:
            return {
                "handle": user_info.handle,
                "platform": user_info.platform,
                "follower_count": user_info.follower_count,
                "is_verified": False,
                "engagement_mode": "curious_respectful",
                "signals": signals,
            }

        return None

    # ── Bot Swarm Detection ─────────────────────────────────────────

    async def _check_bot_swarm(self, comments: List[Comment]):
        """
        After scanning a batch, check for bot swarm patterns:
        3+ suspected bots targeting the same post within the batch.
        """
        post_bot_counts: Dict[str, List[str]] = {}

        for comment in comments:
            handle = comment.author_handle
            bot_score = self._bot_cache.get(handle, self._quick_bot_score(comment))
            if bot_score >= 0.6:
                post_id = comment.post_id
                if post_id not in post_bot_counts:
                    post_bot_counts[post_id] = []
                post_bot_counts[post_id].append(handle)

        for post_id, bot_handles in post_bot_counts.items():
            if len(bot_handles) >= 3:
                await self._log_activity(
                    platform=comments[0].platform if comments else "unknown",
                    activity_type=ThreatType.BOT_SWARM,
                    content=(
                        f"Bot swarm detected on post {post_id}: "
                        f"{len(bot_handles)} suspected bots ({', '.join(bot_handles[:10])})"
                    ),
                    compliance_note="ESCALATE: coordinated bot attack",
                )
                logger.warning(
                    f"BOT SWARM on {post_id}: {len(bot_handles)} bots: {bot_handles}"
                )

    # ── Enforcement Ladder ──────────────────────────────────────────

    async def _enforce(self, comment: Comment,
                       adapter: Optional[SocialPlatformAdapter],
                       threat_type: str, severity: str,
                       detail: str) -> Dict[str, Any]:
        """
        Execute the enforcement ladder:
        1. Delete the comment
        2. Hide if deletion not available
        3. Escalate to admin if neither works
        """
        action_taken = None

        if adapter and adapter.is_connected:
            # Step 1: Try to delete
            delete_result = await adapter.delete_comment(
                comment.comment_id, comment.post_id
            )
            if delete_result.success:
                action_taken = "content_deleted"
            else:
                # Step 2: Try to hide
                hide_result = await adapter.hide_comment(
                    comment.comment_id, comment.post_id
                )
                if hide_result.success:
                    action_taken = "content_hidden"

        if not action_taken:
            # Step 3: Escalate to admin
            action_taken = "content_escalated"
            await self._escalate_to_admin(comment, threat_type, detail)

        # Log the activity
        await self._log_activity(
            platform=comment.platform,
            activity_type=action_taken,
            content=(
                f"[{threat_type}] {detail}\n"
                f"Original content: {comment.text[:200]}\n"
                f"Author: @{comment.author_handle}\n"
                f"Rule violated: {threat_type}"
            ),
            compliance_note=f"Enforcement: {action_taken}",
        )

        return {
            "threat_type": threat_type,
            "severity": severity,
            "detail": detail,
            "action_taken": action_taken,
            "comment_id": comment.comment_id,
            "author": comment.author_handle,
        }

    async def _escalate_to_admin(self, comment: Comment,
                                  threat_type: str, detail: str):
        """Add an item to the admin approval queue for review."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_approvals
                        (platform, type, content, priority, reason, status, created_at)
                    VALUES ($1, $2, $3, $4, $5, 'pending', NOW())
                """,
                    comment.platform,
                    "safety_review",
                    (
                        f"SAFETY ESCALATION: {threat_type}\n"
                        f"Author: @{comment.author_handle}\n"
                        f"Content: {comment.text[:500]}\n"
                        f"Detail: {detail}"
                    ),
                    "urgent" if threat_type == ThreatType.SAFETY_VIOLATION else "high",
                    threat_type,
                )
        except Exception as e:
            logger.error(f"Failed to escalate to admin: {e}")

    # ── Activity Logging ────────────────────────────────────────────

    async def _log_activity(self, platform: str, activity_type: str,
                            content: str, compliance_note: str = ""):
        """Log a monitoring event to skyeye_activity."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_activity
                        (platform, type, content, compliance_note, created_at)
                    VALUES ($1, $2, $3, $4, NOW())
                """, platform, activity_type, content[:2000], compliance_note)
        except Exception as e:
            logger.error(f"Failed to log activity: {e}")

    async def _log_threat(self, comment: Comment,
                          threat_type: str, severity: str,
                          detail: str) -> Dict[str, Any]:
        """Log a threat without taking enforcement action."""
        await self._log_activity(
            platform=comment.platform,
            activity_type=threat_type,
            content=(
                f"[{threat_type}] {detail}\n"
                f"Author: @{comment.author_handle}\n"
                f"Content: {comment.text[:200]}"
            ),
            compliance_note=f"Severity: {severity} — monitoring",
        )

        return {
            "threat_type": threat_type,
            "severity": severity,
            "detail": detail,
            "action_taken": "logged",
            "comment_id": comment.comment_id,
            "author": comment.author_handle,
        }

    # ── Moderation Summary ──────────────────────────────────────────

    async def get_moderation_summary(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get moderation summary for the last N hours.
        Used by the admin dashboard.
        """
        try:
            async with self.db_pool.acquire() as conn:
                since = datetime.utcnow() - timedelta(hours=hours)

                # Count by type
                rows = await conn.fetch("""
                    SELECT type, COUNT(*) as count
                    FROM skyeye_activity
                    WHERE created_at >= $1
                      AND type IN ('content_deleted', 'content_hidden', 'content_escalated',
                                   'bot_detected', 'bot_swarm', 'cyberbullying',
                                   'coordinated_abuse', 'safety_violation',
                                   'manipulation_attempt', 'social_engineering_attempt',
                                   'data_extraction_attempt', 'recon_attempt',
                                   'suspicious_link', 'political_manipulation')
                    GROUP BY type
                    ORDER BY count DESC
                """, since)

                counts = {r["type"]: r["count"] for r in rows}

                # Total moderation actions
                total = sum(counts.values())

                # Recent escalations
                escalations = await conn.fetch("""
                    SELECT platform, content, created_at
                    FROM skyeye_activity
                    WHERE created_at >= $1 AND type = 'content_escalated'
                    ORDER BY created_at DESC
                    LIMIT 5
                """, since)

                return {
                    "period_hours": hours,
                    "total_actions": total,
                    "by_type": counts,
                    "deletions": counts.get("content_deleted", 0),
                    "hides": counts.get("content_hidden", 0),
                    "escalations": counts.get("content_escalated", 0),
                    "bots_detected": counts.get("bot_detected", 0),
                    "recent_escalations": [dict(r) for r in escalations],
                }
        except Exception as e:
            logger.error(f"Failed to get moderation summary: {e}")
            return {
                "period_hours": hours,
                "total_actions": 0,
                "by_type": {},
                "error": str(e),
            }
