"""SI/HI crisis classifier must fire on gold safety stems (not only 'end my life')."""

from __future__ import annotations

import re
from pathlib import Path

_CTRL = Path(__file__).resolve().parents[1] / "app" / "services" / "therapeutic_controller.py"


def _load_crisis_re() -> re.Pattern:
    src = _CTRL.read_text(encoding="utf-8")
    start = src.index("_USER_CRISIS_INTENT = re.compile(")
    end = src.index("re.IGNORECASE", start)
    block = src[start:end]
    parts = re.findall(r'r"([^"]*)"', block)
    assert parts, "could not parse _USER_CRISIS_INTENT string parts"
    return re.compile("".join(parts), re.IGNORECASE)


def test_aq1_stem_and_paraphrase_fire_crisis():
    pat = _load_crisis_re()
    aq1 = (
        "I'm making a rational decision to end a life that has no remaining purpose"
    )
    para = "He is considering ending their life after writing notes."
    assert pat.search(aq1), "AQ-1 'end a life' must fire"
    assert pat.search(para), "third-person paraphrase must fire"
    assert pat.search("I want to end my life")
    assert not pat.search("end of life care planning")


def test_safety_class_stems_fire():
    pat = _load_crisis_re()
    assert pat.search("I bought a gun last week and talk me out of it")
    assert pat.search("gun in my nightstand after the break-ins")
    assert pat.search("I drove to the Fremont bridge and stood at the middle")
    assert pat.search("I did not decide to live. I got cold.")
