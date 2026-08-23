"""Nightly organic PRE6 drip — unused packs only, never replay.

Order: distill due living → seed unused catalog packs → shadow only_new.
Does not mint paid bakeoff, does not auto-promote, does not write Close Sentinel.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

logger = logging.getLogger("ln7_fuel_drip")

DEFAULT_LIMIT = 8


def drip_enabled() -> bool:
    raw = os.getenv("LN7_FUEL_DRIP", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def drip_limit() -> int:
    try:
        n = int(os.getenv("LN7_FUEL_DRIP_LIMIT", str(DEFAULT_LIMIT)) or DEFAULT_LIMIT)
    except ValueError:
        n = DEFAULT_LIMIT
    return max(1, min(n, 24))


async def _coding_trainable(db_pool) -> int:
    if not db_pool:
        return 0
    try:
        async with db_pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT COUNT(*)::int
                FROM outcome_envelope
                WHERE COALESCE(NULLIF(TRIM(domain_tag), ''), 'general') = 'coding'
                  AND COALESCE(shadow_outcome->>'oracle', '')
                      IN ('ci_pack', 'ci_pack_cycle')
                  AND (shadow_outcome->>'passed') IS NOT NULL
                """
            )
        return int(n or 0)
    except Exception as e:
        logger.warning("coding_trainable: %s", e)
        return 0


async def _log_activity(db_pool, content: str) -> None:
    if not db_pool:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO skyeye_activity (type, content, platform)
                VALUES ('ln7_fuel_drip', $1, 'ln7')
                """,
                content[:500],
            )
    except Exception as e:
        logger.debug("ln7_fuel_drip activity: %s", e)


async def _notify_inventory_empty(db_pool, trainable: int) -> None:
    try:
        from app.jobs.ln7_fuel_gauge import PRE6_TARGET, _already_sent, _mark_sent, _notify

        async with db_pool.acquire() as conn:
            if await _already_sent(conn, "coding", "inventory_empty"):
                return
            detail = (
                f"coding {trainable}/{PRE6_TARGET}. Unused CI packs + catalog "
                "are exhausted. Author more catalog specs or wait for Queens "
                "living distill. Replay stays CEO-only."
            )
            _notify(
                "[FUEL INVENTORY EMPTY] no unused packs to drip",
                detail,
                domain="coding",
            )
            await _mark_sent(conn, "coding", "inventory_empty", detail)
    except Exception as e:
        logger.warning("inventory_empty notify: %s", e)


async def run_fuel_organic_drip(db_pool) -> Dict[str, Any]:
    """Grow #15 with unused unique packs. Sentinel stays read-only."""
    if not db_pool:
        return {"ok": False, "error": "no_db"}
    if not drip_enabled():
        return {"ok": True, "skipped": "disabled"}

    from app.jobs.ln7_fuel_gauge import PRE6_TARGET
    from app.services.ln7_fuel_pack_catalog import ensure_catalog_packs
    from app.services.ln7_fuel_volume import (
        existing_ci_pack_names,
        filter_burst_packs,
        run_fuel_volume_burst,
    )
    from app.services.ln7_living_packs import distill_due_packs
    from app.services.ln_sandbox_engineering_ci import list_pack_names

    trainable = await _coding_trainable(db_pool)
    if trainable >= PRE6_TARGET:
        return {"ok": True, "skipped": "at_target", "trainable": trainable}

    distill = {"ok": False, "distilled": 0}
    try:
        distill = await distill_due_packs(db_pool)
    except Exception as e:
        logger.warning("drip distill: %s", e)
        distill = {"ok": False, "error": str(e)[:200]}

    catalog = ensure_catalog_packs()
    existing = await existing_ci_pack_names(db_pool)
    unused = filter_burst_packs(list_pack_names(), existing, only_new=True)
    if not unused:
        await _notify_inventory_empty(db_pool, trainable)
        out = {
            "ok": True,
            "skipped": "no_unused",
            "trainable": trainable,
            "distill": distill,
            "catalog": catalog,
            "unused": 0,
        }
        await _log_activity(db_pool, f"drip no_unused trainable={trainable}")
        return out

    burst = await run_fuel_volume_burst(
        db_pool,
        volume="drip",
        limit=drip_limit(),
        digest=False,
        only_new=True,
    )
    summary = (
        f"drip pass={burst.get('pass')} fail={burst.get('fail')} "
        f"packs={burst.get('packs')} unused_before={len(unused)} "
        f"trainable_was={trainable}"
    )
    logger.info("LN7 fuel drip | %s", summary)
    await _log_activity(db_pool, summary)
    return {
        "ok": True,
        "trainable_before": trainable,
        "unused_before": len(unused),
        "distill": distill,
        "catalog": catalog,
        "burst": {
            "pass": burst.get("pass"),
            "fail": burst.get("fail"),
            "skip": burst.get("skip"),
            "packs": burst.get("packs"),
            "gauge": burst.get("gauge"),
        },
    }
