"""
LITTLE NATE — Data Export API
Allows users to download their personal data (GDPR/CCPA compliance).
Returns profile, session summaries, coherence metrics, wisdom, social memory, billing.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse

from app.services.api_server import get_current_user

logger = logging.getLogger("nate.data_export")

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/{user_id}/data-export")
async def export_user_data(user_id: str, request: Request, user: Dict = Depends(get_current_user)):
    """
    Export all data associated with a user.
    Returns JSON containing profile, sessions, metrics, wisdom, social, and billing data.
    """
    requesting_user = user.get("user_id", user.get("username", ""))
    requesting_role = user.get("role", "")

    if requesting_user != user_id and requesting_role != "ADMIN":
        raise HTTPException(status_code=403, detail="Can only export your own data")

    pool = request.app.state.db_pool
    export = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "profile": {},
        "session_summaries": [],
        "coherence_metrics": [],
        "wisdom_extractions": [],
        "social_memory": [],
        "billing_history": [],
        "community_attendance": [],
        "liminal_sessions": [],
    }

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, profile_data FROM users WHERE username = $1",
            user_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        user_uuid = row["id"]

        profile = row.get("profile_data", {}) or {}
        if isinstance(profile, str):
            import json as _json
            try:
                profile = _json.loads(profile)
            except Exception:
                profile = {}
        safe_profile = {
            k: v for k, v in profile.items()
            if k not in ("password_hash", "totp_secret", "webauthn_credentials")
        }
        export["profile"] = safe_profile

        try:
            sessions = await conn.fetch("""
                SELECT id, started_at, ended_at, session_type,
                       status, duration_seconds
                FROM sessions
                WHERE user_id = $1
                ORDER BY started_at DESC
                LIMIT 500
            """, user_uuid)
            export["session_summaries"] = [
                {
                    "session_id": str(s["id"]) if s["id"] else None,
                    "started_at": s["started_at"].isoformat() if s["started_at"] else None,
                    "ended_at": s["ended_at"].isoformat() if s["ended_at"] else None,
                    "session_type": s.get("session_type"),
                    "status": s.get("status"),
                    "duration_seconds": s.get("duration_seconds"),
                }
                for s in sessions
            ]
        except Exception:
            pass

        try:
            metrics = await conn.fetch("""
                SELECT c_emo, gap, velocity, risk_level,
                       mood_current, mood_trend, updated_at
                FROM client_metrics
                WHERE user_id = $1
                ORDER BY updated_at DESC
                LIMIT 100
            """, user_uuid)
            export["coherence_metrics"] = [
                {
                    "c_emo": float(m["c_emo"]) if m.get("c_emo") else None,
                    "gap": float(m["gap"]) if m.get("gap") else None,
                    "velocity": float(m["velocity"]) if m.get("velocity") else None,
                    "risk_level": m.get("risk_level"),
                    "mood_current": m.get("mood_current"),
                    "mood_trend": m.get("mood_trend"),
                    "updated_at": m["updated_at"].isoformat() if m.get("updated_at") else None,
                }
                for m in metrics
            ]
        except Exception:
            pass

        try:
            wisdom = await conn.fetch("""
                SELECT insight_type, content, source, extracted_at
                FROM wisdom_extractions
                WHERE user_id = $1
                ORDER BY extracted_at DESC
                LIMIT 500
            """, user_uuid)
            export["wisdom_extractions"] = [
                {
                    "type": w.get("insight_type"),
                    "content": w.get("content"),
                    "source": w.get("source"),
                    "extracted_at": w["extracted_at"].isoformat() if w.get("extracted_at") else None,
                }
                for w in wisdom
            ]
        except Exception:
            pass

        try:
            social = await conn.fetch("""
                SELECT platform, platform_handle, interaction_count, last_interaction
                FROM skyeye_social_memory
                ORDER BY last_interaction DESC
                LIMIT 200
            """)
            export["social_memory"] = [
                {
                    "platform": s.get("platform"),
                    "handle": s.get("platform_handle"),
                    "interactions": s.get("interaction_count"),
                    "last_interaction": s["last_interaction"].isoformat() if s.get("last_interaction") else None,
                }
                for s in social
            ]
        except Exception:
            pass

        try:
            billing = await conn.fetch("""
                SELECT type, content, created_at
                FROM skyeye_activity
                WHERE (content LIKE '%' || $1 || '%')
                  AND type IN ('subscription_created', 'subscription_updated',
                               'iap_receipt_verified', 'token_purchase', 'token_deduction')
                ORDER BY created_at DESC
                LIMIT 200
            """, user_id)
            export["billing_history"] = [
                {
                    "type": b.get("type"),
                    "content": b.get("content"),
                    "timestamp": b["created_at"].isoformat() if b.get("created_at") else None,
                }
                for b in billing
            ]
        except Exception:
            pass

        try:
            attendance = await conn.fetch("""
                SELECT session_date, group_name, location_name, check_in_time,
                       check_out_time, duration_minutes, verified_by_manager
                FROM community_attendance_records
                WHERE user_id = $1
                ORDER BY session_date DESC
                LIMIT 500
            """, user_id)
            export["community_attendance"] = [
                {
                    "date": str(a.get("session_date", "")),
                    "group": a.get("group_name"),
                    "location": a.get("location_name"),
                    "check_in": a["check_in_time"].isoformat() if a.get("check_in_time") else None,
                    "check_out": a["check_out_time"].isoformat() if a.get("check_out_time") else None,
                    "duration_minutes": a.get("duration_minutes"),
                    "verified": a.get("verified_by_manager"),
                }
                for a in attendance
            ]
        except Exception:
            pass

        try:
            liminal = await conn.fetch("""
                SELECT platform, contact_alias, started_at, ended_at, message_count
                FROM liminal_sessions
                WHERE user_id = $1
                ORDER BY started_at DESC
                LIMIT 200
            """, user_id)
            export["liminal_sessions"] = [
                {
                    "platform": l.get("platform"),
                    "contact": l.get("contact_alias"),
                    "started": l["started_at"].isoformat() if l.get("started_at") else None,
                    "ended": l["ended_at"].isoformat() if l.get("ended_at") else None,
                    "messages": l.get("message_count"),
                }
                for l in liminal
            ]
        except Exception:
            pass

    await _log_export(pool, user_id)

    return JSONResponse(
        content=export,
        headers={
            "Content-Disposition": f'attachment; filename="sovereign_sanctuary_data_{user_id}.json"',
            "Content-Type": "application/json",
        },
    )


async def _log_export(pool, user_id: str):
    """Log the data export event."""
    try:
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO skyeye_activity (type, platform, content, created_at)
                VALUES ('data_export', 'system', $1, NOW())
            """, f"User {user_id} exported their data")
    except Exception as e:
        logger.warning("Failed to log data export: %s", e)
