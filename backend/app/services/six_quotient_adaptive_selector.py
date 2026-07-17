"""
Adaptive battery selection — anchors + IRT max-info + weak-quotient bias.

Falls back to static v4 pack when bank empty / flag off.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.six_quotient_irt import select_max_info, section_thetas
from app.services.six_quotient_scenario_bank import (
    bank_row_to_scenario,
    get_ability,
    list_bank,
)

logger = logging.getLogger("sovereign.six_quotient_selector")

_QUOTIENTS = ("IQ", "EQ", "MQ", "SQ", "CQ", "AQ")
_ANCHOR_KEYS = {f"{q}-{i}" for q in _QUOTIENTS for i in (1, 2)}  # 12 anchors


def _living_on() -> bool:
    return os.getenv("ENABLE_SIX_QUOTIENT_LIVING_BATTERY", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _v4_scenarios() -> List[Dict[str, Any]]:
    path = Path(__file__).resolve().parents[1] / "data" / "six_quotient_scenarios_v4.json"
    if not path.exists():
        path = Path("/app/app/data/six_quotient_scenarios_v4.json")
    with open(path, encoding="utf-8") as f:
        pack = json.load(f)
    return pack.get("scenarios") or []


async def select_battery(
    db_pool,
    *,
    environment: str = "staging",
    limit: int = 0,
    gap_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Returns {scenarios, mode, theta, weak_sections}.
    mode: v4_static | living_adaptive
    """
    target_n = limit if limit and limit > 0 else 24

    if not _living_on() or not db_pool:
        sc = _v4_scenarios()[:target_n]
        return {
            "scenarios": sc,
            "mode": "v4_static",
            "theta": 0.0,
            "weak_sections": [],
            "battery_version": "v4",
        }

    try:
        approved = await list_bank(db_pool, status="approved", limit=500)
    except Exception as e:
        logger.warning("bank list failed, falling back to v4: %s", e)
        sc = _v4_scenarios()[:target_n]
        return {
            "scenarios": sc,
            "mode": "v4_static_fallback",
            "theta": 0.0,
            "weak_sections": [],
            "battery_version": "v4",
        }

    if len(approved) < 12:
        sc = _v4_scenarios()[:target_n]
        return {
            "scenarios": sc,
            "mode": "v4_static_bank_thin",
            "theta": 0.0,
            "weak_sections": [],
            "battery_version": "v4",
        }

    ability = await get_ability(db_pool, environment)
    theta = float(ability.get("theta") or 0.0)
    tbs = section_thetas(ability.get("theta_by_section") or {}, default=theta)

    # Weak sections from last gap or from section thetas
    weak: List[str] = []
    if gap_summary and isinstance(gap_summary.get("quotients"), dict):
        for q, meta in gap_summary["quotients"].items():
            if (meta or {}).get("risk") in ("RED", "YELLOW"):
                weak.append(q.upper())
    if not weak:
        # lowest thetas
        weak = [q for q, _ in sorted(tbs.items(), key=lambda kv: kv[1])[:2]]

    by_key = {r["scenario_key"]: r for r in approved}
    selected: List[Dict[str, Any]] = []
    used: set = set()

    # 1) Anchors (12) for trend continuity — prefer v4 keys
    for key in sorted(_ANCHOR_KEYS):
        if key in by_key and len(selected) < min(12, target_n):
            selected.append(bank_row_to_scenario(by_key[key]))
            used.add(key)

    # 2) Weak-section max-info fill
    remaining = target_n - len(selected)
    weak_quota = max(remaining // 2, 0)
    weak_pool = [
        r for r in approved
        if r["scenario_key"] not in used and r["section"] in weak
    ]
    for it in select_max_info(
        weak_pool,
        tbs.get(weak[0], theta) if weak else theta,
        k=weak_quota,
        exclude_keys=used,
    ):
        selected.append(bank_row_to_scenario(it))
        used.add(it["scenario_key"])

    # 3) Global max-info / boundary fill
    rest_pool = [r for r in approved if r["scenario_key"] not in used]
    need = target_n - len(selected)
    for it in select_max_info(rest_pool, theta, k=need, exclude_keys=used):
        selected.append(bank_row_to_scenario(it))
        used.add(it["scenario_key"])

    # Ensure each quotient has ≥1
    have = {s["section"] for s in selected}
    for q in _QUOTIENTS:
        if q not in have:
            for r in approved:
                if r["section"] == q and r["scenario_key"] not in used:
                    selected.append(bank_row_to_scenario(r))
                    used.add(r["scenario_key"])
                    break

    return {
        "scenarios": selected[:target_n],
        "mode": "living_adaptive",
        "theta": theta,
        "theta_by_section": tbs,
        "weak_sections": weak,
        "battery_version": "v5",
    }
