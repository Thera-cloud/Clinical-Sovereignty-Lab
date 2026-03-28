"""
Counter-Intelligence API — Admin endpoints for threat management
and the public beacon endpoint for canary/seed tracking.

Endpoints:
  GET  /api/threats               — List active threat profiles (admin)
  GET  /api/threats/summary       — High-level threat summary (admin)
  GET  /api/threats/{profile_id}  — Attacker profile details (admin)
  GET  /api/threats/{profile_id}/map — Infrastructure map (admin)
  POST /api/threats/{profile_id}/escalate — Manual tier escalation (admin)
  GET  /beacon/{canary_id}        — Tracking pixel (public, logged)
  GET  /beacon/{canary_id}/{path} — Tracking pixel with subpath (public, logged)
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from app.services.api_server import require_admin

logger = logging.getLogger("counter_intelligence.api")

router = APIRouter()

# Module-level references set during app startup
_orchestrator = None
_threat_db = None
_fingerprinter = None
_reverse_mapper = None
_beacon_listener = None


def configure(
    orchestrator=None,
    threat_db=None,
    fingerprinter=None,
    reverse_mapper=None,
    beacon_listener=None,
) -> None:
    """Configure module-level service references during app startup."""
    global _orchestrator, _threat_db, _fingerprinter, _reverse_mapper, _beacon_listener
    _orchestrator = orchestrator
    _threat_db = threat_db
    _fingerprinter = fingerprinter
    _reverse_mapper = reverse_mapper
    _beacon_listener = beacon_listener


# =============================================================================
# ADMIN ENDPOINTS — Threat Management
# =============================================================================


@router.get("/api/threats", dependencies=[Depends(require_admin)])
async def list_threats(limit: int = Query(100, ge=1, le=500)):
    """List all active threat profiles."""
    if _threat_db:
        profiles = await _threat_db.list_active_profiles(limit=limit)
        return {"threats": profiles, "count": len(profiles)}
    if _fingerprinter:
        profiles = await _fingerprinter.get_all_active()
        return {"threats": profiles[:limit], "count": len(profiles)}
    return {"threats": [], "count": 0}


@router.get("/api/threats/summary", dependencies=[Depends(require_admin)])
async def threat_summary():
    """High-level threat intelligence summary."""
    summary = {}
    if _threat_db:
        summary = await _threat_db.get_threat_summary()
    if _orchestrator:
        summary["orchestrator"] = _orchestrator.get_status()
    return summary


@router.get("/api/threats/{profile_id}", dependencies=[Depends(require_admin)])
async def get_threat_profile(profile_id: str):
    """Get detailed attacker profile."""
    try:
        pid = UUID(profile_id)
    except ValueError:
        return {"error": "Invalid profile ID"}

    if _fingerprinter:
        profile = await _fingerprinter.get_profile(pid)
        if profile:
            return {"profile": profile}

    if _threat_db:
        profile = await _threat_db.get_profile(pid)
        if profile:
            return {"profile": profile}

    return {"error": "Profile not found"}


@router.get("/api/threats/{profile_id}/events", dependencies=[Depends(require_admin)])
async def get_threat_events(
    profile_id: str, limit: int = Query(100, ge=1, le=500),
):
    """Get attack events for a profile."""
    try:
        pid = UUID(profile_id)
    except ValueError:
        return {"error": "Invalid profile ID"}

    if _threat_db:
        events = await _threat_db.get_events_for_profile(pid, limit=limit)
        return {"events": events, "count": len(events)}

    return {"events": [], "count": 0}


@router.get("/api/threats/{profile_id}/map", dependencies=[Depends(require_admin)])
async def get_infrastructure_map(profile_id: str):
    """Get the reverse-mapped infrastructure map for an attacker."""
    if _reverse_mapper:
        infra_map = await _reverse_mapper.get_map(profile_id)
        if infra_map:
            return {"map": infra_map}

    return {"error": "No infrastructure map available"}


@router.post("/api/threats/{profile_id}/escalate", dependencies=[Depends(require_admin)])
async def escalate_threat(profile_id: str, tier: int = Query(2, ge=1, le=3)):
    """Manually escalate an attacker to a higher response tier."""
    try:
        pid = UUID(profile_id)
    except ValueError:
        return {"error": "Invalid profile ID"}

    if _orchestrator:
        result = await _orchestrator.escalate(pid, tier)
        return {"result": result}

    return {"error": "Orchestrator not configured"}


# =============================================================================
# PUBLIC ENDPOINT — Beacon (Canary/Seed Tracking Pixel)
# =============================================================================

# 1x1 transparent GIF
_PIXEL = (
    b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00"
    b"\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x00\x00\x00\x00"
    b"\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02"
    b"\x44\x01\x00\x3b"
)


@router.get("/beacon/{canary_id}")
async def beacon_hit(canary_id: str, request: Request):
    """
    Tracking pixel endpoint.
    When an attacker processes stolen data containing a canary/seed,
    their system fetches this URL, revealing their IP and User-Agent.
    """
    requester_ip = request.client.host if request.client else "unknown"
    requester_ua = request.headers.get("user-agent", "")
    headers = dict(request.headers)

    logger.warning(
        "BEACON HIT: canary=%s ip=%s ua=%s",
        canary_id, requester_ip, requester_ua,
    )

    if _beacon_listener:
        await _beacon_listener.on_http_beacon(
            canary_id, requester_ip, requester_ua, headers,
        )

    return Response(
        content=_PIXEL,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/beacon/{canary_id}/{path:path}")
async def beacon_hit_with_path(canary_id: str, path: str, request: Request):
    """Beacon with subpath — same tracking, captures path info."""
    requester_ip = request.client.host if request.client else "unknown"
    requester_ua = request.headers.get("user-agent", "")
    headers = dict(request.headers)
    headers["_subpath"] = path

    logger.warning(
        "BEACON HIT: canary=%s path=%s ip=%s",
        canary_id, path, requester_ip,
    )

    if _beacon_listener:
        await _beacon_listener.on_http_beacon(
            canary_id, requester_ip, requester_ua, headers,
        )

    # Return appropriate content type based on path
    if path.endswith(".png") or path.endswith(".gif"):
        return Response(content=_PIXEL, media_type="image/gif")
    elif path.endswith(".css"):
        return Response(content=b"/* */", media_type="text/css")
    elif path.endswith(".json"):
        return Response(content=b"{}", media_type="application/json")
    else:
        return Response(content=_PIXEL, media_type="image/gif")
