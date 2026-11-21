"""Secret-gated ingest for host-nginx probe paths. No session, no login."""

from __future__ import annotations

import hmac
import ipaddress
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from app.services.edge_probe_memory import enabled, ingest_token, mirror_page, remember

logger = logging.getLogger("edge_probe")

router = APIRouter(tags=["edge_probe"])

_QUIET = Response(status_code=404, content=b"", media_type="text/plain")


def _client_ip(request: Request) -> str:
    raw = (request.headers.get("cf-connecting-ip") or "").strip()
    if not raw:
        return ""
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return ""


@router.api_route("/api/edge-probe", methods=["GET", "HEAD"])
async def edge_probe(request: Request):
    token = ingest_token()
    presented = request.headers.get("x-edge-probe-token", "")
    try:
        token_ok = bool(token) and hmac.compare_digest(presented, token)
    except Exception:
        token_ok = False
    if not enabled() or not token_ok:
        return _QUIET
    source = _client_ip(request)
    if not source:
        return _QUIET
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        return _QUIET
    uri = request.headers.get("x-original-uri", "/")[:200]
    host = request.headers.get("host", "")[:80]
    hive = getattr(request.app.state, "hive_defense", None) or {}
    try:
        result = await remember(pool, source, host, uri, hive if isinstance(hive, dict) else {})
    except Exception as exc:
        logger.warning("edge probe memory failed: %s", exc)
        return _QUIET
    if not result["mirror"]:
        return _QUIET
    page = mirror_page(result["canary_id"])
    if request.method == "HEAD":
        return Response(status_code=404, media_type="text/html")
    return HTMLResponse(status_code=404, content=page)
