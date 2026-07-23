"""Clinical-AGI Observer acceptance contracts (offline).

These encode the four plan acceptance tests as structural/unit proofs.
Live PG/Vectorize E2E still required on GREEN for full Clinical-AGI-class.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_BACKEND = Path(__file__).resolve().parents[1]
_SERVICES = _BACKEND / "app" / "services"


def _load(name: str, path: Path):
    if name in sys.modules and name.startswith("app.services.ln_observer"):
        del sys.modules[name]
    elif name in sys.modules:
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


def test_acceptance_1_crystal_cross_client_relevant_memory_slot():
    """Test 1: assigned-client mention → RELEVANT MEMORY block format."""
    eng = _load("app.services.ln_observer_engine", _SERVICES / "ln_observer_engine.py")
    sess = eng.LiveSession(
        "s1",
        "CoachN",
        "Coach N",
        assigned_clients=[{"username": "client_a", "name": "Alice Example"}],
    )
    engine = eng.LNObserverEngine()
    hay = engine.live_haystack(sess, "Working with Alice Example on attachment")
    assert "client_a" in engine.match_client_ids(sess, hay)
    block = engine.format_relevant_memory(
        [{"metadata": {"text": "Alice attachment repair crystal"}, "score": 0.91}]
    )
    assert block.startswith("[RELEVANT MEMORY]")
    assert "Alice attachment" in block


def test_acceptance_2_prior_session_summary_extractive_fallback():
    """Test 2: close path never leaves empty summary (prior-session seed)."""
    eng = _load("app.services.ln_observer_engine", _SERVICES / "ln_observer_engine.py")
    sess = eng.LiveSession("s1", "CoachN", "Coach N")
    sess.add_transcript(
        "audio_transcript",
        "Client named the pursue-withdraw cycle from last week.",
    )
    sess.add_transcript("coach_chat", "What do you remember from last session?")
    summary = eng.LNObserverEngine()._extractive_close_summary(sess)
    assert summary and "pursue-withdraw" in summary.lower()
    assert len(summary) > 40


def test_acceptance_3_modality_wisdom_injected_non_lean():
    """Test 3: Night School wisdom prefix lands in non-lean chat prompt."""
    eng = _load("app.services.ln_observer_engine", _SERVICES / "ln_observer_engine.py")
    sess = eng.LiveSession("s1", "CoachN", "Coach N")
    engine = eng.LNObserverEngine()
    sb = (
        "[NIGHT SCHOOL WISDOM]\n"
        "EFT: track the attachment emotion under the content.\n\n"
        "[RELEVANT MEMORY]\n- modality depth crystal"
    )
    prompt, _ = engine._build_observer_prompts(
        sess,
        "Which modality fits this rupture?",
        look_now=False,
        lean=False,
        images=None,
        frame_ages=[],
        detail_q=False,
        n_buf=0,
        obs_block="",
        same_brain_prefix=sb,
    )
    assert "[NIGHT SCHOOL WISDOM]" in prompt
    assert "EFT" in prompt
    assert "[RELEVANT MEMORY]" in prompt


def test_acceptance_4_write_path_origin_surface_kwarg():
    """Test 4: crystallize path tags origin_surface=ln_observer (PG proof contract)."""
    import types

    eng_mod = _load(
        "app.services.ln_observer_engine", _SERVICES / "ln_observer_engine.py"
    )
    engine = eng_mod.LNObserverEngine()
    engine._validator = lambda: None  # type: ignore
    called = {}

    async def fake_crystallize(*args, **kwargs):
        called.update(kwargs)
        return "crystal-id"

    bridge = types.ModuleType("app.websocket.crystal_recall_bridge")
    bridge.crystallize_from_conversation = fake_crystallize
    sys.modules["app.websocket"] = types.ModuleType("app.websocket")
    sys.modules["app.websocket.crystal_recall_bridge"] = bridge

    asyncio.run(
        engine._crystallize_safe(
            "CoachN",
            "LN-Observer look_now frame=x: clinically relevant cues for coach.",
            "Aligned visual note about attachment repair and safety.",
            coach_name="Coach N",
            min_score=2,
        )
    )
    assert called.get("origin_surface") == "ln_observer"


def test_close_summary_falls_back_when_inference_missing():
    eng = _load("app.services.ln_observer_engine", _SERVICES / "ln_observer_engine.py")
    sess = eng.LiveSession("s1", "CoachN", "Coach N")
    sess.add_transcript("coach_chat", "Closing themes: trust repair.")
    engine = eng.LNObserverEngine()
    engine._inference = lambda: None  # type: ignore
    engine._validator = lambda: None  # type: ignore
    out = asyncio.run(engine.close_summary(sess))
    assert out and "trust repair" in out.lower()


def test_auditor_endpoint_count_is_11():
    aud = _load(
        "app.services.ln_observer_auditor", _SERVICES / "ln_observer_auditor.py"
    )
    total = sum(len(t["endpoints"]) for t in aud.TAB_ENDPOINTS)
    assert total == 11
