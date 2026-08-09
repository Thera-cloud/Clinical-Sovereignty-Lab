"""Fence: Branch 1 screener-permanent marker is present and engine-wired."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARKER = ROOT / "docs" / "ln7" / "evidence" / "v7_screener_permanent.json"
ENGINE = ROOT / "backend" / "app" / "services" / "ln7_close_percent_engine.py"


def test_marker_declares_branch_1():
    data = json.loads(MARKER.read_text(encoding="utf-8"))
    assert data["decision"] == "screener_permanent"
    assert data["branch"] == 1
    assert data["evidence_id"] == 12
    assert data["effects"]["certify_opens"] is False
    assert data["effects"]["weekly_live"] is False


def test_engine_reads_marker_path():
    src = ENGINE.read_text(encoding="utf-8")
    assert "v7_screener_permanent.json" in src
    assert "100(screener-permanent)" in src
