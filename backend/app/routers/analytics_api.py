"""
LITTLE NATE — Analytics API
Campaign metrics, funnel data, timeseries, and activity feed.
"""

from fastapi import APIRouter, HTTPException, Request, Query
from typing import Optional
from datetime import datetime, timedelta

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


# =============================================================================
# OVERVIEW
# =============================================================================

@router.get("/overview")
async def get_overview(request: Request):
    """
    Aggregated overview metrics for the dashboard.
    Returns: active prospects, quizzes completed, tickets issued/redeemed,
    conversion rate, open rate, etc.
    """
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        # Prospect counts by status
        status_counts = await conn.fetch(
            """SELECT status, COUNT(*) as count
               FROM prospects
               GROUP BY status"""
        )
        status_map = {r["status"]: r["count"] for r in status_counts}

        # Total prospects
        total_prospects = sum(status_map.values())

        # Quiz completion stats
        total_quizzes = await conn.fetchval(
            "SELECT COUNT(*) FROM quiz_responses"
        )

        # Insight count
        total_insights = await conn.fetchval(
            "SELECT COUNT(*) FROM nate_insights"
        )

        # Golden ticket stats
        tickets_issued = status_map.get("golden_ticket_issued", 0) + status_map.get("redeemed", 0) + status_map.get("converted", 0)
        tickets_redeemed = status_map.get("redeemed", 0) + status_map.get("converted", 0)

        # Conversion rate
        conversion_rate = (
            status_map.get("converted", 0) / total_prospects * 100
            if total_prospects > 0 else 0
        )

        # Email delivery stats (last 30 days)
        email_stats = await conn.fetchrow(
            """SELECT
                COUNT(*) as total_sent,
                COUNT(*) FILTER (WHERE status = 'delivered') as delivered,
                COUNT(*) FILTER (WHERE status IN ('opened', 'clicked')) as opened,
                COUNT(*) FILTER (WHERE status = 'clicked') as clicked,
                COUNT(*) FILTER (WHERE status = 'bounced') as bounced
               FROM delivery_log
               WHERE channel = 'email' AND sent_at >= NOW() - INTERVAL '30 days'"""
        )

        open_rate = (
            email_stats["opened"] / email_stats["total_sent"] * 100
            if email_stats["total_sent"] > 0 else 0
        )

        # Active campaigns
        active_campaigns = await conn.fetchval(
            "SELECT COUNT(*) FROM campaigns WHERE status = 'active'"
        )

        return {
            "total_prospects": total_prospects,
            "active_prospects": status_map.get("active_journey", 0),
            "quiz_complete": status_map.get("quiz_complete", 0),
            "total_quizzes_completed": total_quizzes,
            "total_insights": total_insights,
            "tickets_issued": tickets_issued,
            "tickets_redeemed": tickets_redeemed,
            "tickets_pending": status_map.get("golden_ticket_issued", 0),
            "converted": status_map.get("converted", 0),
            "lapsed": status_map.get("lapsed", 0),
            "conversion_rate": round(conversion_rate, 1),
            "open_rate": round(open_rate, 1),
            "emails_sent_30d": email_stats["total_sent"],
            "emails_delivered_30d": email_stats["delivered"],
            "active_campaigns": active_campaigns,
            "prospect_status_breakdown": status_map
        }


# =============================================================================
# FUNNEL
# =============================================================================

@router.get("/funnel/{campaign_id}")
async def get_funnel(request: Request, campaign_id: str):
    """Stage-by-stage funnel data for a campaign."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        # Verify campaign
        campaign = await conn.fetchrow(
            "SELECT * FROM campaigns WHERE id = $1", campaign_id
        )
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")

        # Get funnel counts
        funnel = await conn.fetch(
            """SELECT
                p.status,
                COUNT(*) as count
               FROM prospects p
               WHERE p.current_campaign_id = $1
               GROUP BY p.status
               ORDER BY
                CASE p.status
                    WHEN 'subscribed' THEN 1
                    WHEN 'active_journey' THEN 2
                    WHEN 'quiz_complete' THEN 3
                    WHEN 'golden_ticket_issued' THEN 4
                    WHEN 'redeemed' THEN 5
                    WHEN 'converted' THEN 6
                    WHEN 'lapsed' THEN 7
                    WHEN 'unsubscribed' THEN 8
                END""",
            campaign_id
        )

        # Get step-level progress
        step_progress = await conn.fetch(
            """SELECT
                current_step,
                COUNT(*) as count
               FROM prospects
               WHERE current_campaign_id = $1
               GROUP BY current_step
               ORDER BY current_step""",
            campaign_id
        )

        # Quiz completion per quiz
        quiz_completions = await conn.fetch(
            """SELECT
                q.quiz_order, q.title,
                COUNT(qr.id) as completions
               FROM quizzes q
               LEFT JOIN quiz_responses qr ON qr.quiz_id = q.id
                   AND qr.campaign_id = $1
               GROUP BY q.id, q.quiz_order, q.title
               ORDER BY q.quiz_order""",
            campaign_id
        )

        return {
            "campaign": dict(campaign),
            "funnel_stages": [dict(f) for f in funnel],
            "step_progress": [dict(s) for s in step_progress],
            "quiz_completions": [dict(q) for q in quiz_completions]
        }


# =============================================================================
# TIMESERIES
# =============================================================================

@router.get("/timeseries/{campaign_id}")
async def get_timeseries(
    request: Request,
    campaign_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    days: int = 30
):
    """Daily metrics timeseries for charts."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        if from_date and to_date:
            rows = await conn.fetch(
                """SELECT * FROM campaign_analytics
                   WHERE campaign_id = $1 AND date BETWEEN $2 AND $3
                   ORDER BY date""",
                campaign_id, from_date, to_date
            )
        else:
            rows = await conn.fetch(
                """SELECT * FROM campaign_analytics
                   WHERE campaign_id = $1 AND date >= CURRENT_DATE - $2::INTEGER
                   ORDER BY date""",
                campaign_id, days
            )

        return [dict(r) for r in rows]


# =============================================================================
# ACTIVITY FEED
# =============================================================================

@router.get("/activity")
async def get_activity_feed(request: Request, limit: int = Query(10, ge=1, le=50)):
    """Recent activity feed for the admin dashboard."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        # Combine recent events from multiple tables
        activities = []

        # Recent quiz completions
        quiz_events = await conn.fetch(
            """SELECT 'quiz_completed' as event_type,
                      p.first_name || ' ' || COALESCE(p.last_name, '') as actor,
                      p.email as actor_email,
                      q.title as detail,
                      qr.completed_at as event_time
               FROM quiz_responses qr
               JOIN prospects p ON p.id = qr.prospect_id
               JOIN quizzes q ON q.id = qr.quiz_id
               ORDER BY qr.completed_at DESC
               LIMIT $1""",
            limit
        )
        activities.extend([dict(r) for r in quiz_events])

        # Recent ticket events
        ticket_events = await conn.fetch(
            """SELECT
                CASE
                    WHEN golden_ticket_redeemed_at IS NOT NULL THEN 'ticket_redeemed'
                    ELSE 'ticket_issued'
                END as event_type,
                first_name || ' ' || COALESCE(last_name, '') as actor,
                email as actor_email,
                status as detail,
                COALESCE(golden_ticket_redeemed_at, golden_ticket_issued_at) as event_time
               FROM prospects
               WHERE golden_ticket_token IS NOT NULL
               ORDER BY COALESCE(golden_ticket_redeemed_at, golden_ticket_issued_at) DESC
               LIMIT $1""",
            limit
        )
        activities.extend([dict(r) for r in ticket_events])

        # Recent subscriptions
        sub_events = await conn.fetch(
            """SELECT 'new_prospect' as event_type,
                      first_name || ' ' || COALESCE(last_name, '') as actor,
                      email as actor_email,
                      source as detail,
                      created_at as event_time
               FROM prospects
               ORDER BY created_at DESC
               LIMIT $1""",
            limit
        )
        activities.extend([dict(r) for r in sub_events])

        # Sort all by time descending, take top N
        activities.sort(key=lambda x: x.get("event_time") or datetime.min, reverse=True)
        return activities[:limit]


# =============================================================================
# INTEGRATIONS STATUS
# =============================================================================

@router.get("/integrations/sendgrid/stats")
async def sendgrid_stats(request: Request, days: int = 30):
    """SendGrid delivery stats for the integrations panel."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        stats = await conn.fetchrow(
            """SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'delivered') as delivered,
                COUNT(*) FILTER (WHERE status IN ('opened', 'clicked')) as opened,
                COUNT(*) FILTER (WHERE status = 'clicked') as clicked,
                COUNT(*) FILTER (WHERE status = 'bounced') as bounced,
                COUNT(*) FILTER (WHERE status = 'failed') as failed
               FROM delivery_log
               WHERE channel = 'email'
                 AND sent_at >= NOW() - ($1::INTEGER || ' days')::INTERVAL""",
            days
        )
        return dict(stats) if stats else {}


@router.get("/integrations/twilio/stats")
async def twilio_stats(request: Request, days: int = 30):
    """Twilio SMS delivery stats for the integrations panel."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        stats = await conn.fetchrow(
            """SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'delivered') as delivered,
                COUNT(*) FILTER (WHERE status = 'failed') as failed
               FROM delivery_log
               WHERE channel = 'sms'
                 AND sent_at >= NOW() - ($1::INTEGER || ' days')::INTERVAL""",
            days
        )
        return dict(stats) if stats else {}
