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
    apply_surface_postflight,
    format_critical_recall,
    run_offline_smoke,
    tempo_max_tokens,
)
from app.services.attunement.live_ring import append, merge
from app.services.attunement.recall_cache import fetch, store_recall
from app.services.attunement.tokens import cover
from app.services.attunement.turn_contract import (
    evaluate,
    is_boundary_leak,
    is_collapse,
    is_meta_repair,
    is_session_review,
    is_yes_no_question,
    memory_claim_ok,
    scrub_ai_for_prompt,
    should_bind_stale_unacked,
    strip_hold_only,
    witnessing_fallback,
)
from app.services.attunement.unacked import (
    ack_if_covered,
    format_block,
    note_skipped,
    peek,
    push,
)
from app.services.attunement.voice import boilerplate_hits, name_cap, register_directive
from app.websocket.chat_depth_mode import pg_history_limit, pg_history_limit_for


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
    block = format_critical_recall(uid, [], user_text="anyway")
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


def test_lisa_stale_unacked_not_glued_on_new_share():
    uid = "t_lisa_stale"
    church = (
        "I told Bill I was working through a feeling of sadness that we are not "
        "attending church together. We both made room for each other with no "
        "fixing and no defenses. We are growing individually and together."
    )
    push(uid, church, "church1")
    meta_text = (
        "Little Nate, something is off with how you are functioning. I have been "
        "talking with you for an hour and it sounds like it is quite uncentered."
    )
    assert is_meta_repair(meta_text)
    assert should_bind_stale_unacked("anyway")
    assert not should_bind_stale_unacked(meta_text)
    out, _meta = apply_postflight(
        uid,
        meta_text,
        "I hear that the conversation has felt off and I want to stay with that.",
        live_turns=[],
    )
    assert "I'm still with that last part" not in out
    assert "growing individually" not in out.lower()


def test_ack_covers_last_clause_not_only_full_paragraph():
    uid = "t_clause_ack"
    push(
        uid,
        "Long church share about Bill and Holy Spirit and sadness. "
        "We are growing individually and together.",
        "c1",
    )
    acked = ack_if_covered(
        uid,
        "I'm still with that last part — We are growing individually and together.",
    )
    assert acked


def test_note_skipped_drops_stale_after_two():
    uid = "t_skip"
    push(uid, "I told you about the night I almost left and you skipped it", "s1")
    note_skipped(uid)
    assert peek(uid)
    note_skipped(uid)
    assert peek(uid) == []


def test_unanswered_not_injected_on_meta_or_long_share():
    uid = "t_no_bind"
    push(uid, "I told you about the night I almost left and you skipped it", "n1")
    meta = "Little Nate, can you please review our interactions from the beginning"
    assert "UNANSWERED" not in format_block(uid, [], user_text=meta)
    long_share = (
        "I have been carrying this shame for years and it is wrecking my marriage "
        "and I do not know what to do about church or Bill tonight"
    )
    assert "UNANSWERED" not in format_block(uid, [], user_text=long_share)
    assert "UNANSWERED" in format_block(uid, [], user_text="anyway")


def test_scrub_ai_strips_glue_and_boundary_leak():
    glued = (
        "I'm still with that last part — We are growing individually and together. "
        "You need to seek a therapist for the rest of this."
    )
    out = scrub_ai_for_prompt(glued)
    assert "I'm still with that last part" not in out
    assert "seek a therapist" not in out.lower()
    assert is_boundary_leak(glued)
    assert is_session_review("please review today's session from the start")


def test_no_unacked_push_on_substantial_hold():
    uid = "t_nopush"
    user = (
        "I have been carrying this shame for years and it is wrecking my marriage "
        "and I do not know what to do"
    )
    reply = (
        "The shame you have been carrying is still here, and the wrecking of "
        "your marriage is not something I will skip past."
    )
    apply_postflight(uid, user, reply, live_turns=[])
    assert peek(uid) == []


def test_apply_surface_postflight_strips_stale_glue_on_meta():
    uid = "t_surface"
    push(
        uid,
        "I told Bill I was working through sadness that we are not attending church.",
        "s1",
    )
    meta = "something is off with how you are functioning in this conversation"
    out = apply_surface_postflight(
        uid,
        meta,
        "I hear that this conversation has felt off and I want to stay with that.",
    )
    assert "I'm still with that last part" not in out


def test_pg_history_limit_for_review_widens():
    assert pg_history_limit("faster") == 6
    assert pg_history_limit_for("faster", "hello") == 12
    assert pg_history_limit_for(
        "faster", "can you please review today's session from the start"
    ) == 40


def test_boundary_leak_crystals_filtered_at_recall():
    from app.services.nate_response_validator import NateResponseValidator

    kept = {"crystal_text": "Shame on the chest is still here with you."}
    leak = {
        "crystal_text": "You need to seek a therapist; this isn't the place to go back into trauma processing."
    }
    out = NateResponseValidator.filter_recalled_crystals([kept, leak])
    assert kept in out
    assert leak not in out
