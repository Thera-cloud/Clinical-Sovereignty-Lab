"""
Authentication dependency for FastAPI endpoints.

Extracts and validates the user from JWT token or session.
Falls back to user_id query param ONLY in development mode with a warning log.
All auth attempts (success/failure) are logged to audit trail (Hive Defense v4.3).
"""

import asyncio
import os
import logging
import time
from typing import Optional
from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

ENVIRONMENT = os.getenv("ENVIRONMENT", "production")  # Default to production for safety
JWT_SECRET = os.getenv("JWT_SECRET", "")


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
    except Exception:
        pass


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
        logger.debug("Auth audit write failed (non-fatal): %s", exc)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    user_id: Optional[str] = Query(None, alias="user_id"),
) -> str:
    """Extract authenticated user_id.

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
                _log_auth_attempt(request, str(uid), "jwt_bearer", True)
                return str(uid)
        except Exception as e:
            _log_auth_attempt(request, "", "jwt_bearer", False, reason=str(e)[:100])
            logger.warning("JWT decode failed: %s", e)
            # Don't raise yet — try other methods

    # 2. Try X-User-Id header (for internal service-to-service calls)
    header_user_id = request.headers.get("X-User-Id")
    if header_user_id:
        _log_auth_attempt(request, str(header_user_id).strip(), "x_user_id_header", True)
        return str(header_user_id).strip()

    # 3. Fallback: user_id query param (development only, localhost only)
    if user_id:
        is_dev = ENVIRONMENT.lower() in ("development", "dev", "local")
        is_localhost = request.client and request.client.host in ("127.0.0.1", "::1", "localhost")
        if not (is_dev and is_localhost):
            _log_auth_attempt(request, str(user_id), "query_param", False, reason="non_dev_non_localhost")
            logger.error("user_id query param auth attempt rejected (env=%s, host=%s)",
                         ENVIRONMENT, request.client.host if request.client else "unknown")
            raise HTTPException(
                status_code=401,
                detail="Authentication required. user_id query param not accepted."
            )
        _log_auth_attempt(request, str(user_id).strip(), "query_param_dev", True)
        logger.warning("DEV MODE: user_id query param used for auth (localhost only)")
        return str(user_id).strip()

    _log_auth_attempt(request, "", "none", False, reason="no_credentials_provided")
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Provide Bearer token or X-User-Id header."
    )
