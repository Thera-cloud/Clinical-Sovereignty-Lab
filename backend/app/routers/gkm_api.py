"""
GKM API — Greatest in the Kingdom Ministry 501(c)(3) Integration

Handles:
- BLE/NFC token sharing with Stripe fee ($5 per 10k tokens)
- Donation ledger tracking (all share fees = donations)
- Annual receipt generation for donors >= $250
- Scholarship and discount monitoring
- Token sharing history and analytics

Tax-exempt ID: 84-3879515
Address: Stafford, TX 77477
Contact: support@sovereignsanctuary.net
"""

import json
import logging
import math
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.services.api_server import get_current_user, require_admin

BALANCE_SYNC_CHANNEL = "nate:balance_sync"
USER_RELOAD_CHANNEL = "nate:user_reload"


async def _publish_balance_sync(username: str, new_balance: int):
    """Notify the bridge to update its in-memory cache for this user's token balance."""
    try:
        from app.services.api_server import _get_auth_redis
        r = await _get_auth_redis()
        if r:
            await r.publish(
                BALANCE_SYNC_CHANNEL,
                json.dumps({"username": username, "token_balance": new_balance}),
            )
            await r.publish(
                USER_RELOAD_CHANNEL,
                json.dumps({"username": username}),
            )
    except Exception as e:
        logging.getLogger("gkm").warning("Balance sync publish failed for %s: %s", username, e)

logger = logging.getLogger("gkm_api")

router = APIRouter(prefix="/api/gkm", tags=["gkm"])


GKM_TAX_ID = "84-3879515"
GKM_ADDRESS = "Stafford, TX 77477"
GKM_CONTACT = "support@sovereignsanctuary.net"
SHARE_FEE_PER_10K = 500  # cents
DONATION_RECEIPT_THRESHOLD_CENTS = 25000  # $250
FREE_MONTH_TOKEN_THRESHOLD = 100000


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TokenShareRequest(BaseModel):
    sharer_username: str
    receiver_username: str
    tokens: int
    stripe_payment_method_id: Optional[str] = None


class SendReceiptRequest(BaseModel):
    tax_year: Optional[int] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    return pool


def _calculate_share_fee_cents(tokens: int) -> int:
    """$5 per 10,000 tokens (rounded up)."""
    chunks = math.ceil(tokens / 10000)
    return chunks * SHARE_FEE_PER_10K


# ---------------------------------------------------------------------------
# Token Sharing Endpoints (client-facing, no admin required)
# ---------------------------------------------------------------------------

@router.post("/token-share/initiate")
async def initiate_token_share(body: TokenShareRequest, request: Request):
    """Initiate a BLE/NFC token share with Stripe fee."""
    pool = await _get_pool(request)

    if body.tokens < 1:
        raise HTTPException(400, "Must share at least 1 token")
    if body.tokens > 100000:
        raise HTTPException(400, "Maximum 100,000 tokens per share")
    if body.sharer_username == body.receiver_username:
        raise HTTPException(400, "Cannot share tokens with yourself")

    fee_cents = _calculate_share_fee_cents(body.tokens)

    async with pool.acquire() as conn:
        sharer = await conn.fetchrow(
            "SELECT username, COALESCE(token_balance, 0) as bal, profile_data->>'email' as email, profile_data->>'name' as name, id::text as uid FROM users WHERE username = $1",
            body.sharer_username,
        )
        if not sharer:
            raise HTTPException(404, f"Sharer {body.sharer_username} not found")
        if sharer["bal"] < body.tokens:
            raise HTTPException(400, f"Insufficient balance: {sharer['bal']:,} < {body.tokens:,}")

        receiver = await conn.fetchrow(
            "SELECT username, COALESCE(token_balance, 0) as bal FROM users WHERE username = $1",
            body.receiver_username,
        )
        if not receiver:
            raise HTTPException(404, f"Receiver {body.receiver_username} not found")

        stripe_payment_id = None
        try:
            from app.services.stripe_integration import StripeService
            svc = StripeService(pool)
            stripe_payment_id = await svc.charge_token_share_fee(
                user_id=sharer["uid"],
                email=sharer["email"] or "",
                name=sharer["name"] or body.sharer_username,
                tokens_shared=body.tokens,
                sharer_username=body.sharer_username,
                receiver_username=body.receiver_username,
            )
        except Exception as e:
            logger.warning("Stripe share fee charge failed: %s", e)
            raise HTTPException(402, f"Payment failed: {e}")

        async with conn.transaction():
            sharer_before = sharer["bal"]
            receiver_before = receiver["bal"]
            sharer_after = sharer_before - body.tokens
            receiver_after = receiver_before + body.tokens

            await conn.execute("""
                UPDATE users SET token_balance = $1,
                    profile_data = jsonb_set(COALESCE(profile_data, '{}'::jsonb), '{token_balance}', to_jsonb($1::int))
                WHERE username = $2
            """, sharer_after, body.sharer_username)

            await conn.execute("""
                UPDATE users SET token_balance = $1,
                    profile_data = jsonb_set(COALESCE(profile_data, '{}'::jsonb), '{token_balance}', to_jsonb($1::int))
                WHERE username = $2
            """, receiver_after, body.receiver_username)

            await conn.execute("""
                INSERT INTO token_shares
                    (sharer_username, receiver_username, tokens_shared, share_fee_cents, stripe_payment_id, donation_eligible)
                VALUES ($1, $2, $3, $4, $5, TRUE)
            """, body.sharer_username, body.receiver_username, body.tokens, fee_cents, stripe_payment_id)

            await conn.execute("""
                INSERT INTO token_transactions
                    (username, action, amount, balance_before, balance_after, reason, source, initiated_by, target_scope)
                VALUES ($1, 'share_out', $2, $3, $4, $5, 'token_share', 'user', 'individual')
            """, body.sharer_username, -body.tokens, sharer_before, sharer_after,
                f"Shared {body.tokens:,} tokens to {body.receiver_username}")

            await conn.execute("""
                INSERT INTO token_transactions
                    (username, action, amount, balance_before, balance_after, reason, source, initiated_by, target_scope)
                VALUES ($1, 'share_in', $2, $3, $4, $5, 'token_share', 'user', 'individual')
            """, body.receiver_username, body.tokens, receiver_before, receiver_after,
                f"Received {body.tokens:,} tokens from {body.sharer_username}")

            now = datetime.now(timezone.utc)
            tax_year = now.year

            cumulative = await conn.fetchval("""
                SELECT COALESCE(SUM(donation_amount_cents), 0)
                FROM gkm_donations WHERE username = $1 AND tax_year = $2
            """, body.sharer_username, tax_year) or 0
            new_cumulative = cumulative + fee_cents

            await conn.execute("""
                INSERT INTO gkm_donations
                    (username, donation_amount_cents, source, cumulative_total_cents, tax_year, stripe_payment_id)
                VALUES ($1, $2, 'token_share', $3, $4, $5)
            """, body.sharer_username, fee_cents, new_cumulative, tax_year, stripe_payment_id)

            total_tokens_shared = await conn.fetchval("""
                SELECT COALESCE(SUM(tokens_shared), 0) FROM token_shares WHERE sharer_username = $1
            """, body.sharer_username)

            free_month_awarded = False
            if total_tokens_shared >= FREE_MONTH_TOKEN_THRESHOLD:
                existing_reward = await conn.fetchval("""
                    SELECT COUNT(*) FROM token_transactions
                    WHERE username = $1 AND action = 'reward_free_month'
                """, body.sharer_username)
                milestones_earned = total_tokens_shared // FREE_MONTH_TOKEN_THRESHOLD
                if milestones_earned > (existing_reward or 0):
                    await conn.execute("""
                        INSERT INTO token_transactions
                            (username, action, amount, balance_before, balance_after, reason, source, initiated_by)
                        VALUES ($1, 'reward_free_month', 0, $2, $2, 'Free month for sharing 100k+ tokens', 'sharing_reward', 'system')
                    """, body.sharer_username, sharer_after)
                    free_month_awarded = True

    await _publish_balance_sync(body.sharer_username, sharer_after)
    await _publish_balance_sync(body.receiver_username, receiver_after)

    nate_response = None
    try:
        chat_engine = getattr(request.app.state, "skyeye_chat", None)
        if chat_engine and hasattr(chat_engine, "generate_gifting_response"):
            nate_response = await chat_engine.generate_gifting_response(
                sharer_name=sharer["name"] or body.sharer_username,
                sharer_username=body.sharer_username,
                receiver_name=body.receiver_username,
                tokens_shared=body.tokens,
                total_shares=total_tokens_shared,
                pool=pool,
            )
    except Exception as e:
        logger.warning("Gifting response generation failed: %s", e)

    return {
        "status": "completed",
        "tokens_shared": body.tokens,
        "fee_cents": fee_cents,
        "fee_display": f"${fee_cents / 100:.2f}",
        "sharer_balance": sharer_after,
        "receiver_balance": receiver_after,
        "donation_cumulative_cents": new_cumulative,
        "donation_receipt_eligible": new_cumulative >= DONATION_RECEIPT_THRESHOLD_CENTS,
        "free_month_awarded": free_month_awarded,
        "nate_response": nate_response,
    }


@router.get("/token-share/history/{username}")
async def get_share_history(username: str, request: Request):
    """Share history for a user (liminal history of shares)."""
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        shares = await conn.fetch("""
            SELECT id, sharer_username, receiver_username, tokens_shared,
                   share_fee_cents, created_at
            FROM token_shares
            WHERE sharer_username = $1 OR receiver_username = $1
            ORDER BY created_at DESC LIMIT 100
        """, username)

        stats = await conn.fetchrow("""
            SELECT
                COUNT(*) as total_shares,
                COALESCE(SUM(tokens_shared), 0) as total_tokens_shared,
                COUNT(DISTINCT receiver_username) as unique_recipients
            FROM token_shares WHERE sharer_username = $1
        """, username)

        return {
            "username": username,
            "stats": dict(stats) if stats else {},
            "history": [
                {**dict(s), "id": str(s["id"]), "created_at": s["created_at"].isoformat()}
                for s in shares
            ],
        }


# ---------------------------------------------------------------------------
# Admin GKM Endpoints (require admin)
# ---------------------------------------------------------------------------

@router.get("/donations", dependencies=[Depends(require_admin)])
async def get_all_donations(request: Request, year: Optional[int] = None, limit: int = 200):
    """All donations for GKM tab."""
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        if year:
            rows = await conn.fetch("""
                SELECT id, username, donation_amount_cents, source, cumulative_total_cents,
                       receipt_sent, tax_year, created_at
                FROM gkm_donations WHERE tax_year = $1
                ORDER BY created_at DESC LIMIT $2
            """, year, limit)
        else:
            rows = await conn.fetch("""
                SELECT id, username, donation_amount_cents, source, cumulative_total_cents,
                       receipt_sent, tax_year, created_at
                FROM gkm_donations ORDER BY created_at DESC LIMIT $1
            """, limit)

        summary = await conn.fetchrow("""
            SELECT
                COUNT(DISTINCT username) as total_donors,
                COALESCE(SUM(donation_amount_cents), 0) as total_all_time_cents,
                COUNT(*) as total_donations
            FROM gkm_donations
        """)

        year_summary = await conn.fetchrow("""
            SELECT COALESCE(SUM(donation_amount_cents), 0) as total_this_year_cents,
                   COUNT(DISTINCT username) as donors_this_year
            FROM gkm_donations WHERE tax_year = $1
        """, year or datetime.now(timezone.utc).year)

        return {
            "summary": {
                "total_donors": summary["total_donors"] if summary else 0,
                "total_all_time_cents": summary["total_all_time_cents"] if summary else 0,
                "total_this_year_cents": year_summary["total_this_year_cents"] if year_summary else 0,
                "donors_this_year": year_summary["donors_this_year"] if year_summary else 0,
            },
            "donations": [
                {**dict(r), "id": str(r["id"]), "created_at": r["created_at"].isoformat()}
                for r in rows
            ],
        }


@router.get("/donations/{username}", dependencies=[Depends(require_admin)])
async def get_user_donations(username: str, request: Request):
    """Per-user donation history."""
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, donation_amount_cents, source, cumulative_total_cents,
                   receipt_sent, tax_year, created_at
            FROM gkm_donations WHERE username = $1 ORDER BY created_at DESC
        """, username)

        total = await conn.fetchval(
            "SELECT COALESCE(SUM(donation_amount_cents), 0) FROM gkm_donations WHERE username = $1",
            username,
        )

        return {
            "username": username,
            "total_donations_cents": total or 0,
            "receipt_eligible": (total or 0) >= DONATION_RECEIPT_THRESHOLD_CENTS,
            "donations": [
                {**dict(r), "id": str(r["id"]), "created_at": r["created_at"].isoformat()}
                for r in rows
            ],
        }


@router.get("/annual-summary", dependencies=[Depends(require_admin)])
async def get_annual_summary(request: Request, year: Optional[int] = None):
    """Annual donation totals per user."""
    pool = await _get_pool(request)
    tax_year = year or datetime.now(timezone.utc).year
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT username,
                   SUM(donation_amount_cents) as total_cents,
                   COUNT(*) as donation_count
            FROM gkm_donations
            WHERE tax_year = $1
            GROUP BY username
            ORDER BY total_cents DESC
        """, tax_year)

        receipts = await conn.fetch("""
            SELECT username, total_donations_cents, sent_at, receipt_pdf_path
            FROM gkm_annual_receipts WHERE tax_year = $1
        """, tax_year)
        receipt_map = {r["username"]: dict(r) for r in receipts}

        return {
            "tax_year": tax_year,
            "donors": [
                {
                    "username": r["username"],
                    "total_cents": r["total_cents"],
                    "total_display": f"${r['total_cents'] / 100:.2f}",
                    "donation_count": r["donation_count"],
                    "receipt_eligible": r["total_cents"] >= DONATION_RECEIPT_THRESHOLD_CENTS,
                    "receipt_sent": receipt_map.get(r["username"], {}).get("sent_at") is not None,
                }
                for r in rows
            ],
        }


@router.post("/send-receipt/{username}", dependencies=[Depends(require_admin)])
async def send_donation_receipt(username: str, body: SendReceiptRequest, request: Request):
    """Generate and send a donation receipt for a user."""
    pool = await _get_pool(request)
    tax_year = body.tax_year or datetime.now(timezone.utc).year
    async with pool.acquire() as conn:
        total = await conn.fetchval("""
            SELECT COALESCE(SUM(donation_amount_cents), 0)
            FROM gkm_donations WHERE username = $1 AND tax_year = $2
        """, username, tax_year)

        if not total or total < DONATION_RECEIPT_THRESHOLD_CENTS:
            raise HTTPException(400, f"Donations for {username} in {tax_year} are ${total / 100:.2f} (below $250 threshold)")

        await conn.execute("""
            INSERT INTO gkm_annual_receipts (username, tax_year, total_donations_cents, sent_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (username, tax_year)
            DO UPDATE SET total_donations_cents = EXCLUDED.total_donations_cents, sent_at = NOW()
        """, username, tax_year, total)

        await conn.execute("""
            UPDATE gkm_donations SET receipt_sent = TRUE, receipt_sent_at = NOW()
            WHERE username = $1 AND tax_year = $2
        """, username, tax_year)

        return {
            "status": "receipt_generated",
            "username": username,
            "tax_year": tax_year,
            "total_display": f"${total / 100:.2f}",
            "gkm_tax_id": GKM_TAX_ID,
            "gkm_address": GKM_ADDRESS,
        }


@router.post("/annual-receipts/generate", dependencies=[Depends(require_admin)])
async def generate_all_annual_receipts(request: Request, year: Optional[int] = None):
    """Batch generate year-end receipts for all qualifying donors."""
    pool = await _get_pool(request)
    tax_year = year or datetime.now(timezone.utc).year - 1
    async with pool.acquire() as conn:
        qualifying = await conn.fetch("""
            SELECT username, SUM(donation_amount_cents) as total_cents
            FROM gkm_donations
            WHERE tax_year = $1
            GROUP BY username
            HAVING SUM(donation_amount_cents) >= $2
        """, tax_year, DONATION_RECEIPT_THRESHOLD_CENTS)

        generated = 0
        for donor in qualifying:
            await conn.execute("""
                INSERT INTO gkm_annual_receipts (username, tax_year, total_donations_cents, sent_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (username, tax_year)
                DO UPDATE SET total_donations_cents = EXCLUDED.total_donations_cents, sent_at = NOW()
            """, donor["username"], tax_year, donor["total_cents"])

            await conn.execute("""
                UPDATE gkm_donations SET receipt_sent = TRUE, receipt_sent_at = NOW()
                WHERE username = $1 AND tax_year = $2
            """, donor["username"], tax_year)
            generated += 1

        return {
            "status": "batch_complete",
            "tax_year": tax_year,
            "receipts_generated": generated,
            "threshold": f"${DONATION_RECEIPT_THRESHOLD_CENTS / 100:.2f}",
        }


@router.get("/scholarships", dependencies=[Depends(require_admin)])
async def get_scholarships(request: Request):
    """Scholarship fund overview (proxied from scholarship_api data)."""
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        try:
            funds = await conn.fetch("""
                SELECT id, sponsor_username, fund_name, balance_cents,
                       total_deposited_cents, created_at
                FROM scholarship_funds ORDER BY created_at DESC
            """)
            allocations = await conn.fetch("""
                SELECT id, fund_id, beneficiary_username, monthly_limit_cents, created_at
                FROM scholarship_allocations ORDER BY created_at DESC LIMIT 50
            """)
            return {
                "funds": [{**dict(f), "id": str(f["id"]), "created_at": f["created_at"].isoformat()} for f in funds],
                "allocations": [{**dict(a), "id": str(a["id"]), "fund_id": str(a["fund_id"]), "created_at": a["created_at"].isoformat()} for a in allocations],
            }
        except Exception:
            return {"funds": [], "allocations": [], "note": "Scholarship tables may not exist yet"}


@router.get("/discounts", dependencies=[Depends(require_admin)])
async def get_discounts(request: Request, limit: int = 100):
    """Promotional discount tracking."""
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch("""
                SELECT id, username, discount_type, discount_code,
                       amount_cents, description, applied_at
                FROM gkm_discounts ORDER BY applied_at DESC LIMIT $1
            """, limit)
            total = await conn.fetchval(
                "SELECT COALESCE(SUM(amount_cents), 0) FROM gkm_discounts"
            )
            return {
                "total_discounts_cents": total or 0,
                "discounts": [{**dict(r), "id": str(r["id"]), "applied_at": r["applied_at"].isoformat()} for r in rows],
            }
        except Exception:
            return {"total_discounts_cents": 0, "discounts": []}


@router.get("/sharing-activity", dependencies=[Depends(require_admin)])
async def get_sharing_activity(request: Request, days: int = 30, limit: int = 100):
    """Real-time feed of all BLE/NFC token shares."""
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        shares = await conn.fetch("""
            SELECT id, sharer_username, receiver_username, tokens_shared,
                   share_fee_cents, created_at
            FROM token_shares
            WHERE created_at >= $1
            ORDER BY created_at DESC LIMIT $2
        """, cutoff, limit)

        stats = await conn.fetchrow("""
            SELECT COUNT(*) as total_shares,
                   COALESCE(SUM(tokens_shared), 0) as total_tokens,
                   COALESCE(SUM(share_fee_cents), 0) as total_fees_cents,
                   COUNT(DISTINCT sharer_username) as unique_sharers,
                   COUNT(DISTINCT receiver_username) as unique_receivers
            FROM token_shares WHERE created_at >= $1
        """, cutoff)

        return {
            "period_days": days,
            "stats": dict(stats) if stats else {},
            "shares": [
                {**dict(s), "id": str(s["id"]), "created_at": s["created_at"].isoformat()}
                for s in shares
            ],
        }


@router.get("/health")
async def gkm_health():
    return {"status": "ok", "service": "gkm", "tax_id": GKM_TAX_ID}
