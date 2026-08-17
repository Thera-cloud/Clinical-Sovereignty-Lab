"""GEO public + coach/admin surfaces. Flags default OFF — unpublished until T1 gate."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

try:
    from app.services.api_server import require_admin, require_coach
except ImportError:
    from backend.app.services.api_server import require_admin, require_coach

from app.services.disco.flags import disco_flag
from app.services.disco.workers_61_64 import CredentialClaim, InlineValueRenderer

logger = logging.getLogger("disco.api")

public_router = APIRouter(prefix="/api/v1/public/disco", tags=["disco-public"])
router = APIRouter(prefix="/api/disco", tags=["disco"])


def _engine(request: Request):
    eng = getattr(request.app.state, "disco_engine", None)
    if eng is None:
        raise HTTPException(503, detail={"status": "degraded", "reason": "disco_engine unavailable"})
    return eng


@public_router.get("/health")
async def public_health(request: Request):
    eng = getattr(request.app.state, "disco_engine", None)
    if eng is None:
        return {"status": "degraded", "reason": "disco_engine unavailable"}
    return eng.health()


@public_router.get("/robots.txt", response_class=PlainTextResponse)
async def public_robots(request: Request, host: str = Query("brand")):
    return _engine(request).robots(host)


@public_router.get("/llms.txt", response_class=PlainTextResponse)
async def public_llms(request: Request):
    return _engine(request).llms()


@public_router.get("/product")
async def public_product(request: Request):
    return {"status": "ok", "copy": _engine(request).static_copy()["product"]}


@public_router.get("/pricing")
async def public_pricing(request: Request):
    copy = _engine(request).static_copy()
    return {
        "status": "ok",
        "copy": copy["pricing"],
        "canonical_price_claim": copy["canonical_price_claim"],
        "schema": _engine(request).org_offer_schema(),
    }


@public_router.get("/org-schema")
async def public_org_schema(request: Request):
    return {"status": "ok", "jsonld": _engine(request).org_schema()}


@public_router.get("/homepage-seo")
async def public_homepage_seo(request: Request):
    return {"status": "ok", "packet": _engine(request).homepage_seo()}


@public_router.get("/mcp.json")
async def public_mcp(request: Request):
    if not disco_flag("DISCO_AGENT_API"):
        raise HTTPException(404, detail={"status": "not_live", "reason": "DISCO_AGENT_API off"})
    return _engine(request).mcp_descriptor()


@public_router.get("/verify-credential")
async def public_verify(
    request: Request,
    full_name: str,
    credential_type: str,
    jurisdiction: str,
    identifier: str,
    coach_id: str = "public",
):
    if not disco_flag("DISCO_AGENT_API"):
        raise HTTPException(404, detail={"status": "not_live", "reason": "DISCO_AGENT_API off"})
    claim = CredentialClaim(coach_id, full_name, credential_type, jurisdiction, identifier)
    return {"status": "ok", "result": _engine(request).verifier.process(claim)}


@public_router.get("/widget", response_class=HTMLResponse)
async def public_widget(request: Request, unit: str = "grounding_60s", region: str = "US"):
    if not disco_flag("DISCO_WIDGET"):
        raise HTTPException(404, detail={"status": "not_live", "reason": "DISCO_WIDGET off — T5.7/T5.9 gate"})
    html = InlineValueRenderer().render_page("<p>Sovereign Sanctuary</p>", unit, region)
    return HTMLResponse(html)


@public_router.get("/coaches/{slug}", response_class=HTMLResponse)
async def public_coach(request: Request, slug: str):
    out = await _engine(request).public_profile_html(slug)
    if not out.get("ok"):
        raise HTTPException(out.get("status") or 404, detail={"status": "not_found", "reason": out.get("reason")})
    return HTMLResponse(out["html"])


@public_router.post("/referrer")
async def public_referrer(request: Request, body: Dict[str, Any]):
    coach_id = body.get("coach_id") or "unknown"
    referrer = body.get("referrer") or ""
    return await _engine(request).log_ai_search(coach_id, referrer, body)


@router.get("/status")
async def disco_status(request: Request, _user: Dict = Depends(require_coach)):
    return _engine(request).health()


@router.post("/lint")
async def disco_lint(request: Request, body: Dict[str, Any], _user: Dict = Depends(require_coach)):
    return {
        "status": "ok",
        **_engine(request).lint(body.get("text") or "", body.get("relationship_class") or "coaching"),
    }


@router.post("/canonical")
async def disco_canonical(request: Request, body: Dict[str, Any], user: Dict = Depends(require_coach)):
    record = dict(body)
    record.setdefault("coach_id", user.get("username") or user.get("user_id"))
    return await _engine(request).upsert_canonical(record)


@router.get("/queue")
async def disco_queue(request: Request, _user: Dict = Depends(require_coach)):
    return {"status": "ok", "items": _engine(request).queue_snapshot()}


@router.post("/listing-packet")
async def disco_listing(request: Request, body: Dict[str, Any], _user: Dict = Depends(require_coach)):
    return {"status": "ok", "packet": _engine(request).listing_packet(body)}


@router.post("/gbp-packet")
async def disco_gbp(request: Request, body: Dict[str, Any], _user: Dict = Depends(require_coach)):
    return {"status": "ok", "packet": _engine(request).gbp_claim_packet(body)}


@router.get("/admin/health")
async def admin_health(request: Request, _admin: Dict = Depends(require_admin)):
    return _engine(request).health()


@router.get("/admin/checklist")
async def admin_checklist(request: Request, _admin: Dict = Depends(require_admin)):
    return {"status": "ok", "tickets": _engine(request).checklist_state()}


@router.post("/admin/panel")
async def admin_panel(request: Request, body: Optional[Dict[str, Any]] = None, _admin: Dict = Depends(require_admin)):
    vol = float((body or {}).get("volatility") or 0)
    return {"status": "ok", **_engine(request).run_panel(vol)}


@router.post("/admin/horizons")
async def admin_horizons(request: Request, body: Dict[str, Any], _admin: Dict = Depends(require_admin)):
    series = [float(x) for x in (body.get("daily_series") or [])]
    return {"status": "ok", **_engine(request).horizons(series)}
