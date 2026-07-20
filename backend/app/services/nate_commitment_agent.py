"""
QUANTUM-CRYSTAL-ARCH: Proactive commitment touch agent (Agentic Phase 1).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.commitment_agent")

POLL_INTERVAL_SECONDS = 1800
STAGGER_DELAY = 320
LOOKAHEAD_HOURS = 48
DEDUP_HOURS = 24


def commitments_agent_enabled() -> bool:
    return os.getenv("ENABLE_PROACTIVE_COMMITMENTS", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _profile_data(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


class NateCommitmentAgent:
    def __init__(self, db_pool, notification_system=None, app_state=None):
        self.db_pool = db_pool
        self.notification_system = notification_system
        self.app_state = app_state
        self._running = False
        self._task = None

    async def start(self):
        if not commitments_agent_enabled():
            logger.info("NateCommitmentAgent disabled (ENABLE_PROACTIVE_COMMITMENTS=false)")
            return
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("NateCommitmentAgent started (30min cycle, stagger %ss)", STAGGER_DELAY)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_DELAY)
        while self._running:
            try:
                await self._cycle()
            except Exception as e:
                logger.warning("NateCommitmentAgent cycle error: %s", e)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _cycle(self):
        if not self.db_pool:
            return
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(hours=LOOKAHEAD_HOURS)
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.*, u.profile_data, u.username, u.hardware_id AS resolved_hw_id
                FROM nate_commitments c
                JOIN users u ON (u.hardware_id = c.user_id OR u.username = c.user_id)
                WHERE c.status = 'active'
                  AND c.target_date IS NOT NULL
                  AND c.target_date BETWEEN $1 AND $2
                """,
                now,
                window_end,
            )
            for row in rows:
                await self._process_due_commitment(conn, row)

    async def _recent_touch(self, conn, commitment_id: str) -> bool:
        row = await conn.fetchrow(
            """
            SELECT 1 FROM nate_proactive_touches
            WHERE commitment_id = $1::uuid
              AND created_at > NOW() - ($2::int * INTERVAL '1 hour')
            LIMIT 1
            """,
            str(commitment_id),
            DEDUP_HOURS,
        )
        return row is not None

    async def _process_due_commitment(self, conn, row):
        from app.services.proactive_touch_policy import (
            can_send_proactive_touch,
            record_skipped_touch,
        )

        hw_id = row.get("resolved_hw_id") or row["user_id"]
        commitment_id = str(row["id"])
        if await self._recent_touch(conn, commitment_id):
            return

        profile = _profile_data(row["profile_data"])
        preferred = profile.get("preferred_contact", "email")
        sensitivity = row.get("sensitivity") or "routine"

        decision = await can_send_proactive_touch(
            self.db_pool,
            hw_id,
            source="commitment",
            channel_pref=preferred,
            sensitivity=sensitivity,
            crystal_id=str(row["crystal_id"]) if row.get("crystal_id") else None,
        )
        if not decision.allowed:
            await record_skipped_touch(
                self.db_pool,
                hw_id,
                source_agent="commitment",
                reason=decision.reason or "skipped_gate_error",
                content=row["commitment_text"][:500],
            )
            return

        msg = await self._generate_message(row)
        channel = decision.channel_override or preferred
        sent_channel = await self._deliver(hw_id, profile, msg, channel)

        await conn.execute(
            """
            INSERT INTO nate_proactive_touches
                (user_id, commitment_id, source_agent, touch_type, channel, content, status)
            VALUES ($1, $2::uuid, 'commitment', 'proactive', $3, $4, 'sent')
            """,
            hw_id,
            commitment_id,
            sent_channel or "in_app",
            msg[:2000],
        )
        await conn.execute(
            """
            UPDATE nate_commitments
            SET touch_count = touch_count + 1, last_touched_at = NOW(), updated_at = NOW()
            WHERE id = $1::uuid
            """,
            commitment_id,
        )
        await self._create_nudge(conn, hw_id, msg)
        await self._ws_push(hw_id, msg, commitment_id)

    async def _generate_message(self, row) -> str:
        text = row["commitment_text"]
        name = _profile_data(row["profile_data"]).get("name") or "there"
        fallback = (
            f"Hi {name}, it's Little Nate. You mentioned: \"{text}\" — "
            "wanted to check in as that time approaches. How are you feeling about it?"
        )
        try:
            from app.services.nate_inference_router import NateInferenceRouter

            router = NateInferenceRouter()
            prompt = (
                f"Write a warm, brief proactive check-in (max 3 sentences) about this "
                f"commitment: {text}. Client name: {name}. No clinical diagnosis."
            )
            out = await router.generate(
                messages=[{"role": "user", "content": prompt}],
                domain="clinical",
                max_tokens=120,
            )
            if out and out.strip():
                return out.strip()
        except Exception as e:
            logger.warning("commitment_agent: message gen failed: %s", e)
        return fallback

    async def _deliver(self, hw_id: str, profile: Dict, msg: str, channel: str) -> Optional[str]:
        if channel == "in_app":
            return "in_app"
        email = profile.get("email")
        phone = profile.get("phone")
        if channel == "sms" and phone and self.notification_system:
            if await self.notification_system.send_sms(phone, msg):
                return "sms"
        if email and self.notification_system:
            if await self.notification_system._send_email(
                email,
                "Little Nate — holding this with you",
                msg,
                notification_type="commitment_touch",
            ):
                return "email"
        return "in_app"

    async def _create_nudge(self, conn, hw_id: str, msg: str):
        try:
            user_uuid = await conn.fetchval(
                """
                SELECT id FROM users
                WHERE hardware_id = $1 OR username = $1
                LIMIT 1
                """,
                hw_id,
            )
            if not user_uuid:
                return
            await conn.execute(
                """
                INSERT INTO nate_nudges (user_id, nudge_type, title, content, created_at)
                VALUES ($1, 'commitment_touch', 'What Nate is holding', $2, NOW())
                """,
                user_uuid,
                msg[:500],
            )
        except Exception as e:
            logger.warning("commitment_agent: nudge insert failed: %s", e)

    async def _ws_push(self, hw_id: str, msg: str, commitment_id: str):
        push = getattr(self.app_state, "commitment_ws_push", None) if self.app_state else None
        if not push:
            return
        try:
            await push(hw_id, {"type": "commitment_touch", "text": msg, "commitment_id": commitment_id})
        except Exception as e:
            logger.warning("commitment_agent: ws push failed: %s", e)
