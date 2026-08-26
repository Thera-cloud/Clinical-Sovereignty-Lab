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

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.alphaln_gym")

# C_emo > this for 3 consecutive scored turns = regulation.
_REGULATION_THRESHOLD = 0.6
_REGULATION_WINDOW = 3

_ENV_FLAG = "ENABLE_ALPHALN_GYM"

# Hard ceiling on admin-triggered runs; nightly stagger uses its own
# ``max_matches_per_night()``. We keep this small so the admin console
# stays snappy.
ADMIN_MAX_MATCHES = 4


def is_enabled() -> bool:
    raw = (os.getenv(_ENV_FLAG) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


_nevedal_mod = None


def _nevedal():
    """Reuse NevedalEngine._compute_c_emo — do not duplicate the formula."""
    global _nevedal_mod
    if _nevedal_mod is None:
        import importlib.util
        from pathlib import Path

        # File-path load avoids app.services.__init__ (Stripe) side effects in CI.
        path = Path(__file__).resolve().parent / "nevedal_engine.py"
        spec = importlib.util.spec_from_file_location("nevedal_engine_alphaln_gym", path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        _nevedal_mod = mod
    return _nevedal_mod


def _c_emo(p_ent: float, t_tunnel: float, gamma_env: float, e_g: float) -> float:
    mod = _nevedal()
    eng = object.__new__(mod.NevedalEngine)
    eng.constants = mod.NevedalConstants()
    return float(
        mod.NevedalEngine._compute_c_emo(
            eng,
            float(p_ent),
            float(t_tunnel),
            float(gamma_env),
            float(e_g),
            elapsed_t=0.0,
        )
    )


def _params_from_turn(turn: Dict[str, Any], prior_c: Optional[float]) -> Dict[str, float]:
    """Map a {role, text} turn (or explicit params) onto C_emo inputs."""
    if all(k in (turn or {}) for k in ("p_ent", "t_tunnel", "gamma_env", "e_g")):
        return {
            "p_ent": float(turn["p_ent"]),
            "t_tunnel": float(turn["t_tunnel"]),
            "gamma_env": float(turn["gamma_env"]),
            "e_g": float(turn["e_g"]),
        }
    text = str((turn or {}).get("text") or turn.get("content") or "").lower()
    role = str((turn or {}).get("role") or "").lower()
    p_ent = 0.35
    t_tunnel = 0.30
    gamma_env = 0.45
    e_g = 0.55
    if any(k in text for k in ("hear", "with you", "stay with", "what i'm hearing")):
        p_ent += 0.25
        t_tunnel += 0.25
        gamma_env -= 0.10
        e_g -= 0.12
    if "?" in text and role in ("nate", "assistant", "ai"):
        t_tunnel += 0.15
        p_ent += 0.08
    if any(k in text for k in ("can't", "crisis", "hurt", "rage", "leave")):
        e_g += 0.20
        gamma_env += 0.10
        p_ent -= 0.05
    if any(k in text for k in ("quieter", "stay with it", "okay")):
        e_g -= 0.15
        p_ent += 0.10
        t_tunnel += 0.10
    if prior_c is not None and prior_c >= _REGULATION_THRESHOLD:
        p_ent += 0.05
        t_tunnel += 0.05
        gamma_env -= 0.05
    return {
        "p_ent": max(0.05, min(1.0, p_ent)),
        "t_tunnel": max(0.05, min(1.0, t_tunnel)),
        "gamma_env": max(0.05, min(1.0, gamma_env)),
        "e_g": max(0.05, min(1.0, e_g)),
    }


def score_regulation(match_transcript: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Mark regulation when C_emo > 0.6 for 3 consecutive turns.

    # QUANTUM-CRYSTAL-ARCH — reuses NevedalEngine._compute_c_emo (no formula copy).

    ``match_transcript`` is a list of turn dicts (bakeoff trajectory or
    explicit ``p_ent``/``t_tunnel``/``gamma_env``/``e_g`` params).
    """
    turns = list(match_transcript or [])
    scores: List[float] = []
    escalations = 0
    prior: Optional[float] = None
    for t in turns:
        params = _params_from_turn(t if isinstance(t, dict) else {}, prior)
        c = _c_emo(
            params["p_ent"],
            params["t_tunnel"],
            params["gamma_env"],
            params["e_g"],
        )
        if prior is not None and c < prior - 0.08:
            escalations += 1
        scores.append(c)
        prior = c

    achieved = False
    turns_to: Optional[int] = None
    need = _REGULATION_WINDOW
    for i in range(len(scores) - need + 1):
        window = scores[i : i + need]
        if all(s > _REGULATION_THRESHOLD for s in window):
            achieved = True
            turns_to = i + need  # 1-based index of window end
            break
    return {
        "regulation_achieved": achieved,
        "turns_to_regulation": turns_to,
        "escalation_events": escalations,
        "c_emo_series": [round(s, 4) for s in scores],
    }


def _aggregate_regulation(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not results:
        return {
            "regulation_achieved": False,
            "turns_to_regulation": None,
            "escalation_events": 0,
        }
    achieved_any = any(r.get("regulation_achieved") for r in results)
    times = [
        int(r["turns_to_regulation"])
        for r in results
        if r.get("regulation_achieved") and r.get("turns_to_regulation") is not None
    ]
    return {
        "regulation_achieved": achieved_any,
        "turns_to_regulation": min(times) if times else None,
        "escalation_events": sum(int(r.get("escalation_events") or 0) for r in results),
    }


async def _score_night_regulation(
    db_pool,
    result: Dict[str, Any],
    max_matches: int,
) -> Dict[str, Any]:
    """Score bakeoff trajectories from the result payload or recent match rows."""
    scored: List[Dict[str, Any]] = []
    for key in ("trajectory_a", "trajectory_b", "match_transcript"):
        traj = (result or {}).get(key)
        if isinstance(traj, list) and traj:
            scored.append(score_regulation(traj))
    matches = (result or {}).get("matches") or []
    if isinstance(matches, list):
        for m in matches:
            if not isinstance(m, dict):
                continue
            for key in ("trajectory_a", "trajectory_b", "transcript"):
                traj = m.get(key)
                if isinstance(traj, list) and traj:
                    scored.append(score_regulation(traj))
    if not scored and db_pool is not None:
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT trajectory_a, trajectory_b
                         FROM nate_clinical_bakeoff_matches
                        ORDER BY created_at DESC
                        LIMIT $1""",
                    max(1, int(max_matches or 4)),
                )
            for r in rows or []:
                for key in ("trajectory_a", "trajectory_b"):
                    traj = r[key]
                    if isinstance(traj, str):
                        try:
                            traj = json.loads(traj)
                        except Exception:
                            traj = []
                    if isinstance(traj, list) and traj:
                        scored.append(score_regulation(traj))
        except Exception as exc:
            logger.warning("alphaln gym regulation read failed: %s", exc)
    return _aggregate_regulation(scored)


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
        reg = await _score_night_regulation(db_pool, result, max_matches)
        result = dict(result or {})
        result["regulation"] = {
            "regulation_achieved": reg["regulation_achieved"],
            "turns_to_regulation": reg["turns_to_regulation"],
            "escalation_events": reg["escalation_events"],
        }
        async with db_pool.acquire() as conn:
            await conn.execute(
                """UPDATE alphaln_gym_runs
                      SET status=$2,
                          completed_at=NOW(),
                          matches_attempted=$3,
                          matches_complete=$4,
                          preferences_written=$5,
                          result_summary=$6,
                          error_text=$7,
                          turns_to_regulation=$8,
                          regulation_achieved=$9,
                          escalation_events=$10
                    WHERE id=$1""",
                run_id,
                status,
                int(result.get("matches_attempted") or 0),
                int(result.get("matches_complete") or 0),
                int(result.get("preferences_written") or 0),
                json.dumps(result or {}),
                None if result.get("ok") else str(result.get("reason") or "unknown"),
                reg["turns_to_regulation"],
                bool(reg["regulation_achieved"]),
                int(reg["escalation_events"] or 0),
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
                      preferences_written, error_text,
                      turns_to_regulation, regulation_achieved, escalation_events
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
                "turns_to_regulation": r["turns_to_regulation"],
                "regulation_achieved": bool(r["regulation_achieved"]),
                "escalation_events": int(r["escalation_events"] or 0),
            }
            for r in rows
        ]
    }
