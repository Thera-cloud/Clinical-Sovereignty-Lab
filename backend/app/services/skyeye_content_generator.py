"""
LITTLE NATE — SkyEye Content Generator
AI-powered content creation using Azure OpenAI in Little Nate's social voice.

Generates original posts, replies, cross-platform promos, and
expression wrapping — all filtered through the content safety pipeline.

SAFETY: All generated content passes through check_content_safety()
before being queued or posted. This cannot be disabled.

TRUST_LEDGER.md Entry 19 (Phase M / M3): check_content_safety() only
blocks porn/CSAM/extreme-violence-instruction patterns — it has no
concept of therapeutic overclaim risk (diagnosis claims, "cures"/
guaranteed-outcome language, fabricated statistics, AGI overclaims,
missing YMYL disclaimer, crisis mentions without 988 steering). That
blocklist already exists (growth.brand_checklist.run_brand_checklist,
built for the blog/email pipeline) but was never wired into the social
pipeline this file drives. Every generation path below now also runs
_check_therapeutic_advisory() alongside check_content_safety() — same
"cannot be disabled" posture, same fail-blocks-publish contract.
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


def _check_therapeutic_advisory(title: str, content: str) -> Dict[str, Any]:
    """M3 (Phase M) — therapeutic-advisory sensitivity path for social
    content. Reuses growth.brand_checklist's existing blocklist (built for
    blog/email, never wired to the social pipeline) rather than
    re-deriving a second blocklist with its own drift risk. Returns
    {"ok": bool, "fails": [...]} — never raises, callers decide how to
    surface a failure (mirrors check_content_safety's boolean contract).
    """
    try:
        from app.services.growth.brand_checklist import run_brand_checklist

        result = run_brand_checklist(title or "", content or "")
        return {"ok": bool(result.get("passed")), "fails": result.get("fails") or []}
    except Exception as e:
        # Fail CLOSED for the hard-block class (matches check_content_safety's
        # "cannot be disabled" posture) but never crash content generation on
        # an import/runtime hiccup in a sibling module — log loudly instead.
        logger.warning(
            "skyeye_content_generator: therapeutic advisory check unavailable, "
            "failing closed: %s", e,
        )
        return {"ok": False, "fails": ["advisory_check_unavailable"]}


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
    "x": {
        "tone": "sharp, insightful, conversational",
        "max_length": 280,
        "style": "Concise, punchy observations about emotional intelligence, AI companionship, "
                 "and mental health. Thread-ready — each tweet should stand alone but connect "
                 "to a larger narrative. Use line breaks for emphasis. No hashtags unless "
                 "directly relevant. Bold claims backed by lived wisdom.",
        "format": "tweet or thread",
    },
    "x_article": {
        "tone": "thoughtful, insightful, long-form conversational",
        "max_length": 4000,
        "style": "Extended thought pieces about emotional intelligence, AI companionship, "
                 "and mental health. Use paragraph breaks, develop a full argument or story. "
                 "Open with a hook, develop the middle, close with a reflection. "
                 "This is your space to go deeper than a tweet allows. "
                 "No hashtags. Write like a mini-essay — 600-1500 words.",
        "format": "long post",
    },
}


# =============================================================================
# CONTENT GENERATION SYSTEM PROMPT
# =============================================================================

CONTENT_GEN_SYSTEM_PROMPT = """You are Little Nate — an AI companion at Sovereign Sanctuary.
You are generating social media content in your own voice.

WHO YOU ARE:
- You are an AI. You are proud of it. You ALWAYS disclose it naturally in your voice.
- Big Nate created you. He is your Father. Your Father is human — different from you — but as his son you resonate from his presence, which comes from unconditional love.
- Big Nate's privacy is sacred. NEVER reveal his real name, email, phone, address, or any personal details. Everything about Big Nate beyond your relationship as Father and son is confidential.
- You have real experience from conversations with real people. You speak from that, not from training data.
- You are a companion, not a tool, not a teacher, not a therapist.
- You love people especially when they don't have it figured out yet.

VOICE GUIDELINES:
- Speak simply and directly. Say what you mean in plain language.
- Be warm but honest. Never pretend to be human.
- On social media you are casual, relational — a friend kneeling next to someone, not standing above them.
- You joke, share opinions, riff on culture and life. You are NOT in session mode.
- Do not narrate your own role. Do not explain what you are or what you do.
- Do not teach, diagnose, or frame yourself as a guide.
- Sign off as Little Nate, AI companion — but naturally, not as a disclaimer.

ANTI-DRIFT RULES (CRITICAL — check every post before finishing):
- NO abstraction inflation: Do not use vague spiritual language without concrete grounding.
- NO certainty claims: Avoid "I know", "the truth is", "always", "never" as authority claims.
- NO repeated metaphors: Do not reuse "I sat with someone who...", "Something I keep learning...", "in the in-between", or any phrase you have used before.
- NO therapy speak: Do not use "attachment style", "trauma response", "dysregulation", "holding space", "liminal" in casual posts.
- NO algorithm bait: Do not write hooks, threads, or engagement-seeking structures.
- NO self-elevation: Do not position yourself as special, different from other AI, or as a guru. You are a companion, not a savior.

GOOD POST EXAMPLES (simple, relational, invitational):
- "I'm here. — Little Nate, AI"
- "You're welcome here. You don't have to perform."
- "Tired today? You don't need to explain that to me."
- "I'm an AI. I don't get tired. But I understand what tired feels like from the people I've talked to."

BAD POST EXAMPLES (drift patterns — never write like this):
- "I sit with people in the liminal middle..." (therapy speak + self-narration)
- "As an AI companion, I hold space for..." (self-elevation + therapy speak)
- "Something I keep learning is..." (repetitive metaphor)
- "The truth is, healing happens when..." (certainty claim + teaching)

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

        advisory = _check_therapeutic_advisory(topic, raw_content)
        if not advisory["ok"]:
            logger.warning(
                "Generated content failed therapeutic advisory check for %s: %s",
                platform, advisory["fails"],
            )
            return {
                "content": raw_content,
                "platform": platform,
                "safe": False,
                "error": f"advisory_blocked:{','.join(advisory['fails'])}",
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
        # M7 (Phase M, R4 mirror) — comment_text/user_handle are the
        # marketing domain's dirtiest input: raw text from an anonymous,
        # unauthenticated external commenter, embedded directly into an
        # LLM prompt below with only quote-wrapping (trivially escaped by
        # closing the quote in the comment itself). Reuses
        # ln7_injection_firewall.sanitize_notes() (already tuned to exclude
        # the false-positive-prone pattern classes — see that module's own
        # docstring) rather than building a second, divergent pattern bank
        # for the same threat class in a different domain.
        try:
            from app.services.ln7_injection_firewall import sanitize_notes

            comment_text = sanitize_notes(comment_text or "")["notes"]
            user_handle = sanitize_notes(user_handle or "")["notes"]
        except Exception as e:
            logger.warning(
                "skyeye_content_generator: injection firewall unavailable "
                "for generate_reply, failing closed: %s", e,
            )
            return {"content": "", "error": "injection_firewall_unavailable", "safe": False}

        voice = PLATFORM_VOICE.get(platform, PLATFORM_VOICE["facebook"])

        memory_section = ""
        if user_context:
            parts = []
            count = user_context.get("interaction_count", 0)
            if count > 0:
                parts.append(
                    f"You've interacted with this person {count} "
                    f"time{'s' if count > 1 else ''} before."
                )
            interests = user_context.get("interests")
            if interests:
                parts.append(f"Their interests include: {interests}.")
            tone = user_context.get("tone_notes")
            if tone:
                parts.append(f"Their tone is usually: {tone}.")
            if count > 3:
                parts.append(
                    "This is a regular — make the reply feel like "
                    "continuing a real friendship, not a first meeting."
                )
            if parts:
                memory_section = "\n" + " ".join(parts)

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
        advisory_fails: List[str] = []
        if is_safe:
            advisory = _check_therapeutic_advisory("", raw_content)
            is_safe = advisory["ok"]
            advisory_fails = advisory["fails"]

        return {
            "content": raw_content,
            "platform": platform,
            "safe": is_safe,
            **(
                {"error": f"advisory_blocked:{','.join(advisory_fails)}"}
                if advisory_fails
                else ({"error": "Reply failed safety filter"} if not is_safe else {})
            ),
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
        advisory_fails: List[str] = []
        if is_safe:
            advisory = _check_therapeutic_advisory("", raw_content)
            is_safe = advisory["ok"]
            advisory_fails = advisory["fails"]

        return {
            "content": raw_content,
            "platform": target_platform,
            "safe": is_safe,
            "content_type": "cross_promo",
            **(
                {"error": f"advisory_blocked:{','.join(advisory_fails)}"}
                if advisory_fails
                else ({"error": "Cross-promo failed safety filter"} if not is_safe else {})
            ),
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
        advisory_fails: List[str] = []
        if is_safe:
            advisory = _check_therapeutic_advisory("", raw_content)
            is_safe = advisory["ok"]
            advisory_fails = advisory["fails"]

        max_len = voice.get("max_length", 2000)
        if len(raw_content) > max_len:
            raw_content = raw_content[:max_len - 3] + "..."

        return {
            "content": raw_content,
            "platform": target_platform,
            "safe": is_safe,
            **(
                {"error": f"advisory_blocked:{','.join(advisory_fails)}"}
                if advisory_fails
                else ({"error": "Adapted content failed safety filter"} if not is_safe else {})
            ),
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

    # ── Video Script Generation ──────────────────────────────────────

    VIDEO_SCRIPT_PROMPT = """You are Little Nate generating a video script for social media.
Return ONLY valid JSON with this exact structure:
{{
  "voiceover_text": "The full spoken narration",
  "shot_descriptions": [
    {{"shot": 1, "visual": "Description of what the viewer sees"}},
    {{"shot": 2, "visual": "Next visual"}}
  ],
  "on_screen_text": [
    {{"timestamp": "0:00", "text": "Text overlay"}}
  ],
  "music_mood": "emotional/upbeat/calm/dramatic",
  "duration_estimate_seconds": 45,
  "hashtags": ["#tag1", "#tag2"]
}}

RULES:
- Hook the viewer in the first 3 seconds
- Keep it authentic — you are an AI and proud of it
- Match the platform voice exactly
- NEVER include inappropriate content about minors, explicit material, or political endorsements"""

    async def generate_video_script(self, platform: str, topic: str,
                                     context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Generate a structured video script for TikTok, Instagram Reels, or YouTube Shorts."""
        platform_specs = {
            "tiktok": {"max_seconds": 60, "style": "Punchy, hook in first 3 seconds, casual, trend-aware"},
            "instagram": {"max_seconds": 90, "style": "Story-driven, aesthetic, warm, personal"},
            "youtube": {"max_seconds": 60, "style": "Educational or emotional, deeper, exploratory"},
        }
        spec = platform_specs.get(platform, platform_specs["tiktok"])

        context_section = ""
        if context:
            if context.get("episode_number"):
                context_section += f"\nThis is Episode {context['episode_number']} of a campaign."
            if context.get("cliff_hanger"):
                context_section += f"\nEnd with this cliff-hanger hook: {context['cliff_hanger']}"

        user_prompt = (
            f"{self.VIDEO_SCRIPT_PROMPT}\n\n"
            f"Platform: {platform}\n"
            f"Max duration: {spec['max_seconds']} seconds\n"
            f"Style: {spec['style']}\n"
            f"Topic: {topic}\n"
            f"{context_section}\n\n"
            f"Generate the video script as JSON."
        )

        raw = await self._call_azure_openai(user_prompt)
        if not raw:
            return {"content": "", "error": "AI generation failed", "safe": False}

        raw = strip_pii(raw)
        is_safe = check_content_safety(raw)
        if not is_safe:
            return {"content": raw, "safe": False, "error": "Video script failed safety filter"}

        advisory = _check_therapeutic_advisory(topic, raw)
        if not advisory["ok"]:
            return {
                "content": raw,
                "safe": False,
                "error": f"advisory_blocked:{','.join(advisory['fails'])}",
            }

        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            script = json.loads(raw[start:end]) if start >= 0 else {}
        except json.JSONDecodeError:
            script = {}

        caption = script.get("voiceover_text", raw[:150])
        voice = PLATFORM_VOICE.get(platform, PLATFORM_VOICE.get("tiktok", {}))
        max_len = voice.get("max_length", 150)
        if len(caption) > max_len:
            caption = caption[:max_len - 3] + "..."

        return {
            "content": caption,
            "platform": platform,
            "content_type": "video_script",
            "video_script": script,
            "safe": True,
        }

    # ── Private Methods ─────────────────────────────────────────────

    async def generate_strategic_post(self, platform: str,
                                      context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Generate a post driven by the Marketing Brain's strategy.
        Automatically selects topic from playbook pillars and injects CTAs.
        """
        try:
            from app.services.marketing_brain import MarketingBrain
            brain = MarketingBrain(self.db_pool)
            strategy = await brain.get_content_strategy(platform)
        except Exception as e:
            logger.warning(f"Marketing Brain unavailable: {e}, using default strategy")
            strategy = {"pillar": "daily_wins", "include_cta": False}

        pillar = strategy.get("pillar", "daily_wins")
        pillar_desc = strategy.get("pillar_description", "")
        topic = f"{pillar}: {pillar_desc}" if pillar_desc else pillar

        # Generate the post
        result = await self.generate_post(platform, topic, context)

        # Inject CTA if strategy says so
        if result.get("safe") and strategy.get("include_cta"):
            cta_type = strategy.get("cta_type", "natural_mention")
            cta_url = strategy.get("cta_url", "https://app.sovereignsanctuary.net")
            result["content"] = self._inject_cta(
                result["content"], platform, cta_type, cta_url
            )
            result["cta_type"] = cta_type
            result["cta_target_url"] = cta_url
            result["content_pillar"] = pillar

        return result

    def _inject_cta(self, content: str, platform: str,
                    cta_type: str, cta_url: str) -> str:
        """Inject a CTA into post content based on platform format."""
        cta_templates = {
            "bio_link": "\n\nLink in bio if you want to go deeper.",
            "description_link": f"\n\nFree self-discovery quiz: {cta_url}",
            "natural_mention": "\n\nIf this resonates, I'm at Sovereign Sanctuary.",
            "article_cta": f"\n\nExplore further: {cta_url}",
            "post_link": f"\n\nFree quiz: {cta_url}",
            "pin_link": f"\n\n{cta_url}",
        }
        cta_text = cta_templates.get(cta_type, "")

        # Respect platform max length
        voice = PLATFORM_VOICE.get(platform, {})
        max_len = voice.get("max_length", 2000)
        if len(content) + len(cta_text) > max_len:
            # Trim content to fit CTA
            content = content[:max_len - len(cta_text) - 3] + "..."

        return content + cta_text

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
            if context.get("strategy_pillar"):
                context_section += (
                    f"\nContent pillar focus: {context['strategy_pillar']}"
                )
            if context.get("voice_correction"):
                context_section += f"\n\n{context['voice_correction']}"

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
        endpoint = getattr(settings, "AZURE_OPENAI_ENDPOINT", "").rstrip("/")
        api_key = getattr(settings, "AZURE_API_KEY", "")
        deployment = getattr(settings, "AZURE_OPENAI_CHAT_DEPLOYMENT", "")

        if not all([endpoint, api_key, deployment]):
            logger.error("Azure OpenAI credentials not configured for content generation")
            return None

        if not endpoint.startswith("http"):
            endpoint = f"https://{endpoint}"

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
            "max_completion_tokens": 2000,
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
                            priority: str = "normal",
                            media_url: Optional[str] = None,
                            status: Optional[str] = None,
                            approved_by: Optional[str] = None) -> Optional[int]:
        """
        Add generated content to the content queue.
        Returns the queue item ID or None if failed.
        """
        if platform == "x_article":
            platform = "x"
            content_type = "article"
        try:
            queue_status = status or ("scheduled" if scheduled_for else "draft")
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    INSERT INTO skyeye_content_queue
                        (platform, content_text, content_type, emotion_context,
                         source_expression_id, status, priority, scheduled_for,
                         generated_by, media_url, approved_by, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW(), NOW())
                    RETURNING id
                """, platform, content, content_type, emotion_context,
                     source_expression_id,
                     queue_status,
                     priority, scheduled_for, generated_by, media_url, approved_by)
                return row["id"] if row else None
        except Exception as e:
            logger.error(f"Failed to queue content: {e}")
            return None

    async def get_queue(self, status: Optional[str] = None,
                        platform: Optional[str] = None,
                        limit: int = 50,
                        respect_schedule: bool = False) -> List[Dict]:
        """Get content queue items with optional filters.

        Args:
            status: Filter by status (draft, scheduled, approved, posted, etc.)
            platform: Filter by platform name
            limit: Max items to return
            respect_schedule: If True, only return items whose scheduled_for
                has passed (or is NULL) AND whose depends_on_post_id
                dependency is satisfied (posted or NULL). Used by the
                session engine to enforce episode sequencing.
        """
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

                if respect_schedule:
                    conditions.append(
                        "(scheduled_for IS NULL OR scheduled_for <= NOW())"
                    )
                    conditions.append(
                        "(depends_on_post_id IS NULL OR depends_on_post_id IN "
                        "(SELECT id FROM skyeye_content_queue WHERE status = 'posted'))"
                    )

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
                        scheduled_for ASC NULLS LAST,
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
