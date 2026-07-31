"""Ops sensors on existing LN7 rollback — p99 latency + error rate (N≥30 floor).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ln7_serve_health")

MIN_REQUEST_FLOOR = int(os.getenv("LN7_SERVE_MIN_REQUESTS", "30"))
P99_MS = float(os.getenv("LN7_SERVE_P99_MS", "8000"))
ERROR_RATE_MAX = float(os.getenv("LN7_SERVE_ERROR_RATE", "0.005"))
WINDOW_MINUTES = int(os.getenv("LN7_SERVE_WINDOW_MIN", "5"))


def _percentile(xs: List[float], p: float) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    if len(ys) == 1:
        return float(ys[0])
    k = (len(ys) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(ys) - 1)
    if f == c:
        return float(ys[f])
    return float(ys[f] + (ys[c] - ys[f]) * (k - f))


async def _active_candidates(conn) -> List[str]:
    rows = await conn.fetch(
        """
        SELECT revision_id FROM ln7_revisions
        WHERE active = TRUE
          AND revision_id NOT IN ('LN7-baseline', 'LN7-fast-baseline')
        """
    )
    return [str(r["revision_id"]) for r in rows]


async def _window_metrics(conn, revision_id: str) -> Dict[str, Any]:
    rows = await conn.fetch(
        """
        SELECT COALESCE(latency_ms, 0)::float AS latency_ms,
               CASE WHEN passed THEN 0 ELSE 1 END AS err
        FROM ln7_coding_outcomes
        WHERE revision_id = $1
          AND created_at >= NOW() - ($2::int * INTERVAL '1 minute')
        ORDER BY created_at DESC
        LIMIT 500
        """,
        revision_id,
        WINDOW_MINUTES,
    )
    n = len(rows)
    lat = [float(r["latency_ms"] or 0) for r in rows]
    errs = sum(int(r["err"] or 0) for r in rows)
    return {
        "total_requests": n,
        "p99_latency_ms": _percentile(lat, 99) if lat else 0.0,
        "error_rate": (errs / n) if n else 0.0,
    }


async def run_serve_health_cycle(db_pool) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "error": "no_db"}
    checked: List[Dict[str, Any]] = []
    rollbacks: List[Dict[str, Any]] = []
    async with db_pool.acquire() as conn:
        revs = await _active_candidates(conn)
    if not revs:
        return {"ok": True, "checked": [], "note": "no_promoted_candidate"}

    from app.services.ln7_rollback import rollback_serving_revision

    for rid in revs:
        async with db_pool.acquire() as conn:
            window = await _window_metrics(conn, rid)
        entry = {"revision_id": rid, **window, "triggered": False}
        if window["total_requests"] < MIN_REQUEST_FLOOR:
            entry["skipped"] = f"n<{MIN_REQUEST_FLOOR}"
            checked.append(entry)
            continue
        ops_1 = window["p99_latency_ms"] > P99_MS
        ops_2 = window["error_rate"] > ERROR_RATE_MAX
        if ops_1 or ops_2:
            reason = []
            if ops_1:
                reason.append(f"p99={window['p99_latency_ms']:.0f}>{P99_MS}")
            if ops_2:
                reason.append(f"err={window['error_rate']:.4f}>{ERROR_RATE_MAX}")
            out = await rollback_serving_revision(
                db_pool,
                rid,
                reason=";".join(reason),
                trigger="ops_sensor",
            )
            entry["triggered"] = True
            entry["rollback"] = out
            rollbacks.append(entry)
            logger.warning("LN7 serve health rollback %s %s", rid, reason)
        checked.append(entry)
    return {"ok": True, "checked": checked, "rollbacks": rollbacks}
