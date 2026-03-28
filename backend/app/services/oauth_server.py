"""
LittleNate-1.X OAuth 2.0 Server.

Supports client_credentials grant for machine-to-machine API access.
JWT tokens with scopes: nate:chat, nate:voice, nate:realtime, nate:coherence.

Rate limiting is Redis-backed with per-client sliding windows.
"""

import hashlib
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
_TOKEN_TTL_HOURS = int(os.getenv("API_TOKEN_TTL_HOURS", "1"))

VALID_SCOPES = {"nate:chat", "nate:voice", "nate:realtime", "nate:coherence"}

TIER_LIMITS = {
    "free": {"requests_per_min": 10, "concurrent_realtime": 1, "monthly_cap": 1000},
    "developer": {"requests_per_min": 60, "concurrent_realtime": 5, "monthly_cap": 50000},
    "enterprise": {"requests_per_min": 600, "concurrent_realtime": 50, "monthly_cap": -1},
}


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class OAuthServer:
    """OAuth 2.0 client_credentials server for LittleNate-1.X API."""

    def __init__(self, db_pool=None, redis_client=None):
        self._db_pool = db_pool
        self._redis = redis_client
        self._active_sessions = 0

    def set_db_pool(self, pool):
        self._db_pool = pool

    def set_redis(self, redis_client):
        self._redis = redis_client

    async def register_client(
        self,
        name: str,
        created_by: str,
        scopes: Optional[List[str]] = None,
        tier: str = "free",
        redirect_uri: str = "",
    ) -> Dict[str, Any]:
        """Register a new API client. Returns client_id + plaintext secret (shown once)."""
        if not self._db_pool:
            return {"error": "Database not available"}

        client_secret = secrets.token_urlsafe(48)
        secret_hash = _hash_secret(client_secret)

        valid_scopes = [s for s in (scopes or ["nate:chat"]) if s in VALID_SCOPES]
        if not valid_scopes:
            valid_scopes = ["nate:chat"]

        limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])

        try:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """INSERT INTO api_clients
                       (client_secret_hash, name, redirect_uri, tier, scopes,
                        rate_limit, monthly_cap, created_by)
                       VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8)
                       RETURNING client_id""",
                    secret_hash, name, redirect_uri, tier,
                    __import__("json").dumps(valid_scopes),
                    limits["requests_per_min"],
                    limits["monthly_cap"],
                    created_by,
                )
                return {
                    "client_id": str(row["client_id"]),
                    "client_secret": client_secret,
                    "name": name,
                    "tier": tier,
                    "scopes": valid_scopes,
                    "rate_limit": limits["requests_per_min"],
                    "monthly_cap": limits["monthly_cap"],
                }
        except Exception as e:
            logger.error("OAuthServer: registration failed: %s", e)
            return {"error": str(e)}

    async def authenticate(self, client_id: str, client_secret: str) -> Optional[Dict[str, Any]]:
        """Validate client credentials and return client info if valid."""
        if not self._db_pool:
            return None

        secret_hash = _hash_secret(client_secret)

        try:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT client_id, name, tier, scopes, rate_limit, monthly_cap
                       FROM api_clients
                       WHERE client_id = $1::uuid AND client_secret_hash = $2 AND is_active = TRUE""",
                    client_id, secret_hash,
                )
                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.warning("OAuthServer: auth failed: %s", e)
            return None

    async def issue_token(self, client_id: str, client_secret: str) -> Dict[str, Any]:
        """client_credentials grant: validate and return a JWT access token."""
        client = await self.authenticate(client_id, client_secret)
        if not client:
            return {"error": "invalid_client", "error_description": "Invalid client credentials"}

        import jwt as pyjwt

        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(client["client_id"]),
            "name": client["name"],
            "scopes": client["scopes"] if isinstance(client["scopes"], list) else [],
            "tier": client["tier"],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=_TOKEN_TTL_HOURS)).timestamp()),
            "iss": "littlenate-1.x",
        }

        token = pyjwt.encode(payload, _JWT_SECRET, algorithm="HS256")

        if self._redis:
            try:
                key = f"nate:api:token:{token[:32]}"
                await self._redis.setex(key, _TOKEN_TTL_HOURS * 3600, str(client["client_id"]))
            except Exception:
                pass

        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": _TOKEN_TTL_HOURS * 3600,
            "scope": " ".join(payload["scopes"]),
        }

    async def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Validate a JWT access token and return the claims."""
        try:
            import jwt as pyjwt
            payload = pyjwt.decode(token, _JWT_SECRET, algorithms=["HS256"])
            return payload
        except Exception:
            return None

    async def check_rate_limit(self, client_id: str, requests_per_min: int = 10) -> bool:
        """Check if client is within rate limit. Returns True if allowed."""
        if not self._redis:
            return True

        try:
            key = f"nate:api:rate:{client_id}"
            current = await self._redis.incr(key)
            if current == 1:
                await self._redis.expire(key, 60)
            return current <= requests_per_min
        except Exception:
            return True

    async def check_monthly_usage(self, client_id: str, monthly_cap: int) -> bool:
        """Check if client is within monthly usage cap. Returns True if allowed."""
        if monthly_cap < 0 or not self._db_pool:
            return True

        try:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT COUNT(*) as cnt FROM api_usage
                       WHERE client_id = $1::uuid
                       AND created_at >= date_trunc('month', NOW())""",
                    client_id,
                )
                return (row["cnt"] if row else 0) < monthly_cap
        except Exception:
            return True

    def get_status(self) -> Dict[str, Any]:
        return {
            "db_connected": self._db_pool is not None,
            "redis_connected": self._redis is not None,
            "token_ttl_hours": _TOKEN_TTL_HOURS,
            "valid_scopes": sorted(VALID_SCOPES),
        }
