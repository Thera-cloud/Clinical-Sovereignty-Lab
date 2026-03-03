"""
Token Lab API — Admin Token Command Center

Full token management for Sovereign Command:
- View all balances across clients, coaches, families, groups
- Adjust individual token balances with audit trail
- Mass token drops (individual, family, group, selected, network-wide)
- Reward/bonus token grants
- Token usage statistics with time-series data
- Cost/profit analysis per user, family, group
"""

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.services.api_server import require_admin

logger = logging.getLogger("token_lab")

BALANCE_SYNC_CHANNEL = "nate:balance_sync"
USER_RELOAD_CHANNEL = "nate:user_reload"


async def _publish_balance_sync(request: Request, username: str, new_balance: int):
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
        logger.warning("Balance sync publish failed for %s: %s", username, e)

router = APIRouter(
    prefix="/api/token-lab",
    tags=["token-lab"],
    dependencies=[Depends(require_admin)],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TokenAdjust(BaseModel):
    username: str
    amount: int
    reason: Optional[str] = None
    idempotency_key: Optional[str] = None

class TokenReward(BaseModel):
    username: str
    amount: int
    reason: Optional[str] = "Bonus reward"

class MassDrop(BaseModel):
    scope: str  # 'individual', 'family', 'group', 'selected', 'network'
    amount: int
    target_ref: Optional[str] = None   # family_id, company_id
    usernames: Optional[List[str]] = None  # for 'selected' scope
    reason: Optional[str] = None

class CostConfig(BaseModel):
    cost_per_token: float
    price_per_token: float
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_pool(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")
    return pool


async def _log_transaction(
    conn, username: str, action: str, amount: int,
    balance_before: int, balance_after: int,
    reason: str = None, batch_id: str = None,
    initiated_by: str = "DrNevedal1",
    target_scope: str = None, target_ref: str = None
):
    await conn.execute("""
        INSERT INTO token_transactions
            (username, action, amount, balance_before, balance_after,
             reason, batch_id, initiated_by, target_scope, target_ref)
        VALUES ($1, $2, $3, $4, $5, $6, $7::uuid, $8, $9, $10)
    """, username, action, amount, balance_before, balance_after,
        reason, batch_id, initiated_by, target_scope, target_ref)


async def _get_balance(conn, username: str) -> int:
    row = await conn.fetchrow(
        "SELECT COALESCE(token_balance, 0) as bal FROM users WHERE username = $1",
        username
    )
    return row["bal"] if row else 0


async def _set_balance(conn, username: str, new_balance: int):
    await conn.execute("""
        UPDATE users
        SET token_balance = $1,
            profile_data = jsonb_set(
                COALESCE(profile_data, '{}'::jsonb),
                '{token_balance}',
                to_jsonb($1::int)
            )
        WHERE username = $2
    """, new_balance, username)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/balances")
async def get_all_balances(request: Request):
    """All user token balances with role, family, tier info."""
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                u.username,
                u.role,
                COALESCE(u.token_balance, 0) as token_balance,
                u.subscription_status,
                u.profile_data->>'name' as name,
                u.profile_data->>'tier' as tier,
                u.profile_data->>'family_id' as family_id,
                u.profile_data->>'company_id' as company_id,
                COALESCE(td.usage_today, 0) as usage_today,
                COALESCE(tm.usage_month, 0) as usage_month,
                u.family_id as family_uuid,
                COALESCE(p.total_purchased, 0) as tokens_purchased
            FROM users u
            LEFT JOIN (
                SELECT REGEXP_REPLACE(username, '^(client_|coach_|admin_)', '') as clean_user,
                       SUM(amount) as total_purchased
                FROM token_transactions
                WHERE action = 'purchase' AND source = 'token_pack'
                GROUP BY clean_user
            ) p ON p.clean_user = u.username
            LEFT JOIN (
                SELECT REGEXP_REPLACE(username, '^(client_|coach_|admin_)', '') as clean_user,
                       SUM(ABS(amount)) as usage_today
                FROM token_transactions
                WHERE created_at >= CURRENT_DATE
                  AND action IN ('deduct', 'usage') AND source IS NOT NULL
                GROUP BY clean_user
            ) td ON td.clean_user = u.username
            LEFT JOIN (
                SELECT REGEXP_REPLACE(username, '^(client_|coach_|admin_)', '') as clean_user,
                       SUM(ABS(amount)) as usage_month
                FROM token_transactions
                WHERE created_at >= date_trunc('month', CURRENT_DATE)
                  AND action IN ('deduct', 'usage') AND source IS NOT NULL
                GROUP BY clean_user
            ) tm ON tm.clean_user = u.username
            ORDER BY u.token_balance DESC NULLS LAST, u.role, u.username
        """)
        return [dict(r) for r in rows]


@router.get("/stats")
async def get_token_stats(request: Request, days: int = 30):
    """Aggregate token statistics across the network."""
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        totals = await conn.fetchrow("""
            SELECT
                COUNT(*) as total_users,
                SUM(COALESCE(token_balance, 0)) as total_tokens_in_circulation,
                AVG(COALESCE(token_balance, 0))::int as avg_balance,
                MAX(COALESCE(token_balance, 0)) as max_balance,
                MIN(COALESCE(token_balance, 0)) as min_balance,
                COUNT(*) FILTER (WHERE COALESCE(token_balance, 0) = 0) as zero_balance_count,
                COUNT(*) FILTER (WHERE COALESCE(token_balance, 0) < 0) as negative_balance_count
            FROM users
        """)

        by_role = await conn.fetch("""
            SELECT
                role,
                COUNT(*) as user_count,
                SUM(COALESCE(token_balance, 0)) as total_tokens,
                AVG(COALESCE(token_balance, 0))::int as avg_tokens
            FROM users
            GROUP BY role ORDER BY role
        """)

        by_tier = await conn.fetch("""
            SELECT
                COALESCE(profile_data->>'tier', 'UNKNOWN') as tier,
                COUNT(*) as user_count,
                SUM(COALESCE(token_balance, 0)) as total_tokens
            FROM users
            GROUP BY profile_data->>'tier' ORDER BY total_tokens DESC
        """)

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        recent_tx = await conn.fetch("""
            SELECT
                action,
                COUNT(*) as tx_count,
                SUM(amount) as total_amount,
                SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as total_added,
                SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) as total_deducted
            FROM token_transactions
            WHERE created_at >= $1
            GROUP BY action ORDER BY tx_count DESC
        """, cutoff)

        daily_activity = await conn.fetch("""
            SELECT
                created_at::date as day,
                COUNT(*) as tx_count,
                SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as tokens_added,
                SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) as tokens_deducted
            FROM token_transactions
            WHERE created_at >= $1
            GROUP BY day ORDER BY day
        """, cutoff)

        return {
            "totals": dict(totals) if totals else {},
            "by_role": [dict(r) for r in by_role],
            "by_tier": [dict(r) for r in by_tier],
            "recent_transactions": [dict(r) for r in recent_tx],
            "daily_activity": [
                {"day": str(r["day"]), "tx_count": r["tx_count"],
                 "tokens_added": r["tokens_added"], "tokens_deducted": r["tokens_deducted"]}
                for r in daily_activity
            ],
        }


@router.get("/stats/user/{username}")
async def get_user_stats(username: str, request: Request):
    """Token stats for a specific user."""
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        user = await conn.fetchrow("""
            SELECT username, role, token_balance,
                   profile_data->>'name' as name,
                   profile_data->>'tier' as tier,
                   profile_data->>'token_usage_today' as usage_today,
                   profile_data->>'token_usage_month' as usage_month,
                   profile_data->>'family_id' as family_id
            FROM users WHERE username = $1
        """, username)
        if not user:
            raise HTTPException(404, f"User {username} not found")

        txs = await conn.fetch("""
            SELECT action, amount, balance_before, balance_after,
                   reason, created_at, target_scope
            FROM token_transactions
            WHERE username = $1
            ORDER BY created_at DESC LIMIT 100
        """, username)

        return {
            "user": dict(user),
            "transactions": [
                {**dict(r), "created_at": r["created_at"].isoformat()}
                for r in txs
            ],
        }


@router.get("/families")
async def get_family_token_stats(request: Request):
    """Token stats grouped by family."""
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                COALESCE(profile_data->>'family_id', 'NO_FAMILY') as family_id,
                COUNT(*) as member_count,
                SUM(COALESCE(token_balance, 0)) as total_tokens,
                AVG(COALESCE(token_balance, 0))::int as avg_tokens,
                array_agg(username ORDER BY username) as members
            FROM users
            WHERE role = 'CLIENT'
            GROUP BY 1
            ORDER BY total_tokens DESC
        """)
        return [dict(r) for r in rows]


@router.get("/groups")
async def get_group_token_stats(request: Request):
    """Token stats grouped by company/group."""
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                COALESCE(profile_data->>'company_id', 'NO_GROUP') as company_id,
                COALESCE(profile_data->>'company_name', 'Ungrouped') as company_name,
                COUNT(*) as member_count,
                SUM(COALESCE(token_balance, 0)) as total_tokens,
                AVG(COALESCE(token_balance, 0))::int as avg_tokens,
                array_agg(username ORDER BY username) as members
            FROM users
            GROUP BY 1, 2
            ORDER BY total_tokens DESC
        """)
        return [dict(r) for r in rows]


@router.post("/adjust")
async def adjust_balance(body: TokenAdjust, request: Request):
    """Adjust a single user's token balance (add or subtract)."""
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM users WHERE username = $1", body.username
        )
        if not exists:
            raise HTTPException(404, f"User '{body.username}' not found")

        if body.idempotency_key:
            dup = await conn.fetchval(
                "SELECT 1 FROM token_transactions WHERE batch_id = $1::uuid",
                body.idempotency_key
            )
            if dup:
                bal = await _get_balance(conn, body.username)
                return {"username": body.username, "before": bal, "after": bal, "deduplicated": True}

        async with conn.transaction():
            before = await _get_balance(conn, body.username)
            after = before + body.amount
            if after < 0:
                after = 0
            await _set_balance(conn, body.username, after)
            await _log_transaction(
                conn, body.username, "adjust", body.amount,
                before, after, body.reason,
                batch_id=body.idempotency_key,
                target_scope="individual"
            )
        await _publish_balance_sync(request, body.username, after)
        return {"username": body.username, "before": before, "after": after}


@router.post("/reward")
async def reward_tokens(body: TokenReward, request: Request):
    """Grant bonus/reward tokens to a user."""
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM users WHERE username = $1", body.username
        )
        if not exists:
            raise HTTPException(404, f"User '{body.username}' not found")
        async with conn.transaction():
            before = await _get_balance(conn, body.username)
            after = before + body.amount
            await _set_balance(conn, body.username, after)
            await _log_transaction(
                conn, body.username, "reward", body.amount,
                before, after, body.reason,
                target_scope="individual"
            )
        await _publish_balance_sync(request, body.username, after)
        return {"username": body.username, "before": before, "after": after, "reward": body.amount}


@router.post("/mass-drop")
async def mass_token_drop(body: MassDrop, request: Request):
    """Mass token operation across users by scope."""
    pool = await _get_pool(request)
    batch_id = str(uuid.uuid4())
    results = []

    async with pool.acquire() as conn:
        if body.scope == "individual":
            if not body.usernames or len(body.usernames) != 1:
                raise HTTPException(400, "Provide exactly one username for individual scope")
            exists = await conn.fetchval(
                "SELECT 1 FROM users WHERE username = $1", body.usernames[0]
            )
            if not exists:
                raise HTTPException(404, f"User '{body.usernames[0]}' not found")
            usernames = body.usernames

        elif body.scope == "selected":
            if not body.usernames:
                raise HTTPException(400, "Provide usernames for selected scope")
            found = await conn.fetch(
                "SELECT username FROM users WHERE username = ANY($1::text[])", body.usernames
            )
            found_set = {r["username"] for r in found}
            missing = [u for u in body.usernames if u not in found_set]
            if missing:
                raise HTTPException(404, f"Users not found: {', '.join(missing)}")
            usernames = body.usernames

        elif body.scope == "family":
            if not body.target_ref:
                raise HTTPException(400, "Provide target_ref (family_id) for family scope")
            rows = await conn.fetch(
                "SELECT username FROM users WHERE profile_data->>'family_id' = $1",
                body.target_ref
            )
            usernames = [r["username"] for r in rows]
            if not usernames:
                raise HTTPException(404, f"No users found in family {body.target_ref}")

        elif body.scope == "group":
            if not body.target_ref:
                raise HTTPException(400, "Provide target_ref (company_id) for group scope")
            rows = await conn.fetch(
                "SELECT username FROM users WHERE profile_data->>'company_id' = $1",
                body.target_ref
            )
            usernames = [r["username"] for r in rows]
            if not usernames:
                raise HTTPException(404, f"No users found in group {body.target_ref}")

        elif body.scope == "network":
            rows = await conn.fetch("SELECT username FROM users")
            usernames = [r["username"] for r in rows]

        else:
            raise HTTPException(400, f"Invalid scope: {body.scope}")

        async with conn.transaction():
            for uname in usernames:
                before = await _get_balance(conn, uname)
                after = body.amount  # mass drop SETS the value
                await _set_balance(conn, uname, after)
                await _log_transaction(
                    conn, uname, "mass_drop", after - before,
                    before, after, body.reason, batch_id,
                    target_scope=body.scope, target_ref=body.target_ref
                )
                results.append({"username": uname, "before": before, "after": after})

    for r in results:
        await _publish_balance_sync(request, r["username"], r["after"])

    return {
        "batch_id": batch_id,
        "scope": body.scope,
        "target_ref": body.target_ref,
        "amount_set": body.amount,
        "users_affected": len(results),
        "results": results,
    }


@router.get("/transactions")
async def get_transactions(
    request: Request, limit: int = 100, action: Optional[str] = None,
    username: Optional[str] = None
):
    """Transaction history with optional filters."""
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        conditions = []
        params = []
        idx = 1
        if action:
            conditions.append(f"action = ${idx}")
            params.append(action)
            idx += 1
        if username:
            conditions.append(f"username = ${idx}")
            params.append(username)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(min(limit, 500))

        rows = await conn.fetch(f"""
            SELECT id, username, action, amount, balance_before, balance_after,
                   reason, batch_id, initiated_by, target_scope, target_ref, created_at
            FROM token_transactions
            {where}
            ORDER BY created_at DESC
            LIMIT ${idx}
        """, *params)

        return [
            {**dict(r), "id": str(r["id"]),
             "batch_id": str(r["batch_id"]) if r["batch_id"] else None,
             "created_at": r["created_at"].isoformat()}
            for r in rows
        ]


@router.get("/cost-analysis")
async def get_cost_analysis(request: Request, days: int = 30):
    """Cost and profit analysis for token usage."""
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        config = await conn.fetchrow(
            "SELECT cost_per_token, price_per_token FROM token_cost_config ORDER BY effective_from DESC LIMIT 1"
        )
        cost_per = float(config["cost_per_token"]) if config else 0.0001
        price_per = float(config["price_per_token"]) if config else 0.001

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        by_user = await conn.fetch("""
            SELECT
                username,
                SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) as tokens_consumed,
                SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as tokens_granted,
                COUNT(*) as tx_count
            FROM token_transactions
            WHERE created_at >= $1
            GROUP BY username
            ORDER BY tokens_consumed DESC
        """, cutoff)

        user_analysis = []
        total_consumed = 0
        total_granted = 0
        for r in by_user:
            consumed = r["tokens_consumed"] or 0
            granted = r["tokens_granted"] or 0
            total_consumed += consumed
            total_granted += granted
            user_analysis.append({
                "username": r["username"],
                "tokens_consumed": consumed,
                "tokens_granted": granted,
                "cost": round(consumed * cost_per, 4),
                "revenue": round(consumed * price_per, 4),
                "profit": round(consumed * (price_per - cost_per), 4),
                "tx_count": r["tx_count"],
            })

        network_totals = await conn.fetchrow("""
            SELECT
                SUM(COALESCE(token_balance, 0)) as total_outstanding,
                COUNT(*) as total_users
            FROM users
        """)

        return {
            "period_days": days,
            "cost_per_token": cost_per,
            "price_per_token": price_per,
            "margin": round((price_per - cost_per) / price_per * 100, 1) if price_per > 0 else 0,
            "period_summary": {
                "total_consumed": total_consumed,
                "total_granted": total_granted,
                "total_cost": round(total_consumed * cost_per, 2),
                "total_revenue": round(total_consumed * price_per, 2),
                "total_profit": round(total_consumed * (price_per - cost_per), 2),
            },
            "outstanding_liability": {
                "total_tokens": network_totals["total_outstanding"] if network_totals else 0,
                "total_cost_if_consumed": round((network_totals["total_outstanding"] or 0) * cost_per, 2),
            },
            "by_user": user_analysis,
        }


@router.post("/cost-config")
async def update_cost_config(body: CostConfig, request: Request):
    """Update token cost/price configuration."""
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO token_cost_config (cost_per_token, price_per_token, notes)
            VALUES ($1, $2, $3)
        """, body.cost_per_token, body.price_per_token, body.notes)
        return {
            "status": "updated",
            "cost_per_token": body.cost_per_token,
            "price_per_token": body.price_per_token,
        }


@router.get("/usage-by-source")
async def get_usage_by_source(
    request: Request, days: int = 30,
    username: Optional[str] = None,
    family_id: Optional[str] = None,
    group_id: Optional[str] = None,
):
    """Token consumption breakdown by source (ai_chat, sanctuary_ai, etc.)."""
    pool = await _get_pool(request)
    async with pool.acquire() as conn:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        conditions = ["t.created_at >= $1", "t.source IS NOT NULL", "t.action IN ('deduct', 'usage')"]
        params: list = [cutoff]
        idx = 2

        if username:
            conditions.append(f"t.username = ${idx}")
            params.append(username)
            idx += 1
        elif family_id:
            conditions.append(f"u.profile_data->>'family_id' = ${idx}")
            params.append(family_id)
            idx += 1
        elif group_id:
            conditions.append(f"u.profile_data->>'company_id' = ${idx}")
            params.append(group_id)
            idx += 1

        where = " AND ".join(conditions)
        need_join = family_id or group_id

        if need_join:
            query = f"""
                SELECT COALESCE(t.source, 'unknown') as source,
                       SUM(ABS(t.amount)) as total_tokens,
                       COUNT(*) as tx_count
                FROM token_transactions t
                JOIN users u ON u.username = t.username
                WHERE {where}
                GROUP BY t.source
                ORDER BY total_tokens DESC
            """
        else:
            query = f"""
                SELECT COALESCE(source, 'unknown') as source,
                       SUM(ABS(amount)) as total_tokens,
                       COUNT(*) as tx_count
                FROM token_transactions t
                WHERE {where}
                GROUP BY source
                ORDER BY total_tokens DESC
            """

        sources = await conn.fetch(query, *params)

        top_users_query = f"""
            SELECT t.username, COALESCE(t.source, 'unknown') as source,
                   SUM(ABS(t.amount)) as tokens
            FROM token_transactions t
            {"JOIN users u ON u.username = t.username" if need_join else ""}
            WHERE {where}
            GROUP BY t.username, t.source
            ORDER BY tokens DESC
            LIMIT 50
        """
        top_users_raw = await conn.fetch(top_users_query, *params)

        top_by_source = {}
        for r in top_users_raw:
            src = r["source"]
            if src not in top_by_source:
                top_by_source[src] = []
            if len(top_by_source[src]) < 5:
                top_by_source[src].append({"username": r["username"], "tokens": r["tokens"]})

        CANONICAL_SOURCES = ["ai_chat", "sanctuary_ai", "group_coaching", "private_coaching"]
        db_map = {r["source"]: r for r in sources}

        result = []
        for src in CANONICAL_SOURCES:
            if src in db_map:
                result.append({
                    "source": src,
                    "total_tokens": db_map[src]["total_tokens"],
                    "tx_count": db_map[src]["tx_count"],
                    "top_users": top_by_source.get(src, []),
                })
            else:
                result.append({
                    "source": src,
                    "total_tokens": 0,
                    "tx_count": 0,
                    "top_users": [],
                })

        for r in sources:
            if r["source"] not in CANONICAL_SOURCES:
                result.append({
                    "source": r["source"],
                    "total_tokens": r["total_tokens"],
                    "tx_count": r["tx_count"],
                    "top_users": top_by_source.get(r["source"], []),
                })

        role_rows = await conn.fetch(f"""
            SELECT u.role, COALESCE(t.source, 'unknown') as source,
                   SUM(ABS(t.amount)) as total_tokens, COUNT(*) as tx_count
            FROM token_transactions t
            JOIN users u ON u.username = t.username
            WHERE t.created_at >= $1 AND t.source IS NOT NULL
                  AND t.action IN ('deduct', 'usage')
            GROUP BY u.role, t.source
            ORDER BY u.role, total_tokens DESC
        """, cutoff)

        role_breakdown = {}
        for r in role_rows:
            role = r["role"]
            if role not in role_breakdown:
                role_breakdown[role] = []
            role_breakdown[role].append({
                "source": r["source"],
                "total_tokens": r["total_tokens"],
                "tx_count": r["tx_count"],
            })

        return {"sources": result, "by_role": role_breakdown}


@router.get("/health")
async def token_lab_health():
    return {"status": "ok", "service": "token-lab"}
