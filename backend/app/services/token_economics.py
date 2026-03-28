from typing import Dict, Any, Optional, List
from fastapi import Depends
from sqlalchemy import text
from app.auth import get_current_user_id
from app.services.db import get_db
from app.services.api_server import get_current_user

class TokenEconomics:
    def __init__(self):
        self.db = None

    async def get_balance(self, family_id: str, user_id: str) -> Dict[str, int]:
        """Get current token balance for user."""
        if not self.db:
            raise ValueError("DB not initialized")
        
        result = await self.db.fetchrow(
            text("""
                SELECT balance, pending_in, pending_out, total_earned, total_spent
                FROM token_balances
                WHERE family_id = :family_id AND user_id = :user_id
            """),
            {"family_id": family_id, "user_id": user_id}
        )
        return dict(result) if result else {"balance": 0, "pending_in": 0, "pending_out": 0, "total_earned": 0, "total_spent": 0}

    async def transfer_tokens(self, from_user_id: str, to_user_id: str, amount: int, reason: str) -> bool:
        """Transfer tokens between users (admin only)."""
        if amount <= 0:
            return False
        
        # Get family IDs
        from_family = await self.db.fetchval(
            text("SELECT family_id FROM users WHERE id = :user_id"),
            {"user_id": from_user_id}
        )
        to_family = await self.db.fetchval(
            text("SELECT family_id FROM users WHERE id = :user_id"),
            {"user_id": to_user_id}
        )
        
        if not from_family or not to_family:
            return False
        
        result = await self.db.execute(
            text("""
                INSERT INTO token_transfers (from_family_id, from_user_id, to_family_id, to_user_id, amount, reason)
                VALUES (:from_family_id, :from_user_id, :to_family_id, :to_user_id, :amount, :reason)
            """),
            {
                "from_family_id": from_family,
                "from_user_id": from_user_id,
                "to_family_id": to_family,
                "to_user_id": to_user_id,
                "amount": amount,
                "reason": reason
            }
        )
        return result.rowcount > 0

    async def award_tokens(self, user_id: str, amount: int, reason: str) -> bool:
        """Mint/award tokens to user (admin only)."""
        family_id = await self.db.fetchval(
            text("SELECT family_id FROM users WHERE id = :user_id"),
            {"user_id": user_id}
        )
        if not family_id:
            return False
        
        # Insert transfer from system (null from_user)
        result = await self.db.execute(
            text("""
                INSERT INTO token_transfers (from_family_id, from_user_id, to_family_id, to_user_id, amount, reason)
                VALUES (:from_family_id, :from_user_id, :to_family_id, :to_user_id, :amount, :reason)
            """),
            {
                "from_family_id": None, "from_user_id": None,
                "to_family_id": family_id, "to_user_id": user_id,
                "amount": amount, "reason": reason
            }
        )
        return result.rowcount > 0

token_economics = TokenEconomics()

async def init_token_service(db):
    token_economics.db = db
    return token_economics

# Health check
def token_health_check():
    return token_economics.db is not None