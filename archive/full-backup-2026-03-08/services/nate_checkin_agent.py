"""
LITTLE NATE — Check-In Agent
Monitors client and coach inactivity and sends warm check-in outreach
after 72 hours of no activity. Sends an early coach alert at 62 hours
for inactive clients.

Poll interval: 30 minutes. Stagger: 310s.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import aiohttp

from app.services.nate_ai_config import NATE_CHAT_URL, NATE_CHAT_KEY, nate_chat_headers, nate_chat_payload

logger = logging.getLogger("nate.checkin_agent")

POLL_INTERVAL_SECONDS = 1800  # 30 minutes
STAGGER_DELAY = 310

CLIENT_ALERT_HOURS = 62
CLIENT_OUTREACH_HOURS = 72
COACH_OUTREACH_HOURS = 72


class NateCheckInAgent:
    def __init__(self, db_pool, notification_system=None, app_state=None):
        self.db_pool = db_pool
        self.notification_system = notification_system
        self.app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("NateCheckInAgent started (every 30min, stagger %ds)", STAGGER_DELAY)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("NateCheckInAgent stopped")

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_DELAY)
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("NateCheckInAgent tick failed: %s", e, exc_info=True)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _tick(self):
        now = datetime.now(timezone.utc)
        async with self.db_pool.acquire() as conn:
            users = await conn.fetch("""
                SELECT username, role, hardware_id, profile_data
                FROM users
                WHERE subscription_status IN ('ACTIVE', 'TRIAL_ACTIVE')
                  AND role IN ('CLIENT', 'COACH')
            """)

        for row in users:
            try:
                profile = row["profile_data"] or {}
                if isinstance(profile, str):
                    try:
                        profile = json.loads(profile)
                    except Exception:
                        profile = {}

                role = row["role"]
                hw_id = row["hardware_id"] or row["username"]
                username = row["username"]
                name = profile.get("name") or username

                last_activity = profile.get("last_activity_at") or profile.get("last_login") or ""
                if not last_activity:
                    continue

                try:
                    last_dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue

                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)

                hours_inactive = (now - last_dt).total_seconds() / 3600

                snooze_until = profile.get("checkin_snooze_until")
                if snooze_until:
                    try:
                        snooze_dt = datetime.fromisoformat(snooze_until.replace("Z", "+00:00"))
                        if snooze_dt.tzinfo is None:
                            snooze_dt = snooze_dt.replace(tzinfo=timezone.utc)
                        if now < snooze_dt:
                            continue
                    except (ValueError, AttributeError):
                        pass

                if role == "CLIENT":
                    await self._handle_client(conn, now, username, hw_id, name, profile, hours_inactive)
                elif role == "COACH":
                    await self._handle_coach(conn, now, username, hw_id, name, profile, hours_inactive)

            except Exception as e:
                logger.warning("NateCheckInAgent: error processing %s: %s", row.get("username", "?"), e)

    # ── Client Logic ──────────────────────────────────────────────────

    async def _handle_client(self, conn, now, username, hw_id, name, profile, hours_inactive):
        if hours_inactive >= CLIENT_OUTREACH_HOURS:
            if not await self._recent_checkin(conn, username, "client_72h", hours=72):
                await self._send_client_outreach(conn, username, hw_id, name, profile)

        elif hours_inactive >= CLIENT_ALERT_HOURS:
            if not await self._recent_checkin(conn, username, "coach_alert_62h", hours=72):
                await self._send_coach_alert(conn, username, hw_id, name, profile)

    async def _send_coach_alert(self, conn, username, hw_id, name, profile):
        coach_id = profile.get("coach_id") or profile.get("assigned_coach_id")
        if not coach_id:
            return

        async with self.db_pool.acquire() as c:
            coach_row = await c.fetchrow("""
                SELECT username, profile_data FROM users
                WHERE hardware_id = $1 AND role = 'COACH'
            """, coach_id)

        if not coach_row:
            return

        coach_profile = coach_row["profile_data"] or {}
        if isinstance(coach_profile, str):
            try:
                coach_profile = json.loads(coach_profile)
            except Exception:
                coach_profile = {}

        coach_name = coach_profile.get("name") or coach_row["username"]
        coach_contact = coach_profile.get("preferred_contact", "email")
        coach_email = coach_profile.get("email")
        coach_phone = coach_profile.get("phone")

        msg = (
            f"Hi {coach_name}, this is Little Nate. Your client {name} hasn't "
            f"been active for over 62 hours. You may want to reach out and check in."
        )

        channel = None
        if coach_contact == "sms" and coach_phone and self.notification_system:
            sent = await self.notification_system.send_sms(coach_phone, msg)
            if sent:
                channel = "sms"
        if not channel and coach_email and self.notification_system:
            sent = await self.notification_system._send_email(
                coach_email,
                f"Client Check-In Alert: {name}",
                msg,
                notification_type="checkin_coach_alert",
                reply_to="checkin@reply.sovereignsanctuary.net",
            )
            if sent:
                channel = "email"

        await self._record_checkin(conn, username, "CLIENT", "coach_alert_62h", channel, msg, {
            "coach_id": coach_id,
            "coach_username": coach_row["username"],
        })
        await self._create_nudge(conn, hw_id, "checkin_coach_alert",
                                 "Client Activity Alert",
                                 f"{name} has been inactive for 62+ hours.")
        logger.info("Coach alert sent for client %s to coach %s", username, coach_row["username"])

    async def _send_client_outreach(self, conn, username, hw_id, name, profile):
        preferred = profile.get("preferred_contact", "email")
        email = profile.get("email")
        phone = profile.get("phone")

        deep_link = "https://app.sovereignsanctuary.net"
        msg = (
            f"Hi {name}, it's Little Nate. Just checking in \u2014 how are you doing? "
            f"If you'd like to connect, tap here: {deep_link} . "
            f"If you're doing well, reply with a number (1-3) for when you'd like "
            f"me to check back in (days). Take care."
        )

        channel = None
        if preferred == "sms" and phone and self.notification_system:
            sent = await self.notification_system.send_sms(phone, msg)
            if sent:
                channel = "sms"
        if not channel and email and self.notification_system:
            email_body = self._build_checkin_email_html(name, deep_link)
            sent = await self.notification_system._send_email(
                email, "Little Nate is checking in", email_body,
                notification_type="checkin_client",
                reply_to="checkin@reply.sovereignsanctuary.net",
            )
            if sent:
                channel = "email"

        await self._record_checkin(conn, username, "CLIENT", "client_72h", channel, msg)
        await self._create_nudge(conn, hw_id, "checkin_client_72h",
                                 "Little Nate is checking in",
                                 f"Hey {name}, it's been a few days. Tap to reconnect.")
        logger.info("72h check-in sent to client %s via %s", username, channel or "nudge-only")

    # ── Coach Logic ───────────────────────────────────────────────────

    async def _handle_coach(self, conn, now, username, hw_id, name, profile, hours_inactive):
        if hours_inactive < COACH_OUTREACH_HOURS:
            return
        if await self._recent_checkin(conn, username, "coach_72h", hours=72):
            return

        question = await self._generate_coach_question(username, name)

        preferred = profile.get("preferred_contact", "email")
        email = profile.get("email")
        phone = profile.get("phone")

        msg = question or (
            f"Hey {name}, it's Little Nate. It's been a few days \u2014 wanted to check in "
            f"on your coaching goals. Any wins to celebrate or goals you'd like me to "
            f"help track this week? Reply anytime."
        )

        channel = None
        if preferred == "sms" and phone and self.notification_system:
            sent = await self.notification_system.send_sms(phone, msg)
            if sent:
                channel = "sms"
        if not channel and email and self.notification_system:
            sent = await self.notification_system._send_email(
                email, "Little Nate coaching check-in", msg,
                notification_type="checkin_coach",
                reply_to="checkin@reply.sovereignsanctuary.net",
            )
            if sent:
                channel = "email"

        await self._record_checkin(conn, username, "COACH", "coach_72h", channel, msg)
        await self._create_nudge(conn, hw_id, "checkin_coach_72h",
                                 "Little Nate coaching check-in",
                                 msg[:200])
        logger.info("72h check-in sent to coach %s via %s", username, channel or "nudge-only")

    # ── DOJO-Aware AI Question Generator ──────────────────────────────

    async def _generate_coach_question(self, username: str, name: str) -> Optional[str]:
        """Query recent DOJO data and use Azure OpenAI to craft a coaching question."""
        try:
            dojo_context = await self._get_dojo_context(username)
        except Exception as e:
            logger.warning("NateCheckInAgent: DOJO context fetch failed for %s: %s", username, e)
            dojo_context = ""

        if not dojo_context:
            return None

        if not NATE_CHAT_KEY:
            return None

        system_prompt = (
            "You are Little Nate, a warm and supportive AI coaching assistant. "
            "Generate a single, brief check-in question for a coach who hasn't "
            "been active for 3 days. Use the DOJO session context below to make "
            "the question specific and motivating. Keep it under 280 characters "
            "(SMS-friendly). Be warm but not clinical. Use their first name."
        )

        user_prompt = (
            f"Coach name: {name}\n\n"
            f"Recent DOJO context:\n{dojo_context}\n\n"
            f"Generate a warm, specific check-in message."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(NATE_CHAT_URL,
                                        json=nate_chat_payload(messages, max_tokens=200, user_id=username),
                                        headers=nate_chat_headers(),
                                        timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            content = choices[0].get("message", {}).get("content", "")
                            return content.strip().strip('"').strip("'")
                    else:
                        err = await resp.text()
                        logger.warning("Azure coach question gen failed (%d): %s", resp.status, err[:200])
        except Exception as e:
            logger.warning("Azure coach question gen error: %s", e)

        return None

    async def _get_dojo_context(self, username: str) -> str:
        """Fetch recent DOJO feedback and mentor observations for a coach."""
        parts = []
        async with self.db_pool.acquire() as conn:
            feedback = await conn.fetch("""
                SELECT cm.content, cm.metadata, cm.created_at
                FROM coaching_mesh_messages cm
                JOIN coaching_mesh_participants cp ON cp.session_id = cm.session_id
                JOIN users u ON u.id::text = cp.user_id OR u.username = cp.user_id
                WHERE u.username = $1
                  AND cm.message_type = 'nate_feedback'
                  AND cm.created_at > NOW() - INTERVAL '30 days'
                ORDER BY cm.created_at DESC
                LIMIT 5
            """, username)

            for row in feedback:
                meta = row["metadata"] or {}
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}
                score = meta.get("score", "")
                dimensions = meta.get("rubric_scores", {})
                snippet = (row["content"] or "")[:200]
                dim_str = ", ".join(f"{k}: {v}" for k, v in dimensions.items()) if dimensions else ""
                parts.append(f"- Feedback (score {score}): {snippet}")
                if dim_str:
                    parts.append(f"  Dimensions: {dim_str}")

            mentor_obs = await conn.fetch("""
                SELECT content, metadata, created_at
                FROM dojo_mentor_interactions
                WHERE coach_username = $1
                  AND interaction_type = 'observation'
                  AND created_at > NOW() - INTERVAL '30 days'
                ORDER BY created_at DESC
                LIMIT 3
            """, username)

            for row in mentor_obs:
                snippet = (row["content"] or "")[:200]
                parts.append(f"- Mentor observation: {snippet}")

        return "\n".join(parts) if parts else ""

    # ── Helpers ────────────────────────────────────────────────────────

    async def _recent_checkin(self, conn, username: str, checkin_type: str, hours: int = 72) -> bool:
        """Check if a check-in of this type was already sent recently."""
        async with self.db_pool.acquire() as c:
            row = await c.fetchval("""
                SELECT 1 FROM nate_checkins
                WHERE user_id = $1 AND checkin_type = $2
                  AND status IN ('sent', 'snoozed')
                  AND created_at > NOW() - ($3 || ' hours')::interval
                LIMIT 1
            """, username, checkin_type, str(hours))
        return row is not None

    async def _record_checkin(self, conn, username: str, role: str, checkin_type: str,
                              channel: Optional[str], content: str,
                              metadata: Optional[dict] = None):
        async with self.db_pool.acquire() as c:
            await c.execute("""
                INSERT INTO nate_checkins (user_id, role, checkin_type, channel, content, metadata)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, username, role, checkin_type, channel, content,
                json.dumps(metadata or {}))

    async def _create_nudge(self, conn, hw_id: str, nudge_type: str, title: str, content: str):
        """Create an in-app nudge so the user sees a notification if they open the app."""
        try:
            async with self.db_pool.acquire() as c:
                user_id = await c.fetchval(
                    "SELECT id FROM users WHERE hardware_id = $1", hw_id)
                if user_id:
                    await c.execute("""
                        INSERT INTO nate_nudges (user_id, nudge_type, title, content, scheduled_at)
                        VALUES ($1, $2, $3, $4, NOW())
                    """, user_id, nudge_type, title, content)
        except Exception as e:
            logger.warning("NateCheckInAgent: nudge creation failed: %s", e)

    def _build_checkin_email_html(self, name: str, deep_link: str) -> str:
        return f"""
        <div style="font-family: 'DM Sans', sans-serif; color: #e2e8f0; line-height: 1.6;">
            <p>Hi {name},</p>
            <p>It's Little Nate. I noticed it's been a few days since we connected,
            and I just wanted to check in and see how you're doing.</p>
            <p>If you'd like to reconnect, just tap the button below:</p>
            <p style="text-align: center; margin: 24px 0;">
                <a href="{deep_link}"
                   style="background: linear-gradient(135deg, #C9A962, #8B7355);
                          color: #050505; padding: 14px 32px; border-radius: 8px;
                          text-decoration: none; font-weight: 600; font-size: 16px;">
                    Open Sovereign Sanctuary
                </a>
            </p>
            <p>If you're doing well and just need a little space, no worries at all.
            You can reply to this email or text us back with a number (1-3) for how
            many days you'd like before I check in again.</p>
            <p>Take care,<br>Little Nate</p>
        </div>
        """
