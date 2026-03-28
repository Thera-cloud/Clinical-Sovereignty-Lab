"""
Enterprise API — Key management, metering, and tenant crystal namespaces.

4 SLA tiers: FREE (3/day), STARTER ($29/mo), GROWTH ($199/mo), ENTERPRISE (custom).
API keys are validated at the edge via D1 for sub-ms auth.
Enterprise tenants get isolated Vectorize indexes for their domain knowledge.
"""

import asyncio
import hashlib
import logging
import os
import secrets
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("enterprise_api")

router = APIRouter(prefix="/api/enterprise", tags=["enterprise"])

TIER_CONFIGS = {
    "FREE": {"rate_limit_per_minute": 0, "daily_limit": 3, "price_cents": 0},
    "STARTER": {"rate_limit_per_minute": 60, "daily_limit": 10000, "price_cents": 2900},
    "GROWTH": {"rate_limit_per_minute": 300, "daily_limit": 100000, "price_cents": 19900},
    "ENTERPRISE": {"rate_limit_per_minute": 1000, "daily_limit": 1000000, "price_cents": 0},
}

# Moat-aligned overlay (commercial messaging while preserving legacy tiers).
MOAT_CATALOG = {
    "BASE": {
        "price_range_monthly_usd": [29, 49],
        "description": "Stateless chat, core usage class only.",
        "includes": [
            "stateless_chat",
            "core_depth_class",
        ],
    },
    "INTELLIGENCE": {
        "price_range_monthly_usd": [199, 499],
        "description": "Crystal-backed memory, ODPE-optimized routing, C_emo tracking.",
        "includes": [
            "crystal_memory",
            "odpe_routing",
            "c_emo_tracking",
            "deep_noetic_access",
        ],
    },
    "CLINICAL": {
        "price_range_monthly_usd": [999, None],
        "description": "Full Nevedal + Foresight + voice biometrics with compliance controls.",
        "includes": [
            "nevedal_full",
            "foresight_predictions",
            "voice_biometrics",
            "compliance_controls",
        ],
    },
}

LEGACY_TO_MOAT = {
    "FREE": "BASE",
    "STARTER": "BASE",
    "GROWTH": "INTELLIGENCE",
    "ENTERPRISE": "CLINICAL",
}

_db_pool = None


def set_db_pool(pool):
    global _db_pool
    _db_pool = pool


def _generate_api_key() -> str:
    return f"sk_{secrets.token_urlsafe(32)}"


class CreateKeyRequest(BaseModel):
    org_name: str = Field(..., min_length=2, max_length=200)
    tier: str = Field(default="FREE", pattern=r"^(FREE|STARTER|GROWTH|ENTERPRISE)$")
    contact_email: str = Field(default="")
    rate_limit_per_minute: Optional[int] = None
    daily_limit: Optional[int] = None


class UpdateKeyRequest(BaseModel):
    tier: Optional[str] = Field(default=None, pattern=r"^(FREE|STARTER|GROWTH|ENTERPRISE)$")
    rate_limit_per_minute: Optional[int] = None
    daily_limit: Optional[int] = None
    active: Optional[bool] = None


@router.get("/health")
async def enterprise_health():
    return {"status": "ok", "tiers": list(TIER_CONFIGS.keys())}


@router.post("/keys")
async def create_api_key(req: CreateKeyRequest):
    if not _db_pool:
        raise HTTPException(503, "Database unavailable")

    api_key = _generate_api_key()
    tier_config = TIER_CONFIGS.get(req.tier, TIER_CONFIGS["FREE"])
    rate_limit = req.rate_limit_per_minute or tier_config["rate_limit_per_minute"]
    daily_limit = req.daily_limit or tier_config["daily_limit"]

    try:
        async with _db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO api_keys (api_key, org_name, tier, contact_email,
                    rate_limit_per_minute, daily_limit, active)
                VALUES ($1, $2, $3, $4, $5, $6, true)
            """, api_key, req.org_name, req.tier, req.contact_email,
                rate_limit, daily_limit)

        return {
            "api_key": api_key,
            "org_name": req.org_name,
            "tier": req.tier,
            "rate_limit_per_minute": rate_limit,
            "daily_limit": daily_limit,
        }
    except Exception as e:
        logger.warning("Create API key error: %s", e)
        raise HTTPException(500, "Failed to create API key")


@router.get("/keys")
async def list_api_keys():
    if not _db_pool:
        raise HTTPException(503, "Database unavailable")

    try:
        async with _db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, org_name, LEFT(api_key, 10) || '...' as api_key_preview,
                       tier, rate_limit_per_minute, daily_limit, monthly_usage,
                       active, created_at
                FROM api_keys
                ORDER BY created_at DESC
            """)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("List API keys error: %s", e)
        return []


@router.get("/keys/{key_id}")
async def get_api_key(key_id: str):
    if not _db_pool:
        raise HTTPException(503, "Database unavailable")

    try:
        async with _db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, org_name, LEFT(api_key, 10) || '...' as api_key_preview,
                       tier, rate_limit_per_minute, daily_limit, monthly_usage,
                       active, created_at, contact_email
                FROM api_keys WHERE id::text = $1
            """, key_id)
        if not row:
            raise HTTPException(404, "API key not found")
        return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Get API key error: %s", e)
        raise HTTPException(500, "Failed to get API key")


@router.patch("/keys/{key_id}")
async def update_api_key(key_id: str, req: UpdateKeyRequest):
    if not _db_pool:
        raise HTTPException(503, "Database unavailable")

    updates = []
    params = []
    param_idx = 1

    if req.tier is not None:
        param_idx += 1
        updates.append(f"tier = ${param_idx}")
        params.append(req.tier)
    if req.rate_limit_per_minute is not None:
        param_idx += 1
        updates.append(f"rate_limit_per_minute = ${param_idx}")
        params.append(req.rate_limit_per_minute)
    if req.daily_limit is not None:
        param_idx += 1
        updates.append(f"daily_limit = ${param_idx}")
        params.append(req.daily_limit)
    if req.active is not None:
        param_idx += 1
        updates.append(f"active = ${param_idx}")
        params.append(req.active)

    if not updates:
        raise HTTPException(400, "No fields to update")

    try:
        async with _db_pool.acquire() as conn:
            result = await conn.execute(
                f"UPDATE api_keys SET {', '.join(updates)} WHERE id::text = $1",
                key_id, *params,
            )
        return {"updated": True, "key_id": key_id}
    except Exception as e:
        logger.warning("Update API key error: %s", e)
        raise HTTPException(500, "Failed to update API key")


@router.delete("/keys/{key_id}")
async def deactivate_api_key(key_id: str):
    if not _db_pool:
        raise HTTPException(503, "Database unavailable")

    try:
        async with _db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE api_keys SET active = false WHERE id::text = $1",
                key_id,
            )
        return {"deactivated": True, "key_id": key_id}
    except Exception as e:
        logger.warning("Deactivate API key error: %s", e)
        raise HTTPException(500, "Failed to deactivate API key")


@router.get("/usage/{key_id}")
async def get_usage(key_id: str, days: int = 30):
    if not _db_pool:
        raise HTTPException(503, "Database unavailable")

    try:
        async with _db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT monthly_usage, daily_limit, rate_limit_per_minute, tier
                FROM api_keys WHERE id::text = $1
            """, key_id)
            if not row:
                raise HTTPException(404, "API key not found")

        return {
            "key_id": key_id,
            "monthly_usage": row["monthly_usage"],
            "daily_limit": row["daily_limit"],
            "tier": row["tier"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Get usage error: %s", e)
        raise HTTPException(500, "Failed to get usage")


@router.get("/tiers")
async def list_tiers():
    return {
        tier: {
            "rate_limit_per_minute": config["rate_limit_per_minute"],
            "daily_limit": config["daily_limit"],
            "price_monthly_usd": config["price_cents"] / 100,
            "moat_catalog_tier": LEGACY_TO_MOAT.get(tier, "BASE"),
        }
        for tier, config in TIER_CONFIGS.items()
    }


@router.get("/tiers/moat-catalog")
async def list_moat_catalog():
    return {
        "status": "ok",
        "catalog": MOAT_CATALOG,
        "legacy_mapping": LEGACY_TO_MOAT,
    }
