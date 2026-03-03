"""
Authentication dependency for FastAPI endpoints.

Extracts and validates the user from JWT token or session.
Falls back to bridge token via Redis, then to user_id query param (dev only).
All auth attempts (success/failure) are logged to audit trail (Hive Defense v4.3).
"""

import asyncio
import json
import os
import logging
import time
from typing import Optional
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

ENVIRONMENT = os.getenv("ENVIRONMENT", "production")  # Default to production for safety
JWT_SECRET = os.getenv("JWT_SECRET", "")

_BRIDGE_TOKEN_PREFIX = os.getenv("REDIS_KEY_PREFIX", "nate")
_BRIDGE_TOKEN_ENV = os.getenv("ENVIRONMENT", "prod")


def _log_auth_attempt(request: Request, user_id: str, method: str, success: bool, reason: str = "") -> None:
    """
    Non-blocking audit log for every authentication attempt.
    Writes to the audit_log table via the app's db_pool.
    """
    ip = request.client.host if request.client else "unknown"
    endpoint = request.url.path

    if success:
        logger.info("AUTH OK: user=%s method=%s ip=%s path=%s", user_id[:12] if user_id else "?", method, ip, endpoint)
    else:
        logger.warning("AUTH FAIL: method=%s ip=%s path=%s reason=%s", method, ip, endpoint, reason)

    try:
        db_pool = getattr(request.app.state, "db_pool", None)
        if db_pool:
            asyncio.ensure_future(_write_auth_audit(db_pool, user_id, method, success, ip, endpoint, reason))
    except Exception as e:
        logger.warning("Auth audit dispatch failed: %s", e)


async def _write_auth_audit(
    db_pool, user_id: str, method: str, success: bool,
    ip: str, endpoint: str, reason: str,
) -> None:
    """Persist auth attempt to audit_log table."""
    try:
        await db_pool.execute(
            """INSERT INTO audit_log
               (event_type, user_id, ip_address, endpoint, success, detail, created_at)
               VALUES ('auth_attempt', $1, $2, $3, $4, $5, NOW())""",
            user_id or "unknown", ip, endpoint, success,
            f"method={method}" + (f" reason={reason}" if reason else ""),
        )
    except Exception as exc:
        logger.warning("Auth audit write failed (non-fatal): %s", exc)


async def get_current_user_id(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """Extract authenticated user_id (returns str, not Dict).

    For the Dict-returning variant used by require_admin/require_coach,
    see app.services.api_server.get_current_user.

    Priority:
    1. JWT Bearer token (production)
    2. X-User-Id header (internal service calls)
    3. user_id query param (development only — logged as warning)

    Raises HTTPException 401 if no valid identity found.
    """
    # 1. Try Bearer token
    if credentials and credentials.credentials:
        try:
            import jwt  # PyJWT — replaces abandoned python-jose
            payload = jwt.decode(
                credentials.credentials,
                JWT_SECRET,
                algorithms=["HS256"]
            )
            uid = payload.get("user_id") or payload.get("sub")
            if uid:
                request.state.user_id = str(uid)
                _log_auth_attempt(request, str(uid), "jwt_bearer", True)
                return str(uid)
        except Exception as e:
            _log_auth_attempt(request, "", "jwt_bearer", False, reason=str(e)[:100])
            logger.warning("JWT decode failed, trying bridge token: %s", e)

        # 1b. Try bridge session token via Redis
        if credentials and credentials.credentials:
            try:
                redis_client = getattr(request.app.state, "_auth_redis", None)
                if redis_client is None:
                    import redis as _sync_redis
                    from app.config import settings
                    redis_url = settings.redis_url
                    redis_pw = os.getenv("REDIS_PASSWORD")
                    _r = _sync_redis.Redis.from_url(
                        redis_url, password=redis_pw, socket_timeout=2, decode_responses=True
                    )
                    _r.ping()
                    request.app.state._auth_redis = _r
                    redis_client = _r

                token_key = f"{_BRIDGE_TOKEN_PREFIX}:{_BRIDGE_TOKEN_ENV}:auth:{credentials.credentials}"
                raw = redis_client.get(token_key)
                if raw:
                    profile = json.loads(raw) if isinstance(raw, str) else raw
                    uid = profile.get("hardware_id") or profile.get("name") or "bridge_user"
                    request.state.user_id = str(uid)
                    request.state.user_role = profile.get("role", "")
                    _log_auth_attempt(request, str(uid), "bridge_token", True)
                    return str(uid)
            except Exception as bt_err:
                logger.warning("Bridge token Redis check failed (non-fatal): %s", bt_err)

    # 2. Try X-User-Id header (for internal service-to-service calls)
    header_user_id = request.headers.get("X-User-Id")
    if header_user_id:
        request.state.user_id = str(header_user_id).strip()
        _log_auth_attempt(request, str(header_user_id).strip(), "x_user_id_header", True)
        return str(header_user_id).strip()

    # 3. Fallback: user_id query param (development only, localhost only)
    #    Read from request.query_params to avoid conflicting with {user_id} path params
    query_user_id = request.query_params.get("user_id")
    if query_user_id:
        is_dev = ENVIRONMENT.lower() in ("development", "dev", "local")
        is_localhost = request.client and request.client.host in ("127.0.0.1", "::1", "localhost")
        if not (is_dev and is_localhost):
            _log_auth_attempt(request, str(query_user_id), "query_param", False, reason="non_dev_non_localhost")
            logger.error("user_id query param auth attempt rejected (env=%s, host=%s)",
                         ENVIRONMENT, request.client.host if request.client else "unknown")
            raise HTTPException(
                status_code=401,
                detail="Authentication required. user_id query param not accepted."
            )
        request.state.user_id = str(query_user_id).strip()
        _log_auth_attempt(request, str(query_user_id).strip(), "query_param_dev", True)
        logger.warning("DEV MODE: user_id query param used for auth (localhost only)")
        return str(query_user_id).strip()

    _log_auth_attempt(request, "", "none", False, reason="no_credentials_provided")
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Provide Bearer token or X-User-Id header."
    )
