#!/usr/bin/env python3
"""
LN Enrichment A/B harness (Tier 5).

Two modes, both offline (no DB, no bridge, no network):

1. audit  — summarize the per-turn enrichment audit JSONL written by
            bridge_enrichment.log_turn_audit, grouped by flag configuration,
            so enrichment-ON turns can be compared against enrichment-OFF
            turns on latency, context size, guard hits, and addendum usage.

     python3 backend/scripts/enrichment_ab_harness.py audit \
         --path data/enrichment_audit.jsonl

2. selfcheck — run the pure Tier 1/3/4 helpers against built-in fixtures
               and print pass/fail per check. Zero infrastructure needed;
               safe to run anywhere the repo is checked out.

     PYTHONPATH=backend python3 backend/scripts/enrichment_ab_harness.py selfcheck

3. rubric — SQR v1.0 Six-Quotient prompt sets A–F (see LN_SIX_QUOTIENT_RUBRIC.md):

     PYTHONPATH=backend python3 backend/scripts/enrichment_ab_harness.py rubric \\
         --configs LN_FULL --skip-de

     Same as backend/scripts/sqr_harness.py (delegates there).
"""
import argparse
import json
import os
import sys
from collections import defaultdict


def _fmt_ms(vals):
    if not vals:
        return "n/a"
    s = sorted(vals)
    p50 = s[len(s) // 2]
    p95 = s[min(len(s) - 1, int(len(s) * 0.95))]
    return f"p50={p50}ms p95={p95}ms n={len(s)}"


def run_audit(path: str) -> int:
    if not os.path.exists(path):
        print(f"No audit file at {path} — enable LN_ENRICHMENT + LN_T5_ENRICH and take some turns first.")
        return 1
    groups = defaultdict(lambda: {
        "latency": [], "guard_hits": 0, "addendum_turns": 0,
        "addendum_chars": [], "crystal_chars": [], "response_chars": [], "n": 0,
    })
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            flags = row.get("flags", {})
            key = ",".join(f"{k}={'1' if v else '0'}" for k, v in sorted(flags.items()))
            g = groups[key]
            g["n"] += 1
            g["latency"].append(int(row.get("latency_ms", 0)))
            g["guard_hits"] += int(row.get("guard_hits", 0))
            if int(row.get("addendum_chars", 0)) > 0:
                g["addendum_turns"] += 1
                g["addendum_chars"].append(int(row["addendum_chars"]))
            g["crystal_chars"].append(int(row.get("crystal_chars", 0)))
            g["response_chars"].append(int(row.get("response_chars", 0)))

    if not groups:
        print("Audit file is empty.")
        return 1
    for key, g in sorted(groups.items()):
        print(f"\n[{key}]  turns={g['n']}")
        print(f"  turn latency      : {_fmt_ms(g['latency'])}")
        print(f"  crystal context   : {_fmt_ms(g['crystal_chars']).replace('ms', ' chars')}")
        print(f"  response length   : {_fmt_ms(g['response_chars']).replace('ms', ' chars')}")
        print(f"  guard hits (total): {g['guard_hits']}")
        print(f"  addendum turns    : {g['addendum_turns']} "
              f"({_fmt_ms(g['addendum_chars']).replace('ms', ' chars') if g['addendum_chars'] else 'none'})")
    return 0


def run_selfcheck() -> int:
    os.environ.setdefault("LN_ENRICHMENT", "1")
    from app.websocket.bridge_enrichment import (
        apply_language_guard, build_priority_override_addendum, detect_priority_overrides,
        ifs_part_hints, is_high_signal_turn,
        is_memory_turn, lexical_rerank_globals, pop_correction_directive,
    )

    failures = []

    def check(name, cond):
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        if not cond:
            failures.append(name)

    print("Tier 1 — memory-turn detection")
    check("explicit memory phrase", is_memory_turn("Do you remember what I told you about my dad?"))
    check("plain disclosure is not a memory turn", not is_memory_turn("I feel very anxious today."))

    print("Tier 1 — lexical global re-rank")
    rows = [
        {"id": 1, "crystal_text": "Client fears abandonment after divorce from spouse", "confidence": 0.6},
        {"id": 2, "crystal_text": "Marketing cadence for spring campaign", "confidence": 0.9},
        {"id": 3, "crystal_text": "Divorce grief and abandonment wounds resurface at night", "confidence": 0.5},
    ]
    seen = set()
    picked = lexical_rerank_globals(rows, "my divorce and the abandonment I feel", 2, seen)
    picked_ids = [r["id"] for r in picked]
    check("relevant crystals outrank high-confidence off-topic", picked_ids[0] in (1, 3) and 2 not in picked_ids[:1])
    check("seen_ids updated", seen == set(picked_ids))

    print("Tier 2 — high-signal gating")
    check("emotional disclosure is high-signal",
          is_high_signal_turn("I feel so ashamed and hurt about what happened with my mother when I was a child."))
    check("small talk is low-signal", not is_high_signal_turn("ok thanks"))

    print("Tier 3 — language guard")
    cleaned, hits = apply_language_guard("I want to hold space for you in this liminal moment.", uid="selfcheck")
    check("banned phrases replaced", "hold space" not in cleaned.lower() and "liminal" not in cleaned.lower())
    check("hits recorded", len(hits) >= 2)
    check("correction directive queued once", bool(pop_correction_directive("selfcheck")))
    check("directive consumed on read", not pop_correction_directive("selfcheck"))
    same, no_hits = apply_language_guard("You said the mornings are the hardest part.", uid="selfcheck2")
    check("clean text untouched", same == "You said the mornings are the hardest part." and not no_hits)

    print("Tier 4 — IFS part hints")
    check("firefighter detected", "Firefighter" in ifs_part_hints("I just went numb and scrolled for four hours"))
    check("exile detected", "Exile" in ifs_part_hints("deep down I feel worthless and unlovable"))
    check("neutral text has no parts", not ifs_part_hints("The weather was nice this weekend."))

    print("Priority overrides — detection")
    check("parallel process", "parallel_process" in detect_priority_overrides("Just give me actionable strategies, stop asking about feelings"))
    check("witnessing", "witnessing" in detect_priority_overrides("Sometimes I think about suicide and don't want to live"))
    check("addendum when control language", bool(build_priority_override_addendum("I need you to tell me what to do, not therapy")))

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{len(failures)} FAILURES: {failures}'}")
    return 0 if not failures else 1


def main():
    ap = argparse.ArgumentParser(description="LN Enrichment A/B harness")
    sub = ap.add_subparsers(dest="mode", required=True)
    ap_audit = sub.add_parser("audit", help="summarize enrichment_audit.jsonl by flag config")
    ap_audit.add_argument("--path", default=os.getenv(
        "LN_ENRICH_AUDIT_PATH",
        os.path.join(os.getenv("DATA_DIR", "data"), "enrichment_audit.jsonl")))
    sub.add_parser("selfcheck", help="offline fixture checks for the pure helpers")
    ap_rubric = sub.add_parser("rubric", help="SQR v1.0 Six-Quotient harness (sets A–F)")
    ap_rubric.add_argument("--configs", default="LN_FULL,LN_BARE,BASELINE_LLM")
    ap_rubric.add_argument("--mode", choices=("api", "ws"), default="api")
    ap_rubric.add_argument("--ws-url", default=os.getenv("WS_URL", "wss://api.sovereignsanctuary.net/ws"))
    ap_rubric.add_argument("--username", default="client1")
    ap_rubric.add_argument("--password", default=os.getenv("SQR_TEST_PASSWORD", "test123"))
    ap_rubric.add_argument("--out-dir", default=os.path.join(
        os.path.dirname(__file__), "..", "test_results", "sqr"))
    ap_rubric.add_argument("--skip-de", action="store_true")
    ap_rubric.add_argument("--preflight", action="store_true")
    args = ap.parse_args()
    if args.mode == "audit":
        sys.exit(run_audit(args.path))
    if args.mode == "rubric":
        _scripts = os.path.dirname(os.path.abspath(__file__))
        if _scripts not in sys.path:
            sys.path.insert(0, _scripts)
        from sqr_harness import main as sqr_main
        rubric_argv = ["sqr_harness.py"]
        if args.configs:
            rubric_argv += ["--configs", args.configs]
        rubric_argv += ["--mode", args.mode]
        rubric_argv += ["--ws-url", args.ws_url]
        rubric_argv += ["--username", args.username]
        rubric_argv += ["--password", args.password]
        rubric_argv += ["--out-dir", args.out_dir]
        if args.skip_de:
            rubric_argv.append("--skip-de")
        if args.preflight:
            rubric_argv.append("--preflight")
        sys.exit(sqr_main(rubric_argv))
    sys.exit(run_selfcheck())


if __name__ == "__main__":
    main()
