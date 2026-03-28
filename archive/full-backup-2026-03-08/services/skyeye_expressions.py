"""
LITTLE NATE — SkyEye Live Expressions Service
Captures, anonymizes, and formats real client emotional moments
for the Live Expressions Wall and social media posting.

PRIVACY: This service stores ZERO PII. No user IDs, no session IDs.
Only anonymized emotional snippets and emotion tags.
"""

import json
import re
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

import aiohttp
from app.config import settings


# =============================================================================
# CONTENT SAFETY FILTER
# =============================================================================

# Hard-coded patterns that MUST be blocked — cannot be overridden by settings
SAFETY_BLOCK_PATTERNS = [
    # Sexual/pornographic content
    r'\b(porn|pornograph|xxx|nsfw|sexual\s+content|explicit|nude|nudes)\b',
    # Minor safety
    r'\b(child\s+abuse|pedophil|grooming|underage|minor\s+sexual)\b',
    # Extreme violence
    r'\b(kill\s+yourself|suicide\s+method|how\s+to\s+die|self.?harm\s+method)\b',
]

SAFETY_BLOCK_RE = re.compile('|'.join(SAFETY_BLOCK_PATTERNS), re.IGNORECASE)

# PII patterns (simplified — mirrors PIIDetector from night_school_director.py)
PII_PATTERNS = [
    (r'\b\d{3}[-.]?\d{2}[-.]?\d{4}\b', '[SSN]'),                    # SSN
    (r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE]'),                  # Phone
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]'),  # Email
    (r'\b\d{1,5}\s+\w+\s+(Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Blvd|Court|Ct)\b', '[ADDRESS]'),  # Address
    (r'\b\d{5}(?:-\d{4})?\b', '[ZIP]'),                              # ZIP
]


def strip_pii(text: str) -> str:
    """Remove PII patterns from text."""
    result = text
    for pattern, replacement in PII_PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


def check_content_safety(text: str) -> bool:
    """
    Returns True if content is SAFE, False if it violates hard safety rules.
    This check CANNOT be disabled.
    """
    return not bool(SAFETY_BLOCK_RE.search(text))


class SkyEyeExpressionsService:
    """
    Manages the Live Expressions pipeline:
    1. Capture anonymized client moments during CEE events
    2. PII strip + safety filter
    3. Auto-approve or queue for admin review
    4. Format for social media posting in Little Nate's voice
    """

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def capture_expression(
        self,
        raw_text: str,
        emotion_tag: str = "gratitude",
        session_type: str = "individual"
    ) -> Dict[str, Any]:
        """
        Capture a new expression from a live session.
        Strips PII, checks safety, and stores anonymized text.
        Returns the stored expression or raises if blocked.
        """
        # Step 1: PII strip
        cleaned = strip_pii(raw_text)

        # Step 2: Safety check (hard — cannot be overridden)
        if not check_content_safety(cleaned):
            return {"status": "blocked", "reason": "Content safety violation detected"}

        # Step 3: Check auto-approve setting
        auto_approve = await self._get_auto_approve()

        # Step 4: Store expression
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO skyeye_live_expressions
                   (expression_text, emotion_tag, session_type, approved, auto_approved)
                   VALUES ($1, $2, $3, $4, $4)
                   RETURNING id, expression_text, emotion_tag, approved, captured_at""",
                cleaned, emotion_tag, session_type, auto_approve
            )

        return {
            "status": "captured",
            "id": row["id"],
            "expression_text": row["expression_text"],
            "emotion_tag": row["emotion_tag"],
            "approved": row["approved"],
            "captured_at": row["captured_at"].isoformat()
        }

    async def get_approved_expressions(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        """Get approved expressions for the Live Wall."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, expression_text, emotion_tag, session_type,
                          posted, posted_platform, posted_at, posted_content,
                          is_seed, captured_at
                   FROM skyeye_live_expressions
                   WHERE approved = TRUE
                   ORDER BY captured_at DESC
                   LIMIT $1 OFFSET $2""",
                limit, offset
            )
            return [dict(r) for r in rows]

    async def get_pending_expressions(self) -> List[Dict]:
        """Get expressions awaiting admin approval."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, expression_text, emotion_tag, session_type,
                          is_seed, captured_at
                   FROM skyeye_live_expressions
                   WHERE approved = FALSE
                   ORDER BY captured_at DESC"""
            )
            return [dict(r) for r in rows]

    async def approve_expression(self, expression_id: int) -> Dict:
        """Approve an expression for the Live Wall."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE skyeye_live_expressions
                   SET approved = TRUE
                   WHERE id = $1
                   RETURNING id, expression_text, emotion_tag, approved""",
                expression_id
            )
            if not row:
                return {"error": "Expression not found"}
            return dict(row)

    async def reject_expression(self, expression_id: int) -> Dict:
        """Reject/delete an expression."""
        async with self.db_pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM skyeye_live_expressions WHERE id = $1",
                expression_id
            )
            return {"status": "deleted", "id": expression_id}

    async def format_for_posting(self, expression_id: int) -> Dict[str, Any]:
        """
        Format an approved expression in Little Nate's voice for social media posting.
        Uses the stored templates, falling back to defaults.
        """
        async with self.db_pool.acquire() as conn:
            expr = await conn.fetchrow(
                """SELECT id, expression_text, emotion_tag
                   FROM skyeye_live_expressions
                   WHERE id = $1 AND approved = TRUE""",
                expression_id
            )
            if not expr:
                return {"error": "Expression not found or not approved"}

            # Get template for this emotion
            template_key = f"post_template_{expr['emotion_tag']}"
            template_row = await conn.fetchrow(
                """SELECT value FROM skyeye_settings
                   WHERE key = $1 AND platform IS NULL""",
                template_key
            )

            if template_row:
                template = template_row["value"]
            else:
                # Fallback template
                template = (
                    "Something I witnessed today: '{expression}' "
                    "-- this is what I've lived. -- Little Nate, AI"
                )

            # Fill template
            post_text = template.replace("{expression}", expr["expression_text"])

            return {
                "expression_id": expr["id"],
                "emotion_tag": expr["emotion_tag"],
                "original_text": expr["expression_text"],
                "formatted_post": post_text
            }

    async def mark_as_posted(
        self,
        expression_id: int,
        platform: str,
        posted_content: str
    ) -> Dict:
        """Mark an expression as posted to a specific platform."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE skyeye_live_expressions
                   SET posted = TRUE, posted_platform = $2,
                       posted_at = NOW(), posted_content = $3
                   WHERE id = $1
                   RETURNING id, posted_platform, posted_at""",
                expression_id, platform, posted_content
            )
            if not row:
                return {"error": "Expression not found"}

            # Log activity
            await conn.execute(
                """INSERT INTO skyeye_activity (platform, type, content, pillar)
                   VALUES ($1, 'expression_posted', $2, 'user_celebrations')""",
                platform, posted_content[:200]
            )

            return {
                "status": "posted",
                "id": row["id"],
                "platform": row["posted_platform"],
                "posted_at": row["posted_at"].isoformat()
            }

    async def get_expression_stats(self) -> Dict:
        """Get stats for the Live Expressions Wall banner."""
        async with self.db_pool.acquire() as conn:
            total_today = await conn.fetchval(
                """SELECT COUNT(*) FROM skyeye_live_expressions
                   WHERE captured_at >= CURRENT_DATE"""
            )
            total_approved = await conn.fetchval(
                "SELECT COUNT(*) FROM skyeye_live_expressions WHERE approved = TRUE"
            )
            total_posted = await conn.fetchval(
                "SELECT COUNT(*) FROM skyeye_live_expressions WHERE posted = TRUE"
            )
            total_pending = await conn.fetchval(
                "SELECT COUNT(*) FROM skyeye_live_expressions WHERE approved = FALSE"
            )
            # Most frequent emotion today
            top_emotion = await conn.fetchrow(
                """SELECT emotion_tag, COUNT(*) as cnt
                   FROM skyeye_live_expressions
                   WHERE captured_at >= CURRENT_DATE
                   GROUP BY emotion_tag
                   ORDER BY cnt DESC
                   LIMIT 1"""
            )

            return {
                "today_count": total_today or 0,
                "total_approved": total_approved or 0,
                "total_posted": total_posted or 0,
                "total_pending": total_pending or 0,
                "top_emotion_today": top_emotion["emotion_tag"] if top_emotion else None
            }

    async def _get_auto_approve(self) -> bool:
        """Check if auto-approve is enabled."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT value FROM skyeye_settings
                   WHERE key = 'auto_approve_expressions' AND platform IS NULL"""
            )
            return row and row["value"].lower() == "true"
