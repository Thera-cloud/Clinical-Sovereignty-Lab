"""
Nevedal Research Reports API
Generates 5 report types for the Nevedal Research Laboratory (SC_07).
Includes client-facing weekly coherence brief.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import APIRouter, Depends, Request, HTTPException
from uuid import UUID
from typing import List, Optional

from app.services.api_server import require_admin, require_coach
from app.auth import get_current_user_id
from app.config import settings
from app.services.nate_ai_config import NATE_CHAT_URL, NATE_CHAT_KEY, nate_chat_headers, nate_chat_payload

logger = logging.getLogger("nevedal.reports")

_DATA_ROOT = Path(os.environ.get("DATA_DIR", "/app/data"))
_VAULT_ROOT = _DATA_ROOT / "Vaults"
_COACH_NOTES_FILE = _DATA_ROOT / "coach_session_notes.json"

router = APIRouter(
    prefix="/api/research/nevedal/reports",
    tags=["nevedal_reports"],
)

_REPORT_TIERS = {"TOP_TIER", "SOVEREIGN_CIRCLE", "STANDARD", "INNER_CHAMBER", "TRIAL"}


async def _check_report_tier(
    request: Request,
    user_id: str = Depends(get_current_user_id),
) -> str:
    """Verify user has at least TRIAL tier for reports (all tiers get some reports)."""
    pool = getattr(request.app.state, "db_pool", None)
    if pool:
        try:
            row = await pool.fetchrow(
                "SELECT tier, profile_data->>'subscription_plan' AS plan "
                "FROM users WHERE hardware_id = $1 AND deleted_at IS NULL LIMIT 1",
                user_id,
            )
            if row:
                tier = (row["tier"] or row["plan"] or "TRIAL").upper()
                if tier in ("COACH_ONLY",):
                    raise HTTPException(
                        403,
                        "Nevedal reports are not available on Coach Only plan.",
                    )
                return user_id
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("_check_report_tier: %s", e)
    return user_id


@router.post("/generate", dependencies=[Depends(require_coach)])
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
    try:
        body = await request.json()
    except Exception as e:
        logger.error("Report generate: failed to parse JSON body: %s", e)
        raise HTTPException(400, f"Invalid JSON body: {e}")

    logger.info("Report generate: body=%s", json.dumps(body) if isinstance(body, dict) else str(body)[:200])
    report_type = body.get("report_type") if isinstance(body, dict) else None
    subject_ids_raw = (body.get("subject_ids") or body.get("user_ids", [])) if isinstance(body, dict) else []
    date_range_days = body.get("date_range_days", 84) if isinstance(body, dict) else 84
    family_id = body.get("family_id") if isinstance(body, dict) else None

    if not report_type:
        logger.error("Report generate: report_type missing from body keys: %s", list(body.keys()) if isinstance(body, dict) else type(body))
        raise HTTPException(400, "report_type is required")
    if not subject_ids_raw and report_type != "family_dynamics":
        raise HTTPException(400, "subject_ids is required")

    db = request.app.state.db_pool
    subject_ids = []
    for sid in subject_ids_raw:
        s = str(sid).strip() if sid is not None else ""
        if not s:
            continue
        try:
            subject_ids.append(UUID(s) if s else sid)
        except ValueError:
            async with db.acquire() as conn:
                resolved = await conn.fetchval(
                    """SELECT id FROM users
                       WHERE hardware_id = $1 OR LOWER(username) = LOWER($1)
                         AND deleted_at IS NULL
                       LIMIT 1""",
                    s,
                )
                if not resolved:
                    # Fallback: match hardware_id prefix (e.g. CLIENT_JAIMECARPENTER_ID -> CLIENT_JAIMECARPENTER%)
                    prefix = s[:-3] if s.upper().endswith("_ID") else s
                    if prefix and len(prefix) > 5:
                        resolved = await conn.fetchval(
                            """SELECT id FROM users
                               WHERE hardware_id LIKE $1 || '%' AND deleted_at IS NULL
                               ORDER BY hardware_id LIMIT 1""",
                            prefix,
                        )
                if not resolved:
                    # Fallback: match profile name (strip ID suffix, replace _ with %)
                    name_part = s.replace("CLIENT_", "").replace("COACH_", "").replace("ADMIN_", "").rstrip("_ID").replace("_", "%")
                    if len(name_part) >= 2:
                        resolved = await conn.fetchval(
                            """SELECT id FROM users
                               WHERE LOWER(profile_data->>'name') LIKE '%' || LOWER($1) || '%'
                                 AND deleted_at IS NULL
                               LIMIT 1""",
                            name_part,
                        )
            if resolved:
                subject_ids.append(resolved)
            else:
                raise HTTPException(400, f"Could not resolve user: {s}")

    from app.services.nevedal_report_generator import NevedalReportGenerator

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
    user_id: str = Depends(_check_report_tier),
):
    """
    Generate a personalized weekly coherence brief.
    Pulls C_emo trends, memory transcripts, coach notes, session summaries,
    and relational themes — then uses Azure OpenAI to produce a deeply
    personal brief grounded in the client's lived experience with Little Nate.
    """
    db = request.app.state.db_pool
    user_uuid = None

    try:
        async with db.acquire() as conn:
            user_row = await conn.fetchrow(
                "SELECT id, username, profile_data FROM users "
                "WHERE (hardware_id = $1 OR username = $1) AND deleted_at IS NULL LIMIT 1",
                user_id,
            )
            if not user_row:
                return {
                    "brief": "I couldn't find your profile. Try logging in again.",
                    "mood_summary": {"sessions": 0, "data_points": 0},
                    "goal": "Reconnect with Little Nate to start tracking your coherence.",
                }
            user_uuid = user_row["id"]
            username = user_row["username"]
            profile = user_row["profile_data"] or {}
            if isinstance(profile, str):
                try:
                    profile = json.loads(profile)
                except Exception:
                    profile = {}
            client_name = profile.get("name", username)

            metrics = await conn.fetch("""
                SELECT c_emo, p_ent, t_tunnel, gamma_env,
                       cee_window, recorded_at
                FROM nevedal_metrics
                WHERE user_id = $1
                  AND recorded_at >= NOW() - INTERVAL '7 days'
                ORDER BY recorded_at ASC
            """, user_uuid)

            sessions = await conn.fetch("""
                SELECT id, session_type, started_at, ended_at, duration_seconds, coach_id
                FROM sessions
                WHERE user_id = $1
                  AND started_at >= NOW() - INTERVAL '7 days'
                ORDER BY started_at ASC
            """, user_uuid)
    except Exception as e:
        logger.warning("Brief data fetch error: %s", e)
        metrics = []
        sessions = []
        client_name = "friend"
        username = user_id

    # --- Memory transcripts (last 7 days, up to 15 exchanges) ---
    memory_context = ""
    topics_found = set()
    try:
        mem_path = _VAULT_ROOT / "Clients" / user_id / "memory.json"
        if mem_path.exists():
            all_mem = json.loads(mem_path.read_text())
            cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
            recent = [e for e in all_mem if (e.get("timestamp", "") >= cutoff)]
            if not recent:
                recent = all_mem[-15:]
            else:
                recent = recent[-15:]

            topic_keywords = [
                "anxiety", "depression", "family", "work", "relationship",
                "sleep", "stress", "anger", "fear", "grief", "trauma",
                "childhood", "parent", "mother", "father", "spouse", "child",
                "boss", "friend", "loneliness", "self-worth", "confidence",
                "divorce", "loss", "addiction", "alcohol", "faith", "purpose",
            ]
            exchanges = []
            for e in recent:
                u = e.get("user", "")
                a = e.get("ai", "")
                combined = (u + " " + a).lower()
                for kw in topic_keywords:
                    if kw in combined:
                        topics_found.add(kw)
                exchanges.append(f"  Client: {u[:150]}\n  Nate: {a[:150]}")
            memory_context = "\n".join(exchanges[-10:])
    except Exception as e:
        logger.warning("Brief memory read error: %s", e)

    # --- CEE moments from text chat (bridge metrics.json) ---
    chat_cee_count = 0
    try:
        metrics_path = _VAULT_ROOT / "Clients" / user_id / "metrics.json"
        if metrics_path.exists():
            mdata = json.loads(metrics_path.read_text())
            ns = mdata.get("nevedal_state", {})
            cee_exp = ns.get("cee_experiences", [])
            if isinstance(cee_exp, list):
                cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
                chat_cee_count = sum(
                    1 for ce in cee_exp
                    if ce.get("timestamp", "") >= cutoff
                )
    except Exception as e:
        logger.warning("Brief CEE read error: %s", e)

    # --- Coach session notes (last 7 days) ---
    coach_notes_text = ""
    try:
        if _COACH_NOTES_FILE.exists():
            store = json.loads(_COACH_NOTES_FILE.read_text())
            family_id = profile.get("family_id", "")
            key = f"family:{family_id}" if family_id else f"client:{user_id}"
            notes = store.get(key, [])
            if not notes and family_id:
                notes = store.get(f"client:{user_id}", [])
            cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
            recent_notes = [
                n for n in notes
                if n.get("created_at", "") >= cutoff
            ]
            if recent_notes:
                parts = []
                for n in recent_notes[-5:]:
                    coach = n.get("coach_name", "Coach")
                    text = n.get("note_text", n.get("text", ""))[:200]
                    parts.append(f"  {coach}: {text}")
                coach_notes_text = "\n".join(parts)
    except Exception as e:
        logger.warning("Brief coach notes read error: %s", e)

    # --- Compute metrics ---
    c_emo_values = [float(m["c_emo"]) for m in metrics if m["c_emo"] is not None]
    avg_cemo = sum(c_emo_values) / len(c_emo_values) if c_emo_values else 0
    voice_cee_count = sum(1 for m in metrics if m["cee_window"])
    total_cee = voice_cee_count + chat_cee_count
    trend = "stable"
    if len(c_emo_values) >= 3:
        half = len(c_emo_values) // 2
        first_half = sum(c_emo_values[:half]) / max(half, 1)
        second_half = sum(c_emo_values[half:]) / max(len(c_emo_values) - half, 1)
        if second_half > first_half + 0.05:
            trend = "improving"
        elif second_half < first_half - 0.05:
            trend = "dipping"

    coach_sessions = [s for s in sessions if s["session_type"] == "COACH"]
    ai_sessions = [s for s in sessions if s["session_type"] == "AI"]

    mood_summary = {
        "sessions": len(sessions),
        "coach_sessions": len(coach_sessions),
        "ai_sessions": len(ai_sessions),
        "data_points": len(metrics),
        "avg_c_emo": round(avg_cemo, 3),
        "cee_windows": total_cee,
        "voice_cee": voice_cee_count,
        "chat_cee": chat_cee_count,
        "trend": trend,
    }

    if not metrics and not memory_context:
        return {
            "brief": "You haven't had enough sessions this week for me to create a full brief yet. "
                     "That's okay — even a single conversation gives me data to work with. "
                     "Come talk to me when you're ready, and I'll have something meaningful to share.",
            "mood_summary": mood_summary,
            "goal": "Start a conversation with Little Nate this week to begin tracking your emotional patterns.",
        }

    # --- Build the rich prompt ---
    topics_str = ", ".join(sorted(topics_found)) if topics_found else "general check-ins"

    context_sections = []
    context_sections.append(f"""Data from the past 7 days:
- Client name: {client_name}
- Total sessions: {len(sessions)} ({len(ai_sessions)} with Nate, {len(coach_sessions)} with coach)
- Emotional coherence (C_emo) average: {avg_cemo:.3f} (0-1 scale)
- Trend: {trend}
- CEE moments (deep emotional shifts): {total_cee} ({voice_cee_count} voice, {chat_cee_count} chat)
- Topics discussed: {topics_str}""")

    if memory_context:
        context_sections.append(f"""Recent conversation excerpts (these are real exchanges — reference them):
{memory_context}""")

    if coach_notes_text:
        context_sections.append(f"""Coach notes from this week (incorporate any relevant themes):
{coach_notes_text}""")

    context_block = "\n\n".join(context_sections)

    prompt = f"""You are Little Nate, a warm AI therapy companion who has been walking alongside
{client_name} through their journey. Write a brief weekly check-in that shows you REMEMBER
what you've talked about. Be gentle, personal, and specific — not generic.

{context_block}

Structure:
1. A warm greeting that references something specific from this week's conversations
2. What you noticed about their emotional patterns (2-3 sentences, grounding in actual topics)
3. One specific, actionable goal for the coming week that connects to what they've been working on

Rules:
- Reference actual topics and themes from the conversations above — do NOT be generic
- If coach notes exist, weave in awareness of coaching themes naturally
- Keep it under 250 words
- Tone: Like a trusted friend who has been present through their story
- End with the weekly goal clearly stated as **Goal for this week**: ..."""

    try:
        import aiohttp
        async with aiohttp.ClientSession() as http_session:
            messages = [
                {"role": "system", "content": f"You are Little Nate, a warm AI therapy companion who knows {client_name} personally from weeks of conversations."},
                {"role": "user", "content": prompt},
            ]
            async with http_session.post(NATE_CHAT_URL, json=nate_chat_payload(messages=messages, max_tokens=450), headers=nate_chat_headers(), timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    brief_text = data["choices"][0]["message"]["content"].strip()
                else:
                    brief_text = _generate_fallback_brief(mood_summary)
    except Exception as e:
        logger.warning("AI brief generation failed: %s", e)
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
    sessions = mood_summary.get("sessions", 0)
    cee = mood_summary.get("cee_windows", 0)
    coach_sess = mood_summary.get("coach_sessions", 0)

    trend_msg = {
        "improving": "Your emotional coherence has been trending upward, which is genuinely encouraging.",
        "dipping": "Your coherence dipped a bit this week, and that's okay — growth isn't always linear.",
        "stable": "Your emotional patterns have been steady this week, showing real consistency.",
    }.get(trend, "I've been watching your patterns this week.")

    coach_note = ""
    if coach_sess:
        coach_note = f"You also had {coach_sess} session{'s' if coach_sess != 1 else ''} with your coach — that investment in yourself matters. "

    return (
        f"Hey — wanted to check in with you about your week. "
        f"You showed up for {sessions} session{'s' if sessions != 1 else ''}, "
        f"and that matters more than any number I could give you.\n\n"
        f"{trend_msg} {coach_note}"
        f"{'You had ' + str(cee) + ' moment' + ('s' if cee != 1 else '') + ' of deep emotional connection, which is beautiful.' if cee else ''}\n\n"
        f"**Goal for this week**: Take 5 minutes each day to notice one emotion without trying to change it. "
        f"Just sit with it. That simple practice builds the coherence we're tracking together."
    )
