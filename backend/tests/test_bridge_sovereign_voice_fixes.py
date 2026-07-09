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
    """Mirrors AzureCortex.unregister + _ensure_session_id (SOVEREIGN-VOICE)."""

    def __init__(self):
        self.sockets: dict = {}
        self.active_sessions: dict = {}
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


class _FakeWebSocket:
    pass


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
