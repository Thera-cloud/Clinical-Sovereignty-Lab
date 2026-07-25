"""Offline smoke: Principal-Review API surface (no heavy app imports)."""
from __future__ import annotations

import ast
from pathlib import Path

_SRC = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "routers"
    / "principal_review_api.py"
)


def _src() -> str:
    return _SRC.read_text(encoding="utf-8")


def test_principal_review_file_exists():
    assert _SRC.is_file()


def test_principal_review_prefix_in_source():
    assert 'prefix="/api/admin/principal-review"' in _src()


def test_principal_review_routes_decorated():
    tree = ast.parse(_src())
    paths = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            if not isinstance(dec.func, ast.Attribute):
                continue
            if dec.func.attr not in ("get", "post", "patch", "put", "delete"):
                continue
            if not dec.args:
                continue
            arg0 = dec.args[0]
            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                paths.add(arg0.value)
            elif isinstance(arg0, ast.Str):  # py3.9
                paths.add(arg0.s)
    required = {
        "/health",
        "/gold/session/start",
        "/gold/progress",
        "/gold/items",
        "/gold/score",
        "/gold/kappa/latest",
        "/gold/kappa/ingest",
        "/gold/kappa/compute",
        "/gold/recheck/session/start",
        "/gold/recheck/items",
        "/gold/recheck/score",
        "/gold/recheck/finalize",
        "/gold/reliability/latest",
        "/library",
        "/library/generate-nate",
        "/library/{item_id}/promote",
        "/coach-shares",
        "/coach-shares/ingest",
    }
    missing = required - paths
    assert not missing, f"missing routes: {missing}"


def test_allowed_raters_include_drnevedal1():
    assert '"DrNevedal1"' in _src()


def test_migration_274_present():
    mig = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "274_principal_review_library.sql"
    )
    assert mig.is_file()
    text = mig.read_text(encoding="utf-8")
    assert "principal_review_library" in text
    assert "safety_veto" in text


def test_dashboard_page_present():
    page = (
        Path(__file__).resolve().parents[2]
        / "dashboard"
        / "principal_review.html"
    )
    assert page.is_file()
    html = page.read_text(encoding="utf-8")
    assert "Principal-Review" in html
    assert "/api/admin/principal-review" in html
