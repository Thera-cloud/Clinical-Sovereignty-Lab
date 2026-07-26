"""Offline: TIER1_SOAK_WAIVED is wired into gate + weekly-live allow path."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_gate_script_mentions_soak_waive():
    src = (ROOT / "backend/scripts/clinical_tier1_competence_gate_check.py").read_text()
    assert "TIER1_SOAK_WAIVED" in src
    assert "soak_waived" in src


def test_battery_agent_weekly_live_checks_soak_waive():
    src = (ROOT / "backend/app/services/six_quotient_battery_agent.py").read_text()
    assert "TIER1_SOAK_WAIVED" in src
    tree = ast.parse(src)
    names = {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_weekly_live_allowed" in names


def test_compose_exposes_soak_waive():
    src = (ROOT / "docker-compose.prod.yml").read_text()
    assert "TIER1_SOAK_WAIVED" in src
