"""
Analytics API Router — R2 SQL / Iceberg Data Lake

Routes heavy analytical queries to R2 SQL (Cloudflare Iceberg), keeping
PostgreSQL lean for transactional workloads. Falls back to PostgreSQL
if R2 SQL is unavailable.

All endpoints are admin-only.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

try:
    from app.services.api_server import require_admin
except ImportError:
    from backend.app.services.api_server import require_admin

router = APIRouter(
    prefix="/api/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_admin)],
)


def _get_analytics(request: Request):
    svc = getattr(request.app.state, "r2_analytics", None)
    if not svc:
        raise HTTPException(503, "Analytics service not initialized")
    return svc


def _get_cdc(request: Request):
    agent = getattr(request.app.state, "iceberg_cdc_agent", None)
    if not agent:
        raise HTTPException(503, "CDC agent not initialized")
    return agent


# -------------------------------------------------------------------
# Health & Status
# -------------------------------------------------------------------

@router.get("/health")
async def analytics_health(request: Request):
    analytics = getattr(request.app.state, "r2_analytics", None)
    cdc = getattr(request.app.state, "iceberg_cdc_agent", None)
    return {
        "status": "ok",
        "analytics": analytics.get_status() if analytics else {"enabled": False},
        "cdc": cdc.get_status() if cdc else {"running": False},
    }


@router.get("/cdc/status")
async def cdc_status(request: Request):
    cdc = _get_cdc(request)
    return cdc.get_status()


@router.post("/cdc/backfill")
async def cdc_backfill(
    request: Request,
    table: Optional[str] = Query(None, description="Specific table to backfill (or all)"),
    since: Optional[str] = Query(None, description="ISO timestamp to backfill from"),
):
    cdc = _get_cdc(request)
    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, "Invalid 'since' timestamp")

    result = await cdc.backfill(table_name=table, since=since_dt)
    return {"status": "backfill_complete", **result}


# -------------------------------------------------------------------
# Conversation Analytics
# -------------------------------------------------------------------

@router.get("/conversations/volume")
async def conversation_volume(request: Request, days: int = Query(30, ge=1, le=365)):
    svc = _get_analytics(request)
    return await svc.conversation_volume(days)


@router.get("/conversations/by-user")
async def conversation_by_user(request: Request, days: int = Query(30, ge=1, le=365), limit: int = Query(50, ge=1, le=500)):
    svc = _get_analytics(request)
    return await svc.conversation_volume_by_user(days, limit)


# -------------------------------------------------------------------
# Token Analytics
# -------------------------------------------------------------------

@router.get("/tokens/trends")
async def token_trends(request: Request, days: int = Query(30, ge=1, le=365)):
    svc = _get_analytics(request)
    return await svc.token_usage_trends(days)


@router.get("/tokens/by-user")
async def token_by_user(request: Request, days: int = Query(30, ge=1, le=365), limit: int = Query(50, ge=1, le=500)):
    svc = _get_analytics(request)
    return await svc.token_usage_by_user(days, limit)


# -------------------------------------------------------------------
# Nevedal Coherence Analytics
# -------------------------------------------------------------------

@router.get("/coherence/trends")
async def coherence_trends(request: Request, days: int = Query(30, ge=1, le=365)):
    svc = _get_analytics(request)
    return await svc.coherence_trends(days)


@router.get("/coherence/user/{user_id}")
async def coherence_user(request: Request, user_id: str, days: int = Query(90, ge=1, le=365)):
    svc = _get_analytics(request)
    return await svc.coherence_by_user(user_id, days)


# -------------------------------------------------------------------
# Wisdom & Me2Me Analytics
# -------------------------------------------------------------------

@router.get("/wisdom/insights")
async def wisdom_insights(request: Request, days: int = Query(30, ge=1, le=365)):
    svc = _get_analytics(request)
    return await svc.wisdom_insights(days)


@router.get("/me2me/activity")
async def me2me_activity(request: Request, days: int = Query(30, ge=1, le=365)):
    svc = _get_analytics(request)
    return await svc.me2me_activity(days)


# -------------------------------------------------------------------
# Social / SkyEye Analytics
# -------------------------------------------------------------------

@router.get("/social/engagement")
async def social_engagement(request: Request, days: int = Query(30, ge=1, le=365)):
    svc = _get_analytics(request)
    return await svc.social_engagement_trends(days)


@router.get("/social/notifications")
async def notification_breakdown(request: Request, days: int = Query(30, ge=1, le=365)):
    svc = _get_analytics(request)
    return await svc.notification_breakdown(days)


@router.get("/social/heatmap")
async def activity_heatmap(request: Request, days: int = Query(7, ge=1, le=30)):
    svc = _get_analytics(request)
    return await svc.platform_activity_heatmap(days)


# -------------------------------------------------------------------
# Coaching Session Analytics
# -------------------------------------------------------------------

@router.get("/coaching/stats")
async def coaching_stats(request: Request, days: int = Query(90, ge=1, le=365)):
    svc = _get_analytics(request)
    return await svc.coaching_session_stats(days)


@router.get("/coaching/by-coach")
async def coaching_by_coach(request: Request, days: int = Query(90, ge=1, le=365)):
    svc = _get_analytics(request)
    return await svc.coaching_by_coach(days)


@router.get("/skyeye/sessions")
async def skyeye_sessions(request: Request, days: int = Query(30, ge=1, le=365)):
    svc = _get_analytics(request)
    return await svc.skyeye_session_summary(days)


# -------------------------------------------------------------------
# Cross-Table User Profile
# -------------------------------------------------------------------

@router.get("/user/{user_id}/engagement")
async def user_engagement(request: Request, user_id: str):
    svc = _get_analytics(request)
    return await svc.cross_table_user_engagement(user_id)


# -------------------------------------------------------------------
# Raw SQL (admin power query)
# -------------------------------------------------------------------

@router.post("/query")
async def raw_query(request: Request):
    body = await request.json()
    sql = body.get("sql", "").strip()
    if not sql:
        raise HTTPException(422, "SQL query required")

    write_keywords = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE")
    if any(sql.upper().startswith(kw) for kw in write_keywords):
        raise HTTPException(400, "Write operations not allowed on analytics lake")

    svc = _get_analytics(request)
    return await svc.query(sql)
