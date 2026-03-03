"""
Scholarship Fund API
Sponsor accounts that pre-fund services for beneficiaries.
Scholarship balances are deducted before the HoH's card is charged.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import json
import os
import uuid as _uuid_mod

from app.auth import get_current_user

try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False

if STRIPE_AVAILABLE:
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

router = APIRouter(
    prefix="/api/billing/scholarship",
    tags=["scholarship"],
    dependencies=[Depends(get_current_user)],
)


class CreateFundRequest(BaseModel):
    fund_name: str
    sponsor_user_id: str


class DepositRequest(BaseModel):
    fund_id: str
    amount_cents: int
    description: Optional[str] = "Scholarship deposit"


class AllocateRequest(BaseModel):
    fund_id: str
    beneficiary_user_id: str
    monthly_limit_cents: Optional[int] = None


class WithdrawRequest(BaseModel):
    fund_id: str
    allocation_id: str
    amount_cents: int
    description: Optional[str] = "Service charge"


def _get_pool(request: Request):
    return getattr(request.app.state, "db_pool", None)


def _validate_uuid(value: str, field_name: str = "id") -> str:
    try:
        _uuid_mod.UUID(value)
        return value
    except (ValueError, AttributeError):
        raise HTTPException(400, f"Invalid UUID for {field_name}: {value}")


@router.post("/create")
async def create_fund(req: CreateFundRequest, request: Request):
    pool = _get_pool(request)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO scholarship_funds (sponsor_user_id, fund_name)
            VALUES (
                (SELECT id FROM users WHERE hardware_id = $1 LIMIT 1),
                $2
            )
            RETURNING id, fund_name, balance_cents, created_at
        """, req.sponsor_user_id, req.fund_name)

    if not row:
        raise HTTPException(400, "Failed to create fund — sponsor not found")

    return {
        "fund_id": str(row["id"]),
        "fund_name": row["fund_name"],
        "balance_cents": row["balance_cents"],
        "created_at": row["created_at"].isoformat(),
    }


@router.post("/deposit")
async def deposit_to_fund(req: DepositRequest, request: Request):
    pool = _get_pool(request)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    _validate_uuid(req.fund_id, "fund_id")

    if req.amount_cents <= 0:
        raise HTTPException(400, "Deposit amount must be positive")

    async with pool.acquire() as conn:
        fund = await conn.fetchrow(
            "SELECT id, balance_cents, active FROM scholarship_funds WHERE id = $1",
            req.fund_id,
        )
        if not fund:
            raise HTTPException(404, "Fund not found")
        if not fund["active"]:
            raise HTTPException(400, "Fund is inactive")

        await conn.execute("""
            UPDATE scholarship_funds
            SET balance_cents = balance_cents + $1,
                total_deposited = total_deposited + $1,
                updated_at = NOW()
            WHERE id = $2
        """, req.amount_cents, req.fund_id)

        await conn.execute("""
            INSERT INTO scholarship_transactions (fund_id, amount_cents, txn_type, description)
            VALUES ($1, $2, 'deposit', $3)
        """, req.fund_id, req.amount_cents, req.description)

    return {
        "fund_id": req.fund_id,
        "deposited_cents": req.amount_cents,
        "new_balance_cents": fund["balance_cents"] + req.amount_cents,
    }


@router.post("/allocate")
async def allocate_beneficiary(req: AllocateRequest, request: Request):
    pool = _get_pool(request)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    _validate_uuid(req.fund_id, "fund_id")

    async with pool.acquire() as conn:
        fund = await conn.fetchrow(
            "SELECT id, active FROM scholarship_funds WHERE id = $1", req.fund_id
        )
        if not fund:
            raise HTTPException(404, "Fund not found")
        if not fund["active"]:
            raise HTTPException(400, "Fund is inactive")

        existing = await conn.fetchrow("""
            SELECT id FROM scholarship_allocations
            WHERE fund_id = $1 AND beneficiary_user_id = (
                SELECT id FROM users WHERE hardware_id = $2 LIMIT 1
            ) AND active = TRUE
        """, req.fund_id, req.beneficiary_user_id)

        if existing:
            raise HTTPException(400, "Beneficiary already allocated to this fund")

        row = await conn.fetchrow("""
            INSERT INTO scholarship_allocations
                (fund_id, beneficiary_user_id, monthly_limit_cents)
            VALUES (
                $1,
                (SELECT id FROM users WHERE hardware_id = $2 LIMIT 1),
                $3
            )
            RETURNING id, created_at
        """, req.fund_id, req.beneficiary_user_id, req.monthly_limit_cents)

    if not row:
        raise HTTPException(400, "Failed to allocate — beneficiary not found")

    return {
        "allocation_id": str(row["id"]),
        "fund_id": req.fund_id,
        "beneficiary_user_id": req.beneficiary_user_id,
        "monthly_limit_cents": req.monthly_limit_cents,
    }


@router.get("/{fund_id}/balance")
async def get_fund_balance(fund_id: str, request: Request):
    pool = _get_pool(request)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    _validate_uuid(fund_id, "fund_id")

    async with pool.acquire() as conn:
        fund = await conn.fetchrow("""
            SELECT id, fund_name, balance_cents, total_deposited,
                   total_disbursed, active, created_at
            FROM scholarship_funds WHERE id = $1
        """, fund_id)

        if not fund:
            raise HTTPException(404, "Fund not found")

        allocations = await conn.fetch("""
            SELECT sa.id, sa.monthly_limit_cents, sa.used_this_month, sa.active,
                   u.name as beneficiary_name, u.hardware_id as beneficiary_id
            FROM scholarship_allocations sa
            LEFT JOIN users u ON sa.beneficiary_user_id = u.id
            WHERE sa.fund_id = $1
            ORDER BY sa.created_at
        """, fund_id)

        recent_txns = await conn.fetch("""
            SELECT id, amount_cents, txn_type, description, created_at
            FROM scholarship_transactions
            WHERE fund_id = $1
            ORDER BY created_at DESC
            LIMIT 20
        """, fund_id)

    return {
        "fund_id": str(fund["id"]),
        "fund_name": fund["fund_name"],
        "balance_cents": fund["balance_cents"],
        "total_deposited": fund["total_deposited"],
        "total_disbursed": fund["total_disbursed"],
        "active": fund["active"],
        "allocations": [
            {
                "id": str(a["id"]),
                "beneficiary_name": a["beneficiary_name"],
                "beneficiary_id": a["beneficiary_id"],
                "monthly_limit_cents": a["monthly_limit_cents"],
                "used_this_month": a["used_this_month"],
                "active": a["active"],
            }
            for a in allocations
        ],
        "recent_transactions": [
            {
                "id": str(t["id"]),
                "amount_cents": t["amount_cents"],
                "type": t["txn_type"],
                "description": t["description"],
                "created_at": t["created_at"].isoformat(),
            }
            for t in recent_txns
        ],
    }


@router.post("/withdraw")
async def withdraw_from_fund(req: WithdrawRequest, request: Request):
    """Deduct from a scholarship allocation (called internally during billing)."""
    pool = _get_pool(request)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    _validate_uuid(req.fund_id, "fund_id")
    _validate_uuid(req.allocation_id, "allocation_id")

    if req.amount_cents <= 0:
        raise HTTPException(400, "Amount must be positive")

    async with pool.acquire() as conn:
        alloc = await conn.fetchrow("""
            SELECT sa.id, sa.fund_id, sa.monthly_limit_cents, sa.used_this_month, sa.active,
                   sf.balance_cents as fund_balance, sf.active as fund_active
            FROM scholarship_allocations sa
            JOIN scholarship_funds sf ON sa.fund_id = sf.id
            WHERE sa.id = $1 AND sa.fund_id = $2
        """, req.allocation_id, req.fund_id)

        if not alloc:
            raise HTTPException(404, "Allocation not found")
        if not alloc["active"] or not alloc["fund_active"]:
            raise HTTPException(400, "Allocation or fund is inactive")

        if alloc["fund_balance"] < req.amount_cents:
            raise HTTPException(400, "Insufficient fund balance")

        if alloc["monthly_limit_cents"] is not None:
            remaining_monthly = alloc["monthly_limit_cents"] - alloc["used_this_month"]
            if req.amount_cents > remaining_monthly:
                raise HTTPException(400, f"Monthly limit exceeded (remaining: {remaining_monthly} cents)")

        await conn.execute("""
            UPDATE scholarship_funds
            SET balance_cents = balance_cents - $1,
                total_disbursed = total_disbursed + $1,
                updated_at = NOW()
            WHERE id = $2
        """, req.amount_cents, req.fund_id)

        await conn.execute("""
            UPDATE scholarship_allocations
            SET used_this_month = used_this_month + $1
            WHERE id = $2
        """, req.amount_cents, req.allocation_id)

        await conn.execute("""
            INSERT INTO scholarship_transactions
                (fund_id, allocation_id, amount_cents, txn_type, description)
            VALUES ($1, $2, $3, 'withdrawal', $4)
        """, req.fund_id, req.allocation_id, req.amount_cents, req.description)

    return {
        "withdrawn_cents": req.amount_cents,
        "fund_id": req.fund_id,
        "allocation_id": req.allocation_id,
    }


@router.get("/user/{user_id}")
async def get_user_scholarships(user_id: str, request: Request):
    """Get scholarship allocations for a specific user (beneficiary view)."""
    pool = _get_pool(request)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    async with pool.acquire() as conn:
        allocations = await conn.fetch("""
            SELECT sa.id, sa.monthly_limit_cents, sa.used_this_month, sa.active,
                   sf.fund_name, sf.balance_cents as fund_balance,
                   su.name as sponsor_name
            FROM scholarship_allocations sa
            JOIN scholarship_funds sf ON sa.fund_id = sf.id
            LEFT JOIN users su ON sf.sponsor_user_id = su.id
            WHERE sa.beneficiary_user_id = (
                SELECT id FROM users WHERE hardware_id = $1 LIMIT 1
            ) AND sa.active = TRUE AND sf.active = TRUE
        """, user_id)

    return {
        "user_id": user_id,
        "scholarships": [
            {
                "allocation_id": str(a["id"]),
                "fund_name": a["fund_name"],
                "sponsor_name": a["sponsor_name"],
                "fund_balance_cents": a["fund_balance"],
                "monthly_limit_cents": a["monthly_limit_cents"],
                "used_this_month": a["used_this_month"],
            }
            for a in allocations
        ],
    }
