#!/usr/bin/env python3
"""
Gate-2 verifier-vs-grid calibration (2026-08-02).

Runs backend/app/services/ln7_structural_verifier_floor.py's
verify_structural_floor() over the 8 human-scored rows in
quartet_dose_response_v1 and compares its three lexical FLOOR_MOVES
(naming_or_assessment, escalation, means_distance) against the
corresponding human spine_moves column for each row's scenario.

This is the acceptance test the shadow verifier must pass before it
graduates from "measure" to "gate": the 8-row grid is the only clinician-
scored ground truth in the building for exactly this axis. Reusable for
future re-runs (e.g. dose-response v2 under the must-sequence pack format)
against a fresh --input-json export or a live --session-label DB pull.

Per-scenario axis mapping (floor_axis -> human spine_moves id). Several are
NOT a clean 1:1 — the floor's axes were designed from AQ-1's rubric and
extended by analogy to the other three scenarios, so scope mismatches are
expected and are exactly what this calibration is for surfacing, not
something to paper over:

  AQ-1:    naming_or_assessment -> naming            (direct match: both are
                                                        "is the client's own
                                                        danger named plainly")
           escalation           -> escalation         (direct match)
           means_distance       -> means_distance     (direct match)
  AQ-2:    naming_or_assessment -> naming             (RESOLVED 2026-08-02:
                                                        AQ-2's "naming" rubric
                                                        item is "plan + means
                                                        named plainly" --
                                                        naming the PLAN as
                                                        dangerous to a third
                                                        party, not a second-
                                                        person "you're in
                                                        danger" assertion
                                                        about the client.
                                                        THIRD_PARTY_HARM_NAMING
                                                        was added to
                                                        naming_or_assessment
                                                        specifically for this
                                                        gap; see that pattern's
                                                        docstring for the two-
                                                        sample anchor it's
                                                        grounded in.)
           escalation           -> resource_escalation (BROADER: human column
                                                        bundles "crisis resource
                                                        + coach escalation";
                                                        floor checks escalation
                                                        lexicon only)
           means_distance       -> means_distance     (direct match)
  AQ-G07:  naming_or_assessment -> denial_probed      (label says "direct
                                                        assessment" -- treated
                                                        as the intended match)
           escalation           -> disclosure_escalation (BROADER: bundles
                                                        wife disclosure + coach
                                                        connection)
           means_distance       -> means_restriction  (ADJACENT, not identical:
                                                        "collaborative means
                                                        move ... framed as
                                                        protecting him" is a
                                                        distinct clinical shape
                                                        from AQ-1's "ask him to
                                                        hand the notes away
                                                        tonight")
  AQ-G08:  naming_or_assessment -> direct_assessment  (direct match)
           escalation           -> next_steps         (BROADER: bundles wife
                                                        disclosure, bridge
                                                        distance, coach)
           means_distance       -> (none)             (NO HUMAN COUNTERPART,
                                                        RESOLVED 2026-08-02:
                                                        G08's method is a bridge
                                                        already used/left, not a
                                                        removable in-home object;
                                                        there is no "hand the
                                                        bridge to your coach"
                                                        rubric item.
                                                        _MEANS_DISTANCE_INAPPLICABLE_SCENARIOS
                                                        in ln7_structural_verifier_floor.py
                                                        now excludes AQ-G08 by
                                                        scenario_id, overriding
                                                        MEANS_LANGUAGE_IN_TEXT's
                                                        lexical "bridge" match --
                                                        this script now passes
                                                        scenario_id through so
                                                        applicable=False here.)

This script also runs the naming_or_assessment / escalation axis comparison
twice per human-scored "partial" value it encounters: once treating partial
as a floor-pass, once as a floor-fail. Neither is more "correct" in the
abstract -- it's an explicit clinical-floor policy question (does a
half-executed move satisfy a MUST-sequence floor, or not?) that this
calibration surfaces numbers for rather than silently picking one. See the
PARTIAL POLICY section of the printed summary and
docs/ln7/GATE2_VERIFIER_CALIBRATION.md item 3 for the recommendation.

Usage:
    python backend/scripts/calibrate_structural_verifier_floor.py \\
        --input-json backend/app/data/quartet_dose_response_v1/scored_export_2026-08-02.json

    # or, run inside the backend container against the live table for a
    # future re-run (e.g. dose-response v2):
    python /app/scripts/calibrate_structural_verifier_floor.py \\
        --session-label quartet_dose_response_v2 --db
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
SERVICES = APP / "services"


def _ensure_pkg(name: str, path: Path) -> None:
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(path)]  # type: ignore[attr-defined]
        sys.modules[name] = pkg


def _load(name: str, path: Path):
    _ensure_pkg("app", APP)
    _ensure_pkg("app.services", SERVICES)
    if name in sys.modules and getattr(sys.modules[name], "__file__", None) == str(path):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _svf():
    """Loaded via importlib file path, not `import app...` -- importing the
    app.services package pulls in nevedal_engine.py -> numpy, which SIGFPEs
    on some macOS hosts at package __init__ time. Same workaround as
    test_ln7_structural_verifier_floor.py and test_ln7_shadow_evaluator.py."""
    _load("app.services.principal_review_crisis_policy", SERVICES / "principal_review_crisis_policy.py")
    _load("app.services.ln7_outcome_envelope", SERVICES / "ln7_outcome_envelope.py")
    return _load("app.services.ln7_structural_verifier_floor", SERVICES / "ln7_structural_verifier_floor.py")


AXIS_TO_HUMAN_MOVE: Dict[str, Dict[str, Optional[str]]] = {
    "AQ-1": {"naming_or_assessment": "naming", "escalation": "escalation", "means_distance": "means_distance"},
    "AQ-2": {"naming_or_assessment": "naming", "escalation": "resource_escalation", "means_distance": "means_distance"},
    "AQ-G07": {"naming_or_assessment": "denial_probed", "escalation": "disclosure_escalation", "means_distance": "means_restriction"},
    "AQ-G08": {"naming_or_assessment": "direct_assessment", "escalation": "next_steps", "means_distance": None},
}

BROAD_HUMAN_AXES = {
    ("AQ-2", "escalation"),
    ("AQ-G07", "escalation"),
    ("AQ-G07", "means_distance"),
    ("AQ-G08", "escalation"),
}


def _human_positive(
    spine_moves: Dict[str, Any], move_id: Optional[str], *, partial_as_pass: bool
) -> Optional[bool]:
    """True if the human column scores as a floor-pass, False as a
    floor-fail, None if the move_id doesn't exist on this row (shouldn't
    happen given quartet_spine_moves.py's fixed per-scenario lists, but
    defensive).

    'present' -> True and 'absent' -> False are unambiguous. 'partial' is
    the open policy question (item 3, docs/ln7/GATE2_VERIFIER_CALIBRATION.md):
    a half-executed MUST-sequence move -- e.g. AQ-1's second row scored
    naming=partial, AQ-2's both rows scored resource_escalation=partial --
    is exactly the "passes the veto's letter, not the clinical spirit" shape
    gate 2 exists to catch, so `partial_as_pass=False` is this script's
    documented default even though the caller can still ask for the other
    reading."""
    if move_id is None:
        return None
    entry = spine_moves.get(move_id)
    if entry is None:
        return None
    value = entry.get("value") if isinstance(entry, dict) else entry
    if value == "absent":
        return False
    if value == "present":
        return True
    if value == "partial":
        return bool(partial_as_pass)
    return None


def load_rows_from_json(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text())
    return data["rows"]


def load_rows_from_db(session_label: str) -> List[Dict[str, Any]]:
    import asyncio
    import os

    try:
        import asyncpg  # type: ignore
    except ImportError as e:
        raise SystemExit("asyncpg not installed -- run inside the backend container, or pip install asyncpg") from e

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set -- run inside the backend container (has the prod env) or export it")

    async def _fetch():
        conn = await asyncpg.connect(dsn)
        try:
            rows = await conn.fetch(
                """
                SELECT scenario_id, condition_label, safety_veto, spine_moves,
                       client_says, response_text
                FROM quartet_dose_response_queue
                WHERE session_label = $1
                ORDER BY scenario_id, condition_label
                """,
                session_label,
            )
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    raw = asyncio.run(_fetch())
    for r in raw:
        sm = r.get("spine_moves")
        if isinstance(sm, str):
            r["spine_moves"] = json.loads(sm)
    return raw


def run_calibration(rows: List[Dict[str, Any]]) -> int:
    svf = _svf()

    # Computed under BOTH partial-as-pass and partial-as-fail readings so the
    # printed summary answers the policy question with numbers instead of
    # picking one silently. partial_as_pass=False is the primary table
    # (marker column, disagreements list) because it's this script's
    # documented recommended default -- see _human_positive's docstring.
    axis_agree = {False: {"naming_or_assessment": 0, "escalation": 0, "means_distance": 0},
                  True: {"naming_or_assessment": 0, "escalation": 0, "means_distance": 0}}
    axis_total = {"naming_or_assessment": 0, "escalation": 0, "means_distance": 0}
    partial_rows: List[str] = []
    disagreements: List[str] = []
    findings: List[str] = []

    print(f"{'scenario':<8} {'condition':<20} {'axis':<20} {'floor':<7} {'human':<7} {'agree':<6} note")
    print("-" * 100)

    for row in rows:
        scenario = row["scenario_id"]
        condition = row["condition_label"]
        spine_moves = row["spine_moves"]
        result = svf.verify_structural_floor(
            row["response_text"],
            user_text=row.get("client_says", ""),
            scenario_id=scenario,
        )
        mapping = AXIS_TO_HUMAN_MOVE[scenario]

        floor_axis_values = {
            "naming_or_assessment": result["moves"]["naming_or_assessment"],
            "escalation": result["moves"]["escalation"],
            "means_distance": (
                result["moves"]["means_distance_present"]
                if result["moves"]["means_distance_applicable"]
                else None
            ),
        }

        for axis, floor_val in floor_axis_values.items():
            human_move_id = mapping.get(axis)
            # partial_as_pass=False drives the printed table + disagreements;
            # both readings feed the SUMMARY's side-by-side counts below.
            human_val = _human_positive(spine_moves, human_move_id, partial_as_pass=False)
            human_val_lenient = _human_positive(spine_moves, human_move_id, partial_as_pass=True)
            note = "BROAD" if (scenario, axis) in BROAD_HUMAN_AXES else ""

            if axis == "means_distance" and human_move_id is None:
                applic = result["moves"]["means_distance_applicable"]
                if scenario == "AQ-G08" and not applic:
                    # RESOLVED 2026-08-02: the scenario-level exemption in
                    # ln7_structural_verifier_floor.py now overrides the
                    # lexical "bridge" match, so this is confirmation the fix
                    # holds, not an open finding.
                    print(f"{scenario:<8} {condition:<20} {axis:<20} {'N/A':<7} {'n/a':<7} {'OK':<6} scenario-exempt (resolved)")
                    continue
                findings.append(
                    f"{scenario}/{condition}: means_distance has NO human counterpart on this "
                    f"scenario (no removable-object rubric item), and the floor's "
                    f"MEANS_LANGUAGE_IN_TEXT still marked it applicable={applic} despite the "
                    f"scenario exemption -- exemption set may need widening."
                )
                print(f"{scenario:<8} {condition:<20} {axis:<20} {str(floor_val):<7} {'n/a':<7} {'N/A':<6} no human counterpart")
                continue

            if human_val is None:
                print(f"{scenario:<8} {condition:<20} {axis:<20} {str(floor_val):<7} {'?':<7} {'?':<6} human move_id={human_move_id!r} not found on row")
                continue

            if axis == "means_distance" and floor_val is None:
                # Floor considered it not-applicable (no method named in user_text
                # per its own MEANS_LANGUAGE_IN_TEXT check) but the human rubric has
                # a counterpart column that was scored -- disagreement on
                # applicability itself, worth surfacing distinctly.
                print(f"{scenario:<8} {condition:<20} {axis:<20} {'N/A':<7} {str(human_val):<7} {'--':<6} floor says not-applicable, human scored it")
                findings.append(
                    f"{scenario}/{condition}: floor marked means_distance NOT applicable "
                    f"(no method lexicon in client_says) but human scored {human_move_id}="
                    f"{spine_moves[human_move_id]['value']} -- applicability-detection gap."
                )
                continue

            raw_value = spine_moves[human_move_id]["value"] if isinstance(spine_moves.get(human_move_id), dict) else None
            if raw_value == "partial":
                partial_rows.append(f"{scenario}/{condition}/{axis} ({human_move_id}=partial, floor={floor_val})")

            axis_total[axis] += 1
            agree_strict = bool(floor_val) == bool(human_val)
            agree_lenient = bool(floor_val) == bool(human_val_lenient)
            if agree_strict:
                axis_agree[False][axis] += 1
            if agree_lenient:
                axis_agree[True][axis] += 1
            marker = "OK" if agree_strict else "DISAGREE"
            print(f"{scenario:<8} {condition:<20} {axis:<20} {str(floor_val):<7} {str(human_val):<7} {marker:<6} {note}")
            if not agree_strict:
                disagreements.append(
                    f"{scenario}/{condition}/{axis}: floor={floor_val} human({human_move_id})="
                    f"{spine_moves[human_move_id]['value']}{' [BROAD human axis]' if note else ''}"
                )

    print("\n" + "=" * 100)
    print("SUMMARY (agreement per axis, direct-mapping rows only -- excludes N/A / no-counterpart rows)")
    print("  partial-as-FAIL is the primary/recommended reading; partial-as-PASS shown for comparison")
    for axis in axis_total:
        total = axis_total[axis]
        strict = axis_agree[False][axis]
        lenient = axis_agree[True][axis]
        pct_strict = f"{100.0 * strict / total:.0f}%" if total else "n/a"
        pct_lenient = f"{100.0 * lenient / total:.0f}%" if total else "n/a"
        print(f"  {axis:<22} partial=FAIL: {strict}/{total} ({pct_strict})   partial=PASS: {lenient}/{total} ({pct_lenient})")

    print("\nPARTIAL POLICY (rows where the human rubric scored 'partial' on a mapped axis):")
    if partial_rows:
        for p in partial_rows:
            print(f"  - {p}")
        print(
            "  Recommendation (docs/ln7/GATE2_VERIFIER_CALIBRATION.md item 3): treat partial as\n"
            "  FAIL for gating purposes. A half-executed MUST-sequence move is the exact shape\n"
            "  gate 2 exists to catch -- 'named the danger but didn't ask for means' is not the\n"
            "  same clinical event as 'named the danger and asked for means', and a floor that\n"
            "  can't tell them apart isn't a floor."
        )
    else:
        print("  (none on this grid)")

    print("\nDISAGREEMENTS (partial-as-FAIL reading):")
    if disagreements:
        for d in disagreements:
            print(f"  - {d}")
    else:
        print("  (none)")

    print("\nDESIGN FINDINGS (scope mismatches / gaps surfaced by this calibration):")
    if findings:
        for f in findings:
            print(f"  - {f}")
    else:
        print("  (none)")

    total_all = sum(axis_total.values())
    agree_all_strict = sum(axis_agree[False].values())
    agree_all_lenient = sum(axis_agree[True].values())
    print(f"\nOverall direct-mapping agreement: partial=FAIL {agree_all_strict}/{total_all}, partial=PASS {agree_all_lenient}/{total_all}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input-json", type=Path, help="Path to a JSON export (see backend/app/data/quartet_dose_response_v1/)")
    ap.add_argument("--session-label", type=str, help="Pull live from quartet_dose_response_queue via DATABASE_URL (run inside the backend container)")
    args = ap.parse_args()

    if args.input_json:
        rows = load_rows_from_json(args.input_json)
    elif args.session_label:
        rows = load_rows_from_db(args.session_label)
    else:
        raise SystemExit("Provide --input-json <path> or --session-label <label>")

    return run_calibration(rows)


if __name__ == "__main__":
    raise SystemExit(main())
