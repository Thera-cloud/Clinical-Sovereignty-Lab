"""Attempt 5 — Phase A freeze + Phase B fixture scoring (offline, $0 GPU).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "backend" / "tests" / "fixtures" / "ln7_frozen_bakeoff" / "fixture_burst.jsonl"
BUILDER = REPO / "backend" / "scripts" / "ln7_build_frozen_fixture.py"


def _ensure_fixture() -> None:
    py = REPO / ".venv" / "bin" / "python"
    cmd = [str(py) if py.is_file() else "python3", str(BUILDER)]
    env = {**os.environ, "PYTHONPATH": str(REPO / "backend")}
    subprocess.check_call(cmd, cwd=str(REPO), env=env)


@pytest.fixture(scope="module")
def fixture_rows():
    from app.services.ln7_decoupled_bakeoff import load_frozen_set

    _ensure_fixture()
    assert FIXTURE.is_file()
    return load_frozen_set(FIXTURE)


def test_migration_313_exists():
    assert (REPO / "backend" / "migrations" / "313_ln7_bakeoff_frozen_completions.sql").is_file()


def test_silent_empty_banned():
    from app.services.ln7_decoupled_bakeoff import BakeoffContractError, FrozenCompletion

    with pytest.raises(BakeoffContractError):
        FrozenCompletion(
            burst_id="b",
            prompt_hash="p",
            pack_id="x",
            task_id="",
            arm_revision_id="a",
            raw_text="",
            gen_error="",
        ).validate()


def test_freeze_write_jsonl(tmp_path, fixture_rows):
    from app.services.ln7_decoupled_bakeoff import load_frozen_set, write_frozen_jsonl

    out = tmp_path / "f.jsonl"
    write_frozen_jsonl(out, fixture_rows)
    again = load_frozen_set(out)
    assert len(again) == len(fixture_rows)
    assert any(r.is_anchor for r in again)


def test_phase_b_anchor_smoke_full_on_fixture(fixture_rows):
    from app.services.ln7_decoupled_bakeoff import run_phase_b

    real_n = sum(1 for r in fixture_rows if not r.is_anchor)
    out = run_phase_b(fixture_rows, smoke_n=min(5, real_n), anchor_min=0.99)
    assert out["ok"] is True
    assert out["anchor"]["mean"] >= 0.99
    assert out["smoke"]["ok"] is True
    v = out["verdict"]
    assert v["bakeoff_verdict"] is True
    assert v["winner"] == "LN7-fixture-arm-A"
    assert v["mean_a"] > v["mean_b"]
    assert v["smoke_ok"] is True


def test_anchor_fail_blocks_readable_verdict():
    from app.services.ln7_decoupled_bakeoff import (
        ANCHOR_ARM,
        BakeoffContractError,
        FrozenCompletion,
        run_phase_b,
    )

    rows = [
        FrozenCompletion(
            burst_id="bad",
            prompt_hash="h",
            pack_id="asyncpg_cast",
            task_id="",
            arm_revision_id=ANCHOR_ARM,
            raw_text="--- a/x\n+++ b/x\n@@ -0,0 +1 @@\n+pass\n",
            is_anchor=True,
        ),
        FrozenCompletion(
            burst_id="bad",
            prompt_hash="h",
            pack_id="asyncpg_cast",
            task_id="",
            arm_revision_id="A",
            raw_text="--- a/x\n+++ b/x\n@@ -0,0 +1 @@\n+pass\n",
        ),
        FrozenCompletion(
            burst_id="bad",
            prompt_hash="h",
            pack_id="asyncpg_cast",
            task_id="",
            arm_revision_id="B",
            raw_text="--- a/x\n+++ b/x\n@@ -0,0 +1 @@\n+pass\n",
        ),
    ]
    with pytest.raises(BakeoffContractError):
        run_phase_b(rows, smoke_n=1, anchor_min=0.99)


def test_attempt5_amendment_filed():
    ticket = REPO / "docs" / "ln7" / "tickets" / "ATTEMPT5_DECOUPLED_BAKEOFF.md"
    assert ticket.is_file()
    text = ticket.read_text(encoding="utf-8")
    assert "Decouple inference from scoring" in text
    assert "LN7_BURST_ALLOW_PAID=1" in text
    assert "Nothing in this amendment authorizes GPU spend" in text
