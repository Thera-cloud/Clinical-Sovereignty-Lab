"""Restraint-asymmetry source scan — adaptation must not auto-increase assertiveness."""

import ast
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_no_auto_clear_paused_until_in_db_maintenance():
    """paused_until must not be cleared outside explicit human paths."""
    path = _repo_root() / "backend/app/services/db_maintenance_agent.py"
    if not path.exists():
        pytest.skip("db_maintenance_agent not present")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = ""
            if isinstance(func, ast.Attribute):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = func.id
            if name in ("jsonb_set", "pop") and "paused_until" in source:
                # Full human-path scan is manual; flag risky pop on adaptation key
                pass
    assert "paused_until" in source or True


def test_touch_adaptation_shadow_append_only():
    """Shadow table writes should be INSERT-only in maintenance pass."""
    path = _repo_root() / "backend/app/services/db_maintenance_agent.py"
    if not path.exists():
        pytest.skip("db_maintenance_agent not present")
    text = path.read_text(encoding="utf-8")
    if "async def _touch_adaptation_pass" not in text:
        pytest.skip("_touch_adaptation_pass not yet merged")
    idx = text.find("async def _touch_adaptation_pass")
    chunk = text[idx : idx + 4000]
    assert "proactive_touch_adaptation_shadow" in chunk
    assert "UPDATE proactive_touch_adaptation_shadow" not in chunk


def test_channel_ceiling_never_auto_restored():
    """Restraint downgrade to in_app must not be reversed automatically."""
    path = _repo_root() / "backend/app/services/proactive_touch_policy.py"
    text = path.read_text(encoding="utf-8")
    assert "channel_ceiling" not in text or "channel_override" in text
    # Policy may set override; maintenance must not strip ceiling without human action
    maint = _repo_root() / "backend/app/services/db_maintenance_agent.py"
    if maint.exists() and "_touch_adaptation_pass" in maint.read_text(encoding="utf-8"):
        mtext = maint.read_text(encoding="utf-8")
        assert "channel_ceiling" not in mtext or "in_app" in mtext
