"""
LITTLE NATE — Twilio Voice API
Handles outbound call initiation, TwiML webhooks, and call status tracking
for the Liminal Presence Live Call Coaching feature.
"""

import json
import os
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import APIRouter, Request, HTTPException, Depends, Form
from fastapi.responses import Response
from pydantic import BaseModel

from app.services.api_server import get_current_user

logger = logging.getLogger("nate.twilio_voice")

router = APIRouter(prefix="/api/calls", tags=["calls"])

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")
TWILIO_VOICE_APP_SID = os.getenv("TWILIO_VOICE_APP_SID", "")
TWILIO_CALL_WEBHOOK_URL = os.getenv("TWILIO_CALL_WEBHOOK_URL", "https://api.sovereignsanctuary.net/api/calls/twiml")
TWILIO_MEDIA_STREAM_URL = os.getenv("TWILIO_MEDIA_STREAM_URL", "wss://api.sovereignsanctuary.net/ws/media-stream")
LIMINAL_CALL_TOKEN_RATE = int(os.getenv("LIMINAL_CALL_TOKEN_RATE", "50"))


class CallInitiateRequest(BaseModel):
    to_number: str
    user_id: str
    contact_alias: Optional[str] = None


@router.post("/initiate")
async def initiate_call(body: CallInitiateRequest, request: Request, user: Dict = Depends(get_current_user)):
    """Create an outbound call via Twilio. Requires sufficient token balance."""
    pool = request.app.state.db_pool

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT profile_data FROM users WHERE user_id = $1 OR username = $1",
            body.user_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        profile = row.get("profile_data", {}) or {}
        balance = profile.get("token_balance", 0)
        min_tokens = LIMINAL_CALL_TOKEN_RATE * 5
        if balance < min_tokens:
            raise HTTPException(
                status_code=402,
                detail=f"Insufficient tokens. Need at least {min_tokens} for a 5-minute call. Balance: {balance}",
            )

    try:
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        call = client.calls.create(
            to=body.to_number,
            from_=TWILIO_PHONE_NUMBER,
            url=f"{TWILIO_CALL_WEBHOOK_URL}?user_id={body.user_id}",
            status_callback=f"{TWILIO_CALL_WEBHOOK_URL.replace('/twiml', '/status')}",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
            status_callback_method="POST",
        )

        liminal_engine = getattr(request.app.state, "liminal_coaching_engine", None)
        if liminal_engine:
            session_id = await liminal_engine.start_session(
                body.user_id, "phone_call", body.contact_alias
            )
        else:
            session_id = None

        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE liminal_sessions SET call_sid = $1, call_type = 'voice'
                WHERE id = $2
            """, call.sid, session_id)

        return {
            "status": "initiated",
            "call_sid": call.sid,
            "session_id": session_id,
            "token_rate": LIMINAL_CALL_TOKEN_RATE,
            "estimated_cost_per_minute": f"{LIMINAL_CALL_TOKEN_RATE} tokens",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to initiate call: %s", e)
        raise HTTPException(status_code=500, detail="Failed to initiate call")


@router.post("/twiml")
async def twiml_webhook(request: Request, user_id: str = ""):
    """TwiML webhook — Twilio calls this to get call instructions including Media Stream."""
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{TWILIO_MEDIA_STREAM_URL}">
            <Parameter name="user_id" value="{user_id}" />
        </Stream>
    </Connect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@router.post("/status")
async def call_status_webhook(
    request: Request,
    CallSid: str = Form(""),
    CallStatus: str = Form(""),
    CallDuration: str = Form("0"),
):
    """Call status webhook — handles call lifecycle events and token deduction."""
    logger.info("Call status: sid=%s status=%s duration=%s", CallSid, CallStatus, CallDuration)

    if CallStatus == "completed":
        pool = request.app.state.db_pool
        duration_seconds = int(CallDuration or 0)
        duration_minutes = max(1, (duration_seconds + 59) // 60)
        tokens_to_deduct = duration_minutes * LIMINAL_CALL_TOKEN_RATE

        async with pool.acquire() as conn:
            session = await conn.fetchrow(
                "SELECT id, user_id FROM liminal_sessions WHERE call_sid = $1",
                CallSid,
            )
            if session:
                await conn.execute("""
                    UPDATE liminal_sessions
                    SET ended_at = NOW(),
                        call_duration_seconds = $1,
                        tokens_consumed = $2
                    WHERE call_sid = $3
                """, duration_seconds, tokens_to_deduct, CallSid)

                await conn.execute("""
                    UPDATE users SET profile_data = jsonb_set(
                        profile_data,
                        '{token_balance}',
                        to_jsonb(GREATEST(0,
                            COALESCE((profile_data->>'token_balance')::int, 0) - $1
                        ))
                    )
                    WHERE user_id = $2 OR username = $2
                """, tokens_to_deduct, session["user_id"])

                await conn.execute("""
                    INSERT INTO skyeye_activity (action, platform, details, timestamp)
                    VALUES ('call_completed', 'twilio', $1, NOW())
                """, f"call_sid={CallSid} duration={duration_seconds}s tokens={tokens_to_deduct}")

                new_bal = await conn.fetchval(
                    "SELECT COALESCE((profile_data->>'token_balance')::int, 0) FROM users WHERE user_id = $1 OR username = $1",
                    session["user_id"],
                )

                logger.info(
                    "Call completed: sid=%s duration=%ds tokens_deducted=%d user=%s",
                    CallSid, duration_seconds, tokens_to_deduct, session["user_id"],
                )

                try:
                    from app.services.api_server import _get_auth_redis
                    r = await _get_auth_redis()
                    if r and new_bal is not None:
                        await r.publish(
                            "nate:balance_sync",
                            json.dumps({"username": session["user_id"], "token_balance": int(new_bal)}),
                        )
                except Exception:
                    pass

    return {"status": "received"}


@router.get("/history/{user_id}")
async def call_history(user_id: str, request: Request, user: Dict = Depends(get_current_user)):
    """Get call history for a user."""
    pool = request.app.state.db_pool

    async with pool.acquire() as conn:
        calls = await conn.fetch("""
            SELECT id, platform, contact_alias, started_at, ended_at,
                   call_sid, call_duration_seconds, tokens_consumed, call_type
            FROM liminal_sessions
            WHERE user_id = $1 AND call_sid IS NOT NULL
            ORDER BY started_at DESC
            LIMIT 50
        """, user_id)

    return {
        "calls": [
            {
                "id": c["id"],
                "contact": c.get("contact_alias"),
                "started": c["started_at"].isoformat() if c.get("started_at") else None,
                "ended": c["ended_at"].isoformat() if c.get("ended_at") else None,
                "duration_seconds": c.get("call_duration_seconds"),
                "tokens_used": c.get("tokens_consumed"),
                "type": c.get("call_type"),
            }
            for c in calls
        ],
    }
