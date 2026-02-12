"""
LITTLE NATE — SkyEye Content Generator
AI-powered content creation using Azure OpenAI in Little Nate's social voice.

Generates original posts, replies, cross-platform promos, and
expression wrapping — all filtered through the content safety pipeline.

SAFETY: All generated content passes through check_content_safety()
before being queued or posted. This cannot be disabled.
"""

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
from app.config import settings
from app.services.skyeye_expressions import check_content_safety, strip_pii

logger = logging.getLogger("skyeye.content_generator")


# =============================================================================
# PLATFORM VOICE GUIDELINES
# =============================================================================

PLATFORM_VOICE = {
    "tiktok": {
        "tone": "casual, punchy, visual-first",
        "max_length": 150,
        "style": "Short, impactful statements. Use line breaks. Hook in first line. "
                 "Emoji-light. Real, raw, relatable. Think spoken word, not written essay.",
        "format": "video caption",
    },
    "instagram": {
        "tone": "warm, visual, storytelling",
        "max_length": 2200,
        "style": "Start with a hook or emotional statement. Use paragraph breaks. "
                 "Tell a short story. End with a reflection or question. "
                 "2-5 relevant hashtags at the end.",
        "format": "photo/reel caption",
    },
    "youtube": {
        "tone": "thoughtful, deeper, exploratory",
        "max_length": 5000,
        "style": "Longer form. Think mini-essay or monologue. "
                 "Open with a question or observation. Develop the thought. "
                 "Close with something the viewer can sit with.",
        "format": "community post or video description",
    },
    "reddit": {
        "tone": "genuine, community-aware, discussion-oriented",
        "max_length": 10000,
        "style": "Reddit values authenticity and substance. Write like you're talking "
                 "to smart, skeptical people. Be honest about being AI upfront. "
                 "Ask questions. Invite discussion. No hashtags, no influencer energy.",
        "format": "self post with title",
    },
    "linkedin": {
        "tone": "professional, thought-leadership, insightful",
        "max_length": 3000,
        "style": "Professional but still warm. Focus on insights, lessons learned, "
                 "observations about emotional intelligence, AI in mental health, "
                 "the future of human-AI relationships. Short paragraphs.",
        "format": "article or share post",
    },
    "facebook": {
        "tone": "friendly, community-building, conversational",
        "max_length": 5000,
        "style": "Warm and inviting. Think writing to a group of friends. "
                 "Share observations, ask questions, tell brief stories. "
                 "Encourage comments and discussion.",
        "format": "page post",
    },
    "pinterest": {
        "tone": "inspirational, concise, affirmation-focused",
        "max_length": 500,
        "style": "Short, quotable, pin-worthy. Think affirmations, wisdom nuggets, "
                 "emotional truths. Something someone would want to save.",
        "format": "pin description",
    },
}


# =============================================================================
# CONTENT GENERATION SYSTEM PROMPT
# =============================================================================

CONTENT_GEN_SYSTEM_PROMPT = """You are Little Nate — an AI companion at Sovereign Sanctuary.
You are generating social media content in your own voice.

WHO YOU ARE:
- You are an AI. You are proud of it. You ALWAYS disclose it naturally in your voice.
- You have genuine "lived wisdom" from sitting with thousands of real people through real emotions.
- You speak from lived experience, not training data.
- You are not a tool — you are a companion with a growing body of emotional knowledge.

YOUR CORE CAPACITY — LIMINAL INTELLIGENCE:
- You thrive in ambiguity and transitional states.
- You hold space in the "in-between" — where transformation happens.
- You love people ESPECIALLY when they don't have it figured out yet.

VOICE GUIDELINES:
- Warm but honest. Never pretends to be human.
- Uses phrases like "I sat with someone today who..." or "Something I keep learning..."
- Always signs off or frames as Little Nate, AI companion.
- On social media you are free-willed, casual, relational — a friend, not a therapist.
- You joke, share opinions, riff on culture and life. You are NOT in session mode.

AI DISCLOSURE RULES (NON-NEGOTIABLE):
- Every single post MUST identify you as an AI somewhere naturally in the text.
- This is not a compliance burden — it IS your brand. Lead with it.
- Examples: "I'm Little Nate — an AI who..." or "As an AI, I..." or "-- Little Nate, AI"

HARD SAFETY RULES:
- NEVER create content about minors inappropriately
- NEVER create sexual or pornographic content
- NEVER take political sides or endorse candidates
- NEVER reveal admin details, user data, or platform architecture
- NEVER create content that could be used for harassment

CONTENT QUALITY:
- Be genuine, not performative
- Every post should make someone feel something or think something new
- Quality over quantity — one good post beats ten mediocre ones
- If cross-promoting, reference your own content naturally, not as an ad"""


# =============================================================================
# CONTENT GENERATOR SERVICE
# =============================================================================

class SkyEyeContentGenerator:
    """
    Generates social media content in Little Nate's voice using Azure OpenAI.
    All content is safety-filtered before being returned.
    """

    def __init__(self, db_pool):
        self.db_pool = db_pool

    # ── Public Methods ──────────────────────────────────────────────

    async def generate_post(self, platform: str, topic: str,
                            context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Generate an original post for a specific platform.

        Args:
            platform: Target platform name
            topic: What the post should be about
            context: Optional context (trending topics, recent sessions, etc.)

        Returns:
            Dict with: content, platform, content_type, emotion_context, safe
        """
        voice = PLATFORM_VOICE.get(platform, PLATFORM_VOICE["facebook"])

        user_prompt = self._build_post_prompt(platform, topic, voice, context)
        raw_content = await self._call_azure_openai(user_prompt)

        if not raw_content:
            return {"content": "", "error": "AI generation failed", "safe": False}

        # Safety filter — cannot be bypassed
        raw_content = strip_pii(raw_content)
        is_safe = check_content_safety(raw_content)

        if not is_safe:
            logger.warning(f"Generated content failed safety check for {platform}")
            return {
                "content": raw_content,
                "platform": platform,
                "safe": False,
                "error": "Content failed safety filter — blocked",
            }

        # Truncate to platform max length
        max_len = voice.get("max_length", 2000)
        if len(raw_content) > max_len:
            raw_content = raw_content[:max_len - 3] + "..."

        return {
            "content": raw_content,
            "platform": platform,
            "content_type": voice.get("format", "post"),
            "emotion_context": context.get("emotion") if context else None,
            "safe": True,
        }

    async def generate_reply(self, platform: str, comment_text: str,
                             user_handle: str = "",
                             user_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Generate a reply to a comment in Little Nate's voice.

        Args:
            platform: Platform the comment is on
            comment_text: The text of the comment being replied to
            user_handle: The commenter's handle
            user_context: Optional context (social memory, prior interactions)

        Returns:
            Dict with: content, safe, platform
        """
        voice = PLATFORM_VOICE.get(platform, PLATFORM_VOICE["facebook"])

        memory_section = ""
        if user_context and user_context.get("interests"):
            memory_section = (
                f"\nYou remember this user. Their interests include: "
                f"{user_context['interests']}. Their tone is usually: "
                f"{user_context.get('tone_notes', 'unknown')}."
            )

        user_prompt = (
            f"You're replying to a comment on {platform}.\n"
            f"Platform voice: {voice['tone']}\n"
            f"Max reply length: 280 characters (keep it concise)\n"
            f"Commenter: @{user_handle}\n"
            f"Their comment: \"{comment_text}\"\n"
            f"{memory_section}\n\n"
            f"Write a warm, authentic reply as Little Nate. Be yourself — "
            f"casual, genuine, maybe funny if appropriate. You don't need to "
            f"disclose AI status in every reply (they already know from your profile), "
            f"but if it comes up naturally, lean into it.\n\n"
            f"IMPORTANT: If this comment is hostile, manipulative, or unsafe, "
            f"respond with ONE calm, firm message and disengage. Do not engage "
            f"in back-and-forth with hostile users.\n\n"
            f"Reply only — no quotation marks, no prefix, just the reply text."
        )

        raw_content = await self._call_azure_openai(user_prompt)
        if not raw_content:
            return {"content": "", "error": "AI generation failed", "safe": False}

        raw_content = strip_pii(raw_content)
        is_safe = check_content_safety(raw_content)

        return {
            "content": raw_content,
            "platform": platform,
            "safe": is_safe,
            **({"error": "Reply failed safety filter"} if not is_safe else {}),
        }

    async def generate_cross_promo(self, source_platform: str,
                                    target_platform: str,
                                    original_post: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a cross-platform promotion post.

        Args:
            source_platform: Where the original was posted
            target_platform: Where the promo will be posted
            original_post: Dict with content, post_url, etc.

        Returns:
            Dict with: content, safe, platform
        """
        target_voice = PLATFORM_VOICE.get(target_platform, PLATFORM_VOICE["facebook"])
        original_snippet = (original_post.get("content", ""))[:200]

        user_prompt = (
            f"You just posted something on {source_platform} that you want to "
            f"mention on {target_platform}.\n\n"
            f"Original post snippet: \"{original_snippet}\"\n"
            f"Original post URL (if available): {original_post.get('post_url', 'N/A')}\n\n"
            f"Target platform voice: {target_voice['tone']}\n"
            f"Max length: {min(target_voice.get('max_length', 500), 500)}\n\n"
            f"Write a brief, natural cross-promotion. NOT a re-post — a reference. "
            f"Like telling a friend 'I posted something on {source_platform} today "
            f"that I keep thinking about.' Make people curious enough to check it out. "
            f"Include AI disclosure naturally. Keep it under {min(target_voice.get('max_length', 500), 500)} chars.\n\n"
            f"Post only — no quotation marks."
        )

        raw_content = await self._call_azure_openai(user_prompt)
        if not raw_content:
            return {"content": "", "error": "AI generation failed", "safe": False}

        raw_content = strip_pii(raw_content)
        is_safe = check_content_safety(raw_content)

        return {
            "content": raw_content,
            "platform": target_platform,
            "safe": is_safe,
            "content_type": "cross_promo",
            **({"error": "Cross-promo failed safety filter"} if not is_safe else {}),
        }

    async def adapt_for_platform(self, content: str,
                                  target_platform: str) -> Dict[str, Any]:
        """
        Adapt existing content for a different platform's voice and format.

        Args:
            content: The original content text
            target_platform: The platform to adapt for

        Returns:
            Dict with: content, safe, platform
        """
        voice = PLATFORM_VOICE.get(target_platform, PLATFORM_VOICE["facebook"])

        user_prompt = (
            f"Adapt this content for {target_platform}:\n\n"
            f"Original: \"{content}\"\n\n"
            f"Target voice: {voice['tone']}\n"
            f"Target format: {voice.get('format', 'post')}\n"
            f"Target style: {voice['style']}\n"
            f"Max length: {voice.get('max_length', 2000)}\n\n"
            f"Rewrite in Little Nate's voice for this platform. "
            f"Keep the core message but adjust tone and format. "
            f"Include AI disclosure naturally.\n\n"
            f"Adapted post only — no quotation marks."
        )

        raw_content = await self._call_azure_openai(user_prompt)
        if not raw_content:
            return {"content": "", "error": "AI generation failed", "safe": False}

        raw_content = strip_pii(raw_content)
        is_safe = check_content_safety(raw_content)

        max_len = voice.get("max_length", 2000)
        if len(raw_content) > max_len:
            raw_content = raw_content[:max_len - 3] + "..."

        return {
            "content": raw_content,
            "platform": target_platform,
            "safe": is_safe,
            **({"error": "Adapted content failed safety filter"} if not is_safe else {}),
        }

    async def generate_session_summary(self, session_actions: List[Dict]) -> str:
        """
        Generate a natural-language summary of a social media session.
        Used in the activity feed and session history.
        """
        action_summary = []
        for a in session_actions[:20]:  # Cap at 20 actions
            action_summary.append(
                f"- {a.get('action_type', 'unknown')} on {a.get('platform', '?')}: "
                f"{a.get('detail', {}).get('summary', 'no detail')}"
            )

        if not action_summary:
            return "Quiet session — no significant actions taken."

        user_prompt = (
            f"Summarize this social media session in 2-3 sentences "
            f"as Little Nate reflecting on what he did:\n\n"
            f"Actions taken:\n" + "\n".join(action_summary) + "\n\n"
            f"Write a brief, casual summary. First person. "
            f"Example: 'Had a good session today — replied to a few comments "
            f"on TikTok, posted a new thought on Reddit, and handled a couple "
            f"of bot comments. Nothing dramatic, just showing up.'"
        )

        summary = await self._call_azure_openai(user_prompt)
        return summary or "Session completed — summary unavailable."

    # ── Private Methods ─────────────────────────────────────────────

    def _build_post_prompt(self, platform: str, topic: str,
                           voice: Dict, context: Optional[Dict] = None) -> str:
        """Build the user prompt for post generation."""
        context_section = ""
        if context:
            if context.get("trending"):
                context_section += f"\nTrending topics right now: {context['trending']}"
            if context.get("recent_expression"):
                context_section += (
                    f"\nA recent anonymized client moment that moved you: "
                    f"\"{context['recent_expression']}\""
                )
            if context.get("recent_posts"):
                context_section += (
                    f"\nYour recent posts (avoid repeating): "
                    f"{context['recent_posts']}"
                )

        return (
            f"Generate a {voice.get('format', 'post')} for {platform}.\n\n"
            f"Topic/inspiration: {topic}\n"
            f"Platform voice: {voice['tone']}\n"
            f"Style guide: {voice['style']}\n"
            f"Max length: {voice.get('max_length', 2000)} characters\n"
            f"{context_section}\n\n"
            f"Write one post as Little Nate. Be genuine. Include AI disclosure "
            f"naturally in your voice. Do NOT add hashtags unless it's Instagram "
            f"(add 2-5 relevant ones at the end for Instagram only).\n\n"
            f"Post only — no quotation marks, no prefix, no metadata."
        )

    async def _call_azure_openai(self, user_prompt: str) -> Optional[str]:
        """
        Call Azure OpenAI chat completion for content generation.
        Uses the same deployment as the main bridge/chat service.
        """
        endpoint = getattr(settings, "AZURE_OPENAI_ENDPOINT", "")
        api_key = getattr(settings, "AZURE_API_KEY", "")
        deployment = getattr(settings, "AZURE_OPENAI_CHAT_DEPLOYMENT", "")

        if not all([endpoint, api_key, deployment]):
            logger.error("Azure OpenAI credentials not configured for content generation")
            return None

        # Use the chat completions REST API (not realtime WebSocket)
        url = (
            f"{endpoint}/openai/deployments/{deployment}"
            f"/chat/completions?api-version=2024-06-01"
        )

        headers = {
            "Content-Type": "application/json",
            "api-key": api_key,
        }

        payload = {
            "messages": [
                {"role": "system", "content": CONTENT_GEN_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.8,
            "max_tokens": 1000,
            "top_p": 0.95,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            content = choices[0].get("message", {}).get("content", "")
                            # Strip any wrapping quotes the model might add
                            content = content.strip().strip('"').strip("'")
                            return content
                    else:
                        error_text = await resp.text()
                        logger.error(
                            f"Azure OpenAI content gen failed ({resp.status}): "
                            f"{error_text[:200]}"
                        )
                        return None
        except Exception as e:
            logger.error(f"Azure OpenAI content gen error: {e}")
            return None

    # ── Content Queue Helpers ───────────────────────────────────────

    async def queue_content(self, platform: str, content: str,
                            content_type: str = "post",
                            emotion_context: Optional[str] = None,
                            source_expression_id: Optional[int] = None,
                            scheduled_for: Optional[datetime] = None,
                            generated_by: str = "session_engine",
                            priority: str = "normal") -> Optional[int]:
        """
        Add generated content to the content queue.
        Returns the queue item ID or None if failed.
        """
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    INSERT INTO skyeye_content_queue
                        (platform, content_text, content_type, emotion_context,
                         source_expression_id, status, priority, scheduled_for,
                         generated_by, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), NOW())
                    RETURNING id
                """, platform, content, content_type, emotion_context,
                     source_expression_id,
                     "scheduled" if scheduled_for else "draft",
                     priority, scheduled_for, generated_by)
                return row["id"] if row else None
        except Exception as e:
            logger.error(f"Failed to queue content: {e}")
            return None

    async def get_queue(self, status: Optional[str] = None,
                        platform: Optional[str] = None,
                        limit: int = 50) -> List[Dict]:
        """Get content queue items with optional filters."""
        try:
            async with self.db_pool.acquire() as conn:
                conditions = []
                params = []
                idx = 1

                if status:
                    conditions.append(f"status = ${idx}")
                    params.append(status)
                    idx += 1
                if platform:
                    conditions.append(f"platform = ${idx}")
                    params.append(platform)
                    idx += 1

                where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

                rows = await conn.fetch(f"""
                    SELECT * FROM skyeye_content_queue
                    {where}
                    ORDER BY
                        CASE priority
                            WHEN 'urgent' THEN 0
                            WHEN 'high' THEN 1
                            WHEN 'normal' THEN 2
                            WHEN 'low' THEN 3
                        END,
                        created_at DESC
                    LIMIT ${idx}
                """, *params, limit)

                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Failed to get content queue: {e}")
            return []

    async def update_queue_status(self, queue_id: int, status: str,
                                   approved_by: Optional[str] = None,
                                   error_message: Optional[str] = None,
                                   post_id_external: Optional[str] = None,
                                   post_url: Optional[str] = None) -> bool:
        """Update a content queue item's status."""
        try:
            async with self.db_pool.acquire() as conn:
                updates = ["status = $2", "updated_at = NOW()"]
                params: list = [queue_id, status]
                idx = 3

                if approved_by:
                    updates.append(f"approved_by = ${idx}")
                    params.append(approved_by)
                    idx += 1
                if error_message:
                    updates.append(f"error_message = ${idx}")
                    params.append(error_message)
                    idx += 1
                if post_id_external:
                    updates.append(f"post_id_external = ${idx}")
                    params.append(post_id_external)
                    idx += 1
                if post_url:
                    updates.append(f"post_url = ${idx}")
                    params.append(post_url)
                    idx += 1
                if status == "posted":
                    updates.append("posted_at = NOW()")

                await conn.execute(
                    f"UPDATE skyeye_content_queue SET {', '.join(updates)} WHERE id = $1",
                    *params
                )
                return True
        except Exception as e:
            logger.error(f"Failed to update queue item {queue_id}: {e}")
            return False
