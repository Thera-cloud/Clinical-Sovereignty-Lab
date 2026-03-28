"""
CLI Analytics API — Turn-level cost analytics and session history for the Command Terminal.

Phase 5: Provides per-session token usage breakdown, cost estimates (Grok rates),
turn distribution, and tool call distribution.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from typing import Optional
import logging

from app.services.api_server import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/cli",
    tags=["CLI Analytics"],
)

GROK_INPUT_RATE = 0.20 / 1_000_000   # $0.20 per million input tokens
GROK_OUTPUT_RATE = 0.50 / 1_000_000  # $0.50 per million output tokens
CHARS_PER_TOKEN = 4


def _require_admin(user: dict = Depends(get_current_user)):
    if user.get("role") != "ADMIN":
        raise HTTPException(403, "Admin access required")
    return user


@router.get("/analytics")
async def cli_analytics(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    mode: Optional[str] = Query(None),
    user: dict = Depends(_require_admin),
):
    """Full CLI analytics dashboard data: sessions, cost, tool breakdown."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        return {"status": "ok", "data": _empty_analytics()}

    try:
        async with pool.acquire() as conn:
            mode_filter = ""
            params = [days]
            if mode:
                mode_filter = "AND mode = $2"
                params.append(mode)

            sessions = await conn.fetch(f"""
                SELECT plan_id, mode, cli_type, status, title,
                       created_by, created_at, resolved_at,
                       total_turns, total_tool_calls,
                       COALESCE(input_chars, 0) AS input_chars,
                       COALESCE(output_chars, 0) AS output_chars,
                       COALESCE(est_input_tokens, 0) AS est_input_tokens,
                       COALESCE(est_output_tokens, 0) AS est_output_tokens,
                       COALESCE(est_cost_usd, 0) AS est_cost_usd,
                       EXTRACT(EPOCH FROM (COALESCE(resolved_at, NOW()) - created_at)) AS duration_secs
                FROM cli_plans
                WHERE created_at >= NOW() - $1 * INTERVAL '1 day'
                {mode_filter}
                ORDER BY created_at DESC
                LIMIT 200
            """, *params)

            tool_dist = await conn.fetch(f"""
                SELECT tool_name, COUNT(*) AS call_count,
                       AVG(duration_ms)::int AS avg_ms,
                       SUM(duration_ms) AS total_ms
                FROM cli_tool_calls
                WHERE created_at >= NOW() - $1 * INTERVAL '1 day'
                GROUP BY tool_name
                ORDER BY call_count DESC
            """, days)

            mode_dist = await conn.fetch(f"""
                SELECT mode, COUNT(*) AS session_count,
                       SUM(total_turns) AS total_turns,
                       SUM(total_tool_calls) AS total_tools
                FROM cli_plans
                WHERE created_at >= NOW() - $1 * INTERVAL '1 day'
                GROUP BY mode
                ORDER BY session_count DESC
            """, days)

            cost_by_day = await conn.fetch("""
                SELECT DATE(created_at) AS day,
                       COUNT(DISTINCT plan_id) AS sessions,
                       SUM(total_turns) AS turns,
                       SUM(total_tool_calls) AS tool_calls
                FROM cli_plans
                WHERE created_at >= NOW() - $1 * INTERVAL '1 day'
                GROUP BY DATE(created_at)
                ORDER BY day DESC
            """, days)

            data_access_count = await conn.fetchval("""
                SELECT COUNT(*) FROM cli_data_access_log
                WHERE created_at >= NOW() - $1 * INTERVAL '1 day'
            """, days)

        session_list = []
        total_turns = 0
        total_tool_calls = 0
        for s in sessions:
            total_turns += s.get("total_turns") or 0
            total_tool_calls += s.get("total_tool_calls") or 0
            session_list.append({
                "plan_id": s["plan_id"],
                "mode": s.get("mode"),
                "cli_type": s.get("cli_type"),
                "status": s.get("status"),
                "title": (s.get("title") or "")[:100],
                "created_by": s.get("created_by"),
                "created_at": s["created_at"].isoformat() if s.get("created_at") else None,
                "resolved_at": s["resolved_at"].isoformat() if s.get("resolved_at") else None,
                "total_turns": s.get("total_turns", 0),
                "total_tool_calls": s.get("total_tool_calls", 0),
                "duration_secs": round(float(s.get("duration_secs") or 0), 1),
                "input_chars": int(s.get("input_chars") or 0),
                "output_chars": int(s.get("output_chars") or 0),
                "est_input_tokens": int(s.get("est_input_tokens") or 0),
                "est_output_tokens": int(s.get("est_output_tokens") or 0),
                "est_cost_usd": round(float(s.get("est_cost_usd") or 0), 6),
            })

        tool_breakdown = [
            {
                "tool": r["tool_name"],
                "count": r["call_count"],
                "avg_ms": r.get("avg_ms", 0),
                "total_ms": r.get("total_ms", 0),
            }
            for r in tool_dist
        ]

        mode_breakdown = [
            {
                "mode": r["mode"],
                "sessions": r["session_count"],
                "total_turns": r.get("total_turns", 0),
                "total_tools": r.get("total_tools", 0),
            }
            for r in mode_dist
        ]

        daily = [
            {
                "day": str(r["day"]),
                "sessions": r["sessions"],
                "turns": r.get("turns", 0),
                "tool_calls": r.get("tool_calls", 0),
            }
            for r in cost_by_day
        ]

        return {
            "status": "ok",
            "data": {
                "period_days": days,
                "total_sessions": len(session_list),
                "total_turns": total_turns,
                "total_tool_calls": total_tool_calls,
                "data_access_queries": data_access_count or 0,
                "mode_breakdown": mode_breakdown,
                "tool_breakdown": tool_breakdown,
                "daily_activity": daily,
                "sessions": session_list[:50],
            },
        }
    except Exception as e:
        logger.warning("CLI analytics query failed: %s", e)
        return {"status": "ok", "data": _empty_analytics()}


@router.get("/sessions")
async def cli_sessions(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    user: dict = Depends(_require_admin),
):
    """List recent CLI sessions with details."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        return {"status": "ok", "sessions": []}

    try:
        conditions = ["1=1"]
        params = []
        idx = 1
        if status:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        params.append(limit)

        async with pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT plan_id, mode, cli_type, status, title,
                       created_by, created_at, resolved_at,
                       total_turns, total_tool_calls, files
                FROM cli_plans
                WHERE {' AND '.join(conditions)}
                ORDER BY created_at DESC
                LIMIT ${idx}
            """, *params)

        return {
            "status": "ok",
            "sessions": [
                {
                    "plan_id": r["plan_id"],
                    "mode": r.get("mode"),
                    "cli_type": r.get("cli_type"),
                    "status": r.get("status"),
                    "title": (r.get("title") or "")[:200],
                    "created_by": r.get("created_by"),
                    "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                    "resolved_at": r["resolved_at"].isoformat() if r.get("resolved_at") else None,
                    "total_turns": r.get("total_turns", 0),
                    "total_tool_calls": r.get("total_tool_calls", 0),
                    "files": r.get("files"),
                }
                for r in rows
            ],
        }
    except Exception as e:
        logger.warning("CLI sessions query failed: %s", e)
        return {"status": "ok", "sessions": []}


@router.get("/cost-summary")
async def cli_cost_summary(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    user: dict = Depends(_require_admin),
):
    """Cost estimate breakdown by mode and provider."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        return {"status": "ok", "cost": _empty_cost()}

    try:
        async with pool.acquire() as conn:
            tool_data = await conn.fetch("""
                SELECT tc.cli_type,
                       cp.mode,
                       COUNT(*) AS tool_calls,
                       SUM(tc.duration_ms) AS total_duration_ms,
                       SUM(LENGTH(tc.tool_input::text)) AS input_chars,
                       SUM(LENGTH(tc.tool_output::text)) AS output_chars
                FROM cli_tool_calls tc
                LEFT JOIN cli_plans cp ON tc.plan_id = cp.plan_id
                WHERE tc.created_at >= NOW() - $1 * INTERVAL '1 day'
                GROUP BY tc.cli_type, cp.mode
            """, days)

            session_summary = await conn.fetchrow("""
                        SELECT COUNT(*) AS total_sessions,
                               SUM(total_turns) AS total_turns,
                               SUM(total_tool_calls) AS total_tool_calls,
                               SUM(COALESCE(input_chars, 0)) AS total_input_chars,
                               SUM(COALESCE(output_chars, 0)) AS total_output_chars,
                               SUM(COALESCE(est_cost_usd, 0)) AS total_est_cost
                        FROM cli_plans
                        WHERE created_at >= NOW() - $1 * INTERVAL '1 day'
                    """, days)

        cloud_input_chars = 0
        cloud_output_chars = 0
        local_sessions = 0
        breakdown = []

        for r in tool_data:
            ic = r.get("input_chars") or 0
            oc = r.get("output_chars") or 0
            cli_type = r.get("cli_type") or "cloud"
            mode_name = r.get("mode") or "unknown"

            if cli_type == "cloud":
                cloud_input_chars += ic
                cloud_output_chars += oc
            else:
                local_sessions += r.get("tool_calls", 0)

            est_in_tokens = ic // CHARS_PER_TOKEN
            est_out_tokens = oc // CHARS_PER_TOKEN
            est_cost = (est_in_tokens * GROK_INPUT_RATE) + (est_out_tokens * GROK_OUTPUT_RATE)

            breakdown.append({
                "cli_type": cli_type,
                "mode": mode_name,
                "tool_calls": r.get("tool_calls", 0),
                "est_input_tokens": est_in_tokens,
                "est_output_tokens": est_out_tokens,
                "est_cost_usd": round(est_cost, 6),
            })

        ss_input = int(session_summary.get("total_input_chars") or 0) if session_summary else 0
        ss_output = int(session_summary.get("total_output_chars") or 0) if session_summary else 0
        ss_cost = float(session_summary.get("total_est_cost") or 0) if session_summary else 0.0

        if ss_input > 0 or ss_output > 0:
            total_in_tokens = ss_input // CHARS_PER_TOKEN
            total_out_tokens = ss_output // CHARS_PER_TOKEN
            total_cost = ss_cost
        else:
            total_in_tokens = cloud_input_chars // CHARS_PER_TOKEN
            total_out_tokens = cloud_output_chars // CHARS_PER_TOKEN
            total_cost = (total_in_tokens * GROK_INPUT_RATE) + (total_out_tokens * GROK_OUTPUT_RATE)

        return {
            "status": "ok",
            "cost": {
                "period_days": days,
                "total_sessions": (session_summary.get("total_sessions") or 0) if session_summary else 0,
                "total_turns": (session_summary.get("total_turns") or 0) if session_summary else 0,
                "cloud_est_input_tokens": total_in_tokens,
                "cloud_est_output_tokens": total_out_tokens,
                "cloud_est_cost_usd": round(total_cost, 6),
                "local_tool_calls": local_sessions,
                "local_cost_usd": 0.0,
                "breakdown": breakdown,
            },
        }
    except Exception as e:
        logger.warning("CLI cost summary failed: %s", e)
        return {"status": "ok", "cost": _empty_cost()}


@router.get("/data-access-log")
async def cli_data_access_log(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(_require_admin),
):
    """HIPAA audit trail: all data-touching CLI tool calls."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        return {"status": "ok", "entries": []}

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, plan_id, username, tool_name, data_scope,
                       result_row_count, role_tier, data_classification,
                       redacted_args, created_at
                FROM cli_data_access_log
                WHERE created_at >= NOW() - $1 * INTERVAL '1 day'
                ORDER BY created_at DESC
                LIMIT $2
            """, days, limit)

        return {
            "status": "ok",
            "entries": [
                {
                    "id": str(r["id"]),
                    "plan_id": r.get("plan_id"),
                    "username": r.get("username"),
                    "tool_name": r.get("tool_name"),
                    "data_scope": r.get("data_scope"),
                    "result_row_count": r.get("result_row_count"),
                    "role_tier": r.get("role_tier"),
                    "data_classification": r.get("data_classification"),
                    "redacted_args": r.get("redacted_args"),
                    "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                }
                for r in rows
            ],
        }
    except Exception as e:
        logger.warning("CLI data access log query failed: %s", e)
        return {"status": "ok", "entries": []}


@router.get("/health")
async def cli_analytics_health():
    """Health check for CLI Analytics API."""
    return {"status": "ok", "service": "cli_analytics"}


def _empty_analytics():
    return {
        "period_days": 0,
        "total_sessions": 0,
        "total_turns": 0,
        "total_tool_calls": 0,
        "data_access_queries": 0,
        "mode_breakdown": [],
        "tool_breakdown": [],
        "daily_activity": [],
        "sessions": [],
    }


def _empty_cost():
    return {
        "period_days": 0,
        "total_sessions": 0,
        "total_turns": 0,
        "cloud_est_input_tokens": 0,
        "cloud_est_output_tokens": 0,
        "cloud_est_cost_usd": 0.0,
        "local_tool_calls": 0,
        "local_cost_usd": 0.0,
        "breakdown": [],
    }
