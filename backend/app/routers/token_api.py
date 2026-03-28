from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.auth import get_current_user_id
from app.services.api_server import require_admin, get_current_user
from app.services.db import get_db
from app.services.token_economics import token_economics, init_token_service

router = APIRouter(prefix="/api/tokens", tags=["tokens"])

@router.on_startup
async def startup():
    """Initialize token service on router startup."""
    db = next(get_db())
    await init_token_service(db)

@router.get("/balance/{user_id}")
async def get_user_balance(
    user_id: str,
    current_user_id: str = Depends(get_current_user_id),
    user: Dict[str, Any] = Depends(get_current_user)
):
    """Get token balance for a user (self or coach/admin)."""
    # Self access or coach/admin
    if user_id != current_user_id and user.get("role") not in ["COACH", "ADMIN"]:
        raise HTTPException(403, "Insufficient permissions")
    
    family_id = await get_db().__anext__().fetchval(
        text("SELECT family_id FROM users WHERE id = :user_id"),
        {"user_id": user_id}
    )
    if not family_id:
        raise HTTPException(404, "User not found")
    
    balance = await token_economics.get_balance(family_id, user_id)
    return {
        "user_id": user_id,
        "family_id": family_id,
        "balance": balance
    }

@router.get("/balance/family/{family_id}")
async def get_family_balances(
    family_id: str,
    current_user: Dict[str, Any] = Depends(require_admin)
):
    """Get all balances for a family (admin only)."""
    result = await get_db().__anext__().fetchall(
        text("""
            SELECT user_id, balance, pending_in, pending_out, total_earned, total_spent
            FROM token_balances
            WHERE family_id = :family_id
        """),
        {"family_id": family_id}
    )
    return [dict(row) for row in result]

@router.post("/transfer")
async def transfer_tokens(
    data: Dict[str, str],
    current_user: Dict[str, Any] = Depends(require_admin)
):
    """Transfer tokens between users (admin only)."""
    from_user_id = data.get("from_user_id")
    to_user_id = data.get("to_user_id")
    amount = int(data.get("amount", 0))
    reason = data.get("reason", "manual transfer")
    
    if not all([from_user_id, to_user_id, amount > 0, reason]):
        raise HTTPException(400, "Missing required fields")
    
    success = await token_economics.transfer_tokens(from_user_id, to_user_id, amount, reason)
    if not success:
        raise HTTPException(400, "Transfer failed")
    
    return {"status": "success", "amount": amount, "reason": reason}

@router.post("/award")
async def award_tokens(
    data: Dict[str, str],
    current_user: Dict[str, Any] = Depends(require_admin)
):
    """Award/mint tokens to user (admin only)."""
    user_id = data.get("user_id")
    amount = int(data.get("amount", 0))
    reason = data.get("reason", "award")
    
    if not all([user_id, amount > 0, reason]):
        raise HTTPException(400, "Missing required fields")
    
    success = await token_economics.award_tokens(user_id, amount, reason)
    if not success:
        raise HTTPException(400, "Award failed")
    
    return {"status": "success", "amount": amount, "reason": reason}

@router.get("/transfers")
async def list_transfers(
    limit: int = 100,
    current_user: Dict[str, Any] = Depends(require_admin)
):
    """List recent token transfers (admin only)."""
    result = await get_db().__anext__().fetchall(
        text("""
            SELECT * FROM token_transfers
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        {"limit": limit}
    )
    return [dict(row) for row in result}