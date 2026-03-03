"""
SOVEREIGN SWARM — Legacy Vault API Router
REST endpoints for transgenerational pattern storage and consent management:
  - Family consent status and management
  - Vault entries (inheritance maps, pattern interruptions, transformations)
  - Inheritance map retrieval
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import get_current_user_id
from app.services.legacy_vault import LegacyVault
from app.services.exceptions import ConsentWithdrawnException, LegacyVaultException

logger = logging.getLogger("routers.legacy_vault")

router = APIRouter(prefix="/api/legacy-vault", tags=["Legacy Vault"])

_VAULT_TIERS = {"TOP_TIER", "SOVEREIGN_CIRCLE", "STANDARD", "INNER_CHAMBER"}


async def _require_vault_tier(
    request: Request,
    user_id: str = Depends(get_current_user_id),
) -> str:
    """Legacy Vault requires Inner Chamber (STANDARD) or higher."""
    pool = getattr(request.app.state, "db_pool", None)
    if pool:
        try:
            row = await pool.fetchrow(
                "SELECT tier, profile_data->>'subscription_plan' AS plan "
                "FROM users WHERE hardware_id = $1 AND deleted_at IS NULL LIMIT 1",
                user_id,
            )
            if row:
                tier = (row["tier"] or row["plan"] or "").upper()
                if tier in _VAULT_TIERS:
                    return user_id
                raise HTTPException(
                    403,
                    f"Legacy Vault requires Inner Chamber or higher. Current: {tier or 'TRIAL'}",
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("_require_vault_tier PG check failed: %s", e)
    return user_id


# =============================================================================
# REQUEST MODELS
# =============================================================================


class ConsentUserIdBody(BaseModel):
    """Body for grant/withdraw consent operations."""

    user_id: UUID = Field(..., description="User ID granting or withdrawing consent")


# =============================================================================
# HELPERS
# =============================================================================


def _get_service(request: Request) -> LegacyVault:
    """Get LegacyVault instance from app state."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")
    return LegacyVault(db_pool)


async def _verify_family_membership(request: Request, family_id: UUID, current_user: str) -> None:
    """Verify the authenticated user belongs to the given family. Raises 403 if not."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        return  # Can't verify if no pool; service-layer will handle
    try:
        async with db_pool.acquire() as conn:
            member = await conn.fetchval(
                "SELECT 1 FROM family_members WHERE family_id = $1 AND user_id = $2::uuid LIMIT 1",
                family_id, current_user,
            )
            if not member:
                raise HTTPException(status_code=403, detail="Access denied: you are not a member of this family")
    except HTTPException:
        raise
    except Exception:
        pass  # Table may not exist yet; allow through


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("/consent/{family_id}")
async def check_consent_status(
    request: Request,
    family_id: UUID,
    current_user: str = Depends(_require_vault_tier),
) -> dict:
    """
    Check consent status for a family.
    Returns list of members who have granted consent for transgenerational analysis.
    Requires authentication; user must belong to the family.
    """
    await _verify_family_membership(request, family_id, current_user)
    svc = _get_service(request)
    try:
        return await svc.check_family_consent(family_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/consent/{family_id}")
async def grant_consent(
    request: Request,
    family_id: UUID,
    body: ConsentUserIdBody,
    current_user: str = Depends(_require_vault_tier),
) -> dict:
    """
    Grant consent for transgenerational analysis.
    The user will be included in family pattern analysis.
    Requires authentication; user can only grant their own consent.
    """
    if current_user != str(body.user_id):
        raise HTTPException(status_code=403, detail="Access denied: you can only grant your own consent")
    await _verify_family_membership(request, family_id, current_user)
    svc = _get_service(request)
    try:
        return await svc.grant_consent(body.user_id, family_id)
    except LegacyVaultException as e:
        raise HTTPException(status_code=400, detail=str(e.message))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/consent/{family_id}")
async def withdraw_consent(
    request: Request,
    family_id: UUID,
    body: ConsentUserIdBody,
    current_user: str = Depends(_require_vault_tier),
) -> dict:
    """
    Withdraw consent for transgenerational analysis.
    Data from this member will be excluded from all family pattern analyses.
    Requires authentication; user can only withdraw their own consent.
    """
    if current_user != str(body.user_id):
        raise HTTPException(status_code=403, detail="Access denied: you can only withdraw your own consent")
    svc = _get_service(request)
    try:
        return await svc.withdraw_consent(body.user_id, family_id)
    except ConsentWithdrawnException as e:
        raise HTTPException(status_code=400, detail=str(e.message))
    except LegacyVaultException as e:
        raise HTTPException(status_code=400, detail=str(e.message))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entries/{family_id}")
async def list_vault_entries(
    request: Request,
    family_id: UUID,
    current_user: str = Depends(_require_vault_tier),
    entry_type: Optional[str] = None,
) -> list:
    """
    List vault entries for a family.
    Optionally filter by entry_type (e.g. inheritance_map, pattern_interruption, transformation).
    Returns all types if entry_type is omitted.
    Requires authentication; user must belong to the family.
    """
    await _verify_family_membership(request, family_id, current_user)
    svc = _get_service(request)
    try:
        entries = await svc.get_vault_entries(family_id, entry_type=entry_type)
        return entries
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/inheritance-map/{family_id}")
async def get_inheritance_map(
    request: Request,
    family_id: UUID,
    current_user: str = Depends(_require_vault_tier),
) -> dict:
    """
    Get or create the emotional inheritance map for a family.
    Maps shared emotional patterns across consented members.
    Requires authentication; user must belong to the family.
    """
    await _verify_family_membership(request, family_id, current_user)
    svc = _get_service(request)
    try:
        return await svc.get_inheritance_map(family_id)
    except LegacyVaultException as e:
        raise HTTPException(status_code=400, detail=str(e.message))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
