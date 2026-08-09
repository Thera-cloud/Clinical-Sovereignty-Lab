"""Close #17 — named cohort roster → 40 / N/N named (not vacuous 100)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.ln7_close_percent_engine import _h_pilot


@pytest.mark.asyncio
async def test_pilot_named_roster_scores_40(tmp_path: Path):
    prereg = {
        "pre_registered_success_numbers": {"n_planned": 15},
        "first_cohort": {
            "enrolled_n": 15,
            "enrolled_usernames": [f"user{i}" for i in range(15)],
        },
    }
    p = tmp_path / "pilot_prereg.json"
    p.write_text(json.dumps(prereg), encoding="utf-8")

    with patch(
        "app.services.ln7_close_percent_engine._resolve_path",
        return_value=p,
    ):
        score = await _h_pilot(
            None,
            {"item_id": "#17", "tier": "HUMAN", "title": "pilot", "owner": "ceo", "weight": 1.0},
            {},
            {},
        )
    assert score.pct == 40.0
    assert score.display == "15/15 named"


def test_pilot_async_wrapper():
    asyncio.get_event_loop()  # collection safety
