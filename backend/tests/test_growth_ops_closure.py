"""Ops-closure tests: Dual-COO growth kinds, authority map, hive dispatch.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import asyncio

from app.services.growth.authority_map import (
    POLICY_FACTORY_SYSTEM,
    social_strategy_owner,
)
from app.services.growth.growth_hive import FACTORY_DIGEST_MIN, _dispatch_kind
from app.websocket.cli_dual_coo import RISK_GREEN, RISK_YELLOW, classify_risk
from app.websocket.cli_task_bus import GROWTH_TASK_KINDS


def test_growth_kinds_risk_tiers():
    assert classify_risk(kind="growth_policy_cross_review") == RISK_YELLOW
    assert classify_risk(kind="growth_weekly_digest") == RISK_YELLOW
    assert classify_risk(kind="growth_segment_propose") == RISK_YELLOW
    assert classify_risk(kind="growth_experiment_conclude") == RISK_GREEN


def test_growth_kinds_complete():
    assert GROWTH_TASK_KINDS == frozenset({
        "growth_policy_cross_review",
        "growth_weekly_digest",
        "growth_segment_propose",
        "growth_experiment_conclude",
    })


def test_authority_map_social_owner():
    assert social_strategy_owner() == "MarketingBrain"
    assert POLICY_FACTORY_SYSTEM == "factory_system_prompt"


def test_factory_digest_min_default():
    assert FACTORY_DIGEST_MIN >= 2


def test_dispatch_unknown_kind():
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    out = loop.run_until_complete(
        _dispatch_kind(None, "growth_not_real")
    )
    assert out.get("ok") is False
