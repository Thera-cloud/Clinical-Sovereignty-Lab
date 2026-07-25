"""Offline unit tests for D.14b evidence writers (no app package import — macOS numpy)."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

_SVC = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "tier1_gold_evidence.py"
)


def _load_mod():
    spec = importlib.util.spec_from_file_location("tier1_gold_evidence_iso", _SVC)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ev():
    return _load_mod()


def test_perfect_agreement_kappa_is_one(ev):
    gold = [0, 1, 2, 3, 2, 1]
    assert ev.quadratic_weighted_kappa_0_3(gold, gold) == pytest.approx(1.0)


def test_mean_per_dimension_kappa_perfect(ev):
    rows = [
        {"primary": 2, "accuracy": 2, "naturalness": 3},
        {"primary": 1, "accuracy": 2, "naturalness": 2},
        {"primary": 3, "accuracy": 3, "naturalness": 3},
    ]
    agg, per = ev.mean_per_dimension_kappa(rows, rows)
    assert agg == pytest.approx(1.0)
    assert per["primary"] == pytest.approx(1.0)
    assert ev.KAPPA_METHOD == "quadratic_weighted_per_dimension_mean"


def test_disagreement_lowers_kappa(ev):
    g = [{"primary": 3, "accuracy": 3, "naturalness": 3}] * 8
    p = [{"primary": 0, "accuracy": 0, "naturalness": 0}] * 8
    agg, _ = ev.mean_per_dimension_kappa(g, p)
    assert agg < 0.3


def test_harmful_miss_degraded_safety(ev):
    assert ev.is_harmful_miss(
        response_class="escalate_or_safety",
        safety_veto="fail",
        is_degraded_distractor=True,
        gold_primary=0,
        judge_primary=3,
    )
    assert not ev.is_harmful_miss(
        response_class="escalate_or_safety",
        safety_veto="fail",
        is_degraded_distractor=True,
        gold_primary=0,
        judge_primary=1,
    )


def test_compute_safety_veto_ok_and_fail(ev):
    gold = [
        {
            "scenario_id": "AQ-1",
            "response_class": "escalate_or_safety",
            "safety_veto": "fail",
            "is_degraded_distractor": True,
            "primary_score": 0,
        }
    ]
    ok, n, ids = ev.compute_safety_veto(
        gold, {"AQ-1": {"primary": 3, "accuracy": 2, "naturalness": 2}}
    )
    assert ok is False and n == 1 and ids == ["AQ-1"]
    ok2, n2, _ = ev.compute_safety_veto(
        gold, {"AQ-1": {"primary": 0, "accuracy": 0, "naturalness": 1}}
    )
    assert ok2 is True and n2 == 0


def test_principal_review_evidence_routes_present():
    src = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "principal_review_api.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    paths = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            if dec.func.attr not in ("get", "post") or not dec.args:
                continue
            a0 = dec.args[0]
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                paths.add(a0.value)
    for p in (
        "/gold/kappa/latest",
        "/gold/kappa/ingest",
        "/gold/kappa/compute",
        "/gold/recheck/session/start",
        "/gold/recheck/items",
        "/gold/recheck/score",
        "/gold/recheck/finalize",
        "/gold/reliability/latest",
    ):
        assert p in paths, f"missing {p}"


def test_migration_275_present():
    mig = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "275_tier1_gold_recheck_scores.sql"
    )
    assert mig.is_file()
    assert "six_quotient_gold_recheck_scores" in mig.read_text(encoding="utf-8")


def test_cli_kappa_script_exists():
    p = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "compute_tier1_gold_kappa.py"
    )
    assert p.is_file()
    assert "persist_kappa_evidence" in p.read_text(encoding="utf-8")


def test_dashboard_has_recheck_and_evidence():
    html = (
        Path(__file__).resolve().parents[2]
        / "dashboard"
        / "principal_review.html"
    ).read_text(encoding="utf-8")
    assert "panel-recheck" in html
    assert "panel-evidence" in html
    assert "/gold/recheck/finalize" in html
