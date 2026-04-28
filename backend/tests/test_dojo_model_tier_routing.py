"""
DOJO per-type model-tier routing contract test.

Verifies the routing table in bridge_server.py (`_DOJO_TYPE_MODEL_TIER` and
`_DOJO_TIER_TO_SIGNAL`) against the spec defined in the Apr 27, 2026 fix:
  tension     → odpe_signal="TENSION"  → grok primary (premium)
  workers_ai  → odpe_signal="LOCKED"   → workers_ai primary (free)
  auto        → no signal              → ODPE classifies normally

Non-DOJO chat (no dojo_type field) ALWAYS falls through to ODPE — this table is
opt-in. Test imports the literal dicts from bridge_server.py to catch any drift
between the routing table and this spec.

Why this exists: CoachN saw weak responses in DOJO comments because ODPE
classified the message as LOCKED and routed to free Workers AI when the scenario
clearly warranted Grok premium. The routing table makes the cost/quality
tradeoff explicit per scenario.
"""

import importlib.util
import pathlib
import re
import pytest


def _load_dojo_routing_tables():
    """
    Extract _DOJO_TYPE_MODEL_TIER and _DOJO_TIER_TO_SIGNAL from bridge_server.py
    via AST-style parsing. Avoids importing bridge_server.py (27k lines, heavy
    side effects on import).
    """
    src = pathlib.Path("backend/app/websocket/bridge_server.py").read_text()
    # Extract the two literal-dict definitions
    ns = {}
    m = re.search(r"^_DOJO_TYPE_MODEL_TIER = \{[\s\S]*?^\}", src, re.MULTILINE)
    assert m, "_DOJO_TYPE_MODEL_TIER not found in bridge_server.py"
    exec(m.group(0), ns)
    m = re.search(r"^_DOJO_TIER_TO_SIGNAL = \{[^}]+\}", src, re.MULTILINE)
    assert m, "_DOJO_TIER_TO_SIGNAL not found in bridge_server.py"
    exec(m.group(0), ns)
    return ns["_DOJO_TYPE_MODEL_TIER"], ns["_DOJO_TIER_TO_SIGNAL"]


@pytest.fixture(scope="module")
def routing():
    return _load_dojo_routing_tables()


# Spec from user's request (Apr 27, 2026)
EXPECTED_TIER = {
    "pitch_practice": "tension",
    "financial_analysis": "tension",
    "market_strategy": "tension",
    "client_acquisition": "workers_ai",
    "operations": "workers_ai",
    "leadership": "tension",
    "therapist": "tension",
    "crisis": "workers_ai",
    "hostile": "workers_ai",
    "judge": "tension",
    "mcat": "tension",
    "project_pm": "workers_ai",
    "cnc": "workers_ai",
    "teacher": "workers_ai",
    "coach_nate": "tension",
}


def test_all_15_dojo_scenarios_present(routing):
    table, _ = routing
    missing = set(EXPECTED_TIER) - set(table)
    extra = set(table) - set(EXPECTED_TIER)
    assert not missing, f"DOJO scenarios missing from routing table: {missing}"
    assert not extra, f"Unexpected DOJO scenarios in routing table: {extra}"


def test_tier_assignments_match_spec(routing):
    table, _ = routing
    mismatches = {k: (table[k], v) for k, v in EXPECTED_TIER.items() if table[k] != v}
    assert not mismatches, f"Tier mismatches (got, expected): {mismatches}"


def test_tier_to_signal_mapping(routing):
    _, sig = routing
    assert sig["tension"] == "TENSION", "premium tier must map to TENSION ODPE signal"
    assert sig["workers_ai"] == "LOCKED", "free tier must map to LOCKED ODPE signal"
    assert sig["auto"] is None, "auto tier must map to None (let ODPE classify)"


def test_resolution_pipeline_scenarios(routing):
    """End-to-end resolution: dojo_type → tier → odpe_signal."""
    table, sig = routing

    def resolve(dojo_type):
        tier = table.get((dojo_type or "").lower())
        return sig.get(tier) if tier else None

    assert resolve("therapist") == "TENSION"
    assert resolve("THERAPIST") == "TENSION"  # case-insensitive
    assert resolve("crisis") == "LOCKED"
    assert resolve("hostile") == "LOCKED"
    assert resolve("coach_nate") == "TENSION"
    assert resolve(None) is None  # non-DOJO chat → ODPE default
    assert resolve("") is None
    assert resolve("nonexistent_dojo") is None  # unknown → ODPE default


def test_premium_scenarios_are_high_stakes(routing):
    """
    Sanity check the cost/quality tradeoff: high-stakes scenarios (clinical,
    legal, medical, leadership, financial pitches) must route to premium.
    Drilling-style scenarios (rote practice, simple acquisition) get free tier.
    """
    table, _ = routing
    high_stakes = {"therapist", "judge", "mcat", "leadership", "pitch_practice",
                   "financial_analysis", "market_strategy", "coach_nate"}
    for scenario in high_stakes:
        assert table[scenario] == "tension", (
            f"{scenario} is high-stakes — must route to premium tier (tension)"
        )
