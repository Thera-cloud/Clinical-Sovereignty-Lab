"""AlphaLN Slice 5 — Sim gym control.

Thin wrapper around the existing ``nate_clinical_bakeoff_agent.run_night``
so DrNevedal1 can trigger a bakeoff from the AlphaLN admin console instead of
waiting for the nightly stagger window (07:00 UTC).

Invariants:
- Dark-shipped: if ``ENABLE_ALPHALN_GYM`` is off, ``trigger_run`` records a
  ``flag_off`` row and returns without invoking the bakeoff engine.
- All runs are attributed to ``admin_user`` in ``alphaln_gym_runs``.
- We NEVER call the engine directly; we route through
  ``app.state.nate_clinical_bakeoff_agent`` so we inherit its rate ceiling,
  variant persistence, and CEO alerts.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.alphaln_gym")

_ENV_FLAG = "ENABLE_ALPHALN_GYM"

# Hard ceiling on admin-triggered runs; nightly stagger uses its own
# ``max_matches_per_night()``. We keep this small so the admin console
# stays snappy.
ADMIN_MAX_MATCHES = 4


def is_enabled() -> bool:
    raw = (os.getenv(_ENV_FLAG) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


async def trigger_run(
    db_pool,
    app_state,
    admin_user: str,
    max_matches: Optional[int] = None,
) -> Dict[str, Any]:
    """Insert an audit row, invoke the bakeoff (if flag on), then update row."""
    if db_pool is None:
        return {"ok": False, "reason": "no_db"}
    max_matches = min(int(max_matches or ADMIN_MAX_MATCHES), ADMIN_MAX_MATCHES)

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO alphaln_gym_runs
                   (admin_user, status, max_matches)
                 VALUES ($1, 'queued', $2)
              RETURNING id""",
            admin_user, max_matches,
        )
        run_id = row["id"]

    if not is_enabled():
        async with db_pool.acquire() as conn:
            await conn.execute(
                """UPDATE alphaln_gym_runs
                      SET status='flag_off', completed_at=NOW()
                    WHERE id=$1""",
                run_id,
            )
        return {"ok": True, "run_id": run_id, "status": "flag_off"}

    agent = getattr(app_state, "nate_clinical_bakeoff_agent", None) if app_state else None
    if agent is None or not hasattr(agent, "run_night"):
        async with db_pool.acquire() as conn:
            await conn.execute(
                """UPDATE alphaln_gym_runs
                      SET status='error', completed_at=NOW(),
                          error_text='bakeoff_agent_missing'
                    WHERE id=$1""",
                run_id,
            )
        return {"ok": False, "run_id": run_id, "reason": "bakeoff_agent_missing"}

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE alphaln_gym_runs SET status='running' WHERE id=$1", run_id,
        )

    try:
        result = await agent.run_night(max_matches=max_matches)
        status = "complete" if result.get("ok") else "error"
        async with db_pool.acquire() as conn:
            await conn.execute(
                """UPDATE alphaln_gym_runs
                      SET status=$2,
                          completed_at=NOW(),
                          matches_attempted=$3,
                          matches_complete=$4,
                          preferences_written=$5,
                          result_summary=$6,
                          error_text=$7
                    WHERE id=$1""",
                run_id,
                status,
                int(result.get("matches_attempted") or 0),
                int(result.get("matches_complete") or 0),
                int(result.get("preferences_written") or 0),
                result,
                None if result.get("ok") else str(result.get("reason") or "unknown"),
            )
        return {"ok": True, "run_id": run_id, "status": status, "result": result}
    except Exception as exc:
        logger.warning("alphaln gym run %s failed: %s", run_id, exc)
        async with db_pool.acquire() as conn:
            await conn.execute(
                """UPDATE alphaln_gym_runs
                      SET status='error', completed_at=NOW(),
                          error_text=$2
                    WHERE id=$1""",
                run_id, str(exc)[:500],
            )
        return {"ok": False, "run_id": run_id, "reason": str(exc)[:200]}


async def list_recent_runs(db_pool, admin_user: str, limit: int = 20) -> Dict[str, Any]:
    if db_pool is None:
        return {"runs": []}
    limit = max(1, min(int(limit or 20), 200))
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, admin_user, triggered_at, completed_at, status,
                      max_matches, matches_attempted, matches_complete,
                      preferences_written, error_text
                 FROM alphaln_gym_runs
                WHERE admin_user = $1
                ORDER BY triggered_at DESC
                LIMIT $2""",
            admin_user, limit,
        )
    return {
        "runs": [
            {
                "id": int(r["id"]),
                "admin_user": r["admin_user"],
                "triggered_at": r["triggered_at"].isoformat() if r["triggered_at"] else None,
                "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
                "status": r["status"],
                "max_matches": r["max_matches"],
                "matches_attempted": r["matches_attempted"],
                "matches_complete": r["matches_complete"],
                "preferences_written": r["preferences_written"],
                "error_text": r["error_text"],
            }
            for r in rows
        ]
    }
