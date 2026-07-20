"""
QUANTUM-CRYSTAL-ARCH: Therapeutic plan context + divergence (Agentic Phase 3).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.therapeutic_plan")


def therapeutic_plans_enabled() -> bool:
    return os.getenv("ENABLE_THERAPEUTIC_PLANS", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _step_theme(step_definitions: List[Dict[str, Any]], step_num: int) -> str:
    for step in step_definitions or []:
        if int(step.get("step_number") or 0) == step_num:
            return str(step.get("theme") or step.get("title") or "")
    if step_definitions and 0 < step_num <= len(step_definitions):
        s = step_definitions[step_num - 1]
        if isinstance(s, dict):
            return str(s.get("theme") or s.get("title") or "")
    return ""


async def get_active_plan_context(db_pool: Any, user_id: str) -> str:
    """Short context block for system prompt injection."""
    if not therapeutic_plans_enabled() or not db_pool or not user_id:
        return ""

    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT title, total_steps, current_step, step_definitions
                FROM nate_therapeutic_plans
                WHERE user_id IN (
                    SELECT x FROM unnest(ARRAY[
                        $1::text,
                        (SELECT username FROM users WHERE hardware_id = $1 LIMIT 1),
                        (SELECT hardware_id FROM users WHERE username = $1 LIMIT 1)
                    ]) AS t(x)
                    WHERE x IS NOT NULL AND x <> ''
                )
                AND status = 'active'
                ORDER BY started_at DESC
                LIMIT 1
                """,
                user_id,
            )
        if not row:
            return ""

        steps = row["step_definitions"]
        if isinstance(steps, str):
            steps = json.loads(steps)
        theme = _step_theme(steps if isinstance(steps, list) else [], int(row["current_step"]))
        return (
            f"PLAN CONTEXT: Step {row['current_step']} of {row['total_steps']} — "
            f"{row['title']}. This week's focus: {theme or 'see plan steps'}."
        )
    except Exception as e:
        logger.warning("therapeutic_plan: get_active_plan_context failed: %s", e)
        return ""


def detect_plan_divergence(conversation_text: str, current_step_theme: str) -> bool:
    """
    Lightweight keyword drift check. Logs caller should append to adaptation_log.
    """
    if not conversation_text or not current_step_theme:
        return False

    theme_tokens = {
        t.lower()
        for t in re.findall(r"[a-zA-Z]{4,}", current_step_theme)
        if t.lower() not in ("this", "week", "focus", "plan", "step")
    }
    if not theme_tokens:
        return False

    lower = conversation_text.lower()
    overlap = sum(1 for t in theme_tokens if t in lower)
    if overlap >= max(1, len(theme_tokens) // 3):
        return False

    off_topic_markers = (
        "completely different",
        "change the subject",
        "don't want to talk about",
        "something else entirely",
    )
    if any(m in lower for m in off_topic_markers):
        return True

    return len(conversation_text) > 120 and overlap == 0


async def append_adaptation_log(
    db_pool: Any,
    plan_id: str,
    entry: Dict[str, Any],
) -> None:
    if not db_pool or not plan_id:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE nate_therapeutic_plans
                SET adaptation_log = adaptation_log || $2::jsonb,
                    updated_at = NOW()
                WHERE id = $1::uuid
                """,
                plan_id,
                json.dumps([entry]),
            )
    except Exception as e:
        logger.warning("therapeutic_plan: adaptation_log append failed: %s", e)


async def maybe_record_plan_divergence(
    db_pool: Any,
    user_id: str,
    conversation_text: str,
) -> bool:
    """QUANTUM-CRYSTAL-ARCH: Log divergence to adaptation_log; never auto-pause."""
    if not therapeutic_plans_enabled() or not db_pool or not user_id or not conversation_text:
        return False
    try:
        from datetime import datetime, timezone

        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, current_step, step_definitions
                FROM nate_therapeutic_plans
                WHERE user_id IN (
                    SELECT x FROM unnest(ARRAY[
                        $1::text,
                        (SELECT username FROM users WHERE hardware_id = $1 LIMIT 1),
                        (SELECT hardware_id FROM users WHERE username = $1 LIMIT 1)
                    ]) AS t(x)
                    WHERE x IS NOT NULL AND x <> ''
                )
                AND status = 'active'
                ORDER BY started_at DESC
                LIMIT 1
                """,
                user_id,
            )
        if not row:
            return False
        steps = row["step_definitions"]
        if isinstance(steps, str):
            steps = json.loads(steps)
        theme = _step_theme(steps if isinstance(steps, list) else [], int(row["current_step"]))
        if not detect_plan_divergence(conversation_text, theme):
            return False
        await append_adaptation_log(
            db_pool,
            str(row["id"]),
            {
                "event": "divergence",
                "at": datetime.now(timezone.utc).isoformat(),
                "step": int(row["current_step"]),
                "theme": theme[:200],
                "note": "keyword drift — coach/client acknowledgment required to pause",
            },
        )
        return True
    except Exception as e:
        logger.warning("therapeutic_plan: maybe_record_plan_divergence failed: %s", e)
        return False


def schedule_plan_divergence_check(
    db_pool: Any,
    *,
    user_id: str,
    conversation_text: str,
) -> None:
    """Fire-and-forget post-turn divergence check (bridge chat path)."""
    if not therapeutic_plans_enabled() or not db_pool or not user_id:
        return
    try:
        import asyncio

        asyncio.create_task(
            maybe_record_plan_divergence(db_pool, user_id, conversation_text or "")
        )
    except Exception:
        pass
