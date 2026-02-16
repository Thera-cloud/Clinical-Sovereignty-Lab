"""
HIVE DEFENSE PROTOCOL — Canary Monitor Worker (Phase 8B)
Continuous decoy-credential access detection.

Runs every 60 seconds, checks all planted canary credentials for
unauthorised access, and triggers DEFCON 2 escalation on any hit.

This worker is the automated counterpart to the manual
:meth:`CanaryCredentialManager.check_access` — it ensures that even
if no one explicitly polls a canary, any access is detected within
at most 60 seconds.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger("hive.canary_monitor")


# =============================================================================
# CONSTANTS
# =============================================================================

# Default poll interval (seconds).
DEFAULT_INTERVAL: float = 60.0

# DEFCON → interval mapping for tighter monitoring at higher threat levels.
DEFCON_INTERVAL_MAP: Dict[int, float] = {
    5: 60.0,    # PEACE — standard 60s
    4: 45.0,    # ELEVATED
    3: 30.0,    # SUBSTANTIAL
    2: 15.0,    # SEVERE — near real-time
    1: 5.0,     # CRITICAL — maximum vigilance
}


# =============================================================================
# CANARY MONITOR WORKER
# =============================================================================

class CanaryMonitorWorker:
    """Background worker: continuous canary-credential access detection.

    Responsibilities
    ----------------
    * Poll the :class:`CanaryCredentialManager` for newly triggered canaries.
    * For each triggered canary, invoke ``on_canary_triggered`` to execute
      the DEFCON 2 escalation response chain.
    * Emit structured metrics after each poll cycle.

    Parameters
    ----------
    canary_manager : Any
        Reference to :class:`CanaryCredentialManager`.
    db_pool : Any, optional
        asyncpg connection pool for metrics persistence.
    forensic_logger : Any, optional
        :class:`ForensicLogger` for evidence-chain logging.
    defcon_provider : callable, optional
        Async callable returning the current DEFCON level (int 1-5).
    base_interval : float
        Default poll interval in seconds.
    """

    def __init__(
        self,
        canary_manager: Any,
        db_pool: Any = None,
        forensic_logger: Any = None,
        defcon_provider: Optional[Any] = None,
        base_interval: float = DEFAULT_INTERVAL,
    ) -> None:
        self.canary_manager = canary_manager
        self.db_pool = db_pool
        self.forensic_logger = forensic_logger
        self.defcon_provider = defcon_provider
        self.base_interval = base_interval

        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

        # Processed canary events (to avoid double-handling)
        self._processed_events: set = set()

        # Cumulative metrics
        self._total_polls: int = 0
        self._total_triggers_detected: int = 0
        self._total_escalations_fired: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the canary monitoring loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("worker_started", worker="CanaryMonitorWorker")

    async def stop(self) -> None:
        """Gracefully stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(
            "worker_stopped",
            worker="CanaryMonitorWorker",
            total_polls=self._total_polls,
            total_triggers=self._total_triggers_detected,
            total_escalations=self._total_escalations_fired,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Primary loop: poll canaries at the DEFCON-adjusted interval."""
        while self._running:
            cycle_start = time.monotonic()
            try:
                await self._poll_canaries()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "canary_poll_error",
                    error=str(exc),
                    exc_info=True,
                )

            interval = await self._current_interval()
            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0.0, interval - elapsed)
            await asyncio.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Poll logic
    # ------------------------------------------------------------------

    async def _poll_canaries(self) -> None:
        """Check all planted canaries for new access events.

        For each newly detected access:
        1. Log the event.
        2. Invoke the canary manager's trigger handler (which escalates
           to DEFCON 2 and logs forensic evidence).
        3. Record the event as processed to prevent duplicate handling.
        """
        self._total_polls += 1

        # Fetch triggered canaries
        triggered_events = await self._fetch_triggered_canaries()

        new_events: List[Dict[str, Any]] = []
        for event in triggered_events:
            # Create a dedup key
            event_key = f"{event.get('canary_id')}:{event.get('accessed_at', '')}"
            if event_key in self._processed_events:
                continue

            new_events.append(event)
            self._processed_events.add(event_key)

        if not new_events:
            # Normal cycle — no triggers
            if self._total_polls % 60 == 0:  # Log every ~60 cycles (~1h)
                logger.debug(
                    "canary_poll_clear",
                    polls=self._total_polls,
                    processed_total=len(self._processed_events),
                )
            return

        # Process new trigger events
        self._total_triggers_detected += len(new_events)

        for event in new_events:
            canary_id = event.get("canary_id", "unknown")
            access_source = event.get("access_source", "unknown")

            logger.critical(
                "CANARY_ACCESS_DETECTED",
                canary_id=canary_id,
                access_source=access_source,
                credential_type=event.get("credential_type"),
                location=event.get("planted_location"),
            )

            # Invoke the canary manager's trigger handler
            try:
                if hasattr(self.canary_manager, "on_canary_triggered"):
                    from uuid import UUID
                    cid = UUID(canary_id) if isinstance(canary_id, str) else canary_id
                    result = await self.canary_manager.on_canary_triggered(
                        canary_id=cid,
                        access_source=access_source,
                        access_metadata={
                            "detected_by": "canary_monitor_worker",
                            "poll_cycle": self._total_polls,
                            "original_event": event,
                        },
                    )
                    if result.get("escalation", {}).get("escalated"):
                        self._total_escalations_fired += 1
            except Exception as exc:
                logger.error(
                    "canary_trigger_handler_failed",
                    canary_id=canary_id,
                    error=str(exc),
                )

        # Persist poll metrics
        await self._persist_poll_metrics(len(new_events))

        logger.warning(
            "canary_poll_complete",
            triggers_detected=len(new_events),
            total_triggers=self._total_triggers_detected,
            total_escalations=self._total_escalations_fired,
        )

    async def _fetch_triggered_canaries(self) -> List[Dict[str, Any]]:
        """Fetch triggered canary events from the canary manager and/or database.

        Returns
        -------
        list[dict]
            Triggered canary events.
        """
        events: List[Dict[str, Any]] = []

        # Primary: ask the canary manager
        if hasattr(self.canary_manager, "check_all_canaries"):
            try:
                manager_events = await self.canary_manager.check_all_canaries()
                events.extend(manager_events)
            except Exception as exc:
                logger.debug("canary_manager_check_failed", error=str(exc))

        # Secondary: direct DB query as fallback
        if not events and self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT cc.canary_id, cc.credential_type, cc.planted_location,
                               cc.accessed_at, cc.access_source
                        FROM canary_credentials cc
                        WHERE cc.accessed = true
                          AND cc.active = true
                          AND cc.accessed_at IS NOT NULL
                        ORDER BY cc.accessed_at DESC
                        LIMIT 100
                    """)
                    for row in rows:
                        events.append({
                            "canary_id": str(row["canary_id"]),
                            "credential_type": row["credential_type"],
                            "planted_location": row["planted_location"],
                            "accessed_at": row["accessed_at"].isoformat() if row["accessed_at"] else None,
                            "access_source": row["access_source"],
                        })
            except Exception as exc:
                logger.debug("canary_db_check_failed", error=str(exc))

        return events

    # ------------------------------------------------------------------
    # DEFCON-aware interval
    # ------------------------------------------------------------------

    async def _current_interval(self) -> float:
        """Return the poll interval adjusted for the current DEFCON level."""
        if self.defcon_provider:
            try:
                level = await self.defcon_provider()
                level_int = int(level.value) if hasattr(level, "value") else int(level)
                return DEFCON_INTERVAL_MAP.get(level_int, self.base_interval)
            except Exception:
                pass
        return self.base_interval

    # ------------------------------------------------------------------
    # Metrics persistence
    # ------------------------------------------------------------------

    async def _persist_poll_metrics(self, triggers: int) -> None:
        """Write poll-cycle metrics to the database."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_canary_metrics
                        (poll_number, triggers_detected, escalations_fired, polled_at)
                    VALUES ($1, $2, $3, NOW())
                    """,
                    self._total_polls,
                    triggers,
                    self._total_escalations_fired,
                )
        except Exception as exc:
            logger.debug("canary_metrics_persist_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics for monitoring."""
        return {
            "running": self._running,
            "total_polls": self._total_polls,
            "total_triggers_detected": self._total_triggers_detected,
            "total_escalations_fired": self._total_escalations_fired,
            "processed_events": len(self._processed_events),
        }

    def __repr__(self) -> str:
        return (
            f"<CanaryMonitorWorker "
            f"polls={self._total_polls} "
            f"triggers={self._total_triggers_detected} "
            f"escalations={self._total_escalations_fired}>"
        )
