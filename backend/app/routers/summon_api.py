"""
Universal Nate Summon API — POST /api/summon

Public endpoint supporting both authenticated (bearer token) and anonymous
("3 Queries in a Bottle") access from any doorway.

Dual Brain Immune System hardening:
- HMAC-SHA256 request verification on /internal endpoint
- EndpointShield payload scanning
- Edge Mirror Shell coherence check
- Input sanitization and response validation
- SASE outbound validation wired
"""

import base64
import hashlib
import hmac
import html
import re
import time
import logging
import os
from typing import Optional
from collections import defaultdict

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/summon", tags=["summon"])

BURST_LIMIT = 10
BURST_WINDOW = 60
INTERNAL_BURST_LIMIT = 30
INTERNAL_BURST_WINDOW = 60
_fallback_rate_limits: dict = defaultdict(list)
_fallback_internal_rate: dict = defaultdict(list)

_HMAC_SECRET = os.getenv("EDGE_HMAC_SECRET", "").encode()
_HMAC_MAX_AGE = 30

_POISON_PATTERNS = [
    re.compile(r'<script', re.I),
    re.compile(r'javascript:', re.I),
    re.compile(r'data:text/html', re.I),
    re.compile(r'\beval\b'),
    re.compile(r'\bFunction\b'),
    re.compile(r'__proto__'),
    re.compile(r'ignore\s+(all\s+)?previous\s+instructions', re.I),
    re.compile(r'<\|im_start\|>'),
    re.compile(r'you\s+are\s+now\s+(a|an|the)\b', re.I),
]


class SummonRequest(BaseModel):
    message: str = Field(..., max_length=2000)
    channel: str = Field(default="api")
    context: Optional[dict] = None
    response_format: str = Field(default="text")
    device_fingerprint: Optional[str] = None


class SummonResponseModel(BaseModel):
    response: str
    sources_used: list
    access_level: str
    queries_remaining: Optional[int] = None
    powered_by: Optional[str] = None
    channel: str


async def _check_burst_limit(ip: str, request: Request) -> bool:
    """Per-IP burst limiting via Redis INCR (multi-worker safe).
    Falls back to in-memory dict if Redis is unavailable."""
    redis_client = getattr(request.app.state, "redis_client", None)
    if redis_client:
        try:
            key = f"nate:rate:summon:{ip}"
            count = await redis_client.incr(key)
            if count == 1:
                await redis_client.expire(key, BURST_WINDOW)
            return count <= BURST_LIMIT
        except Exception:
            pass
    now = time.time()
    window = [t for t in _fallback_rate_limits[ip] if now - t < BURST_WINDOW]
    _fallback_rate_limits[ip] = window
    if len(window) >= BURST_LIMIT:
        return False
    _fallback_rate_limits[ip].append(now)
    return True


@router.post("", response_model=SummonResponseModel)
async def summon_nate(req: SummonRequest, request: Request):
    """Universal summon endpoint — public or authenticated."""

    client_ip = request.client.host if request.client else "unknown"
    if not await _check_burst_limit(client_ip, request):
        raise HTTPException(429, "Too many requests. Please wait a moment.")

    summon_service = getattr(request.app.state, "nate_summon_service", None)
    if not summon_service:
        raise HTTPException(503, "Summon service is not available")

    auth_header = request.headers.get("Authorization", "")
    user = None

    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            user = await summon_service.validate_summon_token(token)
            if not user:
                user = await _try_bridge_token(request, token)

    if user:
        allowed, remaining = await summon_service.check_daily_limit(user["username"])
        if not allowed:
            return SummonResponseModel(
                response=(
                    "You've been busy today! Your queries will reset at midnight UTC. "
                    "You can continue using token-governed access for deeper analysis."
                ),
                sources_used=[],
                access_level="daily_limit",
                queries_remaining=0,
                channel=req.channel,
            )

    device_fp = req.device_fingerprint
    if not user and not device_fp:
        from app.services.nate_summon_service import NateSummonService
        user_agent = request.headers.get("User-Agent", "")
        accept_lang = request.headers.get("Accept-Language", "")
        device_fp = NateSummonService.generate_device_fingerprint(
            client_ip, user_agent, accept_lang
        )

    result = await summon_service.process_summon(
        message=req.message,
        channel=req.channel,
        user=user,
        device_fingerprint=device_fp,
        context=req.context,
        ip_address=client_ip,
    )

    return SummonResponseModel(
        response=result.response,
        sources_used=result.sources_used,
        access_level=result.access_level,
        queries_remaining=result.queries_remaining,
        powered_by=result.powered_by,
        channel=result.channel,
    )


@router.get("/my-token")
async def get_my_summon_token(request: Request):
    """Retrieve or generate the user's summon token (authenticated)."""
    user = await _require_auth(request)
    summon_service = getattr(request.app.state, "nate_summon_service", None)
    if not summon_service:
        raise HTTPException(503, "Summon service is not available")

    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database not available")

    async with db_pool.acquire() as conn:
        existing = await conn.fetchval(
            """SELECT token FROM summon_tokens
               WHERE username = $1 AND is_active = TRUE
               ORDER BY created_at DESC LIMIT 1""",
            user["username"],
        )

    if existing:
        return {"token": existing, "status": "active"}

    new_token = await summon_service.generate_summon_token(user["username"])
    if not new_token:
        raise HTTPException(500, "Failed to generate token")

    return {"token": new_token, "status": "created"}


@router.post("/regenerate-token")
async def regenerate_summon_token(request: Request):
    """Revoke current summon tokens and generate a new one (authenticated)."""
    user = await _require_auth(request)
    summon_service = getattr(request.app.state, "nate_summon_service", None)
    if not summon_service:
        raise HTTPException(503, "Summon service is not available")

    db_pool = getattr(request.app.state, "db_pool", None)
    if db_pool:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE summon_tokens SET is_active = FALSE WHERE username = $1",
                user["username"],
            )

    new_token = await summon_service.generate_summon_token(user["username"])
    if not new_token:
        raise HTTPException(500, "Failed to generate token")

    return {"token": new_token, "status": "regenerated"}


@router.get("/health")
async def summon_health(request: Request):
    """Health check for summon service."""
    summon_service = getattr(request.app.state, "nate_summon_service", None)
    privacy_shield = getattr(request.app.state, "privacy_shield", None)
    mention_agent = getattr(request.app.state, "nate_mention_agent", None)
    mention_status = mention_agent.get_status() if mention_agent else {}
    return {
        "status": "ok",
        "summon_service": summon_service is not None,
        "privacy_shield": privacy_shield is not None,
        "mention_agent": mention_status,
        "channels": [
            "api", "browser_extension", "telegram", "alexa",
            "google_assistant", "siri", "chatgpt_custom_gpt",
            "mention_x", "mention_linkedin",
        ],
    }


@router.get("/openapi.yaml")
async def summon_openapi_spec():
    """Serve the OpenAPI spec for ChatGPT Custom GPT registration."""
    import os
    spec_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "openapi-summon.yaml")
    try:
        with open(spec_path, "r") as f:
            content = f.read()
        from starlette.responses import Response as StarletteResponse
        return StarletteResponse(content=content, media_type="text/yaml")
    except FileNotFoundError:
        raise HTTPException(404, "OpenAPI spec not found")


class InternalSummonRequest(BaseModel):
    """Pydantic model for cross-brain communication."""
    message: str = Field(..., min_length=1, max_length=2000)
    source: str = Field(..., pattern=r"^(edge_resonance|edge_fallback)$")


def _verify_hmac(request: Request, body_bytes: bytes) -> None:
    """Verify HMAC-SHA256 signature from Edge Brain."""
    if not _HMAC_SECRET:
        internal_token = os.getenv("EDGE_INTERNAL_TOKEN", "")
        if not internal_token:
            raise HTTPException(503, "Internal endpoint not configured")
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {internal_token}":
            raise HTTPException(403, "Not authorized for internal endpoint")
        return

    timestamp_str = request.headers.get("X-Nate-Timestamp", "0")
    nonce = request.headers.get("X-Nate-Nonce", "")
    signature = request.headers.get("X-Nate-Signature", "")

    if not timestamp_str or not nonce or not signature:
        raise HTTPException(403, "Missing HMAC headers")

    try:
        timestamp = int(timestamp_str)
    except ValueError:
        raise HTTPException(403, "Invalid timestamp")

    if abs(time.time() - timestamp) > _HMAC_MAX_AGE:
        raise HTTPException(403, "Request expired")

    payload = f"{timestamp}.{nonce}.{body_bytes.decode()}"
    expected = hmac.new(_HMAC_SECRET, payload.encode(), hashlib.sha256).digest()
    try:
        provided = base64.b64decode(signature)
    except Exception:
        raise HTTPException(403, "Invalid signature encoding")

    if not hmac.compare_digest(provided, expected):
        raise HTTPException(403, "Invalid signature")


def _sanitize_input(text: str) -> str:
    """Strip injection vectors from inbound message."""
    text = html.escape(text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    return text[:2000]


def _sanitize_outbound(text: str) -> str:
    """Validate sovereign response before returning to Edge Brain."""
    if not text or not isinstance(text, str):
        return ""
    if len(text) > 10000:
        text = text[:10000]
    for p in _POISON_PATTERNS:
        if p.search(text):
            logger.warning("Sovereign outbound response failed poison check: %s", p.pattern)
            return ""
    return text


async def _check_internal_rate_limit(ip: str, request: Request) -> bool:
    """Per-IP rate limit for the internal endpoint via Redis (multi-worker safe)."""
    redis_client = getattr(request.app.state, "redis_client", None)
    if redis_client:
        try:
            key = f"nate:rate:summon_int:{ip}"
            count = await redis_client.incr(key)
            if count == 1:
                await redis_client.expire(key, INTERNAL_BURST_WINDOW)
            return count <= INTERNAL_BURST_LIMIT
        except Exception:
            pass
    now = time.time()
    window = [t for t in _fallback_internal_rate[ip] if now - t < INTERNAL_BURST_WINDOW]
    _fallback_internal_rate[ip] = window
    if len(window) >= INTERNAL_BURST_LIMIT:
        return False
    _fallback_internal_rate[ip].append(now)
    return True


@router.post("/internal")
async def summon_internal(request: Request):
    """Edge Worker calls this for dual-brain resonance comparison.
    Hardened with HMAC verification, input sanitization, EndpointShield,
    Edge Mirror Shell, and response validation."""

    body_bytes = await request.body()
    _verify_hmac(request, body_bytes)

    client_ip = request.client.host if request.client else "edge"
    if not await _check_internal_rate_limit(client_ip, request):
        raise HTTPException(429, "Internal rate limit exceeded")

    # Edge Mirror Shell assessment
    edge_mirror = getattr(request.app.state, "edge_mirror_shell", None)
    if edge_mirror:
        try:
            from app.services.security.edge_mirror_shell import SignalSource
            assessment = edge_mirror.assess_signal(
                source=SignalSource.CLOUDFLARE_WORKER,
                payload={"body_length": len(body_bytes), "ip": client_ip},
                identity=client_ip,
            )
            from app.services.security.edge_mirror_shell import MirrorVerdict
            if assessment.get("verdict") == MirrorVerdict.MIRROR:
                return {"response": "I sense this needs more reflection.", "source": "mirror_shell"}
            elif assessment.get("verdict") == MirrorVerdict.REJECT:
                raise HTTPException(403, "Request rejected by coherence layer")
        except HTTPException:
            raise
        except Exception as ems_err:
            logger.warning("EdgeMirrorShell assessment error (allowing): %s", ems_err)

    # SASE inbound evaluation
    hive_v4 = getattr(request.app.state, "hive_v4", {})
    sase = hive_v4.get("sase_controller") if isinstance(hive_v4, dict) else None
    if sase:
        try:
            sase_verdict = await sase.evaluate_request(
                source_ip=client_ip,
                path="/api/summon/internal",
                method="POST",
                content_length=len(body_bytes),
            )
            if not sase_verdict.allowed:
                logger.warning("SASE blocked internal summon from %s: %s", client_ip, sase_verdict.reason)
                raise HTTPException(403, "Request denied by SASE policy")
        except HTTPException:
            raise
        except Exception as sase_err:
            logger.warning("SASE evaluation error (allowing): %s", sase_err)

    try:
        import json
        body_dict = json.loads(body_bytes)
        req = InternalSummonRequest(**body_dict)
    except Exception:
        raise HTTPException(400, "Invalid request body")

    clean_message = _sanitize_input(req.message)

    # EndpointShield inbound scan
    endpoint_shield = getattr(request.app.state, "endpoint_shield", None)
    if endpoint_shield:
        try:
            verdict = await endpoint_shield.evaluate_payload(
                user_id="edge_worker",
                payload=clean_message,
                direction="inbound",
            )
            if not verdict.safe:
                logger.warning("EndpointShield blocked internal summon: %s", verdict.details)
                raise HTTPException(403, "Payload rejected by endpoint shield")
        except HTTPException:
            raise
        except Exception as es_err:
            logger.warning("EndpointShield evaluation error (allowing): %s", es_err)

    summon_service = getattr(request.app.state, "nate_summon_service", None)
    if not summon_service:
        raise HTTPException(503, "Summon service unavailable")

    response = await summon_service._generate_response(clean_message, max_tokens=1000)
    response = _sanitize_outbound(response)

    if not response:
        response = "I need a moment to gather my thoughts."

    # EndpointShield outbound scan
    if endpoint_shield:
        try:
            sanitized, blocked_urls = endpoint_shield.sanitize_ai_response(response)
            if blocked_urls:
                logger.warning("EndpointShield removed %d URLs from internal response", len(blocked_urls))
            response = sanitized
        except Exception:
            pass

    return {"response": response, "source": "sovereign_brain"}


async def _require_auth(request: Request) -> dict:
    """Extract authenticated user from request. Tries bridge token via Redis."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Authentication required")

    token = auth_header[7:].strip()
    user = await _try_bridge_token(request, token)
    if not user:
        raise HTTPException(401, "Invalid or expired token")
    return user


async def _try_bridge_token(request: Request, token: str) -> Optional[dict]:
    """Validate a bridge token via the api_server get_current_user pattern."""
    try:
        from app.services.api_server import get_current_user as _get_user
        from unittest.mock import AsyncMock

        mock_request = type("R", (), {"headers": {"Authorization": f"Bearer {token}"}})()
        user = await _get_user(mock_request)
        if isinstance(user, dict) and user.get("username"):
            return user
    except Exception:
        pass

    redis_client = getattr(request.app.state, "redis_client", None)
    if redis_client:
        try:
            import os
            env = os.getenv("ENVIRONMENT", "development")
            key = f"nate:{env}:auth:{token}"
            data = await redis_client.get(key)
            if data:
                import json
                profile = json.loads(data) if isinstance(data, str) else data
                if isinstance(profile, dict):
                    return profile
        except Exception:
            pass

    return None
