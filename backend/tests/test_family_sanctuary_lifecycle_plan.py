"""
Family Sanctuary lifecycle validation pack (Phases 1-9).

Purpose:
- Automate what is safely testable in CI/local without mutating production accounts.
- Keep privacy and data-boundary invariants as hard checks.
- Leave Stripe/Twilio UX flows to manual execution checklist.

Live mode:
- Set FAMILY_SANCTUARY_LIVE_TEST=1 and DATABASE_URL to run DB presence checks.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "app" / "websocket" / "bridge_server.py"
INFER = ROOT / "app" / "services" / "littlenate_inference.py"
VOICE = ROOT / "app" / "services" / "twilio_grok_xtts_pipeline.py"
CLIENT_DATA = ROOT / "app" / "routers" / "client_data_api.py"
BILLING = ROOT / "app" / "routers" / "billing.py"
ADMIN = ROOT / "app" / "routers" / "admin.py"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Phase 1: Creation / merge safety
# ---------------------------------------------------------------------------


def test_phase1_merge_handlers_exist():
    s = _text(BRIDGE)
    assert 'elif t == "admin_merge_families":' in s
    assert 'elif t == "admin_unmerge_family_member":' in s
    assert 'elif t == "admin_preview_merge":' in s


def test_phase1_merge_preserves_history_and_crystal_data_contract():
    s = _text(BRIDGE)
    merge_idx = s.find('elif t == "admin_merge_families":')
    assert merge_idx > 0
    tail = s[merge_idx: merge_idx + 12000]

    # Merge metadata is tracked for reversibility.
    assert 'p["merged_from_family"]' in tail
    assert 'p["merged_at"]' in tail
    assert 'spouse_profile["merged_from_family"]' in tail

    # No destructive deletion of user crystals/conversation in merge path.
    assert "DELETE FROM nate_intelligence_crystals" not in tail
    assert "DELETE FROM conversation_history" not in tail


# ---------------------------------------------------------------------------
# Phase 2 + 8: Individual privacy + quantum recall scope
# ---------------------------------------------------------------------------


def test_phase2_individual_recall_scope_is_user_bound():
    s = _text(INFER)
    assert "semantic_search_all(query, user_id, top_k=15)" in s
    assert "reinforce_and_log_recall_hits(" in s
    assert "user_id=user_id" in s
    assert "record_co_activation_from_hits(" in s

    # Family-wide context should not be used in crystal recall here.
    assert "family_id" not in s


# ---------------------------------------------------------------------------
# Phase 3: Group coaching + private intervention wiring
# ---------------------------------------------------------------------------


def test_phase3_group_and_private_intervention_message_paths_exist():
    s = _text(BRIDGE)
    assert "sanctuary_group_coaching_offer" in s
    assert "sanctuary_group_coaching_approve" in s
    assert "sanctuary_group_coaching_decline" in s
    assert "sanctuary_coaching_offer" in s
    assert "sanctuary_send_suggested_response" in s


# ---------------------------------------------------------------------------
# Phase 4: Voice attribution and per-user metering hooks
# ---------------------------------------------------------------------------


def test_phase4_voice_usage_and_transcript_are_user_scoped():
    s = _text(VOICE)
    assert "ENABLE_VOICE_TRANSCRIPT_CRYSTALLIZATION" in s
    assert "_resolve_user_uuid" in s
    assert "add_voice_minutes(db_pool, user_uuid, minutes)" in s
    assert "(user_id, session_id, user_text, ai_text, created_at)" in s
    assert "user_id=session_username" in s


# ---------------------------------------------------------------------------
# Phase 5: Family billing API presence (manual Stripe path remains out-of-band)
# ---------------------------------------------------------------------------


def test_phase5_family_billing_endpoint_exists():
    s = _text(BILLING)
    assert '@router.get("/family/members")' in s


# ---------------------------------------------------------------------------
# Phase 6: Coach/family assignment paths exist
# ---------------------------------------------------------------------------


def test_phase6_coach_assignment_supports_family_scope():
    s = _text(ADMIN)
    assert "entity_type must be client/family/group/company" in s


# ---------------------------------------------------------------------------
# Phase 7: Privacy walls
# ---------------------------------------------------------------------------


def test_phase7_family_member_listing_excludes_admin_accounts():
    s = _text(CLIENT_DATA)
    assert "role != 'ADMIN'" in s
    assert 'p.get("role") != "ADMIN"' in s


def test_phase7_no_cross_member_private_recall_from_inference_path():
    s = _text(INFER)
    # The inference path should use requester identity only.
    assert "semantic_search_all(query, user_id, top_k=15)" in s
    assert "conversation_context" in s
    assert "family_id" not in s


# ---------------------------------------------------------------------------
# Phase 9: Exit / reversibility
# ---------------------------------------------------------------------------


def test_phase9_unmerge_path_cleans_merge_markers():
    s = _text(BRIDGE)
    idx = s.find('elif t == "admin_unmerge_family_member":')
    assert idx > 0
    tail = s[idx: idx + 5000]
    assert 'tp.pop("merged_from_family", None)' in tail
    assert 'tp.pop("merged_at", None)' in tail
    assert 'tp.pop("merged_by_admin", None)' in tail


# ---------------------------------------------------------------------------
# Optional live DB checks (non-mutating)
# ---------------------------------------------------------------------------


LIVE = os.getenv("FAMILY_SANCTUARY_LIVE_TEST", "0") == "1"
DB_URL = os.getenv("DATABASE_URL", "")


@pytest.mark.skipif(not LIVE or not DB_URL, reason="Set FAMILY_SANCTUARY_LIVE_TEST=1 and DATABASE_URL")
@pytest.mark.asyncio
async def test_live_schema_presence_for_family_lifecycle():
    asyncpg = pytest.importorskip("asyncpg")
    conn = await asyncpg.connect(DB_URL)
    try:
        rows = await conn.fetch(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema='public'
              AND table_name IN (
                'families',
                'family_sanctuary_sessions',
                'sessions',
                'subscriptions',
                'conversation_history',
                'nate_intelligence_crystals',
                'voice_call_usage'
              )
            ORDER BY table_name
            """
        )
        names = [r["table_name"] for r in rows]
        assert names == [
            "conversation_history",
            "families",
            "nate_intelligence_crystals",
            "sessions",
            "subscriptions",
            "voice_call_usage",
        ] or names == [
            "conversation_history",
            "families",
            "family_sanctuary_sessions",
            "nate_intelligence_crystals",
            "sessions",
            "subscriptions",
            "voice_call_usage",
        ]
    finally:
        await conn.close()

