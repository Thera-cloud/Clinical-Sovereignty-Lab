"""
Monetization Control API

Admin-only control surface for:
- pricing predictability drift detection
- depth mix visibility (core vs deep_noetic)
- Stripe/Apple entitlement reconciliation
- API + DOJO commercial performance snapshots
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.routers.billing import PLAN_DETAILS
from app.services.api_server import require_admin
from app.services.billing.tier_enforcement import TIER_LIMITS, _resolve_tier_key

logger = logging.getLogger("monetization_control_api")

router = APIRouter(
    prefix="/api/monetization-control",
    tags=["Monetization Control"],
    dependencies=[Depends(require_admin)],
)


DISPLAY_TO_ENFORCED_KEY = {
    "COACH_ONLY": {
        "ai_minutes": "ai_session_minutes",
        "coach_sessions": "coach_sessions",
    },
    "TRIAL": {
        "ai_minutes": "ai_session_minutes",
        "coach_sessions": "coach_sessions",
        "legacy_vault_gb": "legacy_vault_gb",
        "nevedal_per_month": "nevedal_reports",
        "foresight_per_month": "foresight_reports",
        "me2me_avatar_hours": "me2me_hours",
    },
    "STANDARD": {
        "ai_minutes": "ai_session_minutes",
        "coach_sessions": "coach_sessions",
        "legacy_vault_gb": "legacy_vault_gb",
        "nevedal_per_month": "nevedal_reports",
        "foresight_per_month": "foresight_reports",
        "me2me_avatar_hours": "me2me_hours",
    },
    "TOP_TIER": {
        "ai_minutes": "ai_session_minutes",
        "coach_sessions": "coach_sessions",
        "legacy_vault_gb": "legacy_vault_gb",
        "nevedal_per_month": "nevedal_reports",
        "foresight_per_month": "foresight_reports",
        "me2me_avatar_hours": "me2me_hours",
    },
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _classify_depth(source: str) -> str:
    s = (source or "").strip().lower()
    if s in {
        "ai_chat",
        "sanctuary_ai",
        "usage",
        "deduct",
        "token_share",
        "admin_adjust",
        "sharing_reward",
    }:
        return "core"
    if s in {
        "private_coaching",
        "group_coaching",
        "foresight_report",
        "nevedal_report",
        "me2me_avatar",
        "archivist_chapter",
        "deep_noetic",
        "odpe",
    }:
        return "deep_noetic"
    return "core"


async def _table_exists(conn, table_name: str) -> bool:
    row = await conn.fetchrow(
        """
        SELECT EXISTS(
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = $1
        ) AS exists
        """,
        table_name,
    )
    return bool(row and row["exists"])


def _plan_to_enforced_key(plan_key: str) -> str:
    # PLAN_DETAILS keys -> tier_enforcement canonical keys
    if plan_key == "STANDARD":
        return "inner_chamber"
    if plan_key == "TOP_TIER":
        return "sovereign_circle"
    if plan_key == "TRIAL":
        return "threshold"
    if plan_key == "COACH_ONLY":
        return "coach_only"
    return _resolve_tier_key(plan_key.lower())


class PricingProposalRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    proposal_type: str = Field(default="pricing_rules", min_length=3, max_length=50)
    payload: Dict[str, Any] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=1000)


@router.get("/health")
async def monetization_control_health():
    return {
        "status": "ok",
        "service": "monetization_control",
        "timestamp": _utc_now_iso(),
    }


@router.get("/overview")
async def monetization_overview(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    now = datetime.now(timezone.utc)
    last_24h = now - timedelta(hours=24)
    mtd_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    core_events = 0
    deep_events = 0
    api_monthly_usage = 0
    dojo_sessions = 0
    mrr_estimate_cents = 0
    arr_estimate_cents = 0

    async with pool.acquire() as conn:
        if await _table_exists(conn, "token_transactions"):
            rows = await conn.fetch(
                """
                SELECT source, COUNT(*) AS c
                FROM token_transactions
                WHERE created_at >= $1
                GROUP BY source
                """,
                last_24h,
            )
            for r in rows:
                depth = _classify_depth(r["source"])
                if depth == "deep_noetic":
                    deep_events += _to_int(r["c"])
                else:
                    core_events += _to_int(r["c"])

        if await _table_exists(conn, "api_keys"):
            api_row = await conn.fetchrow(
                "SELECT COALESCE(SUM(monthly_usage), 0) AS total FROM api_keys WHERE active = true"
            )
            api_monthly_usage = _to_int(api_row["total"] if api_row else 0)

            # Conservative MRR estimate from current API tier catalog (existing values)
            price_rows = await conn.fetch(
                """
                SELECT tier, COUNT(*) AS c
                FROM api_keys
                WHERE active = true
                GROUP BY tier
                """
            )
            price_map = {"FREE": 0, "STARTER": 2900, "GROWTH": 19900, "ENTERPRISE": 0}
            for p in price_rows:
                mrr_estimate_cents += price_map.get((p["tier"] or "").upper(), 0) * _to_int(p["c"])

        if await _table_exists(conn, "coaching_mesh_sessions"):
            dojo_row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS c
                FROM coaching_mesh_sessions
                WHERE created_at >= $1
                """,
                mtd_start,
            )
            dojo_sessions = _to_int(dojo_row["c"] if dojo_row else 0)

    total_events = core_events + deep_events
    deep_ratio = round((deep_events / total_events) if total_events > 0 else 0.0, 4)
    arr_estimate_cents = mrr_estimate_cents * 12

    # Placeholder margin model until full rating engine lands.
    # Deep events are assumed to be more expensive than core.
    est_cost_units = core_events + (deep_events * 3)
    est_revenue_units = max(1, total_events * 2)
    margin_pct = round(max(0.0, 1.0 - (est_cost_units / est_revenue_units)) * 100.0, 2)
    cost_alert = "ok" if margin_pct >= 50 else "watch"

    return {
        "status": "ok",
        "window": {"last_24h": last_24h.isoformat(), "mtd": mtd_start.isoformat()},
        "revenue": {
            "mrr_estimate_cents": mrr_estimate_cents,
            "arr_estimate_cents": arr_estimate_cents,
        },
        "usage": {
            "core_events": core_events,
            "deep_noetic_events": deep_events,
            "deep_ratio": deep_ratio,
            "api_monthly_usage": api_monthly_usage,
            "dojo_sessions_mtd": dojo_sessions,
        },
        "margin": {
            "estimated_gross_margin_pct": margin_pct,
            "cost_alert": cost_alert,
        },
        "updated_at": _utc_now_iso(),
    }


@router.get("/predictability")
async def pricing_predictability():
    drifts: List[Dict[str, Any]] = []

    for plan_key, mapping in DISPLAY_TO_ENFORCED_KEY.items():
        plan = PLAN_DETAILS.get(plan_key, {})
        enforced_tier_key = _plan_to_enforced_key(plan_key)
        enforced = TIER_LIMITS.get(enforced_tier_key, {})

        for display_key, enforced_key in mapping.items():
            if display_key not in plan or enforced_key not in enforced:
                continue
            display_value = plan.get(display_key)
            enforced_value = enforced.get(enforced_key)
            if display_value != enforced_value:
                drifts.append(
                    {
                        "tier": plan_key,
                        "display_key": display_key,
                        "enforced_key": enforced_key,
                        "display_value": display_value,
                        "enforced_value": enforced_value,
                    }
                )

    status = "ok" if not drifts else "drift_detected"
    return {
        "status": status,
        "drift_count": len(drifts),
        "drifts": drifts if drifts else [{"note": "No plan/enforcement drift detected"}],
        "last_checked_at": _utc_now_iso(),
    }


@router.get("/credits/depth-mix")
async def credits_depth_mix(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    since = datetime.now(timezone.utc) - timedelta(days=days)
    total_core = 0
    total_deep = 0
    by_channel: Dict[str, Dict[str, Any]] = {}
    by_tenant: Dict[str, Dict[str, Any]] = {}

    async with pool.acquire() as conn:
        used_usage_events = False
        if await _table_exists(conn, "usage_events"):
            rows = await conn.fetch(
                """
                SELECT channel, COALESCE(tenant_id, 'unknown') AS tenant_id, depth_class, COUNT(*) AS c
                FROM usage_events
                WHERE occurred_at >= $1
                GROUP BY channel, tenant_id, depth_class
                """,
                since,
            )
            if rows:
                used_usage_events = True
            for r in rows:
                channel = (r["channel"] or "unknown").lower()
                tenant = str(r["tenant_id"] or "unknown")
                depth = (r["depth_class"] or "core").lower()
                c = _to_int(r["c"])

                if channel not in by_channel:
                    by_channel[channel] = {"channel": channel, "core": 0, "deep_noetic": 0}
                if tenant not in by_tenant:
                    by_tenant[tenant] = {"tenant_id": tenant, "core": 0, "deep_noetic": 0}

                if depth == "deep_noetic":
                    by_channel[channel]["deep_noetic"] += c
                    by_tenant[tenant]["deep_noetic"] += c
                    total_deep += c
                else:
                    by_channel[channel]["core"] += c
                    by_tenant[tenant]["core"] += c
                    total_core += c

        # Fall back to token_transactions if usage_events is missing OR exists but empty.
        if not used_usage_events and await _table_exists(conn, "token_transactions"):
            # Fallback while unified ledger is in rollout.
            rows = await conn.fetch(
                """
                SELECT COALESCE(source, 'unknown') AS source, COUNT(*) AS c
                FROM token_transactions
                WHERE created_at >= $1
                GROUP BY source
                """,
                since,
            )
            for r in rows:
                channel = "token_transactions"
                source = (r["source"] or "unknown").lower()
                tenant = "global"
                depth = _classify_depth(source)
                c = _to_int(r["c"])
                if channel not in by_channel:
                    by_channel[channel] = {"channel": channel, "core": 0, "deep_noetic": 0}
                if tenant not in by_tenant:
                    by_tenant[tenant] = {"tenant_id": tenant, "core": 0, "deep_noetic": 0}
                if depth == "deep_noetic":
                    by_channel[channel]["deep_noetic"] += c
                    by_tenant[tenant]["deep_noetic"] += c
                    total_deep += c
                else:
                    by_channel[channel]["core"] += c
                    by_tenant[tenant]["core"] += c
                    total_core += c

    total = total_core + total_deep
    by_channel_list = []
    for _, v in by_channel.items():
        subtotal = _to_int(v["core"]) + _to_int(v["deep_noetic"])
        v["deep_noetic_pct"] = round((_to_float(v["deep_noetic"]) / subtotal), 4) if subtotal else 0.0
        by_channel_list.append(v)
    by_channel_list.sort(key=lambda x: x["deep_noetic"], reverse=True)

    top_tenants = []
    for _, v in by_tenant.items():
        total_t = _to_int(v["core"]) + _to_int(v["deep_noetic"])
        deep_pct = (_to_float(v["deep_noetic"]) / total_t) if total_t else 0.0
        if deep_pct >= 0.7:
            cost_band = "high"
        elif deep_pct >= 0.3:
            cost_band = "medium"
        else:
            cost_band = "low"
        top_tenants.append(
            {
                "tenant_id": v["tenant_id"],
                "core": v["core"],
                "deep_noetic": v["deep_noetic"],
                "cost_band": cost_band,
            }
        )
    top_tenants.sort(key=lambda x: (x["deep_noetic"] + x["core"]), reverse=True)

    return {
        "status": "ok",
        "days": days,
        "totals": {
            "core": total_core,
            "deep_noetic": total_deep,
            "total": total,
            "deep_noetic_pct": round((_to_float(total_deep) / total), 4) if total else 0.0,
        },
        "by_channel": by_channel_list if by_channel_list else [{"channel": "none", "core": 0, "deep_noetic": 0, "deep_noetic_pct": 0.0}],
        "top_tenants": top_tenants[:20] if top_tenants else [{"tenant_id": "none", "core": 0, "deep_noetic": 0, "cost_band": "low"}],
    }


@router.get("/rails/reconciliation")
async def rails_reconciliation(request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    checked = 0
    matched = 0
    mismatched = 0
    pending = 0
    stale = 0
    mismatch_rows: List[Dict[str, Any]] = []
    last_reconciled_at = None

    async with pool.acquire() as conn:
        has_conflicts = await _table_exists(conn, "entitlement_reconciliation_conflicts")
        has_snapshots = await _table_exists(conn, "entitlement_snapshots")
        if has_conflicts:
            c_rows = await conn.fetch(
                """
                SELECT account_id, stripe_state, apple_state, effective_state, reason, status, created_at
                FROM entitlement_reconciliation_conflicts
                ORDER BY created_at DESC
                LIMIT 100
                """
            )
            for r in c_rows:
                checked += 1
                status = (r["status"] or "").lower()
                if status in {"open", "pending"}:
                    pending += 1
                if status == "resolved":
                    matched += 1
                else:
                    mismatched += 1
                mismatch_rows.append(
                    {
                        "account_id": str(r["account_id"]),
                        "stripe_state": r["stripe_state"] or "unknown",
                        "apple_state": r["apple_state"] or "unknown",
                        "effective_state": r["effective_state"] or "unknown",
                        "reason": r["reason"] or "unspecified",
                    }
                )
            if c_rows:
                last_reconciled_at = c_rows[0]["created_at"].isoformat() if c_rows[0]["created_at"] else None

        if has_snapshots:
            stale_row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS c
                FROM entitlement_snapshots
                WHERE is_active = true
                  AND (effective_to IS NOT NULL AND effective_to < NOW())
                """
            )
            stale = _to_int(stale_row["c"] if stale_row else 0)

        # Zero conflicts means no mismatches have ever been detected — report accurately.
        # Do NOT fabricate matched=1; that implies a reconciliation pass ran and succeeded.

    return {
        "status": "ok",
        "summary": {
            "checked": checked,
            "matched": matched,
            "mismatched": mismatched,
            "pending": pending,
            "stale": stale,
        },
        "mismatches": mismatch_rows if mismatch_rows else [{"account_id": "none", "stripe_state": "none", "apple_state": "none", "effective_state": "none", "reason": "No mismatches"}],
        "last_reconciled_at": last_reconciled_at or _utc_now_iso(),
    }


@router.get("/api-dojo/performance")
async def api_dojo_performance(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    since = datetime.now(timezone.utc) - timedelta(days=days)
    tier_usage: List[Dict[str, Any]] = []
    dojo_verticals: List[Dict[str, Any]] = []
    effective_arpu_cents = 0
    overage_capture_pct = 0.0

    async with pool.acquire() as conn:
        if await _table_exists(conn, "api_keys"):
            rows = await conn.fetch(
                """
                SELECT tier, COUNT(*) AS key_count, COALESCE(SUM(monthly_usage), 0) AS total_usage
                FROM api_keys
                WHERE active = true
                GROUP BY tier
                ORDER BY tier
                """
            )
            tier_prices = {"FREE": 0, "STARTER": 2900, "GROWTH": 19900, "ENTERPRISE": 0}
            total_cents = 0
            total_keys = 0
            for r in rows:
                tier = (r["tier"] or "FREE").upper()
                key_count = _to_int(r["key_count"])
                usage = _to_int(r["total_usage"])
                tier_usage.append({"tier": tier, "key_count": key_count, "monthly_usage": usage})
                total_cents += tier_prices.get(tier, 0) * key_count
                total_keys += key_count
            effective_arpu_cents = int(total_cents / total_keys) if total_keys else 0

        if await _table_exists(conn, "coaching_mesh_sessions"):
            rows = await conn.fetch(
                """
                SELECT COALESCE(session_type, 'unknown') AS session_type, COUNT(*) AS c
                FROM coaching_mesh_sessions
                WHERE created_at >= $1
                GROUP BY session_type
                ORDER BY c DESC
                LIMIT 20
                """,
                since,
            )
            # Conservative proxy: dojo session traffic is deep_noetic-heavy.
            for r in rows:
                c = _to_int(r["c"])
                dojo_verticals.append(
                    {
                        "vertical": (r["session_type"] or "unknown").lower(),
                        "sessions": c,
                        "deep_noetic_ratio": 0.9 if c > 0 else 0.0,
                        "revenue_cents": c * 500,  # placeholder proxy until unified rating.
                    }
                )

        if await _table_exists(conn, "usage_ratings"):
            o_row = await conn.fetchrow(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN credits_burned > 0 THEN 1 ELSE 0 END), 0) AS rated_rows,
                    COALESCE(SUM(CASE WHEN margin_band IN ('medium','high') THEN 1 ELSE 0 END), 0) AS healthy_rows
                FROM usage_ratings
                WHERE rated_at >= $1
                """,
                since,
            )
            rated_rows = _to_int(o_row["rated_rows"] if o_row else 0)
            healthy_rows = _to_int(o_row["healthy_rows"] if o_row else 0)
            overage_capture_pct = round((healthy_rows / rated_rows) * 100.0, 2) if rated_rows > 0 else 0.0

    recommendations = []
    if effective_arpu_cents < 5000:
        recommendations.append("Raise API value signaling for moat-backed calls (ODPE/C_emo/crystal) before changing list prices.")
    else:
        recommendations.append("Current API ARPU supports phased moat-tier overlay rollout.")
    if dojo_verticals:
        recommendations.append("Prioritize DOJO verticals with highest sessions for near-term deep_noetic revenue expansion.")
    else:
        recommendations.append("Instrument DOJO revenue attribution for clearer expansion ranking.")
    if overage_capture_pct < 60:
        recommendations.append("Improve overage capture controls with budget alerts and effective-at policy updates.")
    else:
        recommendations.append("Overage capture health is acceptable for canary expansion.")

    return {
        "status": "ok",
        "api": {
            "tier_usage": tier_usage if tier_usage else [{"tier": "FREE", "key_count": 0, "monthly_usage": 0}],
            "effective_arpu_cents": effective_arpu_cents,
            "overage_capture_pct": overage_capture_pct,
        },
        "dojo": {
            "verticals": dojo_verticals if dojo_verticals else [{"vertical": "none", "sessions": 0, "deep_noetic_ratio": 0.0, "revenue_cents": 0}],
        },
        "recommendations": recommendations if recommendations else ["No recommendations available"],
    }


@router.get("/entitlements/{account_id}")
async def get_entitlements(account_id: str, request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    snapshots: List[Dict[str, Any]] = []
    async with pool.acquire() as conn:
        if await _table_exists(conn, "entitlement_snapshots"):
            rows = await conn.fetch(
                """
                SELECT source_rail, source_ref, entitlement_json, effective_from, effective_to, is_active
                FROM entitlement_snapshots
                WHERE account_id = $1
                ORDER BY effective_from DESC
                LIMIT 50
                """,
                account_id,
            )
            for r in rows:
                snapshots.append(
                    {
                        "source_rail": r["source_rail"],
                        "source_ref": r["source_ref"],
                        "entitlement": r["entitlement_json"] or {},
                        "effective_from": r["effective_from"].isoformat() if r["effective_from"] else None,
                        "effective_to": r["effective_to"].isoformat() if r["effective_to"] else None,
                        "is_active": bool(r["is_active"]),
                    }
                )

    effective_state = "none"
    if any(s.get("is_active") for s in snapshots):
        effective_state = "active"
    return {
        "status": "ok",
        "account_id": account_id,
        "effective_state": effective_state,
        "snapshots": snapshots if snapshots else [{"source_rail": "none", "source_ref": "", "entitlement": {}, "effective_from": None, "effective_to": None, "is_active": False}],
    }


@router.post("/reconcile/{account_id}")
async def reconcile_account(account_id: str, request: Request):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    # Read-only reconciliation pass for now.
    # It evaluates latest Stripe/Apple states from snapshots and records a conflict row if needed.
    async with pool.acquire() as conn:
        if not await _table_exists(conn, "entitlement_snapshots"):
            return {
                "status": "ok",
                "account_id": account_id,
                "reconciled": False,
                "reason": "entitlement_snapshots table missing",
                "timestamp": _utc_now_iso(),
            }
        if not await _table_exists(conn, "entitlement_reconciliation_conflicts"):
            return {
                "status": "ok",
                "account_id": account_id,
                "reconciled": False,
                "reason": "entitlement_reconciliation_conflicts table missing",
                "timestamp": _utc_now_iso(),
            }

        rows = await conn.fetch(
            """
            SELECT source_rail, entitlement_json, effective_from, is_active
            FROM entitlement_snapshots
            WHERE account_id = $1
            ORDER BY effective_from DESC
            LIMIT 20
            """,
            account_id,
        )
        stripe_state = "none"
        apple_state = "none"
        effective_state = "none"

        for r in rows:
            rail = (r["source_rail"] or "").lower()
            active = bool(r["is_active"])
            if rail == "stripe" and active and stripe_state == "none":
                stripe_state = "active"
            if rail == "apple" and active and apple_state == "none":
                apple_state = "active"
            if active:
                effective_state = "active"

        reason = "matched"
        status = "resolved"
        if stripe_state != apple_state:
            reason = "stripe_apple_state_mismatch"
            status = "open"

            # Only insert a new conflict if no open/pending conflict already exists for this account
            # with the same state combination. Prevents duplicate rows on repeated reconcile calls.
            existing = await conn.fetchrow(
                """
                SELECT id FROM entitlement_reconciliation_conflicts
                WHERE account_id = $1
                  AND stripe_state = $2
                  AND apple_state = $3
                  AND status IN ('open', 'pending')
                LIMIT 1
                """,
                account_id,
                stripe_state,
                apple_state,
            )
            if not existing:
                await conn.execute(
                    """
                    INSERT INTO entitlement_reconciliation_conflicts
                    (account_id, stripe_state, apple_state, effective_state, reason, status, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, NOW())
                    """,
                    account_id,
                    stripe_state,
                    apple_state,
                    effective_state,
                    reason,
                    status,
                )

    return {
        "status": "ok",
        "account_id": account_id,
        "reconciled": True,
        "stripe_state": stripe_state,
        "apple_state": apple_state,
        "effective_state": effective_state,
        "result": status,
        "reason": reason,
        "timestamp": _utc_now_iso(),
    }


@router.get("/reconcile/conflicts")
async def list_reconcile_conflicts(
    request: Request,
    status: str = Query(default="open"),
    limit: int = Query(default=100, ge=1, le=500),
):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    conflicts: List[Dict[str, Any]] = []
    async with pool.acquire() as conn:
        if await _table_exists(conn, "entitlement_reconciliation_conflicts"):
            rows = await conn.fetch(
                """
                SELECT id, account_id, stripe_state, apple_state, effective_state, reason, status, created_at, resolved_at, resolved_by
                FROM entitlement_reconciliation_conflicts
                WHERE status = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                status,
                limit,
            )
            for r in rows:
                conflicts.append(
                    {
                        "id": str(r["id"]),
                        "account_id": str(r["account_id"]),
                        "stripe_state": r["stripe_state"],
                        "apple_state": r["apple_state"],
                        "effective_state": r["effective_state"],
                        "reason": r["reason"],
                        "status": r["status"],
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                        "resolved_at": r["resolved_at"].isoformat() if r["resolved_at"] else None,
                        "resolved_by": r["resolved_by"],
                    }
                )

    return {
        "status": "ok",
        "conflicts": conflicts if conflicts else [{"id": "none", "account_id": "none", "reason": "No conflicts", "status": status}],
        "count": len(conflicts),
    }


@router.post("/reconcile/conflicts/{conflict_id}/resolve")
async def resolve_reconcile_conflict(
    conflict_id: str,
    request: Request,
    current_user: Dict[str, Any] = Depends(require_admin),
):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    admin = str(current_user.get("username") or current_user.get("name") or "admin")

    async with pool.acquire() as conn:
        if not await _table_exists(conn, "entitlement_reconciliation_conflicts"):
            raise HTTPException(503, "Conflict table unavailable")

        row = await conn.fetchrow(
            """
            UPDATE entitlement_reconciliation_conflicts
            SET status = 'resolved', resolved_at = NOW(), resolved_by = $2
            WHERE id::text = $1
            RETURNING id, account_id
            """,
            conflict_id,
            admin,
        )
        if not row:
            raise HTTPException(404, "Conflict not found")

    return {
        "status": "ok",
        "resolved": True,
        "conflict_id": str(row["id"]),
        "account_id": str(row["account_id"]),
        "resolved_by": admin,
        "resolved_at": _utc_now_iso(),
    }


@router.post("/pricing/proposals")
async def create_pricing_proposal(
    body: PricingProposalRequest,
    request: Request,
    current_user: Dict[str, Any] = Depends(require_admin),
):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    proposer = str(current_user.get("username") or current_user.get("name") or "admin")
    async with pool.acquire() as conn:
        if not await _table_exists(conn, "pricing_change_proposals"):
            raise HTTPException(503, "Proposal table unavailable")
        row = await conn.fetchrow(
            """
            INSERT INTO pricing_change_proposals
            (proposal_type, title, payload_json, status, proposed_by, notes, created_at)
            VALUES ($1, $2, $3::jsonb, 'proposed', $4, $5, NOW())
            RETURNING id, status
            """,
            body.proposal_type,
            body.title,
            body.payload,
            proposer,
            body.notes,
        )

    return {
        "status": "ok",
        "proposal_id": str(row["id"]),
        "proposal_status": row["status"],
        "proposed_by": proposer,
        "created_at": _utc_now_iso(),
    }


@router.post("/pricing/proposals/{proposal_id}/approve")
async def approve_pricing_proposal(
    proposal_id: str,
    request: Request,
    current_user: Dict[str, Any] = Depends(require_admin),
):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    approver = str(current_user.get("username") or current_user.get("name") or "admin")
    async with pool.acquire() as conn:
        if not await _table_exists(conn, "pricing_change_proposals"):
            raise HTTPException(503, "Proposal table unavailable")
        row = await conn.fetchrow(
            """
            UPDATE pricing_change_proposals
            SET status = 'approved', approved_by = $2, approved_at = NOW()
            WHERE id::text = $1 AND status IN ('proposed', 'rejected')
            RETURNING id, status, title
            """,
            proposal_id,
            approver,
        )
        if not row:
            raise HTTPException(404, "Proposal not found or not approvable")

    return {
        "status": "ok",
        "proposal_id": str(row["id"]),
        "proposal_status": row["status"],
        "approved_by": approver,
        "approved_at": _utc_now_iso(),
    }


@router.post("/pricing/proposals/{proposal_id}/apply")
async def apply_pricing_proposal(
    proposal_id: str,
    request: Request,
    current_user: Dict[str, Any] = Depends(require_admin),
):
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(503, "Database unavailable")

    applier = str(current_user.get("username") or current_user.get("name") or "admin")
    async with pool.acquire() as conn:
        if not await _table_exists(conn, "pricing_change_proposals"):
            raise HTTPException(503, "Proposal table unavailable")
        if not await _table_exists(conn, "pricing_rule_versions"):
            raise HTTPException(503, "Pricing rule table unavailable")

        proposal = await conn.fetchrow(
            """
            SELECT id, title, payload_json, status
            FROM pricing_change_proposals
            WHERE id::text = $1
            """,
            proposal_id,
        )
        if not proposal:
            raise HTTPException(404, "Proposal not found")
        if proposal["status"] != "approved":
            raise HTTPException(400, "Proposal must be approved before apply")

        version = f"v_{proposal_id[:8]}_{int(datetime.now(timezone.utc).timestamp())}"

        # Deactivate all currently active pricing rules before inserting the new one.
        # Only one pricing rule version may be active at any time.
        await conn.execute(
            """
            UPDATE pricing_rule_versions
            SET status = 'superseded'
            WHERE status = 'active'
            """
        )

        await conn.execute(
            """
            INSERT INTO pricing_rule_versions
            (rule_version, status, rules_json, effective_at, created_by, approved_by, created_at, approved_at)
            VALUES ($1, 'active', $2::jsonb, NOW(), $3, $4, NOW(), NOW())
            """,
            version,
            proposal["payload_json"] or {},
            applier,
            applier,
        )
        await conn.execute(
            """
            UPDATE pricing_change_proposals
            SET status = 'applied', applied_by = $2, applied_at = NOW()
            WHERE id::text = $1
            """,
            proposal_id,
            applier,
        )

    return {
        "status": "ok",
        "proposal_id": proposal_id,
        "applied": True,
        "rule_version": version,
        "applied_by": applier,
        "applied_at": _utc_now_iso(),
    }

