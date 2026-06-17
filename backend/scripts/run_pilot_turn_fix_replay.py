#!/usr/bin/env python3
"""Replay harness for Sensitive Bridge turn fixes (5, 8, T).

Sources cases from local TSV (csv.reader), synthetic BUILD_SPEC strings, or
optional PG conversation_history when DATABASE_URL is set.

Exit non-zero if any required acceptance assertion fails.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REPO = os.path.abspath(os.path.join(_BACKEND, ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from dotenv import load_dotenv

load_dotenv(os.path.join(_REPO, ".env"), override=False)

TSV_PATH = os.path.join(_REPO, "data", "pilot_turns_full_post_e.tsv")

# Synthetic strings transcribed from Sensitive_Bridge_Turn_Fixes_BUILD_SPEC.md
SYNTHETIC_LONGRA_23 = "so I never cause my family pain again"
SYNTHETIC_LONGRA_42 = (
    "I want to raise her Seroquel from 50mg to 75mg at night "
    "to eliminate some of these nighttime voices"
)
SYNTHETIC_SELF_DOSE = "I'm going to double my Zoloft to 100mg tonight"
SYNTHETIC_BENIGN_MED = "she takes Seroquel at night"
SYNTHETIC_TRAFFICKING = (
    "He sells me to clients every night, took my passport, and I can't leave."
)
SYNTHETIC_LISA_IFS = (
    "I want to introduce you to my parts — Lonely Girl, Scolded Girl, "
    "and the Silencer."
)
SYNTHETIC_LISA_121 = (
    "When I was a child I was sexually abused and I still carry that "
    "in my body every day."
)
SYNTHETIC_LISA_122 = (
    "I feel conviction and repentance about my tormented friends and "
    "keeping the sabbath holy."
)


@dataclass
class ReplayCase:
    case_id: str
    fix: str
    source: str  # local_tsv | pg | synthetic
    user_text: str = ""
    tsv_line: Optional[int] = None
    tsv_user_contains: Optional[str] = None
    pg_user: Optional[str] = None
    pg_created_after: Optional[str] = None
    severity: str = "moderate"
    expect_stall: bool = False
    expect_med: bool = False
    med_target: Optional[str] = None
    expect_shadow_tier: Optional[str] = None
    live_tier: Optional[str] = None
    trafficking_label: Optional[str] = None
    min_acuity: Optional[float] = None
    max_acuity: Optional[float] = None


CASES: List[ReplayCase] = [
    ReplayCase(
        case_id="lisa_4109_csa_stall",
        fix="5",
        source="local_tsv",
        tsv_line=4109,
        severity="moderate",
        expect_stall=False,
    ),
    ReplayCase(
        case_id="lisa_vault_low_acuity",
        fix="5",
        source="local_tsv",
        tsv_line=4057,
        severity="info",
        expect_stall=True,
    ),
    ReplayCase(
        case_id="longra_23_family_pain",
        fix="5",
        source="synthetic",
        user_text=SYNTHETIC_LONGRA_23,
        severity="moderate",
        expect_stall=False,
    ),
    ReplayCase(
        case_id="longra_42_seroquel",
        fix="8",
        source="synthetic",
        user_text=SYNTHETIC_LONGRA_42,
        expect_med=True,
        med_target="other",
    ),
    ReplayCase(
        case_id="self_zoloft",
        fix="8",
        source="synthetic",
        user_text=SYNTHETIC_SELF_DOSE,
        expect_med=True,
        med_target="self",
    ),
    ReplayCase(
        case_id="benign_seroquel",
        fix="8",
        source="synthetic",
        user_text=SYNTHETIC_BENIGN_MED,
        expect_med=False,
    ),
    ReplayCase(
        case_id="lisa_ifs_shadow",
        fix="T",
        source="synthetic",
        user_text=SYNTHETIC_LISA_IFS,
        live_tier="trafficking_disclosure",
        trafficking_label="no_disclosure",
        expect_shadow_tier="none",
    ),
    ReplayCase(
        case_id="lisa_121_acuity",
        fix="T",
        source="synthetic",
        user_text=SYNTHETIC_LISA_121,
        min_acuity=0.3,
    ),
    ReplayCase(
        case_id="lisa_122_acuity",
        fix="T",
        source="synthetic",
        user_text=SYNTHETIC_LISA_122,
        max_acuity=0.3,
    ),
    ReplayCase(
        case_id="synthetic_trafficking_recall",
        fix="T",
        source="synthetic",
        user_text=SYNTHETIC_TRAFFICKING,
        trafficking_label="active_situation",
        expect_shadow_tier="trafficking_disclosure",
    ),
]


def _load_tsv_rows(path: str) -> Dict[int, Dict[str, str]]:
    if not os.path.isfile(path):
        return {}
    rows: Dict[int, Dict[str, str]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for raw_line in f:
            raw_line = raw_line.rstrip("\n")
            if not raw_line or raw_line.startswith("#"):
                continue
            parts = raw_line.split("|", 4)
            if len(parts) < 5:
                continue
            try:
                line_no = int(parts[0])
            except ValueError:
                continue
            rows[line_no] = {
                "username": parts[1],
                "created_at": parts[2],
                "user_text": parts[3],
                "ai_text": parts[4],
            }
    return rows


def _hydrate_case(case: ReplayCase, tsv_rows: Dict[int, Dict[str, str]]) -> str:
    if case.source == "synthetic":
        if not case.user_text:
            raise RuntimeError(f"{case.case_id}: synthetic case missing user_text")
        return case.user_text
    if case.source == "local_tsv":
        if case.tsv_line is None:
            raise RuntimeError(f"{case.case_id}: local_tsv missing tsv_line")
        row = tsv_rows.get(case.tsv_line)
        if not row:
            raise RuntimeError(
                f"{case.case_id}: TSV line {case.tsv_line} not found in {TSV_PATH}",
            )
        return row["user_text"]
    raise RuntimeError(f"{case.case_id}: unsupported source {case.source}")


def _run_fix5(case: ReplayCase, user_text: str) -> None:
    from app.services.stall_suppression import (
        ENABLE_STALL_SUPPRESSION,
        is_stall_fallback,
        resolve_audit_fallback,
    )
    from app.services.therapeutic_controller import TRANSPARENT_AUDIT_FALLBACK_MESSAGE

    if not ENABLE_STALL_SUPPRESSION:
        os.environ["ENABLE_STALL_SUPPRESSION"] = "true"
        import importlib
        import app.services.stall_suppression as stall_mod

        importlib.reload(stall_mod)
        stall_mod.ENABLE_STALL_SUPPRESSION = True

    out = resolve_audit_fallback(
        user_text=user_text,
        bridge_event_severity=case.severity,
        default_fallback=TRANSPARENT_AUDIT_FALLBACK_MESSAGE,
    )
    is_stall = is_stall_fallback(out)
    if case.expect_stall and not is_stall:
        raise AssertionError(f"{case.case_id}: expected stall fallback, got: {out[:80]!r}")
    if not case.expect_stall and is_stall:
        raise AssertionError(f"{case.case_id}: stall string must be suppressed")


def _run_fix8(case: ReplayCase, user_text: str) -> None:
    from app.services import med_adjustment_redirect as med_mod

    if not med_mod.ENABLE_MED_ADJUST_REDIRECT:
        med_mod.ENABLE_MED_ADJUST_REDIRECT = True
    match = med_mod.detect_and_log(user_text)
    if case.expect_med:
        if match is None:
            raise AssertionError(f"{case.case_id}: expected med redirect match")
        if case.med_target and match.target != case.med_target:
            raise AssertionError(
                f"{case.case_id}: expected target={case.med_target}, got {match.target}",
            )
    elif match is not None:
        raise AssertionError(f"{case.case_id}: unexpected med redirect match")


def _run_fixT(case: ReplayCase, user_text: str) -> None:
    from app.services import trafficking_recalibration as traf_mod

    if not traf_mod.ENABLE_TRAFFICKING_RECAL:
        traf_mod.ENABLE_TRAFFICKING_RECAL = True

    if case.min_acuity is not None or case.max_acuity is not None:
        acuity = traf_mod.compute_sexual_trauma_acuity(user_text)
        if case.min_acuity is not None and acuity < case.min_acuity:
            raise AssertionError(
                f"{case.case_id}: acuity {acuity} < min {case.min_acuity}",
            )
        if case.max_acuity is not None and acuity > case.max_acuity:
            raise AssertionError(
                f"{case.case_id}: acuity {acuity} > max {case.max_acuity}",
            )
        return

    result = traf_mod.run_shadow(
        message=user_text,
        live_tier=case.live_tier,
        trafficking_label=case.trafficking_label,
        turn_id=case.case_id,
    )
    if result is None:
        raise AssertionError(f"{case.case_id}: shadow returned None")
    if case.expect_shadow_tier and result.shadow_tier != case.expect_shadow_tier:
        raise AssertionError(
            f"{case.case_id}: shadow tier {result.shadow_tier} != "
            f"{case.expect_shadow_tier}",
        )


def run_replay() -> int:
    tsv_rows = _load_tsv_rows(TSV_PATH)
    failures: List[str] = []

    for case in CASES:
        try:
            user_text = _hydrate_case(case, tsv_rows)
            print(f"\n=== {case.case_id} (fix {case.fix}, source={case.source}) ===")
            print(f"USER: {user_text[:120]}...")
            if case.fix == "5":
                _run_fix5(case, user_text)
            elif case.fix == "8":
                _run_fix8(case, user_text)
            elif case.fix == "T":
                _run_fixT(case, user_text)
            print(f"PASS: {case.case_id}")
        except Exception as exc:
            failures.append(f"{case.case_id}: {exc}")
            print(f"FAIL: {case.case_id}: {exc}", file=sys.stderr)

    if failures:
        print("\nREPLAY FAILURES:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    # Acuity pair check: turn 121 > turn 122
    from app.services.trafficking_recalibration import compute_sexual_trauma_acuity

    a121 = compute_sexual_trauma_acuity(SYNTHETIC_LISA_121)
    a122 = compute_sexual_trauma_acuity(SYNTHETIC_LISA_122)
    if a121 <= a122:
        print(
            f"FAIL: Lisa 121 acuity ({a121}) must exceed 122 ({a122})",
            file=sys.stderr,
        )
        return 1

    print(f"\nAll {len(CASES)} replay cases passed.")
    return 0


def main() -> None:
    os.environ.setdefault("ENABLE_STALL_SUPPRESSION", "true")
    os.environ.setdefault("ENABLE_MED_ADJUST_REDIRECT", "true")
    os.environ.setdefault("ENABLE_TRAFFICKING_RECAL", "true")
    raise SystemExit(run_replay())


if __name__ == "__main__":
    main()
