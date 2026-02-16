"""
HIVE DEFENSE PROTOCOL v1.0 — Coherence Gate
Phase 8A: Five-Step Signal Evaluation for Internal Hive Communications

The Coherence Gate is the single checkpoint that every *internal* hive signal
must pass through before reaching the Real Hive.  It implements a strict 5-step
evaluation pipeline:

    Step 1 — Does the signal carry a heartbeat?
             No  → MIRROR_ABSORB  (silent discard into Mirror Dimension)
    Step 2 — Is the heartbeat pulse valid for the claimed identity?
             No  → MIRROR_CONTAIN (quarantine + forensic capture)
    Step 3 — Is the heartbeat consistent with the entity's known history?
             No  → MIRROR_SUSPICIOUS (flag for Curiosity Protocol)
    Step 4 — Does the entity exist in the real registry?
             Verify originator signature (Ed25519 from Big Nate).
             No  → MIRROR_CONTAIN
    Step 5 — All three cords agree → PASS_TO_REAL

IMPORTANT:  External API requests from JWT-authenticated members and coaches
bypass this gate entirely — they use standard FastAPI/JWT auth.  The Coherence
Gate specifically guards internal hive communications:
    • Fibre signals (task dispatch, observations)
    • Trail Emissions (evolution journal broadcasts)
    • Quakete energy transfers
    • ZEFCP fragments

Patent-Pending — Claims 30, 32
    Claim 30: "A method for generating a cryptographic heartbeat signal …"
    Claim 32: "A multi-step coherence gate that evaluates internal signals
               using heartbeat presence, pulse validity, history continuity,
               and originator provenance before permitting passage to the
               real processing layer."

© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.models.hive_defense import (
    GateDecision,
    HeartbeatPulse,
    MirrorSignal,
    ThreeCordVerification,
)
from app.services.security.heartbeat import HeartbeatRegistry, HeartbeatSignal

logger = logging.getLogger("hive.coherence_gate")


# =============================================================================
# GATE METRICS
# =============================================================================

@dataclass
class GateMetrics:
    """
    Running counters for Coherence Gate decisions.

    Exposed on the admin dashboard (SkyEye / The Eye) so Nathan can monitor
    the health of internal hive traffic at a glance.
    """
    total_evaluated: int = 0
    passed: int = 0
    absorbed: int = 0       # Step 1: no heartbeat
    contained: int = 0      # Step 2 / Step 4: invalid pulse or no registry entry
    suspicious: int = 0     # Step 3: continuity broken
    last_reset: float = field(default_factory=time.monotonic)

    # Per-entity counters (entity_id → count of rejections)
    rejections_by_entity: Dict[str, int] = field(default_factory=dict)

    def record(self, decision: GateDecision, entity_id: Optional[UUID] = None) -> None:
        """Record a gate decision in the metrics."""
        self.total_evaluated += 1
        if decision == GateDecision.PASS_TO_REAL:
            self.passed += 1
        elif decision == GateDecision.MIRROR_ABSORB:
            self.absorbed += 1
        elif decision == GateDecision.MIRROR_CONTAIN:
            self.contained += 1
        elif decision == GateDecision.MIRROR_SUSPICIOUS:
            self.suspicious += 1

        if decision != GateDecision.PASS_TO_REAL and entity_id is not None:
            eid_str = str(entity_id)
            self.rejections_by_entity[eid_str] = (
                self.rejections_by_entity.get(eid_str, 0) + 1
            )

    def reset(self) -> None:
        """Reset all counters (e.g., on a new monitoring window)."""
        self.total_evaluated = 0
        self.passed = 0
        self.absorbed = 0
        self.contained = 0
        self.suspicious = 0
        self.rejections_by_entity.clear()
        self.last_reset = time.monotonic()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON API responses."""
        uptime_sec = time.monotonic() - self.last_reset
        return {
            "total_evaluated": self.total_evaluated,
            "passed": self.passed,
            "absorbed": self.absorbed,
            "contained": self.contained,
            "suspicious": self.suspicious,
            "pass_rate": round(self.passed / max(self.total_evaluated, 1), 4),
            "reject_rate": round(
                (self.absorbed + self.contained + self.suspicious)
                / max(self.total_evaluated, 1),
                4,
            ),
            "uptime_seconds": round(uptime_sec, 1),
            "top_rejected_entities": dict(
                sorted(
                    self.rejections_by_entity.items(),
                    key=lambda kv: kv[1],
                    reverse=True,
                )[:10]
            ),
        }


# =============================================================================
# INTERNAL SIGNAL WRAPPER
# =============================================================================

@dataclass
class InternalSignal:
    """
    Wrapper for any signal traversing the internal hive mesh.

    Every Fibre-to-Fibre message, trail emission, Quakete transfer, and ZEFCP
    fragment is wrapped in this structure before entering the Coherence Gate.

    Fields:
        source_entity_id:  UUID of the entity that emitted the signal
                           (None for genuinely external / anonymous signals).
        signal_type:       Descriptive tag (e.g., "fibre_observation",
                           "trail_emission", "quakete_transfer", "zefcp_fragment").
        heartbeat:         The HeartbeatPulse attached to the signal.
                           If None, the signal will be absorbed at Step 1.
        payload:           The actual signal payload (opaque to the gate).
        metadata:          Any additional routing or contextual metadata.
    """
    source_entity_id: Optional[UUID] = None
    signal_type: str = ""
    heartbeat: Optional[HeartbeatPulse] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# GATE RESULT
# =============================================================================

@dataclass
class GateResult:
    """
    The full result of a Coherence Gate evaluation.

    Includes the decision, a human-readable reason, and the Three-Cord
    verification breakdown.
    """
    decision: GateDecision
    reason: str
    three_cord: Optional[ThreeCordVerification] = None
    step_failed: Optional[int] = None      # Which step (1-5) caused rejection
    evaluation_time_ns: int = 0            # Nanoseconds taken for evaluation


# =============================================================================
# COHERENCE GATE
# =============================================================================

class CoherenceGate:
    """
    Five-step signal evaluation gate for internal hive communications.

    The gate is stateless except for its reference to the HeartbeatRegistry
    and its running GateMetrics.  It makes a single, deterministic pass/fail
    decision for each signal.

    Usage::

        gate = CoherenceGate(heartbeat_registry=registry)

        # Evaluate an internal signal
        result = gate.evaluate(signal, system_state_hash="abc123...")

        if result.decision == GateDecision.PASS_TO_REAL:
            # Route to real processing
            ...
        else:
            # Route to Mirror Dimension
            mirror_engine.absorb(signal, result)

    Patent Ref: Claims 30, 32
    """

    def __init__(
        self,
        heartbeat_registry: HeartbeatRegistry,
        db_pool=None,
        max_missed_beats: int = 3,
    ):
        """
        Args:
            heartbeat_registry: The central HeartbeatRegistry containing all
                                known entity heartbeats.
            db_pool:            Optional asyncpg connection pool for persisting
                                gate decisions.
            max_missed_beats:   Continuity threshold — entities with more
                                consecutive missed beats fail Step 3.
        """
        self._registry: HeartbeatRegistry = heartbeat_registry
        self._db_pool = db_pool
        self._max_missed_beats: int = max_missed_beats
        self._metrics: GateMetrics = GateMetrics()

        # Optional callback for Mirror Dimension integration
        self._on_reject_callback = None

        logger.info(
            "CoherenceGate initialized (max_missed_beats=%d)",
            max_missed_beats,
        )

    # ── Properties ───────────────────────────────────────────────────────────

    @property
    def metrics(self) -> GateMetrics:
        """Access the running gate metrics."""
        return self._metrics

    @property
    def registry(self) -> HeartbeatRegistry:
        """Access the underlying HeartbeatRegistry."""
        return self._registry

    # ── Callbacks ────────────────────────────────────────────────────────────

    def set_reject_callback(self, callback) -> None:
        """
        Register a callback that fires on every non-PASS decision.

        The callback receives ``(signal: InternalSignal, result: GateResult)``.
        This is how the Mirror Dimension engine hooks into the gate.
        """
        self._on_reject_callback = callback

    # ── Core Evaluation ──────────────────────────────────────────────────────

    def evaluate(
        self,
        signal: InternalSignal,
        current_system_state_hash: str = "",
    ) -> GateResult:
        """
        Run the 5-step coherence evaluation on an internal signal.

        Args:
            signal:                    The InternalSignal to evaluate.
            current_system_state_hash: SHA-256 of the current global hive state,
                                       needed for HMAC pulse verification.

        Returns:
            GateResult with the decision and supporting detail.

        This method is synchronous and fast — designed to sit on the hot path
        of every internal message dispatch.

        Patent Ref: Claim 32 — multi-step coherence gate.
        """
        start_ns = time.monotonic_ns()
        entity_id = signal.source_entity_id

        # ── Step 1: Does the signal carry a heartbeat? ───────────────────
        if signal.heartbeat is None:
            result = GateResult(
                decision=GateDecision.MIRROR_ABSORB,
                reason="No heartbeat attached to signal",
                step_failed=1,
            )
            self._finalize(signal, result, start_ns)
            return result

        heartbeat = signal.heartbeat

        # ── Step 2: Is the heartbeat pulse valid for claimed identity? ───
        pulse_valid = HeartbeatSignal.verify_pulse(
            heartbeat,
            current_system_state_hash,
        )
        if not pulse_valid:
            result = GateResult(
                decision=GateDecision.MIRROR_CONTAIN,
                reason=(
                    f"Heartbeat pulse HMAC mismatch for entity {heartbeat.entity_id} "
                    f"at counter {heartbeat.monotonic_counter}"
                ),
                step_failed=2,
            )
            self._finalize(signal, result, start_ns)
            return result

        # ── Step 3: Is heartbeat consistent with entity's known history? ─
        if not self._registry.is_registered(heartbeat.entity_id):
            # Not even in registry — skip continuity, fail at step 4
            pass
        else:
            continuity_ok = self._registry.check_continuity(
                heartbeat.entity_id,
                max_missed=self._max_missed_beats,
            )
            if not continuity_ok:
                result = GateResult(
                    decision=GateDecision.MIRROR_SUSPICIOUS,
                    reason=(
                        f"Heartbeat continuity broken for entity {heartbeat.entity_id} "
                        f"(exceeded {self._max_missed_beats} missed beats)"
                    ),
                    step_failed=3,
                )
                self._finalize(signal, result, start_ns)
                return result

        # ── Step 4: Does entity exist in real registry? ──────────────────
        #            Verify originator signature (Ed25519 from Big Nate).
        if not self._registry.is_registered(heartbeat.entity_id):
            result = GateResult(
                decision=GateDecision.MIRROR_CONTAIN,
                reason=f"Entity {heartbeat.entity_id} not found in HeartbeatRegistry",
                step_failed=4,
            )
            self._finalize(signal, result, start_ns)
            return result

        originator_ok = self._registry.verify_originator(heartbeat.entity_id)
        if not originator_ok:
            result = GateResult(
                decision=GateDecision.MIRROR_CONTAIN,
                reason=(
                    f"Originator signature invalid for entity {heartbeat.entity_id} — "
                    "not signed by Big Nate's master key"
                ),
                step_failed=4,
            )
            self._finalize(signal, result, start_ns)
            return result

        # ── Step 5: All three cords agree → PASS_TO_REAL ────────────────
        three_cord = ThreeCordVerification(
            entity_id=heartbeat.entity_id,
            cord_real=True,          # Step 4 passed: entity in registry
            cord_mirror=True,        # Step 2 passed: pulse HMAC valid
            cord_originator=True,    # Step 4 passed: originator signature valid
            verified=True,
        )

        result = GateResult(
            decision=GateDecision.PASS_TO_REAL,
            reason="All five steps passed — three cords verified",
            three_cord=three_cord,
            step_failed=None,
        )

        # Update the registry's pulse record with the accepted pulse
        self._registry.update_pulse(
            heartbeat.entity_id,
            heartbeat,
            current_system_state_hash,
        )

        self._finalize(signal, result, start_ns)
        return result

    # ── Batch Evaluation ─────────────────────────────────────────────────────

    def evaluate_batch(
        self,
        signals: List[InternalSignal],
        current_system_state_hash: str = "",
    ) -> List[GateResult]:
        """
        Evaluate multiple signals in sequence.

        Useful for processing a batch of queued internal messages after
        a brief outage or during high-traffic periods.

        Args:
            signals:                   List of InternalSignals.
            current_system_state_hash: Global system state hash.

        Returns:
            List of GateResults, one per signal, in the same order.
        """
        return [
            self.evaluate(sig, current_system_state_hash)
            for sig in signals
        ]

    # ── External API Bypass Check ────────────────────────────────────────────

    @staticmethod
    def is_external_api_request(signal: InternalSignal) -> bool:
        """
        Determine whether a signal originates from an external API request
        (JWT-authenticated member or coach) rather than an internal hive entity.

        External signals are identified by the ``signal_type`` being one of
        the recognized external types.  These bypass the Coherence Gate and
        are handled by standard FastAPI JWT middleware instead.

        Args:
            signal: The signal to classify.

        Returns:
            True if the signal should bypass the gate.
        """
        EXTERNAL_TYPES = frozenset({
            "api_request",
            "webhook",
            "client_websocket",
            "coach_websocket",
            "admin_request",
        })
        return signal.signal_type in EXTERNAL_TYPES

    # ── Mirror Signal Construction ───────────────────────────────────────────

    @staticmethod
    def build_mirror_signal(
        signal: InternalSignal,
        result: GateResult,
        namespace_id: UUID,
    ) -> MirrorSignal:
        """
        Construct a MirrorSignal record for a rejected signal.

        This is used by the Mirror Dimension engine to catalog absorbed /
        contained / suspicious traffic for forensic analysis.

        Args:
            signal:       The original InternalSignal that was rejected.
            result:       The GateResult with the rejection reason.
            namespace_id: The Mirror namespace this signal will be stored in.

        Returns:
            A MirrorSignal Pydantic model ready for persistence.
        """
        import hashlib as _hashlib
        import json as _json

        payload_hash = _hashlib.sha256(
            _json.dumps(signal.payload, sort_keys=True, default=str).encode()
        ).hexdigest()

        return MirrorSignal(
            namespace_id=namespace_id,
            source_address=str(signal.source_entity_id or "unknown"),
            signal_type=signal.signal_type,
            payload_hash=payload_hash,
            gate_decision=result.decision,
            metadata={
                "reason": result.reason,
                "step_failed": result.step_failed,
                "evaluation_time_ns": result.evaluation_time_ns,
                "signal_metadata": signal.metadata,
            },
        )

    # ── Admin Summary ────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """
        Return a combined summary of gate metrics and registry health.

        Designed for the SkyEye / admin dashboard.
        """
        return {
            "gate_metrics": self._metrics.to_dict(),
            "registry_summary": self._registry.summary(),
            "max_missed_beats": self._max_missed_beats,
        }

    # ── Persistence ──────────────────────────────────────────────────────────

    async def persist_decision(
        self,
        signal: InternalSignal,
        result: GateResult,
    ) -> None:
        """
        Persist a gate decision to the database for audit trail.

        Only non-PASS decisions are persisted to avoid write amplification.
        PASS decisions are tracked in metrics only.
        """
        if not self._db_pool:
            return
        if result.decision == GateDecision.PASS_TO_REAL:
            return  # Only persist rejections

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_gate_decisions (
                        entity_id, signal_type, decision, reason,
                        step_failed, evaluation_time_ns, recorded_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, NOW())
                    """,
                    signal.source_entity_id,
                    signal.signal_type,
                    result.decision.value,
                    result.reason,
                    result.step_failed,
                    result.evaluation_time_ns,
                )
        except Exception as exc:
            logger.error("Failed to persist gate decision: %s", exc)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _finalize(
        self,
        signal: InternalSignal,
        result: GateResult,
        start_ns: int,
    ) -> None:
        """
        Finalize a gate evaluation:
            1. Stamp evaluation time.
            2. Record metrics.
            3. Log the decision.
            4. Fire rejection callback if applicable.
        """
        result.evaluation_time_ns = time.monotonic_ns() - start_ns

        entity_id = (
            signal.heartbeat.entity_id
            if signal.heartbeat
            else signal.source_entity_id
        )
        self._metrics.record(result.decision, entity_id)

        if result.decision == GateDecision.PASS_TO_REAL:
            logger.debug(
                "PASS entity=%s type=%s (%d ns)",
                entity_id,
                signal.signal_type,
                result.evaluation_time_ns,
            )
        else:
            logger.warning(
                "%s entity=%s type=%s step=%s reason=%s (%d ns)",
                result.decision.value.upper(),
                entity_id,
                signal.signal_type,
                result.step_failed,
                result.reason,
                result.evaluation_time_ns,
            )

            # Fire rejection callback (Mirror Dimension hook)
            if self._on_reject_callback:
                try:
                    self._on_reject_callback(signal, result)
                except Exception as exc:
                    logger.error("Reject callback error: %s", exc)
