"""Studio HMAC hooks. Engagement is idempotent. ENABLE_STUDIO_WEBHOOKS."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

from app.services.studio_hmac import verify_hmac

logger = logging.getLogger("studio_hooks_api")

router = APIRouter(prefix="/api/v1/hooks", tags=["studio-hooks"])

HOOKS = frozenset({"intake-analysis", "engagement", "client-digest"})


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


async def load_coach_hmac_secret(db_pool, coach_id: str) -> Optional[bytes]:
    if not db_pool:
        return None
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT secret_ciphertext FROM studio_webhook_secrets
            WHERE coach_id = $1 AND revoked_at IS NULL
            """,
            coach_id,
        )
    if not row:
        return None
    from app.services.skyeye_platform_base import TokenCipher
    raw = TokenCipher.get().decrypt(row["secret_ciphertext"])
    return raw.encode() if isinstance(raw, str) else raw


@router.post("/{hook}")
async def studio_hook(hook: str, request: Request):
    if not _flag_on("ENABLE_STUDIO_WEBHOOKS"):
        raise HTTPException(503, "temporarily unavailable")
    if hook not in HOOKS:
        raise HTTPException(404, "unknown hook")
    body = await request.body()
    coach_id = (request.headers.get("X-Coach-Id") or "").strip()
    sig = request.headers.get("X-Studio-Signature") or request.headers.get("X-Hub-Signature-256") or ""
    pool = getattr(request.app.state, "db_pool", None)
    secret = await load_coach_hmac_secret(pool, coach_id)
    if not secret or not verify_hmac(secret, body, sig):
        raise HTTPException(401, "invalid hmac")
    try:
        payload = json.loads(body.decode() or "{}")
    except Exception:
        payload = {}
    event_id = str(payload.get("event_id") or payload.get("id") or "")
    if hook == "engagement" and event_id and pool:
        async with pool.acquire() as conn:
            existing = await conn.fetchrow(
                """
                SELECT 1 FROM studio_hook_events
                WHERE coach_id = $1 AND event_id = $2
                """,
                coach_id,
                event_id,
            )
            if existing:
                return {"ok": True, "duplicate": True, "hook": hook}
            await conn.execute(
                """
                INSERT INTO studio_hook_events (coach_id, event_id, hook)
                VALUES ($1, $2, $3)
                """,
                coach_id,
                event_id,
                hook,
            )
            await conn.execute(
                """
                INSERT INTO campaign_engagements (coach_id, campaign_id, source, actor_handle)
                VALUES ($1, $2, 'studio_hook', $3)
                """,
                coach_id,
                payload.get("campaign_id"),
                event_id[:200],
            )
    if hook == "client-digest" and pool:
        cid = str(payload.get("client_id") or "").strip()
        if cid:
            from app.services.effective_scope import client_in_scope

            if not await client_in_scope(pool, coach_id, cid):
                raise HTTPException(403, "out of scope")
    return {"ok": True, "duplicate": False, "hook": hook}
