"""xAI Management API — prepaid credit balance (read-only).

Requires a Management Key (console.x.ai → Settings → Management Keys),
distinct from inference keys (XAI_API_KEY / XAI_SSE_KEY).

# QUANTUM-CRYSTAL-ARCH — provider credit visibility
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import aiohttp

logger = logging.getLogger("nate.xai_billing")

_MGMT_BASE = "https://management-api.x.ai"


def _mgmt_key() -> str:
    return (
        os.getenv("XAI_MANAGEMENT_KEY", "").strip()
        or os.getenv("XAI_MGMT_KEY", "").strip()
    )


def _team_id() -> str:
    return os.getenv("XAI_TEAM_ID", "").strip()


def billing_configured() -> bool:
    return bool(_mgmt_key() and _team_id())


def _cents_to_usd(val: Any) -> Optional[float]:
    """xAI prepaid total.val is USD cents; negative means remaining credit."""
    if val is None:
        return None
    try:
        cents = int(str(val).strip())
    except (TypeError, ValueError):
        return None
    # Remaining credit is negative in the ledger; spend is positive.
    return abs(cents) / 100.0


async def fetch_prepaid_balance() -> Dict[str, Any]:
    """Return prepaid balance summary for the configured xAI team.

    Shape:
      ok, configured, balance_usd, total_cents_raw, team_id, error?, changes_sample?
    """
    key = _mgmt_key()
    team = _team_id()
    if not key or not team:
        return {
            "ok": False,
            "configured": False,
            "balance_usd": None,
            "total_cents_raw": None,
            "team_id": team or None,
            "error": "XAI_MANAGEMENT_KEY and XAI_TEAM_ID required",
        }

    url = f"{_MGMT_BASE}/v1/billing/teams/{team}/prepaid/balance"
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                body = await resp.text()
                if resp.status != 200:
                    logger.warning("xAI prepaid balance %s: %s", resp.status, body[:240])
                    return {
                        "ok": False,
                        "configured": True,
                        "balance_usd": None,
                        "total_cents_raw": None,
                        "team_id": team,
                        "error": f"HTTP {resp.status}: {body[:240]}",
                    }
                import json

                data = json.loads(body) if body else {}
    except Exception as e:
        logger.warning("xAI prepaid balance request failed: %s", e)
        return {
            "ok": False,
            "configured": True,
            "balance_usd": None,
            "total_cents_raw": None,
            "team_id": team,
            "error": str(e)[:240],
        }

    total = data.get("total") or {}
    raw = total.get("val") if isinstance(total, dict) else None
    balance_usd = _cents_to_usd(raw)
    changes = data.get("changes") or []
    sample = []
    for ch in changes[:5]:
        if not isinstance(ch, dict):
            continue
        amt = (ch.get("amount") or {}).get("val")
        sample.append(
            {
                "origin": ch.get("changeOrigin"),
                "amount_usd": _cents_to_usd(amt),
                "at": ch.get("createTs") or ch.get("createTime"),
            }
        )

    return {
        "ok": True,
        "configured": True,
        "balance_usd": balance_usd,
        "total_cents_raw": str(raw) if raw is not None else None,
        "team_id": team,
        "changes_sample": sample,
        "provider": "xai",
    }
