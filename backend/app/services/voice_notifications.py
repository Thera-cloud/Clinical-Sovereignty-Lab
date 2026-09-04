"""
Voice Therapy SMS Notifications (Sovereign Voice v4).

Uses Twilio Messaging Service SID for A2P 10DLC compliance.
All SMS goes through the same pattern as notification_system.py.

SOVEREIGN-VOICE
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nate.voice_notifications")

_twilio_client = None
_data_dir = os.getenv("DATA_DIR", "/app/data")
_opt_out_path = Path(_data_dir) / "sms_opt_out.json"

SIGNUP_URL = "https://app.sovereignsanctuary.net"
RECHARGE_BASE_URL = "https://app.sovereignsanctuary.net/voice-recharge"


def _get_client():
    global _twilio_client
    if _twilio_client is not None:
        return _twilio_client
    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if sid and token:
        try:
            from twilio.rest import Client
            _twilio_client = Client(sid, token)
        except Exception as e:
            logger.warning("Twilio client init failed: %s", e)
    return _twilio_client


def _is_opted_out(phone: str) -> bool:
    try:
        if _opt_out_path.exists():
            data = json.loads(_opt_out_path.read_text())
            return phone in data.get("opted_out", [])
    except Exception:
        pass
    return False


def _send_sms(to: str, body: str) -> bool:
    if not to or not body:
        return False
    if _is_opted_out(to):
        logger.info("SMS skipped (opted out): %s", to[:6])
        return False
    client = _get_client()
    if not client:
        logger.warning("Twilio client not available for SMS")
        return False
    try:
        from app.services.twilio_a2p import sms_create_kwargs

        kwargs = sms_create_kwargs(to, body)
        if not kwargs:
            logger.warning("SMS skipped: no messaging service or from number")
            return False
        msg = client.messages.create(**kwargs)
        logger.info("SMS sent to %s: sid=%s", to[:6], msg.sid)
        return True
    except Exception as e:
        logger.warning("SMS send failed to %s: %s", to[:6], e)
        return False


async def send_recharge_sms(
    phone: str, name: str, balance_minutes: int, recharge_url: str = ""
) -> bool:
    url = recharge_url or RECHARGE_BASE_URL
    body = (
        f"Hi {name or 'there'}, your Little Nate Voice Therapy balance is "
        f"running low ({balance_minutes} min remaining). "
        f"Recharge here: {url}"
    )
    return _send_sms(phone, body)


async def send_zero_balance_decline_sms(
    phone: str, name: str, recharge_url: str = ""
) -> bool:
    url = recharge_url or RECHARGE_BASE_URL
    body = (
        f"Hi {name or 'there'}, your Little Nate Voice Therapy balance "
        f"has reached zero. To continue your sessions, recharge here: {url}"
    )
    return _send_sms(phone, body)


async def send_call_drop_recovery_sms(
    phone: str, name: str, remaining_minutes: int
) -> bool:
    body = (
        f"Hi {name or 'there'}, it looks like your call dropped. "
        f"Your session is paused with {remaining_minutes} min remaining. "
        f"Call back within 5 minutes to resume where you left off: "
        f"+1 (656) 231-8192"
    )
    return _send_sms(phone, body)


async def send_recharge_confirmation_sms(
    phone: str, name: str, minutes_added: int, balance_minutes: int
) -> bool:
    body = (
        f"Hi {name or 'there'}, your Little Nate Voice Therapy account "
        f"has been recharged! {minutes_added} minutes added. "
        f"Your balance is now {balance_minutes} minutes. "
        f"Call anytime: +1 (656) 231-8192"
    )
    return _send_sms(phone, body)


async def send_new_caller_signup_sms(
    phone: str, recharge_url: str = ""
) -> bool:
    """Send SMS to an unknown caller with signup + recharge info."""
    url = recharge_url or RECHARGE_BASE_URL
    body = (
        f"Thanks for calling Little Nate Voice Therapy! "
        f"To get started, purchase your first session block here: {url}\n\n"
        f"Want the full Sovereign Sanctuary experience? "
        f"Sign up at {SIGNUP_URL}\n\n"
        f"Once you've purchased minutes, call back anytime: +1 (656) 231-8192"
    )
    return _send_sms(phone, body)
