"""
Voice Therapy Billing API (Sovereign Voice v4).

Handles inbound Twilio calls, balance checks, recharge flows,
Stripe webhook for voice block purchases, and lead capture for
unknown callers.

SOVEREIGN-VOICE
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import Response

from app.services.voice_twilio_security import (
    public_webhook_url_for_signature,
    twilio_signature_valid,
)

logger = logging.getLogger("nate.voice_billing_api")

router = APIRouter(prefix="/api/voice", tags=["voice-billing"])

TWILIO_MEDIA_STREAM_URL = os.getenv(
    "TWILIO_MEDIA_STREAM_URL",
    "wss://api.sovereignsanctuary.net/ws/nate-media-stream",
)
STRIPE_VOICE_WEBHOOK_SECRET = os.getenv("STRIPE_VOICE_WEBHOOK_SECRET", "")
RECHARGE_BASE_URL = os.getenv(
    "VOICE_RECHARGE_URL",
    "https://app.sovereignsanctuary.net/voice-recharge",
)


def _twilio_form_dict(form: Any) -> Dict[str, str]:
    """Build str→str map for RequestValidator (Twilio voice webhooks are form-only)."""
    out: Dict[str, str] = {}
    for key, value in form.multi_items():
        if isinstance(value, str):
            out[key] = value
        else:
            out[key] = str(value)
    return out


def _twilio_signature_url(request: Request, *, route: str) -> str:
    """
    route: "inbound" | "call_status" — must match the URL configured on the Twilio webhook.
    """
    if route == "inbound":
        explicit = (
            os.getenv("TWILIO_VOICE_INBOUND_WEBHOOK_URL", "").strip()
            or os.getenv("TWILIO_VOICE_WEBHOOK_URL", "").strip()
        )
    else:
        # Do not fall back to TWILIO_VOICE_WEBHOOK_URL — it is often inbound-only and would break validation.
        explicit = os.getenv("TWILIO_VOICE_CALL_STATUS_WEBHOOK_URL", "").strip()
    return public_webhook_url_for_signature(
        request,
        explicit if explicit else None,
    )


def _twiml_connect(params: Dict[str, str]) -> str:
    """Build TwiML <Response><Connect><Stream> with custom parameters."""
    param_xml = "\n".join(
        f'            <Parameter name="{k}" value="{v}" />'
        for k, v in params.items()
        if v
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        '    <Say voice="Polly.Matthew">Hello, I\'m connecting you to Little Nate now. You can start sharing and he will catch up and respond.</Say>\n'  # SOVEREIGN-VOICE
        "    <Connect>\n"
        f'        <Stream url="{TWILIO_MEDIA_STREAM_URL}">\n'
        f"{param_xml}\n"
        "        </Stream>\n"
        "    </Connect>\n"
        "</Response>"
    )


def _twiml_say(message: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f'    <Say voice="Polly.Matthew">{message}</Say>\n'
        "</Response>"
    )


# ── Inbound Call Webhook ──


@router.post("/inbound")
async def inbound_call(request: Request):
    """
    Twilio inbound call webhook. Called when someone dials +1 (656) 231-8192.

    Flow:
    1. Normalize phone number
    2. Check for PAUSED session (resume if within 5 min)
    3. Look up voice_accounts by phone
    4. If found with balance > 0 → connect to Little Nate
    5. If found with balance = 0 → decline + send recharge SMS
    6. If not found → check users table for ADMIN bypass
    7. If not found anywhere → capture lead, send signup SMS
    """
    from app.services.voice_phone import phone_digits_only

    form = await request.form()
    form_str = _twilio_form_dict(form)
    sig_url = _twilio_signature_url(request, route="inbound")
    if not twilio_signature_valid(
        request,
        form_str,
        auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
        request_url=sig_url,
    ):
        logger.warning(
            "Rejected webhook with invalid/missing Twilio signature: path=%s",
            request.url.path,
        )
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    From = form_str.get("From", "")

    billing: Optional[object] = getattr(request.app.state, "voice_billing", None)
    if not billing:
        logger.error("VoiceBillingSystem not initialized")
        return Response(
            content=_twiml_say(
                "We're experiencing a temporary issue. Please try again in a few minutes."
            ),
            media_type="application/xml",
        )

    phone = phone_digits_only(From)
    if not phone:
        return Response(
            content=_twiml_say("We couldn't identify your phone number. Please try again."),
            media_type="application/xml",
        )

    logger.info("Inbound call from %s (normalized: %s)", From[:8], phone[:6])

    # SOVEREIGN-VOICE — coach check-in callback FIRST (ANI match → memory + hybrid)
    try:
        pool = getattr(request.app.state, "db_pool", None)
        if pool:
            from app.services.coach_nate_checkin_service import CoachNateCheckinService
            _ck_task = await CoachNateCheckinService(pool).resolve_inbound_by_phone(From)
            if _ck_task:
                return Response(
                    content=_twiml_connect({
                        "username": str(_ck_task.get("client_username") or ""),
                        "coach_checkin_task_id": str(_ck_task["id"]),
                        "call_id": str(_ck_task.get("call_id") or ""),
                        "from_number": From,
                        "phone": str(_ck_task.get("client_phone_e164") or From),
                        "to_number": str(_ck_task.get("client_phone_e164") or From),
                        "is_callback": "true",
                        "number_match": "true",
                        "hybrid_resume": "true",
                    }),
                    media_type="application/xml",
                )
    except Exception as _ck_err:
        logger.warning("coach checkin callback resolve: %s", _ck_err)

    # SOVEREIGN-VOICE — hybrid PAUSED redial if no open check-in (Redis, 5min)
    try:
        from app.services.api_server import _get_auth_redis
        from app.services.voice_hybrid_resume import peek_hybrid_pause

        _hr = await _get_auth_redis()
        _hp = await peek_hybrid_pause(_hr, phone) if _hr else None
        if _hp and _hp.get("username"):
            logger.info("Hybrid PAUSED resume for %s → %s", phone[:6], _hp["username"])
            return Response(
                content=_twiml_connect({
                    "username": str(_hp["username"]),
                    "admin_bypass": "true",
                    "hybrid_resume": "true",
                    "number_match": "true",
                    "from_number": From,
                    "phone": From,
                    "to_number": From,
                    "resume_call_sid": str(_hp.get("call_sid") or ""),
                }),
                media_type="application/xml",
            )
    except Exception as _hp_err:
        logger.warning("hybrid pause peek: %s", _hp_err)

    # 1. Check for PAUSED session within recovery window
    paused = await billing.get_paused_session_for_phone(phone)
    if paused:
        remaining = await billing.resume_session(paused["session_id"])
        if remaining and remaining > 0:
            logger.info("Resuming PAUSED session %s for %s", paused["session_id"], phone[:6])
            return Response(
                content=_twiml_connect({
                    "voice_billing_user_id": paused["user_id"],
                    "resume_session_id": paused["session_id"],
                }),
                media_type="application/xml",
            )

    # 2. Look up voice_accounts by phone
    account = await billing.get_account_by_phone(phone)

    if account:
        user_id = account["user_id"]
        balance = account["balance_seconds"]

        if balance > 0:
            # Create new session
            call_sid = ""  # Will be set by TwilioMediaSession from start event
            session_id = await billing.start_session(user_id, call_sid)
            logger.info(
                "Connecting caller %s (user=%s, balance=%ds, session=%s)",
                phone[:6], user_id[:8], balance, session_id,
            )
            return Response(
                content=_twiml_connect({
                    "voice_billing_user_id": user_id,
                    "voice_billing_session_id": session_id or "",
                }),
                media_type="application/xml",
            )
        else:
            # Zero balance — decline and send SMS
            name = await billing.resolve_user_name_for_phone(phone)
            asyncio.create_task(_send_zero_balance_sms(phone, name))
            return Response(
                content=_twiml_say(
                    "Hi there. Your Little Nate Voice Therapy balance has reached zero. "
                    "We just sent you a text message with a link to recharge your minutes. "
                    "We look forward to speaking with you again soon. Goodbye."
                ),
                media_type="application/xml",
            )

    # 3. No voice_accounts row — check users table for ADMIN
    is_admin = await billing.is_admin_caller(phone)
    if is_admin:
        logger.info("Admin caller detected: %s", phone[:6])
        return Response(
            content=_twiml_connect({
                "admin_bypass": "true",
                "voice_billing_user_id": "DrNevedal1",
            }),
            media_type="application/xml",
        )

    # 4. Check if this is an existing platform user (has users row but no voice_accounts)
    platform_user_id = await billing.resolve_user_id_for_phone(phone)
    if platform_user_id:
        name = await billing.resolve_user_name_for_phone(phone)
        asyncio.create_task(_send_existing_user_recharge_sms(phone, name))
        return Response(
            content=_twiml_say(
                f"Hi{' ' + name if name else ' there'}. Welcome to Little Nate Voice Therapy. "
                "To get started with voice sessions, you'll need to purchase a session block. "
                "We just sent you a text message with a link to get your first block of minutes. "
                "Once your account is set up, just call this number again. Goodbye."
            ),
            media_type="application/xml",
        )

    # 5. Completely unknown caller — optional guest live intro (safe space)
    # SOVEREIGN-VOICE — ENABLE_VOICE_GUEST_INTRO connects stream instead of hangup
    _guest_intro = os.getenv("ENABLE_VOICE_GUEST_INTRO", "false").lower() in ("1", "true", "yes")
    is_new = await billing.record_lead(phone)
    if is_new:
        asyncio.create_task(_send_new_caller_sms(phone))
    if _guest_intro:
        logger.info("Guest intro stream for unknown phone %s", phone[:6])
        return Response(
            content=_twiml_connect({
                "guest_mode": "true",
                "voice_billing_user_id": f"guest_{phone[-4:] if len(phone) >= 4 else phone}",
                "max_call_seconds": "180",
                "admin_bypass": "true",
            }),
            media_type="application/xml",
        )

    return Response(
        content=_twiml_say(
            "Hi there. Welcome to Little Nate Voice Therapy by Sovereign Sanctuary. "
            "We just sent you a text message with everything you need to get started. "
            "Purchase your first session block and call us back anytime. "
            "We look forward to working with you. Goodbye."
        ),
        media_type="application/xml",
    )


@router.post("/call-status")
async def voice_call_status(request: Request):
    """Twilio call status callback — acknowledge and log."""
    form = await request.form()
    form_str = _twilio_form_dict(form)
    sig_url = _twilio_signature_url(request, route="call_status")
    if not twilio_signature_valid(
        request,
        form_str,
        auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
        request_url=sig_url,
    ):
        logger.warning(
            "Rejected webhook with invalid/missing Twilio signature: path=%s",
            request.url.path,
        )
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    CallSid = form_str.get("CallSid", "")
    CallStatus = form_str.get("CallStatus", "")
    CallDuration = form_str.get("CallDuration", "0")
    logger.info("call-status: sid=%s status=%s duration=%ss", CallSid[:12] if CallSid else "?", CallStatus, CallDuration)
    return {"status": "received"}


async def _send_zero_balance_sms(phone: str, name: str):
    try:
        from app.services.voice_notifications import send_zero_balance_decline_sms
        await send_zero_balance_decline_sms(phone, name)
    except Exception as e:
        logger.warning("Failed to send zero-balance SMS: %s", e)


async def _send_existing_user_recharge_sms(phone: str, name: str):
    try:
        from app.services.voice_notifications import send_recharge_sms
        await send_recharge_sms(phone, name, 0, RECHARGE_BASE_URL)
    except Exception as e:
        logger.warning("Failed to send existing-user recharge SMS: %s", e)


async def _send_new_caller_sms(phone: str):
    try:
        from app.services.voice_notifications import send_new_caller_signup_sms
        from app.services.voice_billing import VoiceBillingSystem
        await send_new_caller_signup_sms(phone, RECHARGE_BASE_URL)
    except Exception as e:
        logger.warning("Failed to send new-caller signup SMS: %s", e)


# ── Balance & Recharge ──


@router.get("/balance/{phone}")
async def get_balance(phone: str, request: Request):
    """Check balance for a phone number (admin use)."""
    from app.services.api_server import require_admin
    from app.services.voice_phone import phone_digits_only
    await require_admin(request)

    billing = getattr(request.app.state, "voice_billing", None)
    if not billing:
        raise HTTPException(500, "Voice billing not initialized")

    normalized = phone_digits_only(phone)
    account = await billing.get_account_by_phone(normalized)
    if not account:
        raise HTTPException(404, "No voice account for this phone")

    return {
        "user_id": account["user_id"],
        "phone": account["phone"],
        "balance_seconds": account["balance_seconds"],
        "balance_minutes": account["balance_seconds"] // 60,
    }


def _auth():  # SOVEREIGN-VOICE
    from app.services.api_server import get_current_user
    return get_current_user


@router.post("/recharge")
async def create_recharge(request: Request, _u: dict = Depends(_auth())):
    """Create a Stripe Checkout session for voice block purchase."""
    billing = getattr(request.app.state, "voice_billing", None)
    if not billing:
        raise HTTPException(500, "Voice billing not initialized")

    body = await request.json()
    user_id = body.get("user_id", "")
    phone = body.get("phone", "")
    pack = body.get("pack", "1block")

    if not user_id and not phone:
        raise HTTPException(400, "user_id or phone required")

    if not user_id and phone:
        from app.services.voice_phone import phone_digits_only
        normalized = phone_digits_only(phone)
        account = await billing.get_account_by_phone(normalized)
        if account:
            user_id = account["user_id"]
            phone = account["phone"]
        else:
            user_id = normalized
            phone = normalized

    url = await billing.create_recharge_checkout(
        user_id, phone, pack,
        success_url=body.get("success_url", ""),
        cancel_url=body.get("cancel_url", ""),
    )
    if not url:
        raise HTTPException(500, "Failed to create checkout session")

    return {"checkout_url": url}


@router.get("/me/balance")
async def get_my_voice_balance(request: Request, _u: dict = Depends(_auth())):
    """Return prepaid voice balance for the authenticated user (by hardware_id / username)."""
    billing = getattr(request.app.state, "voice_billing", None)
    if not billing:
        raise HTTPException(500, "Voice billing not initialized")
    uid = (_u.get("hardware_id") or _u.get("username") or "").strip()
    if not uid:
        raise HTTPException(400, "Missing user identity")
    acc = await billing.get_account_by_user_id(uid)
    if not acc:
        return {"has_account": False, "balance_minutes": 0, "balance_seconds": 0}
    sec = int(acc.get("balance_seconds") or 0)
    return {
        "has_account": True,
        "balance_minutes": sec // 60,
        "balance_seconds": sec,
        "phone": acc.get("phone") or "",
    }


@router.get("/sessions/{user_id}")
async def get_sessions(user_id: str, request: Request, _u: dict = Depends(_auth())):
    """Get voice session history for a user."""
    pool = getattr(request.app.state, "db_pool", None)
    if not pool:
        raise HTTPException(500, "Database not available")

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id::text, status, started_at, ended_at, seconds_used, end_reason "
                "FROM voice_sessions WHERE user_id = $1 "
                "ORDER BY started_at DESC LIMIT 50",
                user_id,
            )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("get_sessions: %s", e)
        raise HTTPException(500, "Failed to fetch sessions")


@router.get("/monthly-summary")
async def monthly_summary(request: Request, _u: dict = Depends(_auth()), user_id: str = "", phone: str = ""):
    """Monthly usage summary (data endpoint for future email invoice)."""
    pool = getattr(request.app.state, "db_pool", None)
    billing = getattr(request.app.state, "voice_billing", None)
    if not pool or not billing:
        raise HTTPException(500, "Service not available")

    if not user_id and phone:
        from app.services.voice_phone import phone_digits_only
        account = await billing.get_account_by_phone(phone_digits_only(phone))
        if account:
            user_id = account["user_id"]

    if not user_id:
        raise HTTPException(400, "user_id or phone required")

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT type, SUM(ABS(seconds)) AS total_seconds, "
                "SUM(amount_cents) AS total_cents, COUNT(*) AS tx_count "
                "FROM voice_transactions WHERE user_id = $1 "
                "AND created_at >= date_trunc('month', NOW()) "
                "GROUP BY type",
                user_id,
            )
        return {
            "user_id": user_id,
            "period": "current_month",
            "summary": [dict(r) for r in rows],
        }
    except Exception as e:
        logger.warning("monthly_summary: %s", e)
        raise HTTPException(500, "Failed to generate summary")


# ── Stripe Webhook ──


@router.post("/webhook/stripe")
async def stripe_voice_webhook(request: Request):
    """
    Stripe webhook for voice billing events.
    Handles checkout.session.completed where metadata.type == 'voice_block'.
    Auto-creates voice_accounts on first purchase.
    """
    import stripe

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    if not STRIPE_VOICE_WEBHOOK_SECRET:
        logger.error("STRIPE_VOICE_WEBHOOK_SECRET not configured")
        raise HTTPException(500, "Webhook not configured")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig, STRIPE_VOICE_WEBHOOK_SECRET,
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(400, "Invalid signature")
    except Exception as e:
        logger.warning("Stripe webhook parse error: %s", e)
        raise HTTPException(400, "Invalid payload")

    if event["type"] != "checkout.session.completed":
        return {"status": "ignored"}

    session = event["data"]["object"]
    metadata = session.get("metadata", {})

    if metadata.get("type") != "voice_block":
        return {"status": "not_voice"}

    billing = getattr(request.app.state, "voice_billing", None)
    pool = getattr(request.app.state, "db_pool", None)
    if not billing or not pool:
        logger.error("VoiceBillingSystem or db_pool not available in webhook")
        raise HTTPException(500, "Internal error")

    phone = metadata.get("phone", "")
    seconds = int(metadata.get("seconds", "1200"))
    customer_id = session.get("customer", "")
    payment_id = session.get("payment_intent", "")
    amount_cents = session.get("amount_total", 0)

    # Resolve user_id: metadata > users table > phone as temp ID
    user_id = metadata.get("user_id", "")
    if not user_id and phone:
        user_id = await billing.resolve_user_id_for_phone(phone)
    if not user_id:
        user_id = phone  # temporary ID for unregistered callers

    if not user_id:
        logger.warning("Stripe voice webhook: no user_id or phone in metadata")
        return {"status": "error", "detail": "no_user_id"}

    if payment_id:
        try:
            async with pool.acquire() as conn:
                already = await conn.fetchval(
                    "SELECT 1 FROM voice_transactions WHERE stripe_payment_id = $1 LIMIT 1",
                    payment_id)
                if already:
                    logger.info("Voice block already credited for payment %s — skipping", payment_id)
                    return {"status": "already_credited"}
        except Exception as e:
            logger.warning("Idempotency check failed (proceeding): %s", e)

    new_balance = await billing.credit_seconds(
        user_id=user_id,
        phone=phone,
        seconds=seconds,
        stripe_customer_id=customer_id,
        stripe_payment_id=payment_id,
        amount_cents=amount_cents,
    )

    logger.info(
        "Voice block credited: user=%s, seconds=%d, balance=%d, payment=%s",
        user_id[:8], seconds, new_balance, payment_id,
    )

    # Mark lead as converted if applicable
    if phone:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE voice_leads SET converted = TRUE WHERE phone = $1",
                    phone,
                )
        except Exception:
            pass

    # Send confirmation SMS
    name = await billing.resolve_user_name_for_phone(phone) if phone else ""
    asyncio.create_task(
        _send_confirmation_sms(phone, name, seconds // 60, new_balance // 60)
    )

    return {"status": "ok", "balance_seconds": new_balance}


async def _send_confirmation_sms(
    phone: str, name: str, minutes_added: int, balance_minutes: int
):
    if not phone:
        return
    try:
        from app.services.voice_notifications import send_recharge_confirmation_sms
        await send_recharge_confirmation_sms(phone, name, minutes_added, balance_minutes)
    except Exception as e:
        logger.warning("Failed to send recharge confirmation SMS: %s", e)


@router.get("/health")
async def voice_billing_health(request: Request):
    billing = getattr(request.app.state, "voice_billing", None)
    return {
        "status": "ok" if billing else "not_initialized",
        "service": "voice_billing",
    }
