"""Host/caller listen hold — 6s silence, unfinished thought extends."""

from app.services.studio_listen_hold import LISTEN_HOLD_MS, LISTEN_SILENCE_MS, hold_floor_ms


def test_finished_thought_is_base_silence():
    assert hold_floor_ms("I want to talk about my week.") == LISTEN_SILENCE_MS
    assert hold_floor_ms("How are you feeling Nate") == LISTEN_SILENCE_MS


def test_named_hold_phrases_extend():
    assert hold_floor_ms("I want to talk a moment to think deeper") == LISTEN_HOLD_MS
    assert hold_floor_ms("let me say more about this") == LISTEN_HOLD_MS
    assert hold_floor_ms("let me pause for a second to think about this") == LISTEN_HOLD_MS


def test_unfinished_last_word_extends():
    assert hold_floor_ms("what I need is") == LISTEN_HOLD_MS
    assert hold_floor_ms("I was going to say um") == LISTEN_HOLD_MS
    assert hold_floor_ms("and then") == LISTEN_HOLD_MS


def test_short_stem_extends():
    assert hold_floor_ms("hold on") == LISTEN_HOLD_MS
    assert hold_floor_ms("give me a second") == LISTEN_HOLD_MS
    assert hold_floor_ms("wait") == LISTEN_HOLD_MS


def test_ellipsis_and_empty():
    assert hold_floor_ms("I was going to say...") == LISTEN_HOLD_MS
    assert hold_floor_ms("") == LISTEN_SILENCE_MS


def test_prime_match_allows_small_growth():
    from app.services.studio_listen_hold import prime_clear, prime_match, prime_store, prime_take

    assert prime_match("I want to talk about my week", "I want to talk about my week and")
    assert not prime_match("hello there friends", "something completely different")
    prime_clear("sid-prime")
    prime_store("sid-prime", "I want to talk about my week", "Yeah, that week sounds heavy.")
    assert prime_take("sid-prime", "I want to talk about my week") == "Yeah, that week sounds heavy."
    assert prime_take("sid-prime", "I want to talk about my week") is None


def test_prime_turn_skips_thread_until_commit():
    import asyncio

    from app.services.studio_listen_hold import prime_clear
    from app.services.studio_session_service import cohost_turn, thread_text

    sid = "sid-prime-hold"
    prime_clear(sid)
    primed = asyncio.run(
        cohost_turn(
            None,
            sid,
            "I want to talk about my week and how heavy it felt",
            event="prime",
        )
    )
    assert primed["ok"] is True
    assert primed.get("primed") is True
    assert primed["text"]
    assert thread_text(sid) == ""
    committed = asyncio.run(
        cohost_turn(
            None,
            sid,
            "I want to talk about my week and how heavy it felt",
            event="commit",
        )
    )
    assert committed["text"] == primed["text"]
    assert committed.get("provider") == "prime"
    assert "NATE:" in thread_text(sid)


def test_room_html_mirrors_hold():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[2] / "mobile/web/studio_nate_room.html").read_text()
    assert "var LISTEN_SILENCE_MS = 6000;" in html
    assert "var LISTEN_HOLD_MS = 14000;" in html
    assert "function holdFloorMs" in html
    assert "function primeHold" in html
    assert "function deliverHold" in html
    assert "rec.continuous = true;" in html
    assert "function releaseCapSoon" in html
