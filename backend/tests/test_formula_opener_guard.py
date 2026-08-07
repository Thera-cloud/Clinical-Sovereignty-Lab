"""Formula opener strip — preserve clinical witnessing lead-ins.

Loads ln_stance_resolver without app.services package __init__ (numpy side-effect).
"""

import importlib.util
import sys
from pathlib import Path

_MOD_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "ln_stance_resolver.py"
)
_NAME = "ln_stance_resolver_under_test"
_spec = importlib.util.spec_from_file_location(_NAME, _MOD_PATH)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules[_NAME] = _mod
_spec.loader.exec_module(_mod)
guard_formula_opener = _mod.guard_formula_opener


def test_strips_it_sounds_like_keeps_body():
    raw = (
        "It sounds like you're exhausted from carrying this alone. "
        "What happens in your chest when the house finally goes quiet?"
    )
    out = guard_formula_opener(raw)
    assert not out.lower().startswith("it sounds")
    assert "exhausted from carrying this alone" in out
    assert "chest" in out


def test_strips_i_hear_you_keeps_body():
    raw = "I hear you. The anger is the part that still wants a witness."
    out = guard_formula_opener(raw)
    assert "i hear you" not in out.lower()
    assert "anger is the part" in out.lower()


def test_preserves_override3_witnessing_lead_in():
    raw = (
        "You carry the names of those children. You said 'cleared hot' and "
        "went home and made spaghetti. I am not here to undo that."
    )
    assert guard_formula_opener(raw) == raw


def test_preserves_override4_helplessness_lead_in():
    raw = (
        "I don't have anything that fixes this. No technique, no reframe, "
        "no words. What I can do is sit here with you inside it and not look away."
    )
    assert guard_formula_opener(raw) == raw


def test_preserves_parallel_process_mirror_lead_in():
    raw = (
        "I'm going to pause on the content for a moment. Right now, you are "
        "telling me what I'm allowed to do in this room."
    )
    assert guard_formula_opener(raw) == raw


def test_single_sentence_formula_keeps_remainder():
    out = guard_formula_opener("It sounds like the silence got louder after he left.")
    assert out == "The silence got louder after he left."
