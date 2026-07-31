"""F1 economics gate + cold-start bootstrap for hive_burst (Phase A).

Bootstrap: first N windows (governance.bootstrap_burst_windows) under
bootstrap_spend_cap_usd are CPAI-exempt. After N windows *and* ≥1 accepted
improvement, CPAI governs (YELLOW over yellow_multiplier × baseline → refuse).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("ln7_burst_economics")


def _gov() -> Dict[str, Any]:
    try:
        from app.services.ln7_frozen_config import load_json

        return load_json("governance.json", {}) or {}
    except Exception:
        return {}


async def burst_spend_stats(db_pool) -> Dict[str, Any]:
    """Trailing hive_burst window count, spend, accepted improvements."""
    empty = {
        "windows": 0,
        "spend_usd": 0.0,
        "accepted_improvements": 0,
    }
    if not db_pool:
        return empty
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*)::int AS windows,
                    COALESCE(SUM(cost_usd), 0)::float AS spend_usd,
                    COALESCE(SUM(
                        CASE
                            WHEN COALESCE(
                                (metrics_json->>'accepted_improvement')::int, 0
                            ) > 0
                            THEN 1 ELSE 0
                        END
                    ), 0)::int AS accepted_improvements
                FROM outcome_envelope
                WHERE loop_name = 'hive'
                  AND event_kind = 'hive_burst'
                """
            )
        if not row:
            return empty
        return {
            "windows": int(row["windows"] or 0),
            "spend_usd": float(row["spend_usd"] or 0.0),
            "accepted_improvements": int(row["accepted_improvements"] or 0),
        }
    except Exception as e:
        logger.warning("burst_spend_stats failed: %s", e)
        return {**empty, "error": str(e)}


async def evaluate_burst_economics(
    db_pool,
    *,
    estimated_cost_usd: float = 0.0,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Return {ok, mode, reason?, stats, gov_slice}.

    Dry-run / LN7_HIVE_DRY_RUN is always exempt (no paid spend).
    Missing observability (stats error with db present) → refuse (fail-safe).
    """
    if dry_run:
        return {
            "ok": True,
            "mode": "dry_run_exempt",
            "stats": {},
            "gov_slice": {},
        }

    gov = _gov()
    n_boot = int(gov.get("bootstrap_burst_windows") or 5)
    cap = float(gov.get("bootstrap_spend_cap_usd") or 75.0)
    yellow_mult = float(gov.get("cpai_yellow_multiplier") or 1.5)
    # Optional welded CPAI baseline USD per accepted improvement (post-bootstrap).
    cpai_baseline = float(gov.get("cpai_baseline_usd") or 25.0)

    stats = await burst_spend_stats(db_pool)
    if stats.get("error") and db_pool is not None:
        return {
            "ok": False,
            "mode": "observability_fail",
            "reason": "WATCHDOG_BLIND_ALARM: cannot read burst spend",
            "stats": stats,
            "gov_slice": {"bootstrap_burst_windows": n_boot, "cap": cap},
        }

    windows = int(stats.get("windows") or 0)
    spend = float(stats.get("spend_usd") or 0.0)
    accepted = int(stats.get("accepted_improvements") or 0)
    projected = spend + max(0.0, float(estimated_cost_usd or 0.0))

    # Bootstrap until both: windows >= N AND ≥1 accepted improvement
    in_bootstrap = windows < n_boot or accepted < 1
    if in_bootstrap:
        if projected > cap:
            return {
                "ok": False,
                "mode": "bootstrap_cap",
                "reason": f"bootstrap spend {projected:.2f} > cap {cap:.2f}",
                "stats": stats,
                "gov_slice": {
                    "bootstrap_burst_windows": n_boot,
                    "bootstrap_spend_cap_usd": cap,
                },
            }
        return {
            "ok": True,
            "mode": "bootstrap",
            "stats": stats,
            "gov_slice": {
                "bootstrap_burst_windows": n_boot,
                "bootstrap_spend_cap_usd": cap,
                "windows_remaining": max(0, n_boot - windows),
            },
            "projected_spend_usd": projected,
        }

    # Post-bootstrap CPAI
    if accepted < 1:
        return {
            "ok": False,
            "mode": "cpai_undefined",
            "reason": "post-bootstrap but zero accepted improvements",
            "stats": stats,
            "gov_slice": {"cpai_baseline_usd": cpai_baseline},
        }
    cpai = spend / accepted
    yellow = cpai_baseline * yellow_mult
    if cpai > yellow:
        return {
            "ok": False,
            "mode": "cpai_yellow",
            "reason": f"cpai {cpai:.2f} > yellow {yellow:.2f}",
            "stats": stats,
            "cpai": cpai,
            "gov_slice": {
                "cpai_baseline_usd": cpai_baseline,
                "cpai_yellow_multiplier": yellow_mult,
            },
        }
    return {
        "ok": True,
        "mode": "cpai",
        "stats": stats,
        "cpai": cpai,
        "gov_slice": {
            "cpai_baseline_usd": cpai_baseline,
            "cpai_yellow_multiplier": yellow_mult,
        },
        "projected_spend_usd": projected,
    }
