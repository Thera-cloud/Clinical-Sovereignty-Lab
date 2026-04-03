"""SSE Stage 4 — Admin deployment operations.

Approve-and-deploy + rollback for SSE storyboards.
Complements the 5 endpoints already in backend/app/routers/admin.py.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


async def approve_and_deploy(
    storyboard_id: str, provenance_id: str, db_pool,
) -> dict[str, Any]:
    """Load related data and finalize deployment for an approved storyboard."""
    from app.sse.foundation import deployment

    async with db_pool.acquire() as conn:
        prov = await conn.fetchrow(
            "SELECT story_plot_json, delivery_config_json FROM sse_ip_provenance "
            "WHERE provenance_id = $1", provenance_id,
        )
        if not prov:
            return {"error": "provenance_id not found", "status": "failed"}

        story_plot = json.loads(prov["story_plot_json"]) if prov["story_plot_json"] else {}
        delivery_config = json.loads(prov["delivery_config_json"]) if prov["delivery_config_json"] else {}

        img_row = await conn.fetchrow(
            "SELECT results FROM sse_imagery_results WHERE storyboard_id = $1 "
            "ORDER BY created_at DESC LIMIT 1", storyboard_id,
        )
        imagery_results = json.loads(img_row["results"]) if img_row and img_row["results"] else {}

    result = await deployment.finalize_deployment(
        storyboard_id, provenance_id, story_plot, delivery_config, imagery_results, db_pool,
    )
    return result


async def rollback_deployment(
    storyboard_id: str, db_pool,
) -> dict[str, Any]:
    """Revert a deployed storyboard — disable config, schedules, and log it."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE sse_delivery_config SET status = 'rolled_back' "
            "WHERE storyboard_id = $1 AND status = 'active'", storyboard_id,
        )
        await conn.execute(
            "UPDATE sse_cron_schedules SET enabled = false "
            "WHERE storyboard_id = $1", storyboard_id,
        )
        log_id = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO sse_deployment_log "
            "(log_id, storyboard_id, action, status, notes) "
            "VALUES ($1, $2, 'rollback', 'rolled_back', 'Admin-initiated rollback')",
            log_id, storyboard_id,
        )
    logger.info("deployment: rolled back storyboard %s", storyboard_id)
    return {"storyboard_id": storyboard_id, "status": "rolled_back"}
