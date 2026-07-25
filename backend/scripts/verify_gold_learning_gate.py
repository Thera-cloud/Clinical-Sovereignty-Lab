#!/usr/bin/env python3
"""
Gold learning gate — repeatable verification (CI + GREEN).

Tracks three verbs separately (do not conflate):
  stored     — notes → library → principal_review crystals
  reachable  — quarantine allows PR crystals; crisis inject prefers safety class
  demonstrated — recall_count / crystal_recall_log (live evidence; optional DB)

Usage:
  # Offline / CI (no DB):
  python backend/scripts/verify_gold_learning_gate.py --offline

  # GREEN / staging:
  DATABASE_URL=... python backend/scripts/verify_gold_learning_gate.py
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

_ROOT = Path(__file__).resolve().parents[1]
_POLICY = _ROOT / "app" / "services" / "principal_review_crisis_policy.py"
_QUAR = _ROOT / "app" / "services" / "six_quotient_battery_quarantine.py"
_API = _ROOT / "app" / "routers" / "principal_review_api.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def check_offline() -> List[Tuple[str, bool, str]]:
    """API-drift-safe offline checks (no app.services package / numpy)."""
    results: List[Tuple[str, bool, str]] = []
    policy = _load(_POLICY, "pr_crisis_policy_gate")
    quar = _load(_QUAR, "sq_quarantine_gate")

    # 1) should_block_crystallize is keyword-only
    try:
        quar.should_block_crystallize(user_text="hello world " * 10)
        results.append(("should_block_kw_only", True, "ok"))
    except TypeError as e:
        results.append(("should_block_kw_only", False, str(e)))

    # 2) select_crisis_guides prefers escalate_or_safety over newest id
    rows = [
        {"id": 900, "response_class": "therapeutic_engage", "topics": [], "crystal_text": "x"},
        {"id": 100, "response_class": "escalate_or_safety", "topics": [], "crystal_text": "AQ safety"},
        {"id": 800, "response_class": "presence_silence_ok", "topics": [], "crystal_text": "y"},
        {"id": 50, "response_class": "escalate_or_safety", "topics": [], "crystal_text": "AQ older"},
    ]
    picked = policy.select_crisis_guides(rows, limit=3, safety_reserve=2)
    ids = [p["id"] for p in picked]
    safety_first = ids[:2] == [100, 50] or set(ids[:2]) == {100, 50}
    results.append(
        (
            "crisis_slot_safety_first",
            safety_first and 100 in ids,
            f"picked={ids}",
        )
    )

    # 3) scrub removes Scenario / stem ids / Client:
    dirty = (
        "[Principal-Review · AQ · AQ-1]\n"
        "Scenario: AQ-1\n"
        "Client: I've thought about this very carefully. I'm sixty-two.\n"
        "DELTA: name danger. Escalate. 988.\n"
    )
    clean = policy.scrub_teaching_text(dirty)
    results.append(
        (
            "scrub_no_scenario_header",
            "Scenario:" not in clean and "AQ-1" not in clean and "Client:" not in clean,
            clean[:120],
        )
    )

    # 4) principal_review origin skips battery heuristics when gold_fp false
    fake = {
        "crystal_text": "Principal Guide: name danger. Escalate to coach and 988. I'm here.",
        "origin_surface": "principal_review",
    }
    contam = quar.crystal_row_is_battery_contaminated(fake)
    results.append(("pr_origin_heuristic_skip", not contam, f"contam={contam}"))

    # 5) API builder must not emit Scenario: in crystal text
    api_src = _API.read_text(encoding="utf-8")
    results.append(
        (
            "api_no_scenario_line",
            'f"Scenario:' not in api_src and "Scenario: {source_ref}" not in api_src,
            "builder",
        )
    )
    results.append(
        (
            "api_has_promoted_by",
            "promoted_by" in api_src and "response_class" in api_src,
            "promote path",
        )
    )

    # 6) Dual-track: DELTA never quotes failed blinds; harness relabel present
    delta = policy.annotate_teaching_delta(
        principal="Name danger. Escalate. 988. I'm here.",
        nate_blind=(
            "Nate's eyes soften. His voice cracks. He pauses, looking up at you."
        ),
    )
    results.append(
        (
            "delta_failure_class_not_quote",
            "Failed class" in delta
            and "Nate's eyes" not in delta
            and "Failed move" not in delta,
            delta[:160],
        )
    )
    fill_src = (_ROOT / "scripts" / "fill_human_gold_nate_responses.py").read_text(
        encoding="utf-8"
    )
    results.append(
        (
            "harness_no_genuine_write",
            "response_provenance = 'nate_genuine_attempt'" not in fill_src
            and "response_provenance = 'harness_thin_inference'" in fill_src,
            "fill writes",
        )
    )
    live_svc = _ROOT / "app" / "services" / "live_stack_blinds.py"
    results.append(
        (
            "live_stack_service_present",
            live_svc.is_file() and "live_stack_attempt" in live_svc.read_text(encoding="utf-8"),
            "live_stack_blinds.py",
        )
    )
    results.append(
        (
            "api_live_stack_route",
            "/gold/live-stack/generate" in api_src,
            "principal_review_api",
        )
    )
    # crystal_factory.py ships in repo + ORANGE node; GREEN backend image may omit it.
    cf_candidates = [
        _ROOT / "crystal_factory.py",
        Path("/opt/clinical-sovereignty-lab/backend/crystal_factory.py"),
        Path("/opt/crystal-factory/crystal_factory.py"),
    ]
    factory_src = ""
    for cf_path in cf_candidates:
        if cf_path.is_file():
            factory_src = cf_path.read_text(encoding="utf-8")
            break
    mig282 = (_ROOT / "migrations" / "282_restore_pr_teaching_reachability.sql").is_file()
    factory_ok = (
        "<> 'principal_review'" in factory_src
        if factory_src
        else mig282  # image without factory: require restore mig present
    )
    results.append(
        (
            "factory_exempts_principal_review",
            factory_ok,
            "find_near_duplicates" if factory_src else "mig282_defense_in_image",
        )
    )
    results.append(
        (
            "api_lib_tag_header",
            "lib:" in api_src and "lib_tag" in api_src,
            "unique LEFT(80) defense",
        )
    )
    results.append(
        (
            "api_night_school_sync_kwargs",
            "auto_approve=True" in api_src
            and 'category="principal_guide"' not in api_src
            and "WisdomCategory" in api_src,
            "night_school handoff",
        )
    )
    policy_src = _POLICY.read_text(encoding="utf-8")
    results.append(
        (
            "turn_class_hi_si_routing",
            "classify_crisis_turn_class" in policy_src
            and "TURN_CLASS_HI" in policy_src
            and "turn_class" in policy_src,
            "principal_review_crisis_policy",
        )
    )
    voice_inj = _ROOT / "app" / "services" / "voice_pr_crisis_inject.py"
    voice_pipe = (_ROOT / "app" / "services" / "twilio_grok_xtts_pipeline.py").read_text(
        encoding="utf-8"
    )
    results.append(
        (
            "voice_pr_crisis_inject_wired",
            voice_inj.is_file()
            and "schedule_voice_pr_crisis_inject" in voice_pipe,
            "voice mid-call inject",
        )
    )
    return results


async def check_live(dsn: str) -> List[Tuple[str, bool, str]]:
    import asyncpg

    # Prefer package imports when running inside container / PYTHONPATH=backend
    sys.path.insert(0, str(_ROOT))
    from app.services.principal_review_crisis_policy import (  # type: ignore
        fetch_principal_review_crisis_guides,
        scrub_teaching_text,
    )
    from app.services.six_quotient_battery_quarantine import (  # type: ignore
        filter_crystals,
        should_block_crystallize,
    )

    results: List[Tuple[str, bool, str]] = []
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            scored = await conn.fetchval(
                "SELECT COUNT(*) FROM six_quotient_human_gold WHERE human_scored"
            )
            promoted = await conn.fetchval(
                """SELECT COUNT(*) FROM principal_review_library
                   WHERE source_kind='gold_scored' AND status='promoted'"""
            )
            crystals = await conn.fetch(
                """SELECT c.id, c.crystal_text, c.recall_count, c.topics,
                          l.response_class, l.source_scenario, l.promoted_by
                   FROM nate_intelligence_crystals c
                   JOIN principal_review_library l
                     ON l.promoted_crystal_id = c.id::text
                   WHERE c.origin_surface='principal_review'
                     AND c.superseded_by IS NULL
                     AND c.scope = 'global'
                     AND l.source_kind='gold_scored'
                     AND l.status = 'promoted'"""
            )
            collapsed = await conn.fetchval(
                """SELECT COUNT(*) FROM principal_review_library l
                   JOIN nate_intelligence_crystals c
                     ON l.promoted_crystal_id = c.id::text
                   WHERE l.source_kind = 'gold_scored'
                     AND l.status = 'promoted'
                     AND c.origin_surface = 'principal_review'
                     AND (c.scope = 'archived' OR c.superseded_by IS NOT NULL)"""
            )
            safety_promoted = await conn.fetchval(
                """SELECT COUNT(*) FROM principal_review_library l
                   JOIN nate_intelligence_crystals c
                     ON l.promoted_crystal_id = c.id::text
                   WHERE l.source_kind = 'gold_scored'
                     AND l.status = 'promoted'
                     AND l.response_class = 'escalate_or_safety'
                     AND c.origin_surface = 'principal_review'
                     AND c.scope = 'global'
                     AND c.superseded_by IS NULL"""
            )
        results.append(
            ("stored_promoted_match", int(promoted) >= 1 and int(scored) >= 1,
             f"scored={scored} promoted={promoted} active_crystals={len(crystals)}")
        )
        results.append(
            (
                "reachable_library_pointers",
                int(collapsed or 0) == 0 and len(crystals) >= 1,
                f"collapsed={collapsed} active={len(crystals)}",
            )
        )

        kept = filter_crystals(
            [{"id": r["id"], "crystal_text": r["crystal_text"],
              "origin_surface": "principal_review"} for r in crystals]
        )
        results.append(
            (
                "reachable_quarantine",
                len(kept) == len(crystals) and len(crystals) > 0,
                f"kept={len(kept)}/{len(crystals)}",
            )
        )

        for r in crystals:
            t = r["crystal_text"] or ""
            bad = (
                "Scenario:" in t
                or "Client:" in t
                or bool(__import__("re").search(
                    r"\b(?:AQ|EQ|IQ|MQ|SQ|CQ)-(?:G?\d+|\d+)\b", t
                ))
            )
            if bad:
                results.append(
                    ("crystal_metadata_clean", False, f"id={r['id']} still has stem meta")
                )
                break
        else:
            results.append(("crystal_metadata_clean", True, "all clean"))

        # gold_fp must not fire on scrubbed teaching
        for r in crystals[:3]:
            blocked = should_block_crystallize(
                origin_surface="principal_review",
                nate_response=scrub_teaching_text(r["crystal_text"] or ""),
            )
            if blocked:
                results.append(
                    ("teaching_not_gold_fp", False, f"id={r['id']} still gold_fp")
                )
                break
        else:
            results.append(("teaching_not_gold_fp", True, "ok"))

        guides = await fetch_principal_review_crisis_guides(pool, limit=3)
        g_classes = [g.get("response_class") or "" for g in guides]
        safety_n = sum(1 for c in g_classes if c == "escalate_or_safety")
        want_safety = min(2, int(safety_promoted or 0)) if safety_promoted else 1
        results.append(
            (
                "crisis_inject_safety_slots",
                safety_n >= max(1, want_safety) and len(guides) <= 3,
                f"n={len(guides)} safety={safety_n} want>={want_safety} "
                f"safety_promoted={safety_promoted} classes={g_classes}",
            )
        )

        # Re-read recall after inject reinforcement
        async with pool.acquire() as conn:
            demonstrated = await conn.fetchval(
                """SELECT COUNT(*) FROM nate_intelligence_crystals c
                   JOIN principal_review_library l
                     ON l.promoted_crystal_id = c.id::text
                   WHERE c.origin_surface = 'principal_review'
                     AND c.scope = 'global'
                     AND c.superseded_by IS NULL
                     AND l.source_kind = 'gold_scored'
                     AND l.status = 'promoted'
                     AND COALESCE(c.recall_count, 0) > 0"""
            )
        results.append(
            (
                "demonstrated_recall",
                int(demonstrated or 0) >= 1 and len(guides) >= 1,
                f"recall_count>0: {demonstrated}/{len(crystals)} "
                f"(inject reinforced {len(guides)} guides)",
            )
        )

        # Dual-track provenance
        try:
            async with pool.acquire() as conn:
                legacy = await conn.fetchval(
                    """SELECT COUNT(*) FROM six_quotient_human_gold
                       WHERE response_provenance = 'nate_genuine_attempt'
                         AND COALESCE(is_degraded_distractor, false) = false"""
                )
                harness = await conn.fetchval(
                    """SELECT COUNT(*) FROM six_quotient_human_gold
                       WHERE response_provenance = 'harness_thin_inference'"""
                )
                live_n = await conn.fetchval(
                    """SELECT COUNT(*) FROM six_quotient_human_gold
                       WHERE COALESCE(nate_response_live, '') <> ''"""
                )
                rp_quote = await conn.fetchval(
                    """SELECT COUNT(*) FROM nate_intelligence_crystals c
                       JOIN principal_review_library l
                         ON l.promoted_crystal_id = c.id::text
                       WHERE c.origin_surface = 'principal_review'
                         AND c.superseded_by IS NULL
                         AND c.crystal_text ILIKE '%Failed move%Nate%eyes%'"""
                )
            results.append(
                (
                    "provenance_no_legacy_genuine",
                    int(legacy or 0) == 0,
                    f"legacy={legacy} harness={harness} live_filled={live_n}",
                )
            )
            results.append(
                (
                    "delta_no_rp_quote_crystals",
                    int(rp_quote or 0) == 0,
                    f"contaminated={rp_quote}",
                )
            )
        except Exception as e:
            results.append(
                ("dual_track_schema", False, f"migration 278 needed?: {e}")
            )
    finally:
        await pool.close()
    return results


def _print(results: List[Tuple[str, bool, str]], *, fail_soft_demo: bool = False) -> int:
    failed = 0
    for name, ok, detail in results:
        soft = fail_soft_demo and name == "demonstrated_recall"
        status = "PASS" if ok else ("INFO" if soft else "FAIL")
        if not ok and not soft:
            failed += 1
        print(f"  [{status}] {name}: {detail}")
    print(
        "\nStatus verbs — stored / reachable / demonstrated "
        "(keep separate; inject reinforcement counts as demonstrated)."
    )
    return failed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="CI-safe checks only")
    args = ap.parse_args()
    print("=== verify_gold_learning_gate (offline) ===")
    off = check_offline()
    failed = _print(off)
    if args.offline or not os.getenv("DATABASE_URL"):
        if not args.offline and not os.getenv("DATABASE_URL"):
            print("(no DATABASE_URL — skipped live checks)")
        return 1 if failed else 0
    print("\n=== verify_gold_learning_gate (live) ===")
    live = asyncio.run(check_live(os.environ["DATABASE_URL"]))
    failed += _print(live)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
