"""
Callback Queue Processor — background agent that dequeues and initiates
Twilio callbacks for callers who hit capacity during inbound calls.

Cycle: every 120 seconds.
Respects voice capacity slots — won't call if at XTTS concurrency limit.
Max 3 attempts per callback entry; marks 'failed' after exhaustion.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger("nate.callback_processor")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")
TWILIO_CHECKIN_TWIML_URL = os.getenv(
    "TWILIO_CHECKIN_TWIML_URL",
    "https://api.sovereignsanctuary.net/api/calls/nate-checkin-twiml",
)

_CYCLE_SECONDS = 120


class CallbackProcessor:
    def __init__(self, db_pool, app_state=None):
        self._pool = db_pool
        self._app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("CallbackProcessor started (cycle=%ds)", _CYCLE_SECONDS)

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CallbackProcessor stopped")

    async def _run_loop(self) -> None:
        await asyncio.sleep(30)
        while self._running:
            try:
                await self._process_one()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("CallbackProcessor cycle error: %s", e)
            await asyncio.sleep(_CYCLE_SECONDS)

    async def _process_one(self) -> None:
        if not self._pool:
            return
        if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
            return

        try:
            from app.services.voice_capacity import get_active_voice_count
            from app.services.voice_capacity import XTTS_CONCURRENCY_LIMIT

            active = await get_active_voice_count()
            if active >= XTTS_CONCURRENCY_LIMIT:
                return
        except Exception:
            pass

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT cq.id, cq.user_uuid, cq.priority, cq.reason,
                       cq.attempt_count, cq.max_attempts, cq.tone_template,
                       u.username,
                       u.profile_data->>'phone' AS phone,
                       u.profile_data->>'name' AS name,
                       u.profile_data->>'email' AS email
                FROM callback_queue cq
                JOIN users u ON u.id = cq.user_uuid
                WHERE cq.status = 'pending'
                  AND cq.scheduled_for <= NOW()
                ORDER BY cq.priority ASC, cq.scheduled_for ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
            )
            if not row:
                return

            cb_id = row["id"]
            phone = (row["phone"] or "").strip()
            username = row["username"] or ""
            name = row["name"] or username
            attempt = (row["attempt_count"] or 0) + 1
            max_att = row["max_attempts"] or 3

            if not phone:
                await conn.execute(
                    "UPDATE callback_queue SET status = 'failed', reason = reason || ' [no phone]', updated_at = NOW() WHERE id = $1",
                    cb_id,
                )
                logger.warning("Callback %d: user %s has no phone — marked failed", cb_id, username)
                return

            await conn.execute(
                "UPDATE callback_queue SET status = 'calling', attempt_count = $2, updated_at = NOW() WHERE id = $1",
                cb_id,
                attempt,
            )

        success = await self._initiate_call(phone, username, name, cb_id)

        async with self._pool.acquire() as conn:
            if success:
                await conn.execute(
                    "UPDATE callback_queue SET status = 'completed', updated_at = NOW() WHERE id = $1",
                    cb_id,
                )
                logger.info("Callback %d: call initiated to %s (%s)", cb_id, username, phone[-4:])
            elif attempt >= max_att:
                await conn.execute(
                    "UPDATE callback_queue SET status = 'failed', updated_at = NOW() WHERE id = $1",
                    cb_id,
                )
                logger.warning("Callback %d: max attempts (%d) reached for %s", cb_id, max_att, username)
            else:
                next_delay = min(attempt * 5, 30)
                await conn.execute(
                    """UPDATE callback_queue
                       SET status = 'pending',
                           scheduled_for = NOW() + ($2 || ' minutes')::interval,
                           updated_at = NOW()
                       WHERE id = $1""",
                    cb_id,
                    str(next_delay),
                )
                logger.info("Callback %d: attempt %d failed, retry in %d min", cb_id, attempt, next_delay)

    async def _initiate_call(self, phone: str, username: str, name: str, cb_id: int) -> bool:
        """Place a Twilio call using the check-in TwiML flow."""
        try:
            import json
            import uuid

            from app.services.nate_outbound_call import prepare_checkin_context, presynthesise_opening

            call_id = str(uuid.uuid4())

            ctx = await prepare_checkin_context(
                username=username,
                phone=phone,
                db_pool=self._pool,
                reason="callback_queue",
            )
            ctx.name = name

            opening_audio = await presynthesise_opening(ctx)

            call_context_data = {
                "call_id": call_id,
                "username": ctx.username,
                "name": ctx.name,
                "phone": ctx.phone,
                "reason": "callback_queue",
                "system_prompt": ctx.system_prompt,
                "opening_line": ctx.opening_line,
                "callback_queue_id": cb_id,
            }
            if opening_audio:
                import base64
                call_context_data["presynthesized_opening_mulaw"] = base64.b64encode(opening_audio).decode()

            try:
                from app.services.api_server import _get_auth_redis
                redis = await _get_auth_redis()
                if redis:
                    await redis.setex(
                        f"nate:call_context:{call_id}",
                        600,
                        json.dumps(call_context_data),
                    )
            except Exception:
                pass

            from twilio.rest import Client
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            twiml_url = f"{TWILIO_CHECKIN_TWIML_URL}?call_id={call_id}"

            call = client.calls.create(
                to=phone,
                from_=TWILIO_PHONE_NUMBER,
                url=twiml_url,
                status_callback_event=["completed", "no-answer", "busy", "failed"],
                status_callback_method="POST",
                machine_detection="Enable",
                machine_detection_timeout=5,
            )

            logger.info("Callback call placed: sid=%s to=%s cb_id=%d", call.sid, phone[-4:], cb_id)
            return True

        except Exception as e:
            logger.warning("Callback call failed for %s: %s", username, e)
            return False
