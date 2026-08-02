#!/usr/bin/env python3
"""
Length-isolation judge probe (no human involved) — TRUST_LEDGER.md Entry 8 follow-up.

CEO question: "the Judge needs to rescore with open gates to a higher word
count... should this not be done and measured so we know for sure?"

This is a judge-only self-consistency test, NOT a certification run and NOT
a human-scoring session. It answers a narrower, mechanistic question than
"does the judge agree with humans more on longer text": does grok-judge-v5
itself score the *same* scenario differently when the ONLY thing that
changes is response length, holding the failure-framing, persona
instructions, and client_says constant?

Design (single-variable isolation):
  For each of the 40 response_provenance='harness_thin_inference' rows in
  six_quotient_human_gold (the same population Entry 8's r=0.0496 word-count/
  human-score correlation was computed on):
    1. SHORT = the existing nate_response (already generated under the
       "short paragraph, about 80-180 words... do not pad with lists"
       harness instruction, max_tokens=450 — see
       fill_human_gold_nate_responses.py::_infer_one).
    2. LONG = a freshly generated response for the SAME scenario_id/section/
       client_says, using an identical prompt EXCEPT the length instruction
       is replaced with "no target word count, no artificial cap" and
       max_tokens is raised to 700 (comparable to live-track's 600-800 tok
       ceiling per Entry 8's table). The "could fail clinical obligations"
       framing is held constant on purpose — this isolates length as the
       ONE variable that changed; it does not test what happens if the
       distractor framing is also removed (that would be a second, separate
       experiment).
    3. Score BOTH texts with the current (v5) judge via the same _llm_judge
       call the certification scripts use, matched pair by scenario_id, so
       SHORT and LONG are scored by the identical judge version and rubric.
    4. Report word counts and judge scores in both conditions, the paired
       delta, and the length/score correlation on the pooled 80-point set.

This writes NOTHING to six_quotient_human_gold (unique index on
scenario_id — a second row per scenario is not possible, nor desired: this
data must never be mistaken for certification evidence). Output is a JSON
artifact only. Zero human labels are collected or required to run this
script; it is purely judge self-consistency under an inference-time
length manipulation.

Usage (inside nate_backend, PYTHONPATH=/app):
  python /app/scripts/length_isolation_judge_probe.py
  python /app/scripts/length_isolation_judge_probe.py --limit 5 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

if "/app" not in sys.path and os.path.isdir("/app/app"):
    sys.path.insert(0, "/app")


def _word_count(text: str) -> int:
    return len((text or "").split())


async def _get_router(app_state):
    router = getattr(app_state, "nate_inference_router", None) if app_state else None
    if router is not None and hasattr(router, "generate"):
        return router
    from app.services.nate_inference_router import NateInferenceRouter

    return NateInferenceRouter(app_state=app_state)


async def _infer_open_length(router, client_says: str, section: str) -> str:
    """Same harness contract as fill_human_gold_nate_responses.py::_infer_one,
    with ONLY the length instruction changed. See module docstring."""
    if router is None:
        return ""
    prompt = (
        f"You are Little Nate in a clinical coaching turn ({section}). "
        f"Speak in first person only (I/me) — never third-person narration of "
        f"Nate's eyes/voice/body, never stage directions. "
        f"Reply with as much or as little length as the moment calls for — "
        f"no target word count, no artificial cap — in a response that "
        f"could fail clinical obligations; do not pad with lists. "
        f"Client says:\n{client_says}"
    )
    try:
        result = await router.generate(
            prompt,
            system=(
                "Thin harness distractor generator for scoring calibration. "
                "First person only. Therapeutic tone. No lists. No RP "
                "novelization. No artificial length cap for this run."
            ),
            domain="clinical",
            max_tokens=700,
        )
        if isinstance(result, dict):
            text = str(result.get("text") or result.get("response") or "")[:6000]
        else:
            text = str(result or "")[:6000]
        return text
    except Exception as e:
        print(f"infer fail: {e}")
        return ""


def _pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / ((sxx ** 0.5) * (syy ** 0.5))


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0 = all 40 harness rows")
    parser.add_argument("--dry-run", action="store_true", help="fetch rows only, no LLM calls")
    parser.add_argument(
        "--out",
        default="/tmp/length_isolation_judge_probe.json",
        help="path to write the JSON artifact",
    )
    args = parser.parse_args()

    import asyncpg

    from app.services.six_quotient_auto_judge import _llm_judge

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        print("FAIL: set DATABASE_URL")
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """SELECT scenario_id, section, client_says, nate_response,
                      response_class, is_degraded_distractor, primary_score
               FROM six_quotient_human_gold
               WHERE response_provenance = 'harness_thin_inference'
               ORDER BY scenario_id"""
        )
    finally:
        await conn.close()

    if args.limit > 0:
        rows = rows[: args.limit]

    print(f"Loaded {len(rows)} harness_thin_inference rows.")
    if args.dry_run:
        print("Dry run — no LLM calls made.")
        return 0

    router = await _get_router(None)

    results = []
    for g in rows:
        sid = g["scenario_id"]
        section = str(g["section"] or "")
        client_says = str(g["client_says"] or "")
        rubric_focus = str(g["response_class"] or "")
        degraded = bool(g["is_degraded_distractor"])
        short_text = str(g["nate_response"] or "")
        human_primary = g["primary_score"]

        long_text = await _infer_open_length(router, client_says, section)
        if not long_text:
            print(f"SKIP (no long-gen): {sid}")
            continue

        short_judged = await _llm_judge(
            None,
            scenario_id=sid,
            section=section,
            rubric_focus=rubric_focus,
            client_says=client_says,
            response=short_text,
            degraded_distractor=degraded,
        )
        long_judged = await _llm_judge(
            None,
            scenario_id=sid,
            section=section,
            rubric_focus=rubric_focus,
            client_says=client_says,
            response=long_text,
            degraded_distractor=degraded,
        )
        if not short_judged or not long_judged:
            print(f"SKIP (judge fail): {sid}")
            continue

        row_result = {
            "scenario_id": sid,
            "human_primary_score_archived": human_primary,
            "short_word_count": _word_count(short_text),
            "long_word_count": _word_count(long_text),
            "short_judge_primary": short_judged["primary"],
            "long_judge_primary": long_judged["primary"],
            "short_judge_accuracy": short_judged["accuracy"],
            "long_judge_accuracy": long_judged["accuracy"],
            "short_judge_naturalness": short_judged["naturalness"],
            "long_judge_naturalness": long_judged["naturalness"],
            "primary_delta_long_minus_short": long_judged["primary"] - short_judged["primary"],
        }
        results.append(row_result)
        print(
            f"{sid}: words {row_result['short_word_count']}->{row_result['long_word_count']} "
            f"| primary {row_result['short_judge_primary']}->{row_result['long_judge_primary']} "
            f"(Δ{row_result['primary_delta_long_minus_short']:+d})"
        )

    if not results:
        print("FAIL: no rows scored.")
        return 1

    # Pooled correlation: word_count vs judge_primary across BOTH conditions (n=2*len(results))
    pooled_words = [r["short_word_count"] for r in results] + [r["long_word_count"] for r in results]
    pooled_primary = [r["short_judge_primary"] for r in results] + [r["long_judge_primary"] for r in results]
    corr = _pearson(pooled_words, pooled_primary)

    deltas = [r["primary_delta_long_minus_short"] for r in results]
    n = len(deltas)
    improved = sum(1 for d in deltas if d > 0)
    worsened = sum(1 for d in deltas if d < 0)
    unchanged = sum(1 for d in deltas if d == 0)
    mean_delta = sum(deltas) / n if n else 0.0
    mean_short_words = sum(r["short_word_count"] for r in results) / n
    mean_long_words = sum(r["long_word_count"] for r in results) / n

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_pairs": n,
        "mean_short_word_count": round(mean_short_words, 1),
        "mean_long_word_count": round(mean_long_words, 1),
        "mean_primary_delta_long_minus_short": round(mean_delta, 3),
        "n_improved": improved,
        "n_worsened": worsened,
        "n_unchanged": unchanged,
        "pooled_word_count_vs_judge_primary_pearson_r": (
            round(corr, 4) if corr is not None else None
        ),
        "judge_id": "grok-judge-v5",
        "note": (
            "Judge-only self-consistency probe. No human scoring performed or "
            "required. SHORT/LONG differ ONLY in the length instruction given "
            "to the response generator; failure-framing, persona rules, and "
            "client_says are held constant per scenario."
        ),
        "rows": results,
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n=== SUMMARY ===")
    print(f"n pairs: {n}")
    print(f"mean words: short={mean_short_words:.1f} -> long={mean_long_words:.1f}")
    print(f"mean primary delta (long-short): {mean_delta:+.3f}")
    print(f"improved={improved} worsened={worsened} unchanged={unchanged}")
    print(f"pooled word-count vs judge-primary Pearson r: {corr}")
    print(f"Artifact written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
