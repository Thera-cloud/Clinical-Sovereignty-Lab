"""
SSE Stage 1 — IP Provenance Tracker

Records source document provenance for every SSE pipeline run.
Deduplicates by source_hash — if a document with the same hash has already
completed processing, returns the existing provenance_id.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)


async def _get_pool():
    """Lazy import to avoid circular dependency at module load."""
    try:
        from app.services.api_server import app
        pool = getattr(app.state, "db_pool", None)
        if pool:
            return pool
    except Exception:
        pass
    return None


async def create_record(
    filename: str,
    uploader_id: str,
    source_hash: str,
) -> str:
    pool = await _get_pool()
    if pool is None:
        provenance_id = str(uuid.uuid4())
        logger.warning("ip_provenance: no db_pool — returning ephemeral id %s", provenance_id)
        return provenance_id

    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT provenance_id FROM sse_ip_provenance "
            "WHERE source_hash = $1 AND status = 'complete'",
            source_hash,
        )
        if existing:
            logger.info("ip_provenance: duplicate source_hash, reusing %s", existing)
            return str(existing)

        provenance_id = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO sse_ip_provenance (provenance_id, filename, uploader_id, source_hash, status) "
            "VALUES ($1, $2, $3, $4, 'processing')",
            provenance_id, filename, uploader_id, source_hash,
        )
    return provenance_id


async def update_status(
    provenance_id: str,
    status: str,
    story_plot_id: Optional[str] = None,
) -> None:
    pool = await _get_pool()
    if pool is None:
        logger.warning("ip_provenance: no db_pool — skipping status update for %s", provenance_id)
        return

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sse_ip_provenance SET status = $1, story_plot_id = COALESCE($2, story_plot_id) "
            "WHERE provenance_id = $3",
            status, story_plot_id, provenance_id,
        )
