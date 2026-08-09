"""Close #17 — named cohort roster → 40 / N/N named (not vacuous 100)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_pilot_named_roster_scores_40(tmp_path: Path):
    from app.services import ln7_close_percent_engine as eng

    prereg = {
        "pre_registered_success_numbers": {"n_planned": 15},
        "first_cohort": {
            "enrolled_n": 15,
            "enrolled_usernames": [f"user{i}" for i in range(15)],
        },
    }
    p = tmp_path / "pilot_prereg.json"
    p.write_text(json.dumps(prereg), encoding="utf-8")

    with patch.object(eng, "_resolve_path", return_value=p):
        score = await eng._h_pilot(
            None,
            {
                "item_id": "#17",
                "tier": "HUMAN",
                "title": "pilot",
                "owner": "ceo",
                "weight": 1.0,
                "pct": None,
                "display": "",
                "evidence_uri": "",
            },
            {},
            {},
        )
    assert score.pct == 40.0
    assert score.display == "15/15 named"
