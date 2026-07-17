"""
SOVEREIGN SWARM — Approval Protocol Service
Wires strategy proposals to SendGrid email + Twilio SMS notifications
with inbound reply parsing for APPROVE/HOLD/REJECT/MODIFY.

Implements the PhD-architecture 4-category approval system:
    OBSERVE  — log only, no approval needed
    SUGGEST  — auto-execute after timeout (implicit approval)
    ACT      — explicit single-party human approval
    CRITICAL — multi-party approval + cooling period + dead-man switch

Phase 1D — integrates with existing drip_scheduler.py scheduling pattern.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.config import settings
from app.models.strategy import ApprovalCategory, ProposalRisk
from app.services.exceptions import (
    ApprovalTimeoutException,
    AutoExecuteBlockedException,
    ProposalNotFoundException,
    StrategyException,
)


# ─── Category Classification Rules ───
# Maps (risk, action_type_prefix) → ApprovalCategory
# More specific rules checked first; fallback to risk-only mapping.

_RISK_TO_CATEGORY: Dict[str, ApprovalCategory] = {
    "low": ApprovalCategory.SUGGEST,
    "medium": ApprovalCategory.ACT,
    "high": ApprovalCategory.ACT,
    "critical": ApprovalCategory.CRITICAL,
}

_OBSERVE_ACTION_TYPES = frozenset({
    "log_insight", "record_metric", "update_cache", "emit_event",
})

_CRITICAL_ACTION_TYPES = frozenset({
    "delete_user_data", "modify_ethical_core", "override_standing_order",
    "mass_campaign", "fibre_prune_all", "change_subscription_tier",
})


class ApprovalProtocolService:
    """
    Manages the lifecycle of strategy proposal approvals.

    Four-category approval flow (PhD Architecture §7.3):
        OBSERVE  — Fibre logs the action; no approval gate.
        SUGGEST  — Auto-execute after timeout window (default 4h for low-risk).
        ACT      — Requires explicit human APPROVE before execution.
        CRITICAL — Requires N-of-M validators, mandatory cooling period,
                   and dead-man switch (revert to OBSERVATION if unresponsive).

    Dead-man switch:
        If no approval system interaction occurs within the configured
        watchdog window (default 24h), all Fibres are forced back to
        OBSERVATION autonomy level until a human heartbeat is received.
    """

    # Dead-man switch: hours without human activity before reverting Fibres
    DEADMAN_WINDOW_HOURS = 24
    # Default required approvers for CRITICAL proposals
    CRITICAL_REQUIRED_APPROVERS = 2
    # Mandatory cooling period (hours) after multi-party approval before execution
    CRITICAL_COOLING_HOURS = 4
    # Escalation timeout (hours) — if no response, escalate to next authority
    ESCALATION_TIMEOUT_HOURS = 8

    def __init__(self, db_pool, wisdom_mesh=None):
        self.db_pool = db_pool
        self._sendgrid_client = None
        self._twilio_client = None
        self._wisdom_mesh = wisdom_mesh  # For veto feedback to Fibres
        # Track last human interaction for dead-man switch
        self._last_human_heartbeat: datetime = datetime.utcnow()

    # ─── Category Classification ───

    @staticmethod
    def classify_category(
        risk: str,
        action_type: str,
    ) -> ApprovalCategory:
        """
        Determine the approval category for a proposal based on its risk
        level and action type.

        Classification rules:
            1. Certain action types always classify as OBSERVE (logging only).
            2. Certain action types always classify as CRITICAL regardless of risk.
            3. Otherwise, map risk → category using the standard mapping.
        """
        action_lower = action_type.lower()

        # Rule 1: Observe-only action types
        if action_lower in _OBSERVE_ACTION_TYPES:
            return ApprovalCategory.OBSERVE

        # Rule 2: Forced-critical action types
        if action_lower in _CRITICAL_ACTION_TYPES:
            return ApprovalCategory.CRITICAL

        # Rule 3: Risk-based mapping
        return _RISK_TO_CATEGORY.get(risk, ApprovalCategory.ACT)

    def configure_proposal_for_category(
        self,
        proposal: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Enrich a proposal dict with category-specific fields before persisting.

        Sets approval_category, required_approvers, cooling_period_hours,
        and auto_execute_after based on the classified category.
        """
        category = self.classify_category(
            proposal.get("risk", "medium"),
            proposal.get("action_type", ""),
        )
        proposal["approval_category"] = category.value

        if category == ApprovalCategory.OBSERVE:
            # No approval needed — mark as auto_executed immediately
            proposal["status"] = "auto_executed"
            proposal["executed_at"] = datetime.utcnow().isoformat()
            proposal["required_approvers"] = 0
            proposal["cooling_period_hours"] = 0

        elif category == ApprovalCategory.SUGGEST:
            # Auto-execute after a timeout window
            proposal["status"] = "pending_approval"
            proposal["required_approvers"] = 1
            proposal["cooling_period_hours"] = 0
            if not proposal.get("auto_execute_after"):
                proposal["auto_execute_after"] = (
                    datetime.utcnow() + timedelta(hours=4)
                ).isoformat()

        elif category == ApprovalCategory.ACT:
            # Requires explicit single-party approval
            proposal["status"] = "pending_approval"
            proposal["required_approvers"] = 1
            proposal["cooling_period_hours"] = 0
            proposal["auto_execute_after"] = None

        elif category == ApprovalCategory.CRITICAL:
            # Multi-party + cooling period
            proposal["status"] = "pending_approval"
            proposal["required_approvers"] = self.CRITICAL_REQUIRED_APPROVERS
            proposal["cooling_period_hours"] = self.CRITICAL_COOLING_HOURS
            proposal["auto_execute_after"] = None

        return proposal

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

    # ─── Helpers for self-contained proposal emails / SMS ───

    _RISK_EMOJI = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}

    # FIX 2: Inbound replies must route to SendGrid Inbound Parse, not to a
    # human-monitored mailbox. Any local-part on this host is delivered to
    # the inbound webhook by SendGrid (hostname-based routing).
    PROPOSAL_REPLY_TO = "approve@reply.sovereignsanctuary.net"

    # FIX 4: Regex for the short-id token we append to the subject line so
    # replies (which prepend "Re: ") still let us recover the proposal.
    _SUBJECT_SHORTID_RE = re.compile(r"\[#([0-9a-fA-F]{6,8})\]")
    _BODY_FULL_UUID_RE = re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
    )
    _BODY_PROPOSAL_ID_LABEL_RE = re.compile(
        r"Proposal\s*ID\s*[:#]?\s*([0-9a-fA-F-]{8,36})", re.IGNORECASE
    )

    @classmethod
    def extract_proposal_id_from_text(
        cls,
        subject: Optional[str],
        body: Optional[str],
    ) -> Optional[str]:
        """Best-effort proposal-id extraction from an inbound email/SMS.

        Order of preference (most reliable first):
            1. ``[#xxxxxxxx]`` token in the subject line (FIX 4).
            2. ``Proposal ID: <uuid>`` literal in the body.
            3. Any full UUID in the body.

        Returns the *short* (8-char) form for downstream lookup with
        ``WHERE proposal_id::text LIKE 'short%'``. Caller is responsible
        for resolving short → full UUID via the database.
        """
        for source, regex in (
            (subject or "", cls._SUBJECT_SHORTID_RE),
        ):
            m = regex.search(source)
            if m:
                return m.group(1).lower()[:8]
        for regex in (cls._BODY_PROPOSAL_ID_LABEL_RE, cls._BODY_FULL_UUID_RE):
            m = regex.search(body or "")
            if m:
                token = m.group(1) if regex is cls._BODY_PROPOSAL_ID_LABEL_RE else m.group(0)
                token = token.replace("-", "").lower()
                return token[:8] if len(token) >= 8 else None
        return None

    async def _resolve_short_proposal_id(self, short_id: str) -> Optional[UUID]:
        """Look up the full proposal UUID from an 8-char prefix."""
        if not short_id or len(short_id) < 6:
            return None
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT proposal_id FROM strategy_proposals "
                "WHERE proposal_id::text LIKE $1 || '%' "
                "ORDER BY created_at DESC LIMIT 1",
                short_id.lower(),
            )
            return row["proposal_id"] if row else None

    @staticmethod
    def _coerce_metadata(raw: Any) -> Dict[str, Any]:
        """Normalize a proposal's metadata column to a dict (it may be JSON str)."""
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw:
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def _coerce_payload(raw: Any) -> Dict[str, Any]:
        """Same normalization for rollback_payload / execution_payload."""
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw:
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    def _proposal_details(self, proposal: Dict[str, Any]) -> Dict[str, Any]:
        """Pull the structured ``details`` block out of metadata, with fallbacks
        to legacy fields so old proposals (pre-enrichment) still render
        without crashing."""
        meta = self._coerce_metadata(proposal.get("metadata"))
        details = meta.get("details") if isinstance(meta.get("details"), dict) else {}

        rollback_payload = self._coerce_payload(proposal.get("rollback_payload"))
        rollback_text = (
            details.get("rollback")
            or rollback_payload.get("description")
            or "No rollback specified"
        )

        return {
            "objective": (details.get("objective") or proposal.get("description") or "").strip()
                         or "No objective recorded — proposal predates enrichment.",
            "reasoning": (details.get("reasoning") or "").strip()
                         or "No reasoning recorded — proposal predates enrichment.",
            "action_steps": [s for s in (details.get("action_steps") or []) if s],
            "expected_impact": (details.get("expected_impact") or "").strip()
                               or "Impact not recorded.",
            "rollback": rollback_text.strip() if isinstance(rollback_text, str) else str(rollback_text),
            "deployment_window": details.get("deployment_window"),
            "data_sources": [s for s in (details.get("data_sources") or []) if s],
            "token_cost_estimate": details.get("token_cost_estimate"),
            "escalation": meta.get("escalation") if isinstance(meta.get("escalation"), dict) else None,
        }

    @staticmethod
    def _format_auto_execute_line(proposal: Dict[str, Any]) -> str:
        """Render the exact UTC time + hours_remaining for the auto-execute line."""
        auto_after = proposal.get("auto_execute_after")
        if not auto_after:
            return "No — requires explicit approval"
        if isinstance(auto_after, str):
            try:
                auto_after = datetime.fromisoformat(auto_after.replace("Z", "+00:00"))
            except ValueError:
                return f"Yes, at {auto_after}"
        # asyncpg returns aware datetimes; strip tzinfo for arithmetic with utcnow()
        if auto_after.tzinfo is not None:
            auto_after_naive = auto_after.replace(tzinfo=None)
        else:
            auto_after_naive = auto_after
        delta = auto_after_naive - datetime.utcnow()
        hours_remaining = max(0.0, delta.total_seconds() / 3600.0)
        return (
            f"Yes, at {auto_after_naive.isoformat(timespec='minutes')} UTC "
            f"({hours_remaining:.1f}h from now)"
        )

    def _build_proposal_email(
        self,
        proposal: Dict[str, Any],
    ) -> "tuple[str, str]":
        """Return ``(subject, body)`` for a self-contained proposal email.

        Includes objective, reasoning, action steps, expected impact,
        rollback, data sources, cost, and the auto-execute timer with
        an exact UTC fire time. If the proposal has been escalated, an
        ESCALATION REASON block is prepended so the operator knows why
        it landed in their inbox a second time.
        """
        risk = (proposal.get("risk") or "medium").lower()
        risk_emoji = self._RISK_EMOJI.get(risk, "⚪")
        details = self._proposal_details(proposal)

        meta = self._coerce_metadata(proposal.get("metadata"))
        escalated_flag = bool(meta.get("escalated"))
        prefix = "🚨 [ESCALATED] " if escalated_flag else ""

        # FIX 4: append the short proposal-id so reply subjects (which Gmail
        # prepends "Re: " to) still let the inbound parser recover the
        # original proposal even when no full UUID survives the quoting.
        pid_short = str(proposal.get("proposal_id", ""))[:8]
        suffix = f" [#{pid_short}]" if pid_short else ""

        subject = (
            f"{prefix}{risk_emoji} Sovereign Proposal: "
            f"{proposal['title']}{suffix}"
        )

        # Action steps — preserve any leading numbering the caller supplied,
        # otherwise number them so the operator sees an ordered checklist.
        steps = details["action_steps"]
        if steps and any(s and s[:2].rstrip(".").isdigit() for s in steps):
            steps_block = "\n".join(steps)
        elif steps:
            steps_block = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))
        else:
            steps_block = "(none provided — proposal would be rejected by current validator)"

        data_sources_line = (
            ", ".join(details["data_sources"])
            if details["data_sources"]
            else "No external data — internal analysis only"
        )
        cost_line = details["token_cost_estimate"] or "Minimal — under $0.01"
        deploy_line = details["deployment_window"] or "Immediate (subject to approval)"

        # ─── Optional escalation block (FIX 3) ───
        escalation_block = ""
        esc = details["escalation"]
        if escalated_flag and isinstance(esc, dict):
            escalation_block = (
                "ESCALATION REASON:\n"
                f"This proposal was sent {esc.get('days_elapsed', '?')} days ago "
                f"and received no response. It has been escalated because: "
                f"{esc.get('reason', 'no response within escalation window')}\n\n"
                f"Original sent: {esc.get('original_sent_date', 'unknown')}\n"
                f"Days without response: {esc.get('days_elapsed', '?')}\n"
                f"Escalation count: {esc.get('count', 1)}\n\n"
                f"{'─' * 50}\n"
            )

        if meta.get("ceo_inbox"):
            reply_block = (
                "REPLY WITH:\n"
                "  ACK      — Dismiss from CEO inbox (no clinical apply)\n"
                "  APPROVE  — Dismiss + apply linked actions (if any)\n"
                "  REJECT   — Dismiss without apply\n"
                "  HOLD     — Note + dismiss from inbox\n\n"
            )
        else:
            reply_block = (
                "REPLY WITH:\n"
                "  APPROVE  — Execute this proposal\n"
                "  HOLD     — Defer for later review\n"
                "  REJECT   — Cancel this proposal\n"
                "  MODIFY: [your changes] — Request modifications\n\n"
            )

        body = (
            "SOVEREIGN STRATEGY PROPOSAL\n"
            f"{'═' * 50}\n\n"
            f"Title: {proposal['title']}\n"
            f"Type: {proposal.get('action_type', 'N/A')} | "
            f"Risk: {risk.upper()} {risk_emoji}\n"
            f"Proposed by: {proposal.get('proposed_by', 'sovereign_mind')}\n"
            f"Proposal ID: {proposal.get('proposal_id', 'N/A')}\n\n"
            f"{'─' * 50}\n"
            f"{escalation_block}"
            "WHAT WILL HAPPEN:\n"
            f"{details['objective']}\n\n"
            "WHY THIS IS BEING PROPOSED:\n"
            f"{details['reasoning']}\n\n"
            "STEPS THAT WILL EXECUTE:\n"
            f"{steps_block}\n\n"
            "EXPECTED IMPACT:\n"
            f"{details['expected_impact']}\n\n"
            "IF SOMETHING GOES WRONG:\n"
            f"{details['rollback']}\n\n"
            "DATA INVOLVED:\n"
            f"{data_sources_line}\n\n"
            "ESTIMATED COST:\n"
            f"{cost_line}\n\n"
            "DEPLOYMENT WINDOW:\n"
            f"{deploy_line}\n\n"
            f"{'─' * 50}\n"
            f"{reply_block}"
            f"Auto-execute: {self._format_auto_execute_line(proposal)}\n"
            f"{'═' * 50}\n"
        )
        return subject, body

    async def send_email_notification(
        self, proposal: Dict[str, Any], to_email: Optional[str] = None
    ) -> Optional[str]:
        """Send a self-contained approval email via SendGrid.

        Renders objective, reasoning, action steps, expected impact,
        rollback, escalation context, and the exact auto-execute fire
        time so the operator never has to open another tool to decide.
        """
        sg = self._get_sendgrid_client()
        if not sg:
            print(">>> [APPROVAL] SendGrid not configured — skipping email")
            return None

        try:
            from sendgrid.helpers.mail import Mail, Email, To, Content

            subject, body = self._build_proposal_email(proposal)
            dest = (to_email or "").strip() or settings.FROM_EMAIL

            message = Mail(
                from_email=Email(settings.FROM_EMAIL, settings.FROM_NAME),
                to_emails=To(dest),
                subject=subject,
                plain_text_content=Content("text/plain", body),
            )
            # FIX 2: route replies to SendGrid Inbound Parse so APPROVE /
            # REJECT / HOLD / MODIFY actually reach the swarm instead of
            # bouncing into the support inbox.
            message.reply_to = Email(self.PROPOSAL_REPLY_TO)

            response = sg.send(message)
            msg_id = response.headers.get("X-Message-Id", "")
            print(f">>> [APPROVAL] Email sent for proposal {proposal.get('proposal_id')}: {msg_id}")
            return msg_id

        except Exception as e:
            print(f">>> [APPROVAL] Email send error: {e}")
            return None

    # ─── Post-execution notification (FIX 4) ───

    async def send_auto_executed_notification(
        self,
        proposal: Dict[str, Any],
    ) -> Optional[str]:
        """Send a follow-up email after a proposal auto-executed.

        Tells the operator what fired without their input, how long the
        approval window was, the result (or that the result is pending),
        and how to roll it back. Sent in addition to the original
        proposal email so the inbox tells a complete story.
        """
        sg = self._get_sendgrid_client()
        if not sg:
            print(">>> [APPROVAL] SendGrid not configured — skipping auto-execute email")
            return None

        try:
            from sendgrid.helpers.mail import Mail, Email, To, Content

            details = self._proposal_details(proposal)

            executed_at = proposal.get("executed_at") or datetime.utcnow()
            if isinstance(executed_at, str):
                try:
                    executed_at = datetime.fromisoformat(executed_at.replace("Z", "+00:00"))
                except ValueError:
                    executed_at = datetime.utcnow()
            if executed_at.tzinfo is not None:
                executed_at = executed_at.replace(tzinfo=None)

            created_at = proposal.get("created_at")
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                except ValueError:
                    created_at = None
            if isinstance(created_at, datetime) and created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)

            hours_elapsed = "?"
            if isinstance(created_at, datetime):
                hours_elapsed = f"{(executed_at - created_at).total_seconds() / 3600.0:.1f}"

            exec_result = proposal.get("execution_result")
            if isinstance(exec_result, str) and exec_result:
                try:
                    exec_result = json.loads(exec_result)
                except json.JSONDecodeError:
                    pass
            if not exec_result:
                result_block = "Pending — check Sovereign Command for details."
            elif isinstance(exec_result, dict):
                result_block = json.dumps(exec_result, indent=2, default=str)
            else:
                result_block = str(exec_result)

            subject = f"⚡ Auto-Executed: {proposal['title']}"
            body = (
                f"This proposal auto-executed at {executed_at.isoformat(timespec='minutes')} UTC "
                f"after {hours_elapsed} hours with no response.\n\n"
                "WHAT HAPPENED:\n"
                f"{details['objective']}\n\n"
                "RESULT:\n"
                f"{result_block}\n\n"
                "ROLLBACK PLAN:\n"
                f"{details['rollback']}\n\n"
                "If this was undesired, reply ROLLBACK to reverse.\n\n"
                f"Proposal ID: {proposal.get('proposal_id', 'N/A')}\n"
            )

            message = Mail(
                from_email=Email(settings.FROM_EMAIL, settings.FROM_NAME),
                to_emails=To(settings.FROM_EMAIL),
                subject=subject,
                plain_text_content=Content("text/plain", body),
            )
            # FIX 2: ROLLBACK replies must also route to the inbound webhook.
            message.reply_to = Email(self.PROPOSAL_REPLY_TO)
            response = sg.send(message)
            msg_id = response.headers.get("X-Message-Id", "")
            print(f">>> [APPROVAL] Auto-executed email sent for {proposal.get('proposal_id')}: {msg_id}")
            return msg_id

        except Exception as e:
            print(f">>> [APPROVAL] Auto-executed email send error: {e}")
            return None

    # ─── Decision confirmation (FIX 3) ───

    _DECISION_NEXT_STEP = {
        "APPROVE": "Execution will begin within the deployment window specified in the proposal.",
        "ACK":     "CEO inbox item dismissed. No clinical apply was performed.",
        "HOLD":    "Proposal deferred. Reply APPROVE when ready to proceed.",
        "REJECT":  "Proposal cancelled. No action will be taken.",
        "MODIFY":  "Your modifications have been logged. Little Nate will revise and resubmit.",
    }

    def _build_decision_confirmation(
        self,
        proposal: Dict[str, Any],
        decision: str,
        channel: str,
        recorded_at: Optional[datetime] = None,
    ) -> "tuple[str, str]":
        """Render the (subject, body) of the post-decision confirmation email.

        Closes the feedback loop: the operator who replied APPROVE / HOLD /
        REJECT / MODIFY gets a self-contained acknowledgement showing what
        was recorded, when, and what happens next.
        """
        if recorded_at is None:
            recorded_at = datetime.utcnow()
        if recorded_at.tzinfo is not None:
            recorded_at = recorded_at.replace(tzinfo=None)

        title = proposal.get("title") or "(untitled)"
        pid = proposal.get("proposal_id") or "N/A"
        next_step = self._DECISION_NEXT_STEP.get(
            decision, "Your response has been recorded."
        )

        subject = f"Confirmed: {decision} — {title}"
        body = (
            "Your response has been recorded.\n\n"
            f"Action: {decision}\n"
            f"Proposal: {title}\n"
            f"Proposal ID: {pid}\n"
            f"Recorded at: {recorded_at.isoformat(timespec='minutes')} UTC\n"
            f"Channel: {channel}\n\n"
            f"{next_step}\n"
        )
        return subject, body

    async def send_decision_confirmation(
        self,
        proposal: Dict[str, Any],
        decision: str,
        channel: str,
        recipient: Optional[str] = None,
    ) -> Optional[str]:
        """Send a confirmation email after a decision is recorded (FIX 3).

        For ``channel="email"``: routes the confirmation to ``recipient``
        (the original sender) so they see "Confirmed: APPROVE — …" land in
        their inbox right after they hit Reply. For ``channel="sms"``:
        skips email — the Twilio webhook already replies inline via TwiML.
        Returns the SendGrid X-Message-Id, or ``None`` if not sent.
        """
        if channel != "email":
            return None
        sg = self._get_sendgrid_client()
        if not sg:
            print(">>> [APPROVAL] SendGrid not configured — skipping confirmation email")
            return None

        target = (recipient or "").strip() or settings.FROM_EMAIL
        try:
            from sendgrid.helpers.mail import Mail, Email, To, Content

            subject, body = self._build_decision_confirmation(
                proposal, decision, channel
            )
            message = Mail(
                from_email=Email(settings.FROM_EMAIL, settings.FROM_NAME),
                to_emails=To(target),
                subject=subject,
                plain_text_content=Content("text/plain", body),
            )
            message.reply_to = Email(self.PROPOSAL_REPLY_TO)
            response = sg.send(message)
            msg_id = response.headers.get("X-Message-Id", "")
            print(
                f">>> [APPROVAL] Confirmation email ({decision}) sent to "
                f"{target} for {proposal.get('proposal_id')}: {msg_id}"
            )
            return msg_id
        except Exception as e:
            print(f">>> [APPROVAL] Confirmation email send error: {e}")
            return None

    # ─── Twilio SMS ───

    def _get_twilio_client(self):
        """Lazy-load Twilio client."""
        if not self._twilio_client:
            try:
                import os

                # settings may omit Twilio fields — env is canonical on GREEN
                twilio_sid = (
                    getattr(settings, "TWILIO_ACCOUNT_SID", None)
                    or os.getenv("TWILIO_ACCOUNT_SID", "")
                )
                twilio_token = (
                    getattr(settings, "TWILIO_AUTH_TOKEN", None)
                    or os.getenv("TWILIO_AUTH_TOKEN", "")
                )
                if twilio_sid and twilio_token:
                    from twilio.rest import Client
                    self._twilio_client = Client(twilio_sid, twilio_token)
            except ImportError:
                print(">>> [APPROVAL] twilio package not installed")
        return self._twilio_client

    # SMS budget: keep under two GSM-7 segments (320 chars). The objective
    # is truncated at 200 chars to leave room for risk + auto-exec line +
    # reply instructions + proposal ID.
    _SMS_MAX_LEN = 320
    _SMS_OBJECTIVE_MAX = 200

    @staticmethod
    def _sms_truncate(text: str, limit: int) -> str:
        """Truncate at a word boundary with an ellipsis if over ``limit``."""
        text = (text or "").strip()
        if len(text) <= limit:
            return text
        cut = text[:limit].rsplit(" ", 1)[0]
        return f"{cut}..."

    def _build_proposal_sms(self, proposal: Dict[str, Any]) -> str:
        """Build a self-contained SMS that fits in two segments (≤320 chars).

        Includes the proposal objective summary so the operator can decide
        without opening email. Falls back to the title for legacy
        proposals that have no enrichment metadata.
        """
        details = self._proposal_details(proposal)
        risk = (proposal.get("risk") or "medium").upper()
        pid_short = str(proposal.get("proposal_id", ""))[:8]

        # Prefer the objective; fall back to the title if it's a legacy stub.
        objective = details["objective"]
        legacy_objective = objective.startswith("No objective recorded")
        summary = self._sms_truncate(
            proposal["title"] if legacy_objective else objective,
            self._SMS_OBJECTIVE_MAX,
        )

        # Auto-exec line — keep terse for SMS.
        auto_after = proposal.get("auto_execute_after")
        if auto_after:
            if isinstance(auto_after, str):
                try:
                    auto_after = datetime.fromisoformat(auto_after.replace("Z", "+00:00"))
                except ValueError:
                    auto_after = None
            if isinstance(auto_after, datetime):
                if auto_after.tzinfo is not None:
                    auto_after = auto_after.replace(tzinfo=None)
                hrs = max(0.0, (auto_after - datetime.utcnow()).total_seconds() / 3600.0)
                auto_line = f"Auto-executes in {hrs:.1f}h."
            else:
                auto_line = "Auto-execute set."
        else:
            auto_line = "Requires explicit approval."

        meta = self._coerce_metadata(proposal.get("metadata"))
        if meta.get("ceo_inbox"):
            reply_hint = "Reply ACK, APPROVE, or REJECT. Details in email."
        else:
            reply_hint = "Reply APPROVE, HOLD, or REJECT. Full details in email."
        body = (
            f"LN Proposal #{pid_short}: {summary} "
            f"Risk: {risk}. {auto_line} "
            f"{reply_hint}"
        )

        # Final safety: hard-cap at the SMS budget to never exceed two segments.
        if len(body) > self._SMS_MAX_LEN:
            body = body[: self._SMS_MAX_LEN - 3].rstrip() + "..."
        return body

    async def send_sms_notification(
        self, proposal: Dict[str, Any], to_number: Optional[str] = None
    ) -> Optional[str]:
        """Send a self-contained approval SMS (≤2 segments / 320 chars) via Twilio."""
        import os

        client = self._get_twilio_client()
        twilio_from = (
            getattr(settings, "TWILIO_FROM_NUMBER", "")
            or os.getenv("TWILIO_FROM_NUMBER", "")
            or os.getenv("TWILIO_PHONE_NUMBER", "")
        )
        twilio_to = (
            (to_number or "").strip()
            or getattr(settings, "TWILIO_ADMIN_NUMBER", "")
            or getattr(settings, "ADMIN_ALERT_PHONE", "")
            or os.getenv("TWILIO_ADMIN_NUMBER", "")
            or os.getenv("ADMIN_ALERT_PHONE", "")
            or os.getenv("CEO_NOTIFY_SMS", "")
        )

        if not client or not twilio_from or not twilio_to:
            print(">>> [APPROVAL] Twilio not configured — skipping SMS")
            return None

        try:
            body = self._build_proposal_sms(proposal)

            message = client.messages.create(
                body=body,
                from_=twilio_from,
                to=twilio_to,
            )
            print(f">>> [APPROVAL] SMS sent ({len(body)} chars): {message.sid}")
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
            ACK / DISMISS  (CEO inbox dismiss)
            MODIFY: <changes>
        """
        # Use first meaningful line (email clients quote below)
        first = ""
        for line in (raw_message or "").splitlines():
            s = line.strip()
            if s and not s.startswith(">"):
                first = s
                break
        msg = (first or raw_message).strip().upper()

        if msg.startswith("APPROVE") or msg in ("YES", "GO", "DO IT", "SHIP IT"):
            return {"decision": "APPROVE", "modifier_text": None}
        elif msg.startswith("ACK") or msg.startswith("DISMISS") or msg in ("ACKED", "GOT IT", "SEEN"):
            return {"decision": "ACK", "modifier_text": None}
        elif msg.startswith("HOLD") or msg in ("WAIT", "DEFER", "LATER"):
            return {"decision": "HOLD", "modifier_text": None}
        elif msg.startswith("REJECT") or msg in ("NO", "CANCEL", "NOPE"):
            return {"decision": "REJECT", "modifier_text": None}
        elif msg.startswith("MODIFY"):
            changes = (first or raw_message).strip()[len("MODIFY"):].lstrip(": ").strip()
            return {"decision": "MODIFY", "modifier_text": changes or None}
        else:
            return {"decision": "UNKNOWN", "modifier_text": raw_message.strip()}

    async def handle_inbound_reply(
        self, raw_message: str,
        channel: str = "sms",
        proposal_id: Optional[UUID] = None,
        approver_identity: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process an inbound approval reply from SMS webhook or email parse.
        If proposal_id is not provided, applies to the most recent pending proposal.

        For CRITICAL proposals with multi-party approval, each approver is
        tracked individually. The proposal only reaches 'approved' status
        once the required number of distinct approvers have responded.
        """
        # Record human heartbeat for dead-man switch
        self._last_human_heartbeat = datetime.utcnow()

        parsed = self.parse_reply(raw_message)
        approver = approver_identity or f"inbound_{channel}"

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
            meta = proposal.get("metadata") or {}
            if isinstance(meta, str):
                meta = json.loads(meta)

            # Retrieve multi-party state
            approver_list = meta.get("approver_list", [])
            required_approvers = meta.get("required_approvers", 1)
            # Prefer the DB column; fall back to metadata for legacy rows
            approval_category = proposal.get("approval_category") or meta.get("approval_category", "act")

            if decision == "APPROVE":
                # Multi-party check for CRITICAL proposals
                if approval_category == ApprovalCategory.CRITICAL.value:
                    if approver not in approver_list:
                        approver_list.append(approver)
                    meta["approver_list"] = approver_list

                    if len(approver_list) >= required_approvers:
                        # All required approvers reached — approved (with cooling period)
                        cooling_hours = meta.get("cooling_period_hours", self.CRITICAL_COOLING_HOURS)
                        execute_after = datetime.utcnow() + timedelta(hours=cooling_hours)
                        await conn.execute("""
                            UPDATE strategy_proposals
                            SET status = 'approved', approved_by = $2, approved_at = NOW(),
                                auto_execute_after = $3, metadata = metadata || $4,
                                updated_at = NOW()
                            WHERE proposal_id = $1
                        """, pid, f"multi-party ({len(approver_list)}/{required_approvers})",
                            execute_after,
                            json.dumps({"approver_list": approver_list}))
                        print(f">>> [APPROVAL] CRITICAL proposal {pid} fully approved "
                              f"({len(approver_list)}/{required_approvers}), "
                              f"cooling until {execute_after.isoformat()}")
                    else:
                        # Partial approval — still waiting for more approvers
                        await conn.execute("""
                            UPDATE strategy_proposals
                            SET metadata = metadata || $2, updated_at = NOW()
                            WHERE proposal_id = $1
                        """, pid, json.dumps({
                            "approver_list": approver_list,
                            "partial_approval": f"{len(approver_list)}/{required_approvers}",
                        }))
                        print(f">>> [APPROVAL] CRITICAL proposal {pid} partial: "
                              f"{len(approver_list)}/{required_approvers}")
                else:
                    # Standard single-party approval (ACT or SUGGEST)
                    await conn.execute("""
                        UPDATE strategy_proposals
                        SET status = 'approved', approved_by = $2, approved_at = NOW(), updated_at = NOW()
                        WHERE proposal_id = $1
                    """, pid, approver)
                    print(f">>> [APPROVAL] Proposal {pid} APPROVED via {channel}")

            elif decision == "ACK":
                # CEO inbox dismiss — close proposal without clinical apply
                await conn.execute("""
                    UPDATE strategy_proposals
                    SET status = 'rejected', rejection_reason = $2, updated_at = NOW(),
                        metadata = COALESCE(metadata, '{}'::jsonb) || $3::jsonb
                    WHERE proposal_id = $1
                """, pid, f"ACK via {channel}",
                    json.dumps({"ceo_acked_at": datetime.utcnow().isoformat(), "ceo_acked_via": channel}))
                print(f">>> [APPROVAL] Proposal {pid} ACK (CEO dismiss) via {channel}")

            elif decision == "REJECT":
                rejection_reason = f"Rejected via {channel}: {raw_message}"
                await conn.execute("""
                    UPDATE strategy_proposals
                    SET status = 'rejected', rejection_reason = $2, updated_at = NOW()
                    WHERE proposal_id = $1
                """, pid, rejection_reason)
                print(f">>> [APPROVAL] Proposal {pid} REJECTED via {channel}")

                # PhD Spec §10.3: Push rejection reason back to proposing Fibre via Mesh
                if self._wisdom_mesh and proposal.get("proposed_by"):
                    try:
                        from uuid import uuid4 as _uuid4
                        from app.services.wisdom_mesh import MeshMessage
                        veto_msg = MeshMessage(
                            message_id=_uuid4(),
                            sender_id=_uuid4(),  # System sender
                            body=json.dumps({
                                "type": "proposal_rejected",
                                "proposal_id": str(pid),
                                "rejection_reason": rejection_reason,
                                "channel": channel,
                                "timestamp": datetime.utcnow().isoformat(),
                            }),
                            tier="strategic",
                            domain_tags=["approval", "veto_feedback"],
                            priority=8,
                        )
                        await self._wisdom_mesh.send_message(veto_msg)
                    except Exception as veto_err:
                        print(f">>> [APPROVAL] Veto feedback via Mesh failed: {veto_err}")

            elif decision == "HOLD":
                hold_meta = {"held_at": datetime.utcnow().isoformat(), "held_via": channel}
                if meta.get("ceo_inbox"):
                    # CEO HOLD = note + dismiss inbox (close proposal to stop escalation)
                    await conn.execute("""
                        UPDATE strategy_proposals
                        SET status = 'rejected', rejection_reason = $2,
                            metadata = COALESCE(metadata, '{}'::jsonb) || $3::jsonb,
                            updated_at = NOW()
                        WHERE proposal_id = $1
                    """, pid, f"HOLD via {channel}", json.dumps(hold_meta))
                else:
                    await conn.execute("""
                        UPDATE strategy_proposals
                        SET metadata = metadata || $2, updated_at = NOW()
                        WHERE proposal_id = $1
                    """, pid, json.dumps(hold_meta))
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

            # PhD Spec §10.4: Immutable approval-decisions audit trail
            await conn.execute("""
                INSERT INTO approval_decisions_audit
                    (proposal_id, decision, channel, approver, approval_category,
                     raw_message, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """, pid, decision, channel, approver,
                 approval_category,
                 raw_message[:1000] if raw_message else "",
                 json.dumps({
                     "approver_count": len(approver_list),
                     "required_approvers": required_approvers,
                     "modifier_text": parsed.get("modifier_text"),
                 }))

            # FIX 5: clear escalation flags on any recognized decision so the
            # next scheduler tick won't re-fire an escalation email for a
            # proposal the operator already responded to (especially HOLD,
            # which keeps status='pending_approval').
            if decision in ("APPROVE", "REJECT", "HOLD", "MODIFY", "ACK"):
                await conn.execute("""
                    UPDATE strategy_proposals
                    SET metadata = metadata || $2, updated_at = NOW()
                    WHERE proposal_id = $1
                """, pid, json.dumps({
                    "escalated": False,
                    "escalation_cleared_at": datetime.utcnow().isoformat(),
                    "escalation_cleared_by_decision": decision,
                }))

        # Dual-COO CEO inbox: ACK/APPROVE/REJECT/HOLD also clear Redis inbox
        ceo_side: Dict[str, Any] = {}
        if decision in ("ACK", "APPROVE", "REJECT", "HOLD") and meta.get("ceo_inbox"):
            try:
                from app.services.ceo_inbox_notify import handle_ceo_decision

                ceo_side = await handle_ceo_decision(
                    db_pool=self.db_pool,
                    proposal=proposal,
                    decision=decision,
                    channel=channel,
                    approver=approver,
                )
            except Exception as e:
                print(f">>> [APPROVAL] CEO inbox side-effect failed: {e}")
                ceo_side = {"status": "error", "error": str(e)[:200]}

        # FIX 3: send post-decision confirmation back to the operator who
        # replied. Only for email channel — SMS already gets inline TwiML.
        if decision in ("APPROVE", "REJECT", "HOLD", "MODIFY", "ACK") and channel == "email":
            try:
                await self.send_decision_confirmation(
                    proposal=proposal,
                    decision=decision,
                    channel=channel,
                    recipient=approver_identity,
                )
            except Exception as e:
                print(f">>> [APPROVAL] Confirmation email dispatch failed: {e}")

        return {
            "proposal_id": str(pid),
            "decision": decision,
            "channel": channel,
            "approval_category": approval_category,
            "approver_count": len(approver_list),
            "required_approvers": required_approvers,
            "modifier_text": parsed.get("modifier_text"),
            "ceo_inbox": ceo_side,
        }

    # ─── Auto-Execute Check (called by scheduler) ───

    async def check_auto_executions(self) -> List[Dict]:
        """
        Find proposals past their auto-execute window and execute them.

        Eligible proposals:
            - SUGGEST category: auto-execute after timeout (LOW risk only —
              MEDIUM/HIGH/CRITICAL are gated to explicit approval upstream
              in ``configure_proposal_for_category`` and validated again
              here via the ``risk = 'low'`` clause).
            - CRITICAL category: auto-execute after cooling period if fully approved

        After execution, sends a follow-up "Auto-Executed" email per row so
        the operator sees what fired without their input.
        """
        async with self.db_pool.acquire() as conn:
            # SUGGEST / low-risk auto-execute
            rows_suggest = await conn.fetch("""
                UPDATE strategy_proposals
                SET status = 'auto_executed', executed_at = NOW(), updated_at = NOW()
                WHERE status = 'pending_approval'
                  AND auto_execute_after IS NOT NULL
                  AND auto_execute_after <= NOW()
                  AND risk = 'low'
                RETURNING *
            """)

            # CRITICAL approved proposals past their cooling period
            rows_critical = await conn.fetch("""
                UPDATE strategy_proposals
                SET status = 'auto_executed', executed_at = NOW(), updated_at = NOW()
                WHERE status = 'approved'
                  AND auto_execute_after IS NOT NULL
                  AND auto_execute_after <= NOW()
                RETURNING *
            """)

            results = [dict(r) for r in rows_suggest] + [dict(r) for r in rows_critical]
            if results:
                print(f">>> [APPROVAL] Auto-executed {len(results)} proposals "
                      f"({len(rows_suggest)} suggest, {len(rows_critical)} critical-cooled)")

        # Follow-up notifications outside the DB transaction so a SendGrid
        # outage cannot block subsequent auto-executions.
        for proposal in results:
            try:
                await self.send_auto_executed_notification(proposal)
            except Exception as e:
                print(f">>> [APPROVAL] Auto-execute follow-up email failed for "
                      f"{proposal.get('proposal_id')}: {e}")
        return results

    # ─── Dead-Man Switch ───

    def record_human_heartbeat(self) -> None:
        """Record a human interaction to keep the dead-man switch alive."""
        self._last_human_heartbeat = datetime.utcnow()

    async def check_deadman_switch(self, fibre_manager=None) -> Dict[str, Any]:
        """
        Dead-man switch: if no human heartbeat has been received within
        DEADMAN_WINDOW_HOURS, revert all Fibres to OBSERVATION autonomy level.

        This ensures the swarm cannot operate autonomously indefinitely
        without human oversight. Called by the scheduler.

        Returns:
            Dict with deadman status and any actions taken.
        """
        now = datetime.utcnow()
        elapsed = now - self._last_human_heartbeat
        elapsed_hours = elapsed.total_seconds() / 3600.0

        result = {
            "last_heartbeat": self._last_human_heartbeat.isoformat(),
            "hours_since_heartbeat": round(elapsed_hours, 2),
            "threshold_hours": self.DEADMAN_WINDOW_HOURS,
            "triggered": False,
            "fibres_reverted": 0,
        }

        if elapsed_hours >= self.DEADMAN_WINDOW_HOURS:
            result["triggered"] = True
            print(f">>> [DEADMAN] ⚠ Dead-man switch TRIGGERED — "
                  f"{elapsed_hours:.1f}h without human heartbeat. "
                  f"Reverting all Fibres to OBSERVATION.")

            if fibre_manager:
                try:
                    from app.models.fibre import AutonomyLevel
                    reverted = 0
                    for fid, fibre in fibre_manager._active_fibres.items():
                        if hasattr(fibre, '_autonomy_level') and \
                                fibre._autonomy_level != AutonomyLevel.OBSERVATION:
                            fibre._autonomy_level = AutonomyLevel.OBSERVATION
                            reverted += 1
                    result["fibres_reverted"] = reverted
                    print(f">>> [DEADMAN] Reverted {reverted} Fibres to OBSERVATION")
                except Exception as e:
                    print(f">>> [DEADMAN] Error reverting Fibres: {e}")
                    result["error"] = str(e)

            # Also log to the ethical audit trail
            # Schema: ethical_audit_log(fibre_id, check_type, passed, scores, details)
            # fibre_id is nullable FK; use NULL for system-level events
            if self.db_pool:
                try:
                    async with self.db_pool.acquire() as conn:
                        await conn.execute("""
                            INSERT INTO ethical_audit_log
                                (fibre_id, check_type, passed, scores, details)
                            VALUES (NULL, 'deadman_switch_triggered', FALSE, '{}'::jsonb, $1)
                        """, json.dumps(result))
                except Exception as e:
                    print(f">>> [DEADMAN] Failed to log audit: {e}")

        return result

    # ─── Escalation Check ───

    async def check_escalation_timeouts(self) -> List[Dict]:
        """
        Find proposals that have been pending_approval longer than
        ESCALATION_TIMEOUT_HOURS and flag them for escalation.

        For CRITICAL proposals, this means re-notifying at higher urgency.
        For ACT proposals, this means sending a reminder.
        """
        cutoff = datetime.utcnow() - timedelta(hours=self.ESCALATION_TIMEOUT_HOURS)
        now = datetime.utcnow()
        async with self.db_pool.acquire() as conn:
            # Re-escalate proposals that were already escalated once but
            # have lingered another full window without a response.
            rows = await conn.fetch("""
                SELECT * FROM strategy_proposals
                WHERE status = 'pending_approval'
                  AND created_at < $1
            """, cutoff)

            escalated = []
            for row in rows:
                proposal = dict(row)
                pid = proposal["proposal_id"]
                risk = proposal.get("risk", "medium")

                # FIX 5: if an audit row already exists for this proposal,
                # the operator HAS responded (APPROVE / REJECT / HOLD /
                # MODIFY). Do not escalate — even a HOLD is an explicit
                # "I see this, leaving it parked" response.
                already_decided = await conn.fetchval(
                    "SELECT 1 FROM approval_decisions_audit "
                    "WHERE proposal_id = $1 LIMIT 1",
                    pid,
                )
                if already_decided:
                    print(
                        f">>> [APPROVAL] Skipping escalation for {pid} — "
                        f"operator already responded (audit row exists)"
                    )
                    continue

                meta = self._coerce_metadata(proposal.get("metadata"))
                prior = meta.get("escalation") if isinstance(meta.get("escalation"), dict) else {}
                prior_count = int(prior.get("count") or 0)
                last_escalated_at = prior.get("escalated_at")

                # Skip if we just escalated this one within the current window
                # (otherwise every scheduler tick would re-fire).
                if last_escalated_at:
                    try:
                        last_dt = datetime.fromisoformat(
                            last_escalated_at.replace("Z", "+00:00")
                        )
                        if last_dt.tzinfo is not None:
                            last_dt = last_dt.replace(tzinfo=None)
                        if (now - last_dt).total_seconds() < self.ESCALATION_TIMEOUT_HOURS * 3600:
                            continue
                    except (ValueError, AttributeError):
                        pass

                # ─── Build escalation context for the email template (FIX 3) ───
                created_at = proposal.get("created_at")
                if isinstance(created_at, str):
                    try:
                        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    except ValueError:
                        created_at = None
                if isinstance(created_at, datetime) and created_at.tzinfo is not None:
                    created_at = created_at.replace(tzinfo=None)

                if isinstance(created_at, datetime):
                    days_elapsed = round((now - created_at).total_seconds() / 86400.0, 2)
                    original_sent = created_at.isoformat(timespec="minutes") + " UTC"
                else:
                    days_elapsed = None
                    original_sent = "unknown"

                escalation_block = {
                    "escalated": True,
                    "count": prior_count + 1,
                    "escalated_at": now.isoformat(),
                    "reason": (
                        f"no human response within the {self.ESCALATION_TIMEOUT_HOURS}h "
                        f"approval window"
                    ),
                    "days_elapsed": days_elapsed,
                    "original_sent_date": original_sent,
                }

                await conn.execute("""
                    UPDATE strategy_proposals
                    SET metadata = metadata || $2, updated_at = NOW()
                    WHERE proposal_id = $1
                """, pid, json.dumps({
                    # Top-level mirrors for backwards compat with old SQL queries
                    "escalated": True,
                    "escalated_at": now.isoformat(),
                    "escalation_reason": escalation_block["reason"],
                    # Structured block consumed by the email template (FIX 3)
                    "escalation": escalation_block,
                }))

                # Re-render with the freshly-stored escalation metadata so the
                # email shows the new ESCALATION REASON block.
                proposal["metadata"] = {**meta, "escalated": True, "escalation": escalation_block}
                await self.send_email_notification(proposal)
                await self.send_sms_notification(proposal)

                escalated.append({
                    "proposal_id": str(pid),
                    "risk": risk,
                    "escalation_count": escalation_block["count"],
                    "days_elapsed": days_elapsed,
                })
                print(f">>> [APPROVAL] ESCALATED proposal {pid} "
                      f"(count={escalation_block['count']}, "
                      f"days_elapsed={days_elapsed})")

            return escalated
