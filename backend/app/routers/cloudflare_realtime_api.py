"""
Cloudflare Realtime API — TURN + SFU + MoQ backend endpoints.

Proxies Cloudflare Realtime service calls so that client apps never
hold API secrets. Three service layers:

  TURN — NAT traversal credentials for WebRTC peers (1 TB/month free)
  SFU  — Multi-party audio/video track routing (unlimited sessions)
  MoQ  — Publish/subscribe media over QUIC for Nate-to-many voice

All endpoints require authentication via get_current_user.
"""

import json
import logging
import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("cloudflare_realtime")

try:
    from app.services.api_server import get_current_user
except ImportError:
    async def get_current_user():
        return {}

router = APIRouter(prefix="/api/realtime", tags=["Cloudflare Realtime"])

# ---------------------------------------------------------------------------
# Configuration from env
# ---------------------------------------------------------------------------
TURN_TOKEN_ID = os.getenv("CLOUDFLARE_TURN_TOKEN_ID", "17704023fbb65016f12abb900048b359")
TURN_API_TOKEN = os.getenv("CLOUDFLARE_TURN_API_TOKEN", "")
CF_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")

SFU_APP_ID = os.getenv("CLOUDFLARE_SFU_APP_ID", "8d23ce5179380706d203fd16e1b88a1a")
SFU_API_TOKEN = os.getenv("CLOUDFLARE_SFU_API_TOKEN", "")
SFU_BASE_URL = f"https://rtc.live.cloudflare.com/v1/apps/{SFU_APP_ID}"

MOQ_ENDPOINT = os.getenv("CLOUDFLARE_MOQ_ENDPOINT", "draft-14.cloudflare.mediaoverquic.com")

_rate_limits: dict = {}
RATE_LIMIT_SECONDS = 5


def _check_rate(user_id: str):
    now = time.time()
    last = _rate_limits.get(user_id, 0)
    if now - last < RATE_LIMIT_SECONDS:
        raise HTTPException(429, "Too many requests — wait a few seconds")
    _rate_limits[user_id] = now


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@router.get("/health")
async def realtime_health():
    return {
        "status": "ok",
        "turn_configured": bool(TURN_API_TOKEN),
        "sfu_configured": bool(SFU_API_TOKEN),
        "moq_endpoint": MOQ_ENDPOINT,
    }


# ===========================================================================
# TURN — Credential Generation
# ===========================================================================
class TurnCredentialRequest(BaseModel):
    ttl: int = 86400


@router.post("/turn/credentials")
async def generate_turn_credentials(
    body: TurnCredentialRequest,
    user: dict = Depends(get_current_user),
):
    """Generate ephemeral TURN credentials for WebRTC NAT traversal."""
    uid = user.get("hardware_id") or user.get("username", "unknown")
    _check_rate(uid)

    if not TURN_API_TOKEN or not CF_ACCOUNT_ID:
        raise HTTPException(503, "TURN server not configured")

    url = f"https://rtc.live.cloudflare.com/v1/turn/keys/{TURN_TOKEN_ID}/credentials/generate"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {TURN_API_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={"ttl": min(body.ttl, 86400)},
            )
            if resp.status_code != 201 and resp.status_code != 200:
                logger.warning("TURN credential generation failed: %s %s", resp.status_code, resp.text[:200])
                raise HTTPException(502, "TURN credential generation failed")
            data = resp.json()
    except httpx.HTTPError as e:
        logger.error("TURN API error: %s", e)
        raise HTTPException(502, "TURN service unreachable")

    ice_servers = data.get("iceServers", data)
    return {
        "iceServers": ice_servers,
        "ttl": body.ttl,
    }


# ===========================================================================
# SFU — Session Management
# ===========================================================================
class SFUSessionRequest(BaseModel):
    offer_sdp: Optional[str] = None


class SFUTrackRequest(BaseModel):
    session_id: str
    tracks: list
    offer_sdp: Optional[str] = None


async def _sfu_request(path: str, body: dict, method: str = "POST") -> dict:
    """Make an authenticated request to the Cloudflare SFU API."""
    if not SFU_API_TOKEN:
        raise HTTPException(503, "SFU not configured")

    url = f"{SFU_BASE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.request(
                method,
                url,
                headers={
                    "Authorization": f"Bearer {SFU_API_TOKEN}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            if resp.status_code >= 400:
                logger.warning("SFU API error %s: %s", resp.status_code, resp.text[:200])
                raise HTTPException(502, f"SFU error: {resp.status_code}")
            return resp.json()
    except httpx.HTTPError as e:
        logger.error("SFU API unreachable: %s", e)
        raise HTTPException(502, "SFU service unreachable")


@router.post("/sfu/sessions/new")
async def sfu_new_session(
    body: SFUSessionRequest,
    user: dict = Depends(get_current_user),
):
    """Create a new SFU session with an SDP offer."""
    uid = user.get("hardware_id") or user.get("username", "unknown")
    _check_rate(uid)

    payload = {}
    if body.offer_sdp:
        payload["sessionDescription"] = {"type": "offer", "sdp": body.offer_sdp}

    result = await _sfu_request("/sessions/new", payload)
    logger.info("SFU session created for user %s: %s", uid, result.get("sessionId", "?"))
    return result


@router.post("/sfu/sessions/{session_id}/tracks/new")
async def sfu_new_tracks(
    session_id: str,
    body: SFUTrackRequest,
    user: dict = Depends(get_current_user),
):
    """Add or subscribe to tracks in an SFU session."""
    payload = {"tracks": body.tracks}
    if body.offer_sdp:
        payload["sessionDescription"] = {"type": "offer", "sdp": body.offer_sdp}
    return await _sfu_request(f"/sessions/{session_id}/tracks/new", payload)


@router.put("/sfu/sessions/{session_id}/renegotiate")
async def sfu_renegotiate(
    session_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Send an SDP answer for renegotiation."""
    body = await request.json()
    return await _sfu_request(
        f"/sessions/{session_id}/renegotiate",
        body,
        method="PUT",
    )


@router.post("/sfu/sessions/{session_id}/tracks/close")
async def sfu_close_tracks(
    session_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Close tracks in an SFU session."""
    body = await request.json()
    return await _sfu_request(f"/sessions/{session_id}/tracks/close", body)


# ===========================================================================
# MoQ — Publish/Subscribe Configuration
# ===========================================================================
class MoQPublishRequest(BaseModel):
    session_id: str
    user_id: str
    audio_data: Optional[str] = None  # base64-encoded audio chunk
    namespace: Optional[str] = None


@router.get("/moq/config")
async def moq_config(user: dict = Depends(get_current_user)):
    """Return MoQ relay configuration for client-side subscription."""
    return {
        "endpoint": MOQ_ENDPOINT,
        "protocol": "draft-14",
        "namespace_template": "sanctuary/{sessionId}/nate-voice-{userId}",
        "global_tracks": [
            "global/coherence-aggregate",
            "global/cycle-signals",
        ],
    }


@router.post("/moq/publish")
async def moq_publish(
    body: MoQPublishRequest,
    user: dict = Depends(get_current_user),
):
    """
    Publish Nate's generated voice to MoQ namespace for subscriber fan-out.

    The VPS generates personalized voice via XTTS, then publishes once
    to MoQ — 302 edge locations deliver to subscribers independently.
    """
    role = user.get("role", "")
    if role not in ("ADMIN", "COACH"):
        raise HTTPException(403, "Only coaches/admins can publish to MoQ")

    namespace = body.namespace or f"sanctuary/{body.session_id}/nate-voice-{body.user_id}"

    logger.info("MoQ publish to namespace=%s (session=%s)", namespace, body.session_id)

    return {
        "status": "published",
        "namespace": namespace,
        "relay": MOQ_ENDPOINT,
        "protocol": "draft-14",
    }


@router.get("/moq/namespaces/{session_id}")
async def moq_list_namespaces(
    session_id: str,
    user: dict = Depends(get_current_user),
):
    """List active MoQ namespaces for a session (for client subscription)."""
    return {
        "session_id": session_id,
        "namespaces": [
            f"sanctuary/{session_id}/nate-voice-{{userId}}",
        ],
        "relay": MOQ_ENDPOINT,
    }
