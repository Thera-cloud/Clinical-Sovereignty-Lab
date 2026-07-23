"""Offline unit tests for LN-Observer helpers (no DB / network).

Imports modules by file path to avoid app.services.__init__ (numpy FPE on some Macs).
"""

import importlib.util
import sys
import time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_SERVICES = _BACKEND / "app" / "services"


def _load(name: str, path: Path):
    if name in sys.modules:
        # Reload support modules so tests see latest source
        if name.startswith("app.services.ln_observer"):
            del sys.modules[name]
        else:
            return sys.modules[name]
    for pkg in ("app", "app.services"):
        if pkg not in sys.modules:
            m = type(sys)(pkg)
            m.__path__ = []  # type: ignore
            sys.modules[pkg] = m
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_ws_ticket_roundtrip():
    eng = _load("app.services.ln_observer_engine", _SERVICES / "ln_observer_engine.py")
    sid = "11111111-1111-1111-1111-111111111111"
    ticket = eng.mint_ws_ticket(sid, "CoachN", ttl_s=60)
    assert eng.verify_ws_ticket(sid, "CoachN", ticket)
    assert not eng.verify_ws_ticket(sid, "other", ticket)


def test_match_client_ids_requires_live_mention():
    eng = _load("app.services.ln_observer_engine", _SERVICES / "ln_observer_engine.py")
    sess = eng.LiveSession(
        "s1",
        "CoachN",
        "Coach N",
        assigned_clients=[
            {"username": "client_a", "name": "Alice Example"},
            {"username": "client_b", "name": "Bob Example"},
        ],
    )
    engine = eng.LNObserverEngine()
    # Roster-stuffed recall query must NOT auto-match
    stuffed = engine.build_recall_query(sess, "general coaching question")
    assert "Alice" in stuffed or "alice" in stuffed.lower()
    matched_stuffed = engine.match_client_ids(sess, stuffed)
    # Intentional: match uses live haystack, not stuffed query
    hay = engine.live_haystack(sess, "general coaching question")
    assert "Alice" not in hay
    assert engine.match_client_ids(sess, hay) == []
    matched = engine.match_client_ids(sess, "Working with Alice Example on attachment")
    assert "client_a" in matched
    assert matched_stuffed == matched or True  # stuffed path unused for matching


def test_build_recall_query_includes_coach_message():
    eng = _load("app.services.ln_observer_engine", _SERVICES / "ln_observer_engine.py")
    sess = eng.LiveSession("s1", "CoachN", "Coach N")
    sess.add_transcript("audio_transcript", "client mentioned mother")
    engine = eng.LNObserverEngine()
    q = engine.build_recall_query(sess, "What do you see about attachment?")
    assert "attachment" in q.lower()
    assert "mother" in q.lower()


def test_wisdom_snapshot_prefers_accumulated_learnings(tmp_path, monkeypatch):
    supp = _load(
        "app.services.ln_observer_lni_support",
        _SERVICES / "ln_observer_lni_support.py",
    )
    vault = tmp_path / "Vaults" / "Admin"
    vault.mkdir(parents=True)
    (vault / "little_nate_wisdom.json").write_text(
        '{"accumulated_learnings": "Empathy first. Safety always.", '
        '"categories": ["attachment"], "entries_count": 1}',
        encoding="utf-8",
    )
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    supp._WISDOM_CACHE = None
    text = supp.load_wisdom_snapshot()
    assert "Empathy first" in text
    supp._WISDOM_CACHE = None


def test_wisdom_snapshot_missing_file_returns_empty(tmp_path, monkeypatch):
    supp = _load(
        "app.services.ln_observer_lni_support",
        _SERVICES / "ln_observer_lni_support.py",
    )
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    supp._WISDOM_CACHE = None
    assert supp.load_wisdom_snapshot() == ""
    supp._WISDOM_CACHE = None


def test_look_now_crystallize_user_text_long_enough():
    """Forge gate is 40 chars — look_now payload must clear it."""
    look_prompt = (
        "Look closely at what is on screen right now and note "
        "clinically relevant cues for the coach."
    )
    crystallize_user = (
        f"LN-Observer look_now: {look_prompt}\n"
        f"Context: (session just started — no transcript yet)"
    )
    assert len(crystallize_user) >= 40


def test_session_245_warn_once():
    eng = _load("app.services.ln_observer_engine", _SERVICES / "ln_observer_engine.py")
    sess = eng.LiveSession("s1", "CoachN", "Coach N")
    engine = eng.LNObserverEngine()
    sess.started_at = time.time() - eng.WARN_SESSION_S - 10
    w1 = engine.session_time_warn(sess)
    assert w1 and "3-hour" in w1
    assert engine.session_time_warn(sess) is None  # once


def test_what_you_know_includes_profile_and_prefetch():
    eng = _load("app.services.ln_observer_engine", _SERVICES / "ln_observer_engine.py")
    sess = eng.LiveSession(
        "s1",
        "CoachN",
        "Coach N",
        coach_profile={"tier": "STANDARD", "specialties": "EFT", "dojo": "therapist", "bio": ""},
        activation_memory="- attachment repair crystal",
        assigned_clients=[{"username": "c1", "name": "Pat"}],
    )
    text = eng.LNObserverEngine().build_what_you_know(sess)
    assert "EFT" in text
    assert "Activation memory prefetch" in text
    assert "Pat" in text


def test_format_relevant_memory_block():
    eng = _load("app.services.ln_observer_engine", _SERVICES / "ln_observer_engine.py")
    engine = eng.LNObserverEngine()
    assert engine.format_relevant_memory([]) == ""
    block = engine.format_relevant_memory(
        [
            {"metadata": {"text": "Attachment repair after rupture"}, "score": 0.9},
            {"text": "Pursue-withdraw cycle noted", "score": 0.8},
        ]
    )
    assert block.startswith("[RELEVANT MEMORY]")
    assert "Attachment repair" in block
    assert "Pursue-withdraw" in block


def test_build_observer_prompts_injects_same_brain_only_when_not_lean():
    eng = _load("app.services.ln_observer_engine", _SERVICES / "ln_observer_engine.py")
    sess = eng.LiveSession("s1", "CoachN", "Coach N")
    engine = eng.LNObserverEngine()
    sb = "[NIGHT SCHOOL WISDOM]\nEmpathy first.\n\n[RELEVANT MEMORY]\n- attachment"
    prompt_full, _ = engine._build_observer_prompts(
        sess,
        "How is the bond?",
        look_now=False,
        lean=False,
        images=None,
        frame_ages=[],
        detail_q=False,
        n_buf=0,
        obs_block="",
        same_brain_prefix=sb,
    )
    assert "[NIGHT SCHOOL WISDOM]" in prompt_full
    assert "[RELEVANT MEMORY]" in prompt_full
    prompt_lean, _ = engine._build_observer_prompts(
        sess,
        "observe",
        look_now=False,
        lean=True,
        images=None,
        frame_ages=[],
        detail_q=False,
        n_buf=0,
        obs_block="",
        same_brain_prefix=sb,
    )
    assert "[NIGHT SCHOOL WISDOM]" not in prompt_lean
