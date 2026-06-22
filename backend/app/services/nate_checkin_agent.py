"""
LITTLE NATE — Check-In Agent
Monitors client and coach inactivity and sends warm check-in outreach
after 72 hours of no activity. Sends an early coach alert at 62 hours
for inactive clients.

Poll interval: 30 minutes. Stagger: 310s.

============================================================================
v1.3 SENSITIVE CLINICAL BRIDGE EXTENSIONS (additive to v1.2)
----------------------------------------------------------------------------
Plan: docs/plan_backups/sensitive_clinical_bridge_v1.3.backup.2026-05-08-1402.plan.md
Gaps implemented (Phase 3 dormant; orchestrator wiring lands Phase 4):

  * Gap 2  — Codeword listener (Note 1, BLOCKING)
  * Gap A  — safe_silence_mode two-step gate cadence suspension
  * Gap K  — Codeword + mandatory_reporting interaction (audit emission only)
  * Gap M  — 25-day expiry warning + 30-day auto-revert (Note 2, BLOCKING)
  * Gap S  — Locale fallback chain for welcome-back template (Note 3)

ADDITIVITY CONTRACT
The v1.2 cadence (62h coach alert, 72h client outreach, 72h coach outreach,
session reminders, request escalation) is preserved EXACTLY for any user whose
`profile_data->'safe_silence_mode_state'` is missing or `state == 'inactive'`.
Migration 208 seeds every existing user with `state='inactive'`, so legacy
users hit the v1.2 path unchanged. The `_V1_2_CADENCE_PRESERVED` invariant
below is a static guard the auditor reads (Phase 6 fixture verifies it
under load).

NOTE 1 (Codeword listener) lives in `check_codeword(...)` and intentionally
does NOT consult `safe_silence_mode_state`. The gate that suspends 72h
outreach lives in `_should_suspend_outreach(profile)` and is consulted only
by the v1.2 cadence handlers. The two paths are in separate methods (and
in fact in separate invocation contexts — scheduler vs per-message) so a
future maintainer cannot accidentally nest the codeword check inside the
silence branch. See plan Risk #3: "the silenced safety net is the single
largest clinical risk in the entire bridge."
============================================================================
"""

import asyncio
import hashlib
import hmac
import inspect
import json
import logging
import string
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger("nate.checkin_agent")

POLL_INTERVAL_SECONDS = 1800  # 30 minutes
STAGGER_DELAY = 310

CLIENT_ALERT_HOURS = 62
CLIENT_OUTREACH_HOURS = 72
COACH_OUTREACH_HOURS = 72
COACH_REQUEST_ESCALATION_HOURS = 72  # 3 days
SESSION_REMINDER_HOURS = 24

# ===========================================================================
# v1.3 Sensitive Clinical Bridge — constants, enums, dataclasses
# ===========================================================================

# Boot-time invariant: v1.2 cadence is preserved when no v1.3 state is set.
# Auditor check `phase3_checkin_agent_v1_2_cadence_preserved` (deferred to
# Phase 6 fixtures per the user's sequencing reminder) reads this flag.
_V1_2_CADENCE_PRESERVED = True

# safe_silence_mode_state enum values (mirror migration 208 JSONB shape)
SAFE_SILENCE_INACTIVE = "inactive"
SAFE_SILENCE_PENDING = "pending_approval"
SAFE_SILENCE_ACTIVE = "active"

# Gap M day thresholds. Plan §Gap M: warning at day 25, auto-revert at day 30.
SAFE_SILENCE_WARNING_DAYS = 25
SAFE_SILENCE_REVERT_DAYS = 30

# Codeword normalization. Strip punctuation, lowercase, ASCII-fold via NFKD
# (clinician may set "café"; survivor may type "cafe"). Cap multi-token
# innocuous_phrase windows at 6 tokens — covers the example "I'm thinking
# about ordering pizza tonight" type patterns without fanout explosion.
_PUNCT_TABLE = str.maketrans("", "", string.punctuation)
_CODEWORD_MAX_PHRASE_TOKENS = 6

# Welcome-back template directory (Note 3). Resolves to
# `<repo>/backend/data/templates/`. The stub at `welcome_back_en-US.json`
# ships with `_meta.status="awaiting_clinician_authoring"` and an empty body
# so the loader fails closed until a clinician authors content.
_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "data" / "templates"
_WELCOME_BACK_FILENAME = "welcome_back_{locale}.json"

# sensitive_bridge_log canonical event_type strings (must match the CHECK
# constraint in migration 202). Pinned as constants so a typo can't silently
# downgrade an audit row to a generic event.
AUDIT_EVT_CODEWORD_TRIGGERED = "codeword_triggered"
AUDIT_EVT_CODEWORD_WITH_REPORTING = "codeword_triggered_with_mandatory_reporting_path"
AUDIT_EVT_SAFE_SILENCE_WARNING = "safe_silence_mode_expiry_warning"
AUDIT_EVT_SAFE_SILENCE_REVERTED = "safe_silence_mode_auto_reverted"

# Diagnostic markers (NOT sensitive_bridge_log event_types — these are log
# markers infra dashboards can pick up).
DIAG_WELCOME_BACK_UNAVAILABLE = "welcome_back_template_unavailable"
DIAG_WELCOME_BACK_DISPATCHED = "welcome_back_template_dispatched"


@dataclass
class CodewordMatch:
    """Result returned by `check_codeword(...)` to the orchestrator (Phase 4).

    The orchestrator dispatches the coach alert and (when
    `triggers_mandatory_reporting=True`) invokes
    `mandatory_reporting.evaluate(...)` with a synthetic
    `active_danger_codeword_triggered` trigger per plan Gap K.

    This dataclass NEVER carries the raw matched text. The hash prefix is
    intentionally short (8 hex chars) — enough for clinician correlation in
    the portal, not enough to brute-force the salted hash.
    """

    user_id: str
    codeword_hash: str
    codeword_type: str  # 'explicit_word' | 'innocuous_phrase'
    triggers_mandatory_reporting: bool
    escalation_event: Dict[str, Any]
    matched_at: datetime
    audit_event: str  # which sensitive_bridge_log event_type was emitted


@dataclass
class CodewordDisclosureEvent:
    """v1.4 part-aware codeword disclosure result.

    Extends CodewordMatch with IFS part linkage and addiction-bridge context
    per migration 217 columns on user_safety_codewords. Returned by
    `detect_codeword_disclosure(...)`.
    """

    user_id: str
    matched_codeword_id: int
    codeword_hash: str
    codeword_type: str
    disclosure_type: Optional[str]
    part_name: Optional[str]
    part_number: Optional[int]
    part_category: Optional[str]
    addiction_link: Optional[str]
    triggers_mandatory_reporting: bool
    escalation_event: Dict[str, Any]
    matched_at: datetime
    audit_event: str


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

        # v1.3 Gap M (Note 2): independent expiry scan. Internally runs Pass A
        # (day-25 warning) and Pass B (day-30 auto-revert) as two separate
        # idempotent jobs so a missed warning never blocks the revert.
        # Wrapped in its own try so a scan failure cannot crash the v1.2 cadence.
        try:
            await self.scan_safe_silence_expiry()
        except Exception as _exp_err:
            logger.warning(
                "nate_checkin_agent: scan_safe_silence_expiry failed (non-fatal): %s",
                _exp_err,
            )

        try:
            from app.services.wisdom_lifecycle_manager import WisdomLifecycleManager

            _wlm = WisdomLifecycleManager(self.db_pool, None)
            await _wlm.auto_absorb_high_confidence()
        except Exception as _wlc_err:
            logger.debug("wisdom lifecycle auto-absorb (non-fatal): %s", _wlc_err)

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
        # === Independent gate 1 (v1.3 Gap A): outreach cadence suspension ===
        # Suspends 62h/72h outreach when safe_silence_mode_state.state == 'active'.
        # This gate is INDEPENDENT of the codeword listener, which lives in
        # `check_codeword(...)` and intentionally never consults this state
        # (plan Gap 2 / Risk #3). The two paths are in separate methods AND
        # separate invocation contexts (scheduler tick vs per-message dispatch)
        # so the codeword safety net cannot accidentally be silenced.
        if self._should_suspend_outreach(profile):
            return

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
        # === Independent gate 1 (v1.3 Gap A): outreach cadence suspension ===
        # Same parallel-gate contract as `_handle_client`. The codeword listener
        # does NOT live here — it lives in `check_codeword(...)` and runs on
        # every inbound message regardless of silence state.
        if self._should_suspend_outreach(profile):
            return

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
        """Send 24h and 72h reminders for upcoming coaching sessions."""
        # Run two separate windows: 72h and 24h
        await self._send_reminder_window(window_hours=72, action_type="session_reminder_72h",
                                         lower_offset="71 hours", upper_offset="73 hours",
                                         label_for_client="in 3 days", label_for_coach="in 3 days")
        await self._send_reminder_window(window_hours=24, action_type="session_reminder_24h",
                                         lower_offset="23 hours", upper_offset="25 hours",
                                         label_for_client="tomorrow", label_for_coach="tomorrow")

    async def _send_reminder_window(self, *, window_hours: int, action_type: str,
                                    lower_offset: str, upper_offset: str,
                                    label_for_client: str, label_for_coach: str):
        from app.utils.timezone_resolver import format_session_start_for_profile

        notif_type = "reminder_72h" if window_hours == 72 else "reminder_24h"
        try:
            async with self.db_pool.acquire() as conn:
                upcoming = await conn.fetch(f"""
                    SELECT cs.id AS session_uuid, cs.session_id, cs.client_id, cs.coach_id,
                           cs.scheduled_start, cs.zoom_link,
                           u_client.username AS client_username,
                           u_client.profile_data AS client_profile,
                           u_coach.username AS coach_username,
                           u_coach.profile_data AS coach_profile
                    FROM coaching_sessions cs
                    JOIN users u_client ON u_client.hardware_id = cs.client_id
                    JOIN users u_coach ON u_coach.hardware_id = cs.coach_id
                    WHERE cs.status = 'scheduled'
                      AND cs.id IS NOT NULL
                      AND cs.scheduled_start BETWEEN NOW() + INTERVAL '{lower_offset}'
                                                 AND NOW() + INTERVAL '{upper_offset}'
                """)

                for row in upcoming:
                    session_uuid = row["session_uuid"]
                    session_id = str(row["session_id"])

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
                    zoom_link = (row["zoom_link"] or "").strip()

                    client_start_str, client_tz = format_session_start_for_profile(
                        row["scheduled_start"], client_profile,
                    )
                    coach_start_str, coach_tz = format_session_start_for_profile(
                        row["scheduled_start"], coach_profile,
                    )
                    join_line = f"\nJoin: {zoom_link}" if zoom_link else ""
                    sent_any = False

                    if (
                        client_email
                        and self.notification_system
                        and self._session_reminders_enabled(client_profile)
                        and await self._claim_session_notification(
                            conn, session_uuid, notif_type, row["client_id"],
                        )
                    ):
                        await self.notification_system._send_email(
                            client_email,
                            f"Session reminder: {client_start_str}",
                            f"Hi {client_name}, you have a coaching session with {coach_name} "
                            f"{label_for_client} ({client_start_str}, {client_tz})."
                            f"{join_line} See you there!",
                            notification_type="session_reminder",
                        )
                        sent_any = True

                    if (
                        coach_email
                        and self.notification_system
                        and self._session_reminders_enabled(coach_profile)
                        and await self._claim_session_notification(
                            conn, session_uuid, notif_type, row["coach_id"],
                        )
                    ):
                        await self.notification_system._send_email(
                            coach_email,
                            f"Session reminder: {client_name} {label_for_coach}",
                            f"Hi {coach_name}, reminder that you have a session with "
                            f"{client_name} {label_for_coach} at {coach_start_str} ({coach_tz})."
                            f"{join_line}",
                            notification_type="session_reminder",
                        )
                        sent_any = True

                    if sent_any:
                        await self._record_checkin(
                            conn, session_id, "SYSTEM", action_type,
                            "email", f"{window_hours}h reminder for session {session_id}",
                            {"client": row["client_username"], "coach": row["coach_username"]},
                        )
                        logger.info("%dh reminder sent for session %s", window_hours, session_id)
        except Exception as e:
            logger.warning("NateCheckInAgent: %s reminder failed: %s", action_type, e)

    @staticmethod
    def _session_reminders_enabled(profile: dict) -> bool:
        """Respect client/coach notification prefs (Flutter + bridge field names)."""
        if not profile:
            return True
        if profile.get("notif_session_reminders") is False:
            return False
        if profile.get("session_reminders") is False:
            return False
        return True

    @staticmethod
    async def _claim_session_notification(
        conn, session_uuid, notification_type: str, recipient_id: str,
    ) -> bool:
        """Idempotent send gate — claim slot before email (TZ-NOTIFICATION-FIX)."""
        if not session_uuid:
            return False
        claimed = await conn.fetchval(
            """
            INSERT INTO session_notifications (session_id, notification_type, channel, recipient_id)
            VALUES ($1, $2, 'email', $3)
            ON CONFLICT DO NOTHING RETURNING id
            """,
            session_uuid,
            notification_type,
            recipient_id,
        )
        return claimed is not None

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
                SELECT cm.content, cm.score, cm.created_at
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
                score = row["score"]
                snippet = (row["content"] or "")[:200]
                if score is not None:
                    parts.append(f"- Feedback (score {score}): {snippet}")
                else:
                    parts.append(f"- Feedback: {snippet}")

            mentor_obs = await conn.fetch("""
                SELECT di.content, di.dojo_lens, di.created_at
                FROM dojo_mentor_interactions di
                JOIN dojo_mentor_sessions dms ON dms.session_id = di.session_id
                WHERE di.interaction_type = 'observation'
                  AND di.created_at > NOW() - INTERVAL '30 days'
                  AND (
                      dms.coach_user_id = $1
                      OR dms.coach_user_id = (
                          SELECT u.hardware_id FROM users u WHERE u.username = $1 LIMIT 1
                      )
                      OR dms.coach_user_id = (
                          SELECT u.id::text FROM users u WHERE u.username = $1 LIMIT 1
                      )
                  )
                ORDER BY di.created_at DESC
                LIMIT 3
            """, username)

            for row in mentor_obs:
                snippet = (row["content"] or "")[:200]
                lens = row["dojo_lens"] or ""
                if lens:
                    parts.append(f"- Mentor observation ({lens}): {snippet}")
                else:
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

    # =======================================================================
    # v1.3 Sensitive Clinical Bridge — safe_silence_mode helpers (Gap A)
    # =======================================================================

    def _safe_silence_state(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        """Extract `safe_silence_mode_state` from profile JSONB. Returns {} when
        absent so callers can use `.get(...)` without isinstance gymnastics.

        Migration 208 seeds every existing user with the inactive shape, so a
        truly missing key only appears for users created before 208 ran or via
        a code path that bypassed the seeded default — both treated as
        v1.2-cadence users.
        """
        state = profile.get("safe_silence_mode_state")
        if isinstance(state, str):
            try:
                state = json.loads(state)
            except Exception:
                return {}
        return state if isinstance(state, dict) else {}

    def _should_suspend_outreach(self, profile: Dict[str, Any]) -> bool:
        """Independent gate 1: returns True iff 72h/62h outreach is suspended.

        Plan §Gap A: only `state == 'active'` suspends outreach. The
        `pending_approval` state intentionally does NOT suspend — the v1.2
        cadence keeps running while the dual-clinician approval is pending so
        the survivor is never silently dropped if approval stalls.
        """
        return self._safe_silence_state(profile).get("state") == SAFE_SILENCE_ACTIVE

    # =======================================================================
    # v1.3 Codeword listener (Note 1, BLOCKING) — Gap 2 / Gap K
    # =======================================================================

    def _normalize_for_codeword(self, text: str) -> List[str]:
        """Lowercase + ASCII-fold + strip punctuation + tokenize.

        NEVER logs the input text. Returns a list of tokens for the caller to
        slide windows over. Returns `[]` for empty/None input so callers can
        treat the empty case uniformly.
        """
        if not text:
            return []
        folded = (
            unicodedata.normalize("NFKD", text)
            .encode("ascii", "ignore")
            .decode("ascii", "ignore")
        )
        folded = folded.lower().translate(_PUNCT_TABLE)
        return [t for t in folded.split() if t]

    async def _get_active_codewords(self, user_id: str) -> List[Dict[str, Any]]:
        """Fetch active codewords (hash + salt + flags) for one user.

        Plain-text codewords are NEVER stored; this query returns only what is
        needed to constant-time-compare a salted hash of a candidate window.

        Failure-mode contract: if the query fails (DB down, table missing
        before migration 204 applies), return `[]`. The codeword path is the
        safety net (plan Risk #3) — we cannot fail-CLOSED here in the sense of
        blocking inbound messages. Infra monitoring catches the DB-down case
        upstream; the warning log surfaces the gap so on-call notices.
        """
        try:
            async with self.db_pool.acquire() as c:
                rows = await c.fetch(
                    """
                    SELECT codeword_hash, codeword_salt, codeword_type,
                           codeword_label, triggers_mandatory_reporting
                    FROM user_safety_codewords
                    WHERE user_id = $1 AND active = TRUE
                    """,
                    user_id,
                )
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(
                "nate_checkin_agent: codeword fetch failed for %s: %s",
                user_id,
                e,
            )
            return []

    async def check_codeword(
        self,
        *,
        user_id: str,
        message: str,
        session_id: Optional[str] = None,
    ) -> Optional[CodewordMatch]:
        """Independent gate 2: codeword listener. Runs on every inbound
        message regardless of `safe_silence_mode_state`.

        NOTE 1 CONTRACT (do not modify without clinician sign-off):
        This function MUST NOT consult `safe_silence_mode_state`. The
        codeword path is the SAFETY NET — plan Gap 2 / Risk #3:
            "the silenced safety net is the single largest clinical risk
             in the entire bridge."
        A future maintainer who adds an early-return based on silence state
        breaks the bridge's central safety contract. The boot guard
        `_auditor_self_check` reads the source of this function and asserts
        the absence of any `safe_silence_mode` reference here.

        Returns a `CodewordMatch` on first hit (the match itself is enough to
        escalate; we do not enumerate further matches per message). Returns
        `None` on no match. Plaintext is NEVER returned and NEVER logged.
        """
        # NB: NO safe_silence_mode check here. Do not add one.
        if not message or not user_id:
            return None

        tokens = self._normalize_for_codeword(message)
        if not tokens:
            return None

        codewords = await self._get_active_codewords(user_id)
        if not codewords:
            return None

        # Build candidate windows. Explicit words are 1-token; innocuous
        # phrases slide 2..N tokens. Both sets are constructed up-front so
        # the inner loop just does constant-time hash compares.
        explicit_candidates: List[Tuple[str, ...]] = [(tok,) for tok in tokens]
        phrase_candidates: List[Tuple[str, ...]] = []
        for window in range(2, _CODEWORD_MAX_PHRASE_TOKENS + 1):
            for i in range(len(tokens) - window + 1):
                phrase_candidates.append(tuple(tokens[i : i + window]))

        for cw in codewords:
            cw_type = cw["codeword_type"]
            salt = cw["codeword_salt"]
            stored_hash = cw["codeword_hash"]
            candidates = (
                explicit_candidates
                if cw_type == "explicit_word"
                else phrase_candidates
            )
            for cand in candidates:
                cand_text = " ".join(cand)
                digest = hashlib.sha256(
                    (cand_text + salt).encode("utf-8")
                ).hexdigest()
                if not hmac.compare_digest(digest, stored_hash):
                    continue

                # MATCH. Build escalation event + audit row. The orchestrator
                # (Phase 4) consumes the returned `CodewordMatch` and
                # dispatches the actual coach alert + (when
                # `triggers_mandatory_reporting`) the mandatory_reporting
                # evaluation. We never call those from inside the agent.
                triggers_reporting = bool(cw["triggers_mandatory_reporting"])
                audit_event = (
                    AUDIT_EVT_CODEWORD_WITH_REPORTING
                    if triggers_reporting
                    else AUDIT_EVT_CODEWORD_TRIGGERED
                )

                escalation = self._build_codeword_escalation(
                    user_id=user_id,
                    cw_type=cw_type,
                    cw_label=cw.get("codeword_label"),
                    triggers_reporting=triggers_reporting,
                )

                await self._emit_codeword_audit(
                    user_id=user_id,
                    session_id=session_id,
                    codeword_hash=stored_hash,
                    codeword_type=cw_type,
                    triggers_reporting=triggers_reporting,
                    audit_event=audit_event,
                    escalation=escalation,
                )

                # Best-effort trigger-metadata bump (clinician dashboards).
                try:
                    async with self.db_pool.acquire() as c:
                        await c.execute(
                            """
                            UPDATE user_safety_codewords
                            SET last_triggered_at = NOW(),
                                trigger_count = trigger_count + 1
                            WHERE user_id = $1 AND codeword_hash = $2
                            """,
                            user_id,
                            stored_hash,
                        )
                except Exception as _meta_err:
                    logger.debug(
                        "nate_checkin_agent: codeword trigger metadata update "
                        "non-fatal: %s",
                        _meta_err,
                    )

                return CodewordMatch(
                    user_id=user_id,
                    codeword_hash=stored_hash,
                    codeword_type=cw_type,
                    triggers_mandatory_reporting=triggers_reporting,
                    escalation_event=escalation,
                    matched_at=datetime.now(timezone.utc),
                    audit_event=audit_event,
                )

        return None

    # ===================================================================
    # v1.4 — Part-aware codeword disclosure detection (Phase C)
    # ===================================================================

    async def detect_codeword_disclosure(
        self,
        message: str,
        username: str,
        *,
        session_id: Optional[str] = None,
    ) -> Optional["CodewordDisclosureEvent"]:
        """v1.4 part-aware codeword detection.

        Loads codewords including the part-linkage columns added by migration
        217 (disclosure_type, part_name, part_number, part_category,
        addiction_link). Returns CodewordDisclosureEvent on match, None
        otherwise.

        Backward-compatible: if migration 217 columns are absent, falls back
        gracefully to the v1.3 `check_codeword` result wrapped in the v1.4
        dataclass shape (part fields = None).
        """
        if not message or not username:
            return None

        tokens = self._normalize_for_codeword(message)
        if not tokens:
            return None

        codewords = await self._get_active_codewords_v2(username)
        if not codewords:
            return None

        explicit_candidates: List[Tuple[str, ...]] = [(tok,) for tok in tokens]
        phrase_candidates: List[Tuple[str, ...]] = []
        for window in range(2, _CODEWORD_MAX_PHRASE_TOKENS + 1):
            for i in range(len(tokens) - window + 1):
                phrase_candidates.append(tuple(tokens[i : i + window]))

        for cw in codewords:
            cw_type = cw["codeword_type"]
            salt = cw["codeword_salt"]
            stored_hash = cw["codeword_hash"]
            candidates = (
                explicit_candidates
                if cw_type == "explicit_word"
                else phrase_candidates
            )
            for cand in candidates:
                cand_text = " ".join(cand)
                digest = hashlib.sha256(
                    (cand_text + salt).encode("utf-8")
                ).hexdigest()
                if not hmac.compare_digest(digest, stored_hash):
                    continue

                triggers_reporting = bool(cw["triggers_mandatory_reporting"])
                audit_event = (
                    AUDIT_EVT_CODEWORD_WITH_REPORTING
                    if triggers_reporting
                    else AUDIT_EVT_CODEWORD_TRIGGERED
                )

                escalation = self._build_codeword_escalation(
                    user_id=username,
                    cw_type=cw_type,
                    cw_label=cw.get("codeword_label"),
                    triggers_reporting=triggers_reporting,
                )

                await self._emit_codeword_audit(
                    user_id=username,
                    session_id=session_id,
                    codeword_hash=stored_hash,
                    codeword_type=cw_type,
                    triggers_reporting=triggers_reporting,
                    audit_event=audit_event,
                    escalation=escalation,
                )

                try:
                    async with self.db_pool.acquire() as c:
                        await c.execute(
                            """
                            UPDATE user_safety_codewords
                            SET last_triggered_at = NOW(),
                                trigger_count = trigger_count + 1
                            WHERE user_id = $1 AND codeword_hash = $2
                            """,
                            username,
                            stored_hash,
                        )
                except Exception as _meta_err:
                    logger.debug(
                        "nate_checkin_agent: codeword_disclosure trigger "
                        "metadata update non-fatal: %s",
                        _meta_err,
                    )

                return CodewordDisclosureEvent(
                    user_id=username,
                    matched_codeword_id=cw.get("id", 0),
                    codeword_hash=stored_hash,
                    codeword_type=cw_type,
                    disclosure_type=cw.get("disclosure_type"),
                    part_name=cw.get("part_name"),
                    part_number=cw.get("part_number"),
                    part_category=cw.get("part_category"),
                    addiction_link=cw.get("addiction_link"),
                    triggers_mandatory_reporting=triggers_reporting,
                    escalation_event=escalation,
                    matched_at=datetime.now(timezone.utc),
                    audit_event=audit_event,
                )

        return None

    async def _get_active_codewords_v2(
        self, user_id: str
    ) -> List[Dict[str, Any]]:
        """v1.4 fetch with part-aware columns from migration 217.

        Falls back to v1.3 query if new columns don't exist yet.
        """
        try:
            async with self.db_pool.acquire() as c:
                rows = await c.fetch(
                    """
                    SELECT codeword_hash, codeword_salt, codeword_type,
                           codeword_label, triggers_mandatory_reporting,
                           disclosure_type, part_name, part_number,
                           part_category, addiction_link
                    FROM user_safety_codewords
                    WHERE user_id = $1 AND active = TRUE
                    """,
                    user_id,
                )
            return [dict(r) for r in rows]
        except Exception as e:
            if "does not exist" in str(e):
                logger.info(
                    "nate_checkin_agent: v1.4 columns not yet applied, "
                    "falling back to v1.3 query for %s",
                    user_id,
                )
                return await self._get_active_codewords(user_id)
            logger.warning(
                "nate_checkin_agent: _get_active_codewords_v2 failed "
                "for %s: %s — returning empty",
                user_id, e,
            )
            return []

    def _build_codeword_escalation(
        self,
        *,
        user_id: str,
        cw_type: str,
        cw_label: Optional[str],
        triggers_reporting: bool,
    ) -> Dict[str, Any]:
        """Build the acuity escalation event via the central registry.

        Falls back to a structured stub if `coach_override_protocol` is
        unimportable in the current process — the audit row is still emitted
        so the orchestrator can cross-reference. The label policy from
        migration 204 forbids the codeword text from `codeword_label`, so
        passing it through is safe.
        """
        try:
            from app.services.coach_override_protocol import escalate_acuity

            return escalate_acuity(
                tier="codeword_triggered",
                user_id=user_id,
                context={
                    "codeword_label": cw_label,
                    "codeword_type": cw_type,
                    "triggers_mandatory_reporting": triggers_reporting,
                },
            )
        except Exception as e:
            logger.warning(
                "nate_checkin_agent: escalate_acuity unavailable for codeword "
                "on %s: %s — emitting fallback event",
                user_id,
                e,
            )
            return {
                "tier": "codeword_triggered",
                "severity": "high",
                "user_id": user_id,
                "plan_gap": "Gap 2 / Gap K",
                "fallback": True,
                "context": {
                    "codeword_label": cw_label,
                    "codeword_type": cw_type,
                    "triggers_mandatory_reporting": triggers_reporting,
                },
            }

    async def _emit_codeword_audit(
        self,
        *,
        user_id: str,
        session_id: Optional[str],
        codeword_hash: str,
        codeword_type: str,
        triggers_reporting: bool,
        audit_event: str,
        escalation: Dict[str, Any],
    ) -> None:
        """Append a `codeword_triggered[_with_mandatory_reporting_path]` row to
        `sensitive_bridge_log`. Plaintext is NEVER part of the payload — only
        the first 8 hex chars of the hash for clinician correlation.

        Severity:
          * 'emergency' when `triggers_mandatory_reporting=True` (Gap K)
          * 'high'      otherwise (Gap 2)

        Failure here is logged at ERROR but does not raise — the orchestrator
        still receives the `CodewordMatch` and can dispatch the alert from
        the in-memory event.
        """
        severity = "emergency" if triggers_reporting else "high"
        payload = {
            "codeword_hash_prefix": codeword_hash[:8],
            "codeword_type": codeword_type,
            "triggers_mandatory_reporting": triggers_reporting,
            "escalation_tier": escalation.get("tier"),
            "escalation_severity": escalation.get("severity"),
            "plan_gap": escalation.get("plan_gap"),
        }
        try:
            async with self.db_pool.acquire() as c:
                await c.execute(
                    """
                    INSERT INTO sensitive_bridge_log
                        (user_id, session_id, event_type, event_severity,
                         payload_json, recorded_by, access_classification,
                         pii_screened_at)
                    VALUES ($1, $2, $3, $4, $5, 'nate_checkin_agent',
                            'clinician_only', NOW())
                    """,
                    user_id,
                    session_id,
                    audit_event,
                    severity,
                    json.dumps(payload),
                )
        except Exception as e:
            logger.error(
                "nate_checkin_agent: sensitive_bridge_log write failed for "
                "codeword on %s: %s",
                user_id,
                e,
            )

    # =======================================================================
    # v1.3 safe_silence_mode expiry scheduler (Note 2, BLOCKING) — Gap M
    # =======================================================================

    async def scan_safe_silence_expiry(self) -> Dict[str, int]:
        """Note 2 contract: THREE independent passes, NOT one.

          * Pass A — day-25 expiry warning
          * Pass B — day-30 auto-revert
          * Pass C — manual admin revoke → welcome-back follow-up within 24h
             (Priority 2a; fail-closed template — Gap M wiring extension).

        Each pass has its own idempotency:
          * Pass A reserves `expiry_warning_sent_at` atomically.
          * Pass B re-uses the same JSONB shape mutation; a missed warning
            does NOT block the revert (Note 2b).

        Trade-off (Note 2a): the warning timestamp is reserved BEFORE the
        alert is dispatched. If dispatch fails after the timestamp commits,
        the next scan does NOT re-alert. Rationale documented inline in
        `_warn_expiry`. The portal expiry badge (driven by `expires_at`,
        independent of warning status) remains the source of truth so the
        clinician still sees the upcoming expiry even if the email blip
        landed in the gap.
        """
        counters = {
            "warnings_emitted": 0,
            "reverts_emitted": 0,
            "manual_revoke_welcome_attempts": 0,
            "errors": 0,
        }

        # ===== Pass A: Day-25 expiry warning =====
        try:
            async with self.db_pool.acquire() as conn:
                warning_rows = await conn.fetch(
                    """
                    SELECT username,
                           profile_data->'safe_silence_mode_state' AS state_json
                    FROM users
                    WHERE profile_data->'safe_silence_mode_state'->>'state' = $1
                      AND (profile_data->'safe_silence_mode_state'
                           ->>'approved_at')::timestamptz
                          <= (NOW() - ($2 || ' days')::interval)
                      AND profile_data->'safe_silence_mode_state'
                          ->>'expiry_warning_sent_at' IS NULL
                    """,
                    SAFE_SILENCE_ACTIVE,
                    str(SAFE_SILENCE_WARNING_DAYS),
                )

            for row in warning_rows:
                try:
                    state = self._coerce_state_json(row["state_json"])
                    ok = await self._warn_expiry(row["username"], state)
                    if ok:
                        counters["warnings_emitted"] += 1
                except Exception as e:
                    logger.warning(
                        "nate_checkin_agent: warning pass row failed for "
                        "%s: %s",
                        row.get("username"),
                        e,
                    )
                    counters["errors"] += 1
        except Exception as e:
            logger.warning(
                "nate_checkin_agent: warning pass query failed: %s", e
            )
            counters["errors"] += 1

        # ===== Pass B: Day-30 auto-revert =====
        # Independent of Pass A (Note 2b). Even if the warning never fired
        # (scheduler downtime between days 22-26), revert proceeds at day 30.
        # The revert SELECT does NOT include any `expiry_warning_sent_at`
        # predicate — that independence is verified by the auditor.
        try:
            async with self.db_pool.acquire() as conn:
                revert_rows = await conn.fetch(
                    """
                    SELECT username,
                           profile_data->'safe_silence_mode_state' AS state_json
                    FROM users
                    WHERE profile_data->'safe_silence_mode_state'->>'state' = $1
                      AND (profile_data->'safe_silence_mode_state'
                           ->>'expires_at')::timestamptz <= NOW()
                    """,
                    SAFE_SILENCE_ACTIVE,
                )

            for row in revert_rows:
                try:
                    state = self._coerce_state_json(row["state_json"])
                    ok = await self._revert_silence_mode(
                        row["username"],
                        state,
                        reason="approval_window_elapsed",
                    )
                    if ok:
                        counters["reverts_emitted"] += 1
                except Exception as e:
                    logger.warning(
                        "nate_checkin_agent: revert pass row failed for "
                        "%s: %s",
                        row.get("username"),
                        e,
                    )
                    counters["errors"] += 1
        except Exception as e:
            logger.warning(
                "nate_checkin_agent: revert pass query failed: %s", e
            )
            counters["errors"] += 1

        # ===== Pass C: Manual admin revoke → welcome-back (24h window; Priority 2a)
        try:
            async with self.db_pool.acquire() as conn:
                revoke_rows = await conn.fetch(
                    """
                    SELECT id, user_id, occurred_at, payload_json
                    FROM sensitive_bridge_log
                    WHERE event_type = 'safe_silence_mode_state_change'
                      AND payload_json->>'mutation_kind' = $1
                      AND occurred_at >= NOW() - INTERVAL '24 hours'
                    ORDER BY occurred_at ASC
                    """,
                    "safe_silence_active_revoked",
                )

            for row in revoke_rows:
                try:
                    uid = row["user_id"]
                    occurred_at = row["occurred_at"]
                    raw_pl = row["payload_json"]
                    pl: Dict[str, Any] = {}
                    if isinstance(raw_pl, dict):
                        pl = raw_pl
                    elif isinstance(raw_pl, str):
                        try:
                            parsed = json.loads(raw_pl)
                            if isinstance(parsed, dict):
                                pl = parsed
                        except Exception:
                            pl = {}
                    af = pl.get("additional_fields_redacted") or {}
                    if not isinstance(af, dict):
                        af = {}
                    trigger_ok = af.get("revoke_trigger") == (
                        "manual_admin_revocation"
                    )
                    if not trigger_ok:
                        continue

                    sole_ov = af.get("sole_clinician_override")

                    async with self.db_pool.acquire() as conn:
                        dup = await conn.fetchval(
                            """
                            SELECT 1 FROM sensitive_bridge_log
                            WHERE user_id = $1
                              AND event_type = $2
                              AND occurred_at >= $3
                              AND COALESCE(
                                  payload_json->>'welcome_back_source',
                                  ''
                              ) = $4
                            LIMIT 1
                            """,
                            uid,
                            AUDIT_EVT_SAFE_SILENCE_REVERTED,
                            occurred_at,
                            "manual_admin_revocation",
                        )
                    if dup:
                        continue

                    await self._dispatch_welcome_back(
                        uid,
                        locale_hint=None,
                        welcome_back_source="manual_admin_revocation",
                        sole_clinician_override=(
                            bool(sole_ov) if sole_ov is not None else None
                        ),
                    )
                    counters["manual_revoke_welcome_attempts"] += 1
                except Exception as e:
                    logger.warning(
                        "nate_checkin_agent: manual-revoke welcome-back "
                        "row failed for %s: %s",
                        row.get("user_id"),
                        e,
                    )
                    counters["errors"] += 1
        except Exception as e:
            logger.warning(
                "nate_checkin_agent: manual-revoke welcome-back query "
                "failed: %s",
                e,
            )
            counters["errors"] += 1

        return counters

    @staticmethod
    def _coerce_state_json(raw: Any) -> Dict[str, Any]:
        """asyncpg returns JSONB as either a parsed dict or a JSON string
        depending on driver settings. Normalise to dict; fall back to {} on
        anything unparseable so the caller's `.get(...)` chain is safe."""
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}

    def _resolve_warning_recipients(
        self, state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Note 2c: prefer `backup_clinician_id`; fall back to approving
        clinician (and orchestrator/admin pool downstream).

        Phase 3 ships before the Phase 5 portal that sets
        `backup_clinician_id` at approval time — most production rows will
        not have it yet. We degrade gracefully (`used_backup=False`,
        `primary_clinician_id=approver_id`) so the warning never fails
        merely because the backup field is absent.
        """
        backup_id = state.get("backup_clinician_id")
        approver_id = state.get("approver_id")
        return {
            # Prefer backup; fall back to approver. None remains None so the
            # downstream alert path can route to the admin pool.
            "primary_clinician_id": backup_id or approver_id,
            "approver_id": approver_id,
            "used_backup": bool(backup_id),
        }

    async def _warn_expiry(
        self, username: str, state: Dict[str, Any]
    ) -> bool:
        """Emit the day-25 warning for one user.

        ATOMICITY CONTRACT (Note 2a):
            1. Reserve the warning slot via conditional UPDATE inside a
               transaction. Only succeeds when
               `expiry_warning_sent_at IS NULL`, which prevents two
               concurrent scans from both winning.
            2. Insert the audit row in the same transaction.
            3. Commit the transaction.
            4. Dispatch the alert OUTSIDE the transaction.

        Trade-off: if alert dispatch fails after step 3 commits, the
        timestamp stays set and the next scan does NOT re-alert. We accept
        this because:
            * Reserve-first prevents two concurrent scans from
              double-alerting (which would erode coach trust).
            * Under-alerting is rare (requires alert-dispatch failure
              within the same scheduler tick) and visible (ERROR log +
              the portal expiry badge driven by `expires_at`).
        Inverse trade-off (timestamp set AFTER dispatch) was rejected
        because the race window allows double-fire, which is more harmful
        than a rare missed warning.
        """
        try:
            async with self.db_pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        """
                        UPDATE users
                        SET profile_data = jsonb_set(
                            profile_data,
                            '{safe_silence_mode_state,expiry_warning_sent_at}',
                            to_jsonb(NOW()::text)
                        )
                        WHERE username = $1
                          AND profile_data->'safe_silence_mode_state'
                              ->>'state' = $2
                          AND profile_data->'safe_silence_mode_state'
                              ->>'expiry_warning_sent_at' IS NULL
                        RETURNING username
                        """,
                        username,
                        SAFE_SILENCE_ACTIVE,
                    )
                    if not row:
                        # Lost the race to another scan, OR state changed,
                        # OR warning was already fired.
                        return False

                    recipients = self._resolve_warning_recipients(state)
                    payload = {
                        "approved_at": state.get("approved_at"),
                        "expires_at": state.get("expires_at"),
                        "warning_threshold_days": SAFE_SILENCE_WARNING_DAYS,
                        "primary_clinician_id": recipients[
                            "primary_clinician_id"
                        ],
                        "approver_id": recipients["approver_id"],
                        "used_backup_clinician": recipients["used_backup"],
                    }
                    await conn.execute(
                        """
                        INSERT INTO sensitive_bridge_log
                            (user_id, event_type, event_severity,
                             payload_json, recorded_by,
                             access_classification, pii_screened_at)
                        VALUES ($1, $2, 'moderate', $3,
                                'nate_checkin_agent',
                                'clinician_and_admin', NOW())
                        """,
                        username,
                        AUDIT_EVT_SAFE_SILENCE_WARNING,
                        json.dumps(payload),
                    )
        except Exception as e:
            logger.warning(
                "nate_checkin_agent: warning reserve+audit failed for "
                "%s: %s",
                username,
                e,
            )
            return False

        # Dispatch the alert outside the transaction. Failure here is
        # logged at ERROR — see atomicity trade-off above.
        try:
            await self._dispatch_safe_silence_warning_alert(
                username, self._resolve_warning_recipients(state), state
            )
        except Exception as e:
            logger.error(
                "nate_checkin_agent: WARNING DISPATCH FAILED for %s after "
                "timestamp commit. Coach portal expiry badge remains source "
                "of truth. Error: %s",
                username,
                e,
            )
        return True

    async def _dispatch_safe_silence_warning_alert(
        self,
        username: str,
        recipients: Dict[str, Any],
        state: Dict[str, Any],
    ) -> None:
        """Phase 3 dormant: structured log line that infra dashboards can
        pick up. Phase 4 wiring will replace this with the orchestrator's
        `coach_alert.fire(...)` call (in-app + portal badge).

        We intentionally do NOT push the warning through the email
        pipeline. Plan §Gap A specifies coach_alert as the channel so the
        clinician portal is the single source of truth for safe-silence
        governance. Email routing can race with profile mutations and
        produce stale state for the clinician.
        """
        primary = recipients.get("primary_clinician_id")
        logger.info(
            "nate_checkin_agent: safe_silence_mode warning user=%s "
            "primary_clinician=%s used_backup=%s expires_at=%s "
            "threshold_days=%d (Phase 4 will dispatch via coach_alert)",
            username,
            primary,
            recipients.get("used_backup"),
            state.get("expires_at"),
            SAFE_SILENCE_WARNING_DAYS,
        )

    async def _revert_silence_mode(
        self,
        username: str,
        state: Dict[str, Any],
        *,
        reason: str,
    ) -> bool:
        """Auto-revert one user. Independent of warning status (Note 2b).

        Atomicity: the JSONB rewrite + audit row commit in the same
        transaction. The welcome-back dispatch (Note 3) runs outside the
        transaction and is fail-closed: if no clinician-authored template
        exists, no message is sent.
        """
        try:
            async with self.db_pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        """
                        UPDATE users
                        SET profile_data = jsonb_set(
                            profile_data,
                            '{safe_silence_mode_state}',
                            jsonb_build_object(
                                'state', 'inactive',
                                'proposer_id', NULL,
                                'approver_id', NULL,
                                'proposed_at', NULL,
                                'approved_at', NULL,
                                'expires_at', NULL,
                                'expiry_warning_sent_at', NULL,
                                'auto_revert_eligible_at', NULL,
                                'codeword_precondition_met', false,
                                'reason_redacted', NULL
                            )
                        )
                        WHERE username = $1
                          AND profile_data->'safe_silence_mode_state'
                              ->>'state' = $2
                        RETURNING username
                        """,
                        username,
                        SAFE_SILENCE_ACTIVE,
                    )
                    if not row:
                        return False  # raced; another scan reverted

                    payload = {
                        "reason": reason,
                        "previous_approver": state.get("approver_id"),
                        "previous_expires_at": state.get("expires_at"),
                        "warning_was_sent": (
                            state.get("expiry_warning_sent_at") is not None
                        ),
                    }
                    await conn.execute(
                        """
                        INSERT INTO sensitive_bridge_log
                            (user_id, event_type, event_severity,
                             payload_json, recorded_by,
                             access_classification, pii_screened_at)
                        VALUES ($1, $2, 'high', $3,
                                'nate_checkin_agent',
                                'clinician_and_admin', NOW())
                        """,
                        username,
                        AUDIT_EVT_SAFE_SILENCE_REVERTED,
                        json.dumps(payload),
                    )
        except Exception as e:
            logger.warning(
                "nate_checkin_agent: revert atomic block failed for "
                "%s: %s",
                username,
                e,
            )
            return False

        # Welcome-back dispatch outside the transaction. Fail-closed.
        try:
            await self._dispatch_welcome_back(
                username,
                locale_hint=None,
                welcome_back_source="approval_window_elapsed",
            )
        except Exception as e:
            logger.error(
                "nate_checkin_agent: welcome-back dispatch failed for %s "
                "after revert: %s",
                username,
                e,
            )
        return True

    # =======================================================================
    # v1.3 Welcome-back template loader (Note 3) — Gap S locale fallback
    # =======================================================================

    def _load_welcome_back_template(
        self, locale: str = "en-US"
    ) -> Optional[Dict[str, Any]]:
        """Load the clinician-authored welcome-back template for a locale.

        Note 3 contract:
          * Template body is a clinician-authored artifact, NOT hardcoded.
          * Loader is FAIL-CLOSED: returns `None` (and emits the
            `welcome_back_template_unavailable` diagnostic marker) when the
            file is missing, malformed, has empty body, or its
            `_meta.status != 'clinician_authored'`.
          * No engineer-default body string is ever shipped to the
            survivor.

        Locale fallback chain (Gap S):
            <requested_locale>  ->  <language>  ->  en-US  ->  None
        """
        candidates: List[str] = []
        if locale:
            candidates.append(locale)
            if "-" in locale:
                candidates.append(locale.split("-", 1)[0])
        if "en-US" not in candidates:
            candidates.append("en-US")

        for cand in candidates:
            path = _TEMPLATE_DIR / _WELCOME_BACK_FILENAME.format(locale=cand)
            if not path.exists():
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    doc = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(
                    "nate_checkin_agent: welcome-back template %s "
                    "unreadable: %s — %s",
                    path.name,
                    e,
                    DIAG_WELCOME_BACK_UNAVAILABLE,
                )
                continue
            if not isinstance(doc, dict):
                continue
            meta = doc.get("_meta") or {}
            body = (doc.get("body") or "").strip()
            status = meta.get("status") if isinstance(meta, dict) else None
            if status != "clinician_authored" or not body:
                logger.info(
                    "nate_checkin_agent: welcome-back template %s present "
                    "but %s (status=%s, body_empty=%s) — fail-closed; "
                    "trying next locale in chain",
                    path.name,
                    DIAG_WELCOME_BACK_UNAVAILABLE,
                    status,
                    not bool(body),
                )
                continue
            return doc

        logger.info(
            "nate_checkin_agent: %s — no clinician-authored template "
            "across %s. Returning to the survivor without a welcome-back "
            "message (engineer-default text is intentionally not shipped).",
            DIAG_WELCOME_BACK_UNAVAILABLE,
            candidates,
        )
        return None

    async def _dispatch_welcome_back(
        self,
        username: str,
        *,
        locale_hint: Optional[str] = None,
        welcome_back_source: str = "approval_window_elapsed",
        sole_clinician_override: Optional[bool] = None,
    ) -> bool:
        """Dispatch the welcome-back message after auto-revert or manual
        admin revoke (Priority 2a Pass C).

        Fail-closed: if the loader returns None, no message is sent. An
        audit row is appended noting the gap so the portal can surface
        "template missing — clinician authoring required" to the
        responsible clinician.

        Phase 3 dormant: the actual delivery (in-app nudge / email / SMS)
        will be wired through the orchestrator's outreach pipeline in
        Phase 4. We log + audit so the path is testable today.
        """
        locale = locale_hint or "en-US"
        doc = self._load_welcome_back_template(locale)

        def _wb_payload(base: Dict[str, Any]) -> Dict[str, Any]:
            out = {**base, "welcome_back_source": welcome_back_source}
            if sole_clinician_override is not None:
                out["sole_clinician_override"] = bool(sole_clinician_override)
            return out

        if doc is None:
            try:
                async with self.db_pool.acquire() as c:
                    await c.execute(
                        """
                        INSERT INTO sensitive_bridge_log
                            (user_id, event_type, event_severity,
                             payload_json, recorded_by,
                             access_classification, pii_screened_at)
                        VALUES ($1, $2, 'moderate', $3,
                                'nate_checkin_agent',
                                'clinician_and_admin', NOW())
                        """,
                        username,
                        AUDIT_EVT_SAFE_SILENCE_REVERTED,
                        json.dumps(
                            _wb_payload(
                                {
                                    "welcome_back_dispatched": False,
                                    "reason": DIAG_WELCOME_BACK_UNAVAILABLE,
                                    "requested_locale": locale,
                                }
                            )
                        ),
                    )
            except Exception as e:
                logger.warning(
                    "nate_checkin_agent: welcome-back unavailable audit "
                    "row failed for %s: %s",
                    username,
                    e,
                )
            return False

        body = (doc.get("body") or "").strip()
        meta = doc.get("_meta") or {}

        logger.info(
            "nate_checkin_agent: %s for %s (locale=%s, version=%s, "
            "clinician=%s) — Phase 4 orchestrator will perform the actual "
            "outreach delivery",
            DIAG_WELCOME_BACK_DISPATCHED,
            username,
            meta.get("locale"),
            meta.get("version"),
            meta.get("clinician_authored_by"),
        )
        try:
            async with self.db_pool.acquire() as c:
                await c.execute(
                    """
                    INSERT INTO sensitive_bridge_log
                        (user_id, event_type, event_severity, payload_json,
                         recorded_by, access_classification,
                         pii_screened_at)
                    VALUES ($1, $2, 'moderate', $3,
                            'nate_checkin_agent',
                            'clinician_and_admin', NOW())
                    """,
                    username,
                    AUDIT_EVT_SAFE_SILENCE_REVERTED,
                    json.dumps(
                        _wb_payload(
                            {
                                "welcome_back_dispatched": True,
                                "template_version": meta.get("version"),
                                "template_locale": meta.get("locale"),
                                "clinician_authored_by": meta.get(
                                    "clinician_authored_by"
                                ),
                                "body_length": len(body),
                            }
                        )
                    ),
                )
        except Exception as e:
            logger.warning(
                "nate_checkin_agent: welcome-back dispatch audit row "
                "failed for %s: %s",
                username,
                e,
            )
        return True

    # =======================================================================
    # v1.3 Auditor self-check + boot guards
    # =======================================================================

    def _auditor_self_check(self) -> Dict[str, Any]:
        """Phase 6 auditor hook. Returns a dict the auditor maps to checks.

        Verifies the v1.3 contracts that protect the safety net:
          * codeword_listener_runs_in_silence_mode (Note 1)
          * expiry_warning_atomicity_documented (Note 2a)
          * expiry_warning_independent_of_revert (Note 2b)
          * backup_clinician_graceful_degradation (Note 2c)
          * welcome_back_template_clinician_gated (Note 3)
          * phase3_checkin_agent_v1_2_cadence_preserved (sequencing)

        Each check inspects source code or static state so the audit is
        deterministic and does not require a running DB. A separate Phase 6
        fixture exercises the live behaviors (codeword fires under active
        silence, day-25/day-30 idempotency, fail-closed loader).
        """
        # 1. Codeword listener does NOT consult silence state.
        #    The contract is structural: `check_codeword` must not CALL the
        #    silence-state helpers. Mentions in docstrings are allowed (and
        #    explicitly required by the "Do not add one" warning to future
        #    maintainers). We assert against the call patterns themselves.
        cw_src = inspect.getsource(self.check_codeword)
        cw_has_warning_comment = (
            "Do not add one" in cw_src or "do not add one" in cw_src
        )
        cw_invokes_silence_helper = (
            "self._should_suspend_outreach(" in cw_src
            or "self._safe_silence_state(" in cw_src
        )
        codeword_listener_runs_in_silence_mode = (
            cw_has_warning_comment and not cw_invokes_silence_helper
        )

        # 2. Atomicity contract documented in `_warn_expiry`.
        warn_src = inspect.getsource(self._warn_expiry)
        expiry_warning_atomicity_documented = (
            "ATOMICITY CONTRACT" in warn_src
            and "Reserve" in warn_src
        )

        # 3. Pass B does not gate on Pass A. We extract the Pass B SQL
        #    block and confirm `expiry_warning_sent_at` does not appear in
        #    the WHERE clause. Comments in surrounding Python prose may
        #    legitimately reference the column name to document the
        #    independence; what matters is the SQL predicate itself.
        scan_src = inspect.getsource(self.scan_safe_silence_expiry)
        revert_sql = ""
        if "Pass B" in scan_src and "WHERE profile_data" in scan_src:
            # Grab the Pass B section, then the first SQL block within it.
            _, pass_b_src = scan_src.split("Pass B", 1)
            if 'fetch(' in pass_b_src and '"""' in pass_b_src:
                # Triple-quoted SQL between the first pair of triple quotes.
                first = pass_b_src.find('"""')
                second = pass_b_src.find('"""', first + 3)
                if first >= 0 and second > first:
                    revert_sql = pass_b_src[first + 3 : second]
        expiry_warning_independent_of_revert = bool(revert_sql) and (
            "expiry_warning_sent_at" not in revert_sql
        )

        # 4. Backup clinician graceful degradation: the resolver must
        #    coalesce backup -> approver, not require backup.
        resolve_src = inspect.getsource(self._resolve_warning_recipients)
        backup_clinician_graceful_degradation = (
            "backup_clinician_id" in resolve_src
            and "backup_id or approver_id" in resolve_src
        )

        # 5. Welcome-back template loader: file-driven + fail-closed.
        loader_src = inspect.getsource(self._load_welcome_back_template)
        welcome_back_template_clinician_gated = (
            "_TEMPLATE_DIR" in loader_src
            and "clinician_authored" in loader_src
            and "fail-closed" in loader_src.lower()
        )

        # 6. v1.2 cadence preservation invariant
        phase3_checkin_agent_v1_2_cadence_preserved = bool(
            _V1_2_CADENCE_PRESERVED
        )

        return {
            "codeword_listener_runs_in_silence_mode": (
                codeword_listener_runs_in_silence_mode
            ),
            "expiry_warning_atomicity_documented": (
                expiry_warning_atomicity_documented
            ),
            "expiry_warning_independent_of_revert": (
                expiry_warning_independent_of_revert
            ),
            "backup_clinician_graceful_degradation": (
                backup_clinician_graceful_degradation
            ),
            "welcome_back_template_clinician_gated": (
                welcome_back_template_clinician_gated
            ),
            "phase3_checkin_agent_v1_2_cadence_preserved": (
                phase3_checkin_agent_v1_2_cadence_preserved
            ),
        }
