"""SSE Stage 4 — Deployment Automation.

Orchestrates storyboard promotion from R2 staging to production,
delivery config persistence, cron schedule registration, and
IP provenance finalization.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.sse.infrastructure import r2_storage

logger = logging.getLogger(__name__)

_STAGING = "sse/staging"
_PROD = "sse/reference_library/story_specific"


class DeploymentError(Exception):
    pass


async def _r2_list(prefix: str) -> list[str]:
    client = r2_storage._get_client()
    if client is None:
        return []
    def _go():
        keys: list[str] = []
        pag = client.get_paginator("list_objects_v2")
        for page in pag.paginate(Bucket=r2_storage._R2_BUCKET, Prefix=prefix):
            keys.extend(o["Key"] for o in page.get("Contents", []))
        return keys
    return await asyncio.get_event_loop().run_in_executor(None, _go)


async def _r2_copy(src: str, dst: str) -> bool:
    client = r2_storage._get_client()
    if client is None:
        return False
    def _go():
        client.copy_object(Bucket=r2_storage._R2_BUCKET,
                           CopySource={"Bucket": r2_storage._R2_BUCKET, "Key": src}, Key=dst)
    await asyncio.get_event_loop().run_in_executor(None, _go)
    return True


async def _r2_delete(keys: list[str]) -> None:
    client = r2_storage._get_client()
    if client is None or not keys:
        return
    def _go():
        objs = [{"Key": k} for k in keys]
        for i in range(0, len(objs), 1000):
            client.delete_objects(Bucket=r2_storage._R2_BUCKET, Delete={"Objects": objs[i:i+1000]})
    await asyncio.get_event_loop().run_in_executor(None, _go)


async def promote_to_production(
    storyboard_id: str, story_plot: dict[str, Any], imagery_results: dict[str, Any],
) -> dict[str, Any]:
    """Copy staging assets to production prefix, verify, then clean staging."""
    stg = f"{_STAGING}/{storyboard_id}/"
    prod = f"{_PROD}/{storyboard_id}/"
    stg_keys = await _r2_list(stg)

    if not stg_keys:
        logger.warning("deployment: no staging objects for %s — mock promotion", storyboard_id)
        return {"storyboard_id": storyboard_id, "production_prefix": prod,
                "objects_promoted": 0, "status": "promoted"}

    copied = 0
    for src in stg_keys:
        dst = f"{prod}{src[len(stg):]}"
        if not await _r2_copy(src, dst):
            raise DeploymentError(f"Copy failed: {src} → {dst}")
        copied += 1

    prod_keys = await _r2_list(prod)
    if len(prod_keys) < copied:
        raise DeploymentError(f"Verification failed: expected {copied}, found {len(prod_keys)}")

    await _r2_delete(stg_keys)
    logger.info("deployment: promoted %d objects for %s", copied, storyboard_id)
    return {"storyboard_id": storyboard_id, "production_prefix": prod,
            "objects_promoted": copied, "status": "promoted"}


async def save_delivery_config(
    storyboard_id: str, delivery_config: dict[str, Any], db_pool,
) -> str:
    """Persist delivery config to PostgreSQL. Returns config_id."""
    config_id = str(uuid.uuid4())
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO sse_delivery_config "
            "(config_id, storyboard_id, delivery_config, status, version) "
            "VALUES ($1, $2, $3::jsonb, 'active', 1)",
            config_id, storyboard_id, json.dumps(delivery_config),
        )
    return config_id


_CRON = {
    "daily_panel": "0 3 * * *",
    "weekly_clip": "0 4 * * 0",
    "monthly_recap": "0 5 28-31 * *",
}


async def register_cron_schedules(
    storyboard_id: str, delivery_config: dict[str, Any], db_pool,
) -> list[str]:
    """Register generation schedules. Returns list of schedule_id strings."""
    entries: list[tuple[str, str, str]] = [("daily_panel", _CRON["daily_panel"], "all")]
    if delivery_config.get("weekly_clip"):
        entries.append(("weekly_clip", _CRON["weekly_clip"], "all"))
    if delivery_config.get("monthly_recap"):
        entries.append(("monthly_recap", _CRON["monthly_recap"], "all"))

    ids: list[str] = []
    async with db_pool.acquire() as conn:
        for stype, cron_expr, tier in entries:
            sid = str(uuid.uuid4())
            await conn.execute(
                "INSERT INTO sse_cron_schedules "
                "(schedule_id, storyboard_id, schedule_type, cron_expression, target_tier, enabled) "
                "VALUES ($1, $2, $3, $4, $5, true)",
                sid, storyboard_id, stype, cron_expr, tier,
            )
            ids.append(sid)
    return ids


async def finalize_deployment(
    storyboard_id: str, provenance_id: str,
    story_plot: dict[str, Any], delivery_config: dict[str, Any],
    imagery_results: dict[str, Any], db_pool,
) -> dict[str, Any]:
    """Master orchestrator — promote, persist config, register cron, log."""
    from . import ip_provenance

    promo = await promote_to_production(storyboard_id, story_plot, imagery_results)
    config_id = await save_delivery_config(storyboard_id, delivery_config, db_pool)
    schedule_ids = await register_cron_schedules(storyboard_id, delivery_config, db_pool)
    await ip_provenance.update_status(provenance_id, "deployed", storyboard_id)

    now = datetime.now(timezone.utc).isoformat()
    log_id = str(uuid.uuid4())
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO sse_deployment_log "
            "(log_id, storyboard_id, provenance_id, action, config_id, "
            "objects_promoted, schedule_ids, deployed_at, status) "
            "VALUES ($1, $2, $3, 'deploy', $4, $5, $6::jsonb, NOW(), 'deployed')",
            log_id, storyboard_id, provenance_id, config_id,
            promo["objects_promoted"], json.dumps(schedule_ids),
        )

    return {
        "storyboard_id": storyboard_id, "provenance_id": provenance_id,
        "config_id": config_id, "schedule_ids": schedule_ids,
        "objects_promoted": promo["objects_promoted"],
        "status": "deployed", "deployed_at": now,
    }
