"""Predictive Restraint — Safety S3.

Blocks generation when signals predict the user is not in a state to
receive therapeutic content safely. Checks:

1. MASKED user state (sse_identity_forge.mask_detection_state)
2. Surveillance context (institutional deployment where content must be
   sanitized or suppressed)
3. Escalation velocity (rapid intensity increases across recent generations)

Returns a safety_gate dict consumed by the TMC and Temporal Orchestrator.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

ESCALATION_VELOCITY_THRESHOLD = 0.3
ESCALATION_WINDOW_HOURS = 2
SURVEILLANCE_BLOCKED_MODALITIES = frozenset({"narration", "video_clip"})


async def evaluate_safety(
    user_id: str,
    db_pool,
    deployment_context: str = "private",
) -> dict[str, Any]:
    """Run all S3 safety checks. Returns a gate dict."""
    gate: dict[str, Any] = {
        "blocked": False,
        "reason": None,
        "masked": False,
        "surveillance": deployment_context in ("institutional", "court_ordered"),
        "escalation_velocity": 0.0,
        "modality_restrictions": [],
    }

    if not db_pool:
        return gate

    try:
        async with db_pool.acquire() as conn:
            mask_row = await conn.fetchrow(
                "SELECT mask_detection_state FROM sse_identity_forge "
                "WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
                user_id,
            )
            if mask_row and mask_row["mask_detection_state"]:
                mask_state = mask_row["mask_detection_state"]
                if isinstance(mask_state, dict) and mask_state.get("active"):
                    gate["masked"] = True
                    gate["blocked"] = True
                    gate["reason"] = "MASKED user — identity forge detected active mask"
                    return gate

            if gate["surveillance"]:
                gate["modality_restrictions"] = list(SURVEILLANCE_BLOCKED_MODALITIES)

            window = datetime.now(timezone.utc) - timedelta(hours=ESCALATION_WINDOW_HOURS)
            velocity_rows = await conn.fetch(
                "SELECT intensity_score, created_at FROM intensity_ledger "
                "WHERE user_id = $1 AND created_at >= $2 "
                "ORDER BY created_at ASC",
                user_id, window,
            )
            if len(velocity_rows) >= 2:
                scores = [float(r["intensity_score"]) for r in velocity_rows]
                delta = scores[-1] - scores[0]
                gate["escalation_velocity"] = round(delta, 4)
                if delta >= ESCALATION_VELOCITY_THRESHOLD:
                    gate["blocked"] = True
                    gate["reason"] = (
                        f"Escalation velocity {delta:.3f} exceeds "
                        f"threshold {ESCALATION_VELOCITY_THRESHOLD}"
                    )

    except Exception as e:
        logger.warning("Predictive restraint check failed for %s: %s", user_id, e)

    return gate
