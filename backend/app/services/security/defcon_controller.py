"""
HIVE DEFENSE PROTOCOL v1.0 — DEFCON Controller (Phase 8B)
Five-level graduated defense posture with instant escalation and 4-hour deescalation.

The DEFCON Controller is the central nervous system of the Hive's threat response.
It translates observed curiosity events, gate rejections, and three-cord failures
into concrete operational parameters that every subsystem respects:

    PEACE (5)       — Normal operations.  Mirror passive, heartbeat 60s.
    ELEVATED (4)    — 3+ NOTICE in 1h.  Mirror active, heartbeat 30s.
    SUBSTANTIAL (3) — INTEREST or >10 gate rejections/min.  Mirror absorbing,
                      heartbeat 10s, all payloads inspected, CDS -50%.
    SEVERE (2)      — ALARM or multi-vector.  Fortress mode, heartbeat 5s,
                      Ghost Swarm deployed, NO new Fibre births.
    CRITICAL (1)    — Three-cord failure on multiple entities OR shard compromise.
                      Real hive DISCONNECTS.  Maintenance page.  Full lockdown.

Escalation is *instant* — any trigger at a higher severity level promotes
the system immediately.  Deescalation requires a 4-hour cool-down with no
new events at the current level or above.

Patent-Pending — Claim 40
    "A graduated defense condition system for a distributed AI therapy hive,
     comprising five severity levels with automatic escalation and time-gated
     deescalation, wherein each level adjusts heartbeat frequency, mirror
     absorption mode, certificate birth limits, and content inspection depth."

© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Coroutine, Dict, List, Optional
from uuid import UUID, uuid4

from app.models.hive_defense import (
    CuriosityLevel,
    DefconLevel,
    DefconState,
    ForensicRecord,
    HIVE_EVENT_TOPICS,
)

logger = logging.getLogger("hive.defcon")


# =============================================================================
# DEFCON PARAMETER PROFILES
# =============================================================================

@dataclass(frozen=True)
class DefconParameters:
    """Operational parameters bound to a specific DEFCON level."""

    level: DefconLevel
    heartbeat_interval_sec: float
    mirror_mode: str                   # passive | active | absorbing | fortress
    cds_threshold_multiplier: float    # 1.0 = normal, 0.5 = -50%
    inspect_all_payloads: bool
    max_cert_births: int
    cert_validity_hours: float
    ghost_swarm_mode: str              # off | standby | deployed
    allow_new_fibre_births: bool
    require_ring_verification: bool
    notify_nathan: bool
    notify_legal: bool
    notify_clinical: bool
    secondary_channels: bool
    disconnect_real_hive: bool
    maintenance_page: bool
    rotate_keys: bool
    description: str


# The five canonical parameter profiles — never modify at runtime.
_DEFCON_PROFILES: Dict[DefconLevel, DefconParameters] = {
    DefconLevel.PEACE: DefconParameters(
        level=DefconLevel.PEACE,
        heartbeat_interval_sec=60.0,
        mirror_mode="passive",
        cds_threshold_multiplier=1.0,
        inspect_all_payloads=False,
        max_cert_births=50,
        cert_validity_hours=24.0,
        ghost_swarm_mode="off",
        allow_new_fibre_births=True,
        require_ring_verification=False,
        notify_nathan=False,
        notify_legal=False,
        notify_clinical=False,
        secondary_channels=False,
        disconnect_real_hive=False,
        maintenance_page=False,
        rotate_keys=False,
        description="Normal operations. All systems green.",
    ),
    DefconLevel.ELEVATED: DefconParameters(
        level=DefconLevel.ELEVATED,
        heartbeat_interval_sec=30.0,
        mirror_mode="active",
        cds_threshold_multiplier=1.0,
        inspect_all_payloads=False,
        max_cert_births=50,
        cert_validity_hours=12.0,
        ghost_swarm_mode="standby",
        allow_new_fibre_births=True,
        require_ring_verification=False,
        notify_nathan=False,
        notify_legal=False,
        notify_clinical=False,
        secondary_channels=False,
        disconnect_real_hive=False,
        maintenance_page=False,
        rotate_keys=False,
        description="Elevated awareness. 3+ NOTICE-level events in 1h.",
    ),
    DefconLevel.SUBSTANTIAL: DefconParameters(
        level=DefconLevel.SUBSTANTIAL,
        heartbeat_interval_sec=10.0,
        mirror_mode="absorbing",
        cds_threshold_multiplier=0.5,
        inspect_all_payloads=True,
        max_cert_births=10,
        cert_validity_hours=1.0,
        ghost_swarm_mode="standby",
        allow_new_fibre_births=True,
        require_ring_verification=False,
        notify_nathan=False,
        notify_legal=False,
        notify_clinical=False,
        secondary_channels=False,
        disconnect_real_hive=False,
        maintenance_page=False,
        rotate_keys=False,
        description=(
            "Substantial threat. INTEREST-level curiosity or >10 gate "
            "rejections/min. Shard holders warned."
        ),
    ),
    DefconLevel.SEVERE: DefconParameters(
        level=DefconLevel.SEVERE,
        heartbeat_interval_sec=5.0,
        mirror_mode="fortress",
        cds_threshold_multiplier=0.25,
        inspect_all_payloads=True,
        max_cert_births=0,
        cert_validity_hours=0.0,
        ghost_swarm_mode="deployed",
        allow_new_fibre_births=False,
        require_ring_verification=True,
        notify_nathan=True,
        notify_legal=False,
        notify_clinical=False,
        secondary_channels=True,
        disconnect_real_hive=False,
        maintenance_page=False,
        rotate_keys=False,
        description=(
            "Severe threat. ALARM-level or multi-vector attack. Fortress mode — "
            "zero new connections, Ghost Swarm deployed, Nathan called."
        ),
    ),
    DefconLevel.CRITICAL: DefconParameters(
        level=DefconLevel.CRITICAL,
        heartbeat_interval_sec=2.0,
        mirror_mode="fortress",
        cds_threshold_multiplier=0.0,
        inspect_all_payloads=True,
        max_cert_births=0,
        cert_validity_hours=0.0,
        ghost_swarm_mode="deployed",
        allow_new_fibre_births=False,
        require_ring_verification=True,
        notify_nathan=True,
        notify_legal=True,
        notify_clinical=True,
        secondary_channels=True,
        disconnect_real_hive=True,
        maintenance_page=True,
        rotate_keys=True,
        description=(
            "CRITICAL. Three-cord failure on multiple entities or shard compromise. "
            "Real hive DISCONNECTED. Maintenance page live. Immutable backup. "
            "Key rotation. Full re-verification. Nathan + legal + clinical notified."
        ),
    ),
}


# Deescalation hold period (seconds).  System must remain quiet for this
# duration before stepping down one level.
DEESCALATION_HOLD_SEC: float = 4 * 3600  # 4 hours


# =============================================================================
# EVENT HISTORY ENTRY
# =============================================================================

@dataclass
class _EscalationEvent:
    """Internal record of an escalation or deescalation event."""

    event_id: UUID = field(default_factory=uuid4)
    from_level: DefconLevel = DefconLevel.PEACE
    to_level: DefconLevel = DefconLevel.PEACE
    reason: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    is_escalation: bool = True


# =============================================================================
# DEFCON CONTROLLER
# =============================================================================

class DefconController:
    """
    Central DEFCON state machine for the Hive Defense Protocol.

    The controller maintains the current defense posture and exposes methods
    to escalate, deescalate, and query operational parameters.  All state
    transitions are persisted to the ``defcon_state`` and ``defcon_history``
    PostgreSQL tables and broadcast via an optional event-bus callback.

    Thread Safety
    -------------
    All mutating operations are guarded by an ``asyncio.Lock``.  This class
    is designed for single-threaded asyncio use.

    Usage
    -----
    ::

        controller = DefconController(db_pool=pool)
        await controller.load_state()

        # Escalate on threat
        await controller.escalate(DefconLevel.SUBSTANTIAL, "INTEREST curiosity on 3 entities")

        # Query parameters
        params = controller.get_parameters()
        print(params.heartbeat_interval_sec)

        # Attempt deescalation (respects 4-hour hold)
        ok = await controller.deescalate()

    Patent Ref: Claim 40
    """

    def __init__(
        self,
        db_pool=None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Coroutine]] = None,
    ) -> None:
        """
        Parameters
        ----------
        db_pool:
            An ``asyncpg.Pool`` for persisting DEFCON state.
        event_callback:
            Async callback ``(topic: str, payload: dict) -> None`` for
            broadcasting state changes to the hive event bus.
        """
        self._db_pool = db_pool
        self._event_callback = event_callback

        # Current state
        self._state = DefconState(
            level=DefconLevel.PEACE,
            triggered_at=datetime.utcnow(),
            trigger_reason="System initialisation",
            heartbeat_interval_sec=60.0,
            cds_threshold_multiplier=1.0,
            max_cert_births=50,
            mirror_mode="passive",
        )

        # History of transitions (in-memory ring buffer, last 200)
        self._history: List[_EscalationEvent] = []
        self._history_max: int = 200

        # Timestamp of the last event at or above the current level.
        # Deescalation is blocked until ``now - _last_level_event >= HOLD``.
        self._last_level_event: datetime = datetime.utcnow()

        # Concurrency guard
        self._lock: asyncio.Lock = asyncio.Lock()

        logger.info(
            "DefconController initialised at level %s",
            self._state.level.name,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def escalate(
        self,
        new_level: DefconLevel,
        reason: str,
    ) -> DefconState:
        """
        Immediately escalate to *new_level* (if it is more severe than the current level).

        Escalation is **instant** — there is no hold period.  If *new_level*
        is less severe than or equal to the current level, the call is a no-op
        and the current state is returned unchanged.

        Parameters
        ----------
        new_level:
            Target DEFCON level (lower integer = more severe).
        reason:
            Human-readable reason for the escalation.

        Returns
        -------
        DefconState
            The (possibly updated) DEFCON state.
        """
        async with self._lock:
            # DefconLevel uses int values: lower number = more severe
            if new_level.value >= self._state.level.value:
                logger.debug(
                    "Escalation request to %s ignored — current level %s "
                    "is already at or above",
                    new_level.name,
                    self._state.level.name,
                )
                return self._state

            old_level = self._state.level

            # Apply the new level
            params = _DEFCON_PROFILES[new_level]
            self._state = DefconState(
                level=new_level,
                triggered_at=datetime.utcnow(),
                trigger_reason=reason,
                heartbeat_interval_sec=params.heartbeat_interval_sec,
                cds_threshold_multiplier=params.cds_threshold_multiplier,
                max_cert_births=params.max_cert_births,
                mirror_mode=params.mirror_mode,
                last_escalation=datetime.utcnow(),
                last_deescalation=self._state.last_deescalation,
            )

            # Record the event
            self._last_level_event = datetime.utcnow()
            event = _EscalationEvent(
                from_level=old_level,
                to_level=new_level,
                reason=reason,
                is_escalation=True,
            )
            self._append_history(event)

            logger.warning(
                "⚠ DEFCON ESCALATED: %s → %s  reason=%s",
                old_level.name,
                new_level.name,
                reason,
            )

            # Persist and broadcast (outside lock is fine — we copied state)
            state_snapshot = self._state.model_copy()

        await self._persist_state(state_snapshot, event)
        await self._broadcast_event(
            "hive.defcon.escalated",
            {
                "from": old_level.name,
                "to": new_level.name,
                "reason": reason,
                "parameters": self._params_to_dict(
                    _DEFCON_PROFILES[new_level]
                ),
            },
        )

        # Layer 8: Sovereign Fall Command — auto-backup on CRITICAL/LOCKDOWN
        if new_level in (DefconLevel.CRITICAL,):
            try:
                from app.services.security.sovereign_fall_command import get_fall_command
                fall = get_fall_command()
                import asyncio
                asyncio.create_task(fall.execute(
                    trigger=f"defcon_{new_level.name.lower()}",
                    include_database=True,
                ))
                logger.warning("SOVEREIGN FALL COMMAND triggered by DEFCON %s", new_level.name)
            except Exception as fall_err:
                logger.error("Fall Command trigger failed: %s", fall_err)

        return state_snapshot

    async def deescalate(self) -> Optional[DefconState]:
        """
        Attempt to step the DEFCON level down by one notch.

        Deescalation is only permitted if the system has been at the
        current level (or escalated above it) for at least
        ``DEESCALATION_HOLD_SEC`` seconds without any new events at or
        above the current severity.

        Returns
        -------
        DefconState or None
            The updated state if deescalation succeeded, ``None`` if
            the hold period has not elapsed or the system is already at PEACE.
        """
        async with self._lock:
            if self._state.level == DefconLevel.PEACE:
                logger.debug("Already at PEACE — cannot deescalate further")
                return None

            elapsed = (datetime.utcnow() - self._last_level_event).total_seconds()
            if elapsed < DEESCALATION_HOLD_SEC:
                remaining = DEESCALATION_HOLD_SEC - elapsed
                logger.info(
                    "Deescalation blocked — %.0f s remaining of 4-hour hold "
                    "(current level: %s)",
                    remaining,
                    self._state.level.name,
                )
                return None

            old_level = self._state.level
            new_level = DefconLevel(old_level.value + 1)  # step toward PEACE

            params = _DEFCON_PROFILES[new_level]
            self._state = DefconState(
                level=new_level,
                triggered_at=datetime.utcnow(),
                trigger_reason=f"Deescalation from {old_level.name} after 4-hour hold",
                heartbeat_interval_sec=params.heartbeat_interval_sec,
                cds_threshold_multiplier=params.cds_threshold_multiplier,
                max_cert_births=params.max_cert_births,
                mirror_mode=params.mirror_mode,
                last_escalation=self._state.last_escalation,
                last_deescalation=datetime.utcnow(),
            )

            # Reset the hold timer for the new level
            self._last_level_event = datetime.utcnow()

            event = _EscalationEvent(
                from_level=old_level,
                to_level=new_level,
                reason=self._state.trigger_reason,
                is_escalation=False,
            )
            self._append_history(event)

            logger.info(
                "DEFCON DEESCALATED: %s → %s",
                old_level.name,
                new_level.name,
            )

            state_snapshot = self._state.model_copy()

        await self._persist_state(state_snapshot, event)
        await self._broadcast_event(
            "hive.defcon.deescalated",
            {
                "from": old_level.name,
                "to": new_level.name,
                "parameters": self._params_to_dict(
                    _DEFCON_PROFILES[new_level]
                ),
            },
        )

        return state_snapshot

    def get_state(self) -> DefconState:
        """
        Return the current DEFCON state (non-async, read-only snapshot).

        Returns
        -------
        DefconState
            A copy of the current state.
        """
        return self._state.model_copy()

    def get_parameters(self) -> DefconParameters:
        """
        Return the canonical parameter profile for the current DEFCON level.

        Returns
        -------
        DefconParameters
            Frozen dataclass of operational parameters.
        """
        return _DEFCON_PROFILES[self._state.level]

    def get_history(self, count: int = 50) -> List[Dict[str, Any]]:
        """
        Return the most recent escalation/deescalation events.

        Parameters
        ----------
        count:
            Maximum number of events to return.

        Returns
        -------
        list[dict]
            List of serialised event dicts (most recent first).
        """
        history_slice = self._history[-count:]
        history_slice.reverse()
        return [
            {
                "event_id": str(ev.event_id),
                "from_level": ev.from_level.name,
                "to_level": ev.to_level.name,
                "reason": ev.reason,
                "timestamp": ev.timestamp.isoformat(),
                "is_escalation": ev.is_escalation,
            }
            for ev in history_slice
        ]

    @property
    def current_level(self) -> DefconLevel:
        """Current DEFCON level."""
        return self._state.level

    @property
    def seconds_until_deescalation(self) -> float:
        """
        Seconds remaining before deescalation is permitted.

        Returns 0.0 if the hold period has elapsed or the system is at PEACE.
        """
        if self._state.level == DefconLevel.PEACE:
            return 0.0
        elapsed = (datetime.utcnow() - self._last_level_event).total_seconds()
        remaining = DEESCALATION_HOLD_SEC - elapsed
        return max(0.0, remaining)

    # ------------------------------------------------------------------
    # Convenience escalation triggers
    # ------------------------------------------------------------------

    async def on_curiosity_event(self, level: CuriosityLevel, entity_id: UUID) -> None:
        """
        React to a curiosity-protocol event by escalating DEFCON if warranted.

        Mapping:
            NOTICE  → record (escalation only if 3+ in 1h → ELEVATED)
            INTEREST → SUBSTANTIAL
            CONCERN  → SUBSTANTIAL (confirm)
            ALARM    → SEVERE
        """
        if level == CuriosityLevel.ALARM:
            await self.escalate(
                DefconLevel.SEVERE,
                f"Curiosity ALARM on entity {entity_id}",
            )
        elif level in (CuriosityLevel.INTEREST, CuriosityLevel.CONCERN):
            await self.escalate(
                DefconLevel.SUBSTANTIAL,
                f"Curiosity {level.value.upper()} on entity {entity_id}",
            )
        elif level == CuriosityLevel.NOTICE:
            # Track NOTICE events; escalate to ELEVATED if 3+ in 1 hour
            async with self._lock:
                self._last_level_event = max(
                    self._last_level_event, datetime.utcnow()
                )
            recent_notices = self._count_recent_notices(hours=1)
            if recent_notices >= 3:
                await self.escalate(
                    DefconLevel.ELEVATED,
                    f"3+ NOTICE events in 1h (latest: entity {entity_id})",
                )

    async def on_gate_rejection_spike(self, rejections_per_minute: float) -> None:
        """
        React to a spike in Coherence Gate rejections.

        Escalates to SUBSTANTIAL if >10 rejections/min.
        """
        if rejections_per_minute > 10:
            await self.escalate(
                DefconLevel.SUBSTANTIAL,
                f"Gate rejection spike: {rejections_per_minute:.1f}/min",
            )

    async def on_three_cord_failure(
        self,
        entity_ids: List[UUID],
        shard_compromise: bool = False,
    ) -> None:
        """
        React to three-cord verification failures.

        Single entity → SEVERE.
        Multiple entities or shard compromise → CRITICAL.
        """
        if shard_compromise or len(entity_ids) > 1:
            await self.escalate(
                DefconLevel.CRITICAL,
                f"Three-cord failure on {len(entity_ids)} entities "
                f"(shard_compromise={shard_compromise})",
            )
        elif entity_ids:
            await self.escalate(
                DefconLevel.SEVERE,
                f"Three-cord failure on entity {entity_ids[0]}",
            )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def load_state(self) -> None:
        """
        Load the most recent DEFCON state from the database on startup.

        If no state is found, the controller begins at PEACE.
        """
        if not self._db_pool:
            logger.debug("No DB pool — starting at PEACE")
            return

        try:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT level, triggered_at, trigger_reason,
                           heartbeat_interval_sec, cds_threshold_multiplier,
                           max_cert_births, mirror_mode,
                           last_escalation, last_deescalation
                    FROM defcon_state
                    ORDER BY triggered_at DESC
                    LIMIT 1
                    """
                )
            if row:
                self._state = DefconState(
                    level=DefconLevel(row["level"]),
                    triggered_at=row["triggered_at"],
                    trigger_reason=row["trigger_reason"] or "",
                    heartbeat_interval_sec=row["heartbeat_interval_sec"],
                    cds_threshold_multiplier=row["cds_threshold_multiplier"],
                    max_cert_births=row["max_cert_births"],
                    mirror_mode=row["mirror_mode"] or "passive",
                    last_escalation=row["last_escalation"],
                    last_deescalation=row["last_deescalation"],
                )
                logger.info(
                    "Loaded DEFCON state from DB: level=%s triggered_at=%s",
                    self._state.level.name,
                    self._state.triggered_at.isoformat(),
                )
            else:
                logger.info("No DEFCON state in DB — starting at PEACE")

        except Exception as exc:
            logger.error("Failed to load DEFCON state: %s", exc)

    async def _persist_state(
        self,
        state: DefconState,
        event: _EscalationEvent,
    ) -> None:
        """Persist the current state and the transition event to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                async with conn.transaction():
                    # Upsert the canonical state row
                    await conn.execute(
                        """
                        INSERT INTO defcon_state (
                            level, triggered_at, trigger_reason,
                            heartbeat_interval_sec, cds_threshold_multiplier,
                            max_cert_births, mirror_mode,
                            last_escalation, last_deescalation
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                        """,
                        state.level.value,
                        state.triggered_at,
                        state.trigger_reason,
                        state.heartbeat_interval_sec,
                        state.cds_threshold_multiplier,
                        state.max_cert_births,
                        state.mirror_mode,
                        state.last_escalation,
                        state.last_deescalation,
                    )

                    # Append to the immutable history table
                    await conn.execute(
                        """
                        INSERT INTO defcon_history (
                            event_id, from_level, to_level,
                            reason, is_escalation, timestamp
                        ) VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        event.event_id,
                        event.from_level.value,
                        event.to_level.value,
                        event.reason,
                        event.is_escalation,
                        event.timestamp,
                    )

            logger.debug(
                "Persisted DEFCON transition %s → %s",
                event.from_level.name,
                event.to_level.name,
            )
        except Exception as exc:
            logger.error(
                "Failed to persist DEFCON state: %s", exc
            )

    # ------------------------------------------------------------------
    # Event bus integration
    # ------------------------------------------------------------------

    async def _broadcast_event(
        self,
        topic: str,
        payload: Dict[str, Any],
    ) -> None:
        """Broadcast a DEFCON event via the registered callback."""
        if self._event_callback:
            try:
                await self._event_callback(topic, payload)
            except Exception as exc:
                logger.error(
                    "Event callback failed for topic %s: %s",
                    topic,
                    exc,
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append_history(self, event: _EscalationEvent) -> None:
        """Append an event to the in-memory history ring buffer."""
        self._history.append(event)
        if len(self._history) > self._history_max:
            self._history = self._history[-self._history_max:]

    def _count_recent_notices(self, hours: int = 1) -> int:
        """Count NOTICE-level escalation events within the last *hours* hours."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        return sum(
            1
            for ev in self._history
            if ev.is_escalation
            and ev.timestamp >= cutoff
            and "NOTICE" in ev.reason.upper()
        )

    @staticmethod
    def _params_to_dict(params: DefconParameters) -> Dict[str, Any]:
        """Serialise a DefconParameters dataclass to a plain dict."""
        return {
            "level": params.level.name,
            "heartbeat_interval_sec": params.heartbeat_interval_sec,
            "mirror_mode": params.mirror_mode,
            "cds_threshold_multiplier": params.cds_threshold_multiplier,
            "inspect_all_payloads": params.inspect_all_payloads,
            "max_cert_births": params.max_cert_births,
            "cert_validity_hours": params.cert_validity_hours,
            "ghost_swarm_mode": params.ghost_swarm_mode,
            "allow_new_fibre_births": params.allow_new_fibre_births,
            "require_ring_verification": params.require_ring_verification,
            "notify_nathan": params.notify_nathan,
            "notify_legal": params.notify_legal,
            "notify_clinical": params.notify_clinical,
            "secondary_channels": params.secondary_channels,
            "disconnect_real_hive": params.disconnect_real_hive,
            "maintenance_page": params.maintenance_page,
            "rotate_keys": params.rotate_keys,
            "description": params.description,
        }

    def __repr__(self) -> str:
        return (
            f"<DefconController level={self._state.level.name} "
            f"mirror={self._state.mirror_mode} "
            f"hb={self._state.heartbeat_interval_sec}s>"
        )
