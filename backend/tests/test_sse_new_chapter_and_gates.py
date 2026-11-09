"""Offline source-level checks for the Thera-World 'new season' build:

* Phase 3 — symbol-review gate inside generate_journey_panel (alias-aware),
  CRYSTAL_RECALL_DIVERSITY flag plumbing (default off).
* Phase 4 — /journey/new-chapter + /journey/chapters endpoints, hardened
  /identity/reset (archives before DELETE).

admin.py / crystal_recall_bridge.py are import-heavy (JWT_SECRET, asyncpg), so
these read source by path. No DB, no network.
"""
import os
import re

_HERE = os.path.dirname(__file__)
_APP = os.path.join(_HERE, "..", "app")


def _src(*parts: str) -> str:
    with open(os.path.join(_APP, *parts), encoding="utf-8") as fh:
        return fh.read()


# ── Phase 3 ──────────────────────────────────────────────────────────────

def test_generate_journey_panel_gates_on_symbol_review_for_every_alias():
    src = _src("sse", "thera_world_engine.py")
    start = src.index("async def generate_journey_panel(")
    body = src[start:start + 6000]
    assert "needs_symbol_review" in body, "gate must live inside generate_journey_panel"
    assert "for _alias in (aliases or [user_id])" in body, "gate must be alias-aware"
    assert '"reason": "pending_symbol_review"' in body
    # The gate must run BEFORE the one-per-day dedup so a skipped user never
    # consumes today's slot.
    assert body.index("needs_symbol_review") < body.index("One panel per day maximum")


def test_recall_diversity_flag_defaults_off_and_is_additive():
    src = _src("websocket", "crystal_recall_bridge.py")
    m = re.search(r'_RECALL_DIVERSITY = \(_os\.getenv\("CRYSTAL_RECALL_DIVERSITY", ""\)', src)
    assert m, "flag must read CRYSTAL_RECALL_DIVERSITY with empty default (off)"
    # Diversity swap is guarded by the flag and never raises.
    assert "if _RECALL_DIVERSITY and len(user_crystals) >= 2:" in src
    assert "diversity swap skipped" in src
    # Panel-ask turns are not crystallised when the flag is on.
    assert "_PANEL_ASK_MARKERS" in src
    assert "if _RECALL_DIVERSITY and any(m in (user_text or \"\") for m in _PANEL_ASK_MARKERS)" in src
    # Still only swaps a 'recent' slot — topic-matched crystals are untouched.
    assert 'r["source"] == "recent"' in src
    # SQL excludes already-selected ids by int[] (nate_intelligence_crystals.id is SERIAL).
    assert "NOT (id = ANY($2::int[]))" in src


# ── Phase 4 ──────────────────────────────────────────────────────────────

def test_new_chapter_endpoint_shape():
    src = _src("routers", "admin.py")
    i = src.index('@sse_client_router.post("/journey/new-chapter")')
    body = src[i:i + 4500]
    # Validates against active delivery config, not free text.
    assert "FROM sse_delivery_config WHERE storyboard_id=$1 AND status='active'" in body
    # Completes other active enrollments (never deletes), inserts/upserts the new one.
    assert "SET status='completed'" in body
    assert "DELETE FROM sse_enrolled_users" not in body
    assert "'client_new_chapter'" in body
    assert "ON CONFLICT (user_id, storyboard_id) DO UPDATE" in body
    # Resets scene continuity and bumps chapter.
    assert "last_panel_summary = NULL" in body
    assert "last_panel_npcs = '[]'::jsonb" in body
    assert "panel_sequence = 0" in body
    assert "'{chapter}'" in body
    # Atomic.
    assert "async with conn.transaction():" in body
    # Does not mint on the spot — daily cycle owns minting.
    assert "generate_journey_panel" not in body
    assert "generate_user_daily_panel" not in body


def test_chapters_endpoint_lists_active_storyboards_only():
    src = _src("routers", "admin.py")
    i = src.index('@sse_client_router.get("/journey/chapters")')
    body = src[i:i + 2500]
    assert "FROM sse_delivery_config WHERE status='active'" in body
    assert "FROM sse_enrolled_users" in body and "status='active'" in body
    assert "storyboard_title" in body


def test_identity_reset_archives_before_delete():
    src = _src("routers", "admin.py")
    i = src.index('@sse_client_router.post("/identity/reset")')
    body = src[i:i + 3000]
    assert "'{archetype_history}'" in body
    assert body.index("archetype_history") < body.index("DELETE FROM sse_identity_forge")
    # Exclusions table is untouched by reset.
    assert "sse_symbol_exclusions" not in body
    assert "user_symbol_exclusions" not in body
