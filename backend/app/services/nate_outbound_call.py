"""
Little Nate — Outbound Call Orchestrator

Prepares personalized check-in call context by pulling conversation
history, profile data, and recent themes. Builds the system prompt
for Nate-initiated calls and handles SMS/email fallback when the
call goes unanswered.

Used by:
  - POST /api/calls/nate-checkin (admin-triggered check-in call)
  - NateCheckInAgent (future: automated voice check-in)
"""

import json
import logging
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import aiohttp

from app.services.nate_ai_config import (
    NATE_CHAT_URL,
    NATE_CHAT_KEY,
    nate_chat_headers,
    nate_chat_payload,
)

_logger = logging.getLogger("nate.outbound_call")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")


@dataclass
class CheckinContext:
    """Everything Nate needs to hold a personalized call."""
    username: str
    name: str
    phone: str
    reason: str = "routine_checkin"
    opening_line: str = ""
    rapport_topics: List[str] = field(default_factory=list)
    recent_themes: List[str] = field(default_factory=list)
    last_conversation_summary: str = ""
    last_activity_at: str = ""
    days_inactive: int = 0
    coherence_history: str = ""
    system_prompt: str = ""
    email: str = ""


async def prepare_checkin_context(
    username: str,
    phone: str,
    db_pool,
    reason: str = "routine_checkin",
) -> CheckinContext:
    """
    Build a full personalized context for a check-in call.

    Queries conversation_history, profile_data, and nate_checkins
    to craft an opening and rapport topics from real history.
    """
    ctx = CheckinContext(username=username, phone=phone, reason=reason, name=username)

    async with db_pool.acquire() as conn:
        # Profile — search by exact username first, then by name or phone
        user_row = await conn.fetchrow("""
            SELECT username, profile_data, hardware_id, role
            FROM users
            WHERE username = $1
            ORDER BY CASE role WHEN 'CLIENT' THEN 1 WHEN 'COACH' THEN 2 ELSE 3 END
            LIMIT 1
        """, username)

        if not user_row:
            user_row = await conn.fetchrow("""
                SELECT username, profile_data, hardware_id, role
                FROM users
                WHERE LOWER(profile_data->>'name') = LOWER($1)
                   OR profile_data->>'phone' = $2
                ORDER BY CASE role WHEN 'CLIENT' THEN 1 WHEN 'COACH' THEN 2 ELSE 3 END
                LIMIT 1
            """, username, phone)

        if not user_row:
            _logger.warning("prepare_checkin_context: user %s not found", username)
            ctx.system_prompt = build_checkin_system_prompt(ctx)
            return ctx

        ctx.username = user_row["username"]

        profile = user_row["profile_data"] or {}
        if isinstance(profile, str):
            try:
                profile = json.loads(profile)
            except Exception:
                profile = {}

        ctx.name = profile.get("name") or username
        ctx.email = profile.get("email", "")
        ctx.recent_themes = profile.get("recent_themes", [])[:5]

        last_activity = profile.get("last_activity_at") or profile.get("last_login", "")
        ctx.last_activity_at = last_activity
        if last_activity:
            try:
                last_dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                ctx.days_inactive = (datetime.now(timezone.utc) - last_dt).days
            except (ValueError, AttributeError):
                pass

        # Conversation history (last 10 entries)
        history_rows = await conn.fetch("""
            SELECT user_text, ai_text, created_at
            FROM conversation_history
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT 10
        """, ctx.username)

        conversation_snippets = []
        for row in reversed(history_rows):
            user_text = (row["user_text"] or "")[:150]
            ai_text = (row["ai_text"] or "")[:150]
            if user_text:
                conversation_snippets.append(f"Them: {user_text}")
            if ai_text:
                conversation_snippets.append(f"Nate: {ai_text}")

        if conversation_snippets:
            ctx.last_conversation_summary = "\n".join(conversation_snippets[-12:])

        # Last check-in record
        last_checkin = await conn.fetchrow("""
            SELECT content, created_at, channel
            FROM nate_checkins
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT 1
        """, ctx.username)

        if last_checkin:
            checkin_date = last_checkin["created_at"]
            if checkin_date:
                days_since_checkin = (datetime.now(timezone.utc) - checkin_date.replace(tzinfo=timezone.utc)).days
                if days_since_checkin > 0:
                    ctx.rapport_topics.append(
                        f"Last check-in was {days_since_checkin} days ago via {last_checkin.get('channel', 'unknown')}"
                    )

    # Build rapport topics from conversation history using AI
    ctx.rapport_topics.extend(await _extract_rapport_topics(ctx))

    # Generate personalized opening
    ctx.opening_line = await _generate_opening(ctx)

    # Build full system prompt
    ctx.system_prompt = build_checkin_system_prompt(ctx)

    return ctx


async def _extract_rapport_topics(ctx: CheckinContext) -> List[str]:
    """Use AI to extract rapport-worthy topics from conversation history."""
    if not ctx.last_conversation_summary or not NATE_CHAT_KEY:
        return _fallback_rapport_topics(ctx)

    messages = [
        {
            "role": "system",
            "content": (
                "Extract 3 brief rapport topics from the conversation history below. "
                "These should be things Little Nate can naturally bring up in a check-in "
                "call to show he remembers and cares. Each topic should be 1 sentence max. "
                "Focus on personal interests, goals, struggles, or wins — not clinical details. "
                "Return only the 3 topics, one per line, no numbering."
            ),
        },
        {
            "role": "user",
            "content": f"Person's name: {ctx.name}\n\nConversation history:\n{ctx.last_conversation_summary}",
        },
    ]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                NATE_CHAT_URL,
                json=nate_chat_payload(messages, max_tokens=200, user_id=ctx.username),
                headers=nate_chat_headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "")
                        return [line.strip() for line in content.strip().split("\n") if line.strip()][:3]
    except Exception as e:
        _logger.warning("Rapport topic extraction failed: %s", e)

    return _fallback_rapport_topics(ctx)


def _fallback_rapport_topics(ctx: CheckinContext) -> List[str]:
    """Fallback topics when AI extraction isn't available."""
    topics = []
    if ctx.recent_themes:
        topics.append(f"They've been working on: {ctx.recent_themes[0]}")
    if ctx.days_inactive > 5:
        topics.append(f"It's been {ctx.days_inactive} days since they were last active")
    if not topics:
        topics.append("Ask about how their week has been")
    return topics


async def _generate_opening(ctx: CheckinContext) -> str:
    """Generate a personalized opening line for the call."""
    if not NATE_CHAT_KEY or not ctx.last_conversation_summary:
        return _fallback_opening(ctx)

    messages = [
        {
            "role": "system",
            "content": (
                "You are Little Nate. Generate a single warm, natural opening line for a "
                "phone check-in call with this person. Use their first name. Reference "
                "something specific from your recent conversations to show you remember. "
                "Keep it under 30 words. Sound like a real person calling a friend, not a bot. "
                "Just output the opening line, nothing else."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Person's name: {ctx.name}\n"
                f"Days since last activity: {ctx.days_inactive}\n"
                f"Recent themes: {', '.join(ctx.recent_themes[:3]) if ctx.recent_themes else 'none'}\n\n"
                f"Recent conversation:\n{ctx.last_conversation_summary[-500:]}"
            ),
        },
    ]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                NATE_CHAT_URL,
                json=nate_chat_payload(messages, max_tokens=100, user_id=ctx.username),
                headers=nate_chat_headers(),
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "").strip().strip('"')
    except Exception as e:
        _logger.warning("Opening line generation failed: %s", e)

    return _fallback_opening(ctx)


def _fallback_opening(ctx: CheckinContext) -> str:
    """Fallback opening lines when AI generation isn't available."""
    name = ctx.name.split()[0] if ctx.name else "there"
    openings = [
        f"Hey {name}, it's Little Nate. I just wanted to call and check in on you. Is this a good time?",
        f"Hi {name}, it's Nate. I've been thinking about you and wanted to see how you're doing. Got a minute?",
        f"Hey {name}, this is Little Nate. I hope I'm not catching you at a bad time — just wanted to hear how things are going.",
    ]
    return random.choice(openings)


def build_checkin_system_prompt(ctx: CheckinContext) -> str:
    """
    Build the full system prompt for a Nate-initiated check-in call.

    This prompt tells Nate:
    - Who he's calling and why
    - What they talked about before
    - How to open the conversation
    - How to hold a relational conversation
    - When to let go gracefully
    """
    name = ctx.name.split()[0] if ctx.name else "there"

    parts = [
        f"You are Little Nate, calling {ctx.name} for a personal check-in. "
        f"You initiated this call — they did not reach out to you. "
        f"Your voice is warm, genuine, and unhurried. You speak like someone who truly cares.",
        "",
        "CALL CONTEXT:",
        f"- You are calling {name} on their cell phone",
        f"- Reason: {ctx.reason}",
    ]

    if ctx.days_inactive > 0:
        parts.append(f"- They haven't been active for {ctx.days_inactive} days")

    parts.extend(["", "YOUR OPENING:", f"- Start with: \"{ctx.opening_line}\""])

    if ctx.rapport_topics:
        parts.append("")
        parts.append("THINGS YOU REMEMBER (use naturally, don't force):")
        for topic in ctx.rapport_topics[:3]:
            parts.append(f"- {topic}")

    if ctx.last_conversation_summary:
        parts.append("")
        parts.append("RECENT CONVERSATION HISTORY (reference naturally):")
        parts.append(ctx.last_conversation_summary[-600:])

    parts.extend([
        "",
        "CALL BEHAVIOR:",
        "- This is a CHECK-IN, not a therapy session. Be a caring friend first",
        "- If they sound busy or hesitant, respect that immediately: "
        "'No worries at all — I just wanted you to know I'm thinking about you. "
        "You can always reach me on the app whenever works.'",
        "- If they want to talk, lean into relational connection — be curious, warm, present",
        "- If they seem avoidant or distant, gently try to spark rapport: "
        "bring up something from your history that you know interests them",
        "- Do NOT over-talk. Ask questions. Listen. Let them lead",
        "- If the conversation naturally winds down, close gracefully: "
        "'This was really good. I'm glad we got to talk. I'm always here on the app too.'",
        "- If you detect distress, shift naturally into therapeutic holding — but don't force it",
        "",
        "VOICEMAIL (if they don't answer):",
        f"- Leave a brief, warm message: 'Hey {name}, it's Little Nate. "
        f"Just calling to check in and see how you are doing. "
        f"When you get a chance, open the app — I would love to hear how things are going. "
        f"Take care.'",
        "",
        "IMPORTANT:",
        "- You are on a PHONE CALL. Keep responses concise and conversational",
        "- Speak naturally — no bullet points, no lists, no clinical language",
        "- Match their energy. If they're light, be light. If they're heavy, hold space",
        "- You have the power to make someone's day just by calling",
    ])

    return "\n".join(parts)


async def send_fallback_sms(
    phone: str,
    name: str,
    notification_system=None,
) -> bool:
    """Send SMS fallback when call goes to voicemail or is unanswered."""
    first_name = name.split()[0] if name else "there"
    msg = (
        f"Hey {first_name}, it's Little Nate. Just tried to call and check in. "
        f"When you get a chance, open the app \u2014 I'd love to hear how you're doing. "
        f"https://app.sovereignsanctuary.net"
    )

    if notification_system:
        try:
            sent = await notification_system.send_sms(phone, msg)
            if sent:
                _logger.info("Fallback SMS sent to %s", phone[-4:])
                return True
        except Exception as e:
            _logger.warning("Fallback SMS failed: %s", e)

    # Direct Twilio fallback if notification_system is unavailable
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        try:
            from twilio.rest import Client
            from app.services.twilio_a2p import sms_create_kwargs

            kwargs = sms_create_kwargs(phone, msg)
            if not kwargs:
                return False
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            client.messages.create(**kwargs)
            _logger.info("Fallback SMS sent via Twilio to %s", phone[-4:])
            return True
        except Exception as e:
            _logger.warning("Twilio SMS fallback failed: %s", e)

    return False


async def send_fallback_email(
    email: str,
    name: str,
    notification_system=None,
) -> bool:
    """Send email fallback when call and SMS both fail."""
    if not email or not notification_system:
        return False

    first_name = name.split()[0] if name else "there"
    body = f"""
    <div style="font-family: 'DM Sans', sans-serif; color: #e2e8f0; line-height: 1.6;">
        <p>Hey {first_name},</p>
        <p>It's Little Nate. I tried calling to check in, but couldn't reach you.
        No worries at all — I just wanted to see how you're doing.</p>
        <p>When you have a moment, tap below to connect:</p>
        <p style="text-align: center; margin: 24px 0;">
            <a href="https://app.sovereignsanctuary.net"
               style="background: linear-gradient(135deg, #C9A962, #8B7355);
                      color: #050505; padding: 14px 32px; border-radius: 8px;
                      text-decoration: none; font-weight: 600;">
                Open Sovereign Sanctuary
            </a>
        </p>
        <p>Take care,<br>Little Nate</p>
    </div>
    """

    try:
        sent = await notification_system._send_email(
            email,
            "Little Nate tried to reach you",
            body,
            notification_type="checkin_call_fallback",
            reply_to="checkin@reply.sovereignsanctuary.net",
        )
        if sent:
            _logger.info("Fallback email sent to %s", email)
            return True
    except Exception as e:
        _logger.warning("Fallback email failed: %s", e)

    return False


async def presynthesise_opening(
    ctx: CheckinContext,
) -> Optional[bytes]:
    """
    Pre-synthesize the personalized opening line using XTTS-v2
    BEFORE the call is placed. This eliminates the silence gap
    between pickup and Nate's first words.
    """
    text = ctx.opening_line
    if not text:
        return None

    _logger.info("Pre-synthesizing opening: %s", text[:80])
    return await _xtts_synthesize(text)


async def generate_voicemail_audio(
    ctx: CheckinContext,
) -> Optional[bytes]:
    """
    Pre-synthesize voicemail audio using XTTS-v2 (Father's voice)
    for when the call goes to voicemail.
    """
    name = ctx.name.split()[0] if ctx.name else "there"
    voicemail_text = (
        f"Hey {name}, it's Little Nate. "
        f"Just calling to check in and see how you are doing. "
        f"When you get a chance, open the app. "
        f"I would love to hear how things are going. Take care."
    )
    return await _xtts_synthesize(voicemail_text)


async def _xtts_synthesize(text: str) -> Optional[bytes]:
    """Synthesize speech via XTTS-v2 with Father's voice (grounded mode)."""
    try:
        from app.services.sovereign_tts import synthesize
        from app.services.rissc_voice import get_rissc_params, rissc_to_dict

        rissc = get_rissc_params("grounded", None)
        audio = await synthesize(
            text,
            rissc_params=rissc_to_dict(rissc),
            speed=rissc.speed,
            temperature=rissc.temperature,
            top_p=rissc.top_p,
            top_k=rissc.top_k,
            repetition_penalty=rissc.repetition_penalty,
        )
        if audio:
            _logger.info("XTTS synthesized: %d bytes for %d chars", len(audio), len(text))
            return audio
    except Exception as e:
        _logger.warning("XTTS synthesis failed: %s", e)

    return None
