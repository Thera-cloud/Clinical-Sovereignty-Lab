"""S3 per-coach YouTube OAuth — coach-owned channel. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

logger = logging.getLogger("studio_youtube")

SCOPES = "https://www.googleapis.com/auth/youtube.upload"


async def oauth_status(db_pool, coach_id: str) -> Dict[str, Any]:
    connected = False
    if db_pool:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT 1 FROM studio_youtube_connection
                WHERE coach_id = $1 AND refresh_ciphertext IS NOT NULL
                """,
                coach_id,
            )
            connected = bool(row)
    cid = os.getenv("YOUTUBE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or ""
    return {
        "status": "ok",
        "connected": connected,
        "phase": "S3",
        "oauth_configured": bool(cid),
        "channel_owned_by": "coach",
    }


async def store_tokens(db_pool, coach_id: str, refresh_cipher: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO studio_youtube_connection (coach_id, refresh_ciphertext, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (coach_id) DO UPDATE SET
              refresh_ciphertext = EXCLUDED.refresh_ciphertext,
              updated_at = NOW()
            """,
            coach_id,
            refresh_cipher,
        )
    return {"ok": True, "connected": True}


async def upload_dry_run(db_pool, coach_id: str, episode_id: str) -> Dict[str, Any]:
    status = await oauth_status(db_pool, coach_id)
    if not status.get("connected"):
        return {"ok": False, "reason": "youtube_not_connected", "code": 409}
    return {
        "ok": True,
        "dry_run": True,
        "episode_id": episode_id,
        "destination": "coach_channel",
    }
