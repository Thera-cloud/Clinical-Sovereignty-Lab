"""Coach Command integrations hub. Setup from Coach Command, not SkyEye.

Workspace OAuth stays on /api/workspace/google (ENABLE_WS_OAUTH / O9).
LinkedIn tokens: coach_linkedin_connection only — never skyeye_platform_tokens.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

try:
    from app.services.api_server import get_current_user, require_coach, _get_auth_redis
except ImportError:
    from backend.app.services.api_server import get_current_user, require_coach, _get_auth_redis

logger = logging.getLogger("coach_integrations_api")

router = APIRouter(
    prefix="/api/coach/integrations",
    tags=["coach-integrations"],
    dependencies=[Depends(get_current_user)],
)
oauth_router = APIRouter(
    prefix="/api/coach/integrations",
    tags=["coach-integrations-oauth"],
)

LINKEDIN_POST_AUTH = os.getenv(
    "LINKEDIN_COACH_POST_AUTH_REDIRECT",
    "https://coach.sovereignsanctuary.net/?linkedin=connected",
)


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


def _hw(user: Dict) -> str:
    return (user.get("hardware_id") or "").strip()


def _require_flag(name: str) -> None:
    if not _flag_on(name):
        raise HTTPException(403, "temporarily unavailable")


@router.get("/hub")
async def integrations_hub(request: Request, user: Dict = Depends(require_coach)):
    from app.services.coach_integrations_hub import hub_snapshot

    pool = getattr(request.app.state, "db_pool", None)
    return await hub_snapshot(pool, _hw(user))


@router.get("/linkedin/status")
async def linkedin_status(request: Request, user: Dict = Depends(require_coach)):
    from app.services.coach_linkedin_oauth import coach_linkedin_status

    pool = getattr(request.app.state, "db_pool", None)
    return await coach_linkedin_status(pool, _hw(user))


@router.get("/linkedin/connect")
async def linkedin_connect(request: Request, user: Dict = Depends(require_coach)):
    _require_flag("ENABLE_COACH_LINKEDIN")
    from app.services.coach_linkedin_oauth import (
        build_coach_linkedin_oauth_url,
        coach_linkedin_credentials,
    )

    cid, secret, redirect = coach_linkedin_credentials()
    if not cid or not secret:
        raise HTTPException(503, "LinkedIn coach OAuth not configured")
    uid = (user.get("username") or "").strip()
    hw = _hw(user)
    state = secrets.token_urlsafe(32)
    r = await _get_auth_redis()
    if not r:
        raise HTTPException(503, "Redis unavailable — cannot issue OAuth state")
    await r.setex(
        f"coach_li_oauth_state:{state}",
        300,
        json.dumps({"user_id": uid, "hardware_id": hw, "role": "COACH"}),
    )
    return {
        "oauth_url": build_coach_linkedin_oauth_url(cid, redirect, state),
        "skyeye_fallback": False,
    }


@oauth_router.get("/linkedin/callback")
async def linkedin_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        raise HTTPException(400, f"LinkedIn OAuth error: {error}")
    _require_flag("ENABLE_COACH_LINKEDIN")
    if not code or not state:
        raise HTTPException(400, "Missing code or state")
    r = await _get_auth_redis()
    if not r:
        raise HTTPException(503, "Redis unavailable")
    raw = await r.get(f"coach_li_oauth_state:{state}")
    await r.delete(f"coach_li_oauth_state:{state}")
    if not raw:
        raise HTTPException(400, "Invalid or expired OAuth state")
    meta = json.loads(raw if isinstance(raw, str) else raw.decode())
    hw = meta.get("hardware_id") or ""
    err = LINKEDIN_POST_AUTH.replace("=connected", "=error")
    try:
        from app.services.coach_linkedin_oauth import (
            exchange_coach_linkedin_code,
            persist_coach_linkedin,
        )

        tokens = await exchange_coach_linkedin_code(code)
        if not tokens.get("access_token"):
            return RedirectResponse(err)
        pool = getattr(request.app.state, "db_pool", None)
        if pool:
            await persist_coach_linkedin(pool, hw, tokens)
    except Exception:
        logger.exception("Coach LinkedIn persist failed")
        return RedirectResponse(err)
    return RedirectResponse(LINKEDIN_POST_AUTH)


@router.get("/clients")
async def list_vault_clients(request: Request, user: Dict = Depends(require_coach)):
    from app.services.effective_scope import effective_scope

    pool = getattr(request.app.state, "db_pool", None)
    hw = _hw(user)
    scope = await effective_scope(pool, hw)
    ids = scope.get("client_hardware_ids") or []
    if not pool or not ids:
        return {"clients": []}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT hardware_id, username, COALESCE(vault_sync, false) AS vault_sync,
                   COALESCE(relationship_class, 'coaching') AS relationship_class,
                   profile_data->>'name' AS name
            FROM users
            WHERE role = 'CLIENT' AND hardware_id = ANY($1::text[])
            ORDER BY profile_data->>'name', username
            """,
            ids,
        )
    return {
        "clients": [
            {
                "hardware_id": r["hardware_id"],
                "username": r["username"],
                "name": r["name"],
                "vault_sync": bool(r["vault_sync"]),
                "relationship_class": r["relationship_class"],
            }
            for r in rows
        ]
    }


@router.post("/clients/{client_hw}/vault-sync")
async def set_vault_sync(client_hw: str, request: Request, user: Dict = Depends(require_coach)):
    from app.services.effective_scope import client_in_scope

    pool = getattr(request.app.state, "db_pool", None)
    hw = _hw(user)
    if not pool:
        raise HTTPException(503, "database unavailable")
    if not await client_in_scope(pool, hw, client_hw):
        raise HTTPException(403, "out of scope")
    body = await request.json()
    enabled = bool(body.get("vault_sync"))
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE users SET vault_sync = $1
            WHERE hardware_id = $2 AND role = 'CLIENT'
            """,
            enabled,
            client_hw,
        )
    return {"ok": True, "hardware_id": client_hw, "vault_sync": enabled}


@router.post("/studio/rotate-secret")
async def rotate_studio_secret(request: Request, user: Dict = Depends(require_coach)):
    from app.services.skyeye_platform_base import TokenCipher

    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "database unavailable")
    hw = _hw(user)
    plaintext = secrets.token_urlsafe(32)
    fingerprint = hashlib.sha256(plaintext.encode()).hexdigest()[:12]
    cipher = TokenCipher.get().encrypt(plaintext)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO studio_webhook_secrets (coach_id, secret_ciphertext, fingerprint, revoked_at)
            VALUES ($1, $2, $3, NULL)
            ON CONFLICT (coach_id) DO UPDATE SET
              secret_ciphertext = EXCLUDED.secret_ciphertext,
              fingerprint = EXCLUDED.fingerprint,
              revoked_at = NULL,
              created_at = NOW()
            """,
            hw,
            cipher,
            fingerprint,
        )
    return {
        "ok": True,
        "secret": plaintext,
        "fingerprint": fingerprint,
        "show_once": True,
        "recovery": False,
    }


@router.put("/chat-webhook")
async def set_chat_webhook(request: Request, user: Dict = Depends(require_coach)):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "database unavailable")
    body = await request.json()
    url = str(body.get("url") or "").strip()
    hw = _hw(user)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO coach_integrations_settings (coach_id, chat_webhook_url, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (coach_id) DO UPDATE SET
              chat_webhook_url = EXCLUDED.chat_webhook_url,
              updated_at = NOW()
            """,
            hw,
            url or None,
        )
    return {"ok": True, "chat_webhook_url": url}


@router.get("/drafts")
async def waiting_drafts(request: Request, user: Dict = Depends(require_coach)):
    from app.services.gmail_draft_service import list_waiting_drafts

    pool = getattr(request.app.state, "db_pool", None)
    return {"drafts": await list_waiting_drafts(pool, _hw(user))}


@router.post("/linkedin/disconnect")
async def linkedin_disconnect(request: Request, user: Dict = Depends(require_coach)):
    from app.services.coach_linkedin_oauth import revoke_coach_linkedin

    pool = getattr(request.app.state, "db_pool", None)
    return await revoke_coach_linkedin(pool, _hw(user))


@router.get("/campaigns")
async def list_campaigns(request: Request, user: Dict = Depends(require_coach)):
    from app.services.voice_campaign_generator import (
        list_approved_unpublished,
        list_review_queue,
    )

    pool = getattr(request.app.state, "db_pool", None)
    hw = _hw(user)
    queue = await list_review_queue(pool, hw) if pool else []
    approved = await list_approved_unpublished(pool, hw) if pool else []
    return {"review_queue": queue, "approved_unpublished": approved}


@router.post("/campaigns/generate")
async def generate_voice_campaign(request: Request, user: Dict = Depends(require_coach)):
    from app.services.google_workspace_service import FlagOff
    from app.services.voice_campaign_generator import generate_campaign

    _require_flag("ENABLE_VOICE_CAMPAIGN")
    body = await request.json()
    pool = getattr(request.app.state, "db_pool", None)
    try:
        return await generate_campaign(
            pool,
            _hw(user),
            title=str(body.get("title") or "Campaign"),
            day_n=int(body.get("day_n") or 0),
        )
    except FlagOff:
        raise HTTPException(403, "temporarily unavailable")


@router.post("/campaigns/{content_id}/review")
async def review_campaign_item(
    content_id: int, request: Request, user: Dict = Depends(require_coach)
):
    from app.services.voice_campaign_generator import set_review_status

    body = await request.json()
    pool = getattr(request.app.state, "db_pool", None)
    try:
        return await set_review_status(
            pool, content_id, coach_id=_hw(user), status=str(body.get("status") or "")
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/tasks")
async def create_client_task(request: Request, user: Dict = Depends(require_coach)):
    from app.services.coach_task_service import create_task
    from app.services.google_workspace_service import FlagOff

    _require_flag("ENABLE_COACH_TASKS")
    body = await request.json()
    pool = getattr(request.app.state, "db_pool", None)
    try:
        return await create_task(
            pool,
            _hw(user),
            client_id=str(body.get("client_id") or ""),
            title=str(body.get("title") or ""),
        )
    except FlagOff:
        raise HTTPException(403, "temporarily unavailable")
    except PermissionError:
        raise HTTPException(403, "out of scope")


@router.post("/campaigns/{content_id}/publish")
async def publish_linkedin_item(
    content_id: int, request: Request, user: Dict = Depends(require_coach)
):
    from app.services.coach_linkedin_publisher import publish_approved_post
    from app.services.google_workspace_service import FlagOff

    _require_flag("ENABLE_COACH_LINKEDIN")
    pool = getattr(request.app.state, "db_pool", None)
    try:
        return await publish_approved_post(pool, coach_id=_hw(user), content_id=content_id)
    except FlagOff:
        raise HTTPException(403, "temporarily unavailable")


@router.post("/voice/recordings")
async def ingest_voice(request: Request, user: Dict = Depends(require_coach)):
    from app.services.google_workspace_service import FlagOff, VaultBlocked
    from app.services.voice_campaign_ingest import store_voice_recording

    _require_flag("ENABLE_VOICE_CAMPAIGN")
    body = await request.json()
    client_id = str(body.get("client_id") or "").strip()
    b64 = str(body.get("audio_b64") or "")
    transcript = str(body.get("transcript") or "")
    try:
        audio = base64.b64decode(b64) if b64 else b""
    except Exception:
        raise HTTPException(400, "invalid audio_b64")
    pool = getattr(request.app.state, "db_pool", None)
    try:
        return await store_voice_recording(
            pool, _hw(user), client_id, audio, transcript=transcript
        )
    except FlagOff:
        raise HTTPException(403, "temporarily unavailable")
    except VaultBlocked as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/morning-brief")
async def morning_brief(request: Request, user: Dict = Depends(require_coach)):
    from app.services.coach_task_service import list_open_tasks
    from app.services.morning_brief_composer import compose_script

    pool = getattr(request.app.state, "db_pool", None)
    hw = _hw(user)
    tasks = []
    day_n = None
    if pool:
        try:
            tasks = await list_open_tasks(pool, hw)
        except Exception:
            tasks = []
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT day_n FROM coach_marketing_campaigns
                WHERE coach_id = $1
                ORDER BY updated_at DESC NULLS LAST, id DESC LIMIT 1
                """,
                hw,
            )
            if row:
                day_n = row["day_n"]
    name = (user.get("name") or user.get("username") or "Coach").strip()
    script = compose_script(coach_name=name, tasks=tasks, campaign_day_n=day_n)
    return {
        "script": script,
        "audio_enabled": _flag_on("ENABLE_AUDIO_BRIEFS"),
        "campaign_day_n": day_n,
    }
