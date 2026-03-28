"""
HIVE DEFENSE v4.4 — Sandbox API
Layer 6 internal FastAPI running inside the isolated detonation container.

Endpoints:
  POST /detonate  — Run DetonationChamber on a URL
  POST /hunt      — Run PhishingLinkHunter recon
  GET  /health    — Liveness check

Auth: Shared HMAC key (SANDBOX_HMAC_KEY env var)

Patent-Pending — Claims 30-56
(c) 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger("sandbox_api")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Detonation Sandbox", docs_url=None, redoc_url=None)

SANDBOX_KEY = os.getenv("SANDBOX_HMAC_KEY", "")

if not SANDBOX_KEY:
    import logging as _logging
    _logging.getLogger("sandbox").warning("SANDBOX_HMAC_KEY is empty — sandbox endpoints accept unauthenticated requests")


def _verify_key(request: Request) -> None:
    """Verify the shared HMAC key. Rejects all requests when key is empty."""
    if not SANDBOX_KEY:
        raise HTTPException(status_code=503, detail="Sandbox HMAC key not configured")
    provided = request.headers.get("X-Sandbox-Key", "")
    if not hmac.compare_digest(provided, SANDBOX_KEY):
        raise HTTPException(status_code=403, detail="Invalid sandbox key")


class DetonateRequest(BaseModel):
    url: str
    inject_decoy: bool = True


class HuntRequest(BaseModel):
    threat_type: str = "url"
    content: str = ""
    source_note: str = ""


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "detonation-sandbox", "timestamp": time.time()}


@app.post("/detonate")
async def detonate(body: DetonateRequest, request: Request):
    """Detonate a URL in the sandboxed headless browser."""
    _verify_key(request)

    try:
        from detonation_chamber import get_chamber
        chamber = get_chamber()
        report = await chamber.detonate(
            url=body.url,
            inject_decoy=body.inject_decoy,
            source="sandbox_api",
        )
        return report.to_dict()
    except Exception as e:
        logger.error("Detonation failed: %s", e)
        raise HTTPException(500, detail=str(e))


@app.get("/detonations")
async def list_detonations(request: Request):
    """List all detonation operations."""
    _verify_key(request)
    from detonation_chamber import get_chamber
    chamber = get_chamber()
    return {"detonations": chamber.get_all_detonations()}


@app.get("/detonation/{det_id}")
async def detonation_detail(det_id: str, request: Request):
    """Get full detonation report."""
    _verify_key(request)
    from detonation_chamber import get_chamber
    chamber = get_chamber()
    report = chamber.get_detonation(det_id)
    if not report:
        raise HTTPException(404, f"Detonation {det_id} not found")
    return report.to_dict()


@app.post("/hunt")
async def hunt(body: HuntRequest, request: Request):
    """Run phishing link hunter reconnaissance."""
    _verify_key(request)

    try:
        from phishing_link_hunter import get_hunter
        hunter = get_hunter()
        report = await hunter.hunt_dropbox(
            threat_type=body.threat_type,
            content=body.content,
            source_note=body.source_note,
        )
        return report.to_dict()
    except Exception as e:
        logger.error("Hunt failed: %s", e)
        raise HTTPException(500, detail=str(e))


@app.get("/hunts")
async def list_hunts(request: Request):
    """List all hunt operations."""
    _verify_key(request)
    from phishing_link_hunter import get_hunter
    hunter = get_hunter()
    return {"hunts": hunter.get_all_hunts()}


@app.get("/hunt/{hunt_id}")
async def hunt_detail(hunt_id: str, request: Request):
    """Get full hunt report."""
    _verify_key(request)
    from phishing_link_hunter import get_hunter
    hunter = get_hunter()
    report = hunter.get_hunt(hunt_id)
    if not report:
        raise HTTPException(404, f"Hunt {hunt_id} not found")
    return report.to_dict()
