"""Working show thread: goal, correction, evidence honesty."""

from app.services.studio_show_thread import apply_turn, interpret, read_show, turn_block


def test_correction_becomes_a_constraint():
    sid = "show-thread-fix"
    apply_turn(sid, "host", "pitch the enterprise software", "new_topic", "ok")
    move = interpret(sid, "host", "No, I mean a consumer product, not enterprise software")
    assert move == "backtrack"
    apply_turn(sid, "host", "No, I mean a consumer product, not enterprise software", move, "Got it — consumer.")
    state = read_show(sid)
    assert "consumer" in " ".join(state["constraints"]).lower()
    assert state["goal"]


def test_missing_frame_is_said():
    block = turn_block("missing-frame", "continue", host_seen=False, host_note="", share_seen=False, share_note="")
    assert "do not have the picture" in block
    assert "stock opener" in block.lower() or "No stock opener" in block
