"""AlphaLN Slice 6 — Trajectory search prototype (Loop C skeleton).

MCTS-style rollout skeleton over reactive-patient sims. The real search loop
requires (a) a reliable patient simulator (Slice 5), (b) a value model that
scores partial trajectories, and (c) a promotion pipeline that consumes
winners (Slice 8). Until those close, this module is deliberately a stub:

- ``schedule_run`` records the *intent* to run a search.
- ``execute_run`` returns ``{"status": "not_implemented"}`` unless
  ``ENABLE_ALPHALN_TRAJECTORY_SEARCH`` is on AND a real search callable is
  wired into ``app.state.alphaln_trajectory_engine``.

This lets us:
- Land the schema (migration 424) and API surface now (dark).
- Give the AlphaLN console a place to display "the queen has scheduled N
  searches, all pending" without pretending we can plan life trajectories.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.alphaln_trajectory")

_ENV_FLAG = "ENABLE_ALPHALN_TRAJECTORY_SEARCH"

MAX_DEPTH_DEFAULT = 3
MAX_ROLLOUTS_DEFAULT = 8


def is_enabled() -> bool:
    raw = (os.getenv(_ENV_FLAG) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _root_seed_from(scenario: str, admin_user: str) -> str:
    """Deterministic opaque seed from scenario + admin. No raw PII in the seed."""
    return hashlib.sha256(f"{admin_user}:{scenario}".encode("utf-8")).hexdigest()[:24]


async def schedule_run(
    db_pool,
    admin_user: str,
    scenario: str,
    max_depth: int = MAX_DEPTH_DEFAULT,
    max_rollouts: int = MAX_ROLLOUTS_DEFAULT,
) -> Dict[str, Any]:
    if db_pool is None:
        return {"ok": False, "reason": "no_db"}
    if not is_enabled():
        return {"ok": False, "reason": "flag_off"}
    seed = _root_seed_from(scenario, admin_user)
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO alphaln_trajectory_runs
                   (admin_user, status, root_seed, max_depth, max_rollouts)
                 VALUES ($1, 'queued', $2, $3, $4)
              RETURNING id""",
            admin_user, seed, int(max_depth), int(max_rollouts),
        )
    return {"ok": True, "run_id": int(row["id"]), "root_seed": seed}


async def execute_run(db_pool, app_state, run_id: int) -> Dict[str, Any]:
    """Attempt to run trajectory search. Stub unless flag+engine both present."""
    if db_pool is None:
        return {"ok": False, "reason": "no_db"}

    if not is_enabled():
        async with db_pool.acquire() as conn:
            await conn.execute(
                """UPDATE alphaln_trajectory_runs
                      SET status='flag_off', finished_at=NOW()
                    WHERE id=$1""",
                run_id,
            )
        return {"ok": True, "status": "flag_off"}

    engine = getattr(app_state, "alphaln_trajectory_engine", None) if app_state else None
    if engine is None or not callable(engine):
        async with db_pool.acquire() as conn:
            await conn.execute(
                """UPDATE alphaln_trajectory_runs
                      SET status='error', finished_at=NOW(),
                          error_text='engine_not_wired'
                    WHERE id=$1""",
                run_id,
            )
        return {"ok": False, "status": "not_implemented", "reason": "engine_not_wired"}

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT root_seed, max_depth, max_rollouts FROM alphaln_trajectory_runs WHERE id=$1",
            run_id,
        )
        if not row:
            return {"ok": False, "reason": "run_not_found"}

    try:
        result = await engine(
            root_seed=row["root_seed"],
            max_depth=row["max_depth"],
            max_rollouts=row["max_rollouts"],
        )
        async with db_pool.acquire() as conn:
            await conn.execute(
                """UPDATE alphaln_trajectory_runs
                      SET status='complete', finished_at=NOW(),
                          best_score=$2,
                          result_summary=$3
                    WHERE id=$1""",
                run_id,
                float(result.get("best_score") or 0.0),
                json.dumps(result or {}),
            )
        return {"ok": True, "status": "complete", "result": result}
    except Exception as exc:
        logger.warning("alphaln trajectory run %s failed: %s", run_id, exc)
        async with db_pool.acquire() as conn:
            await conn.execute(
                """UPDATE alphaln_trajectory_runs
                      SET status='error', finished_at=NOW(),
                          error_text=$2
                    WHERE id=$1""",
                run_id, str(exc)[:500],
            )
        return {"ok": False, "reason": str(exc)[:200]}


async def cleanup_orphaned_runs(db_pool, max_age_hours: int = 2) -> Dict[str, Any]:
    """Mark trajectory runs stuck in 'running' > max_age_hours as errored.

    Called by AlphaLNAuditor and exposed via /api/admin/alphaln/health so
    orphans surface in the invariant report. Safe to run when the flag is off.
    """
    if db_pool is None:
        return {"cleaned": 0}
    async with db_pool.acquire() as conn:
        cleaned = await conn.fetchval(
            """WITH updated AS (
                   UPDATE alphaln_trajectory_runs
                      SET status='error', finished_at=NOW(),
                          error_text='orphaned_by_auditor'
                    WHERE status='running'
                      AND started_at < NOW() - ($1 || ' hours')::interval
                  RETURNING id
               )
               SELECT COUNT(*) FROM updated""",
            str(int(max_age_hours)),
        )
    return {"cleaned": int(cleaned or 0)}


async def list_recent_runs(db_pool, admin_user: str, limit: int = 20) -> Dict[str, Any]:
    if db_pool is None:
        return {"runs": []}
    limit = max(1, min(int(limit or 20), 200))
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, admin_user, started_at, finished_at, status,
                      root_seed, max_depth, max_rollouts, best_score, error_text
                 FROM alphaln_trajectory_runs
                WHERE admin_user = $1
                ORDER BY started_at DESC
                LIMIT $2""",
            admin_user, limit,
        )
    return {
        "runs": [
            {
                "id": int(r["id"]),
                "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
                "status": r["status"],
                "root_seed": r["root_seed"],
                "max_depth": r["max_depth"],
                "max_rollouts": r["max_rollouts"],
                "best_score": float(r["best_score"]) if r["best_score"] is not None else None,
                "error_text": r["error_text"],
            }
            for r in rows
        ]
    }
