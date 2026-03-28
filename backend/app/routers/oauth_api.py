"""OAuth 2.0 Provider API — client_credentials grant, JWT issuance, token validation."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.services.api_server import get_current_user, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/oauth", tags=["oauth"])


class TokenRequest(BaseModel):
    grant_type: str = "client_credentials"
    client_id: str
    client_secret: str
    scope: Optional[str] = None


class RegisterClientRequest(BaseModel):
    name: str
    scopes: Optional[list] = None
    tier: str = "free"
    redirect_uri: str = ""


class ValidateTokenRequest(BaseModel):
    token: str


@router.get("/health")
async def oauth_health(request: Request):
    oauth = getattr(request.app.state, "oauth_server", None)
    if not oauth:
        return {"status": "ok", "service": "oauth_provider", "initialized": False}
    status = oauth.get_status()
    return {"status": "ok", "service": "oauth_provider", **status}


@router.post("/token")
async def oauth_token(body: TokenRequest, request: Request):
    """OAuth 2.0 client_credentials token endpoint."""
    oauth = getattr(request.app.state, "oauth_server", None)
    if not oauth:
        raise HTTPException(503, "OAuth server not initialized")

    if body.grant_type != "client_credentials":
        raise HTTPException(400, {
            "error": "unsupported_grant_type",
            "error_description": "Only client_credentials is supported",
        })

    result = await oauth.issue_token(body.client_id, body.client_secret)
    if "error" in result:
        raise HTTPException(401, result)

    return result


@router.post("/validate")
async def oauth_validate(body: ValidateTokenRequest, request: Request):
    """Validate a JWT and return its claims. Used by edge workers."""
    oauth = getattr(request.app.state, "oauth_server", None)
    if not oauth:
        raise HTTPException(503, "OAuth server not initialized")

    claims = await oauth.validate_token(body.token)
    if not claims:
        raise HTTPException(401, {"error": "invalid_token"})

    return {"valid": True, "claims": claims}


@router.post("/register")
async def oauth_register(
    body: RegisterClientRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):
    """Register a new API client. Admin only."""
    oauth = getattr(request.app.state, "oauth_server", None)
    if not oauth:
        raise HTTPException(503, "OAuth server not initialized")

    result = await oauth.register_client(
        name=body.name,
        created_by=admin.get("username", "admin"),
        scopes=body.scopes,
        tier=body.tier,
        redirect_uri=body.redirect_uri,
    )
    if "error" in result:
        raise HTTPException(400, result)

    return result


@router.get("/clients")
async def oauth_list_clients(
    request: Request,
    admin: dict = Depends(require_admin),
):
    """List registered API clients. Admin only."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        return {"clients": []}

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT client_id, name, tier, scopes, rate_limit, monthly_cap,
                          is_active, created_at
                   FROM api_clients ORDER BY created_at DESC LIMIT 50"""
            )
            return {"clients": [dict(r) for r in rows]}
    except Exception as e:
        logger.warning("oauth_list_clients: %s", e)
        return {"clients": [], "note": "Table may not exist yet"}
