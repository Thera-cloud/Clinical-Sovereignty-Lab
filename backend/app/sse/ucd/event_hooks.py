"""UCD Event Hook Registry — lightweight bridge between therapeutic subsystems and the TMC.

Subsystems (crystallizer, nevedal engine, cycle detection) call
`fire_ucd_event()` to notify the TMC of clinically relevant state changes.
The hook registry dispatches classification asynchronously — subsystems
are never blocked waiting for UCD to respond.

Event types:
  crystal_locked      — a crystal crossed LOCKED confidence threshold
  crystal_created     — a new crystal was synthesized
  ec_shift            — C_emo slope exceeded ±0.15 within a session window
  cycle_detected      — CycleDetectionEngine found a significant pattern
  session_ended       — a therapy session (chat/voice) ended
  manual_trigger      — admin/clinician manual TMC evaluation request

Integration pattern (additive, 2 lines per subsystem):

    from app.sse.ucd.event_hooks import fire_ucd_event
    asyncio.create_task(fire_ucd_event(user_id, "crystal_locked", {...}, db_pool, app_state))
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def fire_ucd_event(
    user_id: str,
    event_type: str,
    payload: dict[str, Any],
    db_pool,
    app_state=None,
) -> None:
    """Non-blocking entry point for UCD event dispatch.

    This function is safe to call from any subsystem — it catches all
    exceptions and logs warnings without propagating failures.
    """
    try:
        orchestrator = _get_orchestrator(db_pool, app_state)
        if not orchestrator:
            logger.debug("UCD event %s for %s — no orchestrator available", event_type, user_id)
            return

        from .tmc import TherapeuticMomentClassifier
        from ..adapters.narrative_state import read_or_create_nso

        nso = await read_or_create_nso(user_id, db_pool)

        classification = await orchestrator.tmc.classify(user_id)

        moment_class = classification.get("moment_class", "REST")
        if moment_class == "REST":
            logger.debug(
                "UCD event %s for %s classified REST — no generation triggered",
                event_type, user_id,
            )
            return

        directive = await orchestrator.evaluate_and_dispatch(
            user_id, nso=nso, trigger=f"event:{event_type}",
        )
        if directive:
            logger.info(
                "UCD event %s → %s directive for %s (conf=%.2f)",
                event_type, directive.moment_class, user_id, directive.tmc_confidence,
            )

    except Exception as e:
        logger.warning("UCD event hook failed (%s, %s): %s", event_type, user_id, e)


def _get_orchestrator(db_pool, app_state):
    """Resolve or lazily create a TemporalOrchestrator."""
    if app_state:
        existing = getattr(app_state, "ucd_orchestrator", None)
        if existing:
            return existing

    if not db_pool:
        return None

    from .temporal_orchestrator import TemporalOrchestrator
    orch = TemporalOrchestrator(db_pool)

    if app_state:
        try:
            app_state.ucd_orchestrator = orch
        except Exception:
            pass

    return orch
