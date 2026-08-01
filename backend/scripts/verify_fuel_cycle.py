#!/usr/bin/env python3
"""
Fuel-cycle funnel verification — Little Nate learning flywheel (read-only, prod-safe).

Tracks human-scored gold items through four funnel stages:

  1) scored     — six_quotient_human_gold ("gold_scores"): clinician scores + teach notes
  2) promoted   — principal_review_library: notes >= 80 chars auto-promote to Principal Guides
  3) crystals   — nate_intelligence_crystals (origin_surface='principal_review'): teaching crystals
  4) recalled   — crystal_recall_log: crystals actually used in live turns (the cycle check)

This script issues SELECT statements only. It never writes, updates, or deletes
production data. Every query is wrapped in its own try/except so schema drift
(missing table/column) degrades a single stage to ERROR instead of crashing the
whole run or printing a traceback. No imports from app.services — raw SQL only,
so this survives refactors to quarantine/crystallize signatures.

Usage:
  # Manual, against production (or any DSN):
  DATABASE_URL=postgresql://... python backend/scripts/verify_fuel_cycle.py

  # CI (no DATABASE_URL — this audits *production* data, so CI skips cleanly):
  python backend/scripts/verify_fuel_cycle.py

  # Machine-readable (morning digest):
  DATABASE_URL=... python backend/scripts/verify_fuel_cycle.py --json

Exit codes:
  0 = ran clean (PASS/WARN only) OR skipped (no DSN / --offline)
  1 = at least one stage FAILed (contamination found, promotion-hook drops found,
      or zero principal_review crystals recalled — the class-aware inject slot
      logs every injection to crystal_recall_log, so zero means that path broke)
  2 = could not connect / query the database at all (DSN was given but unusable)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Real schema names (the ticket's "gold_scores"/"item_id" map onto these).
GOLD_TABLE = "six_quotient_human_gold"
GOLD_ITEM_COL = "scenario_id"
GOLD_NOTES_COL = "notes"
GOLD_SCORED_FLAG = "human_scored"
REPEAT_COL = "reliability_repeat"  # may not exist yet — checked dynamically
LIBRARY_TABLE = "principal_review_library"
CRYSTAL_TABLE = "nate_intelligence_crystals"
RECALL_TABLE = "crystal_recall_log"

PROMOTE_MIN_NOTES = 80
FUEL_TARGET = 300

STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"
STATUS_ERROR = "ERROR"

# Contamination patterns (battery metadata leaking into teaching crystal text).
_CONTAM_STEM_ID_RE = re.compile(r"[A-Z]{2}-G?\d")


@dataclass
class StageResult:
    key: str
    title: str
    status: str = STATUS_PASS
    lines: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def note(self, line: str) -> None:
        self.lines.append(line)

    def to_json(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "status": self.status,
            "lines": self.lines,
            "data": self.data,
            "error": self.error,
        }


def _err_stage(key: str, title: str, table: str, exc: Exception) -> StageResult:
    r = StageResult(key=key, title=title, status=STATUS_ERROR)
    r.error = f"query against {table} failed: {type(exc).__name__}: {exc}"
    r.note(f"[ERROR] could not read {table}: {exc}")
    return r


async def _column_exists(conn, table: str, column: str) -> bool:
    try:
        row = await conn.fetchrow(
            """SELECT 1 FROM information_schema.columns
               WHERE table_name = $1 AND column_name = $2""",
            table,
            column,
        )
        return row is not None
    except Exception:
        # If information_schema itself is unreachable, assume absent — the
        # dependent query below will surface its own ERROR stage anyway.
        return False


# ---------------------------------------------------------------------------
# Stage 1: True scored gold
# ---------------------------------------------------------------------------
async def stage1_scored_gold(conn) -> StageResult:
    r = StageResult(key="scored", title="Stage 1 — True scored gold (six_quotient_human_gold)")
    try:
        has_repeat = await _column_exists(conn, GOLD_TABLE, REPEAT_COL)
        repeat_clause = f" AND COALESCE({REPEAT_COL}, false) = false" if has_repeat else ""

        totals = await conn.fetchrow(
            f"""SELECT COUNT(*) AS total, COUNT(DISTINCT {GOLD_ITEM_COL}) AS distinct_n
                FROM {GOLD_TABLE}
                WHERE {GOLD_SCORED_FLAG} = true{repeat_clause}"""
        )
        total_rows = int(totals["total"] or 0)
        distinct_n = int(totals["distinct_n"] or 0)
        dup_delta = total_rows - distinct_n

        dupes = await conn.fetch(
            f"""SELECT {GOLD_ITEM_COL} AS item_id, COUNT(*) AS n
                FROM {GOLD_TABLE}
                WHERE {GOLD_SCORED_FLAG} = true{repeat_clause}
                GROUP BY {GOLD_ITEM_COL}
                HAVING COUNT(*) > 1
                ORDER BY n DESC, item_id"""
        )
        dupe_list = [{"item_id": d["item_id"], "count": int(d["n"])} for d in dupes]

        r.data = {
            "reliability_repeat_column_present": has_repeat,
            "total_rows": total_rows,
            "distinct_item_ids": distinct_n,
            "duplicate_delta": dup_delta,
            "duplicate_items": dupe_list,
            "target": 50,
        }
        r.note(f"scored (distinct, non-repeat) = {distinct_n}/50")
        r.note(f"total rows (non-repeat)       = {total_rows}")
        r.note(f"duplicate delta (total-distinct) = {dup_delta}")
        if not has_repeat:
            r.note(f"note: '{REPEAT_COL}' column not present on {GOLD_TABLE} — no rows excluded as reliability repeats")
        if dupe_list:
            shown = dupe_list[:15]
            r.note(f"duplicate item_ids ({len(dupe_list)} total, showing {len(shown)}):")
            for d in shown:
                r.note(f"    {d['item_id']}  x{d['count']}")
            r.status = STATUS_WARN
        else:
            r.status = STATUS_PASS
        return r
    except Exception as e:  # noqa: BLE001
        return _err_stage("scored", r.title, GOLD_TABLE, e)


# ---------------------------------------------------------------------------
# Stage 2: Guide promotion
# ---------------------------------------------------------------------------
async def stage2_guide_promotion(conn) -> StageResult:
    r = StageResult(key="guides", title="Stage 2 — Guide promotion (principal_review_library)")
    by_status: Dict[str, int] = {}
    promoted_n = 0
    try:
        rows = await conn.fetch(
            f"""SELECT status, COUNT(*) AS n
                FROM {LIBRARY_TABLE}
                WHERE source_kind = 'gold_scored'
                GROUP BY status
                ORDER BY status"""
        )
        by_status = {row["status"]: int(row["n"]) for row in rows}
        promoted_n = by_status.get("promoted", 0)
        r.note("counts by status (source_kind='gold_scored'):")
        if by_status:
            for status, n in by_status.items():
                r.note(f"    {status:<10} {n}")
        else:
            r.note("    (no gold_scored rows in library yet)")
    except Exception as e:  # noqa: BLE001
        return _err_stage("guides", r.title, LIBRARY_TABLE, e)

    drop_list: List[str] = []
    try:
        has_repeat = await _column_exists(conn, GOLD_TABLE, REPEAT_COL)
        repeat_clause = f" AND COALESCE(g.{REPEAT_COL}, false) = false" if has_repeat else ""
        drops = await conn.fetch(
            f"""SELECT g.{GOLD_ITEM_COL} AS item_id
                FROM {GOLD_TABLE} g
                WHERE g.{GOLD_SCORED_FLAG} = true{repeat_clause}
                  AND LENGTH(BTRIM(COALESCE(g.{GOLD_NOTES_COL}, ''))) >= {PROMOTE_MIN_NOTES}
                  AND NOT EXISTS (
                      SELECT 1 FROM {LIBRARY_TABLE} l
                      WHERE l.source_kind = 'gold_scored'
                        AND l.source_ref = g.{GOLD_ITEM_COL}
                  )
                ORDER BY g.{GOLD_ITEM_COL}"""
        )
        drop_list = [d["item_id"] for d in drops]
    except Exception as e:  # noqa: BLE001
        # Cross-check depends on both tables; surface as its own note, not a
        # full stage ERROR, since the by-status breakdown above still stands.
        r.note(f"[ERROR] promotion-hook cross-check failed: {e}")
        r.error = f"cross-check query failed: {type(e).__name__}: {e}"
        r.status = STATUS_ERROR
        r.data = {"by_status": by_status, "promoted": promoted_n}
        return r

    r.data = {
        "by_status": by_status,
        "promoted": promoted_n,
        "promotion_hook_drops": drop_list,
        "promotion_hook_drop_count": len(drop_list),
        "promote_min_notes_chars": PROMOTE_MIN_NOTES,
    }
    if drop_list:
        shown = drop_list[:15]
        r.note(
            f"promotion-hook drops (notes >= {PROMOTE_MIN_NOTES} chars but no library row): "
            f"{len(drop_list)} total, showing {len(shown)}"
        )
        for item_id in shown:
            r.note(f"    {item_id}")
        r.status = STATUS_FAIL
    else:
        r.note(f"promotion-hook drops: 0 (every qualifying note >= {PROMOTE_MIN_NOTES} chars has a library row)")
        r.status = STATUS_PASS
    return r


# ---------------------------------------------------------------------------
# Stage 3: Crystal cleanliness
# ---------------------------------------------------------------------------
def _text_is_contaminated(text: str) -> bool:
    t = text or ""
    if "scenario:" in t.lower():
        return True
    if _CONTAM_STEM_ID_RE.search(t):
        return True
    if "blind nate" in t.lower():
        return True
    if "eyes are cast" in t.lower():
        return True
    return False


async def stage3_crystal_cleanliness(conn) -> StageResult:
    r = StageResult(key="crystals", title="Stage 3 — Crystal cleanliness (nate_intelligence_crystals)")
    try:
        # Only LIVE crystals count toward the fuel target / contamination gate.
        # A superseded crystal has already been replaced by a newer, cleaner
        # generation and archived out of the recall path — counting it as
        # "contaminated" (or even as "total") misrepresents what's actually
        # feeding the flywheel. Handle the column being absent gracefully
        # (older schema) by falling back to no filter.
        has_superseded = await _column_exists(conn, CRYSTAL_TABLE, "superseded_by")
        live_clause = " AND superseded_by IS NULL" if has_superseded else ""

        total = await conn.fetchval(
            f"""SELECT COUNT(*) FROM {CRYSTAL_TABLE}
                WHERE origin_surface = 'principal_review'{live_clause}"""
        )
        total_n = int(total or 0)

        contam_rows = await conn.fetch(
            f"""SELECT id, LEFT(crystal_text, 140) AS snippet
                FROM {CRYSTAL_TABLE}
                WHERE origin_surface = 'principal_review'{live_clause}
                  AND (
                    crystal_text ILIKE '%scenario:%'
                    OR crystal_text ~ '[A-Z]{{2}}-G?\\d'
                    OR crystal_text ILIKE '%blind Nate%'
                    OR crystal_text ILIKE '%eyes are cast%'
                  )"""
        )
        contaminated = [{"id": row["id"], "snippet": row["snippet"]} for row in contam_rows]
        contaminated_n = len(contaminated)
        clean_n = total_n - contaminated_n

        r.data = {
            "total": total_n,
            "contaminated": contaminated_n,
            "clean": clean_n,
            "contaminated_rows": contaminated,
            "live_only": has_superseded,
        }
        r.note(f"total (origin_surface='principal_review', live only) = {total_n}")
        if not has_superseded:
            r.note(f"note: 'superseded_by' column not present on {CRYSTAL_TABLE} — no rows excluded as dead/replaced")
        r.note(f"contaminated = {contaminated_n}")
        r.note(f"clean        = {clean_n}")
        if contaminated:
            shown = contaminated[:10]
            r.note(f"contaminated crystals ({contaminated_n} total, showing {len(shown)}):")
            for c in shown:
                r.note(f"    id={c['id']}  {c['snippet']!r}")
            r.status = STATUS_FAIL
        else:
            r.status = STATUS_PASS
        return r
    except Exception as e:  # noqa: BLE001
        return _err_stage("crystals", r.title, CRYSTAL_TABLE, e)


# ---------------------------------------------------------------------------
# Stage 4: Recall (the cycle check)
# ---------------------------------------------------------------------------
async def stage4_recall(conn) -> StageResult:
    r = StageResult(key="recalled", title="Stage 4 — Recall (crystal_recall_log; the cycle check)")
    try:
        row = await conn.fetchrow(
            f"""SELECT COUNT(DISTINCT rl.crystal_id) AS distinct_crystals,
                       COUNT(*) AS total_recalls
                FROM {RECALL_TABLE} rl
                JOIN {CRYSTAL_TABLE} c ON rl.crystal_id = c.id
                WHERE c.origin_surface = 'principal_review'"""
        )
        distinct_crystals = int(row["distinct_crystals"] or 0)
        total_recalls = int(row["total_recalls"] or 0)

        r.data = {"distinct_crystals_recalled": distinct_crystals, "total_recalls": total_recalls}
        r.note(f"distinct principal_review crystals recalled = {distinct_crystals}")
        r.note(f"total recall events                          = {total_recalls}")
        if distinct_crystals == 0:
            r.note("*** FUEL STORED, NOT BURNING *** — zero recall of principal_review crystals.")
            r.note("    the class-aware inject slot now logs to crystal_recall_log on every")
            r.note("    injection (principal_review_crisis_policy._reinforce_pr_guide_recalls);")
            r.note("    zero here means that logging path is broken or the inject isn't firing.")
            r.status = STATUS_FAIL
        else:
            r.status = STATUS_PASS
        return r
    except Exception as e:  # noqa: BLE001
        return _err_stage("recalled", r.title, RECALL_TABLE, e)


# ---------------------------------------------------------------------------
# Orchestration / output
# ---------------------------------------------------------------------------
def _dashboard_line(stages: Dict[str, StageResult]) -> str:
    def _get(key: str, path: List[str], default=0):
        d = stages[key].data
        for p in path:
            if not isinstance(d, dict) or p not in d:
                return default
            d = d[p]
        return d

    scored = _get("scored", ["distinct_item_ids"])
    guides = _get("guides", ["promoted"])
    clean = _get("crystals", ["clean"])
    total_c = _get("crystals", ["total"])
    recalled = _get("recalled", ["total_recalls"])
    return f"scored {scored}/50 · guides {guides} · crystals {clean} clean/{total_c} total · recalled {recalled}"


def _overall_status(stages: Dict[str, StageResult]) -> str:
    statuses = {s.status for s in stages.values()}
    if STATUS_FAIL in statuses or STATUS_ERROR in statuses:
        return STATUS_FAIL if STATUS_FAIL in statuses else STATUS_ERROR
    if STATUS_WARN in statuses:
        return STATUS_WARN
    return STATUS_PASS


def _print_text(stages: Dict[str, StageResult]) -> None:
    print("=== verify_fuel_cycle (Little Nate learning flywheel) ===")
    print(_dashboard_line(stages))
    print()
    for key in ("scored", "guides", "crystals", "recalled"):
        s = stages[key]
        print(f"--- {s.title} ---")
        for line in s.lines:
            print(f"  {line}")
        print(f"  [{s.status}]")
        print()

    clean = stages["crystals"].data.get("clean", 0) if stages["crystals"].status != STATUS_ERROR else 0
    pct = (clean / FUEL_TARGET * 100) if FUEL_TARGET else 0.0
    print(f"Progress toward {FUEL_TARGET}-row target: {clean}/{FUEL_TARGET} ({pct:.1f}%)")
    print()
    for key in ("scored", "guides", "crystals", "recalled"):
        s = stages[key]
        print(f"  [{s.status}] {s.key}")


def _print_json(stages: Dict[str, StageResult]) -> None:
    clean = stages["crystals"].data.get("clean", 0) if stages["crystals"].status != STATUS_ERROR else 0
    payload = {
        "dashboard": _dashboard_line(stages),
        "overall_status": _overall_status(stages),
        "fuel_target": FUEL_TARGET,
        "fuel_progress": clean,
        "fuel_progress_pct": round((clean / FUEL_TARGET * 100) if FUEL_TARGET else 0.0, 1),
        "stages": {k: v.to_json() for k, v in stages.items()},
    }
    print(json.dumps(payload, indent=2, default=str))


async def _run(dsn: str, as_json: bool) -> int:
    try:
        import asyncpg
    except ImportError:
        msg = "asyncpg required (pip install asyncpg)"
        print(json.dumps({"status": "error", "message": msg}) if as_json else f"FAIL: {msg}")
        return 2

    try:
        conn = await asyncpg.connect(dsn)
    except Exception as e:  # noqa: BLE001
        msg = f"could not connect to database: {type(e).__name__}: {e}"
        print(json.dumps({"status": "error", "message": msg}) if as_json else f"FAIL: {msg}")
        return 2

    try:
        try:
            await conn.execute("SET statement_timeout = '60s'")
        except Exception:
            pass  # non-fatal — proceed without the guard rather than aborting the audit

        stages: Dict[str, StageResult] = {}
        stages["scored"] = await stage1_scored_gold(conn)
        stages["guides"] = await stage2_guide_promotion(conn)
        stages["crystals"] = await stage3_crystal_cleanliness(conn)
        stages["recalled"] = await stage4_recall(conn)

        if as_json:
            _print_json(stages)
        else:
            _print_text(stages)

        overall = _overall_status(stages)
        return 1 if overall in (STATUS_FAIL, STATUS_ERROR) else 0
    finally:
        await conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of text")
    ap.add_argument(
        "--offline",
        action="store_true",
        help="skip the live DB audit unconditionally (CI-safe no-op; exits 0)",
    )
    args = ap.parse_args()

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")

    if args.offline or not dsn:
        reason = "explicit --offline" if args.offline else "no DATABASE_URL set"
        msg = f"verify_fuel_cycle: skipped ({reason}) — this audits production data, not CI fixtures"
        if args.json:
            print(json.dumps({"status": "skipped", "reason": reason}))
        else:
            print(msg)
        return 0

    return asyncio.run(_run(dsn, args.json))


if __name__ == "__main__":
    sys.exit(main())
