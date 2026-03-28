"""
Check-In Reply Processor — Little Nate Follow-Up to 72h Check-In Responses
===========================================================================

When a coach or client replies to a check-in via SMS/email, this module:
1. Stores the USER's original reply as role='user' in chat history (coach or client)
2. Generates a substantive reply from Little Nate via Azure OpenAI
3. Stores the AI reply (coach: coach_nate_chat_history; client: client_nate_messages)
4. Sends follow-up: email first when available, then SMS when phone exists
"""

import asyncio
import json
import logging
import os
from typing import Optional

import aiohttp

from app.services.nate_ai_config import NATE_CHAT_URL, NATE_CHAT_KEY, nate_chat_headers, nate_chat_payload

logger = logging.getLogger("nate.checkin_reply_processor")

FALLBACK_REPLY = (
    "I got your message and I'm here when you're ready. "
    "Open the app to connect and see my full reply."
)


async def process_checkin_reply(
    user_id: str,
    role: str,
    response_text: str,
    channel: str,
    checkin_id: Optional[str],
    name: str,
    db_pool,
    notification_system,
) -> None:
    """
    Async follow-up after a check-in response is stored in checkin_wisdom.
    Call via asyncio.create_task from Twilio/SendGrid webhooks — do not await in webhook.
    """
    if not db_pool:
        print("[CheckInReply] SKIP: no db_pool")
        return
    if not notification_system:
        print("[CheckInReply] WARNING: no notification_system")

    try:
        from app.services.rls_context import set_rls_admin
        set_rls_admin()
    except Exception:
        pass

    checkin_uuid = str(checkin_id) if checkin_id else None

    # Per-checkin follow-up dedup: skip if we already sent a follow-up for this checkin
    if checkin_uuid:
        try:
            async with db_pool.acquire() as conn:
                already_sent = await conn.fetchval(
                    """SELECT 1 FROM coach_nate_chat_history
                       WHERE context_snapshot::text LIKE $1
                         AND role = 'assistant'
                         AND created_at > NOW() - INTERVAL '5 minutes'
                       LIMIT 1""",
                    f'%{checkin_uuid}%',
                )
                if not already_sent and role != "COACH":
                    already_sent = await conn.fetchval(
                        """SELECT 1 FROM client_nate_messages
                           WHERE source = 'checkin_followup'
                             AND created_at > NOW() - INTERVAL '5 minutes'
                             AND user_id = $1
                           LIMIT 1""",
                        user_id,
                    )
                if already_sent:
                    print(f"[CheckInReply] DEDUP: follow-up already sent for checkin {checkin_uuid[:8]}")
                    return
        except Exception as e:
            print(f"[CheckInReply] dedup check error (non-fatal): {e}")

    # Generate the AI reply
    reply_text = await _generate_reply(role, name, response_text)
    used_fallback = not reply_text
    if not reply_text:
        reply_text = FALLBACK_REPLY
        print(f"[CheckInReply] WARNING: Azure AI failed for {user_id}, using fallback")
    else:
        print(f"[CheckInReply] AI reply generated for {user_id} ({len(reply_text)} chars)")

    try:
        async with db_pool.acquire() as conn:
            # Update checkin_wisdom.ai_summary for the row we just inserted
            # Split by checkin_uuid to avoid asyncpg "inconsistent types" with NULL uuid param
            if checkin_uuid:
                await conn.execute(
                    """UPDATE checkin_wisdom SET ai_summary = $1
                       WHERE id = (
                         SELECT id FROM checkin_wisdom
                         WHERE user_id = $2 AND checkin_id = $3::uuid
                           AND (ai_summary IS NULL OR ai_summary = '')
                         ORDER BY created_at DESC LIMIT 1
                       )""",
                    reply_text[:5000],
                    user_id,
                    checkin_uuid,
                )
            else:
                await conn.execute(
                    """UPDATE checkin_wisdom SET ai_summary = $1
                       WHERE id = (
                         SELECT id FROM checkin_wisdom
                         WHERE user_id = $2
                           AND created_at > NOW() - INTERVAL '5 minutes'
                           AND (ai_summary IS NULL OR ai_summary = '')
                         ORDER BY created_at DESC LIMIT 1
                       )""",
                    reply_text[:5000],
                    user_id,
                )

            if role == "COACH":
                # Store the coach's ORIGINAL message as role='user' for conversation context
                await conn.execute(
                    """INSERT INTO coach_nate_chat_history
                       (coach_username, role, message, mode, context_snapshot)
                       VALUES ($1, 'user', $2, 'inquiry', $3)""",
                    user_id,
                    response_text[:4000],
                    json.dumps({"source": "checkin_reply", "channel": channel, "checkin_id": checkin_uuid}),
                )
                # Then store Nate's reply as role='assistant'
                await conn.execute(
                    """INSERT INTO coach_nate_chat_history
                       (coach_username, role, message, mode, context_snapshot)
                       VALUES ($1, 'assistant', $2, 'inquiry', $3)""",
                    user_id,
                    reply_text[:4000],
                    json.dumps({"source": "checkin_followup", "checkin_id": checkin_uuid, "used_fallback": used_fallback}),
                )
            else:
                # Client: store in client_nate_messages for in-app banner
                if checkin_uuid:
                    await conn.execute(
                        """INSERT INTO client_nate_messages (user_id, message, source, checkin_wisdom_id)
                           SELECT $1::text, $2, 'checkin_followup', cw.id FROM checkin_wisdom cw
                           WHERE cw.user_id = $1::text AND cw.checkin_id = $3::uuid
                           ORDER BY cw.created_at DESC LIMIT 1""",
                        user_id,
                        reply_text[:4000],
                        checkin_uuid,
                    )
                else:
                    await conn.execute(
                        """INSERT INTO client_nate_messages (user_id, message, source, checkin_wisdom_id)
                           SELECT $1::text, $2, 'checkin_followup', cw.id FROM checkin_wisdom cw
                           WHERE cw.user_id = $1::text
                             AND cw.created_at > NOW() - INTERVAL '5 minutes'
                           ORDER BY cw.created_at DESC LIMIT 1""",
                        user_id,
                        reply_text[:4000],
                    )
    except Exception as e:
        print(f"[CheckInReply] DB store failed for {user_id}: {e}")
        logger.warning("CheckInReplyProcessor: DB store failed for %s: %s", user_id, e)

    # Follow-up notification
    if used_fallback:
        # Don't claim "I replied in INSIGHTS" when we only stored the fallback
        await _send_follow_up(
            user_id=user_id, role=role, name=name,
            reply_text=reply_text, db_pool=db_pool,
            notification_system=notification_system,
            ai_succeeded=False,
        )
    else:
        await _send_follow_up(
            user_id=user_id, role=role, name=name,
            reply_text=reply_text, db_pool=db_pool,
            notification_system=notification_system,
            ai_succeeded=True,
        )


async def _generate_reply(role: str, name: str, response_text: str, user_id: str | None = None) -> Optional[str]:
    """Generate Little Nate's substantive reply via Nate AI chat."""
    if not NATE_CHAT_KEY:
        print("[CheckInReply] Nate AI config missing: no NATE_CHAT_KEY")
        return None

    if role == "COACH":
        system_prompt = (
            "You are Little Nate, a warm and knowledgeable AI coaching companion. "
            "A coach has replied to your check-in with a question or update about their practice. "
            "Generate a substantive, helpful reply (3-5 sentences). "
            "If they're asking about a clinical topic, provide relevant therapeutic approaches, "
            "frameworks, or considerations. Be warm but clinically informed. "
            "Use their first name. Address what they specifically asked about."
        )
    else:
        system_prompt = (
            "You are Little Nate, a warm and supportive AI therapy companion. "
            "Generate a brief, substantive reply (2-4 sentences) to this person's response "
            "to a check-in. Acknowledge what they shared and offer support or a gentle next step. "
            "Be warm but not clinical. Use their first name."
        )

    user_prompt = f"{name} replied: {response_text[:2000]}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                NATE_CHAT_URL,
                json=nate_chat_payload(messages, max_tokens=400, user_id=user_id),
                headers=nate_chat_headers(),
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "")
                        result = content.strip().strip('"').strip("'")
                        if result:
                            return result
                        print("[CheckInReply] AI returned empty content")
                    else:
                        print("[CheckInReply] AI returned no choices")
                else:
                    err = await resp.text()
                    print(f"[CheckInReply] AI HTTP {resp.status}: {err[:200]}")
                    logger.warning("CheckInReplyProcessor: AI %d: %s", resp.status, err[:200])
    except asyncio.TimeoutError:
        print("[CheckInReply] AI timeout (20s)")
    except Exception as e:
        print(f"[CheckInReply] AI error: {e}")
        logger.warning("CheckInReplyProcessor: AI error: %s", e)

    return None


async def _send_follow_up(
    user_id: str,
    role: str,
    name: str,
    reply_text: str,
    db_pool,
    notification_system,
    ai_succeeded: bool = True,
) -> None:
    """
    Send follow-up: email first when available, then SMS when phone exists.
    Message differs based on whether AI generated a real reply or fell back.
    """
    if not notification_system:
        return

    email = None
    phone = None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT profile_data->>'email' AS email, profile_data->>'phone' AS phone
                   FROM users WHERE username = $1""",
                user_id,
            )
            if row:
                email = (row.get("email") or "").strip()
                phone = (row.get("phone") or "").strip()
    except Exception as e:
        print(f"[CheckInReply] user lookup failed: {e}")
        return

    if role == "COACH":
        if ai_succeeded:
            msg_body = (
                f"{name}, I got your response. I replied back to you in our INSIGHTS chat. "
                "Please come review it."
            )
        else:
            msg_body = (
                f"{name}, I got your response and I'm here when you're ready. "
                "Open Coach Command to connect."
            )
        subject = "Little Nate replied to your check-in"
        link = "https://coach.sovereignsanctuary.net"
    else:
        if ai_succeeded:
            msg_body = (
                f"{name}, I got your response. I replied in our chat. "
                "Open the app to see my reply."
            )
        else:
            msg_body = (
                f"{name}, I got your response and I'm here when you're ready. "
                "Open the app to connect."
            )
        subject = "Little Nate replied to your check-in"
        link = "https://app.sovereignsanctuary.net"

    if email:
        body_html = f"<p>{msg_body}</p><p><a href=\"{link}\">Open the app</a></p>"
        await notification_system._send_email(
            email,
            subject,
            body_html,
            notification_type="checkin_followup",
            reply_to="checkin@reply.sovereignsanctuary.net",
        )
        print(f"[CheckInReply] Follow-up email sent to {user_id} (ai_ok={ai_succeeded})")

    if phone:
        sms = f"{msg_body} {link}"
        await notification_system.send_sms(phone, sms[:160] if len(sms) > 160 else sms)
        print(f"[CheckInReply] Follow-up SMS sent to {user_id}")
