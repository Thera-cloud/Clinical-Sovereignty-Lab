"""
LITTLE NATE — Drip Campaign Scheduler
APScheduler-based background jobs for email drips, SMS fallbacks,
and Golden Ticket lifecycle management.
"""

import json
import re
from datetime import datetime, timedelta
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

        self.scheduler.start()
        print(">>> [DRIP] Scheduler started with 6 jobs")

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
                                next_at = datetime.utcnow() + timedelta(hours=next_step["delay_hours"])
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
                threshold = datetime.utcnow() - timedelta(hours=settings.DRIP_SMS_FALLBACK_DELAY_HOURS)

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
                now = datetime.utcnow()

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
                today = datetime.utcnow().date()

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

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        """Normalize to E.164 format."""
        digits = re.sub(r'[^\d]', '', phone)
        if len(digits) == 10:
            digits = '1' + digits
        if not digits.startswith('+'):
            digits = '+' + digits
        return digits
