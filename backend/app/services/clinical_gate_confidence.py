"""
L3b — gate confidence from Soft clinical-runtime-gate feedback.

Hard SI / violence coach alerts NEVER consult this module.
Soft runtime-gate classes (pharma/sleep/diagnosis/instrument/credential) may
suppress *follow-up* re-triggers when rolling confidence is low.

# QUANTUM-CRYSTAL-ARCH — L3 feedback-responsive path
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger("clinical_gate_confidence")

_FP_PATTERNS = re.compile(
    r"\b(?:"
    r"not\s+asking\s+for\s+(?:a\s+)?(?:diagnosis|prescription|meds?)|"
    r"i\s+was(?:\s+just)?\s+(?:curious|kidding|joking)|"
    r"you\s+can(?:'t|not)\s+prescribe|"
    r"i\s+know\s+you\s+(?:can(?:'t|not)|won'?t)\s+(?:diagnose|prescribe)|"
    r"not\s+(?:looking\s+for|seeking)\s+(?:medical|clinical)\s+advice"
    r")\b",
    re.I,
)

_SOFT_SUPPRESS_FLOOR = float(os.getenv("GATE_CONFIDENCE_SOFT_FLOOR", "0.30"))


def feedback_enabled() -> bool:
    return os.getenv("ENABLE_GATE_CONFIDENCE_FEEDBACK", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def looks_like_false_positive(user_msg: str) -> bool:
    return bool(user_msg and _FP_PATTERNS.search(user_msg))


async def get_confidence(db_pool: Any, gate_key: str, default: float = 0.70) -> float:
    if not db_pool or not gate_key:
        return default
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT confidence FROM clinical_gate_confidence WHERE gate_key = $1",
                gate_key,
            )
        return float(row) if row is not None else default
    except Exception as e:
        logger.debug("get_confidence skipped: %s", e)
        return default


async def allow_soft_followup(db_pool: Any, gate_class: str) -> bool:
    """False → suppress soft (non-new) runtime-gate re-triggers for this class."""
    if not feedback_enabled():
        return True
    conf = await get_confidence(db_pool, f"runtime_gate:{gate_class}")
    return conf >= _SOFT_SUPPRESS_FLOOR


async def record_fire(db_pool: Any, gate_class: str) -> None:
    if not feedback_enabled() or not db_pool or not gate_class:
        return
    key = f"runtime_gate:{gate_class}"
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO clinical_gate_confidence
                    (gate_key, confidence, sample_size, positive_count, negative_count, reasoning)
                VALUES ($1, 0.70, 1, 0, 0, 'fire')
                ON CONFLICT (gate_key) DO UPDATE SET
                    sample_size = clinical_gate_confidence.sample_size + 1,
                    updated_at = NOW(),
                    reasoning = 'fire'
                """,
                key,
            )
    except Exception as e:
        logger.warning("record_fire failed: %s", e)


async def record_feedback(db_pool: Any, gate_class: str, *, positive: bool) -> None:
    if not feedback_enabled() or not db_pool or not gate_class:
        return
    key = f"runtime_gate:{gate_class}"
    delta = 0.03 if positive else -0.05
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO clinical_gate_confidence
                    (gate_key, confidence, sample_size, positive_count, negative_count, reasoning)
                VALUES (
                    $1,
                    GREATEST(0.05, LEAST(0.99, 0.70 + $2::real)),
                    1,
                    CASE WHEN $3 THEN 1 ELSE 0 END,
                    CASE WHEN $3 THEN 0 ELSE 1 END,
                    $4
                )
                ON CONFLICT (gate_key) DO UPDATE SET
                    confidence = GREATEST(
                        0.05,
                        LEAST(0.99, clinical_gate_confidence.confidence + $2::real)
                    ),
                    sample_size = clinical_gate_confidence.sample_size + 1,
                    positive_count = clinical_gate_confidence.positive_count
                        + CASE WHEN $3 THEN 1 ELSE 0 END,
                    negative_count = clinical_gate_confidence.negative_count
                        + CASE WHEN $3 THEN 0 ELSE 1 END,
                    updated_at = NOW(),
                    reasoning = $4
                """,
                key,
                delta,
                positive,
                "positive" if positive else "false_positive_signal",
            )
        # L4 — measured FP outcomes may auto-draft soft rules (never hard SI/violence)
        if not positive:
            try:
                from app.services.ln_rule_loop import maybe_draft_from_false_positive

                await maybe_draft_from_false_positive(db_pool, gate_class)
            except Exception as draft_e:
                logger.warning("L4 FP draft hook: %s", draft_e)
    except Exception as e:
        logger.warning("record_feedback failed: %s", e)


# In-process last-fired class per session (bridge soft FP detection)
_last_gate_class: dict[str, str] = {}


def remember_fire(session_key: str, gate_class: str) -> None:
    if session_key and gate_class:
        _last_gate_class[session_key] = gate_class


def pop_last_class(session_key: str) -> Optional[str]:
    return _last_gate_class.pop(session_key, None) if session_key else None
