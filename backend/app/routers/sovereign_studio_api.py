"""Sovereign Studio coach + public surfaces. Distinct from SSE /api/sse/admin/studio."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
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


class AttachDidBody(BaseModel):
    did_e164: str


class SessionCreate(BaseModel):
    show_id: str


class CutsBody(BaseModel):
    cuts: Optional[list] = None


class FlagResolveBody(BaseModel):
    reason: str = ""


class RegenBody(BaseModel):
    segment_id: str = "ln"
    coach_note: str = ""


class RtmpBody(BaseModel):
    rtmp_url: str = ""


class YoutubeGoLiveBody(BaseModel):
    title: str = ""
    privacy: str = "unlisted"
    session_id: str = ""


class QueueBody(BaseModel):
    op: str
    caller_id: str = ""


class ConsentRecordBody(BaseModel):
    show_id: str = ""
    granted: bool = False
    consent_kind: str = "sms_opt_in"


class ScanBody(BaseModel):
    text: str = ""


class UtteranceBody(BaseModel):
    text: str = ""


class CohostTurnBody(BaseModel):
    text: str = ""
    speaker: str = "host"
    toss: bool = False
    callers: int = 0
    waiting: int = 0
    event: str = "line"
    realm: str = ""
    realm_blurb: str = ""
    realm_shift: bool = False
    share_kind: str = ""
    share_note: str = ""


class CohostSpeakBody(BaseModel):
    text: str = ""


class CohostShareBody(BaseModel):
    kind: str = "search"
    query: str = ""
    url: str = ""


class CohostSoundBody(BaseModel):
    sound_id: str = ""


def _hw(user: Dict) -> str:
    return (user.get("hardware_id") or "").strip()


def _pool(request: Request):
    return getattr(request.app.state, "db_pool", None)


async def _redis(request: Request):
    try:
        from app.services.api_server import _get_auth_redis

        return await _get_auth_redis()
    except Exception:
        return None


def _flag() -> None:
    if not studio_flag_on():
        raise HTTPException(403, "temporarily unavailable")


def _livekit_session(request: Request, session_id: UUID) -> Dict[str, Any]:
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    from app.services.studio_livekit import verify_livekit_jwt

    checked = verify_livekit_jwt(token)
    if not checked.get("ok"):
        raise HTTPException(401, checked.get("reason") or "livekit_jwt")
    if checked.get("session_id") != str(session_id):
        raise HTTPException(403, "room_mismatch")
    return checked


def _require_host_jwt(request: Request, session_id: UUID) -> Dict[str, Any]:
    checked = _livekit_session(request, session_id)
    from app.services.studio_cohost_share import is_studio_host_identity

    if not is_studio_host_identity(str(checked.get("identity") or "")):
        raise HTTPException(403, "host_only")
    return checked


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
    from app.services.studio_did_service import provision_did as _prov

    return _raise(await _prov(_pool(request), str(show_id), user.get("username") or ""))


@router.post("/shows/{show_id}/attach-did")
async def attach_did(
    show_id: UUID, body: AttachDidBody, request: Request, user: Dict = Depends(require_admin)
):
    _flag()
    from app.services.studio_did_service import attach_existing_did

    return _raise(
        await attach_existing_did(
            _pool(request), str(show_id), body.did_e164, user.get("username") or ""
        )
    )


@router.get("/shows/{show_id}/caller-memory")
async def caller_memory(show_id: UUID, request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_screener_service import caller_memory_counts

    return _raise(await caller_memory_counts(_pool(request), str(show_id), _hw(user)))


@router.get("/shows/{show_id}/episodes")
async def list_show_episodes(
    show_id: UUID, request: Request, user: Dict = Depends(require_coach)
):
    _flag()
    from app.services.studio_episode_service import list_episodes

    return _raise(await list_episodes(_pool(request), str(show_id), _hw(user)))


@router.post("/shows/{show_id}/rtmp-key")
async def set_rtmp(show_id: UUID, body: RtmpBody, request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_tier2 import store_rtmp

    return _raise(await store_rtmp(_pool(request), str(show_id), _hw(user), body.rtmp_url))


@router.get("/shows/{show_id}/delay")
async def show_delay(show_id: UUID, request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_show_service import get_show as _get
    from app.services.studio_tier2 import delay_status

    out = await _get(_pool(request), str(show_id), _hw(user))
    if not out.get("ok"):
        return _raise(out)
    return delay_status(bool((out.get("show") or {}).get("live_unlocked")))


@router.post("/sessions")
async def create_session(body: SessionCreate, request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_session_service import create_session as _create

    return _raise(await _create(_pool(request), body.show_id, _hw(user)))


@router.post("/sessions/{session_id}/end")
async def end_session(session_id: UUID, request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_episode_service import create_from_session
    from app.services.studio_session_service import end_session as _end

    ended = await _end(_pool(request), str(session_id), _hw(user))
    if not ended.get("ok"):
        return _raise(ended)
    ep = await create_from_session(_pool(request), str(session_id), _hw(user))
    ended["episode"] = ep
    return ended


@router.post("/sessions/{session_id}/dump")
async def dump_session(session_id: UUID, request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_tier2 import dump_session as _dump

    # 409 tier2_locked when clean published episodes < LIVE_TIER_CLEAN_EPISODES
    return _raise(await _dump(_pool(request), str(session_id), _hw(user)))


@router.get("/sessions/{session_id}/callers")
async def session_callers(
    session_id: UUID, request: Request, user: Dict = Depends(require_coach)
):
    _flag()
    from app.services.studio_caller_queue import list_session_callers

    return _raise(
        await list_session_callers(_pool(request), str(session_id), _hw(user))
    )


@router.get("/sessions/{session_id}/queue")
async def session_queue_get(
    session_id: UUID, request: Request, user: Dict = Depends(require_coach)
):
    _flag()
    from app.services.studio_caller_queue import get_board

    return _raise(
        await get_board(_pool(request), await _redis(request), str(session_id), _hw(user))
    )


@router.post("/sessions/{session_id}/queue")
async def session_queue_op(
    session_id: UUID,
    body: QueueBody,
    request: Request,
    user: Dict = Depends(require_coach),
):
    _flag()
    from app.services.studio_caller_queue import apply_queue_op

    return _raise(
        await apply_queue_op(
            _pool(request),
            await _redis(request),
            str(session_id),
            _hw(user),
            body.op,
            body.caller_id,
        )
    )


@router.post("/sessions/{session_id}/join-token")
async def join_token(session_id: UUID, request: Request, user: Dict = Depends(require_coach)):
    _flag()
    role = "host"
    try:
        body = await request.json()
        if isinstance(body, dict):
            role = str(body.get("role") or "host")
    except Exception:
        pass
    from app.services.studio_livekit import join_token as _join

    return _join(str(session_id), role, identity=_hw(user))


@router.post("/sessions/{session_id}/egress")
async def start_egress(session_id: UUID, request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_livekit import start_room_egress

    rtmp = ""
    unlocked = False
    pool = _pool(request)
    if pool:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT sh.rtmp_url,
                  (SELECT COUNT(*) FROM studio_episodes e
                    WHERE e.show_id = sh.id AND e.state = 'published'
                      AND NOT EXISTS (
                        SELECT 1 FROM studio_compliance_flags f
                        WHERE f.episode_id = e.id AND f.status = 'open'
                      )
                  ) AS clean_published
                FROM studio_sessions s
                JOIN studio_shows sh ON sh.id = s.show_id
                WHERE s.id = $1::uuid AND sh.coach_id = $2
                """,
                str(session_id),
                _hw(user),
            )
        if not row:
            raise HTTPException(404, "not_found")
        rtmp = row["rtmp_url"] or ""
        from app.services.studio_invariants import live_tier_unlocked

        unlocked = live_tier_unlocked(int(row["clean_published"] or 0))
    plan = await start_room_egress(str(session_id), rtmp_url=rtmp, live_unlocked=unlocked)
    if plan.get("started") and plan.get("egress_id") and plan.get("media_r2_key"):
        from app.services.studio_media_tape import stamp_session_tape

        await stamp_session_tape(
            pool,
            str(session_id),
            media_r2_key=str(plan.get("media_r2_key") or ""),
            egress_id=str(plan.get("egress_id") or ""),
            ready=False,
        )
    return plan


@router.post("/sessions/{session_id}/share-asset")
async def share_asset_coach(
    session_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    user: Dict = Depends(require_coach),
):
    """Coach JWT ingest from the STUDIO ON AIR picker. QUANTUM-CRYSTAL-ARCH"""
    _flag()
    pool = _pool(request)
    if not pool:
        raise HTTPException(503, "no_db")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT s.id FROM studio_sessions s
            JOIN studio_shows sh ON sh.id = s.show_id
            WHERE s.id = $1::uuid AND sh.coach_id = $2
            """,
            str(session_id),
            _hw(user),
        )
    if not row:
        raise HTTPException(404, "not_found")
    raw = await file.read()
    from app.services.studio_cohost_share import ingest_share_asset

    return _raise(
        await ingest_share_asset(
            str(session_id),
            raw,
            filename=file.filename or "file",
            content_type=file.content_type or "",
        )
    )


@router.get("/shows/{show_id}/meter")
async def show_meter(show_id: UUID, request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_meter import show_meter as _meter

    return _raise(await _meter(_pool(request), str(show_id), _hw(user)))


@router.post("/sessions/{session_id}/legs")
async def add_leg(session_id: UUID, request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_livekit import reject_guest_video

    body = await request.json()
    check = reject_guest_video(str(body.get("role") or ""), body.get("video_track_key"))
    if not check.get("ok"):
        return _raise(check)
    return {"ok": True, "session_id": str(session_id), "role": body.get("role")}


@router.post("/sessions/{session_id}/ln-scan")
async def ln_scan(session_id: UUID, body: ScanBody, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_compliance import prescan_outgoing

    out = prescan_outgoing(body.text)
    out["session_id"] = str(session_id)
    return out


@router.post("/sessions/{session_id}/legs/{leg_id}/utterance")
async def add_utterance(
    session_id: UUID,
    leg_id: UUID,
    body: UtteranceBody,
    request: Request,
    user: Dict = Depends(require_coach),
):
    _flag()
    from app.services.studio_session_service import append_utterance

    return _raise(
        await append_utterance(
            _pool(request), str(session_id), _hw(user), str(leg_id), body.text
        )
    )


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


@router.post("/episodes/{episode_id}/apply-cuts")
async def episode_apply_cuts(
    episode_id: UUID, body: CutsBody, request: Request, user: Dict = Depends(require_coach)
):
    _flag()
    from app.services.studio_media_tape import apply_cuts

    return _raise(
        await apply_cuts(_pool(request), str(episode_id), _hw(user), body.cuts)
    )


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


@router.post("/episodes/{episode_id}/regenerate")
async def episode_regen(
    episode_id: UUID, body: RegenBody, request: Request, user: Dict = Depends(require_coach)
):
    _flag()
    from app.services.studio_episode_service import regenerate_segment

    return _raise(
        await regenerate_segment(
            _pool(request), str(episode_id), _hw(user), body.segment_id, body.coach_note
        )
    )


@router.post("/episodes/{episode_id}/youtube-upload")
async def episode_youtube(
    episode_id: UUID, request: Request, user: Dict = Depends(require_coach)
):
    _flag()
    from app.services.studio_youtube import upload_episode

    return _raise(await upload_episode(_pool(request), _hw(user), str(episode_id)))


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
    from app.services.studio_screener_service import inbound_twiml

    return Response(content=inbound_twiml(), media_type="application/xml")


@public_router.post("/voice/screener")
async def voice_screener(request: Request):
    from app.services.studio_screener_service import handle_screener, lookup_show_by_did, persist_screener

    step = (request.query_params.get("step") or "disclosure").strip()
    try:
        n = int(request.query_params.get("n") or 0)
    except (TypeError, ValueError):
        n = 0
    form: Dict[str, Any] = {}
    try:
        form = dict(await request.form())
    except Exception:
        form = {}
    digits = str(form.get("Digits") or "")
    speech = str(form.get("SpeechResult") or "")
    out = handle_screener(step=step, digits=digits, speech=speech, n=n)
    if out.get("persist"):
        show_id = await lookup_show_by_did(_pool(request), str(form.get("To") or ""))
        await persist_screener(
            _pool(request),
            show_id=show_id,
            session_id=None,
            phone=str(form.get("From") or ""),
            speech=str(out.get("speech") or speech),
            consented=bool(out.get("consented")),
            risk=bool(out.get("risk")),
        )
    return Response(content=out["twiml"], media_type="application/xml")


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
    from app.services.studio_sip import sip_health as _sip

    return _sip()


@public_router.get("/voice/zoom-health")
async def zoom_phone_health():
    from app.services.studio_sip import zoom_phone_health as _zoom

    return _zoom()


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
    return {"status": "ok", "connected": False, "phase": "S3", "channel_owned_by": "coach"}


@public_router.get("/youtube/callback")
async def youtube_callback(request: Request):
    from fastapi.responses import HTMLResponse, RedirectResponse

    from app.services.studio_youtube import exchange_code

    code = (request.query_params.get("code") or "").strip()
    state = (request.query_params.get("state") or "").strip()
    out = await exchange_code(_pool(request), code, state)
    dest = os.getenv("STUDIO_YOUTUBE_POST_AUTH", "https://coach.sovereignsanctuary.net/")
    if out.get("ok"):
        return RedirectResponse(f"{dest}#studio_youtube=connected")
    html = f"<html><body>YouTube connect failed: {out.get('reason')}</body></html>"
    return HTMLResponse(html, status_code=int(out.get("code") or 400))


@public_router.post("/voice/sms-reply")
async def voice_sms_reply(request: Request):
    from app.services.studio_screener_service import apply_sms_reply

    form: Dict[str, Any] = {}
    try:
        form = dict(await request.form())
    except Exception:
        form = {}
    await apply_sms_reply(
        _pool(request),
        did=str(form.get("To") or ""),
        phone=str(form.get("From") or ""),
        body=str(form.get("Body") or ""),
    )
    return Response(content="<Response/>", media_type="application/xml")


@public_router.get("/avatar/envelope")
async def avatar_envelope(level: float = 0.35):
    from app.services.studio_avatar import envelope_frame

    return envelope_frame(level)


@public_router.post("/sessions/{session_id}/cohost/turn")
async def cohost_turn_public(session_id: UUID, body: CohostTurnBody, request: Request):
    _flag()
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    from app.services.studio_livekit import verify_livekit_jwt

    checked = verify_livekit_jwt(token)
    if not checked.get("ok"):
        raise HTTPException(401, checked.get("reason") or "livekit_jwt")
    if checked.get("session_id") != str(session_id):
        raise HTTPException(403, "room_mismatch")
    from app.services.studio_session_service import cohost_turn as _turn

    return _raise(
        await _turn(
            _pool(request),
            str(session_id),
            body.text,
            speaker=body.speaker or "host",
            toss=bool(body.toss),
            callers=int(body.callers or 0),
            waiting=int(body.waiting or 0),
            event=body.event or "line",
            realm=(body.realm or "")[:120],
            realm_blurb=(body.realm_blurb or "")[:240],
            realm_shift=bool(body.realm_shift),
            share_kind=(body.share_kind or "")[:40],
            share_note=(body.share_note or "")[:800],
        )
    )


@public_router.post("/sessions/{session_id}/cohost/speak")
async def cohost_speak_public(session_id: UUID, body: CohostSpeakBody, request: Request):
    _flag()
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    from app.services.studio_livekit import verify_livekit_jwt

    checked = verify_livekit_jwt(token)
    if not checked.get("ok"):
        raise HTTPException(401, checked.get("reason") or "livekit_jwt")
    if checked.get("session_id") != str(session_id):
        raise HTTPException(403, "room_mismatch")
    line = (body.text or "").strip()
    if not line or len(line) > 2000:
        raise HTTPException(422, "text required")
    from app.services.studio_session_service import synthesize_cohost_line

    audio = await synthesize_cohost_line(
        line, voice_router=getattr(request.app.state, "voice_router", None)
    )
    if not audio:
        raise HTTPException(502, "tts")
    from app.services.studio_phone_voice import studio_audio_media_type

    return Response(content=audio, media_type=studio_audio_media_type(audio))


@public_router.get("/sessions/{session_id}/realm")
async def studio_realm_current(session_id: UUID, request: Request):
    """The Thera-world realm on air, rotating every REALM_ROTATE_SECONDS.

    Polling this is what drives rotation, so realms only advance while a room
    is actually watching.
    """
    _flag()
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    from app.services.studio_livekit import verify_livekit_jwt

    checked = verify_livekit_jwt(token)
    if not checked.get("ok"):
        raise HTTPException(401, checked.get("reason") or "livekit_jwt")
    if checked.get("session_id") != str(session_id):
        raise HTTPException(403, "room_mismatch")
    from app.services.studio_realm_rotator import current_realm

    return await current_realm(_pool(request), str(session_id))


@public_router.get("/sessions/{session_id}/realm/{frame_id}")
async def studio_realm_image(session_id: UUID, frame_id: int, request: Request):
    """One stored realm frame. Scoped to its own session so a room token can
    only pull the backdrops that played in that room."""
    _flag()
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    from app.services.studio_livekit import verify_livekit_jwt

    checked = verify_livekit_jwt(token)
    if not checked.get("ok"):
        raise HTTPException(401, checked.get("reason") or "livekit_jwt")
    if checked.get("session_id") != str(session_id):
        raise HTTPException(403, "room_mismatch")
    from app.services.studio_realm_rotator import image_media_type, realm_image_bytes

    raw = await realm_image_bytes(_pool(request), str(session_id), int(frame_id))
    if not raw:
        raise HTTPException(404, "realm_frame")
    return Response(
        content=raw,
        media_type=image_media_type(raw),
        headers={"Cache-Control": "private, max-age=86400, immutable"},
    )


@public_router.post("/sessions/{session_id}/cohost/caption")
async def cohost_caption_public(
    session_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    speaker: str = Form("host"),
    identity: str = Form(""),
):
    _flag()
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    from app.services.studio_livekit import verify_livekit_jwt

    checked = verify_livekit_jwt(token)
    if not checked.get("ok"):
        raise HTTPException(401, checked.get("reason") or "livekit_jwt")
    if checked.get("session_id") != str(session_id):
        raise HTTPException(403, "room_mismatch")
    raw = await file.read()
    if len(raw) > 800_000:
        raise HTTPException(413, "caption_too_large")
    from app.services.studio_session_service import ingest_live_caption

    return await ingest_live_caption(
        raw,
        speaker=speaker,
        identity=identity,
        content_type=file.content_type or "audio/webm",
        session_id=str(session_id),
        db_pool=_pool(request),
    )


@public_router.post("/sessions/{session_id}/cohost/share-frame")
async def cohost_share_frame_public(
    session_id: UUID,
    request: Request,
    file: UploadFile = File(...),
):
    """Host-only still of the live share so Nate can read the page. QUANTUM-CRYSTAL-ARCH"""
    _flag()
    _require_host_jwt(request, session_id)
    raw = await file.read()
    from app.services.studio_cohost_share import describe_share_frame, remember_share_frame

    out = await describe_share_frame(raw)
    if not out.get("ok"):
        return _raise(out)
    remember_share_frame(str(session_id), out.get("note") or "", out.get("jpeg") or "")
    return {"ok": True, "seen": bool(out.get("seen")), "note": out.get("note") or ""}


@public_router.post("/sessions/{session_id}/cohost/share-asset")
async def cohost_share_asset_public(
    session_id: UUID,
    request: Request,
    file: UploadFile = File(...),
):
    """Host-only image/PDF/document ingest so Nate can read the page. QUANTUM-CRYSTAL-ARCH"""
    _flag()
    _require_host_jwt(request, session_id)
    raw = await file.read()
    from app.services.studio_cohost_share import ingest_share_asset

    return _raise(
        await ingest_share_asset(
            str(session_id),
            raw,
            filename=file.filename or "file",
            content_type=file.content_type or "",
        )
    )


@public_router.post("/sessions/{session_id}/cohost/share")
async def cohost_share_public(session_id: UUID, body: CohostShareBody, request: Request):
    """Host-only lookup or URL card for the share pane. QUANTUM-CRYSTAL-ARCH"""
    _flag()
    checked = _require_host_jwt(request, session_id)
    from app.services.studio_cohost_share import host_search, host_url_card

    kind = (body.kind or "search").strip().lower()
    if kind == "url":
        return _raise(host_url_card(body.url or body.query))
    if kind != "search":
        raise HTTPException(422, "kind")
    proxy = getattr(request.app.state, "search_proxy", None)
    return _raise(
        await host_search(proxy, body.query or body.url, str(checked.get("identity") or ""))
    )


@public_router.get("/sessions/{session_id}/cohost/sounds")
async def cohost_sounds_public(session_id: UUID, request: Request):
    _flag()
    _require_host_jwt(request, session_id)
    from app.services.studio_cohost_share import sound_catalog

    return {"ok": True, "sounds": sound_catalog()}


@public_router.post("/sessions/{session_id}/cohost/sound")
async def cohost_sound_public(session_id: UUID, body: CohostSoundBody, request: Request):
    """Host-only SFX arm. Room plays the catalog id locally. QUANTUM-CRYSTAL-ARCH"""
    _flag()
    _require_host_jwt(request, session_id)
    from app.services.studio_cohost_share import resolve_sound

    return _raise(resolve_sound(body.sound_id))


@public_router.get("/livekit/health")
async def livekit_health():
    from app.services.studio_livekit import health

    return health()


@public_router.get("/livekit/room")
async def livekit_room_page():
    from app.services.studio_livekit import ROOM_HTML

    return HTMLResponse(ROOM_HTML)


@public_router.post("/livekit/events")
async def livekit_events(request: Request):
    from app.services.studio_livekit import (
        handle_event,
        parse_egress_event,
        verify_livekit_webhook,
    )
    from app.services.studio_media_tape import stamp_session_tape

    raw = await request.body()
    checked = verify_livekit_webhook(request.headers.get("authorization") or "", raw)
    if not checked.get("ok"):
        raise HTTPException(401, checked.get("reason") or "unauthorized")
    body: Dict[str, Any] = {}
    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    parsed = parse_egress_event(body)
    if parsed.get("session_id") and parsed.get("media_r2_key"):
        await stamp_session_tape(
            _pool(request),
            str(parsed["session_id"]),
            media_r2_key=str(parsed.get("media_r2_key") or ""),
            egress_id=str(parsed.get("egress_id") or ""),
            ready=bool(parsed.get("complete")),
        )
    return handle_event(body)


@router.get("/youtube/status")
async def youtube_status(request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_youtube import oauth_status

    return await oauth_status(_pool(request), _hw(user))


@router.post("/shows/{show_id}/youtube-go-live")
async def youtube_go_live(
    show_id: UUID,
    body: YoutubeGoLiveBody,
    request: Request,
    user: Dict = Depends(require_coach),
):
    """Create a Live event on the assigned coach channel and save RTMP. QUANTUM-CRYSTAL-ARCH"""
    _flag()
    from app.services.studio_youtube import go_live

    pool = _pool(request)
    out = await go_live(
        pool,
        _hw(user),
        str(show_id),
        title=body.title,
        privacy=body.privacy,
    )
    if not out.get("ok"):
        return _raise(out)
    sid = (body.session_id or "").strip()
    if sid and pool:
        from app.services.studio_livekit import start_room_egress
        from app.services.studio_invariants import live_tier_unlocked

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT sh.rtmp_url,
                  (SELECT COUNT(*) FROM studio_episodes e
                    WHERE e.show_id = sh.id AND e.state = 'published'
                      AND NOT EXISTS (
                        SELECT 1 FROM studio_compliance_flags f
                        WHERE f.episode_id = e.id AND f.status = 'open'
                      )
                  ) AS clean_published
                FROM studio_sessions s
                JOIN studio_shows sh ON sh.id = s.show_id
                WHERE s.id = $1::uuid AND sh.id = $2::uuid AND sh.coach_id = $3
                """,
                sid,
                str(show_id),
                _hw(user),
            )
        if row:
            unlocked = live_tier_unlocked(int(row["clean_published"] or 0))
            plan = await start_room_egress(
                sid, rtmp_url=row["rtmp_url"] or "", live_unlocked=unlocked
            )
            out["egress"] = plan
    return out


@router.get("/youtube/connect")
async def youtube_connect(user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_youtube import connect_url

    return _raise(connect_url(_hw(user)))


@router.post("/youtube/store")
async def youtube_store(request: Request, user: Dict = Depends(require_coach)):
    _flag()
    from app.services.studio_youtube import store_tokens

    body: Dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    cipher = str(body.get("refresh_ciphertext") or "").strip()
    if not cipher:
        raise HTTPException(422, "refresh_ciphertext required")
    return _raise(await store_tokens(_pool(request), _hw(user), cipher))


@router.post("/shows/{show_id}/sms-consent")
async def sms_consent(
    show_id: UUID, body: ConsentRecordBody, request: Request, user: Dict = Depends(require_coach)
):
    _flag()
    pool = _pool(request)
    if not pool:
        raise HTTPException(503, "no_db")
    kind = body.consent_kind if body.consent_kind in ("sms_opt_in", "recall") else "sms_opt_in"
    async with pool.acquire() as conn:
        show = await conn.fetchrow(
            "SELECT id FROM studio_shows WHERE id = $1::uuid AND coach_id = $2",
            str(show_id),
            _hw(user),
        )
        if not show:
            raise HTTPException(404, "not_found")
        await conn.execute(
            """
            INSERT INTO studio_consent_records (show_id, consent_kind, granted, source)
            VALUES ($1::uuid, $2, $3, 'coach')
            """,
            str(show_id),
            kind,
            body.granted,
        )
    return {"ok": True, "consent_kind": kind, "granted": body.granted}
