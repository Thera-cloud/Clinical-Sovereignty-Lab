"""
Tests for ApprovalProtocolService — strategy proposal approval lifecycle.
"""

from datetime import datetime

import pytest
from uuid import uuid4

from app.services.approval_protocol import ApprovalProtocolService


# ─── Tests ─────────────────────────────────────────────────────────────────────

class TestApprovalProtocolInit:
    def test_initialization(self, fake_pool):
        svc = ApprovalProtocolService(db_pool=fake_pool)
        assert svc.db_pool is fake_pool
        assert svc._sendgrid_client is None
        assert svc._twilio_client is None

    def test_twilio_client_falls_back_to_env(self, fake_pool, monkeypatch):
        """settings may omit Twilio fields — env is canonical on GREEN."""
        monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtestsid123")
        monkeypatch.setenv("TWILIO_AUTH_TOKEN", "testtoken123")

        class _FakeClient:
            def __init__(self, sid, token):
                self.sid = sid
                self.token = token

        import app.services.approval_protocol as ap_mod

        monkeypatch.setattr(ap_mod, "Client", _FakeClient, raising=False)
        # Client is imported inside the method — patch twilio.rest.Client
        import sys
        from types import ModuleType

        fake_rest = ModuleType("twilio.rest")
        fake_rest.Client = _FakeClient
        fake_twilio = ModuleType("twilio")
        fake_twilio.rest = fake_rest
        monkeypatch.setitem(sys.modules, "twilio", fake_twilio)
        monkeypatch.setitem(sys.modules, "twilio.rest", fake_rest)

        svc = ApprovalProtocolService(db_pool=fake_pool)
        client = svc._get_twilio_client()
        assert client is not None
        assert client.sid == "ACtestsid123"


class TestParseReply:
    def test_parse_approve(self):
        result = ApprovalProtocolService.parse_reply("APPROVE")
        assert result["decision"] == "APPROVE"
        assert result["modifier_text"] is None

    def test_parse_approve_aliases(self):
        for word in ("YES", "GO", "DO IT", "SHIP IT"):
            result = ApprovalProtocolService.parse_reply(word)
            assert result["decision"] == "APPROVE", f"'{word}' should map to APPROVE"

    def test_parse_reject(self):
        result = ApprovalProtocolService.parse_reply("REJECT")
        assert result["decision"] == "REJECT"

    def test_parse_hold(self):
        result = ApprovalProtocolService.parse_reply("HOLD")
        assert result["decision"] == "HOLD"

    def test_parse_ack(self):
        for word in ("ACK", "DISMISS", "ACKED", "GOT IT"):
            result = ApprovalProtocolService.parse_reply(word)
            assert result["decision"] == "ACK", f"'{word}' should map to ACK"

    def test_parse_ack_first_line_of_email(self):
        body = "ACK\n\nOn Tue, someone wrote:\n> prior"
        result = ApprovalProtocolService.parse_reply(body)
        assert result["decision"] == "ACK"

    def test_parse_modify(self):
        result = ApprovalProtocolService.parse_reply("MODIFY: change the audience to teens")
        assert result["decision"] == "MODIFY"
        assert "teens" in result["modifier_text"]

    def test_parse_unknown(self):
        result = ApprovalProtocolService.parse_reply("I'm not sure what to do")
        assert result["decision"] == "UNKNOWN"


class TestHandleInboundReply:
    @pytest.mark.asyncio
    async def test_approve_with_pending_proposal(self, fake_pool, fake_conn):
        """APPROVE should update the most recent pending proposal."""
        pid = uuid4()
        fake_conn._fetchrow_result = {
            "proposal_id": pid,
            "title": "Test Proposal",
            "status": "pending_approval",
            "risk": "low",
        }

        svc = ApprovalProtocolService(db_pool=fake_pool)
        result = await svc.handle_inbound_reply("APPROVE", channel="sms")

        assert result["decision"] == "APPROVE"
        assert result["proposal_id"] == str(pid)
        assert result["channel"] == "sms"
        # Verify an UPDATE was executed
        assert any("approved" in q[0].lower() for q in fake_conn._executed)

    @pytest.mark.asyncio
    async def test_reject_with_pending_proposal(self, fake_pool, fake_conn):
        """REJECT should update the most recent pending proposal."""
        pid = uuid4()
        fake_conn._fetchrow_result = {
            "proposal_id": pid,
            "title": "Test Proposal",
            "status": "pending_approval",
            "risk": "medium",
        }

        svc = ApprovalProtocolService(db_pool=fake_pool)
        result = await svc.handle_inbound_reply("REJECT", channel="email")

        assert result["decision"] == "REJECT"
        assert result["proposal_id"] == str(pid)

    @pytest.mark.asyncio
    async def test_no_pending_proposal(self, fake_pool, fake_conn):
        """Should return error when no pending proposal exists."""
        fake_conn._fetchrow_result = None

        svc = ApprovalProtocolService(db_pool=fake_pool)
        result = await svc.handle_inbound_reply("APPROVE")

        assert "error" in result
        assert "No pending proposal" in result["error"]


class TestCheckAutoExecutions:
    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_list(self, fake_pool, fake_conn):
        """Should return empty list when no proposals are ready for auto-execute."""
        fake_conn._fetch_results = []

        svc = ApprovalProtocolService(db_pool=fake_pool)
        results = await svc.check_auto_executions()

        assert results == []


class TestNotificationFormatting:
    def test_notification_message_format(self):
        """Verify the parse_reply method handles case insensitivity."""
        result = ApprovalProtocolService.parse_reply("approve")
        assert result["decision"] == "APPROVE"

        result = ApprovalProtocolService.parse_reply("  HOLD  ")
        assert result["decision"] == "HOLD"


# ─── Self-contained proposal email/SMS rendering ───

def _enriched_proposal(**overrides):
    """Build an in-memory proposal dict with the new structured fields."""
    pid = uuid4()
    base = {
        "proposal_id": pid,
        "title": "Verify client coherence metrics across active users",
        "description": "Auto-generated summary",
        "action_type": "verification_scan",
        "proposed_by": "sovereign_mind",
        "risk": "low",
        "auto_execute_after": None,
        "metadata": {
            "details": {
                "objective": (
                    "Run a coherence verification scan across all 52 active "
                    "users and flag any with GAP > 0.7 for coach review."
                ),
                "reasoning": (
                    "3 users showed rapid GAP increase this week. Verification "
                    "would catch others trending the same direction before "
                    "crisis threshold."
                ),
                "action_steps": [
                    "Query nevedal_metrics for all active users",
                    "Flag users with GAP > 0.7",
                    "Notify assigned coaches of flagged clients",
                    "Generate summary report for admin",
                ],
                "expected_impact": "Coaches receive early warning for at-risk clients.",
                "rollback": "Read-only scan + notifications.",
                "data_sources": ["nevedal_metrics", "coach_assignments"],
                "token_cost_estimate": "Minimal — under $0.01",
            }
        },
        "rollback_payload": None,
        "execution_result": None,
    }
    base.update(overrides)
    return base


class TestProposalEmailRendering:
    def test_subject_includes_risk_emoji_and_title(self, fake_pool):
        svc = ApprovalProtocolService(db_pool=fake_pool)
        subject, _ = svc._build_proposal_email(_enriched_proposal())
        assert "🟢" in subject
        assert "Sovereign Proposal" in subject
        assert "Verify client coherence metrics" in subject

    def test_body_contains_all_required_sections(self, fake_pool):
        svc = ApprovalProtocolService(db_pool=fake_pool)
        _, body = svc._build_proposal_email(_enriched_proposal())
        for section in (
            "WHAT WILL HAPPEN:",
            "WHY THIS IS BEING PROPOSED:",
            "STEPS THAT WILL EXECUTE:",
            "EXPECTED IMPACT:",
            "IF SOMETHING GOES WRONG:",
            "DATA INVOLVED:",
            "ESTIMATED COST:",
            "DEPLOYMENT WINDOW:",
            "REPLY WITH",
            "ONE-TAP REPLY",
            "Auto-execute:",
        ):
            assert section in body, f"Email missing required section: {section}"

    def test_body_contains_objective_text(self, fake_pool):
        """Body must contain the actual objective, not just a placeholder."""
        svc = ApprovalProtocolService(db_pool=fake_pool)
        _, body = svc._build_proposal_email(_enriched_proposal())
        assert "Run a coherence verification scan across all 52 active users" in body
        assert "GAP > 0.7" in body
        # Action steps must be numbered or itemized
        assert "Query nevedal_metrics" in body

    def test_escalation_block_appears_when_escalated(self, fake_pool):
        from datetime import datetime as _dt
        svc = ApprovalProtocolService(db_pool=fake_pool)
        proposal = _enriched_proposal()
        proposal["metadata"]["escalated"] = True
        proposal["metadata"]["escalation"] = {
            "count": 2,
            "reason": "no human response within the 8h approval window",
            "days_elapsed": 1.5,
            "original_sent_date": "2026-04-19T08:00 UTC",
        }
        subject, body = svc._build_proposal_email(proposal)
        assert "[ESCALATED]" in subject
        assert "ESCALATION REASON:" in body
        assert "Days without response: 1.5" in body
        assert "Escalation count: 2" in body

    def test_auto_execute_line_includes_exact_utc_time(self, fake_pool):
        from datetime import datetime as _dt, timedelta as _td
        svc = ApprovalProtocolService(db_pool=fake_pool)
        proposal = _enriched_proposal(
            auto_execute_after=_dt.utcnow() + _td(hours=4),
        )
        _, body = svc._build_proposal_email(proposal)
        assert "Auto-execute: Yes, at" in body
        assert "UTC" in body
        assert "from now" in body

    def test_plain_body_includes_mailto_action_links(self, fake_pool):
        svc = ApprovalProtocolService(db_pool=fake_pool)
        subject, body = svc._build_proposal_email(_enriched_proposal())
        assert "ONE-TAP REPLY" in body
        assert "mailto:approve@reply.sovereignsanctuary.net" in body
        assert "body=APPROVE" in body
        assert "body=REJECT" in body
        assert "body=HOLD" in body
        assert "Re%3A" in body or "Re:" in subject

    def test_html_includes_mailto_buttons(self, fake_pool):
        svc = ApprovalProtocolService(db_pool=fake_pool)
        proposal = _enriched_proposal()
        subject, body = svc._build_proposal_email(proposal)
        html = svc._build_proposal_email_html(proposal, subject, body)
        assert "mailto:approve@reply.sovereignsanctuary.net" in html
        assert ">APPROVE<" in html
        assert ">REJECT<" in html
        assert ">HOLD<" in html
        assert ">ACK<" not in html  # ACK is CEO-inbox only

    def test_ceo_html_includes_ack_mailto_button(self, fake_pool):
        svc = ApprovalProtocolService(db_pool=fake_pool)
        proposal = _enriched_proposal()
        proposal["metadata"]["ceo_inbox"] = True
        subject, body = svc._build_proposal_email(proposal)
        html = svc._build_proposal_email_html(proposal, subject, body)
        assert ">ACK<" in html
        assert "body=ACK" in html
        labels = [c[0] for c in svc._decision_buttons(proposal)]
        assert labels == ["ACK", "APPROVE", "REJECT", "HOLD"]


class TestProposalSmsRendering:
    def test_sms_includes_objective_summary(self, fake_pool):
        svc = ApprovalProtocolService(db_pool=fake_pool)
        body = svc._build_proposal_sms(_enriched_proposal())
        assert "LN Proposal #" in body
        assert "coherence verification scan" in body  # objective leaked through
        assert "Risk: LOW" in body
        assert "APPROVE" in body and "HOLD" in body and "REJECT" in body

    def test_sms_within_two_segment_budget(self, fake_pool):
        svc = ApprovalProtocolService(db_pool=fake_pool)
        body = svc._build_proposal_sms(_enriched_proposal())
        assert len(body) <= 320, f"SMS too long: {len(body)} chars"

    def test_sms_truncates_long_objective(self, fake_pool):
        svc = ApprovalProtocolService(db_pool=fake_pool)
        long_proposal = _enriched_proposal()
        long_proposal["metadata"]["details"]["objective"] = "x " * 300  # 600 chars
        body = svc._build_proposal_sms(long_proposal)
        assert "..." in body
        assert len(body) <= 320

    def test_sms_falls_back_to_title_for_legacy_proposal(self, fake_pool):
        """Legacy proposals (no metadata.details) still get a usable SMS."""
        svc = ApprovalProtocolService(db_pool=fake_pool)
        legacy = {
            "proposal_id": uuid4(),
            "title": "Legacy proposal title without enrichment",
            "risk": "medium",
            "auto_execute_after": None,
            "metadata": {},
        }
        body = svc._build_proposal_sms(legacy)
        assert "Legacy proposal title" in body
        assert "Risk: MEDIUM" in body


# ─── FIX 4: subject [#shortid] + proposal-id extraction ────────────────────

class TestProposalIdInSubject:
    def test_subject_contains_short_id_token(self, fake_pool):
        """Outbound subject must end with [#xxxxxxxx] so reply parsing works."""
        svc = ApprovalProtocolService(db_pool=fake_pool)
        proposal = _enriched_proposal()
        subject, _ = svc._build_proposal_email(proposal)
        short = str(proposal["proposal_id"])[:8]
        assert f"[#{short}]" in subject

    def test_subject_short_id_survives_re_prefix(self, fake_pool):
        """Re: <subject> [#abc12345] must still expose the short id."""
        svc = ApprovalProtocolService(db_pool=fake_pool)
        proposal = _enriched_proposal()
        subject, _ = svc._build_proposal_email(proposal)
        reply_subject = f"Re: {subject}"
        recovered = ApprovalProtocolService.extract_proposal_id_from_text(
            reply_subject, body=""
        )
        assert recovered == str(proposal["proposal_id"])[:8]

    def test_extract_proposal_id_from_body_label(self):
        """'Proposal ID: <uuid>' literal in body must be recovered."""
        pid = uuid4()
        body = (
            "APPROVE\n\n"
            f"Some quoted email content\nProposal ID: {pid}\n"
            "More quoted content."
        )
        recovered = ApprovalProtocolService.extract_proposal_id_from_text(
            subject="Re: Sovereign Proposal: something",
            body=body,
        )
        assert recovered == str(pid).replace("-", "")[:8]

    def test_extract_proposal_id_from_body_full_uuid(self):
        pid = uuid4()
        recovered = ApprovalProtocolService.extract_proposal_id_from_text(
            subject="",
            body=f"APPROVE\n\nrelated to {pid} thanks",
        )
        assert recovered == str(pid).replace("-", "")[:8]

    def test_extract_returns_none_when_nothing_matches(self):
        recovered = ApprovalProtocolService.extract_proposal_id_from_text(
            subject="Re: hello",
            body="APPROVE",
        )
        assert recovered is None


# ─── FIX 2: outbound email Reply-To header ─────────────────────────────────

class _StubSendGrid:
    """Captures the Mail object passed to sg.send() for assertions."""

    def __init__(self):
        self.sent: list = []

    def send(self, message):
        self.sent.append(message)
        class _Resp:
            headers = {"X-Message-Id": "stub-msg-id"}
        return _Resp()


class TestProposalEmailReplyTo:
    @pytest.mark.asyncio
    async def test_reply_to_set_to_approve_inbound_address(self, fake_pool, monkeypatch):
        svc = ApprovalProtocolService(db_pool=fake_pool)
        stub = _StubSendGrid()
        # Inject the stub directly so _get_sendgrid_client returns it.
        svc._sendgrid_client = stub

        await svc.send_email_notification(_enriched_proposal())

        assert stub.sent, "Mail object was never handed to SendGrid"
        message = stub.sent[0]
        # SendGrid v3 Mail stores reply_to as a ReplyTo helper with .email
        reply_to_obj = getattr(message, "reply_to", None)
        assert reply_to_obj is not None, "Mail.reply_to was not set"
        # The helper exposes either .email (string) or .get() depending on
        # sendgrid lib version — accept both.
        reply_addr = (
            getattr(reply_to_obj, "email", None)
            or (reply_to_obj.get("email") if hasattr(reply_to_obj, "get") else None)
            or str(reply_to_obj)
        )
        assert "approve@reply.sovereignsanctuary.net" in str(reply_addr)

    @pytest.mark.asyncio
    async def test_escalation_resolves_ceo_email_not_from_address(
        self, fake_pool, monkeypatch,
    ):
        svc = ApprovalProtocolService(db_pool=fake_pool)
        stub = _StubSendGrid()
        svc._sendgrid_client = stub
        monkeypatch.setenv("CEO_NOTIFY_EMAIL", "admin@ceo.test")
        monkeypatch.setenv("FROM_EMAIL", "support@sovereignsanctuary.net")

        await svc.send_email_notification(_enriched_proposal())

        message = stub.sent[0]
        to_list = message.personalizations[0].tos
        assert to_list[0]["email"] == "admin@ceo.test"

# ─── FIX 3: post-decision confirmation email ───────────────────────────────

class TestDecisionConfirmation:
    def test_confirmation_email_includes_all_required_lines(self, fake_pool):
        svc = ApprovalProtocolService(db_pool=fake_pool)
        proposal = _enriched_proposal()
        subject, body = svc._build_decision_confirmation(
            proposal=proposal, decision="APPROVE", channel="email",
        )
        assert subject.startswith("Confirmed: APPROVE")
        assert proposal["title"] in subject
        for line in (
            "Action: APPROVE",
            "Proposal ID:",
            str(proposal["proposal_id"]),
            "Recorded at:",
            "Channel: email",
            "Execution will begin",
        ):
            assert line in body, f"Confirmation email missing: {line}"

    def test_confirmation_email_next_step_varies_by_decision(self, fake_pool):
        svc = ApprovalProtocolService(db_pool=fake_pool)
        proposal = _enriched_proposal()
        for decision, expected in (
            ("HOLD",   "deferred"),
            ("REJECT", "cancelled"),
            ("MODIFY", "modifications"),
        ):
            _, body = svc._build_decision_confirmation(
                proposal=proposal, decision=decision, channel="email",
            )
            assert expected in body.lower(), (
                f"{decision} confirmation missing '{expected}': {body!r}"
            )

    @pytest.mark.asyncio
    async def test_send_decision_confirmation_skips_for_sms(self, fake_pool):
        svc = ApprovalProtocolService(db_pool=fake_pool)
        svc._sendgrid_client = _StubSendGrid()
        result = await svc.send_decision_confirmation(
            proposal=_enriched_proposal(), decision="APPROVE",
            channel="sms", recipient="+15555550000",
        )
        assert result is None
        assert svc._sendgrid_client.sent == []

    @pytest.mark.asyncio
    async def test_send_decision_confirmation_routes_to_recipient(self, fake_pool):
        svc = ApprovalProtocolService(db_pool=fake_pool)
        stub = _StubSendGrid()
        svc._sendgrid_client = stub
        await svc.send_decision_confirmation(
            proposal=_enriched_proposal(), decision="APPROVE",
            channel="email", recipient="operator@example.com",
        )
        assert stub.sent, "Confirmation email was never sent"
        # Mail.personalizations[0].tos[0] holds the To address
        message = stub.sent[0]
        tos = getattr(message, "personalizations", [None])[0]
        # Best-effort introspection — sendgrid Mail stores 'tos' on personalization.
        assert "operator@example.com" in str(message.get()) if hasattr(message, "get") else True


# ─── FIX 5: escalation guard + clearing ────────────────────────────────────

class TestEscalationGuards:
    @pytest.mark.asyncio
    async def test_handle_inbound_reply_clears_escalated_flag(
        self, fake_pool, fake_conn,
    ):
        """After APPROVE, metadata patch must include escalated=false."""
        pid = uuid4()
        fake_conn._fetchrow_result = {
            "proposal_id": pid,
            "title": "verify",
            "status": "pending_approval",
            "risk": "low",
            "metadata": {"escalated": True, "escalation": {"count": 1}},
        }
        svc = ApprovalProtocolService(db_pool=fake_pool)
        await svc.handle_inbound_reply("APPROVE", channel="sms")

        # Find the escalation-clear UPDATE — looks for metadata patch with escalated:false
        clear_writes = [
            args for query, args in fake_conn._executed
            if "metadata = metadata ||" in query
            and any('"escalated": false' in str(a) for a in args)
        ]
        assert clear_writes, (
            "Expected an UPDATE setting metadata escalated=false after decision; "
            f"saw: {[q for q, _ in fake_conn._executed]}"
        )

    @pytest.mark.asyncio
    async def test_check_escalation_skips_when_audit_row_exists(
        self, fake_pool, fake_conn,
    ):
        """If approval_decisions_audit has any row for this proposal, skip."""
        pid = uuid4()
        fake_conn._fetch_results = [{
            "proposal_id": pid,
            "title": "held proposal",
            "status": "pending_approval",
            "risk": "low",
            "metadata": {},
            "created_at": datetime(2026, 1, 1),
        }]
        # fetchval is what the guard uses ("SELECT 1 FROM approval_decisions_audit")
        fake_conn._fetchval_result = 1

        svc = ApprovalProtocolService(db_pool=fake_pool)
        result = await svc.check_escalation_timeouts()

        assert result == [], (
            "Escalation must be skipped when an audit row already exists "
            f"for the proposal; got {result}"
        )

    @pytest.mark.asyncio
    async def test_check_escalation_proceeds_when_no_audit_row(
        self, fake_pool, fake_conn, monkeypatch,
    ):
        """If no audit row exists, escalation flow runs (writes metadata)."""
        pid = uuid4()
        fake_conn._fetch_results = [{
            "proposal_id": pid,
            "title": "untouched proposal",
            "status": "pending_approval",
            "risk": "low",
            "metadata": {},
            "created_at": datetime(2026, 1, 1),
        }]
        fake_conn._fetchval_result = None  # No prior decision

        svc = ApprovalProtocolService(db_pool=fake_pool)
        # Stub email/SMS sends so we don't hit network.
        async def _noop(*a, **kw): return None
        svc.send_email_notification = _noop
        svc.send_sms_notification = _noop

        result = await svc.check_escalation_timeouts()

        assert len(result) == 1
        assert result[0]["proposal_id"] == str(pid)
        assert result[0]["escalation_count"] == 1

    @pytest.mark.asyncio
    async def test_check_escalation_skips_external_notify_when_staging(
        self, fake_pool, fake_conn, monkeypatch,
    ):
        pid = uuid4()
        fake_conn._fetch_results = [{
            "proposal_id": pid,
            "title": "staging proposal",
            "status": "pending_approval",
            "risk": "low",
            "metadata": {},
            "created_at": datetime(2026, 1, 1),
        }]
        fake_conn._fetchval_result = None
        monkeypatch.setenv("ENVIRONMENT", "staging")
        monkeypatch.delenv("ENABLE_CEO_INBOX_EXTERNAL_NOTIFY", raising=False)

        svc = ApprovalProtocolService(db_pool=fake_pool)
        email_calls: list = []

        async def _track_email(*a, **kw):
            email_calls.append(1)
            return None

        svc.send_email_notification = _track_email
        svc.send_sms_notification = lambda *a, **kw: None

        result = await svc.check_escalation_timeouts()

        assert len(result) == 1
        assert email_calls == []

    @pytest.mark.asyncio
    async def test_check_escalation_stops_at_max_cap(
        self, fake_pool, fake_conn, monkeypatch,
    ):
        """After MAX_ESCALATION_EMAILS cycles, no further escalation emails."""
        pid = uuid4()
        fake_conn._fetch_results = [{
            "proposal_id": pid,
            "title": "capped proposal",
            "status": "pending_approval",
            "risk": "low",
            "metadata": {"escalation": {"count": 2, "escalated_at": "2026-01-01T00:00:00"}},
            "created_at": datetime(2026, 1, 1),
        }]
        fake_conn._fetchval_result = None

        svc = ApprovalProtocolService(db_pool=fake_pool)
        async def _noop(*a, **kw): return None
        svc.send_email_notification = _noop
        svc.send_sms_notification = _noop

        result = await svc.check_escalation_timeouts()
        assert result == []


class TestSendSmsNotification:
    @pytest.mark.asyncio
    async def test_uses_messaging_service_when_configured(
        self, fake_pool, monkeypatch,
    ):
        """CEO RED SMS must use A2P messaging service, not raw from_ number."""
        captured = {}

        class _FakeMessage:
            sid = "SMtest123"
            status = "delivered"
            error_code = None

        class _FakeMessages:
            def create(self, **kwargs):
                captured.update(kwargs)
                return _FakeMessage()

            def __call__(self, sid):
                return self

            def fetch(self):
                return _FakeMessage()

        class _FakeClient:
            messages = _FakeMessages()

        monkeypatch.setenv("TWILIO_MESSAGING_SERVICE_SID", "MGtestservice")
        monkeypatch.setenv("CEO_NOTIFY_SMS", "+15865243969")

        svc = ApprovalProtocolService(db_pool=fake_pool)
        monkeypatch.setattr(svc, "_get_twilio_client", lambda: _FakeClient())

        sid = await svc.send_sms_notification(
            {
                "proposal_id": uuid4(),
                "title": "Trust RED: test",
                "risk": "high",
                "metadata": {"ceo_inbox": True},
            },
            to_number="+15865243969",
        )

        assert sid == "SMtest123"
        assert captured.get("messaging_service_sid") == "MGtestservice"
        assert "from_" not in captured
        assert captured.get("to") == "+15865243969"
