"""Thin Instantly API client (Phase 1 scaffold — health + campaign stubs).

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("nate.growth.instantly")

INSTANTLY_API_BASE = os.getenv(
    "INSTANTLY_API_BASE", "https://api.instantly.ai/api/v2"
).rstrip("/")


class InstantlyClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = (api_key or os.getenv("INSTANTLY_API_KEY") or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def health(self) -> Dict[str, Any]:
        if not self.configured:
            return {"status": "unconfigured", "ok": False}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{INSTANTLY_API_BASE}/campaigns",
                    headers=self._headers(),
                    params={"limit": 1},
                )
            if resp.status_code in (200, 401, 403):
                # 401/403 prove reachability but bad/missing perms
                ok = resp.status_code == 200
                return {
                    "status": "ok" if ok else "auth_error",
                    "ok": ok,
                    "http_status": resp.status_code,
                }
            return {
                "status": "error",
                "ok": False,
                "http_status": resp.status_code,
                "body": (resp.text or "")[:200],
            }
        except Exception as e:
            logger.warning("Instantly health failed: %s", e)
            return {"status": "error", "ok": False, "error": str(e)[:200]}

    async def create_campaign_stub(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Phase 3 will expand; Phase 1 only validates config."""
        if not self.configured:
            return {"ok": False, "error": "INSTANTLY_API_KEY not set"}
        return {
            "ok": False,
            "error": "campaign push deferred to Phase 3",
            "payload_keys": list(payload.keys())[:12],
        }
