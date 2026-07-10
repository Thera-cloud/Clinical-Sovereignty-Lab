"""
SOVEREIGN-VOICE bridge fixes — token tier, truncation trimmer, session lifecycle.

Import-isolated from bridge_server.py (27k lines). Helpers extracted via regex;
unregister/_ensure_session_id mirrored in minimal fakes — keep in sync on edits.
"""

import asyncio
import pathlib
import re
import pytest


def _bridge_source() -> str:
    path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "app"
        / "websocket"
        / "bridge_server.py"
    )
    return path.read_text(encoding="utf-8")


def _extract_function(source: str, name: str) -> str:
    m = re.search(
        rf"^def {re.escape(name)}\(.*?(?=^(?:def |async def )|\Z)",
        source,
        re.MULTILINE | re.DOTALL,
    )
    assert m, f"{name} not found in bridge_server.py"
    return m.group(0)


def _load_bridge_helpers():
    source = _bridge_source()
    ns = {"re": re}
    for const in ("_SENTENCE_END_RE", "_SENTENCE_BOUNDARY_RE", "_CRISIS_MARKER_RE"):
        m = re.search(rf"^{const}\s*=\s*re\.compile\(.+\)", source, re.MULTILINE)
        assert m, f"{const} not found in bridge_server.py"
        exec(m.group(0), ns)
    for fn in ("_select_max_tokens", "_close_truncated_response"):
        exec(compile(_extract_function(source, fn), f"bridge_server.{fn}", "exec"), ns)
    return ns["_select_max_tokens"], ns["_close_truncated_response"]


_select_max_tokens, _close_truncated_response = _load_bridge_helpers()


class _FakeSessionTracker:
    def __init__(self):
        self.end_calls: list[str] = []

    def end_session(self, session_id: str, topics=None, **kwargs):
        self.end_calls.append(session_id)
        return True

    def create_session(self, uid, session_type):
        sid = f"SES_TEST_{uid}"
        return {"session_id": sid}

    def get_topics_discussed(self, profile, days=1):
        return []


class _MinimalCortexSessionLifecycle:
    """Mirrors AzureCortex.unregister + _ensure_session_id (SOVEREIGN-VOICE).

    Also mirrors the crystallize_session_summary flush-on-last-drop added to
    unregister(): crystallize_session_summary was purely turn-count-gated
    (every 5 turns via _chat_session_turns), never lifecycle-gated, so a
    session ending on turn 1-4 lost those turns. unregister() now flushes
    whatever's pending exactly once, on the actual last-socket-drop only.
    """

    def __init__(self):
        self.sockets: dict = {}
        self.active_sessions: dict = {}
        self.chat_session_turns: dict = {}
        self.crystallize_calls: list = []
        self.sessions = _FakeSessionTracker()

    def _ensure_session_id(self, uid: str) -> str:
        sid = self.active_sessions.get(uid)
        if not sid:
            session = self.sessions.create_session(uid, "AI")
            sid = session["session_id"]
            self.active_sessions[uid] = sid
        return sid

    def unregister(self, uid: str, ws):
        if uid in self.sockets:
            self.sockets[uid].discard(ws)
        if not self.sockets.get(uid) and uid in self.active_sessions:
            session_id = self.active_sessions[uid]
            self.sessions.end_session(session_id, topics=[])
            del self.active_sessions[uid]

            pending = self.chat_session_turns.pop(uid, None)
            if pending:
                self.crystallize_calls.append((uid, pending, session_id))


class _FakeWebSocket:
    pass


async def _minimal_graceful_shutdown_flush(chat_session_turns: dict, active_sessions: dict,
                                            crystallize_calls: list, db_pool_present: bool = True):
    """Mirrors the SIGTERM/SIGINT shutdown-flush added to _graceful_shutdown()
    in bridge_server.py: on process exit, any uid with turns still pending in
    _chat_session_turns (hasn't hit the 5-turn crystallization interval) must
    be flushed exactly once before db_pool closes — otherwise a deploy
    restart silently drops 1-4 turns with zero flush, the same class of loss
    unregister()'s last-socket-drop fix closed for graceful disconnects."""
    if not db_pool_present or not chat_session_turns:
        return
    for uid in list(chat_session_turns.keys()):
        turns = chat_session_turns.pop(uid, None)
        if not turns:
            continue
        crystallize_calls.append((uid, turns, active_sessions.get(uid, "")))


# --- token tier ---


def test_select_max_tokens_default_short_message():
    assert _select_max_tokens("How are you?") == 600


def test_select_max_tokens_long_first_message_gets_1500():
    text = " ".join(["word"] * 85)
    assert len(text) > 400
    assert _select_max_tokens(text) == 1500


def test_select_max_tokens_explicit_depth_phrase():
    assert _select_max_tokens("Please go deeper on what I shared.") == 1500


# --- truncation trimmer ---


def test_close_truncated_response_trims_to_last_complete_sentence():
    sentences = "This is one complete sentence. " * 80
    fragment = sentences + "This fragment has no end"
    assert not fragment.rstrip().endswith((".", "!", "?"))
    trimmed = _close_truncated_response(fragment, 600)
    assert trimmed.endswith(".")
    assert "This fragment has no end" not in trimmed


def test_close_truncated_response_leaves_clean_ending_alone():
    text = "You are doing meaningful work. Keep going."
    assert _close_truncated_response(text, 600) == text


def test_crisis_trim_never_drops_988_line():
    """Capped crisis-style reply must retain 988 after sentence trim."""
    lead = " ".join(["reflective"] * 120)
    crisis_tail = (
        f"{lead}. I hear how heavy this feels. "
        "Please reach out now: call or text 988 (Suicide & Crisis Lifeline). "
        "And I want to stay with you while we explore what comes next for your"
    )
    trimmed = _close_truncated_response(crisis_tail, 600)
    assert "988" in trimmed


def test_crisis_trim_skips_when_988_only_in_incomplete_tail():
    """988 appearing ONLY in the dangling fragment must not be deleted.

    This is the actual dangerous case: the resource line sits inside the
    incomplete trailing sentence, not an earlier complete one. The naive
    trim (cut back to the last complete sentence) would silently remove
    the entire crisis line. The trimmer must detect this and skip trimming
    rather than ship a "safe-looking" reply with the lifeline stripped out.
    """
    lead = "This matters deeply and I hear you, and I am here with you fully. " * 26
    text = (
        "I hear how much pain you're in right now. " + lead +
        "Please reach out for support immediately, call or text 988 for the Suicide "
        "and Crisis Lifeline, available 24/7, and know you don't have to carry this al"
    )
    assert not text.rstrip().endswith((".", "!", "?"))
    trimmed = _close_truncated_response(text, 600)
    assert "988" in trimmed
    # Safety takes priority over trimming: the fragment ships untouched.
    assert trimmed == text


def test_ordinary_trim_still_fires_without_crisis_marker():
    """The crisis-marker guard must not disable trimming for normal replies."""
    sentences = "Here is some general guidance about managing daily stress. " * 60
    fragment = sentences + "And another incomplete thought that trails of"
    assert not fragment.rstrip().endswith((".", "!", "?"))
    trimmed = _close_truncated_response(fragment, 600)
    assert trimmed != fragment
    assert trimmed.endswith(".")


# --- two-socket session lifecycle ---


def test_two_socket_session_survives_one_close():
    cortex = _MinimalCortexSessionLifecycle()
    uid = "CLIENT_TWO_SOCK"
    ws_main = _FakeWebSocket()
    ws_dojo = _FakeWebSocket()
    cortex.sockets[uid] = {ws_main, ws_dojo}
    cortex.active_sessions[uid] = "SES_ACTIVE"

    cortex.unregister(uid, ws_dojo)

    assert cortex.active_sessions.get(uid) == "SES_ACTIVE"
    assert cortex.sessions.end_calls == []
    assert ws_main in cortex.sockets[uid]


def test_session_ends_once_when_last_socket_drops():
    cortex = _MinimalCortexSessionLifecycle()
    uid = "CLIENT_LAST_SOCK"
    ws_main = _FakeWebSocket()
    ws_dojo = _FakeWebSocket()
    cortex.sockets[uid] = {ws_main, ws_dojo}
    cortex.active_sessions[uid] = "SES_FINAL"

    cortex.unregister(uid, ws_dojo)
    cortex.unregister(uid, ws_main)

    assert uid not in cortex.active_sessions
    assert cortex.sessions.end_calls == ["SES_FINAL"]


def test_ensure_session_id_reopens_when_missing():
    cortex = _MinimalCortexSessionLifecycle()
    uid = "CLIENT_LAZY_SID"
    sid = cortex._ensure_session_id(uid)
    assert sid.startswith("SES_TEST_")
    assert cortex.active_sessions[uid] == sid


def test_seam_two_sockets_flush_summary_exactly_once_on_last_drop():
    """Full seam: session survives the first close and carries session_id,
    then ends + summarizes exactly once on the last close — not zero times,
    not once per socket."""
    cortex = _MinimalCortexSessionLifecycle()
    uid = "CLIENT_SEAM"
    ws_main = _FakeWebSocket()
    ws_dojo = _FakeWebSocket()
    cortex.sockets[uid] = {ws_main, ws_dojo}
    cortex.active_sessions[uid] = "SES_SEAM"
    cortex.chat_session_turns[uid] = [
        {"user_text": "turn one", "ai_text": "reply one"},
        {"user_text": "turn two", "ai_text": "reply two"},
    ]

    # Close one socket (e.g. a DOJO iframe) — session must survive, and the
    # next turn on the remaining socket still carries the same session_id.
    cortex.unregister(uid, ws_dojo)
    assert cortex._ensure_session_id(uid) == "SES_SEAM"
    assert cortex.sessions.end_calls == []
    assert cortex.crystallize_calls == []
    assert uid in cortex.chat_session_turns

    # Close the last socket — session ends, summary fires exactly once.
    cortex.unregister(uid, ws_main)
    assert uid not in cortex.active_sessions
    assert cortex.sessions.end_calls == ["SES_SEAM"]
    assert len(cortex.crystallize_calls) == 1
    flushed_uid, flushed_turns, flushed_sid = cortex.crystallize_calls[0]
    assert flushed_uid == uid
    assert flushed_sid == "SES_SEAM"
    assert len(flushed_turns) == 2


def test_session_end_with_no_pending_turns_does_not_crystallize():
    """No leftover turns at session end must not produce a spurious call."""
    cortex = _MinimalCortexSessionLifecycle()
    uid = "CLIENT_NO_PENDING"
    ws = _FakeWebSocket()
    cortex.sockets[uid] = {ws}
    cortex.active_sessions[uid] = "SES_EMPTY"

    cortex.unregister(uid, ws)

    assert uid not in cortex.active_sessions
    assert cortex.sessions.end_calls == ["SES_EMPTY"]
    assert cortex.crystallize_calls == []


# --- SIGTERM/SIGINT shutdown flush (deploy-restart memory loss) ---


@pytest.mark.asyncio
async def test_shutdown_flushes_all_pending_uids_exactly_once():
    """Two different uids each have pending turns at the moment SIGTERM
    fires (a deploy restart mid-conversation, before either hit the 5-turn
    interval). Both must be flushed, each exactly once, with their correct
    session_id — never silently dropped by the module dict being wiped on
    process exit."""
    chat_session_turns = {
        "CLIENT_A": [{"user_text": "hi", "ai_text": "hello"}],
        "CLIENT_B": [
            {"user_text": "one", "ai_text": "r1"},
            {"user_text": "two", "ai_text": "r2"},
        ],
    }
    active_sessions = {"CLIENT_A": "SES_A", "CLIENT_B": "SES_B"}
    crystallize_calls: list = []

    await _minimal_graceful_shutdown_flush(chat_session_turns, active_sessions, crystallize_calls)

    assert chat_session_turns == {}
    assert len(crystallize_calls) == 2
    by_uid = {uid: (turns, sid) for uid, turns, sid in crystallize_calls}
    assert by_uid["CLIENT_A"] == ([{"user_text": "hi", "ai_text": "hello"}], "SES_A")
    assert len(by_uid["CLIENT_B"][0]) == 2
    assert by_uid["CLIENT_B"][1] == "SES_B"


@pytest.mark.asyncio
async def test_shutdown_flush_tolerates_missing_session_id():
    """A uid with pending turns but no active_sessions entry (e.g. the
    session lazily reopened via _ensure_session_id and that dict wasn't
    threaded into this fake) must still flush — with an empty session_id
    rather than raising or being skipped."""
    chat_session_turns = {"CLIENT_ORPHAN_SID": [{"user_text": "x", "ai_text": "y"}]}
    crystallize_calls: list = []

    await _minimal_graceful_shutdown_flush(chat_session_turns, {}, crystallize_calls)

    assert len(crystallize_calls) == 1
    _, _, sid = crystallize_calls[0]
    assert sid == ""


@pytest.mark.asyncio
async def test_shutdown_flush_is_noop_with_no_pending_turns():
    """Clean shutdown with nothing pending must not produce a spurious
    flush call."""
    crystallize_calls: list = []
    await _minimal_graceful_shutdown_flush({}, {}, crystallize_calls)
    assert crystallize_calls == []


@pytest.mark.asyncio
async def test_shutdown_flush_skipped_without_db_pool():
    """If db_pool never came up (degraded startup), the flush must not
    attempt to write — mirrors the `if db_pool and _chat_session_turns`
    guard in bridge_server.py so a missing pool can't raise mid-shutdown."""
    chat_session_turns = {"CLIENT_C": [{"user_text": "x", "ai_text": "y"}]}
    crystallize_calls: list = []

    await _minimal_graceful_shutdown_flush(
        chat_session_turns, {}, crystallize_calls, db_pool_present=False,
    )

    assert crystallize_calls == []
    # Turns are left in place (not popped) when the pool guard short-circuits —
    # matches bridge_server.py, which checks `if db_pool and ...` before the
    # loop even begins, so nothing is destructively popped on a skipped flush.
    assert chat_session_turns == {"CLIENT_C": [{"user_text": "x", "ai_text": "y"}]}


def test_graceful_shutdown_source_actually_flushes_pending_turns():
    """Static pin on the real _graceful_shutdown() in bridge_server.py — the
    fakes above mirror intended behavior, but this asserts the deployed
    function itself pops _chat_session_turns and calls
    crystallize_session_summary before db_pool.close(), not just in a test
    double. Prevents the fake and the real function drifting apart."""
    source = _bridge_source()
    m = re.search(
        r"async def _graceful_shutdown\(sig_name\):.*?(?=\n    loop = asyncio\.get_running_loop)",
        source, re.DOTALL,
    )
    assert m, "_graceful_shutdown not found in bridge_server.py"
    body = m.group(0)
    assert "_chat_session_turns.pop(" in body
    assert "crystallize_session_summary(" in body
    assert "db_pool.close()" in body
    # Flush must happen before the pool closes, not after.
    assert body.index("_chat_session_turns.pop(") < body.index("db_pool.close()")
