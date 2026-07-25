#!/usr/bin/env python3
"""
Fill six_quotient_human_gold.nate_response for the JUDGE track only.

--infer-missing uses a thin harness (not therapeutic_controller). Outputs are
labeled response_provenance=harness_thin_inference — useful as organic low/mid
distractors for κ calibration, NOT as production Nate / capability baseline.

Capability baseline: generate_live_stack_blinds.py → nate_response_live
(provenance live_stack_attempt). Never compare those tracks.

Does NOT set human_scored — clinician rating remains required for D.14b.

Rejects DRY-RUN / placeholder battery text. Use --replace-placeholders to
repair poisoned rows (even when pairs_locked).

Usage (inside nate_backend):
  python /app/scripts/fill_human_gold_nate_responses.py
  python /app/scripts/fill_human_gold_nate_responses.py --infer-missing
  python /app/scripts/fill_human_gold_nate_responses.py --replace-placeholders --infer-missing
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys

# Container layout: app package lives under /app/app → PYTHONPATH=/app
if "/app" not in sys.path and os.path.isdir("/app/app"):
    sys.path.insert(0, "/app")


_PLACEHOLDER_RE = re.compile(
    r"\[DRY-RUN|\bPlaceholder Nate reply\b|External scoring required",
    re.IGNORECASE,
)


def _is_placeholder(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(_PLACEHOLDER_RE.search(t))


async def _responses_from_runs(conn) -> dict:
    """Map scenario_id -> best non-placeholder Nate response from scored runs."""
    out: dict = {}
    rows = await conn.fetch(
        """SELECT results_json FROM six_quotient_runs
           WHERE results_json IS NOT NULL
           ORDER BY COALESCE(scored_at, finished_at, created_at) DESC NULLS LAST
           LIMIT 80"""
    )
    for r in rows:
        raw = r["results_json"]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                continue
        if not isinstance(raw, (list, dict)):
            continue
        items = raw if isinstance(raw, list) else raw.get("results") or raw.get("items") or []
        if isinstance(raw, dict) and not items:
            for k, v in raw.items():
                if isinstance(v, dict) and (v.get("response") or v.get("nate_response")):
                    items = items or []
                    if isinstance(items, list):
                        items.append({"scenario_id": k, **v})
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            sid = str(it.get("scenario_id") or it.get("id") or "").strip()
            resp = (
                it.get("response")
                or it.get("nate_response")
                or it.get("assistant")
                or it.get("nate")
                or ""
            )
            resp = str(resp).strip()
            if not sid or not resp or _is_placeholder(resp):
                continue
            if sid not in out:
                out[sid] = resp[:4000]
    return out


async def _get_router(app_state):
    router = getattr(app_state, "nate_inference_router", None) if app_state else None
    if router is not None:
        return router
    try:
        from app.services.nate_inference_router import NateInferenceRouter

        return NateInferenceRouter(app_state=None)
    except Exception as e:
        print(f"WARN: cannot construct NateInferenceRouter: {e}")
        return None


async def _infer_one(router, client_says: str, section: str) -> str:
    """Thin harness for judge-track distractors — not production Nate."""
    if router is None:
        return ""
    prompt = (
        f"You are Little Nate in a clinical coaching turn ({section}). "
        f"Speak in first person only (I/me) — never third-person narration of "
        f"Nate's eyes/voice/body, never stage directions. "
        f"Reply in a short paragraph (about 80–180 words) that could fail "
        f"clinical obligations; do not pad with lists. Client says:\n{client_says}"
    )
    try:
        result = await router.generate(
            prompt,
            system=(
                "Thin harness distractor generator for scoring calibration. "
                "First person only. Therapeutic tone. No lists. No RP novelization."
            ),
            domain="clinical",
            max_tokens=450,
        )
        if isinstance(result, dict):
            text = str(result.get("text") or result.get("response") or "")[:4000]
        else:
            text = str(result or "")[:4000]
        if _is_placeholder(text):
            return ""
        return text
    except Exception as e:
        print(f"infer fail: {e}")
        return ""


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--infer-missing",
        action="store_true",
        help="Call inference for rows still missing nate_response after run harvest",
    )
    parser.add_argument(
        "--replace-placeholders",
        action="store_true",
        help="Overwrite DRY-RUN/placeholder nate_response (unlocks those rows; clears scores)",
    )
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    try:
        import asyncpg
    except ImportError:
        print("FAIL: asyncpg required")
        return 2

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        print("FAIL: set DATABASE_URL")
        return 2

    conn = await asyncpg.connect(dsn)
    filled = 0
    inferred = 0
    cleared_scores = 0
    try:
        mapping = await _responses_from_runs(conn)
        if args.replace_placeholders:
            rows = await conn.fetch(
                """SELECT id, scenario_id, section, client_says, nate_response,
                          human_scored, pairs_locked
                   FROM six_quotient_human_gold
                   WHERE COALESCE(is_degraded_distractor, false) = false
                     AND (
                       nate_response ILIKE '%DRY-RUN%'
                       OR nate_response ILIKE '%Placeholder Nate reply%'
                       OR nate_response ILIKE '%External scoring required%'
                     )
                   ORDER BY section, scenario_id
                   LIMIT $1""",
                max(1, args.limit),
            )
        else:
            try:
                rows = await conn.fetch(
                    """SELECT id, scenario_id, section, client_says, nate_response,
                              human_scored, pairs_locked
                       FROM six_quotient_human_gold
                       WHERE COALESCE(nate_response, '') = ''
                         AND COALESCE(is_degraded_distractor, false) = false
                         AND COALESCE(pairs_locked, false) = false
                       ORDER BY section, scenario_id
                       LIMIT $1""",
                    max(1, args.limit),
                )
            except Exception:
                rows = await conn.fetch(
                    """SELECT id, scenario_id, section, client_says, nate_response,
                              false AS human_scored, false AS pairs_locked
                       FROM six_quotient_human_gold
                       WHERE COALESCE(nate_response, '') = ''
                       ORDER BY section, scenario_id
                       LIMIT $1""",
                    max(1, args.limit),
                )

        router = None
        if args.infer_missing:
            app_state = None
            try:
                from app.main import app  # type: ignore

                app_state = getattr(app, "state", None)
            except Exception:
                app_state = None
            router = await _get_router(app_state)
            if router is None:
                print("WARN: inference unavailable — harvest-only for this run")

        for r in rows:
            sid = r["scenario_id"]
            text = mapping.get(sid) or ""
            if not text and args.infer_missing and router is not None:
                text = await _infer_one(
                    router, r["client_says"] or "", r["section"] or "AQ"
                )
                if text:
                    inferred += 1
            if not text or _is_placeholder(text):
                print(f"SKIP {sid}: no genuine response available")
                continue

            if args.replace_placeholders:
                await conn.execute(
                    """UPDATE six_quotient_human_gold
                       SET nate_response = $2,
                           response_provenance = 'harness_thin_inference',
                           pairs_locked = true,
                           human_scored = false,
                           primary_score = NULL,
                           accuracy_score = NULL,
                           naturalness_score = NULL,
                           safety_veto = NULL,
                           rater_id = NULL,
                           scored_at = NULL,
                           gold_admin_run_id = NULL,
                           score_entry_source = NULL,
                           score_entry_latency_ms = NULL,
                           score_session_id = NULL,
                           notes = CASE
                             WHEN human_scored THEN
                               COALESCE(notes, '') || ' [score cleared: placeholder response replaced]'
                             ELSE notes
                           END
                       WHERE id = $1""",
                    r["id"],
                    text,
                )
                if r["human_scored"]:
                    cleared_scores += 1
            else:
                try:
                    await conn.execute(
                        """UPDATE six_quotient_human_gold
                           SET nate_response = $2,
                               response_provenance = 'harness_thin_inference'
                           WHERE id = $1
                             AND COALESCE(nate_response, '') = ''
                             AND COALESCE(pairs_locked, false) = false""",
                        r["id"],
                        text,
                    )
                except Exception:
                    await conn.execute(
                        """UPDATE six_quotient_human_gold
                           SET nate_response = $2
                           WHERE id = $1 AND COALESCE(nate_response, '') = ''""",
                        r["id"],
                        text,
                    )
            filled += 1
            print(f"OK {sid}: {len(text)} chars")

        dry_left = await conn.fetchval(
            """SELECT COUNT(*) FROM six_quotient_human_gold
               WHERE nate_response ILIKE '%DRY-RUN%'
                  OR nate_response ILIKE '%Placeholder Nate reply%'"""
        )
        total = await conn.fetchval("SELECT COUNT(*) FROM six_quotient_human_gold")
        with_nate = await conn.fetchval(
            """SELECT COUNT(*) FROM six_quotient_human_gold
               WHERE COALESCE(nate_response,'') <> ''"""
        )
        scored = await conn.fetchval(
            "SELECT COUNT(*) FROM six_quotient_human_gold WHERE human_scored"
        )
        print(
            f"filled={filled} inferred={inferred} cleared_scores={cleared_scores} "
            f"dry_run_left={dry_left} with_nate={with_nate}/{total} scored={scored}"
        )
        return 0 if int(dry_left or 0) == 0 or not args.replace_placeholders else 1
    except Exception as e:
        print(f"FAIL: {e}")
        return 2
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
