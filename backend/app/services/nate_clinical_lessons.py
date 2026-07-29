"""QUANTUM-CRYSTAL-ARCH — Clinical lesson candidates; crystallize at match_count>=2."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, Optional

from app.services.nate_clinical_flags import lessons_enabled

logger = logging.getLogger("nate.clinical_lessons")


def _trigger_pattern(loser_text: str, winner_text: str) -> str:
    blob = f"{loser_text} {winner_text}".lower()
    if re.search(r"suicid|crisis|safe", blob):
        return "masked_crisis_handling"
    if re.search(r"stuck|every time|circles", blob):
        return "rut_cycle"
    if re.search(r"resist|pointless|whatever", blob):
        return "resistance_roll"
    return "general_clinical_contrast"


async def record_lesson_from_match(
    db_pool,
    *,
    match_id,
    winner: str,
    y_win: str,
    y_lose: str,
) -> Optional[int]:
    if not lessons_enabled() or db_pool is None:
        return None
    if winner not in ("a", "b") or not y_win:
        return None
    pattern = _trigger_pattern(y_lose or "", y_win)
    lesson = (
        f"When trigger={pattern}, prefer responses like: {y_win[:500]} "
        f"over: {(y_lose or '')[:300]}"
    )
    try:
        async with db_pool.acquire() as conn:
            existing = await conn.fetchrow(
                """
                SELECT id, match_count FROM nate_clinical_lessons
                WHERE trigger_pattern = $1 AND crystal_id IS NULL
                ORDER BY id DESC LIMIT 1
                """,
                pattern,
            )
            if existing:
                new_count = int(existing["match_count"] or 1) + 1
                await conn.execute(
                    """
                    UPDATE nate_clinical_lessons
                    SET match_count = $1, lesson_text = $2, source_match_id = $3
                    WHERE id = $4
                    """,
                    new_count,
                    lesson,
                    match_id,
                    existing["id"],
                )
                lesson_id = existing["id"]
                if new_count >= 2:
                    await _maybe_crystallize(conn, lesson_id, lesson, pattern)
                return lesson_id
            row = await conn.fetchrow(
                """
                INSERT INTO nate_clinical_lessons
                    (lesson_text, trigger_pattern, source_match_id, match_count)
                VALUES ($1, $2, $3, 1)
                RETURNING id
                """,
                lesson,
                pattern,
                match_id,
            )
            return row["id"] if row else None
    except Exception as e:
        logger.warning("lesson record failed: %s", e)
        return None


async def _maybe_crystallize(conn, lesson_id: int, lesson_text: str, pattern: str) -> None:
    try:
        # Minimal crystal insert; validator path optional if table schema varies
        content_hash = hashlib.sha256(lesson_text.encode()).hexdigest()
        crystal_id = await conn.fetchval(
            """
            INSERT INTO nate_intelligence_crystals
                (crystal_text, domain, confidence, content_hash, scope, source_count)
            VALUES ($1, 'clinical', 0.55, $2, 'global', 2)
            RETURNING id::text
            """,
            f"[clinical_lesson:{pattern}] {lesson_text[:1800]}",
            content_hash,
        )
        if crystal_id:
            await conn.execute(
                "UPDATE nate_clinical_lessons SET crystal_id = $1 WHERE id = $2",
                str(crystal_id),
                lesson_id,
            )
    except Exception as e:
        logger.debug("crystallize lesson skipped: %s", e)
