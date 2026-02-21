"""
LITTLE NATE — SkyEye Social Media Hub API
All endpoints for the social media autonomy dashboard.
37+ endpoints covering: overview, platforms, activity, approvals,
compliance, drip suggestions, history, sessions, pulse, chat,
live expressions, social interactions, social memory,
content queue, platform connections, moderation, and content generation.
"""

import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.services.api_server import require_admin

logger = logging.getLogger("skyeye.api")

router = APIRouter(
    prefix="/api/skyeye",
    tags=["skyeye"],
    dependencies=[Depends(require_admin)],
)

# Public router for OAuth callbacks (called by external platforms, no auth)
oauth_router = APIRouter(prefix="/api/skyeye", tags=["skyeye-oauth"])


# =============================================================================
# REQUEST MODELS
# =============================================================================

class ModeUpdate(BaseModel):
    mode: str  # full/approval/observation

class ActivityEntry(BaseModel):
    platform: Optional[str] = None
    type: str
    content: Optional[str] = None
    compliance_note: Optional[str] = None
    pillar: Optional[str] = None
    severity: Optional[str] = "info"
    metadata: Optional[dict] = None

class ApprovalAction(BaseModel):
    action: str  # approve/review/reject

class ChatMessage(BaseModel):
    message: str
    mode: Optional[str] = None

class ChatActionExecute(BaseModel):
    action_id: str

class ExpressionCapture(BaseModel):
    raw_text: str
    emotion_tag: Optional[str] = "gratitude"
    session_type: Optional[str] = "individual"

class ExpressionPost(BaseModel):
    platform: str

class SocialInteractionEntry(BaseModel):
    platform: str
    platform_handle: str
    interaction_type: str  # comment/reply/dm/like/mention
    nate_message: Optional[str] = None
    user_message: Optional[str] = None
    user_interests_detected: Optional[List[str]] = None
    sentiment: Optional[str] = "neutral"

class SocialMemoryMatch(BaseModel):
    platform_handle: str
    platform: str
    user_id: str

class ContentQueueEntry(BaseModel):
    platform: str
    content_text: str
    content_type: Optional[str] = "post"
    media_url: Optional[str] = None
    emotion_context: Optional[str] = None
    priority: Optional[str] = "normal"
    scheduled_for: Optional[str] = None  # ISO datetime string

class ContentQueueSchedule(BaseModel):
    scheduled_for: str  # ISO datetime string

class GeneratePostRequest(BaseModel):
    platform: str
    topic: str
    context: Optional[dict] = None


# =============================================================================
# 1. OVERVIEW
# =============================================================================

@router.get("/overview")
async def get_overview(request: Request):
    """Aggregated SkyEye metrics for the Command Center."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        # Total followers
        total_followers = await conn.fetchval(
            "SELECT COALESCE(SUM(followers), 0) FROM skyeye_platforms WHERE enabled = TRUE"
        )
        # Average engagement
        avg_engagement = await conn.fetchval(
            "SELECT COALESCE(AVG(engagement), 0) FROM skyeye_platforms WHERE enabled = TRUE"
        )
        # Total posts
        total_posts = await conn.fetchval(
            "SELECT COALESCE(SUM(posts), 0) FROM skyeye_platforms WHERE enabled = TRUE"
        )
        # Compliance score (percentage of compliant platforms)
        total_platforms = await conn.fetchval(
            "SELECT COUNT(*) FROM skyeye_platforms WHERE enabled = TRUE"
        )
        compliant = await conn.fetchval(
            "SELECT COUNT(*) FROM skyeye_platforms WHERE compliance_status = 'compliant' AND enabled = TRUE"
        )
        compliance_score = round((compliant / max(total_platforms, 1)) * 100)
        # Pending approvals
        pending_approvals = await conn.fetchval(
            "SELECT COUNT(*) FROM skyeye_approvals WHERE status = 'pending'"
        )
        # Pending expressions
        pending_expressions = await conn.fetchval(
            "SELECT COUNT(*) FROM skyeye_live_expressions WHERE approved = FALSE"
        )
        # Today's activity count
        today_activity = await conn.fetchval(
            "SELECT COUNT(*) FROM skyeye_activity WHERE created_at >= CURRENT_DATE"
        )
        # Security events today
        security_events = await conn.fetchval(
            """SELECT COUNT(*) FROM skyeye_activity
               WHERE created_at >= CURRENT_DATE
               AND type IN ('security_threat','social_engineering_attempt','suspicious_link',
                           'account_security','ddos_suspected','data_extraction_attempt','recon_attempt',
                           'bot_detected','bot_swarm')"""
        )

    return {
        "total_followers": total_followers,
        "avg_engagement": float(avg_engagement),
        "total_posts": total_posts,
        "compliance_score": compliance_score,
        "pending_approvals": pending_approvals,
        "pending_expressions": pending_expressions,
        "today_activity": today_activity,
        "security_events_today": security_events
    }


# =============================================================================
# 2-3. PLATFORMS
# =============================================================================

@router.get("/platforms")
async def get_platforms(request: Request):
    """All platform configs with current mode."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, name, display_name, tier, control_mode, followers,
                      engagement, posts, content_type, aigc_method,
                      compliance_status, icon, color, enabled
               FROM skyeye_platforms
               ORDER BY tier, display_name"""
        )
    return [dict(r) for r in rows]


@router.put("/platforms/{platform_id}/mode")
async def update_platform_mode(platform_id: int, body: ModeUpdate, request: Request):
    """Change control mode for a platform."""
    if body.mode not in ("full", "approval", "observation"):
        raise HTTPException(status_code=400, detail="Mode must be full/approval/observation")
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE skyeye_platforms SET control_mode = $1, updated_at = NOW()
               WHERE id = $2 RETURNING id, name, control_mode""",
            body.mode, platform_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Platform not found")
        # Log activity
        await conn.execute(
            """INSERT INTO skyeye_activity (platform, type, content)
               VALUES ($1, 'mode_change', $2)""",
            row["name"], f"Control mode changed to {body.mode}"
        )
    return dict(row)


# =============================================================================
# 4-5. ACTIVITY
# =============================================================================

@router.get("/activity")
async def get_activity(
    request: Request,
    platform: Optional[str] = None,
    type: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0)
):
    """Activity feed with pagination and filters."""
    pool = request.app.state.db_pool
    conditions = []
    params = []
    idx = 1

    if platform:
        conditions.append(f"platform = ${idx}")
        params.append(platform)
        idx += 1
    if type:
        conditions.append(f"type = ${idx}")
        params.append(type)
        idx += 1

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT id, platform, type, content, compliance_note, pillar,
                       severity, metadata, created_at
                FROM skyeye_activity
                {where}
                ORDER BY created_at DESC
                LIMIT ${idx} OFFSET ${idx + 1}""",
            *params, limit, offset
        )
    return [
        {**dict(r), "metadata": json.loads(r["metadata"]) if r["metadata"] else {},
         "created_at": r["created_at"].isoformat()}
        for r in rows
    ]


@router.post("/activity")
async def log_activity(entry: ActivityEntry, request: Request):
    """Log a new activity entry."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO skyeye_activity (platform, type, content, compliance_note, pillar, severity, metadata)
               VALUES ($1, $2, $3, $4, $5, $6, $7)
               RETURNING id, created_at""",
            entry.platform, entry.type, entry.content,
            entry.compliance_note, entry.pillar, entry.severity,
            json.dumps(entry.metadata or {})
        )
    return {"id": row["id"], "created_at": row["created_at"].isoformat()}


# =============================================================================
# 6-8. APPROVALS
# =============================================================================

@router.get("/approvals")
async def get_approvals(request: Request, status: str = Query(default="pending")):
    """Get approval queue items by status."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, platform, type, content, priority, reason, status,
                      auto_approved, created_at, resolved_at, resolved_by
               FROM skyeye_approvals
               WHERE status = $1
               ORDER BY
                   CASE priority WHEN 'safety' THEN 0 WHEN 'critical' THEN 1
                                 WHEN 'high' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END,
                   created_at DESC""",
            status
        )
    return [dict(r) for r in rows]


@router.post("/approvals/{approval_id}/approve")
async def approve_item(approval_id: int, request: Request):
    """Approve a queue item."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE skyeye_approvals
               SET status = 'approved', resolved_at = NOW(), resolved_by = 'admin'
               WHERE id = $1 RETURNING id, platform, type, content""",
            approval_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Approval item not found")
        await conn.execute(
            """INSERT INTO skyeye_activity (platform, type, content)
               VALUES ($1, 'approval_granted', $2)""",
            row["platform"], f"Approved: {row['content'][:100]}"
        )
    return {"status": "approved", "id": row["id"]}


@router.post("/approvals/{approval_id}/reject")
async def reject_item(approval_id: int, request: Request):
    """Reject a queue item."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE skyeye_approvals
               SET status = 'rejected', resolved_at = NOW(), resolved_by = 'admin'
               WHERE id = $1 RETURNING id""",
            approval_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Approval item not found")
    return {"status": "rejected", "id": row["id"]}


# =============================================================================
# 9. COMPLIANCE
# =============================================================================

@router.get("/compliance")
async def get_compliance(request: Request):
    """Compliance metrics and per-platform matrix."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        # Get latest audit per platform
        rows = await conn.fetch(
            """SELECT DISTINCT ON (platform)
                      id, platform, aigc_labels_applied, bio_disclosure,
                      anti_bot, public_figure, ftc_compliant, coppa_compliant,
                      special_notes, audited_at
               FROM skyeye_compliance
               ORDER BY platform, audited_at DESC"""
        )
        matrix = [dict(r) for r in rows]

        # Calculate overall score
        total_checks = 0
        passed_checks = 0
        for m in matrix:
            for field in ["aigc_labels_applied", "bio_disclosure", "anti_bot",
                          "public_figure", "ftc_compliant", "coppa_compliant"]:
                total_checks += 1
                if m.get(field):
                    passed_checks += 1

        overall_score = round((passed_checks / max(total_checks, 1)) * 100)

    return {
        "overall_score": overall_score,
        "total_checks": total_checks,
        "passed_checks": passed_checks,
        "matrix": matrix
    }


# =============================================================================
# 10-11. DRIP SUGGESTIONS
# =============================================================================

@router.get("/drip-suggestions")
async def get_drip_suggestions(request: Request):
    """Get drip campaign bridge suggestions."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, topic, insight, confidence, source, status, created_at
               FROM skyeye_drip_suggestions
               ORDER BY confidence DESC, created_at DESC"""
        )
    return [dict(r) for r in rows]


@router.post("/drip-suggestions/{suggestion_id}/action")
async def drip_suggestion_action(suggestion_id: int, body: ApprovalAction, request: Request):
    """Act on a drip suggestion (approve/review/reject)."""
    if body.action not in ("approve", "review", "reject"):
        raise HTTPException(status_code=400, detail="Action must be approve/review/reject")
    pool = request.app.state.db_pool
    status_map = {"approve": "approved", "review": "reviewed", "reject": "rejected"}
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE skyeye_drip_suggestions SET status = $1
               WHERE id = $2 RETURNING id, topic, status""",
            status_map[body.action], suggestion_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Suggestion not found")
    return dict(row)


# =============================================================================
# 12. HISTORY
# =============================================================================

@router.get("/history")
async def get_history(
    request: Request,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0)
):
    """Session history log."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT h.id, h.platform, h.action, h.detail, h.session_id, h.created_at
               FROM skyeye_history h
               ORDER BY h.created_at DESC
               LIMIT $1 OFFSET $2""",
            limit, offset
        )
    return [dict(r) for r in rows]


# =============================================================================
# 13-15. SESSIONS + PULSE
# =============================================================================

@router.get("/sessions")
async def get_sessions(request: Request):
    """Session schedule info."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        # Current or next session
        current = await conn.fetchrow(
            """SELECT id, session_start, session_end, platforms_visited,
                      total_actions, status, notes
               FROM skyeye_sessions
               WHERE status IN ('active', 'scheduled')
               ORDER BY session_start ASC
               LIMIT 1"""
        )
        # Recent completed sessions
        recent = await conn.fetch(
            """SELECT id, session_start, session_end, platforms_visited,
                      total_actions, status
               FROM skyeye_sessions
               WHERE status = 'completed'
               ORDER BY session_end DESC
               LIMIT 5"""
        )

    return {
        "current_session": dict(current) if current else None,
        "recent_sessions": [dict(r) for r in recent]
    }


@router.get("/pulse")
async def get_pulse(request: Request):
    """
    Live pulse: current state + last 3 actions.
    Polled every 30s by the frontend.
    """
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        # Current session status
        session = await conn.fetchrow(
            """SELECT id, status FROM skyeye_sessions
               WHERE status = 'active' LIMIT 1"""
        )
        state = "active" if session else "resting"

        # Last 3 actions
        actions = await conn.fetch(
            """SELECT platform, type, content, created_at
               FROM skyeye_activity
               ORDER BY created_at DESC LIMIT 3"""
        )

    return {
        "state": state,
        "session_id": session["id"] if session else None,
        "last_actions": [
            {
                "platform": a["platform"],
                "type": a["type"],
                "content": (a["content"] or "")[:100],
                "timestamp": a["created_at"].isoformat()
            }
            for a in actions
        ]
    }


@router.post("/sessions/toggle")
async def toggle_session(request: Request):
    """Wake/rest toggle — start or end a session."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        # Check if there's an active session
        active = await conn.fetchrow(
            "SELECT id FROM skyeye_sessions WHERE status = 'active' LIMIT 1"
        )
        if active:
            # End the session
            await conn.execute(
                """UPDATE skyeye_sessions
                   SET status = 'completed', session_end = NOW()
                   WHERE id = $1""",
                active["id"]
            )
            await conn.execute(
                """INSERT INTO skyeye_activity (type, content)
                   VALUES ('rest', 'Little Nate entering rest mode')"""
            )
            return {"action": "rest", "session_id": active["id"]}
        else:
            # Start a new session
            row = await conn.fetchrow(
                """INSERT INTO skyeye_sessions (session_start, status)
                   VALUES (NOW(), 'active')
                   RETURNING id, session_start"""
            )
            await conn.execute(
                """INSERT INTO skyeye_activity (type, content)
                   VALUES ('wake', 'Little Nate is now active on social media')"""
            )
            return {
                "action": "wake",
                "session_id": row["id"],
                "session_start": row["session_start"].isoformat()
            }


# =============================================================================
# 16-17. CHAT
# =============================================================================

@router.get("/chat")
async def get_chat(request: Request, limit: int = Query(default=200, le=5000)):
    """Get chat message history (unlimited for Sovereign Command)."""
    from app.services.skyeye_chat import SkyEyeChatService
    service = SkyEyeChatService(request.app.state.db_pool)
    return await service.get_chat_history(limit=limit)


@router.post("/chat")
async def send_chat(body: ChatMessage, request: Request):
    """Send a message from Big Nate and get Little Nate's AI response."""
    from app.services.skyeye_chat import SkyEyeChatService
    service = SkyEyeChatService(request.app.state.db_pool)
    return await service.send_message(body.message, mode_override=body.mode)


@router.post("/chat/execute")
async def execute_chat_action(body: ChatActionExecute, request: Request):
    """Execute a confirmed action from the Big Nate Chat interface."""
    from app.services.skyeye_chat import SkyEyeChatService
    service = SkyEyeChatService(request.app.state.db_pool)
    return await service.execute_confirmed_action(body.action_id)


@router.delete("/chat")
async def clear_chat(request: Request, archive: bool = Query(default=True)):
    """Clear Big Nate Chat history, optionally archiving to strategic memory first."""
    pool = request.app.state.db_pool
    archived_count = 0

    async with pool.acquire() as conn:
        if archive:
            messages = await conn.fetch(
                "SELECT sender, message, metadata, created_at FROM skyeye_chat ORDER BY created_at ASC"
            )
            if messages:
                lines = []
                for m in messages:
                    prefix = "Big Nate" if m["sender"] == "big_nate" else "Little Nate"
                    ts = m["created_at"].strftime("%Y-%m-%d %H:%M") if m["created_at"] else ""
                    lines.append(f"[{ts}] {prefix}: {m['message']}")
                transcript = "\n".join(lines)
                archived_count = len(messages)

                import json as _json
                await conn.execute("""
                    INSERT INTO swarm_oversight_log
                        (event_type, details, metadata)
                    VALUES ('chat_archive', $1, $2)
                """, _json.dumps({"transcript": transcript, "message_count": archived_count}),
                     _json.dumps({"source": "big_nate_chat_clear", "archived_at": datetime.utcnow().isoformat()}))

        deleted = await conn.execute("DELETE FROM skyeye_chat")

    return {
        "cleared": True,
        "archived": archive,
        "archived_count": archived_count,
        "message": f"Chat cleared. {archived_count} messages archived to strategic memory." if archive else "Chat cleared.",
    }


@router.get("/chat/archives")
async def list_chat_archives(request: Request):
    """List all archived Big Nate Chat conversations stored in strategic memory."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, entry_id, details, metadata, created_at
            FROM swarm_oversight_log
            WHERE event_type = 'chat_archive'
            ORDER BY created_at DESC
        """)

    import json as _json
    archives = []
    for r in rows:
        details = r["details"]
        if isinstance(details, str):
            details = _json.loads(details)
        transcript = (details or {}).get("transcript", "")
        msg_count = (details or {}).get("message_count", 0)
        preview = transcript[:200] + ("..." if len(transcript) > 200 else "")
        meta = r["metadata"]
        if isinstance(meta, str):
            meta = _json.loads(meta)
        archives.append({
            "id": r["id"],
            "entry_id": str(r["entry_id"]),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "message_count": msg_count,
            "preview": preview,
            "archived_at": (meta or {}).get("archived_at"),
        })
    return archives


@router.get("/chat/archives/{entry_id}")
async def get_chat_archive(entry_id: str, request: Request):
    """Get the full transcript for a specific archived conversation."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, entry_id, details, metadata, created_at
            FROM swarm_oversight_log
            WHERE entry_id = $1::uuid AND event_type = 'chat_archive'
        """, entry_id)

    if not row:
        from fastapi import HTTPException
        raise HTTPException(404, "Archive not found")

    import json as _json
    details = row["details"]
    if isinstance(details, str):
        details = _json.loads(details)
    meta = row["metadata"]
    if isinstance(meta, str):
        meta = _json.loads(meta)

    return {
        "id": row["id"],
        "entry_id": str(row["entry_id"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "message_count": (details or {}).get("message_count", 0),
        "transcript": (details or {}).get("transcript", ""),
        "archived_at": (meta or {}).get("archived_at"),
    }


@router.post("/chat/archives/{entry_id}/restore")
async def restore_chat_archive(entry_id: str, request: Request):
    """Restore an archived conversation back into the active chat."""
    pool = request.app.state.db_pool
    import re as _re
    import json as _json

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT details FROM swarm_oversight_log
            WHERE entry_id = $1::uuid AND event_type = 'chat_archive'
        """, entry_id)

    if not row:
        from fastapi import HTTPException
        raise HTTPException(404, "Archive not found")

    details = row["details"]
    if isinstance(details, str):
        details = _json.loads(details)
    transcript = (details or {}).get("transcript", "")
    if not transcript:
        return {"restored": 0, "message": "Archive was empty."}

    line_pattern = _re.compile(
        r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]\s+(Big Nate|Little Nate):\s+(.*)',
        _re.DOTALL,
    )

    parsed = []
    for line in transcript.split("\n"):
        m = line_pattern.match(line)
        if m:
            ts_str, speaker, text = m.group(1), m.group(2), m.group(3)
            sender = "big_nate" if speaker == "Big Nate" else "little_nate"
            parsed.append((sender, text.strip(), ts_str))

    if not parsed:
        return {"restored": 0, "message": "Could not parse archive transcript."}

    async with pool.acquire() as conn:
        for sender, message, ts_str in parsed:
            await conn.execute("""
                INSERT INTO skyeye_chat (sender, message, metadata, created_at)
                VALUES ($1, $2, '{}', ($3 || ':00')::timestamptz)
            """, sender, message, ts_str)

    return {
        "restored": len(parsed),
        "message": f"Restored {len(parsed)} messages from archive.",
    }


# =============================================================================
# 18-23. LIVE EXPRESSIONS
# =============================================================================

@router.get("/expressions")
async def get_expressions(
    request: Request,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0)
):
    """Live expressions feed (approved, anonymized client moments)."""
    from app.services.skyeye_expressions import SkyEyeExpressionsService
    service = SkyEyeExpressionsService(request.app.state.db_pool)
    expressions = await service.get_approved_expressions(limit=limit, offset=offset)
    stats = await service.get_expression_stats()
    return {"expressions": expressions, "stats": stats}


@router.get("/expressions/pending")
async def get_pending_expressions(request: Request):
    """Expressions awaiting admin approval."""
    from app.services.skyeye_expressions import SkyEyeExpressionsService
    service = SkyEyeExpressionsService(request.app.state.db_pool)
    return await service.get_pending_expressions()


@router.post("/expressions/{expression_id}/approve")
async def approve_expression(expression_id: int, request: Request):
    """Approve an expression for the live wall."""
    from app.services.skyeye_expressions import SkyEyeExpressionsService
    service = SkyEyeExpressionsService(request.app.state.db_pool)
    return await service.approve_expression(expression_id)


@router.post("/expressions/{expression_id}/reject")
async def reject_expression(expression_id: int, request: Request):
    """Reject/delete an expression."""
    from app.services.skyeye_expressions import SkyEyeExpressionsService
    service = SkyEyeExpressionsService(request.app.state.db_pool)
    return await service.reject_expression(expression_id)


@router.post("/expressions/{expression_id}/post")
async def post_expression(expression_id: int, body: ExpressionPost, request: Request):
    """Format and mark an expression as posted to a platform."""
    from app.services.skyeye_expressions import SkyEyeExpressionsService
    service = SkyEyeExpressionsService(request.app.state.db_pool)

    # Format in Little Nate's voice
    formatted = await service.format_for_posting(expression_id)
    if "error" in formatted:
        raise HTTPException(status_code=404, detail=formatted["error"])

    # Try to post via real platform adapter (Phase 2)
    post_result = None
    try:
        from app.services.platforms import get_adapter
        adapter = get_adapter(body.platform, request.app.state.db_pool)
        if adapter:
            auth_ok = await adapter.authenticate()
            if auth_ok:
                post_result = await adapter.post_content(
                    text=formatted["formatted_post"]
                )
    except Exception as e:
        # Graceful degradation — log but don't fail the request
        import logging
        logging.getLogger("skyeye").warning(
            f"Platform post failed for {body.platform}: {e}"
        )

    # Mark as posted in DB
    result = await service.mark_as_posted(
        expression_id, body.platform, formatted["formatted_post"]
    )
    result["formatted_post"] = formatted["formatted_post"]

    # Include platform post result if available
    if post_result:
        result["platform_post"] = {
            "success": post_result.success,
            "post_id": post_result.post_id,
            "post_url": post_result.post_url,
            "error": post_result.error,
        }

    return result


@router.post("/expressions/capture")
async def capture_expression(body: ExpressionCapture, request: Request):
    """
    Internal endpoint: capture a new anonymized expression.
    Called by the session/therapy system when a CEE is detected.
    """
    from app.services.skyeye_expressions import SkyEyeExpressionsService
    service = SkyEyeExpressionsService(request.app.state.db_pool)
    return await service.capture_expression(
        raw_text=body.raw_text,
        emotion_tag=body.emotion_tag,
        session_type=body.session_type
    )


# =============================================================================
# 24-25. SOCIAL INTERACTIONS
# =============================================================================

@router.get("/social-interactions")
async def get_social_interactions(
    request: Request,
    platform: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0)
):
    """List recent social media interactions."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        if platform:
            rows = await conn.fetch(
                """SELECT id, platform, platform_handle, interaction_type,
                          nate_message, user_message, user_interests_detected,
                          sentiment, created_at
                   FROM skyeye_social_interactions
                   WHERE platform = $1
                   ORDER BY created_at DESC
                   LIMIT $2 OFFSET $3""",
                platform, limit, offset
            )
        else:
            rows = await conn.fetch(
                """SELECT id, platform, platform_handle, interaction_type,
                          nate_message, user_message, user_interests_detected,
                          sentiment, created_at
                   FROM skyeye_social_interactions
                   ORDER BY created_at DESC
                   LIMIT $1 OFFSET $2""",
                limit, offset
            )
    return [dict(r) for r in rows]


@router.post("/social-interactions")
async def log_social_interaction(entry: SocialInteractionEntry, request: Request):
    """Log a new social interaction."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO skyeye_social_interactions
               (platform, platform_handle, interaction_type, nate_message,
                user_message, user_interests_detected, sentiment)
               VALUES ($1, $2, $3, $4, $5, $6, $7)
               RETURNING id, created_at""",
            entry.platform, entry.platform_handle, entry.interaction_type,
            entry.nate_message, entry.user_message,
            entry.user_interests_detected or [],
            entry.sentiment
        )

        # Update or create social memory
        existing = await conn.fetchrow(
            """SELECT id, interaction_count, interests
               FROM skyeye_social_memory
               WHERE platform_handle = $1 AND platform = $2""",
            entry.platform_handle, entry.platform
        )

        if existing:
            # Merge interests
            current_interests = list(existing["interests"] or [])
            new_interests = list(set(current_interests + (entry.user_interests_detected or [])))
            await conn.execute(
                """UPDATE skyeye_social_memory
                   SET interaction_count = interaction_count + 1,
                       interests = $1,
                       last_interaction = NOW(),
                       updated_at = NOW()
                   WHERE id = $2""",
                new_interests, existing["id"]
            )
        else:
            await conn.execute(
                """INSERT INTO skyeye_social_memory
                   (platform_handle, platform, interaction_count, interests, last_interaction)
                   VALUES ($1, $2, 1, $3, NOW())""",
                entry.platform_handle, entry.platform,
                entry.user_interests_detected or []
            )

    return {"id": row["id"], "created_at": row["created_at"].isoformat()}


# =============================================================================
# 26-27. SOCIAL MEMORY
# =============================================================================

@router.get("/social-memory/{handle}")
async def get_social_memory(handle: str, request: Request, platform: Optional[str] = None):
    """Retrieve Little Nate's accumulated memory for a social media handle."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        if platform:
            row = await conn.fetchrow(
                """SELECT id, platform_handle, platform, interaction_count,
                          interests, tone_notes, last_interaction,
                          signup_matched, matched_user_id, summary,
                          created_at, updated_at
                   FROM skyeye_social_memory
                   WHERE platform_handle = $1 AND platform = $2""",
                handle, platform
            )
        else:
            row = await conn.fetchrow(
                """SELECT id, platform_handle, platform, interaction_count,
                          interests, tone_notes, last_interaction,
                          signup_matched, matched_user_id, summary,
                          created_at, updated_at
                   FROM skyeye_social_memory
                   WHERE platform_handle = $1
                   ORDER BY interaction_count DESC
                   LIMIT 1""",
                handle
            )
    if not row:
        raise HTTPException(status_code=404, detail="No social memory found for this handle")
    result = dict(row)
    result["matched_user_id"] = str(result["matched_user_id"]) if result["matched_user_id"] else None
    return result


@router.post("/social-memory/match")
async def match_social_memory(body: SocialMemoryMatch, request: Request):
    """Match a newly signed-up user to their social media handle."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE skyeye_social_memory
               SET signup_matched = TRUE, matched_user_id = $1, updated_at = NOW()
               WHERE platform_handle = $2 AND platform = $3
               RETURNING id, platform_handle, platform, interests, summary""",
            body.user_id, body.platform_handle, body.platform
        )
        if not row:
            raise HTTPException(status_code=404, detail="No social memory found for this handle/platform")

        # Log the match as activity
        await conn.execute(
            """INSERT INTO skyeye_activity (platform, type, content)
               VALUES ($1, 'social_memory_match', $2)""",
            row["platform"],
            f"Social follower @{row['platform_handle']} signed up and matched"
        )

    return {
        "status": "matched",
        "id": row["id"],
        "platform_handle": row["platform_handle"],
        "platform": row["platform"],
        "interests": list(row["interests"] or []),
        "summary": row["summary"]
    }


@router.get("/social-memory/unmatched")
async def get_unmatched_profiles(
    request: Request,
    min_interactions: int = Query(default=3, ge=1),
    limit: int = Query(default=50, le=200)
):
    """List social profiles with high interaction counts that haven't signed up yet."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, platform_handle, platform, interaction_count,
                      interests, tone_notes, last_interaction, summary
               FROM skyeye_social_memory
               WHERE signup_matched = FALSE
                 AND interaction_count >= $1
               ORDER BY interaction_count DESC
               LIMIT $2""",
            min_interactions, limit
        )
    return [dict(r) for r in rows]


# =============================================================================
# PHASE 2: CONTENT QUEUE
# =============================================================================

@router.get("/content-queue")
async def get_content_queue(
    request: Request,
    status: Optional[str] = Query(default=None),
    platform: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200)
):
    """List content queue items with optional filters."""
    from app.services.skyeye_content_generator import SkyEyeContentGenerator
    generator = SkyEyeContentGenerator(request.app.state.db_pool)
    return await generator.get_queue(status=status, platform=platform, limit=limit)


@router.post("/content-queue")
async def add_to_content_queue(body: ContentQueueEntry, request: Request):
    """Manually add content to the queue."""
    from app.services.skyeye_content_generator import SkyEyeContentGenerator
    from app.services.skyeye_expressions import check_content_safety

    # Safety check
    if not check_content_safety(body.content_text):
        raise HTTPException(status_code=400, detail="Content failed safety filter")

    generator = SkyEyeContentGenerator(request.app.state.db_pool)

    scheduled = None
    if body.scheduled_for:
        try:
            scheduled = datetime.fromisoformat(body.scheduled_for)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid scheduled_for datetime")

    queue_id = await generator.queue_content(
        platform=body.platform,
        content=body.content_text,
        content_type=body.content_type or "post",
        emotion_context=body.emotion_context,
        scheduled_for=scheduled,
        generated_by="admin",
        priority=body.priority or "normal",
    )

    if queue_id is None:
        raise HTTPException(status_code=500, detail="Failed to queue content")

    return {"id": queue_id, "status": "draft" if not scheduled else "scheduled"}


@router.post("/content-queue/{queue_id}/approve")
async def approve_queue_item(queue_id: int, request: Request):
    """Approve a content queue item for posting."""
    from app.services.skyeye_content_generator import SkyEyeContentGenerator
    generator = SkyEyeContentGenerator(request.app.state.db_pool)
    success = await generator.update_queue_status(
        queue_id, "approved", approved_by="admin"
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to approve item")
    return {"id": queue_id, "status": "approved"}


@router.post("/content-queue/{queue_id}/schedule")
async def schedule_queue_item(queue_id: int, body: ContentQueueSchedule, request: Request):
    """Schedule a content queue item for a specific time."""
    try:
        scheduled = datetime.fromisoformat(body.scheduled_for)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format")

    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE skyeye_content_queue
               SET status = 'scheduled', scheduled_for = $2, updated_at = NOW()
               WHERE id = $1""",
            queue_id, scheduled
        )
    return {"id": queue_id, "status": "scheduled", "scheduled_for": body.scheduled_for}


@router.delete("/content-queue/{queue_id}")
async def delete_queue_item(queue_id: int, request: Request):
    """Remove a content queue item."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM skyeye_content_queue WHERE id = $1", queue_id
        )
    return {"deleted": True, "id": queue_id}


# =============================================================================
# PHASE 2: PLATFORM CONNECTION STATUS
# =============================================================================

@router.get("/platform-status")
async def get_platform_status(request: Request):
    """Get real-time connection status for all platforms."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        # Get platform configs
        platforms = await conn.fetch(
            "SELECT name, display_name, enabled FROM skyeye_platforms ORDER BY tier, name"
        )
        # Get token statuses
        tokens = await conn.fetch(
            "SELECT platform, status, account_name, last_used, error_message, token_expiry FROM skyeye_platform_tokens"
        )

    token_map = {t["platform"]: dict(t) for t in tokens}

    from app.config import settings
    CREDENTIAL_CHECK = {
        "tiktok":    ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"),
        "instagram": ("INSTAGRAM_APP_ID", "INSTAGRAM_APP_SECRET"),
        "facebook":  ("FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET"),
        "youtube":   ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET"),
        "reddit":    ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"),
        "linkedin":  ("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"),
        "pinterest": ("PINTEREST_APP_ID", "PINTEREST_APP_SECRET"),
        "x":         ("X_CLIENT_ID", "X_CLIENT_SECRET"),
    }

    result = []
    for p in platforms:
        name = p["name"]
        tok = token_map.get(name, {})

        cred_fields = CREDENTIAL_CHECK.get(name, ())
        has_credentials = all(
            bool(getattr(settings, f, "")) for f in cred_fields
        ) if cred_fields else False

        _tok_exp = tok.get("token_expiry")
        _days_left = None
        _health = "unknown"
        if _tok_exp:
            try:
                _exp_dt = _tok_exp if isinstance(_tok_exp, datetime) else datetime.fromisoformat(str(_tok_exp).replace("Z", "+00:00"))
                _now = datetime.now(_exp_dt.tzinfo) if _exp_dt.tzinfo else datetime.now()
                _days_left = (_exp_dt - _now).days
                _health = "healthy" if _days_left > 7 else ("warning" if _days_left > 0 else "expired")
            except Exception:
                pass
        elif tok.get("status") == "connected":
            _health = "healthy"

        result.append({
            "platform": name,
            "display_name": p["display_name"],
            "enabled": p["enabled"],
            "connection_status": tok.get("status", "disconnected"),
            "has_credentials": has_credentials,
            "account_name": tok.get("account_name"),
            "last_used": tok.get("last_used"),
            "token_expiry": _tok_exp.isoformat() if isinstance(_tok_exp, datetime) else _tok_exp,
            "days_until_expiry": _days_left,
            "health": _health,
            "error": tok.get("error_message"),
        })
    return result


@router.post("/platforms/{platform}/connect")
async def initiate_platform_connect(platform: str, request: Request):
    """
    Initiate OAuth connection flow for a platform.
    If credentials are configured, returns the OAuth authorization URL.
    If not, returns the developer portal URL so admin can create an app first.
    """
    # Developer portal URLs for each platform
    DEVELOPER_PORTALS = {
        "tiktok":    "https://developers.tiktok.com/apps/",
        "instagram": "https://developers.facebook.com/apps/",
        "facebook":  "https://developers.facebook.com/apps/",
        "youtube":   "https://console.cloud.google.com/apis/credentials",
        "reddit":    "https://www.reddit.com/prefs/apps",
        "linkedin":  "https://www.linkedin.com/developers/apps",
        "pinterest": "https://developers.pinterest.com/manage/",
        "x":         "https://developer.x.com/en/portal/projects-and-apps",
    }

    # Credential requirements per platform
    CREDENTIAL_FIELDS = {
        "tiktok":    ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"),
        "instagram": ("INSTAGRAM_APP_ID", "INSTAGRAM_APP_SECRET"),
        "facebook":  ("FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET"),
        "youtube":   ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET"),
        "reddit":    ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"),
        "linkedin":  ("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"),
        "pinterest": ("PINTEREST_APP_ID", "PINTEREST_APP_SECRET"),
        "x":         ("X_CLIENT_ID", "X_CLIENT_SECRET"),
    }

    portal_url = DEVELOPER_PORTALS.get(platform)
    if not portal_url:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {platform}")

    # Check if credentials are configured
    from app.config import settings
    cred_fields = CREDENTIAL_FIELDS.get(platform, ())
    missing_creds = [f for f in cred_fields if not getattr(settings, f, "")]

    if missing_creds:
        # Credentials not configured — send admin to developer portal
        return {
            "needs_setup": True,
            "platform": platform,
            "developer_portal_url": portal_url,
            "missing_credentials": missing_creds,
            "message": (
                f"No API credentials configured for {platform}. "
                f"Create a developer app first, then add the credentials to .env on the server."
            ),
        }

    # Credentials exist — generate real OAuth URL
    from app.services.platforms import get_adapter
    adapter = get_adapter(platform, request.app.state.db_pool)
    if not adapter:
        raise HTTPException(status_code=500, detail=f"Failed to load adapter for {platform}")

    base_url = settings.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    redirect_uri = f"{base_url}/api/skyeye/platforms/{platform}/callback"

    try:
        oauth_url = await adapter.get_oauth_url(redirect_uri)
        return {
            "needs_setup": False,
            "oauth_url": oauth_url,
            "redirect_uri": redirect_uri,
        }
    except NotImplementedError:
        return {
            "needs_setup": True,
            "platform": platform,
            "developer_portal_url": portal_url,
            "message": f"OAuth flow not yet implemented for {platform}. Visit the developer portal to manage your app.",
        }


@router.get("/platforms/{platform}/connect")
async def platform_connect_redirect(platform: str, request: Request):
    """Browser-friendly GET redirect — navigates directly to OAuth authorization."""
    from app.services.platforms import get_adapter
    from app.config import settings as _settings

    adapter = get_adapter(platform, request.app.state.db_pool)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {platform}")

    base_url = _settings.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    redirect_uri = f"{base_url}/api/skyeye/platforms/{platform}/callback"

    try:
        oauth_url = await adapter.get_oauth_url(redirect_uri)
        return RedirectResponse(url=oauth_url)
    except NotImplementedError:
        raise HTTPException(status_code=501, detail=f"OAuth not implemented for {platform}")


@oauth_router.get("/platforms/{platform}/callback")
async def platform_oauth_callback(
    platform: str,
    request: Request,
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    error_description: Optional[str] = Query(default=None),
):
    """
    OAuth callback handler. Called by the platform after admin authorizes.
    Exchanges the code for tokens and stores them.
    Handles error responses (e.g. unauthorized_scope_error) gracefully.
    """
    import logging as _logging
    import urllib.parse
    _log = _logging.getLogger("skyeye.oauth")

    if error:
        desc = error_description or error
        _log.warning(f"OAuth error for {platform}: {error} — {desc}")
        dashboard_url = f"https://command.sovereignsanctuary.net/skyeye.html?oauth_error={urllib.parse.quote(desc)}&platform={platform}"
        return RedirectResponse(url=dashboard_url)

    if not code:
        raise HTTPException(status_code=400, detail="No authorization code received")

    from app.services.platforms import get_adapter
    from app.config import settings as _settings
    adapter = get_adapter(platform, request.app.state.db_pool)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {platform}")

    base_url = _settings.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    redirect_uri = f"{base_url}/api/skyeye/platforms/{platform}/callback"

    _log.info(f"OAuth callback for {platform}: code_len={len(code)}, state={state}, redirect_uri={redirect_uri}")

    try:
        success = await adapter.handle_oauth_callback(code, redirect_uri, state=state)
    except TypeError:
        success = await adapter.handle_oauth_callback(code, redirect_uri)
    if success:
        return RedirectResponse(url=f"https://command.sovereignsanctuary.net/skyeye.html?connected={platform}")
    else:
        err_msg = urllib.parse.quote(adapter.last_error or "Token exchange failed")
        return RedirectResponse(url=f"https://command.sovereignsanctuary.net/skyeye.html?oauth_error={err_msg}&platform={platform}")


# =============================================================================
# LIVESTREAM — Little Nate Live Sessions
# =============================================================================

_livestream_engine = None
_livestream_scheduler = None

def _get_livestream_engine(request):
    global _livestream_engine
    if _livestream_engine is None:
        from app.services.livestream_engine import LivestreamEngine
        _livestream_engine = LivestreamEngine(request.app.state.db_pool)
    return _livestream_engine

def _get_livestream_scheduler(request):
    global _livestream_scheduler, _livestream_engine
    if _livestream_scheduler is None:
        from app.services.livestream_scheduler import LivestreamScheduler
        engine = _get_livestream_engine(request)
        _livestream_scheduler = LivestreamScheduler(
            request.app.state.db_pool, livestream_engine=engine
        )
    return _livestream_scheduler


@router.post("/livestream/start")
async def start_livestream(request: Request):
    """Start a live streaming session."""
    body = await request.json()
    engine = _get_livestream_engine(request)
    result = await engine.start_session(
        platforms=body.get("platforms", ["x"]),
        rtmp_keys=body.get("rtmp_keys", {}),
        topic=body.get("topic"),
        duration_limit=body.get("duration_limit", 1800),
    )
    return result


@router.post("/livestream/stop")
async def stop_livestream(request: Request):
    """Stop the current live streaming session."""
    engine = _get_livestream_engine(request)
    result = await engine.stop_session()
    return result


@router.get("/livestream/status")
async def livestream_status(request: Request):
    """Get current livestream session status."""
    engine = _get_livestream_engine(request)
    return await engine.get_status()


@router.get("/livestream/history")
async def livestream_history(request: Request, limit: int = Query(default=20)):
    """Get past livestream sessions with summaries."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT session_id, status, platforms, topic,
                   duration_limit, started_at, ended_at,
                   total_interactions, unique_viewers,
                   signups_attributed, summary, created_at
            FROM livestream_sessions
            ORDER BY created_at DESC
            LIMIT $1
        """, limit)

    return [
        {
            "session_id": str(r["session_id"]),
            "status": r["status"],
            "platforms": r["platforms"],
            "topic": r["topic"],
            "duration_limit": r["duration_limit"],
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "ended_at": r["ended_at"].isoformat() if r["ended_at"] else None,
            "total_interactions": r["total_interactions"],
            "unique_viewers": r["unique_viewers"],
            "signups_attributed": r["signups_attributed"],
            "summary": r["summary"],
        }
        for r in rows
    ]


@router.get("/livestream/wisdom/{session_id}")
async def get_livestream_wisdom(session_id: str, request: Request):
    """Get all interactions from a specific livestream session."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT platform, viewer_handle, viewer_question,
                   nate_response, expression_used, signup_cta_given,
                   matched_client_id, created_at
            FROM livestream_wisdom
            WHERE session_id = $1::uuid
            ORDER BY created_at ASC
        """, session_id)

    return [
        {
            "platform": r["platform"],
            "viewer_handle": r["viewer_handle"],
            "question": r["viewer_question"],
            "response": r["nate_response"],
            "expression": r["expression_used"],
            "cta_given": r["signup_cta_given"],
            "matched_client": r["matched_client_id"],
            "timestamp": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.post("/livestream/scheduler/start")
async def start_scheduler(request: Request):
    """Enable autonomous scheduling — Little Nate picks his own live times."""
    scheduler = _get_livestream_scheduler(request)
    await scheduler.start()
    config = await scheduler.get_config()
    return {"status": "started", **config}


@router.post("/livestream/scheduler/stop")
async def stop_scheduler(request: Request):
    """Disable autonomous scheduling."""
    scheduler = _get_livestream_scheduler(request)
    await scheduler.stop()
    return {"status": "stopped"}


@router.get("/livestream/scheduler/config")
async def get_scheduler_config(request: Request):
    """Get current autonomous schedule configuration."""
    scheduler = _get_livestream_scheduler(request)
    return await scheduler.get_config()


@router.put("/livestream/scheduler/config")
async def update_scheduler_config(request: Request):
    """Update schedule preferences (sessions per week, duration)."""
    body = await request.json()
    scheduler = _get_livestream_scheduler(request)
    await scheduler.update_config(
        sessions_per_week=body.get("sessions_per_week"),
        session_duration=body.get("session_duration"),
    )
    return await scheduler.get_config()


@router.post("/livestream/preflight")
async def run_preflight(request: Request):
    """Manually run a pre-flight connection check without going live."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT rtmp_keys FROM livestream_sessions
            WHERE status = 'config'
            ORDER BY created_at DESC LIMIT 1
        """)
    if not row or not row["rtmp_keys"]:
        return {"connected": False, "error": "No RTMP keys configured"}

    import json as _json
    keys = row["rtmp_keys"]
    if isinstance(keys, str):
        keys = _json.loads(keys)

    from app.services.livestream_renderer import LivestreamRenderer
    renderer = LivestreamRenderer(keys)
    connected = await renderer.preflight_check()
    await renderer.stop()
    return {"connected": connected, "platforms": list(keys.keys())}


# =============================================================================
# TIKTOK WEBHOOK (handles POST from TikTok for event notifications)
# =============================================================================

@router.post("/platforms/tiktok/callback")
async def tiktok_webhook(request: Request):
    """
    TikTok webhook endpoint. Handles:
    1. URL verification challenge (TikTok sends a challenge, we echo it back)
    2. Event notifications (video status, comments, etc.)
    """
    import logging as _logging
    _log = _logging.getLogger("skyeye.tiktok.webhook")

    try:
        body = await request.json()
    except Exception:
        body = {}

    _log.info(f"TikTok webhook received: {body}")

    # --- URL Verification Challenge ---
    # TikTok sends: {"challenge": "<string>"} and expects it echoed back
    if "challenge" in body:
        _log.info("TikTok webhook verification challenge received")
        return {"challenge": body["challenge"]}

    # --- Event Notifications ---
    event_type = body.get("event", "unknown")
    _log.info(f"TikTok webhook event: {event_type}")

    # Acknowledge receipt -- TikTok expects 200 OK
    return {"status": "ok", "event": event_type}


# =============================================================================
# PHASE 2: MODERATION SUMMARY
# =============================================================================

@router.get("/moderation-summary")
async def get_moderation_summary(
    request: Request,
    hours: int = Query(default=24, ge=1, le=168)
):
    """Get moderation summary for the last N hours."""
    from app.services.skyeye_monitor import SkyEyeMonitor
    monitor = SkyEyeMonitor(request.app.state.db_pool)
    return await monitor.get_moderation_summary(hours=hours)


# =============================================================================
# PHASE 2: CONTENT GENERATION
# =============================================================================

@router.post("/generate-post")
async def generate_post(body: GeneratePostRequest, request: Request):
    """
    Manually trigger AI content generation for a topic/platform.
    Returns the generated content (not yet queued — admin can review first).
    """
    from app.services.skyeye_content_generator import SkyEyeContentGenerator
    generator = SkyEyeContentGenerator(request.app.state.db_pool)

    result = await generator.generate_post(
        platform=body.platform,
        topic=body.topic,
        context=body.context,
    )

    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    return result


# =============================================================================
# PHASE 2: SESSION ENGINE CONTROLS
# =============================================================================

@router.get("/engine-status")
async def get_engine_status(request: Request):
    """Get the session engine's current status."""
    engine = getattr(request.app.state, "skyeye_engine", None)
    if not engine:
        return {
            "engine_running": False,
            "state": "disabled",
            "message": "Session engine not enabled (ENABLE_SKYEYE_SESSIONS=false)",
        }

    pulse = await engine.get_pulse()
    return {
        "engine_running": True,
        **pulse,
    }


@router.post("/engine/wake")
async def wake_engine(request: Request):
    """Manually trigger a SkyEye session via the engine's manual_wake()."""
    engine = getattr(request.app.state, "skyeye_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="SkyEye session engine not running")
    result = await engine.manual_wake()
    return result


@router.post("/engine/rest")
async def rest_engine(request: Request):
    """Manually end the current SkyEye session."""
    engine = getattr(request.app.state, "skyeye_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="SkyEye session engine not running")
    result = await engine.manual_rest()
    return result


@router.get("/platform-health")
async def get_platform_health(request: Request):
    """Enhanced platform status with token expiry and health indicators."""
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        platforms = await conn.fetch(
            "SELECT name, display_name, enabled FROM skyeye_platforms ORDER BY tier, name"
        )
        tokens = await conn.fetch(
            """SELECT platform, status, account_name, last_used, error_message,
                      token_expiry, updated_at
               FROM skyeye_platform_tokens"""
        )

    token_map = {t["platform"]: dict(t) for t in tokens}

    from app.config import settings
    CREDENTIAL_CHECK = {
        "tiktok": ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"),
        "instagram": ("INSTAGRAM_APP_ID", "INSTAGRAM_APP_SECRET"),
        "facebook": ("FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET"),
        "youtube": ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET"),
        "reddit": ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"),
        "linkedin": ("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"),
        "pinterest": ("PINTEREST_APP_ID", "PINTEREST_APP_SECRET"),
        "x": ("X_CLIENT_ID", "X_CLIENT_SECRET"),
    }

    result = []
    for p in platforms:
        name = p["name"]
        tok = token_map.get(name, {})

        cred_fields = CREDENTIAL_CHECK.get(name, ())
        has_credentials = all(
            bool(getattr(settings, f, "")) for f in cred_fields
        ) if cred_fields else False

        _ph_tok_exp = tok.get("token_expiry")
        days_until_expiry = None
        health = "unknown"
        if _ph_tok_exp:
            try:
                _ph_exp_dt = _ph_tok_exp if isinstance(_ph_tok_exp, datetime) else datetime.fromisoformat(str(_ph_tok_exp).replace("Z", "+00:00"))
                _ph_now = datetime.now(_ph_exp_dt.tzinfo) if _ph_exp_dt.tzinfo else datetime.now()
                days_until_expiry = (_ph_exp_dt - _ph_now).days
                if days_until_expiry > 7:
                    health = "healthy"
                elif days_until_expiry > 0:
                    health = "warning"
                else:
                    health = "expired"
            except Exception:
                pass
        elif tok.get("status") == "connected":
            health = "healthy"

        _ph_updated = tok.get("updated_at")
        result.append({
            "platform": name,
            "display_name": p["display_name"],
            "enabled": p["enabled"],
            "connection_status": tok.get("status", "disconnected"),
            "has_credentials": has_credentials,
            "account_name": tok.get("account_name"),
            "last_used": tok.get("last_used"),
            "token_expiry": _ph_tok_exp.isoformat() if isinstance(_ph_tok_exp, datetime) else _ph_tok_exp,
            "days_until_expiry": days_until_expiry,
            "health": health,
            "error": tok.get("error_message"),
            "last_refresh_at": _ph_updated.isoformat() if isinstance(_ph_updated, datetime) else _ph_updated,
        })
    return result


@router.post("/verify-posts")
async def verify_recent_posts(request: Request):
    """
    Verify that recently posted content is still live on platforms.
    Fetches the last 24h of posted content, then checks each post's URL
    with an HTTP HEAD request and attempts platform API verification.
    """
    import httpx
    from app.services.platforms import get_adapter

    pool = request.app.state.db_pool
    results = []
    async with pool.acquire() as conn:
        recent_posts = await conn.fetch(
            """SELECT id, platform, content_text, post_url, post_id_external, posted_at
               FROM skyeye_content_queue
               WHERE status = 'posted'
                 AND posted_at > NOW() - INTERVAL '24 hours'
               ORDER BY posted_at DESC
               LIMIT 20"""
        )

        for post in recent_posts:
            verification = {
                "id": post["id"],
                "platform": post["platform"],
                "content_preview": (post["content_text"] or "")[:100],
                "post_url": post["post_url"],
                "posted_at": post["posted_at"].isoformat() if post["posted_at"] else None,
                "status": "unverifiable",
            }

            if not post["post_url"] and not post["post_id_external"]:
                verification["status"] = "no_external_reference"
                await conn.execute(
                    """INSERT INTO skyeye_activity (type, platform, content)
                       VALUES ('post_verification_warning', $1, $2)""",
                    post["platform"],
                    f"Post {post['id']} has no external URL or ID — may not have been published"
                )
                results.append(verification)
                continue

            # Try HTTP HEAD on the post URL to check if it's still reachable
            if post["post_url"]:
                try:
                    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                        resp = await client.head(post["post_url"])
                        if resp.status_code < 400:
                            verification["status"] = "verified_live"
                        elif resp.status_code == 404:
                            verification["status"] = "deleted"
                        else:
                            verification["status"] = f"http_{resp.status_code}"
                except Exception as e:
                    verification["status"] = "url_unreachable"
                    verification["error"] = str(e)[:100]

            # Try platform API verification via get_own_posts if URL check inconclusive
            if verification["status"] not in ("verified_live",) and post["post_id_external"]:
                try:
                    adapter = get_adapter(post["platform"], pool)
                    if adapter:
                        own_posts = await adapter.get_own_posts(limit=30)
                        found = any(
                            getattr(p, "post_id", None) == post["post_id_external"]
                            for p in own_posts
                        )
                        if found:
                            verification["status"] = "verified_via_api"
                        elif verification["status"] == "unverifiable":
                            verification["status"] = "not_found_in_api"
                except Exception:
                    pass

            if verification["status"] in ("deleted", "not_found_in_api"):
                await conn.execute(
                    """INSERT INTO skyeye_activity (type, platform, content)
                       VALUES ('post_verification_failed', $1, $2)""",
                    post["platform"],
                    f"Post {post['id']} appears deleted or unreachable (status: {verification['status']})"
                )

            results.append(verification)

    verified_count = sum(1 for r in results if r["status"] in ("verified_live", "verified_via_api"))
    failed_count = sum(1 for r in results if r["status"] in ("deleted", "not_found_in_api"))
    return {
        "total": len(results),
        "verified": verified_count,
        "failed": failed_count,
        "posts": results,
    }


# =============================================================================
# SECURITY HARDENING
# =============================================================================

@router.get("/dns-check")
async def dns_check():
    """
    Verify SPF, DKIM, and DMARC DNS records for sovereignsanctuary.net.
    Returns pass/fail per record so the admin dashboard can show DNS health.
    """
    import asyncio
    domain = "sovereignsanctuary.net"
    results = {
        "domain": domain,
        "spf": {"status": "fail", "record": None, "detail": "No SPF record found"},
        "dkim": {"status": "fail", "record": None, "detail": "No DKIM record found"},
        "dmarc": {"status": "fail", "record": None, "detail": "No DMARC record found"},
        "overall": "fail",
    }

    try:
        import dns.resolver
        resolver = dns.resolver.Resolver()
        resolver.timeout = 5
        resolver.lifetime = 5
    except ImportError:
        # Fallback: use subprocess dig
        import subprocess

        def _dig(qname: str, rtype: str = "TXT") -> list:
            try:
                proc = subprocess.run(
                    ["dig", "+short", rtype, qname],
                    capture_output=True, text=True, timeout=5,
                )
                return [line.strip().strip('"') for line in proc.stdout.strip().split("\n") if line.strip()]
            except Exception:
                return []

        # SPF
        for txt in _dig(domain, "TXT"):
            if "v=spf1" in txt:
                results["spf"]["record"] = txt
                if "-all" in txt:
                    results["spf"]["status"] = "pass"
                    results["spf"]["detail"] = "SPF with hard fail (-all) found"
                elif "~all" in txt:
                    results["spf"]["status"] = "warn"
                    results["spf"]["detail"] = "SPF uses soft fail (~all) — recommend -all"
                else:
                    results["spf"]["status"] = "warn"
                    results["spf"]["detail"] = "SPF found but missing -all"
                break

        # DKIM — try common selectors
        for selector in ["google", "default", "selector1", "selector2", "s1", "s2"]:
            dkim_name = f"{selector}._domainkey.{domain}"
            records = _dig(dkim_name, "TXT")
            for txt in records:
                if "v=DKIM1" in txt or "p=" in txt:
                    results["dkim"]["status"] = "pass"
                    results["dkim"]["record"] = f"{selector}._domainkey → {txt[:80]}..."
                    results["dkim"]["detail"] = f"DKIM record found (selector: {selector})"
                    break
            if results["dkim"]["status"] == "pass":
                break

        # DMARC
        for txt in _dig(f"_dmarc.{domain}", "TXT"):
            if "v=DMARC1" in txt:
                results["dmarc"]["record"] = txt
                if "p=reject" in txt:
                    results["dmarc"]["status"] = "pass"
                    results["dmarc"]["detail"] = "DMARC with p=reject found"
                elif "p=quarantine" in txt:
                    results["dmarc"]["status"] = "warn"
                    results["dmarc"]["detail"] = "DMARC with p=quarantine — recommend p=reject"
                elif "p=none" in txt:
                    results["dmarc"]["status"] = "warn"
                    results["dmarc"]["detail"] = "DMARC with p=none — recommend p=reject"
                else:
                    results["dmarc"]["status"] = "warn"
                    results["dmarc"]["detail"] = "DMARC found but policy unclear"
                break

        # Overall
        statuses = [results["spf"]["status"], results["dkim"]["status"], results["dmarc"]["status"]]
        if all(s == "pass" for s in statuses):
            results["overall"] = "pass"
        elif any(s == "fail" for s in statuses):
            results["overall"] = "fail"
        else:
            results["overall"] = "warn"

        return results

    # If dnspython is available, use it
    def _resolve_txt(qname: str) -> list:
        try:
            answers = resolver.resolve(qname, "TXT")
            return ["".join(s.decode() if isinstance(s, bytes) else s for s in rdata.strings) for rdata in answers]
        except Exception:
            return []

    # SPF
    for txt in _resolve_txt(domain):
        if "v=spf1" in txt:
            results["spf"]["record"] = txt
            if "-all" in txt:
                results["spf"]["status"] = "pass"
                results["spf"]["detail"] = "SPF with hard fail (-all) found"
            elif "~all" in txt:
                results["spf"]["status"] = "warn"
                results["spf"]["detail"] = "SPF uses soft fail (~all) — recommend -all"
            else:
                results["spf"]["status"] = "warn"
                results["spf"]["detail"] = "SPF found but missing -all"
            break

    # DKIM — try common selectors
    for selector in ["google", "default", "selector1", "selector2", "s1", "s2"]:
        dkim_name = f"{selector}._domainkey.{domain}"
        for txt in _resolve_txt(dkim_name):
            if "v=DKIM1" in txt or "p=" in txt:
                results["dkim"]["status"] = "pass"
                results["dkim"]["record"] = f"{selector}._domainkey → {txt[:80]}..."
                results["dkim"]["detail"] = f"DKIM record found (selector: {selector})"
                break
        if results["dkim"]["status"] == "pass":
            break

    # DMARC
    for txt in _resolve_txt(f"_dmarc.{domain}"):
        if "v=DMARC1" in txt:
            results["dmarc"]["record"] = txt
            if "p=reject" in txt:
                results["dmarc"]["status"] = "pass"
                results["dmarc"]["detail"] = "DMARC with p=reject found"
            elif "p=quarantine" in txt:
                results["dmarc"]["status"] = "warn"
                results["dmarc"]["detail"] = "DMARC with p=quarantine — recommend p=reject"
            elif "p=none" in txt:
                results["dmarc"]["status"] = "warn"
                results["dmarc"]["detail"] = "DMARC with p=none — recommend p=reject"
            else:
                results["dmarc"]["status"] = "warn"
                results["dmarc"]["detail"] = "DMARC found but policy unclear"
            break

    # Overall
    statuses = [results["spf"]["status"], results["dkim"]["status"], results["dmarc"]["status"]]
    if all(s == "pass" for s in statuses):
        results["overall"] = "pass"
    elif any(s == "fail" for s in statuses):
        results["overall"] = "fail"
    else:
        results["overall"] = "warn"

    return results


class EmergencyRevokeRequest(BaseModel):
    confirm: str  # Must be "REVOKE_ALL"


@router.post("/emergency-revoke")
async def emergency_revoke(body: EmergencyRevokeRequest, request: Request):
    """
    Emergency kill switch — revokes ALL platform tokens, stops the session
    engine, and rejects all pending content queue items.

    Requires body: {"confirm": "REVOKE_ALL"} to prevent accidental triggers.
    """
    if body.confirm != "REVOKE_ALL":
        raise HTTPException(
            status_code=400,
            detail="Confirmation required. Send {\"confirm\": \"REVOKE_ALL\"} to proceed."
        )

    db_pool = request.app.state.db_pool
    summary = {
        "tokens_revoked": 0,
        "queue_rejected": 0,
        "engine_stopped": False,
        "errors": [],
    }

    # 1. Revoke all platform tokens — NULL out credentials, set status='revoked'
    try:
        async with db_pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE skyeye_platform_tokens
                SET access_token = NULL,
                    refresh_token = NULL,
                    status = 'revoked',
                    error_message = 'Emergency revoke triggered',
                    updated_at = NOW()
                WHERE status != 'revoked'
            """)
            # result is e.g. "UPDATE 5"
            summary["tokens_revoked"] = int(result.split()[-1]) if result else 0
    except Exception as e:
        summary["errors"].append(f"Token revocation failed: {e}")

    # 2. Reject all pending content queue items
    try:
        async with db_pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE skyeye_content_queue
                SET status = 'rejected',
                    reviewed_at = NOW()
                WHERE status IN ('pending', 'approved', 'scheduled')
            """)
            summary["queue_rejected"] = int(result.split()[-1]) if result else 0
    except Exception as e:
        summary["errors"].append(f"Queue rejection failed: {e}")

    # 3. Stop the session engine if running
    engine = getattr(request.app.state, "skyeye_engine", None)
    if engine:
        try:
            await engine.stop()
            summary["engine_stopped"] = True
        except Exception as e:
            summary["errors"].append(f"Engine stop failed: {e}")

    # 4. Log the emergency action to skyeye_activity
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO skyeye_activity (platform, type, content, sentiment, created_at)
                VALUES ('system', 'emergency_revoke',
                        $1,
                        'critical', NOW())
            """, json.dumps(summary))
    except Exception as e:
        summary["errors"].append(f"Activity log failed: {e}")

    return {
        "status": "revoked",
        "message": "Emergency revoke completed.",
        **summary,
    }


# =============================================================================
# CAMPAIGNS
# =============================================================================

@router.get("/campaigns")
async def list_campaigns(request: Request, status: Optional[str] = None):
    """List all storytelling campaigns, optionally filtered by status."""
    db_pool = request.app.state.db_pool
    from app.services.marketing_brain import MarketingBrain
    brain = MarketingBrain(db_pool)
    campaigns = await brain.get_campaigns(status=status)
    return JSONResponse([{k: str(v) if isinstance(v, datetime) else v for k, v in c.items()} for c in campaigns])


@router.get("/campaigns/{campaign_id}")
async def get_campaign(request: Request, campaign_id: int):
    """Get detailed campaign info including episode posts and feedback."""
    db_pool = request.app.state.db_pool
    from app.services.marketing_brain import MarketingBrain
    brain = MarketingBrain(db_pool)
    detail = await brain.get_campaign_detail(campaign_id)
    if detail.get("error"):
        return JSONResponse({"error": detail["error"]}, status_code=404)

    def serialize(v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    return JSONResponse({k: serialize(v) if not isinstance(v, list) else
                          [{kk: serialize(vv) for kk, vv in p.items()} for p in v] if k == "posts" else v
                          for k, v in detail.items()})


@router.post("/campaigns/{campaign_id}/pause")
async def pause_campaign(request: Request, campaign_id: int):
    """Pause an active campaign."""
    db_pool = request.app.state.db_pool
    from app.services.marketing_brain import MarketingBrain
    brain = MarketingBrain(db_pool)
    ok = await brain.pause_campaign(campaign_id)
    return {"success": ok}


@router.post("/campaigns/{campaign_id}/resume")
async def resume_campaign(request: Request, campaign_id: int):
    """Resume a paused campaign."""
    db_pool = request.app.state.db_pool
    from app.services.marketing_brain import MarketingBrain
    brain = MarketingBrain(db_pool)
    ok = await brain.resume_campaign(campaign_id)
    return {"success": ok}


@router.post("/campaigns/{campaign_id}/extend")
async def extend_campaign(request: Request, campaign_id: int):
    """Add 2 more episodes to a running campaign."""
    db_pool = request.app.state.db_pool
    from app.services.marketing_brain import MarketingBrain
    brain = MarketingBrain(db_pool)
    result = await brain.extend_campaign(campaign_id, extra_episodes=2)
    return result
