"""Offline smoke for conversation attunement (20 units). No Redis/PG required."""

from app.services.attunement.agency import (
    agenda_suppressed,
    format_commitment_steer,
    hold_first_directive,
    reset_session_index,
    session_turn_index,
)
from app.services.attunement.boundaries import consume_deferred, save_deferred
from app.services.attunement.context_rank import rank
from app.services.attunement.hooks import (
    apply_postflight,
    format_critical_recall,
    run_offline_smoke,
    tempo_max_tokens,
)
from app.services.attunement.live_ring import append, merge
from app.services.attunement.recall_cache import fetch, store_recall
from app.services.attunement.tokens import cover
from app.services.attunement.turn_contract import (
    evaluate,
    is_collapse,
    is_yes_no_question,
    memory_claim_ok,
    strip_hold_only,
    witnessing_fallback,
)
from app.services.attunement.unacked import ack_if_covered, peek, push
from app.services.attunement.voice import boilerplate_hits, name_cap, register_directive
from app.websocket.chat_depth_mode import pg_history_limit


def test_01_contract_hold_on_current_or_unacked():
    ev = evaluate(
        "I cannot sleep because the shame sits on my chest every night",
        "The shame on your chest is still here. We can stay with that.",
    )
    assert ev["hold_cover"] > 0.2
    assert ev["steer_present"] is True


def test_02_collapse_gate_long_user_short_reply():
    user = "I have been carrying this for years and it is wrecking my marriage and I do not know what to do"
    assert is_collapse(user, "Yes") is True
    ev = evaluate(user, "Yes")
    assert ev["collapsed"] is True
    assert len(ev["reply"]) > 20


def test_02b_collapse_exempt_yes_no():
    assert is_yes_no_question("Do you remember Tuesday?")
    assert is_collapse("Do you remember Tuesday? " + ("x" * 80), "Yes") is False


def test_03_unacked_queue_and_format():
    uid = "t_unacked"
    push(uid, "I told you about the night I almost left and nobody asked again", "u1")
    assert peek(uid)
    block = format_critical_recall(uid, [])
    assert "UNANSWERED" in block
    assert "college relationship" not in block.lower()


def test_04_live_ring_merge():
    uid = "t_ring"
    append(uid, "hello there friend", "I'm with you")
    merged = merge(uid, [])
    assert merged and merged[-1]["user_text"].startswith("hello")


def test_05_recall_cache_overlap_required():
    uid = "t_cache"
    store_recall(uid, "shame sleep chest", "YOUR PERSONAL MEMORIES: shame sleep chest night", [9])
    assert fetch(uid, "shame and sleep on my chest")
    assert fetch(uid, "unrelated basketball scores") == ""


def test_06_pg_history_faster_is_six():
    assert pg_history_limit("faster") == 6
    assert pg_history_limit("extra") == 15


def test_07_context_rank_demotes_story():
    _l, _s, _c, _p, story = rank("live", "sess", "cry", "pg", "old unfinished file")
    assert story.startswith("BACKGROUND FILE")


def test_08_tempo_caps_faster():
    cap = tempo_max_tokens("t_tempo", "ok", 450, "faster", [{"user_text": "hi"}])
    assert 80 <= cap <= 450


def test_09_hold_only_tag():
    cleaned, flag = strip_hold_only("[HOLD_ONLY] I'm with the last part.")
    assert flag is True
    assert "HOLD_ONLY" not in cleaned
    assert is_collapse("x" * 90, "ok", hold_only=True) is False


def test_10_boilerplate_hits():
    assert boilerplate_hits("I hear you. What's coming up for you?") >= 1


def test_11_register_never_speaks_quotients():
    d = register_directive(["this is fucking hard and I prayed about it"])
    assert "Never speak" in d
    assert "faith" in d.lower() or "Faith" in d or "Honor faith" in d


def test_12_name_cap():
    out = name_cap("John, I hear you John and John stay", "John", [])
    assert out.lower().count("john") <= 1


def test_13_reconnect_clear_is_bool():
    from app.services.attunement.hooks import should_clear_live_on_login

    assert should_clear_live_on_login("fresh_uid") is True


def test_14_memory_claim_requires_evidence():
    assert memory_claim_ok("I remember last Tuesday", has_crystal=False, has_pg_overlap=False) is False
    assert memory_claim_ok("I remember last Tuesday", has_crystal=True, has_pg_overlap=False) is True


def test_15_miss_ack_covers_unacked():
    uid = "t_miss"
    push(uid, "I told you about the night I almost left and you skipped it entirely", "m1")
    out, meta = apply_postflight(
        uid,
        "anyway",
        "I'm still with that last part — the night I almost left.",
        live_turns=[],
    )
    assert meta.get("acked_turn_id") or cover(
        "the night I almost left", out
    ) > 0.2


def test_16_deferred_close():
    uid = "t_def"
    assert save_deferred(uid, [{"user_text": "I am so ashamed I can barely breathe tonight at all"}])
    line = consume_deferred(uid)
    assert "holding" in line.lower()


def test_17_commitment_steer_text():
    assert "commitment" in format_commitment_steer("call my sister")


def test_18_agenda_gate_first_two_turns():
    uid = "t_agenda"
    reset_session_index(uid)
    assert agenda_suppressed(uid, 0.9) is True
    session_turn_index(uid, bump=True)
    session_turn_index(uid, bump=True)
    session_turn_index(uid, bump=True)
    assert agenda_suppressed(uid, 0.8) is False


def test_19_conjecture_hold_first():
    assert "HOLD FIRST" in hold_first_directive()


def test_20_offline_smoke_all_units():
    smoke = run_offline_smoke()
    failed = [k for k, v in smoke.items() if not v]
    assert not failed, failed


def test_witnessing_fallback_does_not_dump():
    long = "word " * 80
    fb = witnessing_fallback(long)
    assert len(fb) < 200


def test_auditor_expected_count():
    from app.services.attunement_auditor import EXPECTED, TAB_ENDPOINTS

    total = sum(len(t["endpoints"]) for t in TAB_ENDPOINTS)
    assert total == EXPECTED == 8


def test_20_scorecard_baselines_instrumented_turns():
    import inspect

    from app.services.attunement_scorecard_agent import AttunementScorecardAgent

    src = inspect.getsource(AttunementScorecardAgent._compute)
    assert "instrumented" in src
    assert "NULLIF" not in src
    assert "FILTER (WHERE metadata" in src
