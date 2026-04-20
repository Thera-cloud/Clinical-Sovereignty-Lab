"""
HIVE DEFENSE PROTOCOL v3.1 — Helix Rotation Worker (Phase 8D)
Background worker that manages continuous rotation of the Trinity Helix
sub-cord sequence.

The worker runs the HelixRotationEngine at the required interval
(50-500ms, adaptive) and ensures that:
    1. Entropy sources remain healthy.
    2. Rotation events are logged for audit.
    3. The TrinityHelix state is periodically persisted to the database.
    4. Degraded entropy is detected and escalated.

Lifecycle:
    - ``start()`` → spawns the background asyncio.Task.
    - ``stop()``  → gracefully cancels and performs a final state persist.

The worker's interval is NOT fixed — it reads the current rotation
interval from the helix state after each rotation, which itself is
entropy-derived (50-500ms).

Patent-Pending — Claims 48-49, 52
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger("hive.helix_rotation_worker")


# =============================================================================
# TUNABLES
# =============================================================================

# Minimum sleep between rotations (safety floor)
MIN_SLEEP_SEC: float = 0.040  # 40ms (below 50ms floor to account for jitter)

# Maximum sleep between rotations (safety ceiling)
MAX_SLEEP_SEC: float = 0.600  # 600ms

# How often to persist helix state to DB (every N rotations)
PERSIST_EVERY_N: int = 50

# How often to check entropy health (every N rotations)
HEALTH_CHECK_EVERY_N: int = 10

# Maximum consecutive entropy failures before alert
MAX_ENTROPY_FAILURES: int = 5


# =============================================================================
# HELIX ROTATION WORKER
# =============================================================================

class HelixRotationWorker:
    """
    Background worker managing continuous Trinity Helix rotation.

    Runs the HelixRotationEngine at the entropy-derived interval,
    monitors entropy source health, and persists state for crash
    recovery.

    Parameters
    ----------
    trinity_helix : object
        The ``TrinityHelix`` instance whose state is being rotated.
    rotation_engine : object
        The ``HelixRotationEngine`` that performs the actual rotation.
    event_bus : object, optional
        Hive event bus for publishing rotation and health events.
    db_pool : object, optional
        asyncpg connection pool for state persistence.

    Usage
    -----
    ::

        worker = HelixRotationWorker(
            trinity_helix=helix,
            rotation_engine=engine,
        )
        await worker.start()
        # ... runs continuously ...
        await worker.stop()
    """

    def __init__(
        self,
        trinity_helix=None,
        rotation_engine=None,
        event_bus=None,
        db_pool=None,
    ) -> None:
        self._helix = trinity_helix
        self._engine = rotation_engine
        self._event_bus = event_bus
        self._db_pool = db_pool

        # Worker state
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

        # Metrics
        self._rotations_performed: int = 0
        self._consecutive_entropy_failures: int = 0
        self._total_entropy_failures: int = 0
        self._last_rotation_time: Optional[datetime] = None
        self._last_persist_time: Optional[datetime] = None
        self._last_degradation_log: Optional[datetime] = None
        self._started_at: Optional[datetime] = None

    # ─── Lifecycle ───────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the helix rotation loop."""
        if self._running:
            logger.warning(
                ">>> [HELIX_WORKER] Already running — ignoring start()"
            )
            return

        self._running = True
        self._started_at = datetime.utcnow()
        self._task = asyncio.create_task(
            self._run_loop(),
            name="helix_rotation_worker",
        )
        logger.info(">>> [HELIX_WORKER] Started — continuous rotation active")

    async def stop(self) -> None:
        """Gracefully stop the rotation loop and perform final persist."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Final state persist
        await self._persist_state()

        logger.info(
            ">>> [HELIX_WORKER] Stopped — %d rotations performed, "
            "%d entropy failures",
            self._rotations_performed,
            self._total_entropy_failures,
        )

    # ─── Main Loop ───────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """
        Primary rotation loop.

        After each rotation, reads the new interval from the helix state
        and sleeps for that duration before the next rotation.  The
        interval is itself entropy-derived, making the rotation timing
        unpredictable.
        """
        logger.info(">>> [HELIX_WORKER] Rotation loop entered")

        while self._running:
            cycle_start = time.monotonic()

            try:
                await self._rotation_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    ">>> [HELIX_WORKER] Rotation cycle error: %s",
                    exc,
                    exc_info=True,
                )

            # Determine sleep interval from current helix state
            sleep_sec = self._get_sleep_interval()
            elapsed = time.monotonic() - cycle_start
            actual_sleep = max(0.0, sleep_sec - elapsed)

            try:
                await asyncio.sleep(actual_sleep)
            except asyncio.CancelledError:
                raise

    # ─── Rotation Cycle ──────────────────────────────────────────────────

    async def _rotation_cycle(self) -> None:
        """
        Execute a single rotation cycle:
            1. Trigger rotation via engine (or helix directly).
            2. Update helix state.
            3. Check entropy health.
            4. Periodic persistence.
            5. Log audit event.
        """
        # 1. Perform rotation
        rotation_result = await self._perform_rotation()
        if rotation_result is None:
            return

        self._rotations_performed += 1
        self._last_rotation_time = datetime.utcnow()

        # 2. Check entropy health
        entropy_healthy = rotation_result.get("entropy_healthy", True)
        if entropy_healthy:
            self._consecutive_entropy_failures = 0
        else:
            self._consecutive_entropy_failures += 1
            self._total_entropy_failures += 1
            # Per-rotation degradation is always logged at debug to avoid log
            # flooding. The rate-limited *** ENTROPY DEGRADATION *** message
            # in _handle_entropy_degradation is the operator-visible signal.
            logger.debug(
                ">>> [HELIX_WORKER] Entropy degraded — consecutive "
                "failures: %d",
                self._consecutive_entropy_failures,
            )

        # 3. Entropy health escalation
        if self._consecutive_entropy_failures >= MAX_ENTROPY_FAILURES:
            await self._handle_entropy_degradation()

        # 4. Periodic health check
        if self._rotations_performed % HEALTH_CHECK_EVERY_N == 0:
            await self._health_check()

        # 5. Periodic persistence
        if self._rotations_performed % PERSIST_EVERY_N == 0:
            await self._persist_state()

        # 6. Log audit event (at reduced frequency to avoid noise)
        if self._rotations_performed % 100 == 0:
            logger.info(
                ">>> [HELIX_WORKER] Rotation milestone: #%d — "
                "interval=%.0fms entropy_ok=%s",
                self._rotations_performed,
                rotation_result.get("new_interval_ms", 0),
                entropy_healthy,
            )

    async def _perform_rotation(self) -> Optional[Dict[str, Any]]:
        """
        Perform the actual rotation — delegates to the engine or helix.
        """
        if self._engine:
            try:
                result = await self._engine.rotate()

                # Update helix state if we have a direct reference
                if self._helix:
                    self._helix._state.current_sequence = result["new_sequence"]
                    self._helix._state.rotation_interval_ms = result["new_interval_ms"]
                    self._helix._state.rotation_count = result.get(
                        "rotation_number",
                        self._helix._state.rotation_count + 1,
                    )
                    self._helix._state.last_rotation_ns = time.monotonic_ns()
                    self._helix._state.entropy_sources_healthy = result.get(
                        "entropy_healthy", True
                    )

                return result
            except Exception as exc:
                logger.error(
                    ">>> [HELIX_WORKER] Rotation engine error: %s", exc
                )
                return None

        # Fallback: trigger helix's own rotation
        if self._helix:
            try:
                await self._helix._rotate()
                return {
                    "new_sequence": self._helix._state.current_sequence,
                    "new_interval_ms": self._helix._state.rotation_interval_ms,
                    "entropy_healthy": self._helix._state.entropy_sources_healthy,
                }
            except Exception as exc:
                logger.error(
                    ">>> [HELIX_WORKER] Helix rotation error: %s", exc
                )
                return None

        logger.warning(
            ">>> [HELIX_WORKER] No engine or helix — cannot rotate"
        )
        return None

    # ─── Sleep Interval ──────────────────────────────────────────────────

    def _get_sleep_interval(self) -> float:
        """
        Get the next sleep interval from the helix state.

        Clamps to [MIN_SLEEP_SEC, MAX_SLEEP_SEC] for safety.
        """
        if self._helix:
            interval_ms = self._helix._state.rotation_interval_ms
            interval_sec = interval_ms / 1000.0
            return max(MIN_SLEEP_SEC, min(MAX_SLEEP_SEC, interval_sec))

        # Default fallback
        return 0.200  # 200ms

    # ─── Health Checks ───────────────────────────────────────────────────

    async def _health_check(self) -> None:
        """
        Periodic health check of the rotation subsystem.
        """
        if self._engine:
            summary = self._engine.summary()
            recent = summary.get("recent_rotations", [])
            if recent:
                unhealthy = [
                    r for r in recent
                    if not r.get("coherence_available")
                    or not r.get("hsm_healthy")
                ]
                if len(unhealthy) > len(recent) * 0.5:
                    logger.debug(
                        ">>> [HELIX_WORKER] >50%% of recent rotations had "
                        "degraded entropy"
                    )

    async def _handle_entropy_degradation(self) -> None:
        """
        Handle sustained entropy source degradation.

        Fires a hive event and resets the failure counter.
        """
        # Rate-limit the loud log line to once per 5 minutes per worker
        # to prevent log flooding when entropy is sustained-degraded.
        _now = datetime.utcnow()
        _should_log = (
            self._last_degradation_log is None
            or (_now - self._last_degradation_log).total_seconds() > 300
        )
        if _should_log:
            logger.warning(
                ">>> [HELIX_WORKER] *** ENTROPY DEGRADATION *** — "
                "%d consecutive failures",
                self._consecutive_entropy_failures,
            )
            self._last_degradation_log = _now

        if self._event_bus:
            try:
                await self._fire_event(
                    topic="hive.helix.entropy_degraded",
                    payload={
                        "consecutive_failures": self._consecutive_entropy_failures,
                        "total_failures": self._total_entropy_failures,
                        "rotations_performed": self._rotations_performed,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )
            except Exception as exc:
                logger.error(
                    ">>> [HELIX_WORKER] Event bus publish failed: %s", exc
                )

        # Reset counter (will escalate again if problem persists)
        self._consecutive_entropy_failures = 0

    # ─── Persistence ─────────────────────────────────────────────────────

    async def _persist_state(self) -> None:
        """Persist current helix state to the database."""
        if self._helix:
            try:
                await self._helix.persist_state()
                self._last_persist_time = datetime.utcnow()
            except Exception as exc:
                logger.error(
                    ">>> [HELIX_WORKER] State persist failed: %s", exc
                )

    # ─── Event Bus ───────────────────────────────────────────────────────

    async def _fire_event(
        self, topic: str, payload: Dict[str, Any]
    ) -> None:
        """Publish a hive event."""
        if not self._event_bus:
            return
        try:
            if asyncio.iscoroutinefunction(
                getattr(self._event_bus, "publish", None)
            ):
                await self._event_bus.publish(topic, payload)
            elif hasattr(self._event_bus, "publish"):
                self._event_bus.publish(topic, payload)
        except Exception as exc:
            logger.error(
                ">>> [HELIX_WORKER] Event publish failed: %s", exc
            )

    # ─── Diagnostics ─────────────────────────────────────────────────────

    @property
    def stats(self) -> Dict[str, Any]:
        """Worker diagnostic metrics."""
        uptime = None
        if self._started_at:
            uptime = (datetime.utcnow() - self._started_at).total_seconds()

        return {
            "running": self._running,
            "rotations_performed": self._rotations_performed,
            "consecutive_entropy_failures": self._consecutive_entropy_failures,
            "total_entropy_failures": self._total_entropy_failures,
            "last_rotation": (
                self._last_rotation_time.isoformat()
                if self._last_rotation_time
                else None
            ),
            "last_persist": (
                self._last_persist_time.isoformat()
                if self._last_persist_time
                else None
            ),
            "uptime_seconds": round(uptime, 1) if uptime else None,
        }

    def __repr__(self) -> str:
        return (
            f"<HelixRotationWorker "
            f"running={self._running} "
            f"rotations={self._rotations_performed}>"
        )
