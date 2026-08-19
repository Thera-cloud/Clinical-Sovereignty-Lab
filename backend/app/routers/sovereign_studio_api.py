"""Sovereign Studio coach + public surfaces. Distinct from SSE /api/sse/admin/studio."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

try:
    from app.services.api_server import get_current_user, require_admin, require_coach
except ImportError:
    from backend.app.services.api_server import get_current_user, require_admin, require_coach

from app.services.studio_invariants import (
    LN_COHOST_LABEL,
    SCREENER_TOKEN_TTL_S,
    STYLE_KEYS,
    VERTICALS,
    clone_context_allowed,
    studio_flag_on,
)

logger = logging.getLogger("sovereign_studio_api")

router = APIRouter(
    prefix="/api/studio",
    tags=["sovereign-studio"],
    dependencies=[Depends(get_current_user)],
)
public_router = APIRouter(prefix="/api/studio", tags=["sovereign-studio-public"])


class ShowCreate(BaseModel):
    name: str
    vertical: str
    description: str = ""
    host_number: str = ""


class StyleBody(BaseModel):
    style: Dict[str, Any]


class HostNumberBody(BaseModel):
    host_number: str


class SessionCreate(BaseModel):
    show_id: str


class CutsBody(BaseModel):
    cuts: Optional[list] = None


class FlagResolveBody(BaseModel):
    reason: str = ""


def _hw(user: Dict) -> str:
    return (user.get("hardware_id") or "").strip()


def _pool(request: Request):
    return getattr(request.app.state, "db_pool", None)


def _flag() -> None:
    if not studio_flag_on():
        raise HTTPException(403, "temporarily unavailable")


def _raise(out: Dict[str, Any]) -> Dict[str, Any]:
    if out.get("ok"):
        return out
    raise HTTPException(int(out.get("code") or 400), out.get("reason") or "error")


@public_router.get("/health")
async def studio_health():
    return {
        "status": "ok",
        "flag": studio_flag_on(),
        "label": LN_COHOST_LABEL,
        "verticals": list(VERTICALS),
        "style_keys": sorted(STYLE_KEYS),
        "screener_ttl_s": SCREENER_TOKEN_TTL_S,
        "clone_ln_broadcast": clone_context_allowed("ln_broadcast"),
    }


@public_router.get("/invariants")
async def studio_invariants_public():
    from app.services.studio_invariants import INV6_BLOCKED, WALL_TABLES

    return {
        "status": "ok",
        "inv6_regex": INV6_BLOCKED.pattern,
        "style_whitelist": sorted(STYLE_KEYS),
        "wall_tables": list(WALL_TABLES),
        "label": LN_COHOST_LABEL,
    }


@router.post("/shows")
async def create_show(body: ShowCreate, request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_show_service import create_show as _create

    return _raise(await _create(
        _pool(request),
        _hw(user),
        name=body.name,
        vertical=body.vertical,
        description=body.description,
        host_number=body.host_number,
    ))


@router.get("/shows")
async def list_shows(request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_show_service import list_shows as _list

    return await _list(_pool(request), _hw(user))


@router.get("/shows/{show_id}")
async def get_show(show_id: UUID, request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_show_service import get_show as _get

    return _raise(await _get(_pool(request), str(show_id), _hw(user)))


@router.put("/shows/{show_id}/persona/style")
async def put_style(
    show_id: UUID, body: StyleBody, request: Request, user: Dict = Depends(require_coach)
):
    _flag()
    from app.services.studio_show_service import update_style

    return _raise(await update_style(_pool(request), str(show_id), _hw(user), body.style))


@router.post("/shows/{show_id}/verify-host-number")
async def verify_host(
    show_id: UUID, body: HostNumberBody, request: Request, user: Dict = Depends(require_coach)
):
    _flag()
    from app.services.studio_show_service import store_host_number

    return _raise(await store_host_number(_pool(request), str(show_id), _hw(user), body.host_number))


@router.post("/shows/{show_id}/provision-did")
async def provision_did(show_id: UUID, request: Request, user: Dict = Depends(require_admin)):
    _flag()
    return {
        "ok": False,
        "reason": "S2 DID provision not enabled",
        "show_id": str(show_id),
        "admin": (user.get("username") or ""),
    }


@router.post("/sessions")
async def create_session(body: SessionCreate, request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_session_service import create_session as _create

    return _raise(await _create(_pool(request), body.show_id, _hw(user)))


@router.post("/sessions/{session_id}/end")
async def end_session(session_id: UUID, request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_session_service import end_session as _end

    return _raise(await _end(_pool(request), str(session_id), _hw(user)))


@router.post("/sessions/{session_id}/dump")
async def dump_session(session_id: UUID, user: Dict = Depends(require_coach)):
    _flag()
    raise HTTPException(409, "tier2_locked")


@router.get("/episodes/{episode_id}")
async def get_episode(episode_id: UUID, request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_episode_service import get_episode as _get

    return _raise(await _get(_pool(request), str(episode_id), _hw(user)))


@router.post("/episodes/{episode_id}/cuts")
async def episode_cuts(
    episode_id: UUID, body: CutsBody, request: Request, user: Dict = Depends(require_coach)
):
    _flag()
    from app.services.studio_episode_service import add_cuts

    return _raise(await add_cuts(_pool(request), str(episode_id), _hw(user), body.cuts or []))


@router.post("/episodes/{episode_id}/approve")
async def episode_approve(episode_id: UUID, request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_episode_service import approve_episode

    return _raise(await approve_episode(_pool(request), str(episode_id), _hw(user)))


@router.post("/episodes/{episode_id}/publish")
async def episode_publish(episode_id: UUID, request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_episode_service import publish_episode

    return _raise(await publish_episode(_pool(request), str(episode_id), _hw(user)))


@router.post("/episodes/{episode_id}/reject")
async def episode_reject(episode_id: UUID, request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_episode_service import reject_episode

    return _raise(await reject_episode(_pool(request), str(episode_id), _hw(user)))


@router.post("/episodes/{episode_id}/flags/{flag_id}/resolve")
async def episode_flag_resolve(
    episode_id: UUID,
    flag_id: UUID,
    body: FlagResolveBody,
    request: Request,
    user: Dict = Depends(require_coach),
):
    _flag()
    from app.services.studio_episode_service import resolve_flag

    role = (user.get("role") or "").upper()
    return _raise(
        await resolve_flag(
            _pool(request),
            str(episode_id),
            str(flag_id),
            _hw(user),
            username=(user.get("username") or ""),
            is_admin=role == "ADMIN",
            reason=body.reason,
        )
    )


@public_router.get("/feeds/{show_id}/rss")
async def show_rss(show_id: UUID, request: Request):
    from app.services.studio_episode_service import rss_xml

    pool = _pool(request)
    show = {"name": "Sovereign Studio", "description": f"Show with {LN_COHOST_LABEL}"}
    items = []
    if pool:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, name, description FROM studio_shows WHERE id = $1::uuid",
                str(show_id),
            )
            if row:
                show = {"name": row["name"], "description": row["description"] or show["description"]}
                recs = await conn.fetch(
                    """
                    SELECT id, title, rss_guid FROM studio_episodes
                    WHERE show_id = $1::uuid AND state = 'published'
                    ORDER BY published_at DESC NULLS LAST LIMIT 50
                    """,
                    str(show_id),
                )
                items = [
                    {"id": str(r["id"]), "title": r["title"], "rss_guid": r["rss_guid"]}
                    for r in recs
                ]
    xml = rss_xml(show, items)
    return Response(content=xml, media_type="application/rss+xml")


@public_router.post("/voice/inbound")
async def voice_inbound():
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Say>This line starts the screening. Please stay on the line.</Say>"
        "<Redirect>/api/studio/voice/screener</Redirect></Response>"
    )
    return Response(content=twiml, media_type="application/xml")


@public_router.post("/voice/screener")
@public_router.get("/voice/screener-health")
async def screener_health():
    return {
        "status": "ok",
        "consent_write": "dry-run",
        "always_screener": True,
        "ttl_s": SCREENER_TOKEN_TTL_S,
    }


@public_router.get("/voice/screener-ttl")
async def screener_ttl():
    return {"status": "ok", "ttl_s": SCREENER_TOKEN_TTL_S}


@public_router.get("/voice/sip-health")
async def sip_health():
    return {"status": "ok", "sip": "s2", "allow_video": False}


@public_router.post("/voice/sip-join")
async def sip_join(request: Request):
    token = (request.headers.get("X-Studio-Screener-Token") or "").strip()
    if not token:
        raise HTTPException(403, "screener token required")
    r = None
    try:
        from app.services.api_server import _get_auth_redis

        r = await _get_auth_redis()
    except Exception:
        r = None
    if r:
        raw = await r.get(f"studio_screener:{token}")
        if not raw:
            raise HTTPException(403, "screener token expired")
    else:
        raise HTTPException(403, "screener token required")
    return {"ok": True}


@public_router.get("/youtube/oauth-status")
async def youtube_oauth_status():
    return {"status": "ok", "connected": False, "phase": "S3"}
