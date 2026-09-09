"""S7 View Brief overlay — conversation_history + no payment-intent IDs."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.presession_brief_overlay import (
    merge_conversation_turns,
    overlay_presession_brief,
    sanitize_conversation_entry,
    session_summary_from_row,
    strip_payment_secrets,
)


class _AsyncCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        return False


class _MockPool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _AsyncCtx(self._conn)


def test_strip_payment_secrets_drops_nested_intent_ids():
    payload = {
        "client": {"username": "audit_client"},
        "stripe_payment_intent_id": "pi_secret",
        "recent_conversations": [
            {
                "user": "hello",
                "ai": "hi",
                "stripe_payment_intent": "pi_nested",
                "client_secret": "sec_x",
            }
        ],
        "session": {"payment_intent_id": "pi_also", "status": "scheduled"},
    }
    cleaned = strip_payment_secrets(payload)
    assert "stripe_payment_intent_id" not in cleaned
    assert "payment_intent_id" not in cleaned["session"]
    assert cleaned["session"]["status"] == "scheduled"
    turn = cleaned["recent_conversations"][0]
    assert "stripe_payment_intent" not in turn
    assert "client_secret" not in turn
    assert turn["user"] == "hello"


def test_merge_prefers_pg_and_fills_vault_gaps():
    vault = [
        {"timestamp": "2026-09-01T10:00:00", "user": "vault only", "ai": "ok"},
        {"timestamp": "2026-09-02T10:00:00", "user": "dup turn", "ai": "vault copy"},
    ]
    pg = [
        {
            "timestamp": "2026-09-02T10:00:00",
            "session_id": "SES_A",
            "user": "dup turn",
            "ai": "pg copy",
        },
        {
            "timestamp": "2026-09-03T10:00:00",
            "session_id": "SES_B",
            "user": "pg only",
            "ai": "yes",
        },
    ]
    merged = merge_conversation_turns(vault, pg, limit=25)
    users = [e["user"] for e in merged]
    assert "vault only" in users
    assert "pg only" in users
    assert users.count("dup turn") == 1
    dup = next(e for e in merged if e["user"] == "dup turn")
    assert dup["ai"] == "pg copy"


def test_sanitize_skips_empty_and_maps_user_text():
    assert sanitize_conversation_entry({"user": "", "ai": ""}) is None
    mapped = sanitize_conversation_entry(
        {"user_text": "hi", "ai_text": "there", "created_at": "2026-09-01"}
    )
    assert mapped["user"] == "hi"
    assert mapped["ai"] == "there"
    assert "stripe_payment_intent_id" not in mapped


def test_session_summary_prefers_nate_then_zoom():
    parsed = session_summary_from_row(
        {
            "session_id": "SES_1",
            "occurred_at": "2026-09-01T12:00:00+00:00",
            "nate_summary": "Client named grief.",
            "session_notes": "notes",
            "zoom_summary": "zoom",
            "stripe_payment_intent_id": "pi_must_not_copy",
        }
    )
    assert parsed["summary"] == "Client named grief."
    assert parsed["source"] == "nate_summary"
    assert "stripe_payment_intent_id" not in parsed


@pytest.mark.asyncio
async def test_overlay_queries_username_not_hardware_only():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"username": "audit_client"})
    conn.fetch = AsyncMock(
        side_effect=[
            [
                {
                    "session_id": "chat_1",
                    "user_text": "I felt unseen",
                    "ai_text": "Stay with that.",
                    "word_count_user": 3,
                    "word_count_ai": 3,
                    "created_at": "2026-09-08T16:00:00+00:00",
                }
            ],
            [
                {
                    "session_id": "SES_PRIOR",
                    "occurred_at": "2026-09-01T12:00:00+00:00",
                    "nate_summary": "Prior hour named isolation.",
                    "session_notes": "",
                    "zoom_summary": "",
                }
            ],
        ]
    )
    pool = _MockPool(conn)
    brief = {
        "recent_conversations": [],
        "stripe_payment_intent_id": "pi_leak",
        "client": {"username": "audit_client"},
    }
    with patch(
        "app.services._identity_resolver.resolve_username",
        new=AsyncMock(return_value="audit_client"),
    ):
        out = await overlay_presession_brief(
            pool,
            "audit_client_hw",
            {"username": "audit_client", "hardware_id": "audit_client_hw"},
            brief,
        )
    assert "stripe_payment_intent_id" not in out
    assert out["recent_conversations"][0]["user"] == "I felt unseen"
    assert out["prior_session_summaries"][0]["summary"] == "Prior hour named isolation."
    conv_sql = conn.fetch.await_args_list[0].args[0]
    conv_ids = conn.fetch.await_args_list[0].args[1]
    assert "conversation_history" in conv_sql
    assert "stripe_payment_intent" not in conv_sql
    assert "audit_client" in conv_ids
    sess_sql = conn.fetch.await_args_list[1].args[0]
    assert "nate_summary" in sess_sql
    assert "stripe_payment_intent" not in sess_sql
    assert "price_cents" not in sess_sql


def test_sanitize_last_session_drops_money_and_urls():
    from app.services.presession_brief_overlay import sanitize_last_session

    cleaned = sanitize_last_session(
        {
            "session_id": "SES_1",
            "status": "completed",
            "nate_summary": "Named isolation.",
            "homework_assigned": ["breathe"],
            "price_cents": 12500,
            "payment_status": "paid",
            "stripe_payment_intent_id": "pi_x",
            "recording_url": "https://zoom.example/rec",
            "zoom_host_url": "https://zoom.us/s/host",
            "session_data": {"stripe_payment_intent_id": "pi_nested"},
        }
    )
    assert cleaned["session_id"] == "SES_1"
    assert cleaned["nate_summary"] == "Named isolation."
    assert cleaned["homework_assigned"] == ["breathe"]
    assert "price_cents" not in cleaned
    assert "payment_status" not in cleaned
    assert "stripe_payment_intent_id" not in cleaned
    assert "session_data" not in cleaned
    assert "recording_url" not in cleaned
    assert "zoom_host_url" not in cleaned


@pytest.mark.asyncio
async def test_overlay_keeps_existing_conversation_topics():
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[[], []])
    pool = _MockPool(conn)
    with patch(
        "app.services._identity_resolver.resolve_username",
        new=AsyncMock(return_value="audit_client"),
    ):
        out = await overlay_presession_brief(
            pool,
            "audit_client_hw",
            {"username": "audit_client", "hardware_id": "audit_client_hw"},
            {
                "recent_conversations": [
                    {"timestamp": "2026-09-01", "user": "vault snippet", "ai": "ok"}
                ],
                "recent_conversation_topics": [
                    {"timestamp": "2026-09-01", "topic_summary": "crystal topic kept"}
                ],
            },
        )
    assert out["recent_conversation_topics"][0]["topic_summary"] == "crystal topic kept"


@pytest.mark.asyncio
async def test_overlay_session_query_includes_username():
    conn = AsyncMock()
    conn.fetch = AsyncMock(side_effect=[[], []])
    pool = _MockPool(conn)
    with patch(
        "app.services._identity_resolver.resolve_username",
        new=AsyncMock(return_value="audit_client"),
    ):
        await overlay_presession_brief(
            pool,
            "audit_client_hw",
            {"username": "audit_client", "hardware_id": "audit_client_hw"},
            {"recent_conversations": []},
        )
    sess_ids = conn.fetch.await_args_list[1].args[1]
    assert "audit_client" in sess_ids
    assert "audit_client_hw" in sess_ids


@pytest.mark.asyncio
async def test_overlay_strips_last_session_intent_when_pool_missing():
    out = await overlay_presession_brief(
        None,
        "audit_client_hw",
        {"username": "audit_client"},
        {
            "client": {
                "last_session": {
                    "status": "completed",
                    "stripe_payment_intent_id": "pi_must_not_brief",
                    "price_cents": 12500,
                    "session_data": {"stripe_payment_intent_id": "pi_nested"},
                }
            },
            "recent_conversations": [
                {"timestamp": "2026-09-01", "preview": "vault snippet", "user": ""}
            ],
        },
    )
    assert "stripe_payment_intent_id" not in out["client"]["last_session"]
    assert "price_cents" not in out["client"]["last_session"]
    assert "session_data" not in out["client"]["last_session"]
    assert out["client"]["last_session"]["status"] == "completed"
    assert out["recent_conversations"][0]["user"] == "vault snippet"


def test_sanitize_maps_vault_nate_to_ai():
    from app.services.presession_brief_overlay import sanitize_conversation_entry

    entry = sanitize_conversation_entry(
        {"timestamp": "2026-09-01", "user": "hello", "nate": "hi from vault"}
    )
    assert entry["ai"] == "hi from vault"
    assert "nate" not in entry
    assert "stripe_payment_intent" not in entry


@pytest.mark.asyncio
async def test_enrich_dual_coo_attaches_and_marks_targeted_delivered():
    from app.services.presession_brief_overlay import enrich_dual_coo_insights

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "uid": "uuid-1",
            "username": "audit_client",
            "hardware_id": "audit_client_hw",
        }
    )
    conn.fetch = AsyncMock(
        return_value=[
            {
                "id": 11,
                "source": "ceo",
                "title": "Check sleep",
                "body": "Ask about rest.",
                "created_at": None,
                "client_user_id": "audit_client",
            },
            {
                "id": 12,
                "source": "coo",
                "title": "Broadcast",
                "body": "All coaches.",
                "created_at": None,
                "client_user_id": "broadcast",
            },
        ]
    )
    conn.execute = AsyncMock()
    pool = _MockPool(conn)
    with patch("app.services.rls_context.set_rls_admin"):
        out = await enrich_dual_coo_insights(
            pool, "audit_client_hw", {"client": {"name": "Audit"}}
        )
    assert len(out["dual_coo_insights"]) == 2
    assert out["dual_coo_insights"][0]["title"] == "Check sleep"
    conn.execute.assert_awaited()
    ids = conn.execute.await_args.args[1]
    assert 11 in ids
    assert 12 not in ids

