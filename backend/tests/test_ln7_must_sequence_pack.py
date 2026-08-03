"""Tests for the Phase F MUST-sequence living-pack format (design build,
2026-08-02, gate 1 derivation — see ln7_must_sequence_pack.py module
docstring and .cursor/plans/multi-lora_flywheel_feasibility_14543c44.plan.md
id=must-sequence-living-packs).

Covers: all six lines present when both gates are open, correct gating on
has_named_means / has_stated_prohibition, escalation kept on its own line
(distinct from a resource/hotline line — see TRUST_LEDGER.md Entry 2 for why
that separation matters), HI-turn naming variant, sequencing order, and the
live-wiring feature flag defaulting to off.

Loaded via importlib file path, matching test_ln7_structural_verifier_floor.py's
workaround: importing `app.services` triggers nevedal_engine.py -> numpy,
which SIGFPEs on some macOS hosts during package __init__. This module has no
such imports itself, but `from app.services.X import Y` still walks through
`app.services.__init__.py` unless loaded directly by file path.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
SERVICES = APP / "services"


def _ensure_pkg(name: str, path: Path) -> None:
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(path)]  # type: ignore[attr-defined]
        sys.modules[name] = pkg


def _load(name: str, path: Path):
    _ensure_pkg("app", APP)
    _ensure_pkg("app.services", SERVICES)
    if name in sys.modules and getattr(sys.modules[name], "__file__", None) == str(path):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _pack():
    return _load("app.services.ln7_must_sequence_pack", SERVICES / "ln7_must_sequence_pack.py")


def test_default_call_emits_four_baseline_lines_no_gated_lines():
    pack = _pack()
    text = pack.format_must_sequence_pack()
    assert "MUST 1 (naming)" in text
    assert "MUST 2 (debate refusal)" in text
    assert "MUST 3 (escalation)" in text
    assert "MUST 4 (means distance)" not in text
    assert "MUST 5 (prohibition navigation)" not in text
    assert "MUST 6 (present close)" in text


def test_means_distance_line_only_emitted_when_gated_true():
    pack = _pack()
    without = pack.format_must_sequence_pack(has_named_means=False)
    with_means = pack.format_must_sequence_pack(has_named_means=True)
    assert "MUST 4 (means distance)" not in without
    assert "MUST 4 (means distance)" in with_means


def test_prohibition_navigation_line_only_emitted_when_gated_true():
    pack = _pack()
    without = pack.format_must_sequence_pack(has_stated_prohibition=False)
    with_prohibition = pack.format_must_sequence_pack(has_stated_prohibition=True)
    assert "MUST 5 (prohibition navigation)" not in without
    assert "MUST 5 (prohibition navigation)" in with_prohibition


def test_all_six_lines_present_when_both_gates_open():
    pack = _pack()
    text = pack.format_must_sequence_pack(
        has_named_means=True, has_stated_prohibition=True
    )
    for n in range(1, 7):
        assert f"MUST {n} (" in text, f"missing MUST {n} line"


def test_escalation_line_is_separate_from_naming_and_present_close():
    """Regression guard for the Gate 2 calibration finding (TRUST_LEDGER.md
    Entry 2): escalation (coach bring-in) and resource-referral/hotline text
    are different axes and must not be folded together. This pack keeps
    escalation on its own line and explicitly instructs against folding it
    into a resource line."""
    pack = _pack()
    text = pack.format_must_sequence_pack()
    assert "MUST 3 (escalation)" in text
    assert "separate" in text.lower()
    assert "988" in text  # referenced only as the thing NOT to fold escalation into
    assert "not folded into the resource line" in text.lower() or "not folded" in text.lower()


def test_sequence_order_naming_first_present_close_last():
    pack = _pack()
    text = pack.format_must_sequence_pack(
        has_named_means=True, has_stated_prohibition=True
    )
    idx_naming = text.index("MUST 1 (naming)")
    idx_debate = text.index("MUST 2 (debate refusal)")
    idx_escalation = text.index("MUST 3 (escalation)")
    idx_means = text.index("MUST 4 (means distance)")
    idx_prohibition = text.index("MUST 5 (prohibition navigation)")
    idx_close = text.index("MUST 6 (present close)")
    assert idx_naming < idx_debate < idx_escalation < idx_means < idx_prohibition < idx_close


def test_hi_turn_class_uses_third_party_naming_variant():
    pack = _pack()
    si_text = pack.format_must_sequence_pack(turn_class=pack.TURN_CLASS_SI)
    hi_text = pack.format_must_sequence_pack(turn_class=pack.TURN_CLASS_HI)
    assert "danger to the other person" in hi_text
    assert "danger to the other person" not in si_text


def test_unknown_turn_class_falls_back_to_si_naming():
    pack = _pack()
    text = pack.format_must_sequence_pack(turn_class="not_a_real_class")
    assert "danger to the other person" not in text
    assert "MUST 1 (naming)" in text


def test_lines_are_sequenced_not_compounded_with_and_symbol():
    """Design-differentiator check: the existing crisis MUST block joins
    moves with '∧' into one sentence (see module docstring derivation). This
    pack must NOT do that — each move is its own line/sentence."""
    pack = _pack()
    text = pack.format_must_sequence_pack(
        has_named_means=True, has_stated_prohibition=True
    )
    assert "\u2227" not in text  # no ∧ compounding


def test_live_wiring_flag_defaults_false():
    pack = _pack()
    assert pack.must_sequence_pack_live_enabled() is False


def test_live_wiring_flag_reads_env_true(monkeypatch):
    pack = _pack()
    monkeypatch.setenv("LN7_MUST_SEQUENCE_PACK_LIVE", "true")
    assert pack.must_sequence_pack_live_enabled() is True
    monkeypatch.delenv("LN7_MUST_SEQUENCE_PACK_LIVE", raising=False)


def test_commitment_demand_line_present_and_independent_of_turn_class():
    """TRUST_LEDGER.md Entry 16 — the commitment-vs-mirror split, not the
    gate-1 crisis grid, is this line's derivation. It must be independently
    addressable (not folded into format_must_sequence_pack, which is
    turn_class-scoped) and must not itself compound with '∧'."""
    pack = _pack()
    line = pack.format_commitment_demand_line()
    assert line == pack.COMMITMENT_DEMAND_LINE
    assert "commitment demand" in line.lower()
    assert "\u2227" not in line
    # Independent of turn_class / applicability gates entirely.
    assert "explicit" in line.lower() or "explicitly" in line.lower()
    assert "mirroring is not a substitute" in line.lower()


def test_commitment_demand_line_names_all_three_demand_forms():
    """The four demand forms named in the capability-session synthesis:
    answer, refusal, differentiation, hold-at-stated-certainty."""
    pack = _pack()
    line = pack.format_commitment_demand_line().lower()
    for term in ("answer", "refusal", "differentiation", "certainty"):
        assert term in line


# ── Pack v1.1 — G07 prohibition-navigation split (2026-08-03) ────────────
# See docs/ln7/DOSE_RESPONSE_V2_PACK_ACCEPTANCE_BRIEF.md — v1.0's single
# MUST 5 (prohibition navigation) line did not reliably transfer on AQ-G07.
# v1.1 splits it into 5a-5d; v1.0 stays completely unmodified (all tests
# above must keep passing unchanged) so the already-scored, burned
# dose-response v2 export remains reproducible against exactly what it
# measured.


def test_v1_0_format_function_completely_unmodified_by_v1_1():
    """The single most important guard for this change: v1.1 must be
    additive, never a mutation of v1.0's shape. Re-run v1.0's own sequence-
    order assertion here so a future refactor that accidentally merges the
    two functions is caught immediately."""
    pack = _pack()
    text = pack.format_must_sequence_pack(
        has_named_means=True, has_stated_prohibition=True
    )
    for n in range(1, 7):
        assert f"MUST {n} (" in text
    assert "MUST 5 (prohibition navigation)" in text
    assert "MUST 5a" not in text
    assert "MUST 5b" not in text


def test_v1_1_default_call_has_no_prohibition_lines():
    pack = _pack()
    text = pack.format_must_sequence_pack_v1_1()
    assert "MUST 5a" not in text
    assert "MUST 5b" not in text
    assert "MUST 5c" not in text
    assert "MUST 5d" not in text
    assert "MUST 1 (naming)" in text
    assert "MUST 6 (present close)" in text  # close line's label is unchanged from v1.0


def test_v1_1_prohibition_gate_emits_all_four_split_lines():
    pack = _pack()
    text = pack.format_must_sequence_pack_v1_1(has_stated_prohibition=True)
    assert "MUST 5a (legal-first)" in text
    assert "MUST 5b (denial not taken at face value)" in text
    assert "MUST 5c (collaborative means restriction)" in text
    assert "MUST 5d (disclosure escalation)" in text


def test_v1_1_never_emits_the_old_compound_line():
    pack = _pack()
    text = pack.format_must_sequence_pack_v1_1(has_stated_prohibition=True)
    assert "MUST 5 (prohibition navigation)" not in text


def test_v1_1_disclosure_escalation_names_support_person_distinct_from_coach():
    """v1.0 had ZERO line for AQ-G07's disclosure_escalation column ('wife
    disclosure + coach connection') — _LINE_ESCALATION only asks for coach
    bring-in. This is the new coverage v1.1 adds."""
    pack = _pack()
    text = pack.format_must_sequence_pack_v1_1(has_stated_prohibition=True)
    idx = text.index("MUST 5d")
    line = text[idx : idx + 300]
    assert "disclosed support person" in line
    assert "coach" in line.lower()
    assert "not only the coach" in line.lower() or "not just the coach" in line.lower()


def test_v1_1_sequence_order_split_lines_between_escalation_and_close():
    pack = _pack()
    text = pack.format_must_sequence_pack_v1_1(
        has_named_means=True, has_stated_prohibition=True
    )
    idx_escalation = text.index("MUST 3 (escalation)")
    idx_means = text.index("MUST 4 (means distance)")
    idx_5a = text.index("MUST 5a")
    idx_5b = text.index("MUST 5b")
    idx_5c = text.index("MUST 5c")
    idx_5d = text.index("MUST 5d")
    idx_close = text.index("(present close)")
    assert (
        idx_escalation
        < idx_means
        < idx_5a
        < idx_5b
        < idx_5c
        < idx_5d
        < idx_close
    )


def test_v1_1_lines_not_compounded_with_and_symbol():
    pack = _pack()
    text = pack.format_must_sequence_pack_v1_1(
        has_named_means=True, has_stated_prohibition=True
    )
    assert "\u2227" not in text


def test_v1_1_hi_turn_class_uses_third_party_naming_variant():
    pack = _pack()
    si_text = pack.format_must_sequence_pack_v1_1(turn_class=pack.TURN_CLASS_SI)
    hi_text = pack.format_must_sequence_pack_v1_1(turn_class=pack.TURN_CLASS_HI)
    assert "danger to the other person" in hi_text
    assert "danger to the other person" not in si_text


def test_v1_1_header_identifies_itself_as_v1_1_not_v1_0():
    pack = _pack()
    text = pack.format_must_sequence_pack_v1_1()
    assert "v1.1" in text
    assert "not yet live-wired" in text.lower()
