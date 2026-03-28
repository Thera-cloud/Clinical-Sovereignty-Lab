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

            return {
                "proposal_id": str(pid),
                "decision": decision,
                "channel": channel,
                "approval_category": approval_category,
                "approver_count": len(approver_list),
                "required_approvers": required_approvers,
                "modifier_text": parsed.get("modifier_text"),
            }

    # ─── Auto-Execute Check (called by scheduler) ───

    async def check_auto_executions(self) -> List[Dict]:
        """
        Find proposals past their auto-execute window and execute them.

        Eligible proposals:
            - SUGGEST category: auto-execute after timeout (any risk == 'low')
            - CRITICAL category: auto-execute after cooling period if fully approved
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
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM strategy_proposals
                WHERE status = 'pending_approval'
                  AND created_at < $1
                  AND (metadata->>'escalated') IS NULL
            """, cutoff)

            escalated = []
            for row in rows:
                proposal = dict(row)
                pid = proposal["proposal_id"]
                risk = proposal.get("risk", "medium")

                # Mark as escalated
                await conn.execute("""
                    UPDATE strategy_proposals
                    SET metadata = metadata || $2, updated_at = NOW()
                    WHERE proposal_id = $1
                """, pid, json.dumps({
                    "escalated": True,
                    "escalated_at": datetime.utcnow().isoformat(),
                    "escalation_reason": f"No response after {self.ESCALATION_TIMEOUT_HOURS}h",
                }))

                # Re-send notification with escalation flag
                proposal["title"] = f"[ESCALATED] {proposal['title']}"
                await self.send_email_notification(proposal)
                await self.send_sms_notification(proposal)

                escalated.append({"proposal_id": str(pid), "risk": risk})
                print(f">>> [APPROVAL] ESCALATED proposal {pid} (no response after "
                      f"{self.ESCALATION_TIMEOUT_HOURS}h)")

            return escalated
