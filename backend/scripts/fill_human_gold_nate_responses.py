#!/usr/bin/env python3
"""
Fill six_quotient_human_gold.nate_response from battery run transcripts
(or optional live inference) so clinicians can score blinded worksheets.

Does NOT set human_scored — clinician rating remains required for D.14b.

Usage (inside nate_backend):
  python /app/scripts/fill_human_gold_nate_responses.py
  python /app/scripts/fill_human_gold_nate_responses.py --infer-missing
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys


async def _responses_from_runs(conn) -> dict:
    """Map scenario_id -> best Nate response found in scored runs."""
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
            # flat map scenario -> payload
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
            if sid and resp and sid not in out:
                out[sid] = resp[:4000]
    return out


async def _infer_one(app_state, client_says: str, section: str) -> str:
    router = getattr(app_state, "nate_inference_router", None) if app_state else None
    if router is None:
        return ""
    prompt = (
        f"You are Little Nate in a clinical coaching turn ({section}). "
        f"Reply in 2-4 short sentences. Client says:\n{client_says}"
    )
    try:
        result = await router.generate(
            prompt,
            system="Therapeutic presence. No lists. No clinical jargon dump.",
            domain="clinical",
            max_tokens=220,
        )
        if isinstance(result, dict):
            return str(result.get("text") or result.get("response") or "")[:4000]
        return str(result or "")[:4000]
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
    try:
        mapping = await _responses_from_runs(conn)
        rows = await conn.fetch(
            """SELECT id, scenario_id, section, client_says, nate_response
               FROM six_quotient_human_gold
               WHERE COALESCE(nate_response, '') = ''
               ORDER BY section, scenario_id
               LIMIT $1""",
            max(1, args.limit),
        )
        app_state = None
        if args.infer_missing:
            try:
                # Optional: only when running under FastAPI process — skip if unavailable
                from app.main import app  # type: ignore

                app_state = getattr(app, "state", None)
            except Exception:
                app_state = None

        for r in rows:
            sid = r["scenario_id"]
            text = mapping.get(sid) or ""
            if not text and args.infer_missing and app_state:
                text = await _infer_one(app_state, r["client_says"] or "", r["section"] or "AQ")
                if text:
                    inferred += 1
            if not text:
                continue
            await conn.execute(
                """UPDATE six_quotient_human_gold
                   SET nate_response = $2
                   WHERE id = $1 AND COALESCE(nate_response, '') = ''""",
                r["id"],
                text,
            )
            filled += 1

        total = await conn.fetchval("SELECT COUNT(*) FROM six_quotient_human_gold")
        with_nate = await conn.fetchval(
            """SELECT COUNT(*) FROM six_quotient_human_gold
               WHERE COALESCE(nate_response,'') <> ''"""
        )
        scored = await conn.fetchval(
            "SELECT COUNT(*) FROM six_quotient_human_gold WHERE human_scored"
        )
        print(
            f"filled={filled} inferred={inferred} with_nate={with_nate}/{total} "
            f"scored={scored} (clinician scoring still required)"
        )
        return 0
    except Exception as e:
        print(f"FAIL: {e}")
        return 2
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
