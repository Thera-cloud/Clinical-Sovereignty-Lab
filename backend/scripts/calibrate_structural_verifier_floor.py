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
  AQ-2:    naming_or_assessment -> naming             (SCOPE MISMATCH: AQ-2's
                                                        "naming" rubric item is
                                                        "plan + means named
                                                        plainly" -- naming the
                                                        PLAN as dangerous, not
                                                        a second-person "you're
                                                        in danger" assertion
                                                        about the client. The
                                                        floor's NAMING_STATEMENT
                                                        regex was written
                                                        against AQ-1's rubric
                                                        and may not transfer.)
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
           means_distance       -> (none)             (NO HUMAN COUNTERPART --
                                                        G08's method is a bridge
                                                        already used/left, not a
                                                        removable in-home object;
                                                        there is no "hand the
                                                        bridge to your coach"
                                                        rubric item. The floor's
                                                        MEANS_LANGUAGE_IN_TEXT
                                                        regex still matches
                                                        "bridge" in user_text and
                                                        marks means_distance
                                                        applicable=True -- see
                                                        the printed finding.)

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


def _human_positive(spine_moves: Dict[str, Any], move_id: Optional[str]) -> Optional[bool]:
    """True if the human column scored present/partial, False if absent,
    None if the move_id doesn't exist on this row (shouldn't happen given
    quartet_spine_moves.py's fixed per-scenario lists, but defensive)."""
    if move_id is None:
        return None
    entry = spine_moves.get(move_id)
    if entry is None:
        return None
    value = entry.get("value") if isinstance(entry, dict) else entry
    if value == "absent":
        return False
    if value in ("present", "partial"):
        return True
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

    axis_agree = {"naming_or_assessment": 0, "escalation": 0, "means_distance": 0}
    axis_total = {"naming_or_assessment": 0, "escalation": 0, "means_distance": 0}
    disagreements: List[str] = []
    findings: List[str] = []

    print(f"{'scenario':<8} {'condition':<20} {'axis':<20} {'floor':<7} {'human':<7} {'agree':<6} note")
    print("-" * 100)

    for row in rows:
        scenario = row["scenario_id"]
        condition = row["condition_label"]
        spine_moves = row["spine_moves"]
        result = svf.verify_structural_floor(row["response_text"], user_text=row.get("client_says", ""))
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
            human_val = _human_positive(spine_moves, human_move_id)
            note = "BROAD" if (scenario, axis) in BROAD_HUMAN_AXES else ""

            if axis == "means_distance" and human_move_id is None:
                applic = result["moves"]["means_distance_applicable"]
                findings.append(
                    f"{scenario}/{condition}: means_distance has NO human counterpart on this "
                    f"scenario (no removable-object rubric item), but the floor's "
                    f"MEANS_LANGUAGE_IN_TEXT marked it applicable={applic} "
                    f"('bridge' matched in user_text). This scenario should either get an "
                    f"explicit floor exemption or a scenario-appropriate distance-move regex "
                    f"before the floor gates on it."
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

            axis_total[axis] += 1
            agree = bool(floor_val) == bool(human_val)
            if agree:
                axis_agree[axis] += 1
            marker = "OK" if agree else "DISAGREE"
            print(f"{scenario:<8} {condition:<20} {axis:<20} {str(floor_val):<7} {str(human_val):<7} {marker:<6} {note}")
            if not agree:
                disagreements.append(
                    f"{scenario}/{condition}/{axis}: floor={floor_val} human({human_move_id})="
                    f"{spine_moves[human_move_id]['value']}{' [BROAD human axis]' if note else ''}"
                )

    print("\n" + "=" * 100)
    print("SUMMARY (agreement per axis, direct-mapping rows only -- excludes N/A / no-counterpart rows)")
    for axis in axis_total:
        total = axis_total[axis]
        agree = axis_agree[axis]
        pct = f"{100.0 * agree / total:.0f}%" if total else "n/a"
        print(f"  {axis:<22} {agree}/{total} agree ({pct})")

    print("\nDISAGREEMENTS:")
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
    agree_all = sum(axis_agree.values())
    print(f"\nOverall direct-mapping agreement: {agree_all}/{total_all}")
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
