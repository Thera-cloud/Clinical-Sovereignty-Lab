"""
LITTLE NATE — Drip Campaign Scheduler
APScheduler-based background jobs for email drips, SMS fallbacks,
and Golden Ticket lifecycle management.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from app.config import settings

# SendGrid import with fallback
try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Email, To, DynamicTemplateData
    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False

# Twilio import with fallback
try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False

logger = logging.getLogger(__name__)


class DripScheduler:
    """Background scheduler for drip campaign automation."""

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self.scheduler = AsyncIOScheduler()

        # Initialize SendGrid
        self.sendgrid_client = None
        if SENDGRID_AVAILABLE and settings.SENDGRID_API_KEY:
            self.sendgrid_client = SendGridAPIClient(settings.SENDGRID_API_KEY)
        elif settings.SMTP_PASSWORD:
            # Fall back to SMTP_PASSWORD (existing pattern)
            self.sendgrid_client = SendGridAPIClient(settings.SMTP_PASSWORD)

        # Initialize Twilio
        self.twilio_client = None
        twilio_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', '') or ''
        twilio_token = getattr(settings, 'TWILIO_AUTH_TOKEN', '') or ''
        if TWILIO_AVAILABLE and twilio_sid and twilio_token:
            self.twilio_client = TwilioClient(twilio_sid, twilio_token)

        # Template mapping (step_order -> SendGrid template ID)
        self.drip_templates = {
            1: settings.SENDGRID_DRIP_TEMPLATE_DAY1,
            2: settings.SENDGRID_DRIP_TEMPLATE_DAY2,
            3: settings.SENDGRID_DRIP_TEMPLATE_DAY3,
            4: settings.SENDGRID_DRIP_TEMPLATE_DAY4,
            5: settings.SENDGRID_DRIP_TEMPLATE_DAY5,
        }

    def start(self):
        """Start the scheduler with all jobs."""
        # Check pending drips every 5 minutes
        self.scheduler.add_job(
            self.check_pending_drips,
            IntervalTrigger(minutes=settings.DRIP_SCHEDULER_CHECK_INTERVAL_MINUTES),
            id="check_pending_drips",
            name="Check & send pending drip emails",
            replace_existing=True
        )

        # Check SMS fallbacks every 15 minutes
        self.scheduler.add_job(
            self.check_sms_fallbacks,
            IntervalTrigger(minutes=15),
            id="check_sms_fallbacks",
            name="Send SMS fallbacks for unopened emails",
            replace_existing=True
        )

        # Check Golden Ticket reminders daily at 10 AM
        self.scheduler.add_job(
            self.check_golden_ticket_reminders,
            CronTrigger(hour=10, minute=0),
            id="check_ticket_reminders",
            name="Send Golden Ticket reminders",
            replace_existing=True
        )

        # Check expired tickets daily at midnight
        self.scheduler.add_job(
            self.check_expired_tickets,
            CronTrigger(hour=0, minute=0),
            id="check_expired_tickets",
            name="Mark expired Golden Tickets",
            replace_existing=True
        )

        # Update campaign analytics daily at 1 AM
        self.scheduler.add_job(
            self.update_campaign_analytics,
            CronTrigger(hour=1, minute=0),
            id="update_analytics",
            name="Update campaign analytics",
            replace_existing=True
        )

        # Check auto-execute strategy proposals every 10 minutes
        self.scheduler.add_job(
            self.check_approval_auto_executions,
            IntervalTrigger(minutes=10),
            id="check_approval_auto_exec",
            name="Auto-execute approved strategy proposals",
            replace_existing=True
        )

        # Generate foresight alerts every 6 hours
        self.scheduler.add_job(
            self.run_foresight_engine,
            IntervalTrigger(hours=6),
            id="run_foresight_engine",
            name="Generate foresight predictions and validate past alerts",
            replace_existing=True
        )

        # Coherence pulse snapshot every 4 hours
        self.scheduler.add_job(
            self.run_coherence_pulse,
            IntervalTrigger(hours=4),
            id="run_coherence_pulse",
            name="Generate coherence pulse snapshot and briefing",
            replace_existing=True
        )

        # Dead-man switch check every 1 hour
        self.scheduler.add_job(
            self.check_deadman_switch,
            IntervalTrigger(hours=1),
            id="check_deadman_switch",
            name="Dead-man switch: revert Fibres if no human heartbeat",
            replace_existing=True
        )

        # Escalation timeout check every 2 hours
        self.scheduler.add_job(
            self.check_approval_escalations,
            IntervalTrigger(hours=2),
            id="check_approval_escalations",
            name="Escalate unresponded proposals after timeout",
            replace_existing=True
        )

        # Nate the Nudge — proactive notifications (gated by ENABLE_NATE_NUDGE)
        if getattr(settings, "ENABLE_NATE_NUDGE", True):
            nudge_interval = getattr(settings, "NUDGE_SCHEDULER_INTERVAL_MINUTES", 30)
            self.scheduler.add_job(
                self.run_nate_nudge,
                IntervalTrigger(minutes=nudge_interval),
                id="run_nate_nudge",
                name="Generate proactive nudges (session prep, mood, milestones)",
                replace_existing=True
            )

        # Deadman Switch — silence monitoring every 4 hours
        self.scheduler.add_job(
            self.run_deadman_switch,
            IntervalTrigger(hours=4),
            id="run_deadman_switch",
            name="Check for silent clients (Deadman Switch)",
            replace_existing=True
        )

        # Trial management — sweep every hour for expired trials + nudges
        self.scheduler.add_job(
            self.sweep_trial_expirations,
            IntervalTrigger(hours=1),
            id="sweep_trial_expirations",
            name="Trial expiry sweep, grace period, conversion tracking",
            replace_existing=True
        )

        # Trial phase transition — daily at 9 AM: notify users entering Week 2 reduced access
        self.scheduler.add_job(
            self.sweep_trial_phase_transitions,
            CronTrigger(hour=9, minute=0),
            id="sweep_trial_phase_transitions",
            name="Notify trial users entering Week 2 (reduced AI access)",
            replace_existing=True
        )

        self.scheduler.start()
        print(">>> [DRIP] Scheduler started with 14 jobs")

    def shutdown(self):
        """Gracefully shut down the scheduler."""
        self.scheduler.shutdown(wait=False)
        print(">>> [DRIP] Scheduler shut down")

    # =========================================================================
    # JOB: Check Pending Drips
    # =========================================================================

    async def check_pending_drips(self):
        """Send pending drip emails where next_email_at <= now()."""
        try:
            async with self.db_pool.acquire() as conn:
                # Find prospects due for their next email
                prospects = await conn.fetch(
                    """SELECT p.*, c.name as campaign_name
                       FROM prospects p
                       JOIN campaigns c ON c.id = p.current_campaign_id
                       WHERE p.status = 'active_journey'
                         AND p.next_email_at <= NOW()
                         AND p.email_opt_out = FALSE
                         AND c.status = 'active'
                       ORDER BY p.next_email_at
                       LIMIT 100"""
                )

                sent = 0
                for prospect in prospects:
                    try:
                        # Get the current step details
                        step = await conn.fetchrow(
                            """SELECT cs.*, q.id as quiz_uuid, q.title as quiz_title
                               FROM campaign_steps cs
                               LEFT JOIN quizzes q ON q.id = cs.quiz_id
                               WHERE cs.campaign_id = $1 AND cs.step_order = $2""",
                            prospect["current_campaign_id"], prospect["current_step"]
                        )

                        if not step:
                            # No more steps — journey complete
                            await conn.execute(
                                """UPDATE prospects
                                   SET next_email_at = NULL
                                   WHERE id = $1""",
                                prospect["id"]
                            )
                            continue

                        # Send the email
                        success = await self._send_drip_email(
                            conn, prospect, step
                        )

                        if success:
                            # Calculate next email time
                            next_step = await conn.fetchrow(
                                """SELECT * FROM campaign_steps
                                   WHERE campaign_id = $1 AND step_order = $2""",
                                prospect["current_campaign_id"],
                                prospect["current_step"] + 1
                            )

                            if next_step:
                                next_at = datetime.now(timezone.utc) + timedelta(
                                    hours=next_step["delay_hours"]
                                )
                                await conn.execute(
                                    """UPDATE prospects
                                       SET current_step = current_step + 1,
                                           next_email_at = $2
                                       WHERE id = $1""",
                                    prospect["id"], next_at
                                )
                            else:
                                # No more steps
                                await conn.execute(
                                    """UPDATE prospects SET next_email_at = NULL
                                       WHERE id = $1""",
                                    prospect["id"]
                                )
                            sent += 1

                    except Exception as e:
                        print(f">>> [DRIP] Error sending to {prospect['email']}: {e}")

                if sent > 0:
                    print(f">>> [DRIP] Sent {sent} drip emails")

        except Exception as e:
            print(f">>> [DRIP] check_pending_drips error: {e}")

    # =========================================================================
    # JOB: Check SMS Fallbacks
    # =========================================================================

    async def check_sms_fallbacks(self):
        """Send SMS nudge for emails not opened after fallback delay."""
        if not self.twilio_client:
            return

        try:
            async with self.db_pool.acquire() as conn:
                # Find emails not opened within the fallback window
                threshold = datetime.now(timezone.utc) - timedelta(
                    hours=settings.DRIP_SMS_FALLBACK_DELAY_HOURS
                )

                unread = await conn.fetch(
                    """SELECT dl.*, p.phone, p.first_name, p.sms_opt_out,
                              cs.sms_enabled, cs.sms_template
                       FROM delivery_log dl
                       JOIN prospects p ON p.id = dl.prospect_id
                       LEFT JOIN campaign_steps cs ON cs.id = dl.campaign_step_id
                       WHERE dl.channel = 'email'
                         AND dl.status = 'delivered'
                         AND dl.sent_at <= $1
                         AND dl.opened_at IS NULL
                         AND p.phone IS NOT NULL
                         AND p.sms_opt_out = FALSE
                         AND cs.sms_enabled = TRUE
                         AND NOT EXISTS (
                             SELECT 1 FROM delivery_log sms
                             WHERE sms.prospect_id = dl.prospect_id
                               AND sms.channel = 'sms'
                               AND sms.campaign_step_id = dl.campaign_step_id
                         )
                       LIMIT 50""",
                    threshold
                )

                for msg in unread:
                    try:
                        sms_body = msg["sms_template"] or (
                            f"Hi {msg['first_name'] or 'there'}! "
                            f"We sent you something special. Check your email from Sovereign Sanctuary. "
                            f"Reply STOP to opt out."
                        )
                        await self._send_sms(conn, msg["prospect_id"], msg["phone"], sms_body, msg["campaign_step_id"])
                    except Exception as e:
                        print(f">>> [DRIP] SMS fallback error for {msg['prospect_id']}: {e}")

        except Exception as e:
            print(f">>> [DRIP] check_sms_fallbacks error: {e}")

    # =========================================================================
    # JOB: Golden Ticket Reminders
    # =========================================================================

    async def check_golden_ticket_reminders(self):
        """Send reminders for unredeemed Golden Tickets (Day 3 and Day 6)."""
        try:
            async with self.db_pool.acquire() as conn:
                now = datetime.now(timezone.utc)

                # Day 3 reminders
                if settings.GOLDEN_TICKET_REMINDER_DAY_3:
                    day3_prospects = await conn.fetch(
                        """SELECT * FROM prospects
                           WHERE status = 'golden_ticket_issued'
                             AND golden_ticket_redeemed_at IS NULL
                             AND golden_ticket_issued_at <= $1
                             AND golden_ticket_issued_at > $2
                             AND email_opt_out = FALSE""",
                        now - timedelta(days=3),
                        now - timedelta(days=4)
                    )

                    for p in day3_prospects:
                        # Check if we already sent a day-3 reminder
                        already_sent = await conn.fetchval(
                            """SELECT 1 FROM delivery_log
                               WHERE prospect_id = $1 AND message_type = 'ticket_reminder_day3'""",
                            p["id"]
                        )
                        if not already_sent:
                            await self._send_ticket_reminder_email(conn, p, "day3")

                # Day 6 (final) reminders
                if settings.GOLDEN_TICKET_REMINDER_DAY_6:
                    day6_prospects = await conn.fetch(
                        """SELECT * FROM prospects
                           WHERE status = 'golden_ticket_issued'
                             AND golden_ticket_redeemed_at IS NULL
                             AND golden_ticket_issued_at <= $1
                             AND golden_ticket_issued_at > $2
                             AND email_opt_out = FALSE""",
                        now - timedelta(days=6),
                        now - timedelta(days=7)
                    )

                    for p in day6_prospects:
                        already_sent = await conn.fetchval(
                            """SELECT 1 FROM delivery_log
                               WHERE prospect_id = $1 AND message_type = 'ticket_reminder_day6'""",
                            p["id"]
                        )
                        if not already_sent:
                            await self._send_ticket_reminder_email(conn, p, "day6")

        except Exception as e:
            print(f">>> [DRIP] check_golden_ticket_reminders error: {e}")

    # =========================================================================
    # JOB: Check Expired Tickets
    # =========================================================================

    async def check_expired_tickets(self):
        """Mark expired Golden Tickets as lapsed."""
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.execute(
                    """UPDATE prospects
                       SET status = 'lapsed'
                       WHERE status = 'golden_ticket_issued'
                         AND golden_ticket_redeemed_at IS NULL
                         AND golden_ticket_expires_at < NOW()"""
                )
                count = int(result.split()[-1]) if result else 0
                if count > 0:
                    print(f">>> [DRIP] Marked {count} Golden Tickets as lapsed")

        except Exception as e:
            print(f">>> [DRIP] check_expired_tickets error: {e}")

    # =========================================================================
    # JOB: Update Campaign Analytics
    # =========================================================================

    async def update_campaign_analytics(self):
        """Aggregate daily campaign analytics."""
        try:
            async with self.db_pool.acquire() as conn:
                today = datetime.now(timezone.utc).date()

                campaigns = await conn.fetch(
                    "SELECT id FROM campaigns WHERE status IN ('active', 'paused')"
                )

                for campaign in campaigns:
                    cid = campaign["id"]

                    stats = await conn.fetchrow(
                        """SELECT
                            (SELECT COUNT(*) FROM delivery_log dl
                             JOIN prospects p ON p.id = dl.prospect_id
                             WHERE p.current_campaign_id = $1 AND dl.channel = 'email'
                               AND dl.sent_at::date = $2) as emails_sent,
                            (SELECT COUNT(*) FROM delivery_log dl
                             JOIN prospects p ON p.id = dl.prospect_id
                             WHERE p.current_campaign_id = $1 AND dl.channel = 'email'
                               AND dl.status = 'delivered' AND dl.delivered_at::date = $2) as emails_delivered,
                            (SELECT COUNT(*) FROM delivery_log dl
                             JOIN prospects p ON p.id = dl.prospect_id
                             WHERE p.current_campaign_id = $1 AND dl.channel = 'email'
                               AND dl.status IN ('opened','clicked') AND dl.opened_at::date = $2) as emails_opened,
                            (SELECT COUNT(*) FROM delivery_log dl
                             JOIN prospects p ON p.id = dl.prospect_id
                             WHERE p.current_campaign_id = $1 AND dl.channel = 'email'
                               AND dl.status = 'clicked' AND dl.clicked_at::date = $2) as emails_clicked,
                            (SELECT COUNT(*) FROM delivery_log dl
                             JOIN prospects p ON p.id = dl.prospect_id
                             WHERE p.current_campaign_id = $1 AND dl.channel = 'sms'
                               AND dl.sent_at::date = $2) as sms_sent,
                            (SELECT COUNT(*) FROM quiz_responses qr
                             WHERE qr.campaign_id = $1 AND qr.completed_at::date = $2) as quizzes_completed,
                            (SELECT COUNT(*) FROM nate_insights ni
                             JOIN quiz_responses qr ON qr.quiz_id = ni.quiz_id AND qr.prospect_id = ni.prospect_id
                             WHERE qr.campaign_id = $1 AND ni.created_at::date = $2) as insights_generated""",
                        cid, today
                    )

                    if stats:
                        es = stats["emails_sent"] or 0
                        open_rate = (stats["emails_opened"] or 0) / es if es > 0 else 0
                        click_rate = (stats["emails_clicked"] or 0) / es if es > 0 else 0

                        await conn.execute(
                            """INSERT INTO campaign_analytics
                               (campaign_id, date, emails_sent, emails_delivered, emails_opened,
                                emails_clicked, sms_sent, quizzes_completed, insights_generated,
                                open_rate, click_rate)
                               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                               ON CONFLICT (campaign_id, date) DO UPDATE
                               SET emails_sent = $3, emails_delivered = $4, emails_opened = $5,
                                   emails_clicked = $6, sms_sent = $7, quizzes_completed = $8,
                                   insights_generated = $9, open_rate = $10, click_rate = $11""",
                            cid, today,
                            stats["emails_sent"] or 0,
                            stats["emails_delivered"] or 0,
                            stats["emails_opened"] or 0,
                            stats["emails_clicked"] or 0,
                            stats["sms_sent"] or 0,
                            stats["quizzes_completed"] or 0,
                            stats["insights_generated"] or 0,
                            round(open_rate, 4),
                            round(click_rate, 4)
                        )

        except Exception as e:
            print(f">>> [DRIP] update_campaign_analytics error: {e}")

    # =========================================================================
    # JOB: Approval Protocol Auto-Execute
    # =========================================================================

    async def check_approval_auto_executions(self):
        """Auto-execute low-risk strategy proposals past their window."""
        try:
            from app.services.approval_protocol import ApprovalProtocolService
            protocol = ApprovalProtocolService(self.db_pool)
            results = await protocol.check_auto_executions()
            if results:
                print(f">>> [DRIP] Auto-executed {len(results)} strategy proposals")
        except Exception as e:
            print(f">>> [DRIP] check_approval_auto_executions error: {e}")

    # =========================================================================
    # EMAIL HELPERS
    # =========================================================================

    async def _send_drip_email(self, conn, prospect, step) -> bool:
        """Send a drip email using SendGrid dynamic template or raw HTML."""
        if not self.sendgrid_client:
            print(f">>> [DRIP] SendGrid not configured, skipping email to {prospect['email']}")
            return False

        template_id = step.get("email_template_id") or self.drip_templates.get(step["step_order"], "")
        subject = step["email_subject"] or f"Day {step['step_order']} — Your Emotional Coherence Journey"
        quiz_url = ""
        if step.get("quiz_uuid"):
            quiz_url = f"https://app.sovereignsanctuary.net/quiz?token={prospect['email']}&step={step['step_order']}"

        try:
            message = Mail(
                from_email=Email(settings.FROM_EMAIL, settings.FROM_NAME),
                to_emails=To(prospect["email"])
            )

            if template_id:
                message.template_id = template_id
                message.dynamic_template_data = {
                    "first_name": prospect["first_name"] or "Friend",
                    "day_number": step["step_order"],
                    "quiz_url": quiz_url,
                    "subject": subject,
                }
            else:
                message.subject = subject
                body = step["email_body"] or f"<p>Day {step['step_order']} of your journey awaits.</p>"
                if quiz_url:
                    body += f'<p><a href="{quiz_url}">Take Today\'s Quiz</a></p>'
                message.html_content = body

            response = self.sendgrid_client.send(message)
            msg_id = response.headers.get("X-Message-Id", "")

            # Log delivery
            await conn.execute(
                """INSERT INTO delivery_log
                   (prospect_id, channel, message_type, provider_message_id, status,
                    campaign_step_id, subject, template_id)
                   VALUES ($1, 'email', $2, $3, 'sent', $4, $5, $6)""",
                prospect["id"],
                f"drip_day_{step['step_order']}",
                msg_id,
                step["id"],
                subject,
                template_id
            )

            return response.status_code in [200, 201, 202]

        except Exception as e:
            print(f">>> [DRIP] Email send error to {prospect['email']}: {e}")
            await conn.execute(
                """INSERT INTO delivery_log
                   (prospect_id, channel, message_type, status, failure_reason, campaign_step_id)
                   VALUES ($1, 'email', $2, 'failed', $3, $4)""",
                prospect["id"], f"drip_day_{step['step_order']}", str(e), step["id"]
            )
            return False

    async def _send_sms(self, conn, prospect_id, phone, body, step_id=None):
        """Send an SMS via Twilio."""
        if not self.twilio_client:
            return

        normalized = self._normalize_phone(phone)
        from_number = getattr(settings, 'TWILIO_FROM_NUMBER', '') or ''
        if not from_number:
            return

        try:
            message = self.twilio_client.messages.create(
                body=body,
                from_=from_number,
                to=normalized
            )

            await conn.execute(
                """INSERT INTO delivery_log
                   (prospect_id, channel, message_type, provider_message_id, status, campaign_step_id)
                   VALUES ($1, 'sms', 'sms_fallback', $2, 'sent', $3)""",
                prospect_id, message.sid, step_id
            )
        except Exception as e:
            print(f">>> [DRIP] SMS error to {phone}: {e}")

    async def _send_ticket_reminder_email(self, conn, prospect, reminder_type: str):
        """Send a Golden Ticket reminder email."""
        if not self.sendgrid_client:
            return

        name = prospect["first_name"] or "Friend"
        token = prospect["golden_ticket_token"]
        redemption_url = f"https://app.sovereignsanctuary.net/golden-ticket?token={token}"

        if reminder_type == "day3":
            subject = f"{name}, I still have your assessment saved..."
            body = f"""<p>Hi {name},</p>
            <p>It's Nate. Three days ago, we finished something together — five conversations that revealed patterns most people take months to see.</p>
            <p>Your coaching assessment and Golden Ticket are still waiting. Inside: your 3 personalized coaching goals and a pathway to real change.</p>
            <p><a href="{redemption_url}" style="display:inline-block;padding:12px 24px;background:#C9A962;color:#050505;text-decoration:none;border-radius:8px;font-weight:bold;">Claim Your Golden Ticket</a></p>
            <p>Warmly,<br>Little Nate</p>"""
            msg_type = "ticket_reminder_day3"
        else:
            subject = f"{name}, your Golden Ticket expires tomorrow"
            body = f"""<p>Hi {name},</p>
            <p>This is the last call. Your Golden Ticket — the one that includes your full emotional coherence assessment and a free trial — expires tomorrow.</p>
            <p>Everything we discovered together is still here: the patterns, the strengths, the growth areas. But the door is closing.</p>
            <p><a href="{redemption_url}" style="display:inline-block;padding:12px 24px;background:#C9A962;color:#050505;text-decoration:none;border-radius:8px;font-weight:bold;">Claim Before It Expires</a></p>
            <p>I'll be here either way.<br>— Nate</p>"""
            msg_type = "ticket_reminder_day6"

        try:
            message = Mail(
                from_email=Email(settings.FROM_EMAIL, settings.FROM_NAME),
                to_emails=To(prospect["email"]),
                subject=subject,
                html_content=body
            )
            response = self.sendgrid_client.send(message)
            msg_id = response.headers.get("X-Message-Id", "")

            await conn.execute(
                """INSERT INTO delivery_log
                   (prospect_id, channel, message_type, provider_message_id, status, subject)
                   VALUES ($1, 'email', $2, $3, 'sent', $4)""",
                prospect["id"], msg_type, msg_id, subject
            )
        except Exception as e:
            print(f">>> [DRIP] Ticket reminder email error for {prospect['email']}: {e}")

    # =========================================================================
    # JOB: Foresight Engine
    # =========================================================================

    async def run_foresight_engine(self):
        """Generate foresight predictions and validate past alerts."""
        try:
            from app.services.foresight_engine import ForesightEngine
            engine = ForesightEngine(db_pool=self.db_pool)
            alerts = await engine.generate_alerts()
            if alerts:
                print(f">>> [DRIP] Foresight: generated {len(alerts)} alert(s)")
            validated = await engine.validate_past_predictions()
            if validated:
                print(f">>> [DRIP] Foresight: validated {validated} past prediction(s)")
        except Exception as e:
            print(f">>> [DRIP] run_foresight_engine error: {e}")

    # =========================================================================
    # JOB: Coherence Pulse Snapshot
    # =========================================================================

    async def run_coherence_pulse(self):
        """Generate coherence pulse snapshot and store briefing."""
        try:
            from app.services.coherence_engine import CoherenceEngine
            from app.services.strategic_memory import StrategicMemoryService
            engine = CoherenceEngine(db_pool=self.db_pool)

            # Generate pulse snapshot (measures all 5 layers)
            await engine.generate_pulse_snapshot()

            # Generate and store briefing in Strategic Memory Layer 4
            briefing = await engine.generate_briefing()
            if briefing:
                memory = StrategicMemoryService(self.db_pool)
                await memory.store_coherence_briefing(briefing)
                print(">>> [DRIP] Coherence briefing stored in strategic memory")
        except Exception as e:
            print(f">>> [DRIP] run_coherence_pulse error: {e}")

    # =========================================================================
    # JOB: Dead-Man Switch
    # =========================================================================

    async def check_deadman_switch(self):
        """Check if human heartbeat is overdue; revert Fibres if triggered."""
        try:
            from app.services.approval_protocol import ApprovalProtocolService
            approval = ApprovalProtocolService(db_pool=self.db_pool)
            # Pass fibre_manager if available via app state
            fibre_manager = None
            try:
                import asyncio
                app = getattr(asyncio.get_event_loop(), '_app', None)
                if app and hasattr(app, 'state'):
                    fibre_manager = getattr(app.state, 'fibre_manager', None)
            except Exception as e:
                logger.debug("Get fibre_manager from app state: %s", e)
            result = await approval.check_deadman_switch(fibre_manager=fibre_manager)
            if result.get("triggered"):
                print(f">>> [DRIP] Dead-man switch activated! "
                      f"Reverted {result.get('fibres_reverted', 0)} Fibres")
        except Exception as e:
            print(f">>> [DRIP] check_deadman_switch error: {e}")

    # =========================================================================
    # JOB: Approval Escalation
    # =========================================================================

    async def check_approval_escalations(self):
        """Escalate proposals that have been pending too long without response."""
        try:
            from app.services.approval_protocol import ApprovalProtocolService
            approval = ApprovalProtocolService(db_pool=self.db_pool)
            escalated = await approval.check_escalation_timeouts()
            if escalated:
                print(f">>> [DRIP] Escalated {len(escalated)} overdue proposals")
        except Exception as e:
            print(f">>> [DRIP] check_approval_escalations error: {e}")

    # =========================================================================
    # JOB: Nate the Nudge — Proactive Notifications
    # =========================================================================

    async def run_nate_nudge(self):
        """Generate all proactive nudges (session prep, mood, milestones)."""
        try:
            from app.services.nate_nudge import NateNudgeService
            nudge_service = NateNudgeService(self.db_pool)
            results = await nudge_service.run_all_nudge_checks()
            total = sum(results.values())
            if total:
                print(f">>> [DRIP] Nate Nudge: generated {total} nudge(s)")
        except Exception as e:
            print(f">>> [DRIP] run_nate_nudge error: {e}")

    # =========================================================================
    # JOB: Deadman Switch — Silence Monitoring
    # =========================================================================

    async def run_deadman_switch(self):
        """Check for silent clients and fire alerts."""
        try:
            from app.services.deadman_switch import DeadmanSwitchService
            switch = DeadmanSwitchService(self.db_pool)
            result = await switch.check_all_clients()
            if result["alerts_generated"]:
                print(f">>> [DRIP] Deadman Switch: {result['alerts_generated']} alert(s) "
                      f"from {result['clients_checked']} clients checked")
        except Exception as e:
            print(f">>> [DRIP] run_deadman_switch error: {e}")

    # =========================================================================
    # JOB: Trial Expiration Sweep
    # =========================================================================

    async def sweep_trial_expirations(self):
        """
        Hourly sweep for trial management:
        1. Pre-expiry nudges at 3 days and 1 day remaining
        2. Trial expiry: set status to TRIAL_EXPIRED, zero tokens
        3. Grace period: 3 days after expiry before full downgrade
        4. Conversion tracking: log trial-to-paid transitions
        """
        from pathlib import Path as _Path

        data_dir = _Path(getattr(settings, "DATA_DIR", "/app/data"))
        registry_path = data_dir / "user_registry.json"

        if not registry_path.exists():
            return

        try:
            with open(registry_path, "r") as f:
                registry = json.load(f)
        except Exception as e:
            logger.error("Trial sweep: failed to load registry: %s", e)
            return

        now = datetime.now(timezone.utc)
        modified = False
        nudges_sent = 0
        expirations = 0
        grace_downgrades = 0
        conversions_logged = 0

        for key, entry in registry.items():
            profile = entry.get("profile", {})
            plan = (profile.get("subscription_plan") or "").upper()
            status = (profile.get("subscription_status") or "").upper()

            # Only process trial users
            if plan not in ("TRIAL", "THRESHOLD", "") or status in ("TRIAL_EXPIRED", "EXPIRED", "GRACE_EXPIRED"):
                # Check for conversion tracking: user was trial and is now paid
                if status == "ACTIVE" and profile.get("_trial_converted") is None:
                    if plan in ("STANDARD", "INNER_CHAMBER", "TOP_TIER", "SOVEREIGN_CIRCLE"):
                        trial_start = profile.get("trial_start_date") or profile.get("created_at")
                        if trial_start:
                            profile["_trial_converted"] = str(now)
                            profile["_trial_conversion_source"] = plan
                            modified = True
                            conversions_logged += 1
                            logger.info("Trial conversion: user %s -> %s", key, plan)
                continue

            # Determine trial end date
            trial_start_str = profile.get("trial_start_date") or profile.get("created_at")
            if not trial_start_str:
                continue

            try:
                trial_start = datetime.fromisoformat(str(trial_start_str).replace("Z", "+00:00").replace("+00:00", ""))
            except (ValueError, TypeError):
                continue

            trial_days = 14  # Default from PLAN_DETAILS
            trial_end = trial_start + timedelta(days=trial_days)
            days_remaining = (trial_end - now).total_seconds() / 86400

            # --- Pre-expiry nudges (3 days and 1 day) ---
            if 0.5 < days_remaining <= 3.5 and status in ("TRIAL_ACTIVE", "ACTIVE", ""):
                nudge_key = f"_trial_nudge_{'3d' if days_remaining > 1.5 else '1d'}"
                if not profile.get(nudge_key):
                    # Send Nate Nudge
                    try:
                        from app.services.nate_nudge import NateNudgeService
                        nudge_svc = NateNudgeService(self.db_pool)
                        days_label = "3 days" if days_remaining > 1.5 else "1 day"
                        user_name = profile.get("name") or profile.get("display_name") or "there"

                        async with self.db_pool.acquire() as conn:
                            await conn.execute(
                                """
                                INSERT INTO nate_nudges
                                    (user_id, nudge_type, title, content, metadata, scheduled_at)
                                VALUES ($1, 'trial_expiry', $2, $3, $4, NOW())
                                ON CONFLICT DO NOTHING
                                """,
                                profile.get("hardware_id", key),
                                f"Your trial ends in {days_label}",
                                f"Hey {user_name}, you have {days_label} left in your Threshold trial. "
                                f"Upgrade to Inner Chamber ($49/mo) or Sovereign Circle ($149/mo) "
                                f"to keep your progress and unlock full features.",
                                json.dumps({"days_remaining": round(days_remaining, 1), "nudge_type": nudge_key}),
                            )
                        profile[nudge_key] = str(now)
                        modified = True
                        nudges_sent += 1
                    except Exception as e:
                        logger.warning("Trial nudge failed for %s: %s", key, e)

                    # Also send email notification
                    try:
                        from app.services.notifications_service import EmailService
                        email_svc = EmailService()
                        user_email = profile.get("email")
                        user_name = profile.get("name") or "Friend"
                        if user_email:
                            await email_svc.send_trial_expiring(
                                user_email, user_name,
                                sessions=profile.get("session_count", 0),
                                coherence_change=profile.get("coherence_delta", "+0%"),
                                insights=profile.get("session_count", 0) * 3,
                            )
                    except Exception as e:
                        logger.warning("Trial expiry email failed for %s: %s", key, e)

            # --- Trial expired ---
            elif days_remaining <= 0 and status in ("TRIAL_ACTIVE", "ACTIVE", ""):
                profile["subscription_status"] = "TRIAL_EXPIRED"
                profile["trial_expired_at"] = str(now)
                profile["token_balance"] = 0
                profile["_grace_period_end"] = str(now + timedelta(days=3))
                modified = True
                expirations += 1

                # Send trial expired email
                try:
                    from app.services.notifications_service import EmailService
                    email_svc = EmailService()
                    user_email = profile.get("email")
                    user_name = profile.get("name") or "Friend"
                    if user_email:
                        await email_svc.send_trial_expired(user_email, user_name)
                except Exception as e:
                    logger.warning("Trial expired email failed for %s: %s", key, e)

            # --- Grace period ended (3 days after expiry) ---
            elif status == "TRIAL_EXPIRED":
                grace_end_str = profile.get("_grace_period_end")
                if grace_end_str:
                    try:
                        grace_end = datetime.fromisoformat(str(grace_end_str))
                        if now > grace_end:
                            profile["subscription_status"] = "GRACE_EXPIRED"
                            profile["subscription_plan"] = "EXPIRED"
                            profile["token_balance"] = 0
                            modified = True
                            grace_downgrades += 1
                    except (ValueError, TypeError):
                        pass

        # Save registry if modified
        if modified:
            try:
                with open(registry_path, "w") as f:
                    json.dump(registry, f, indent=2, default=str)
            except Exception as e:
                logger.error("Trial sweep: failed to save registry: %s", e)

        if nudges_sent or expirations or grace_downgrades or conversions_logged:
            print(
                f">>> [DRIP] Trial sweep: "
                f"{nudges_sent} nudge(s), {expirations} expiration(s), "
                f"{grace_downgrades} grace downgrade(s), {conversions_logged} conversion(s)"
            )

    async def sweep_trial_phase_transitions(self):
        """
        Daily sweep for users transitioning from Week 1 to Week 2 of trial.
        - Users with subscription_status = 'TRIAL_ACTIVE' and trial_start_date exactly 7 days ago
        - Send 'reduced access' notification explaining Week 2 limits
        - Include coherence upgrade prompt encouraging upgrade to Inner Chamber

        Primary: check users table (source of truth when USE_POSTGRES_REGISTRY=true).
        Fallback: also check user_registry.json for backward compatibility.
        """
        from pathlib import Path as _Path

        if not self.db_pool:
            return

        data_dir = _Path(getattr(settings, "DATA_DIR", "/app/data"))
        registry_path = data_dir / "user_registry.json"

        # Primary: check users table (source of truth)
        # Fallback: user_registry.json for backward compatibility
        registry = {}
        file_loaded_keys = set()
        if registry_path.exists():
            try:
                with open(registry_path, "r") as f:
                    registry = json.load(f)
                file_loaded_keys = set(registry.keys())
            except Exception as e:
                logger.error("Trial phase sweep: failed to load registry: %s", e)

        # Supplement from PostgreSQL: trial users not yet phase2-notified
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    rows = await conn.fetch(
                        """SELECT id, username, email, name, created_at
                           FROM users WHERE tier IN ('TRIAL', 'THRESHOLD')
                             AND subscription_status = 'TRIAL_ACTIVE'
                             AND created_at <= NOW() - INTERVAL '7 days'
                             AND NOT EXISTS (
                                 SELECT 1 FROM nate_nudges
                                 WHERE user_id = users.id AND nudge_type = 'trial_phase2'
                             )"""
                    )
                    for row in rows:
                        uid = str(row["id"])
                        if uid not in registry:
                            registry[uid] = {
                                "profile": {
                                    "hardware_id": uid,
                                    "subscription_plan": "TRIAL",
                                    "subscription_status": "TRIAL_ACTIVE",
                                    "trial_start_date": (
                                        row["created_at"].isoformat()
                                        if row["created_at"]
                                        else None
                                    ),
                                    "created_at": (
                                        row["created_at"].isoformat()
                                        if row["created_at"]
                                        else None
                                    ),
                                    "name": row.get("name"),
                                    "email": row.get("email") or row.get("username"),
                                }
                            }
            except Exception as e:
                logger.warning("Trial phase sweep: DB fallback failed: %s", e)

        if not registry:
            return

        now = datetime.now(timezone.utc)
        modified = False
        notifications_sent = 0

        for key, entry in registry.items():
            profile = entry.get("profile", {})
            status = (profile.get("subscription_status") or "").upper()
            plan = (profile.get("subscription_plan") or "").upper()

            if plan not in ("TRIAL", "THRESHOLD", "") or status != "TRIAL_ACTIVE":
                continue

            if profile.get("_trial_phase2_notified"):
                continue

            trial_start_str = profile.get("trial_start_date") or profile.get("created_at")
            if not trial_start_str:
                continue

            try:
                trial_start = datetime.fromisoformat(str(trial_start_str).replace("Z", "+00:00").replace("+00:00", ""))
            except (ValueError, TypeError):
                continue

            days_since_start = (now - trial_start).days
            # Use >= 7 so users are caught even if job runs late (day 8, 9, etc.)
            if days_since_start < 7 or profile.get("_trial_phase2_notified"):
                continue

            user_name = profile.get("name") or profile.get("display_name") or "there"
            hardware_id = profile.get("hardware_id", key)

            coherence_prompt = (
                "Upgrade to Inner Chamber ($49/mo) to keep full AI access, unlock Family Sanctuary, "
                "and continue your emotional coherence journey without limits."
            )

            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO nate_nudges
                            (user_id, nudge_type, title, content, metadata, scheduled_at)
                        VALUES ($1, 'trial_phase2', $2, $3, $4, NOW())
                        ON CONFLICT DO NOTHING
                        """,
                        hardware_id,
                        "Week 2 of your trial — reduced AI access",
                        (
                            f"Hey {user_name}, you're entering Week 2 of your Threshold trial. "
                            f"Your AI access is now limited to 30 minutes per day (down from full access). "
                            f"{coherence_prompt}"
                        ),
                        json.dumps({"phase": "gated", "day": 8}),
                    )
                profile["_trial_phase2_notified"] = str(now)
                # Only persist to registry file if entry came from file (not DB-only)
                if key in file_loaded_keys:
                    modified = True
                notifications_sent += 1
            except Exception as e:
                logger.warning("Trial phase2 nudge failed for %s: %s", key, e)

            try:
                from app.services.notifications_service import EmailService
                email_svc = EmailService()
                user_email = profile.get("email")
                if user_email:
                    await email_svc.send_trial_phase2_reduced_access(
                        user_email, user_name, coherence_prompt=coherence_prompt
                    )
            except Exception as e:
                logger.warning("Trial phase2 email failed for %s: %s", key, e)

        if modified and registry_path.exists():
            try:
                # Save only file-sourced entries (exclude DB-only synthetic entries)
                to_save = {k: v for k, v in registry.items() if k in file_loaded_keys}
                with open(registry_path, "w") as f:
                    json.dump(to_save, f, indent=2, default=str)
            except Exception as e:
                logger.error("Trial phase sweep: failed to save registry: %s", e)

        if notifications_sent:
            print(f">>> [DRIP] Trial phase sweep: {notifications_sent} Week 2 notification(s) sent")

    # ── Campaign Touchpoint Integration ──────────────────────────────

    async def send_campaign_touchpoint(self, campaign_id: int, episode: int,
                                        subject: str, body_html: str,
                                        audience: str = "all_subscribers"):
        """Send email/SMS touchpoint triggered by a campaign episode.

        Used by the session engine when a campaign's drip_touchpoints config
        indicates that an episode should trigger outbound communications.
        """
        try:
            async with self.db_pool.acquire() as conn:
                if audience == "all_subscribers":
                    subscribers = await conn.fetch("""
                        SELECT DISTINCT email, first_name, phone
                        FROM prospects
                        WHERE status IN ('subscribed', 'active', 'trial')
                          AND email IS NOT NULL
                        LIMIT 200
                    """)
                else:
                    subscribers = await conn.fetch("""
                        SELECT email, first_name, phone FROM prospects
                        WHERE id = ANY(
                            SELECT prospect_id FROM prospect_tags WHERE tag = $1
                        ) AND email IS NOT NULL
                    """, audience)

                sent_count = 0
                for sub in subscribers:
                    try:
                        if self.sendgrid_client and sub["email"]:
                            from sendgrid.helpers.mail import Mail, Email, To
                            msg = Mail(
                                from_email=Email(settings.FROM_EMAIL, settings.FROM_NAME),
                                to_emails=To(sub["email"]),
                            )
                            msg.subject = subject
                            name = sub["first_name"] or "Friend"
                            msg.html_content = body_html.replace("{{first_name}}", name)
                            response = self.sendgrid_client.send(msg)
                            if response.status_code in [200, 201, 202]:
                                sent_count += 1

                        if sub.get("phone") and self.twilio_client:
                            sms_body = f"{subject}\n{body_html[:300]}"
                            sms_body = re.sub(r'<[^>]+>', '', sms_body)
                            await self._send_sms(conn, None, sub["phone"], sms_body)

                    except Exception as e:
                        logger.warning(f"Campaign touchpoint delivery error: {e}")

                logger.info(
                    f"Campaign {campaign_id} ep{episode} touchpoint: "
                    f"{sent_count}/{len(subscribers)} emails sent"
                )
                return {"sent": sent_count, "total": len(subscribers)}

        except Exception as e:
            logger.error(f"Campaign touchpoint error: {e}")
            return {"error": str(e)}

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        """Normalize to E.164 format."""
        digits = re.sub(r'[^\d]', '', phone)
        if len(digits) == 10:
            digits = '1' + digits
        if not digits.startswith('+'):
            digits = '+' + digits
        return digits
