"""
Serverless Fallback Service — Cloudflare Workers AI / D1 / KV degraded-mode operation.

When the VPS is down or Azure is unreachable, this service routes through
Cloudflare's serverless stack to maintain Nate's presence:
  - Workers AI for inference (LLM fallback)
  - D1 for lightweight SQL storage (auth tokens, session stubs)
  - KV for fast key-value operations (rate limits, feature flags)

Per quantum-presence-sustainability.mdc: "Every new feature must answer:
where does this live when the VPS is off?"
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID", "")
_CF_API_TOKEN = os.getenv("CF_API_TOKEN", "")
_D1_DATABASE_ID = os.getenv("D1_DATABASE_ID", "")
_KV_NAMESPACE_ID = os.getenv("KV_NAMESPACE_ID", "")
_WORKERS_AI_URL = os.getenv("WORKERS_AI_URL", "")
_WORKERS_AI_TOKEN = os.getenv("WORKERS_AI_TOKEN", "")

WORKERS_AI_MODEL = "@cf/meta/llama-3.1-8b-instruct"


class ServerlessFallback:
    """Provides degraded-mode operation when the VPS or Azure is unreachable."""

    def __init__(self, db_pool=None):
        self._db_pool = db_pool
        self._last_health_check: Dict[str, Any] = {}
        self._health_cache_ttl = 60

    def is_configured(self) -> bool:
        return bool(_CF_ACCOUNT_ID and _CF_API_TOKEN)

    def _workers_ai_configured(self) -> bool:
        if _WORKERS_AI_URL and _WORKERS_AI_TOKEN:
            return True
        return bool(_CF_ACCOUNT_ID and _CF_API_TOKEN)

    def _d1_configured(self) -> bool:
        return bool(_CF_ACCOUNT_ID and _CF_API_TOKEN and _D1_DATABASE_ID)

    def _kv_configured(self) -> bool:
        return bool(_CF_ACCOUNT_ID and _CF_API_TOKEN and _KV_NAMESPACE_ID)

    async def check_health(self) -> Dict[str, Any]:
        """Check if serverless backends are reachable. Caches result for 60s."""
        now = time.time()
        cached = self._last_health_check
        if cached and now - cached.get("checked_at", 0) < self._health_cache_ttl:
            return cached

        health: Dict[str, Any] = {
            "checked_at": now,
            "configured": self.is_configured(),
            "workers_ai": {"configured": self._workers_ai_configured(), "healthy": False},
            "d1": {"configured": self._d1_configured(), "healthy": False},
            "kv": {"configured": self._kv_configured(), "healthy": False},
        }

        if not self.is_configured():
            self._last_health_check = health
            return health

        import httpx

        headers = {
            "Authorization": f"Bearer {_CF_API_TOKEN}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Workers AI health
            if self._workers_ai_configured():
                try:
                    url = _WORKERS_AI_URL or (
                        f"https://api.cloudflare.com/client/v4/accounts/"
                        f"{_CF_ACCOUNT_ID}/ai/run/{WORKERS_AI_MODEL}"
                    )
                    token = _WORKERS_AI_TOKEN or _CF_API_TOKEN
                    resp = await client.post(
                        url,
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json={"messages": [{"role": "user", "content": "ping"}], "max_tokens": 5},
                    )
                    health["workers_ai"]["healthy"] = resp.status_code in (200, 400)
                    health["workers_ai"]["status_code"] = resp.status_code
                except Exception as e:
                    health["workers_ai"]["error"] = str(e)

            # D1 health
            if self._d1_configured():
                try:
                    resp = await client.post(
                        f"https://api.cloudflare.com/client/v4/accounts/"
                        f"{_CF_ACCOUNT_ID}/d1/database/{_D1_DATABASE_ID}/query",
                        headers=headers,
                        json={"sql": "SELECT 1 as ok"},
                    )
                    health["d1"]["healthy"] = resp.status_code == 200
                    health["d1"]["status_code"] = resp.status_code
                except Exception as e:
                    health["d1"]["error"] = str(e)

            # KV health
            if self._kv_configured():
                try:
                    resp = await client.get(
                        f"https://api.cloudflare.com/client/v4/accounts/"
                        f"{_CF_ACCOUNT_ID}/storage/kv/namespaces/{_KV_NAMESPACE_ID}/keys",
                        headers=headers,
                        params={"limit": 1},
                    )
                    health["kv"]["healthy"] = resp.status_code == 200
                    health["kv"]["status_code"] = resp.status_code
                except Exception as e:
                    health["kv"]["error"] = str(e)

        self._last_health_check = health
        return health

    # ── Workers AI (LLM Fallback) ──

    async def generate_fallback(
        self,
        prompt: str,
        context: Optional[str] = None,
        max_tokens: int = 400,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a response via Cloudflare Workers AI when Azure is unreachable."""
        if not self._workers_ai_configured():
            return {
                "text": "I'm temporarily in quiet mode — my full capabilities will return shortly.",
                "provider": "fallback_static",
                "success": False,
            }

        import httpx

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        elif context:
            messages.append({"role": "system", "content": f"Context: {context[:1000]}"})
        messages.append({"role": "user", "content": prompt[:2000]})

        url = _WORKERS_AI_URL or (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{_CF_ACCOUNT_ID}/ai/run/{WORKERS_AI_MODEL}"
        )
        token = _WORKERS_AI_TOKEN or _CF_API_TOKEN

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"messages": messages, "max_tokens": max_tokens},
                )
                resp.raise_for_status()
                data = resp.json()

            result_text = ""
            if "result" in data and isinstance(data["result"], dict):
                result_text = data["result"].get("response", "")
            elif "choices" in data:
                result_text = data["choices"][0]["message"]["content"]

            return {
                "text": result_text.strip() if result_text else "",
                "provider": "workers_ai",
                "model": WORKERS_AI_MODEL,
                "success": bool(result_text),
            }
        except Exception as e:
            logger.warning("ServerlessFallback: Workers AI generation failed: %s", e)
            return {
                "text": "I'm temporarily in quiet mode — my full capabilities will return shortly.",
                "provider": "fallback_static",
                "success": False,
                "error": str(e),
            }

    # ── D1 (SQL Fallback Storage) ──

    async def d1_query(self, sql: str, params: Optional[List] = None) -> List[Dict]:
        """Execute a SQL query against Cloudflare D1."""
        if not self._d1_configured():
            logger.warning("ServerlessFallback: D1 not configured")
            return []

        import httpx

        body: Dict[str, Any] = {"sql": sql}
        if params:
            body["params"] = params

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"https://api.cloudflare.com/client/v4/accounts/"
                    f"{_CF_ACCOUNT_ID}/d1/database/{_D1_DATABASE_ID}/query",
                    headers={
                        "Authorization": f"Bearer {_CF_API_TOKEN}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()

            results = data.get("result", [])
            if results and isinstance(results, list) and "results" in results[0]:
                return results[0]["results"]
            return []
        except Exception as e:
            logger.warning("ServerlessFallback: D1 query failed: %s", e)
            return []

    async def d1_execute(self, sql: str, params: Optional[List] = None) -> bool:
        """Execute a write statement against D1. Returns True on success."""
        result = await self.d1_query(sql, params)
        return result is not None

    # ── KV (Key-Value Operations) ──

    async def store_kv(self, key: str, value: str, ttl_seconds: Optional[int] = None) -> bool:
        """Store a value in Cloudflare KV."""
        if not self._kv_configured():
            logger.warning("ServerlessFallback: KV not configured")
            return False

        import httpx

        url = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{_CF_ACCOUNT_ID}/storage/kv/namespaces/{_KV_NAMESPACE_ID}/values/{key}"
        )
        params = {}
        if ttl_seconds:
            params["expiration_ttl"] = ttl_seconds

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.put(
                    url,
                    headers={"Authorization": f"Bearer {_CF_API_TOKEN}"},
                    params=params if params else None,
                    content=value,
                )
                return resp.status_code == 200
        except Exception as e:
            logger.warning("ServerlessFallback: KV store failed: %s", e)
            return False

    async def get_kv(self, key: str) -> Optional[str]:
        """Retrieve a value from Cloudflare KV."""
        if not self._kv_configured():
            return None

        import httpx

        url = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{_CF_ACCOUNT_ID}/storage/kv/namespaces/{_KV_NAMESPACE_ID}/values/{key}"
        )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {_CF_API_TOKEN}"},
                )
                if resp.status_code == 200:
                    return resp.text
                return None
        except Exception as e:
            logger.warning("ServerlessFallback: KV get failed: %s", e)
            return None

    async def delete_kv(self, key: str) -> bool:
        """Delete a key from Cloudflare KV."""
        if not self._kv_configured():
            return False

        import httpx

        url = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{_CF_ACCOUNT_ID}/storage/kv/namespaces/{_KV_NAMESPACE_ID}/values/{key}"
        )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.delete(
                    url,
                    headers={"Authorization": f"Bearer {_CF_API_TOKEN}"},
                )
                return resp.status_code == 200
        except Exception as e:
            logger.warning("ServerlessFallback: KV delete failed: %s", e)
            return False

    # ── Degraded Mode Orchestration ──

    async def store_session_stub(self, session_id: str, user_id: str, summary: str) -> bool:
        """Store a minimal session record in D1 when PostgreSQL is unreachable."""
        return await self.d1_execute(
            "INSERT INTO session_stubs (session_id, user_id, summary, created_at) "
            "VALUES (?, ?, ?, datetime('now')) ON CONFLICT (session_id) DO NOTHING",
            [session_id, user_id, summary[:2000]],
        )

    async def store_auth_token_fallback(self, token: str, user_data: str, ttl: int = 3600) -> bool:
        """Store an auth token in KV when Redis is unreachable."""
        return await self.store_kv(f"auth:{token}", user_data, ttl_seconds=ttl)

    async def validate_auth_token_fallback(self, token: str) -> Optional[Dict]:
        """Validate an auth token from KV fallback."""
        data = await self.get_kv(f"auth:{token}")
        if data:
            try:
                return json.loads(data)
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    def get_status(self) -> Dict[str, Any]:
        return {
            "configured": self.is_configured(),
            "workers_ai": self._workers_ai_configured(),
            "d1": self._d1_configured(),
            "kv": self._kv_configured(),
            "last_health_check": self._last_health_check or None,
        }
