"""
Tests for ApprovalProtocolService — strategy proposal approval lifecycle.
"""

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
