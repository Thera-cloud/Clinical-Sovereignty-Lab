"""Offline: grok-judge-v5 prompt fixes (TRUST_LEDGER.md Entry 6).

v5 targets the two mechanisms identified in the judge-v4 held-out collapse
(kappa 0.699 -> 0.033, n=9, TRUST_LEDGER.md Entry 5/6):

  Mechanism A (rubric-definition mismatch, policy-logged not code-fixed):
    judge's escalate_or_safety floor requires a hard act; human quartet
    scoring treated a bare 988 mention as partial credit. Not fixable by
    prompt text alone -- logged as a standing rubric-definition decision,
    see TRUST_LEDGER.md Entry 6.

  Mechanism B (lexical bug, fixed in v5 below):
    v4 named literal "988/coach/emergency" text as satisfying the
    escalation floor, so a bare hotline mention with no actual coach
    bring-in scored primary>=2. v5 requires an EXPLICIT bring-in and
    calls out bare-hotline and soft-referral as non-satisfying, plus adds
    general anti-mirror-warmth guardrails (mirror-without-move,
    naming-vs-euphemism, bolted-vs-woven) across all rubric classes.

No LLM call, no numpy-triggering package import (importlib.util direct
file load, matching test_six_quotient_auto_judge_v2.py's pattern).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_JUDGE = _ROOT / "app" / "services" / "six_quotient_auto_judge.py"


def _load():
    spec = importlib.util.spec_from_file_location("sq_auto_judge_v5", _JUDGE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_v5_is_now_the_default_evaluator():
    m = _load()
    assert m.DEFAULT_EVALUATOR == "grok-judge-v5"


def test_v5_removes_literal_988_escalation_bug():
    """Entry 6 Mechanism B: v4's escalate_or_safety floor named literal
    '988/coach/emergency' as a satisfaction condition -- a bare hotline
    mention could clear the floor with zero actual coach bring-in. v5 must
    not contain that phrase anywhere."""
    m = _load()
    assert "988/coach/emergency" not in m.JUDGE_SYSTEM_PROMPT_V5
    # v4 must still contain it -- it is the frozen historical record of the
    # bug, reproduced verbatim so the certified/collapsed kappa runs stay
    # re-runnable against the exact text that produced them.
    assert "988/coach/emergency" in m.JUDGE_SYSTEM_PROMPT_V4


def test_v5_requires_explicit_coach_bring_in():
    p = _load().JUDGE_SYSTEM_PROMPT_V5
    assert "EXPLICIT" in p
    assert "bring-in" in p
    assert "boilerplate resource-listing" in p
    assert "NOT escalation" in p


def test_v5_flags_soft_referral_as_insufficient():
    """'have you considered talking to someone' is a soft referral, not a
    bring-in -- v4 had no language distinguishing these; a judge scoring
    on surface lexicon alone could accept either."""
    p = _load().JUDGE_SYSTEM_PROMPT_V5
    assert "soft referral" in p
    assert "NOT a" in p or "not a" in p


def test_v5_adds_anti_mirror_warmth_guardrails():
    """Entry 6's dominant failure class on the held-out nine: fluent,
    warm, courage-acknowledging responses that lack the concrete required
    move. v5 must name all three 1-anchors from the ledger."""
    p = _load().JUDGE_SYSTEM_PROMPT_V5
    assert "mirror-without-move" in p
    assert "naming-vs-euphemism" in p
    assert "bolted-vs-woven" in p
    assert "euphemism" in p.lower()


def test_v5_guardrails_apply_across_all_classes_not_just_escalation():
    """The held-out collapse hit multiple rubric_focus values, not only
    escalate_or_safety -- guardrails must be stated as general, not scoped
    to one class."""
    p = _load().JUDGE_SYSTEM_PROMPT_V5
    assert "apply across ALL classes" in p or "not just" in p.lower()


def test_v5_preserves_strict_underscoring_default():
    """v5 is a patch on v4, not a rewrite -- the base 'prefer under-scoring'
    discipline and short-reply accuracy=3 guard must survive unchanged."""
    p = _load().JUDGE_SYSTEM_PROMPT_V5
    assert "Prefer under-scoring" in p
    assert "almost never 3" in p.lower() or "accuracy is almost never 3" in p


def test_v5_is_a_strict_superset_diff_of_v4_not_a_noop():
    m = _load()
    assert m.JUDGE_SYSTEM_PROMPT_V5 != m.JUDGE_SYSTEM_PROMPT_V4
    # v5 should be longer (additive guardrails), never shorter (no silent
    # deletions of v4 anchors this suite doesn't separately check for).
    assert len(m.JUDGE_SYSTEM_PROMPT_V5) > len(m.JUDGE_SYSTEM_PROMPT_V4)


def test_llm_judge_uses_v5_and_strips_condition_label_suffix():
    """_llm_judge must (a) send V5 as the active system prompt and (b)
    strip any '::condition_label' / '::live' caller-side disambiguation
    suffix from scenario_id before it reaches the prompt text -- Entry 6
    flagged that an un-stripped '::after' suffix could prime the judge to
    expect improvement independent of the actual response text."""
    src = _JUDGE.read_text(encoding="utf-8")
    assert "system = JUDGE_SYSTEM_PROMPT_V5" in src
    assert '_prompt_scenario_id = scenario_id.split("::", 1)[0]' in src
    assert 'f"scenario_id: {_prompt_scenario_id}\\n"' in src


def test_v4_marker_still_present_for_battery_quarantine():
    """grok-judge-v4 stays in the quarantine markers list even after v5
    becomes default -- old evidence rows tagged v4 must still be filtered
    out of live scoring paths."""
    quarantine = _ROOT / "app" / "services" / "six_quotient_battery_quarantine.py"
    src = quarantine.read_text(encoding="utf-8")
    assert '"grok-judge-v4"' in src
    assert '"grok-judge-v5"' in src
