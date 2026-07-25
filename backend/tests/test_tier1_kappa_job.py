"""Offline smoke for async κ job module (no LLM)."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

_SVC = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "tier1_kappa_job.py"
)


def test_kappa_job_module_exists():
    assert _SVC.is_file()


def test_kappa_job_exports():
    tree = ast.parse(_SVC.read_text(encoding="utf-8"))
    names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "start_kappa_job" in names
    assert "get_job" in names
    assert "latest_job" in names


def test_load_module():
    spec = importlib.util.spec_from_file_location("tier1_kappa_job_iso", _SVC)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    assert mod.get_job("missing") is None
    assert mod.latest_job() is None


def test_readiness_script_present():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "tier1_gold_d14b_readiness.py"
    )
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "auth_ok" in text
    assert "compute_tier1_gold_kappa" in text
