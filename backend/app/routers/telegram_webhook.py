"""
Telegram Bot Webhook — Universal Nate Summon Doorway.

Handles incoming Telegram messages and routes them through
the Nate Summon System. Users can link their Telegram ID
to their Sovereign Sanctuary account for full access.
"""

import hashlib
import logging
import os
from typing import Optional

import aiohttp
from fastapi import APIRouter, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telegram", tags=["telegram"])

_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "LittleNateBot")
_API_BASE = "https://api.telegram.org"


async def _send_message(chat_id: int, text: str):
    """Send a message via Telegram Bot API."""
    if not _BOT_TOKEN:
        return
    url = f"{_API_BASE}/bot{_BOT_TOKEN}/sendMessage"
    async with aiohttp.ClientSession() as sess:
        await sess.post(url, json={
            "chat_id": chat_id,
            "text": text[:4096],
            "parse_mode": "Markdown",
        })


async def _lookup_user_by_telegram(db_pool, telegram_id: int) -> Optional[dict]:
    """Find a registered user linked to this Telegram ID."""
    if not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT username, role, profile_data->>'tier' AS tier
                FROM users
                WHERE profile_data->>'telegram_id' = $1
            """, str(telegram_id))
            return dict(row) if row else None
    except Exception:
        return None


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """Handle incoming Telegram updates."""
    try:
        update = await request.json()
    except Exception:
        return Response(status_code=200)

    message = update.get("message")
    if not message:
        return Response(status_code=200)

    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()
    telegram_id = message["from"]["id"]
    first_name = message["from"].get("first_name", "")

    if not text:
        return Response(status_code=200)

    # Commands
    if text.startswith("/start"):
        await _send_message(chat_id, (
            f"Hey {first_name}! I'm Little Nate — your AI companion from Sovereign Sanctuary.\n\n"
            f"Send me any question and I'll do my best to help.\n\n"
            f"To link your account for full access: `/link your_username`\n"
            f"Questions? Visit app.sovereignsanctuary.net"
        ))
        return Response(status_code=200)

    if text.startswith("/link "):
        username = text[6:].strip()
        if username:
            db_pool = getattr(request.app.state, "db_pool", None)
            if db_pool:
                try:
                    async with db_pool.acquire() as conn:
                        result = await conn.execute("""
                            UPDATE users SET profile_data = jsonb_set(
                                COALESCE(profile_data, '{}'::jsonb),
                                '{telegram_id}', $1::jsonb
                            )
                            WHERE username = $2
                        """, f'"{telegram_id}"', username)
                        if result == "UPDATE 1":
                            await _send_message(chat_id, f"Linked to account `{username}`. You now have full access.")
                        else:
                            await _send_message(chat_id, f"Username `{username}` not found. Check spelling.")
                except Exception as e:
                    await _send_message(chat_id, "Linking failed. Try again later.")
                    logger.warning("Telegram link error: %s", e)
            return Response(status_code=200)

    # Route through Summon System
    db_pool = getattr(request.app.state, "db_pool", None)
    summon_service = getattr(request.app.state, "nate_summon_service", None)

    if not summon_service:
        await _send_message(chat_id, "I'm warming up — try again in a moment.")
        return Response(status_code=200)

    user = await _lookup_user_by_telegram(db_pool, telegram_id)
    device_fp = hashlib.sha256(f"telegram:{telegram_id}".encode()).hexdigest()

    try:
        result = await summon_service.process_summon(
            message=text[:2000],
            channel="telegram",
            user=user,
            device_fingerprint=device_fp,
        )
        response_text = result.response[:4096]
        if result.remaining_queries is not None and not user:
            response_text += f"\n\n_({result.remaining_queries} free queries remaining)_"
        await _send_message(chat_id, response_text)
    except Exception as e:
        logger.warning("Telegram summon error: %s", e)
        await _send_message(chat_id, "Something went wrong. I'll be back shortly.")

    return Response(status_code=200)


@router.get("/health")
async def telegram_health():
    return {
        "status": "ok",
        "bot_configured": bool(_BOT_TOKEN),
        "bot_username": _BOT_USERNAME,
    }
