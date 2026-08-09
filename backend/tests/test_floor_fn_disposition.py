"""Close #5 — structure_pass_quality_fail FN disposition."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def _base():
    return {
        "item_id": "#5",
        "tier": "CRANK",
        "title": "floor FN",
        "owner": "cursor",
        "weight": 1.0,
        "pct": None,
        "display": "",
        "evidence_uri": "",
        "alerts": [],
        "delta_note": "",
        "blocked_owner": None,
        "blocked_hint": "",
    }


@pytest.mark.asyncio
async def test_floor_fn_100_when_aq_v07_disposed(tmp_path):
    from app.services import ln7_close_percent_engine as eng

    replay = {
        "tp": 3,
        "tn": 2,
        "fp": 0,
        "fn": 1,
        "false_negatives": [
            {"scenario_id": "AQ-V07", "floor_checks": {"naming_or_assessment": True}}
        ],
    }
    disp = {
        "exclusions": [
            {
                "scenario_id": "AQ-V07",
                "effective": "exclude_from_fn",
                "class": "structure_pass_quality_fail",
            }
        ]
    }
    disp_path = tmp_path / "floor_fn_disposition.json"
    disp_path.write_text(json.dumps(disp))

    def fake_read(rel: str):
        if Path(rel).name == "floor_fn_disposition.json":
            return json.loads(disp_path.read_text())
        return None

    ctx = {"floor_replay": replay, "address_gate_shipped": True}
    with patch.object(eng, "_read_json_file", side_effect=fake_read):
        score = await eng._h_floor_fn(None, _base(), {}, ctx)

    assert score.pct == 100.0
    assert score.display == "100"
    assert "AQ-V07" in (score.delta_note or "")


@pytest.mark.asyncio
async def test_floor_fn_stays_80_without_disposition():
    from app.services import ln7_close_percent_engine as eng

    replay = {
        "tp": 3,
        "tn": 2,
        "fp": 0,
        "fn": 1,
        "false_negatives": [{"scenario_id": "AQ-V07"}],
    }
    ctx = {"floor_replay": replay, "address_gate_shipped": True}
    with patch.object(eng, "_read_json_file", return_value=None):
        score = await eng._h_floor_fn(None, _base(), {}, ctx)

    assert score.pct == 80.0
    assert score.display == "80"
