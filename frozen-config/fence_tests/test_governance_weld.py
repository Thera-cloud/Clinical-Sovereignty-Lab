"""Fence: governance.json must expose required weld keys.

Lives under frozen-config (Queens SA must not write this tree).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_governance_has_bakeoff_margin():
    data = json.loads((ROOT / "governance.json").read_text(encoding="utf-8"))
    assert "bakeoff_margin" in data
    assert float(data["bakeoff_margin"]) >= 0


def test_checklist_has_required_items():
    data = json.loads((ROOT / "dual_coo_checklist.json").read_text(encoding="utf-8"))
    ids = {c["id"] for c in data["checklist"]}
    assert "heldout_not_in_train" in ids
    assert "fence_manifest_ok" in ids


def test_goodhart_probes_have_metrics():
    data = json.loads((ROOT / "goodhart_probes.json").read_text(encoding="utf-8"))
    assert len(data.get("metrics") or []) >= 3
