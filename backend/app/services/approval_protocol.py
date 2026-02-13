"""
SOVEREIGN SWARM — Approval Protocol Service
Wires strategy proposals to SendGrid email + Twilio SMS notifications
with inbound reply parsing for APPROVE/HOLD/REJECT/MODIFY.

Phase 1D — integrates with existing drip_scheduler.py scheduling pattern.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.config import settings
from app.services.exceptions import (
    ApprovalTimeoutException,
    AutoExecuteBlockedException,
    ProposalNotFoundException,
    StrategyException,
)


class ApprovalProtocolService:
    """
    Manages the lifecycle of strategy proposal approvals.

    Flow:
        1. Proposal created → status = 'pending_approval'
        2. Notification sent via SendGrid + Twilio
        3. Inbound reply parsed → APPROVE / HOLD / REJECT / MODIFY
        4. If no reply and risk == 'low' → auto-execute after window
    """

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self._sendgrid_client = None
        self._twilio_client = None

    # ─── SendGrid ───

    def _get_sendgrid_client(self):
        """Lazy-load SendGrid client."""
        if not self._sendgrid_client and settings.SENDGRID_API_KEY:
            try:
                from sendgrid import SendGridAPIClient
                self._sendgrid_client = SendGridAPIClient(settings.SENDGRID_API_KEY)
            except ImportError:
                print(">>> [APPROVAL] sendgrid package not installed")
        return self._sendgrid_client

    async def send_email_notification(self, proposal: Dict[str, Any]) -> Optional[str]:
        """Send structured approval email via SendGrid."""
        sg = self._get_sendgrid_client()
        if not sg:
            print(">>> [APPROVAL] SendGrid not configured — skipping email")
            return None

        try:
            from sendgrid.helpers.mail import Mail, Email, To, Content

            risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}
            risk_display = risk_emoji.get(proposal.get("risk", "medium"), "⚪")

            subject = f"{risk_display} Sovereign Proposal: {proposal['title']}"
            body = f"""
SOVEREIGN STRATEGY PROPOSAL
{'═' * 50}

Title: {proposal['title']}
Type: {proposal.get('action_type', 'N/A')}
Risk: {proposal.get('risk', 'medium').upper()} {risk_display}
Proposed by: {proposal.get('proposed_by', 'sovereign_mind')}

{proposal.get('description', '')}

{'─' * 50}
REPLY WITH:
  APPROVE — Execute this proposal
  HOLD    — Defer for later review
  REJECT  — Cancel this proposal
  MODIFY: [your changes] — Request modifications

Auto-execute: {'Yes, in 4 hours' if proposal.get('risk') == 'low' else 'No — requires explicit approval'}
{'═' * 50}
Proposal ID: {proposal.get('proposal_id', 'N/A')}
"""

            message = Mail(
                from_email=Email(settings.FROM_EMAIL, settings.FROM_NAME),
                to_emails=To(settings.FROM_EMAIL),  # Admin email
                subject=subject,
                plain_text_content=Content("text/plain", body),
            )

            response = sg.send(message)
            msg_id = response.headers.get("X-Message-Id", "")
            print(f">>> [APPROVAL] Email sent for proposal {proposal.get('proposal_id')}: {msg_id}")
            return msg_id

        except Exception as e:
            print(f">>> [APPROVAL] Email send error: {e}")
            return None

    # ─── Twilio SMS ───

    def _get_twilio_client(self):
        """Lazy-load Twilio client."""
        if not self._twilio_client:
            try:
                twilio_sid = getattr(settings, "TWILIO_ACCOUNT_SID", "")
                twilio_token = getattr(settings, "TWILIO_AUTH_TOKEN", "")
                if twilio_sid and twilio_token:
                    from twilio.rest import Client
                    self._twilio_client = Client(twilio_sid, twilio_token)
            except ImportError:
                print(">>> [APPROVAL] twilio package not installed")
        return self._twilio_client

    async def send_sms_notification(self, proposal: Dict[str, Any]) -> Optional[str]:
        """Send 160-char approval SMS via Twilio."""
        client = self._get_twilio_client()
        twilio_from = getattr(settings, "TWILIO_FROM_NUMBER", "")
        twilio_to = getattr(settings, "TWILIO_ADMIN_NUMBER", "")

        if not client or not twilio_from or not twilio_to:
            print(">>> [APPROVAL] Twilio not configured — skipping SMS")
            return None

        try:
            risk = proposal.get("risk", "medium").upper()
            title = proposal["title"][:60]
            body = f"[SOVEREIGN] {risk} proposal: {title}. Reply APPROVE/HOLD/REJECT. ID:{str(proposal.get('proposal_id', ''))[:8]}"
            body = body[:160]

            message = client.messages.create(
                body=body,
                from_=twilio_from,
                to=twilio_to,
            )
            print(f">>> [APPROVAL] SMS sent: {message.sid}")
            return message.sid

        except Exception as e:
            print(f">>> [APPROVAL] SMS send error: {e}")
            return None

    # ─── Notification Dispatch ───

    async def notify_proposal(self, proposal_id: UUID) -> Dict[str, Any]:
        """Send both email and SMS notifications for a proposal."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM strategy_proposals WHERE proposal_id = $1",
                proposal_id,
            )
            if not row:
                raise ProposalNotFoundException(f"Proposal {proposal_id} not found")

            proposal = dict(row)

        email_id = await self.send_email_notification(proposal)
        sms_sid = await self.send_sms_notification(proposal)

        # Log notification
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE strategy_proposals
                SET status = 'pending_approval', updated_at = NOW(),
                    metadata = metadata || $2
                WHERE proposal_id = $1
            """, proposal_id, json.dumps({
                "notification_email_id": email_id,
                "notification_sms_sid": sms_sid,
                "notified_at": datetime.utcnow().isoformat(),
            }))

        return {
            "proposal_id": str(proposal_id),
            "email_sent": email_id is not None,
            "sms_sent": sms_sid is not None,
        }

    # ─── Inbound Reply Parsing ───

    @staticmethod
    def parse_reply(raw_message: str) -> Dict[str, Any]:
        """
        Parse an inbound SMS or email reply into a decision.
        Expected formats:
            APPROVE
            HOLD
            REJECT
            MODIFY: <changes>
        """
        msg = raw_message.strip().upper()

        if msg.startswith("APPROVE") or msg in ("YES", "GO", "DO IT", "SHIP IT"):
            return {"decision": "APPROVE", "modifier_text": None}
        elif msg.startswith("HOLD") or msg in ("WAIT", "DEFER", "LATER"):
            return {"decision": "HOLD", "modifier_text": None}
        elif msg.startswith("REJECT") or msg in ("NO", "CANCEL", "NOPE"):
            return {"decision": "REJECT", "modifier_text": None}
        elif msg.startswith("MODIFY"):
            changes = raw_message.strip()[len("MODIFY"):].lstrip(": ").strip()
            return {"decision": "MODIFY", "modifier_text": changes or None}
        else:
            return {"decision": "UNKNOWN", "modifier_text": raw_message.strip()}

    async def handle_inbound_reply(
        self, raw_message: str,
        channel: str = "sms",
        proposal_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Process an inbound approval reply from SMS webhook or email parse.
        If proposal_id is not provided, applies to the most recent pending proposal.
        """
        parsed = self.parse_reply(raw_message)

        async with self.db_pool.acquire() as conn:
            if proposal_id:
                row = await conn.fetchrow(
                    "SELECT * FROM strategy_proposals WHERE proposal_id = $1",
                    proposal_id,
                )
            else:
                row = await conn.fetchrow("""
                    SELECT * FROM strategy_proposals
                    WHERE status IN ('proposed', 'pending_approval')
                    ORDER BY created_at DESC LIMIT 1
                """)

            if not row:
                return {"error": "No pending proposal found", "parsed": parsed}

            proposal = dict(row)
            pid = proposal["proposal_id"]
            decision = parsed["decision"]

            if decision == "APPROVE":
                await conn.execute("""
                    UPDATE strategy_proposals
                    SET status = 'approved', approved_by = $2, approved_at = NOW(), updated_at = NOW()
                    WHERE proposal_id = $1
                """, pid, f"inbound_{channel}")
                print(f">>> [APPROVAL] Proposal {pid} APPROVED via {channel}")

            elif decision == "REJECT":
                await conn.execute("""
                    UPDATE strategy_proposals
                    SET status = 'rejected', rejection_reason = $2, updated_at = NOW()
                    WHERE proposal_id = $1
                """, pid, f"Rejected via {channel}: {raw_message}")
                print(f">>> [APPROVAL] Proposal {pid} REJECTED via {channel}")

            elif decision == "HOLD":
                await conn.execute("""
                    UPDATE strategy_proposals
                    SET metadata = metadata || $2, updated_at = NOW()
                    WHERE proposal_id = $1
                """, pid, json.dumps({"held_at": datetime.utcnow().isoformat(), "held_via": channel}))
                print(f">>> [APPROVAL] Proposal {pid} on HOLD via {channel}")

            elif decision == "MODIFY":
                await conn.execute("""
                    UPDATE strategy_proposals
                    SET metadata = metadata || $2, updated_at = NOW()
                    WHERE proposal_id = $1
                """, pid, json.dumps({
                    "modification_requested": parsed["modifier_text"],
                    "modification_via": channel,
                    "modification_at": datetime.utcnow().isoformat(),
                }))
                print(f">>> [APPROVAL] Proposal {pid} MODIFY requested via {channel}")

            return {
                "proposal_id": str(pid),
                "decision": decision,
                "channel": channel,
                "modifier_text": parsed.get("modifier_text"),
            }

    # ─── Auto-Execute Check (called by scheduler) ───

    async def check_auto_executions(self) -> List[Dict]:
        """
        Find proposals past their auto-execute window and execute them.
        Only low-risk proposals are eligible for auto-execution.
        """
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                UPDATE strategy_proposals
                SET status = 'auto_executed', executed_at = NOW(), updated_at = NOW()
                WHERE status = 'pending_approval'
                  AND auto_execute_after IS NOT NULL
                  AND auto_execute_after <= NOW()
                  AND risk = 'low'
                RETURNING *
            """)
            results = [dict(r) for r in rows]
            if results:
                print(f">>> [APPROVAL] Auto-executed {len(results)} low-risk proposals")
            return results
