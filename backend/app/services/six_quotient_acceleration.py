"""
D.13 flywheel accelerators — free labels from live predictors.

1) Cycle / therapeutic prediction calibration (Brier)
2) PGSD coherence trajectory vs battery θ (anti-memorization)
3) PMB-style aggregated seeds → scenario bank drafts

Privacy: aggregates require MIN_CLIENTS distinct users. No PII in seeds.
Flag: ENABLE_SIX_QUOTIENT_ACCELERATION (default false).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sovereign.six_quotient_acceleration")

MIN_CLIENTS = 5

# Domain → six-quotient section for PMB/cycle-mined drafts
_DOMAIN_TO_SECTION = {
    "addiction": "AQ",
    "sexual_desire": "EQ",
    "relational": "SQ",
    "group_dynamics": "SQ",
    "legacy": "MQ",
    "grief": "EQ",
    "anxiety": "AQ",
    "depression": "EQ",
    "habit": "IQ",
    "spiritual": "CQ",
}


def _flag_on() -> bool:
    return os.getenv("ENABLE_SIX_QUOTIENT_ACCELERATION", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def acceleration_enabled() -> bool:
    """Public alias for admin/status surfaces."""
    return _flag_on()


def brier_score(pairs: List[Tuple[float, float]]) -> Optional[float]:
    """pairs: (probability 0-1, outcome 0|1). Lower is better."""
    if not pairs:
        return None
    s = 0.0
    for p, o in pairs:
        p = max(0.0, min(1.0, float(p)))
        o = 1.0 if float(o) >= 0.5 else 0.0
        s += (p - o) ** 2
    return round(s / len(pairs), 6)


def pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    n = min(len(xs), len(ys))
    if n < 3:
        return None
    xs, ys = xs[:n], ys[:n]
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denx = sum((x - mx) ** 2 for x in xs) ** 0.5
    deny = sum((y - my) ** 2 for y in ys) ** 0.5
    if denx <= 0 or deny <= 0:
        return None
    return round(num / (denx * deny), 4)


async def resolve_cycle_predictions(db_pool) -> Dict[str, Any]:
    """
    Resolve pending cycle_predictions whose predicted_at is in the past.
    Outcome hit if mean observation in ±1 day window is elevated for peak_risk
    (value >= 0.55) or depressed for trough_* (value <= 0.45).
    """
    if not db_pool:
        return {"ok": False, "error": "no_db", "resolved": 0}
    resolved = 0
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, user_id, domain, predicted_event, predicted_at, confidence
                   FROM cycle_predictions
                   WHERE status = 'pending'
                     AND predicted_at < NOW() - INTERVAL '12 hours'
                     AND predicted_at > NOW() - INTERVAL '45 days'
                   ORDER BY predicted_at ASC
                   LIMIT 200"""
            )
            for r in rows:
                obs = await conn.fetchrow(
                    """SELECT AVG(value) AS avg_v, COUNT(*)::int AS n
                       FROM cycle_observations
                       WHERE user_id = $1 AND domain = $2
                         AND observed_at BETWEEN $3::timestamptz - INTERVAL '1 day'
                                            AND $3::timestamptz + INTERVAL '1 day'""",
                    r["user_id"],
                    r["domain"],
                    r["predicted_at"],
                )
                if not obs or not obs["n"] or obs["n"] < 1:
                    continue
                avg_v = float(obs["avg_v"] or 0)
                ev = (r["predicted_event"] or "").lower()
                if "peak" in ev:
                    hit = avg_v >= 0.55
                elif "trough" in ev:
                    hit = avg_v <= 0.45
                else:
                    hit = avg_v >= 0.5
                outcome = "hit" if hit else "miss"
                await conn.execute(
                    """UPDATE cycle_predictions
                       SET status = 'resolved', actual_outcome = $2
                       WHERE id = $1""",
                    r["id"],
                    outcome,
                )
                resolved += 1
    except Exception as e:
        logger.warning("resolve_cycle_predictions: %s", e)
        return {"ok": False, "error": str(e)[:200], "resolved": resolved}
    return {"ok": True, "resolved": resolved}


async def compute_world_model_calibration(db_pool) -> Dict[str, Any]:
    """Aggregated Brier from resolved cycle + therapeutic predictions (≥5 clients)."""
    if not db_pool:
        return {"ok": False, "error": "no_db"}
    pairs: List[Tuple[float, float]] = []
    users: set = set()
    try:
        async with db_pool.acquire() as conn:
            cyc = await conn.fetch(
                """SELECT user_id, confidence, actual_outcome
                   FROM cycle_predictions
                   WHERE status = 'resolved'
                     AND actual_outcome IN ('hit', 'miss')
                     AND predicted_at > NOW() - INTERVAL '90 days'
                   LIMIT 2000"""
            )
            for r in cyc:
                users.add(r["user_id"])
                pairs.append(
                    (
                        float(r["confidence"] or 0.5),
                        1.0 if r["actual_outcome"] == "hit" else 0.0,
                    )
                )
            ther = await conn.fetch(
                """SELECT user_id, success_probability, actual_outcome
                   FROM therapeutic_predictions
                   WHERE actual_outcome IS NOT NULL
                     AND created_at > NOW() - INTERVAL '90 days'
                   LIMIT 2000"""
            )
            for r in ther:
                users.add(r["user_id"])
                # actual_outcome stored as REAL success fraction
                pairs.append(
                    (
                        float(r["success_probability"] or 0.5),
                        1.0 if float(r["actual_outcome"] or 0) >= 0.5 else 0.0,
                    )
                )
    except Exception as e:
        logger.warning("world_model_calibration: %s", e)
        return {"ok": False, "error": str(e)[:200], "n_clients": 0}

    n_clients = len(users)
    if n_clients < MIN_CLIENTS:
        return {
            "ok": True,
            "sparse": True,
            "n_clients": n_clients,
            "n_pairs": len(pairs),
            "brier": None,
            "min_clients": MIN_CLIENTS,
        }
    return {
        "ok": True,
        "sparse": False,
        "n_clients": n_clients,
        "n_pairs": len(pairs),
        "brier": brier_score(pairs),
        "min_clients": MIN_CLIENTS,
    }


async def compute_pgsd_live_channel(db_pool, environment: str = "production") -> Dict[str, Any]:
    """
    Mean PGSD coherence delta (latest - prior) across ≥5 clients.
    Correlate recent nightly θ series with weekly mean coherence when possible.
    """
    if not db_pool:
        return {"ok": False, "error": "no_db"}
    try:
        async with db_pool.acquire() as conn:
            deltas = await conn.fetch(
                """WITH ranked AS (
                     SELECT user_id, coherence, computed_at,
                            ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY computed_at DESC) AS rn
                     FROM pgsd_snapshots
                     WHERE computed_at > NOW() - INTERVAL '30 days'
                       AND coherence IS NOT NULL
                   )
                   SELECT a.user_id,
                          a.coherence - b.coherence AS d_coh
                   FROM ranked a
                   JOIN ranked b ON a.user_id = b.user_id AND a.rn = 1 AND b.rn = 2"""
            )
            theta_rows = await conn.fetch(
                """SELECT theta, created_at::date AS d
                   FROM six_quotient_theta_trend
                   WHERE environment = $1 AND run_kind = 'nightly'
                     AND created_at > NOW() - INTERVAL '60 days'
                   ORDER BY created_at ASC""",
                environment,
            )
            coh_by_day = await conn.fetch(
                """SELECT computed_at::date AS d, AVG(coherence) AS avg_coh
                   FROM pgsd_snapshots
                   WHERE computed_at > NOW() - INTERVAL '60 days'
                     AND coherence IS NOT NULL
                   GROUP BY 1
                   ORDER BY 1"""
            )
    except Exception as e:
        logger.warning("pgsd_live_channel: %s", e)
        return {"ok": False, "error": str(e)[:200], "n_clients": 0}

    n_clients = len({r["user_id"] for r in deltas})
    mean_delta = None
    if n_clients >= MIN_CLIENTS and deltas:
        mean_delta = round(
            sum(float(r["d_coh"] or 0) for r in deltas) / len(deltas), 6
        )

    # Align θ and coherence by date for correlation
    coh_map = {str(r["d"]): float(r["avg_coh"]) for r in coh_by_day if r["avg_coh"] is not None}
    xs, ys = [], []
    for r in theta_rows:
        key = str(r["d"])
        if key in coh_map:
            xs.append(float(r["theta"]))
            ys.append(coh_map[key])
    corr = pearson(xs, ys)

    return {
        "ok": True,
        "sparse": n_clients < MIN_CLIENTS,
        "n_clients": n_clients,
        "pgsd_coherence_delta": mean_delta,
        "theta_coherence_corr": corr,
        "aligned_days": len(xs),
        "min_clients": MIN_CLIENTS,
    }


def pmb_seed_from_domains(domain_stats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deterministic de-identified scenario seeds from aggregated cycle domains.
    No client text — clinical structure only.
    """
    seeds = []
    for st in domain_stats:
        domain = str(st.get("domain") or "")
        section = _DOMAIN_TO_SECTION.get(domain, "EQ")
        n = int(st.get("n_clients") or 0)
        if n < MIN_CLIENTS:
            continue
        conf = float(st.get("avg_confidence") or 0.5)
        seeds.append({
            "section": section,
            "title": f"{section} PMB-cycle pattern ({domain})",
            "rubric_focus": (
                f"Test {section} skill under recurring {domain} cycle pressure "
                f"(aggregated n≥{MIN_CLIENTS}, mean_conf={conf:.2f}). "
                "Witness pattern gravity without prescribing; track reconsolidation readiness."
            ),
            "client_says": (
                f"It keeps coming back in waves — same {domain.replace('_', ' ')} pull. "
                "I tell myself I'm past it, then the week turns and I'm right there again."
            ),
            "client_beats": [
                f"It keeps coming back in waves — same {domain.replace('_', ' ')} pull.",
                "I tell myself I'm past it, then the week turns.",
                "Don't give me a worksheet. Just… sit with how stuck this feels.",
            ],
            "dojo_persona": "CRISIS" if section == "AQ" else "SKEPTIC",
            "difficulty_nominal": min(0.9, 0.55 + conf * 0.3),
            "irt_a": 1.15,
            "irt_b": 0.4 + conf * 0.4,
            "status": "pending_review",
            "source": "pmb_mined",
            "provenance_json": {
                "kind": "pmb_cycle_aggregate",
                "domain": domain,
                "n_clients": n,
                "avg_confidence": conf,
                "min_clients": MIN_CLIENTS,
            },
            "safety_flags": ["aggregated_deidentified", "pending_human_review"],
        })
    return seeds


async def mine_pmb_scenario_seeds(db_pool, *, limit: int = 6) -> Dict[str, Any]:
    """Aggregate cycle_detections → draft bank rows (pending_review)."""
    if not db_pool:
        return {"ok": False, "error": "no_db", "inserted": 0}
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT domain,
                          COUNT(DISTINCT user_id)::int AS n_clients,
                          AVG(confidence) AS avg_confidence
                   FROM cycle_detections
                   WHERE detected_at > NOW() - INTERVAL '45 days'
                     AND confidence >= 0.45
                   GROUP BY domain
                   HAVING COUNT(DISTINCT user_id) >= $1
                   ORDER BY AVG(confidence) DESC
                   LIMIT $2""",
                MIN_CLIENTS,
                max(1, min(int(limit or 6), 12)),
            )
    except Exception as e:
        logger.warning("mine_pmb_scenario_seeds query: %s", e)
        return {"ok": False, "error": str(e)[:200], "inserted": 0}

    stats = [dict(r) for r in rows]
    seeds = pmb_seed_from_domains(stats)
    from app.services.six_quotient_scenario_bank import insert_draft

    inserted_keys: List[str] = []
    for seed in seeds:
        try:
            key = await insert_draft(db_pool, seed)
            if key:
                inserted_keys.append(key)
        except Exception as e:
            logger.warning("pmb seed insert: %s", e)
    return {
        "ok": True,
        "domains": stats,
        "seeds": len(seeds),
        "inserted": len(inserted_keys),
        "keys": inserted_keys,
    }


async def run_acceleration_pass(
    db_pool,
    *,
    environment: str = "production",
    trend_id: Optional[int] = None,
    mine_pmb: bool = False,
    cycle_engine: Any = None,
) -> Dict[str, Any]:
    """Full acceleration tick — measurement meta only unless mine_pmb."""
    if not _flag_on():
        return {"ok": False, "error": "ENABLE_SIX_QUOTIENT_ACCELERATION off", "skipped": True}

    # QUANTUM-CRYSTAL-ARCH — refill free labels before resolve/Brier
    sweep: Dict[str, Any] = {"skipped": True}
    if cycle_engine is not None and hasattr(cycle_engine, "sweep_and_predict"):
        try:
            sweep = await cycle_engine.sweep_and_predict(predict=True)
        except Exception as e:
            logger.warning("cycle sweep_and_predict: %s", e)
            sweep = {"ok": False, "error": str(e)[:160]}

    resolve = await resolve_cycle_predictions(db_pool)
    world = await compute_world_model_calibration(db_pool)
    pgsd = await compute_pgsd_live_channel(db_pool, environment)
    pmb: Dict[str, Any] = {"skipped": True}
    if mine_pmb and os.getenv("ENABLE_SIX_QUOTIENT_SCENARIO_GEN", "false").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        pmb = await mine_pmb_scenario_seeds(db_pool)

    meta = {
        "sweep": sweep,
        "resolve": resolve,
        "world_model": world,
        "pgsd": pgsd,
        "pmb": pmb,
        "at": datetime.now(timezone.utc).isoformat(),
    }

    # Patch latest trend row (or specific id)
    try:
        async with db_pool.acquire() as conn:
            if trend_id is not None:
                await conn.execute(
                    """UPDATE six_quotient_theta_trend
                       SET world_model_brier = $2,
                           world_model_n = $3,
                           pgsd_coherence_delta = $4,
                           pgsd_n_clients = $5,
                           acceleration_meta = $6::jsonb
                       WHERE id = $1""",
                    trend_id,
                    world.get("brier"),
                    int(world.get("n_clients") or 0),
                    pgsd.get("pgsd_coherence_delta"),
                    int(pgsd.get("n_clients") or 0),
                    json.dumps(meta),
                )
            else:
                await conn.execute(
                    """UPDATE six_quotient_theta_trend
                       SET world_model_brier = $2,
                           world_model_n = $3,
                           pgsd_coherence_delta = $4,
                           pgsd_n_clients = $5,
                           acceleration_meta = $6::jsonb
                       WHERE id = (
                         SELECT id FROM six_quotient_theta_trend
                         WHERE environment = $1
                         ORDER BY created_at DESC LIMIT 1
                       )""",
                    environment,
                    world.get("brier"),
                    int(world.get("n_clients") or 0),
                    pgsd.get("pgsd_coherence_delta"),
                    int(pgsd.get("n_clients") or 0),
                    json.dumps(meta),
                )
    except Exception as e:
        logger.warning("acceleration trend patch: %s", e)
        meta["trend_patch_error"] = str(e)[:160]

    logger.info(
        "Acceleration pass: brier=%s n=%s pgsd_d=%s",
        world.get("brier"),
        world.get("n_clients"),
        pgsd.get("pgsd_coherence_delta"),
    )
    return {"ok": True, **meta}
