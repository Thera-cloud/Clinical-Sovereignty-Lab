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

logger = logging.getLogger("nate.checkin_agent")

POLL_INTERVAL_SECONDS = 1800  # 30 minutes
STAGGER_DELAY = 310

CLIENT_ALERT_HOURS = 62
CLIENT_OUTREACH_HOURS = 72
COACH_OUTREACH_HOURS = 72
COACH_REQUEST_ESCALATION_HOURS = 72  # 3 days
SESSION_REMINDER_HOURS = 24


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

        await self._escalate_stale_requests()
        await self._send_session_reminders()

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

    # ── Coach Request Escalation ──────────────────────────────────────

    async def _escalate_stale_requests(self):
        """Notify coaches about pending requests older than 3 days."""
        try:
            async with self.db_pool.acquire() as conn:
                stale = await conn.fetch("""
                    SELECT cr.request_id, cr.client_username, cr.coach_user_id,
                           EXTRACT(EPOCH FROM (NOW() - cr.requested_at))/3600 AS hours_pending,
                           u_coach.profile_data AS coach_profile,
                           u_coach.username AS coach_username,
                           u_client.profile_data AS client_profile,
                           ch.master_coach_id
                    FROM coach_requests cr
                    JOIN users u_coach ON u_coach.hardware_id = cr.coach_user_id
                    JOIN users u_client ON u_client.username = cr.client_username
                    LEFT JOIN coach_hierarchy ch
                        ON ch.assistant_id = cr.coach_user_id AND ch.status = 'active'
                    WHERE cr.status = 'pending'
                      AND cr.requested_at < NOW() - INTERVAL '%s hours'
                """ % COACH_REQUEST_ESCALATION_HOURS)

                for row in stale:
                    req_id = str(row["request_id"])
                    if await self._recent_checkin(conn, req_id, "coach_request_escalation", hours=72):
                        continue

                    coach_profile = row["coach_profile"] or {}
                    if isinstance(coach_profile, str):
                        try:
                            coach_profile = json.loads(coach_profile)
                        except Exception:
                            coach_profile = {}

                    client_profile = row["client_profile"] or {}
                    if isinstance(client_profile, str):
                        try:
                            client_profile = json.loads(client_profile)
                        except Exception:
                            client_profile = {}

                    coach_email = coach_profile.get("email")
                    coach_name = coach_profile.get("name") or row["coach_username"]
                    client_name = client_profile.get("name") or row["client_username"]
                    hours = int(row["hours_pending"])
                    days = hours // 24

                    msg = (
                        f"Hi {coach_name}, a coaching request from {client_name} has been "
                        f"waiting for {hours} hours. Please accept or decline at your earliest "
                        f"convenience: https://coach.sovereignsanctuary.net"
                    )

                    channel = None
                    if coach_email and self.notification_system:
                        sent = await self.notification_system._send_email(
                            coach_email,
                            f"Pending coaching request from {client_name}",
                            msg,
                            notification_type="coach_request_escalation",
                        )
                        if sent:
                            channel = "email"

                    await self._record_checkin(
                        conn, req_id, "SYSTEM", "coach_request_escalation",
                        channel, msg, {"coach": row["coach_username"], "client": row["client_username"]},
                    )
                    logger.info("Escalated stale coach request %s to %s", req_id, row["coach_username"])

                    master_id = row["master_coach_id"]
                    if master_id:
                        try:
                            master_row = await conn.fetchrow(
                                "SELECT username, profile_data FROM users WHERE hardware_id = $1",
                                master_id,
                            )
                            if master_row:
                                mp = master_row["profile_data"] or {}
                                if isinstance(mp, str):
                                    try:
                                        mp = json.loads(mp)
                                    except Exception:
                                        mp = {}
                                master_email = mp.get("email")
                                master_name = mp.get("name") or master_row["username"]
                                master_msg = (
                                    f"Hi {master_name}, {coach_name} has not responded to "
                                    f"{client_name}'s coaching request ({days} days). "
                                    f"Please follow up."
                                )
                                if master_email and self.notification_system:
                                    await self.notification_system._send_email(
                                        master_email,
                                        f"Unresponded coaching request: {coach_name} / {client_name}",
                                        master_msg,
                                        notification_type="coach_request_escalation",
                                    )
                                logger.info("Escalated to master coach %s for request %s", master_name, req_id)
                        except Exception as _me:
                            logger.warning("Master coach escalation failed for %s: %s", req_id, _me)
        except Exception as e:
            logger.warning("NateCheckInAgent: request escalation failed: %s", e)

    # ── Session Reminders ──────────────────────────────────────────────

    async def _send_session_reminders(self):
        """Send 24h reminders for upcoming coaching sessions."""
        try:
            async with self.db_pool.acquire() as conn:
                upcoming = await conn.fetch("""
                    SELECT cs.session_id, cs.client_id, cs.coach_id, cs.scheduled_start,
                           u_client.username AS client_username,
                           u_client.profile_data AS client_profile,
                           u_coach.username AS coach_username,
                           u_coach.profile_data AS coach_profile
                    FROM coaching_sessions cs
                    JOIN users u_client ON u_client.hardware_id = cs.client_id
                    JOIN users u_coach ON u_coach.hardware_id = cs.coach_id
                    WHERE cs.status = 'scheduled'
                      AND cs.scheduled_start BETWEEN NOW() + INTERVAL '23 hours'
                                                 AND NOW() + INTERVAL '25 hours'
                """)

                for row in upcoming:
                    session_id = str(row["session_id"])
                    if await self._recent_checkin(conn, session_id, "session_reminder_24h", hours=24):
                        continue

                    client_profile = row["client_profile"] or {}
                    if isinstance(client_profile, str):
                        try:
                            client_profile = json.loads(client_profile)
                        except Exception:
                            client_profile = {}

                    coach_profile = row["coach_profile"] or {}
                    if isinstance(coach_profile, str):
                        try:
                            coach_profile = json.loads(coach_profile)
                        except Exception:
                            coach_profile = {}

                    client_name = client_profile.get("name") or row["client_username"]
                    coach_name = coach_profile.get("name") or row["coach_username"]
                    client_email = client_profile.get("email")
                    coach_email = coach_profile.get("email")

                    start_str = row["scheduled_start"].strftime("%A, %B %d at %I:%M %p")

                    if client_email and self.notification_system:
                        await self.notification_system._send_email(
                            client_email,
                            f"Session reminder: {start_str}",
                            f"Hi {client_name}, you have a coaching session with {coach_name} "
                            f"tomorrow at {start_str}. See you there!",
                            notification_type="session_reminder",
                        )

                    if coach_email and self.notification_system:
                        await self.notification_system._send_email(
                            coach_email,
                            f"Session reminder: {client_name} tomorrow",
                            f"Hi {coach_name}, reminder that you have a session with "
                            f"{client_name} tomorrow at {start_str}.",
                            notification_type="session_reminder",
                        )

                    await self._record_checkin(
                        conn, session_id, "SYSTEM", "session_reminder_24h",
                        "email", f"Reminder for session {session_id}",
                        {"client": row["client_username"], "coach": row["coach_username"]},
                    )
                    logger.info("24h reminder sent for session %s", session_id)
        except Exception as e:
            logger.warning("NateCheckInAgent: session reminder failed: %s", e)

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

        try:
            from app.config import settings
        except Exception:
            return None

        endpoint = getattr(settings, "AZURE_OPENAI_ENDPOINT", "").rstrip("/")
        api_key = getattr(settings, "AZURE_API_KEY", "")
        deployment = getattr(settings, "AZURE_OPENAI_CHAT_DEPLOYMENT", "")

        if not all([endpoint, api_key, deployment]):
            return None

        if not endpoint.startswith("http"):
            endpoint = f"https://{endpoint}"

        url = (
            f"{endpoint}/openai/deployments/{deployment}"
            f"/chat/completions?api-version=2024-06-01"
        )

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

        headers = {"Content-Type": "application/json", "api-key": api_key}
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_completion_tokens": 200,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers,
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
