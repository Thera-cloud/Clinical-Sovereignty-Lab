"""Instantly API v2 client — health, verify, create campaign, add leads.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

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

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "INSTANTLY_API_KEY not set", "degraded": True}
        url = f"{INSTANTLY_API_BASE}{path}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.request(
                    method,
                    url,
                    headers=self._headers(),
                    json=json_body,
                    params=params,
                )
            body: Any
            try:
                body = resp.json()
            except Exception:
                body = {"raw": (resp.text or "")[:500]}
            ok = 200 <= resp.status_code < 300
            return {
                "ok": ok,
                "http_status": resp.status_code,
                "data": body,
                "error": None if ok else str(body)[:300],
            }
        except Exception as e:
            logger.warning("Instantly %s %s failed: %s", method, path, e)
            return {"ok": False, "error": str(e)[:200], "degraded": True}

    async def health(self) -> Dict[str, Any]:
        if not self.configured:
            return {"status": "unconfigured", "ok": False, "degraded": True}
        result = await self._request("GET", "/campaigns", params={"limit": 1})
        if result.get("ok"):
            return {"status": "ok", "ok": True, "http_status": result.get("http_status")}
        if result.get("http_status") in (401, 403):
            return {
                "status": "auth_error",
                "ok": False,
                "http_status": result.get("http_status"),
            }
        return {
            "status": "error",
            "ok": False,
            "http_status": result.get("http_status"),
            "error": result.get("error"),
            "degraded": True,
        }

    async def verify_email(self, email: str) -> Dict[str, Any]:
        return await self._request(
            "POST", "/email-verification", json_body={"email": email}
        )

    async def create_campaign(
        self,
        *,
        name: str,
        sequence_steps: Optional[List[Dict[str, Any]]] = None,
        daily_limit: int = 30,
    ) -> Dict[str, Any]:
        """Create a campaign. Sequence shape follows Instantly v2 campaign schema."""
        payload: Dict[str, Any] = {
            "name": name[:120],
            "campaign_schedule": {
                "schedules": [
                    {
                        "name": "Weekdays",
                        "timing": {"from": "09:00", "to": "17:00"},
                        "days": {
                            "0": False,
                            "1": True,
                            "2": True,
                            "3": True,
                            "4": True,
                            "5": True,
                            "6": False,
                        },
                        "timezone": "America/New_York",
                    }
                ]
            },
            "daily_limit": max(1, min(int(daily_limit), 100)),
        }
        if sequence_steps:
            payload["sequences"] = [{"steps": sequence_steps}]
        return await self._request("POST", "/campaigns", json_body=payload)

    async def add_lead(
        self,
        *,
        email: str,
        campaign_id: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        company_name: Optional[str] = None,
        personalization: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "email": email,
            "campaign": campaign_id,
        }
        if first_name:
            body["first_name"] = first_name
        if last_name:
            body["last_name"] = last_name
        if company_name:
            body["company_name"] = company_name
        if personalization:
            body["personalization"] = personalization[:2000]
        return await self._request("POST", "/leads", json_body=body)

    async def activate_campaign(self, campaign_id: str) -> Dict[str, Any]:
        return await self._request("POST", f"/campaigns/{campaign_id}/activate")

    async def pause_campaign(self, campaign_id: str) -> Dict[str, Any]:
        return await self._request("POST", f"/campaigns/{campaign_id}/pause")
