"""Thread directories, cut-repair, and keep-the-draft on soft audit misses."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "backend"))

from app.services.attunement.thread_directory import (  # noqa: E402
    block_for_turn,
    commit_turn,
    cut_repair_line,
)
from app.services.attunement.turn_contract import evaluate, is_meta_repair  # noqa: E402
from app.services.ln_stance_resolver import (  # noqa: E402
    StanceMove,
    _WITNESS_FALLBACK,
    guard_framing_menu,
)


def test_directories_stay_separate():
    uid = "thread_dir_lisa_test"
    commit_turn(uid, "Bill listened today and I want to stay with our relationship.")
    commit_turn(uid, "The story panel with Dawnsinger needs a name for the figure.")
    block = block_for_turn(uid, "Back to Bill and how unseen I felt in the marriage.")
    assert "Active: marriage" in block
    assert "panel:" in block
    assert "do not bring" in block.lower() or "Parked" in block


def test_cut_does_not_abandon_active_directory():
    uid = "thread_dir_cut_test"
    commit_turn(uid, "Bill and I are trying to build a relationship of equals.")
    block = block_for_turn(uid, "You are glitching. You erased the long reply.")
    assert "Active: marriage" in block
    assert "CUT REPAIR" in block
    line = cut_repair_line(uid)
    assert "cut was on my side" in line
    assert "Bill" in line


def test_presence_check_is_not_a_new_topic():
    uid = "thread_dir_presence_test"
    commit_turn(uid, "The sermon on the Lord's blessing stayed with me all morning.")
    block = block_for_turn(uid, "Are you there?")
    assert "Active: faith" in block
    assert "PRESENCE CHECK" in block
    assert "welcome-back" in block


def test_glitch_turn_is_not_collapsed_to_stock_hold():
    user = "You are glitching. I just gave you a big chunk and you erased it."
    assert is_meta_repair(user)
    long = (
        "The piece you wrote was about the kids and manipulation, "
        "and I was going to stay with that scene."
    )
    ev = evaluate(user, long, last_unacked="earlier beat " * 20, miss_ack=True)
    assert ev["collapsed"] is False
    assert "still with that last part" not in ev["reply"].lower()
    assert "kids and manipulation" in ev["reply"]


def test_long_answer_is_not_replaced_by_witness_stock():
    body = (
        "The leadership story landed because the blessing was named out loud "
        "and the room shifted with it. That is the piece to stay with."
    )
    menu = "\n".join(
        f"{i}. A padded framing option number {i} that should not replace the answer."
        for i in range(1, 40)
    )
    text = body + "\n" + menu
    out = guard_framing_menu(text, StanceMove.WITNESS)
    assert out != _WITNESS_FALLBACK
    assert "leadership story" in out
    assert "What you're carrying is heavy" not in out


@pytest.mark.asyncio
async def test_long_draft_survives_somatic_miss():
    from app.services.therapeutic_controller import audit_therapeutic_response

    draft = (
        "Staying with the leadership morning you described. "
        "The blessing was spoken in the room and it landed on you as both "
        "encouragement and weight, and the story you tied it to is the one "
        "to answer first. I will not swap this paragraph for a shorter line."
    )
    assert len(draft) >= 240
    out = await audit_therapeutic_response(
        response_text=draft,
        audit_metadata={
            "locale": "en-US",
            "autonomic_state": "activated",
            "max_tokens": 600,
            "mismatch_available": False,
            "crisis_exempt": False,
            "user_text_for_audit": "Saturday morning we had a leadership meeting.",
        },
        user_id="thread_keep_draft",
        db_pool=None,
    )
    assert draft in out["response_text"]
    assert "which part of what you shared" not in out["response_text"]
