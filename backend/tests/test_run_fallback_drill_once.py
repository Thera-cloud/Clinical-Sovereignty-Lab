"""Offline coverage for run_fallback_drill_once.py (TRUST_LEDGER Entry
24/27 -- a live-exercised run_fallback_drill() result is one of the three
named prerequisites for re-attempting G2). No live DB/asyncpg here -- this
locks in the safety properties statically; the real execution happened
once, live, on GREEN (see TRUST_LEDGER for the outcome_envelope row it
produced).
"""
from __future__ import annotations

from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "run_fallback_drill_once.py"
)


def test_script_exists():
    assert SCRIPT.is_file()


def test_script_hard_forces_dry_run():
    src = SCRIPT.read_text(encoding="utf-8")
    assert 'os.environ["LN7_HIVE_DRY_RUN"] = "1"' in src


def test_script_never_calls_the_real_provisioning_path():
    """Guard against a future edit accidentally wiring this one-shot
    runner to the paid hive_burst.sh path -- it must only ever call
    run_fallback_drill(), never run_hive_burst() directly with dry_run
    unset/False."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "run_fallback_drill(" in src
    assert "run_hive_burst(" not in src
    assert "dry_run=False" not in src


def test_script_verifies_the_outcome_envelope_row_not_just_exit_code():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "FROM outcome_envelope" in src
    assert "loop_name = 'ops'" in src
    assert "event_kind = 'fallback_drill'" in src
    assert "no outcome_envelope" in src.lower()
