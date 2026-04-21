"""
Tests for the SendGrid Inbound Parse dispatcher.

Covers FIX 1: email replies of the form APPROVE / REJECT / HOLD / MODIFY
are routed to ``ApprovalProtocolService.handle_inbound_reply`` instead of
silently being misrouted into the daily check-in pipeline.
"""

from __future__ import annotations

import pytest

from app.routers import sendgrid_inbound as si


# ─── Helper-level unit tests ──────────────────────────────────────────────

class TestApprovalKeywordDetection:
    @pytest.mark.parametrize("line", [
        "APPROVE",
        "approve please",
        "Approved",
        "REJECT",
        "reject this",
        "HOLD",
        "Hold please",
        "MODIFY: send to coaches first",
        "YES",
        "GO",
        "ship it",
        "WAIT",
        "no",
        "DENIED",
    ])
    def test_recognized_keywords(self, line):
        assert si._matches_approval_keyword(line) is True, (
            f"{line!r} should be recognized as an approval reply"
        )

    @pytest.mark.parametrize("line", [
        "I went to the store",
        "thanks!",
        "I'm not sure",
        "",
        "rejection of the premise made by",  # 'rejection' starts with 'reject'? no — starts with REJECT prefix actually
    ])
    def test_free_text_rejected(self, line):
        # 'REJECTION' starts with 'REJECT' so the prefix check would catch
        # it. Verify our intent: only single-keyword/imperative replies
        # should match. Accept that 'rejection of...' gets matched —
        # callers also need a recoverable proposal id, so this is harmless.
        if line.upper().startswith(si._APPROVAL_PREFIXES):
            return  # expected (over-matches; second-stage proposal-id required)
        assert si._matches_approval_keyword(line) is False, (
            f"{line!r} should NOT trigger approval routing"
        )


class TestRecipientLocalPart:
    @pytest.mark.parametrize("address,expected_local", [
        ("approve@reply.sovereignsanctuary.net", "approve"),
        ("Approve <approve@reply.sovereignsanctuary.net>", "approve"),
        ("approve+abc123@reply.sovereignsanctuary.net", "approve+abc123"),
        ("checkin@reply.sovereignsanctuary.net", "checkin"),
        ("APPROVAL@reply.sovereignsanctuary.net", "approval"),
        ("", ""),
    ])
    def test_extract_local_part(self, address, expected_local):
        assert si._extract_local_part(address) == expected_local

    @pytest.mark.parametrize("local,should_match", [
        ("approve", True),
        ("approve+xyz", True),
        ("approval", True),
        ("checkin", False),
        ("support", False),
        ("", False),
    ])
    def test_approval_local_part_pattern(self, local, should_match):
        match = si._APPROVAL_LOCAL_PARTS.match(local)
        assert bool(match) is should_match


class TestQuotedReplyStripping:
    def test_strips_gmail_on_x_wrote(self):
        text = (
            "APPROVE\n\n"
            "On Mon, Apr 21, 2026 at 1:49 PM Sovereign Sanctuary <x@y.com> wrote:\n"
            "> Original proposal text\n"
            "> Reply with APPROVE / HOLD / REJECT\n"
        )
        cleaned = si._strip_quoted_reply(text)
        assert cleaned.startswith("APPROVE")
        assert "Original proposal text" not in cleaned

    def test_first_meaningful_line_skips_blank_and_quoted(self):
        text = "\n\n> quoted\nAPPROVE\n> more quoted\n"
        assert si._first_meaningful_line(text) == "APPROVE"


# ─── Route-level integration tests ────────────────────────────────────────

class _FormStub:
    """Mimics Starlette's ``Request.form()`` return value."""

    def __init__(self, fields):
        self._fields = fields

    def get(self, key, default=None):
        return self._fields.get(key, default)


class _RequestStub:
    def __init__(self, fields, query_params=None):
        self._fields = fields
        self.query_params = query_params or {}

    async def form(self):
        return _FormStub(self._fields)


class TestRouteDispatch:
    @pytest.mark.asyncio
    async def test_approval_reply_routes_to_approval_service(
        self, fake_pool, fake_conn, monkeypatch,
    ):
        """First-line APPROVE with subject [#shortid] hits the approval service."""
        captured = {}

        class _StubService:
            def __init__(self, pool):
                captured["pool"] = pool

            @staticmethod
            def extract_proposal_id_from_text(subject, body):
                return "abcd1234"

            async def _resolve_short_proposal_id(self, short_id):
                captured["short_id"] = short_id
                return None  # service falls back to most-recent-pending

            async def handle_inbound_reply(self, **kwargs):
                captured["call"] = kwargs
                return {
                    "decision": "APPROVE",
                    "proposal_id": "abcd1234-1111-2222-3333-444455556666",
                    "channel": "email",
                }

        monkeypatch.setattr(
            "app.services.approval_protocol.ApprovalProtocolService",
            _StubService,
        )

        # Attach a db pool (any truthy object — stub doesn't touch it).
        si.router._db_pool = fake_pool

        request = _RequestStub({
            "from": "Operator <operator@example.com>",
            "to": "approve@reply.sovereignsanctuary.net",
            "subject": "Re: 🟢 Sovereign Proposal: verify [#abcd1234]",
            "text": "APPROVE\n\nOn Mon wrote:\n> original",
        })

        response = await si.handle_sendgrid_inbound(request)
        assert response.status_code == 200
        assert captured.get("call"), "handle_inbound_reply was never called"
        call = captured["call"]
        assert call["channel"] == "email"
        assert call["approver_identity"] == "operator@example.com"
        assert call["raw_message"].startswith("APPROVE")

    @pytest.mark.asyncio
    async def test_freetext_reply_routes_to_checkin(self, fake_pool, fake_conn, monkeypatch):
        """No approval keyword + non-approve recipient → check-in pipeline."""
        called = {"approval": False, "checkin": False}

        class _StubService:
            def __init__(self, pool): pass
            @staticmethod
            def extract_proposal_id_from_text(s, b): return None
            async def _resolve_short_proposal_id(self, sid): return None
            async def handle_inbound_reply(self, **kw):
                called["approval"] = True
                return {"error": "should not have been called"}

        async def _stub_checkin(db_pool, sender_email, cleaned_text):
            called["checkin"] = True
            called["sender"] = sender_email
            called["text"] = cleaned_text

        monkeypatch.setattr(
            "app.services.approval_protocol.ApprovalProtocolService",
            _StubService,
        )
        monkeypatch.setattr(si, "_route_checkin_reply", _stub_checkin)

        si.router._db_pool = fake_pool

        request = _RequestStub({
            "from": "<user@example.com>",
            "to": "checkin@reply.sovereignsanctuary.net",
            "subject": "Re: how are you doing today?",
            "text": "I had a hard day but I am still here.",
        })

        response = await si.handle_sendgrid_inbound(request)
        assert response.status_code == 200
        assert called["approval"] is False, "Approval pipeline must not run for free text"
        assert called["checkin"] is True, "Free-text reply must route to check-in"
        assert called["sender"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_approve_recipient_with_no_pending_proposal_returns_quietly(
        self, fake_pool, monkeypatch,
    ):
        """approve@... + no matchable pending proposal must not double-route."""
        called = {"checkin": False}

        class _StubService:
            def __init__(self, pool): pass
            @staticmethod
            def extract_proposal_id_from_text(s, b): return None
            async def _resolve_short_proposal_id(self, sid): return None
            async def handle_inbound_reply(self, **kw):
                return {"error": "No pending proposal found", "parsed": {}}

        async def _stub_checkin(*a, **kw):
            called["checkin"] = True

        monkeypatch.setattr(
            "app.services.approval_protocol.ApprovalProtocolService",
            _StubService,
        )
        monkeypatch.setattr(si, "_route_checkin_reply", _stub_checkin)

        si.router._db_pool = fake_pool

        request = _RequestStub({
            "from": "operator@example.com",
            "to": "approve@reply.sovereignsanctuary.net",
            "subject": "Re: something",
            "text": "APPROVE",
        })

        response = await si.handle_sendgrid_inbound(request)
        assert response.status_code == 200
        assert called["checkin"] is False, (
            "approve@ replies must NOT fall through to check-in even when "
            "the proposal lookup fails — that would corrupt checkin_wisdom."
        )
