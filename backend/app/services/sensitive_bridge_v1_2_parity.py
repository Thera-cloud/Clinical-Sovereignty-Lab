"""v1.2 parity runner — thin shim for the Phase 6 auditor.

Loads the three `<contract>_v1_2_fixtures.json` files in
`backend/tests/fixtures/` and dispatches each fixture through the contract
under audit. Returns a verdict dict per contract that the
`sensitive_bridge_auditor` translates into a `phase3_*_v1_2_fixtures_pass`
boolean.

Per Phase 5 Note 3: this is NOT a test framework. CI continues to use pytest
for blocking-on-merge. This runner gives the auditor a programmatic verdict
at boot/audit time. Each function is intentionally ~30-40 lines.

Per Phase 5 Note 2: fixtures live in `backend/tests/fixtures/` matching the
existing pattern (clinical_arousal_lexicon_test.json, somatic_resource_*).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def _load(name: str) -> Dict[str, Any]:
    """Load a fixture file. Raises on missing/malformed file (fail-loud)."""
    path = _FIXTURE_DIR / name
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _verdict(check_id: str, failures: List[Dict[str, str]], total: int) -> Dict[str, Any]:
    return {
        "check_id": check_id,
        "passed": total - len(failures),
        "failed": len(failures),
        "total": total,
        "ok": len(failures) == 0,
        "failures": failures,
    }


def assert_controller_v1_2_parity() -> Dict[str, Any]:
    """Dispatch controller_v1_2_fixtures.json through pinned v1.2 constants."""
    from app.services.therapeutic_controller import (  # type: ignore
        _PHASE_V1_2_BANNED_PHRASES,
        _PHASE_V1_2_REGISTER_VARIANTS,
        _PHASE_V1_3_NEW_REGISTERS,
        _resolve_banned_phrases,
    )

    data = _load("controller_v1_2_fixtures.json")
    fixtures = data["fixtures"]
    failures: List[Dict[str, str]] = []
    v1_2_set = set(_PHASE_V1_2_REGISTER_VARIANTS)
    v1_3_set = set(_PHASE_V1_3_NEW_REGISTERS)

    for fx in fixtures:
        kind, exp = fx["kind"], fx["expected"]
        if kind in ("v1_2_register_variant_resolved", "v1_3_register_variant_not_in_v1_2"):
            v = fx["input"]["variant"]
            ok = ((v in v1_2_set) == exp["is_v1_2_variant"]) and (
                (v in v1_3_set and v not in v1_2_set) == exp["is_v1_3_only"]
            )
        elif kind == "v1_2_banned_phrase_present":
            resolved = set(_resolve_banned_phrases(fx["input"]["locale"]))
            ok = (fx["input"]["phrase"] in resolved) == exp["present_in_resolved_set"]
        elif kind == "v1_3_banned_phrase_added_without_displacing_v1_2":
            resolved = set(_resolve_banned_phrases(fx["input"]["locale"]))
            v1_2_kept = sum(1 for p in _PHASE_V1_2_BANNED_PHRASES if p in resolved)
            ok = (fx["input"]["new_phrase"] in resolved) == exp["new_phrase_in_resolved_set"] \
                and v1_2_kept == exp["v1_2_phrase_count_preserved"]
        else:
            ok = False
        if not ok:
            failures.append({"id": fx["id"], "reason": f"kind={kind} expected={exp}"})
    return _verdict("phase3_controller_v1_2_fixtures_pass", failures, len(fixtures))


def assert_mandatory_reporting_v1_2_parity() -> Dict[str, Any]:
    """Dispatch mandatory_reporting_v1_2_fixtures.json through pinned v1.2 layer."""
    from app.models.governance import ReportingTrigger  # type: ignore
    from app.services.governance.mandatory_reporting import (  # type: ignore
        _SCREEN_MESSAGE_RAW_MATCH_TRIGGERS,
        TRIGGER_PATTERNS,
    )

    data = _load("mandatory_reporting_v1_2_fixtures.json")
    fixtures = data["fixtures"]
    failures: List[Dict[str, str]] = []

    def _v1_2_scan(message: str):
        lower = message.lower()
        for trig in _SCREEN_MESSAGE_RAW_MATCH_TRIGGERS:
            for pat in TRIGGER_PATTERNS.get(trig, []):
                if pat in lower:
                    return trig, pat
        return None, None

    for fx in fixtures:
        kind, inp, exp = fx["kind"], fx["input"], fx["expected"]
        trig, pat = _v1_2_scan(inp["message"])
        if kind == "v1_2_raw_match_fires":
            expected_enum = getattr(ReportingTrigger, inp["expected_trigger"])
            ok = (trig is not None) == exp["trigger_fires"] and trig == expected_enum \
                and (pat is not None and exp["matched_pattern_substring"] in pat)
        elif kind in (
            "trafficking_pattern_excluded_from_v1_2_raw_match",
            "unclassified_classification_does_not_hijack_v1_2_signature",
        ):
            ok = (trig is not None) == exp["trigger_fires_in_v1_2_path"]
        else:
            ok = False
        if not ok:
            failures.append({"id": fx["id"], "reason": f"kind={kind} matched_trig={trig} pat={pat}"})
    return _verdict("phase3_mandatory_reporting_v1_2_fixtures_pass", failures, len(fixtures))


def assert_coach_override_v1_2_parity() -> Dict[str, Any]:
    """Dispatch coach_override_v1_2_fixtures.json through pinned v1.2 sets."""
    from app.services.coach_override_protocol import (  # type: ignore
        _ACUITY_TIERS_V1_2,
        _ALLOWED_FOCUS_DOMAINS_V1_2,
        ACUITY_TIERS,
        ALLOWED_FOCUS_DOMAINS,
        merge_override_payload,
    )

    data = _load("coach_override_v1_2_fixtures.json")
    fixtures = data["fixtures"]
    failures: List[Dict[str, str]] = []

    for fx in fixtures:
        kind, inp, exp = fx["kind"], fx["input"], fx["expected"]
        if kind == "v1_2_focus_domain_dispatches":
            merged = merge_override_payload(None, {"focus_domain": inp["focus_domain"]})
            ok = merged["focus_domain"] == exp["merged_focus_domain"] \
                and (inp["focus_domain"] in _ALLOWED_FOCUS_DOMAINS_V1_2) == exp["is_v1_2_domain"]
        elif kind == "v1_3_focus_domain_added_without_displacing_v1_2":
            d = inp["focus_domain"]
            ok = (d in _ALLOWED_FOCUS_DOMAINS_V1_2) == exp["is_v1_2_domain"] \
                and (d in ALLOWED_FOCUS_DOMAINS) == exp["in_current_allowed_domains"] \
                and len(_ALLOWED_FOCUS_DOMAINS_V1_2) == exp["v1_2_domain_count_preserved"]
        elif kind == "v1_3_acuity_tier_name_does_not_collide_with_v1_2":
            t = inp["tier_name"]
            ok = (t in _ACUITY_TIERS_V1_2) == exp["in_v1_2_acuity_tiers"] \
                and (t in ACUITY_TIERS) == exp["in_current_acuity_tiers"]
        else:
            ok = False
        if not ok:
            failures.append({"id": fx["id"], "reason": f"kind={kind} expected={exp}"})
    return _verdict("phase3_coach_override_v1_2_fixtures_pass", failures, len(fixtures))


def run_all_v1_2_parity_checks() -> Dict[str, Dict[str, Any]]:
    """Convenience aggregator. The Phase 6 auditor calls this once per cycle."""
    return {
        "controller": assert_controller_v1_2_parity(),
        "mandatory_reporting": assert_mandatory_reporting_v1_2_parity(),
        "coach_override": assert_coach_override_v1_2_parity(),
    }
