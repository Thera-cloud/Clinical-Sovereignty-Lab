"""
Nevedal Research Reports API
Generates 5 report types for the Nevedal Research Laboratory (SC_07).
Includes client-facing weekly coherence brief.
"""

import json
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request, HTTPException
from uuid import UUID
from typing import List, Optional

from app.services.api_server import require_admin
from app.auth import get_current_user_id
from app.config import settings

logger = logging.getLogger("nevedal.reports")

router = APIRouter(
    prefix="/api/research/nevedal/reports",
    tags=["nevedal_reports"],
)


@router.post("/generate", dependencies=[Depends(require_admin)])
async def generate_report(request: Request):
    """
    Generate a Nevedal research report.

    Body:
        report_type: individual_coherence | dyad_comparison | family_dynamics
                     | longitudinal_trends | coach_efficacy
        subject_ids: list of UUID strings (user/coach IDs)
        date_range_days: int (default 84 = 12 weeks)
        family_id: optional UUID (for family_dynamics)
    """
    body = await request.json()
    report_type = body.get("report_type")
    subject_ids_raw = body.get("subject_ids", [])
    date_range_days = body.get("date_range_days", 84)
    family_id = body.get("family_id")

    if not report_type:
        raise HTTPException(400, "report_type is required")
    if not subject_ids_raw and report_type != "family_dynamics":
        raise HTTPException(400, "subject_ids is required")

    subject_ids = [UUID(sid) if isinstance(sid, str) else sid for sid in subject_ids_raw]

    from app.services.nevedal_report_generator import NevedalReportGenerator

    db = request.app.state.db_pool
    gen = NevedalReportGenerator(db)

    kwargs = {}
    if family_id:
        kwargs["family_id"] = UUID(family_id) if isinstance(family_id, str) else family_id

    report = await gen.generate(
        report_type=report_type,
        subject_ids=subject_ids,
        date_range_days=date_range_days,
        **kwargs,
    )

    return report


@router.get("/types", dependencies=[Depends(get_current_user_id)])
async def list_report_types():
    """List available report types (accessible to any authenticated user)."""
    return {
        "report_types": [
            {
                "id": "individual_coherence",
                "name": "Individual Coherence Report",
                "description": "Single user C_emo trends, CEE events, biometric summary",
                "required_ids": ["user_id"],
            },
            {
                "id": "dyad_comparison",
                "name": "Dyad Comparison Report",
                "description": "Coach-client synchrony, correlation, shared CEE moments",
                "required_ids": ["subject_a_id", "subject_b_id"],
            },
            {
                "id": "family_dynamics",
                "name": "Family Dynamics Report",
                "description": "Multi-member coherence matrix, family wellness index",
                "required_ids": ["family_id"],
            },
            {
                "id": "longitudinal_trends",
                "name": "Longitudinal Trends (12-week)",
                "description": "C_emo trend with statistical analysis over 12+ weeks",
                "required_ids": ["user_id"],
            },
            {
                "id": "coach_efficacy",
                "name": "Coach Efficacy Analysis",
                "description": "Coach effectiveness across all assigned clients",
                "required_ids": ["coach_id"],
            },
        ]
    }


@router.get("/brief")
async def weekly_coherence_brief(
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    """
    Generate a warm, 200-word weekly coherence brief for a client.
    Pulls last 7 days of mood history and C_emo trends, then uses
    Azure OpenAI to produce a soft summary with one actionable weekly goal.
    """
    db = request.app.state.db_pool

    try:
        async with db.acquire() as conn:
            metrics = await conn.fetch("""
                SELECT c_emo, p_ent, t_tunnel, gamma_env,
                       cee_window, recorded_at
                FROM nevedal_metrics
                WHERE user_id = $1
                  AND recorded_at >= NOW() - INTERVAL '7 days'
                ORDER BY recorded_at ASC
            """, user_id)

            sessions = await conn.fetch("""
                SELECT id, started_at, ended_at
                FROM sessions
                WHERE user_id = $1
                  AND started_at >= NOW() - INTERVAL '7 days'
                ORDER BY started_at ASC
            """, user_id)
    except Exception as e:
        logger.warning(f"Brief data fetch error: {e}")
        metrics = []
        sessions = []

    if not metrics:
        return {
            "brief": "You haven't had enough sessions this week for me to create a full brief yet. "
                     "That's okay — even a single conversation gives me data to work with. "
                     "Come talk to me when you're ready, and I'll have something meaningful to share.",
            "mood_summary": {"sessions": len(sessions), "data_points": 0},
            "goal": "Start a conversation with Little Nate this week to begin tracking your emotional patterns.",
        }

    c_emo_values = [float(m["c_emo"]) for m in metrics if m["c_emo"] is not None]
    avg_cemo = sum(c_emo_values) / len(c_emo_values) if c_emo_values else 0
    cee_count = sum(1 for m in metrics if m["cee_window"])
    trend = "stable"
    if len(c_emo_values) >= 3:
        first_half = sum(c_emo_values[:len(c_emo_values)//2]) / max(len(c_emo_values)//2, 1)
        second_half = sum(c_emo_values[len(c_emo_values)//2:]) / max(len(c_emo_values) - len(c_emo_values)//2, 1)
        if second_half > first_half + 0.05:
            trend = "improving"
        elif second_half < first_half - 0.05:
            trend = "dipping"

    mood_summary = {
        "sessions": len(sessions),
        "data_points": len(metrics),
        "avg_c_emo": round(avg_cemo, 3),
        "cee_windows": cee_count,
        "trend": trend,
    }

    prompt = f"""You are Little Nate, a warm AI therapy companion. Write a brief weekly
check-in for your client. Be gentle, personal, and encouraging. Do NOT use clinical
jargon. Keep it under 200 words.

Data from the past 7 days:
- Sessions: {len(sessions)}
- Emotional coherence (C_emo) average: {avg_cemo:.3f} (scale 0-1, higher = more coherent)
- Trend: {trend}
- CEE Windows (moments of deep connection): {cee_count}
- Data points: {len(metrics)}

Structure:
1. A warm greeting acknowledging their week
2. What you noticed about their emotional patterns (2-3 sentences)
3. One specific, actionable goal for the coming week

Tone: Like a trusted friend who happens to understand emotions deeply.
End with the weekly goal clearly stated."""

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            headers = {
                "Content-Type": "application/json",
                "api-key": settings.AZURE_API_KEY,
            }
            payload = {
                "messages": [
                    {"role": "system", "content": "You are Little Nate, a warm AI therapy companion."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 350,
                "temperature": 0.7,
            }
            url = f"{settings.AZURE_ENDPOINT}/openai/deployments/{settings.AZURE_DEPLOYMENT}/chat/completions?api-version=2024-10-21"
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    brief_text = data["choices"][0]["message"]["content"].strip()
                else:
                    brief_text = _generate_fallback_brief(mood_summary)
    except Exception as e:
        logger.warning(f"Azure OpenAI brief generation failed: {e}")
        brief_text = _generate_fallback_brief(mood_summary)

    goal_line = ""
    for line in brief_text.split("\n"):
        lower = line.lower().strip()
        if "goal" in lower or "this week" in lower or "try to" in lower:
            goal_line = line.strip().lstrip("- •*").strip()
            break
    if not goal_line:
        goal_line = "Take 5 minutes each day to check in with how you're feeling — no judgment, just notice."

    return {
        "brief": brief_text,
        "mood_summary": mood_summary,
        "goal": goal_line,
    }


def _generate_fallback_brief(mood_summary: dict) -> str:
    """Fallback brief when AI generation is unavailable."""
    trend = mood_summary.get("trend", "stable")
    avg = mood_summary.get("avg_c_emo", 0)
    sessions = mood_summary.get("sessions", 0)
    cee = mood_summary.get("cee_windows", 0)

    trend_msg = {
        "improving": "Your emotional coherence has been trending upward, which is genuinely encouraging.",
        "dipping": "Your coherence dipped a bit this week, and that's okay — growth isn't always linear.",
        "stable": "Your emotional patterns have been steady this week, showing real consistency.",
    }.get(trend, "I've been watching your patterns this week.")

    return (
        f"Hey — wanted to check in with you about your week. "
        f"You showed up for {sessions} session{'s' if sessions != 1 else ''}, "
        f"and that matters more than any number I could give you.\n\n"
        f"{trend_msg} "
        f"{'You had ' + str(cee) + ' moment' + ('s' if cee != 1 else '') + ' of deep emotional connection, which is beautiful.' if cee else ''}\n\n"
        f"**Goal for this week**: Take 5 minutes each day to notice one emotion without trying to change it. "
        f"Just sit with it. That simple practice builds the coherence we're tracking together."
    )
