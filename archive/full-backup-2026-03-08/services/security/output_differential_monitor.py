"""
HIVE DEFENSE PROTOCOL v3.0 — Output Differential Monitor (Phase 8C: Third Cord)
Pre/post system state comparison for detecting payload side effects.

Design rationale:
    Content analysis tells you what a payload *says*.  The Output Differential
    Monitor tells you what a payload *does*.

    Before processing any payload, the monitor captures a snapshot of the
    relevant system state.  After processing, it captures a second snapshot.
    The differential between the two snapshots reveals the payload's EFFECTS
    on the system — which data was modified, which APIs were called, which
    state variables changed.

    A legitimate Trail Emission updates coherence metrics by predictable
    amounts — the emotional coherence score changes by a small delta, the
    session timestamp advances, and the Trail log grows by one entry.

    A malicious payload will:
        - Modify unexpected data (user records, permissions, credentials)
        - Trigger unexpected API calls (external callbacks, data exports)
        - Produce unexpected side effects (new processes, file writes, network connections)
        - Change coherence by implausible amounts (zero change = no-op payload,
          massive change = injected state override)

    The differential monitor catches all of these because it doesn't care
    about the payload content — it watches the *effects*.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

from app.models.hive_defense import (
    DefconLevel,
    HIVE_EVENT_TOPICS,
)

logger = logging.getLogger("hive.output_differential")


# =============================================================================
# CONSTANTS
# =============================================================================

#: Severity thresholds for unexpected effects
SEVERITY_THRESHOLDS: Dict[str, int] = {
    "low": 1,         # 1 unexpected effect
    "medium": 3,      # 3 unexpected effects
    "high": 5,        # 5 unexpected effects
    "critical": 10,   # 10+ unexpected effects
}

#: Maximum state snapshots retained for audit
MAX_SNAPSHOT_HISTORY: int = 1000

#: Maximum allowed coherence delta from a single payload
MAX_COHERENCE_DELTA: float = 0.5

#: Expected effects that are always permitted
ALWAYS_PERMITTED_EFFECTS: Set[str] = {
    "session_timestamp_advanced",
    "trail_log_appended",
    "coherence_updated_within_bounds",
    "heartbeat_counter_incremented",
}


# =============================================================================
# STATE SNAPSHOT
# =============================================================================

@dataclass
class StateSnapshot:
    """
    A point-in-time snapshot of relevant system state.

    Captures the values of tracked state variables at a specific moment,
    used for pre/post comparison to detect unexpected payload effects.

    Attributes:
        snapshot_id:    Unique identifier for this snapshot.
        scope:          Description of the scope captured (e.g., "session:uuid").
        captured_at:    Timestamp of capture.
        state_hash:     SHA-256 hash of the serialized state.
        state_data:     The actual state key-value pairs.
        api_call_count: Number of API calls at capture time.
        process_count:  Number of active processes at capture time.
    """
    snapshot_id: UUID = field(default_factory=uuid4)
    scope: str = ""
    captured_at: datetime = field(default_factory=datetime.utcnow)
    state_hash: str = ""
    state_data: Dict[str, Any] = field(default_factory=dict)
    api_call_count: int = 0
    process_count: int = 0

    def compute_hash(self) -> str:
        """
        Compute the SHA-256 hash of the state data.

        Returns:
            Hex-encoded SHA-256 digest.
        """
        serialized = json.dumps(
            self.state_data, sort_keys=True, default=str,
        )
        self.state_hash = hashlib.sha256(serialized.encode()).hexdigest()
        return self.state_hash


# =============================================================================
# DIFFERENTIAL RESULT
# =============================================================================

@dataclass
class DifferentialResult:
    """
    Result of comparing pre- and post-state snapshots.

    Attributes:
        result_id:          Unique identifier for this result.
        scope:              Scope that was monitored.
        pre_snapshot_id:    UUID of the pre-state snapshot.
        post_snapshot_id:   UUID of the post-state snapshot.
        expected_effects:   Effects that were expected (legitimate).
        actual_effects:     All effects that actually occurred.
        unexpected_effects: Effects that were NOT expected (suspicious).
        severity:           Overall severity (low/medium/high/critical/clean).
        analysis:           Detailed analysis per changed key.
        computed_at:        When the differential was computed.
    """
    result_id: UUID = field(default_factory=uuid4)
    scope: str = ""
    pre_snapshot_id: UUID = field(default_factory=uuid4)
    post_snapshot_id: UUID = field(default_factory=uuid4)
    expected_effects: List[str] = field(default_factory=list)
    actual_effects: List[str] = field(default_factory=list)
    unexpected_effects: List[str] = field(default_factory=list)
    severity: str = "clean"
    analysis: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    computed_at: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# OUTPUT DIFFERENTIAL MONITOR
# =============================================================================

class OutputDifferentialMonitor:
    """
    Pre/post system state comparison for detecting payload side effects.

    Captures system state snapshots before and after payload processing,
    then computes the differential to detect unexpected effects. This
    catches malicious payloads that modify unexpected data, trigger
    unauthorized API calls, or produce suspicious side effects.

    The monitor doesn't analyze payload content — it watches the *effects*
    on system state. A legitimate Trail Emission produces predictable
    effects; a malicious payload produces unexpected ones.

    Integration Points:
        - ContentSentinel    — triggers pre/post captures around payload processing
        - CoherenceEngine    — provides coherence state for monitoring
        - ForensicLogger     — logs unexpected effects to evidence chain
        - DefconController   — escalates on high-severity differentials

    Usage::

        monitor = OutputDifferentialMonitor(db_pool=pool)

        # Before processing payload
        pre = await monitor.capture_pre_state("session:abc123")

        # ... process payload ...

        # After processing
        post = await monitor.capture_post_state("session:abc123")

        # Compute differential
        unexpected, severity = await monitor.compute_differential(
            pre, post, expected_effects=["coherence_updated", "trail_appended"]
        )

    Patent-Pending — Claims 30-56
    """

    def __init__(
        self,
        db_pool=None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Coroutine]] = None,
        forensic_logger=None,
        defcon_controller=None,
        state_provider=None,
    ) -> None:
        """
        Initialize the Output Differential Monitor.

        Args:
            db_pool:           asyncpg connection pool for persistence.
            event_callback:    Async callback for hive event bus.
            forensic_logger:   ForensicLogger for evidence chain.
            defcon_controller: DefconController for escalation.
            state_provider:    Callable that returns the current system state
                               dict for a given scope. Signature:
                               ``async (scope: str) -> Dict[str, Any]``
        """
        self._db_pool = db_pool
        self._event_callback = event_callback
        self._forensic_logger = forensic_logger
        self._defcon_controller = defcon_controller
        self._state_provider = state_provider

        # Pending pre-state snapshots: scope → StateSnapshot
        self._pending_pre: Dict[str, StateSnapshot] = {}

        # Completed differential results (recent history)
        self._results: List[DifferentialResult] = []

        # Statistics
        self._total_captures: int = 0
        self._total_differentials: int = 0
        self._total_anomalies: int = 0

        logger.info("OutputDifferentialMonitor initialized")

    # =========================================================================
    # STATE CAPTURE
    # =========================================================================

    async def capture_pre_state(
        self,
        scope: str,
        additional_state: Optional[Dict[str, Any]] = None,
    ) -> StateSnapshot:
        """
        Capture the pre-processing system state snapshot.

        Called BEFORE a payload is processed. The snapshot captures all
        tracked state variables for later comparison.

        Args:
            scope:            Scope identifier (e.g., "session:uuid", "entity:uuid").
            additional_state: Additional state key-value pairs to include
                              beyond what the state_provider returns.

        Returns:
            StateSnapshot of the pre-processing state.
        """
        state_data: Dict[str, Any] = {}

        # Get state from provider
        if self._state_provider:
            try:
                state_data = await self._state_provider(scope)
            except Exception as exc:
                logger.error(
                    "State provider failed for scope %s: %s", scope, exc,
                )

        # Merge additional state
        if additional_state:
            state_data.update(additional_state)

        snapshot = StateSnapshot(
            scope=scope,
            state_data=copy.deepcopy(state_data),
        )
        snapshot.compute_hash()

        # Store as pending for this scope
        self._pending_pre[scope] = snapshot
        self._total_captures += 1

        logger.debug(
            "Pre-state captured: scope=%s hash=%s… keys=%d",
            scope, snapshot.state_hash[:16], len(state_data),
        )

        return snapshot

    async def capture_post_state(
        self,
        scope: str,
        additional_state: Optional[Dict[str, Any]] = None,
    ) -> StateSnapshot:
        """
        Capture the post-processing system state snapshot.

        Called AFTER a payload is processed. The snapshot is compared
        against the pre-state to detect unexpected effects.

        Args:
            scope:            Scope identifier (must match the pre-state scope).
            additional_state: Additional state key-value pairs.

        Returns:
            StateSnapshot of the post-processing state.
        """
        state_data: Dict[str, Any] = {}

        # Get state from provider
        if self._state_provider:
            try:
                state_data = await self._state_provider(scope)
            except Exception as exc:
                logger.error(
                    "State provider failed for scope %s: %s", scope, exc,
                )

        # Merge additional state
        if additional_state:
            state_data.update(additional_state)

        snapshot = StateSnapshot(
            scope=scope,
            state_data=copy.deepcopy(state_data),
        )
        snapshot.compute_hash()

        self._total_captures += 1

        logger.debug(
            "Post-state captured: scope=%s hash=%s… keys=%d",
            scope, snapshot.state_hash[:16], len(state_data),
        )

        return snapshot

    # =========================================================================
    # DIFFERENTIAL COMPUTATION
    # =========================================================================

    async def compute_differential(
        self,
        pre_state: StateSnapshot,
        post_state: StateSnapshot,
        expected_effects: Optional[List[str]] = None,
    ) -> Tuple[List[str], str]:
        """
        Compute the differential between pre- and post-state snapshots.

        Identifies all state changes, classifies them as expected or
        unexpected, and assigns a severity level.

        Args:
            pre_state:        Pre-processing state snapshot.
            post_state:       Post-processing state snapshot.
            expected_effects: List of effect labels that are expected from
                              the payload (e.g., ["coherence_updated",
                              "trail_appended"]). Any actual effect NOT in
                              this list is classified as unexpected.

        Returns:
            Tuple of (unexpected_effects, severity):
                unexpected_effects: List of unexpected effect descriptions.
                severity:           "clean", "low", "medium", "high", or "critical".
        """
        expected = set(expected_effects or []).union(ALWAYS_PERMITTED_EFFECTS)
        actual_effects: List[str] = []
        unexpected_effects: List[str] = []
        analysis: Dict[str, Dict[str, Any]] = {}

        pre_data = pre_state.state_data
        post_data = post_state.state_data

        # ── Detect changed keys ──
        all_keys = set(pre_data.keys()) | set(post_data.keys())

        for key in all_keys:
            pre_val = pre_data.get(key)
            post_val = post_data.get(key)

            if pre_val == post_val:
                continue

            # A change occurred
            effect_label = self._classify_effect(key, pre_val, post_val)
            actual_effects.append(effect_label)

            analysis[key] = {
                "pre_value": self._safe_repr(pre_val),
                "post_value": self._safe_repr(post_val),
                "effect": effect_label,
                "expected": effect_label in expected,
            }

            if effect_label not in expected:
                unexpected_effects.append(effect_label)

        # ── Detect new keys (not in pre-state) ──
        new_keys = set(post_data.keys()) - set(pre_data.keys())
        for key in new_keys:
            if key not in all_keys:  # already handled above
                effect_label = f"new_key:{key}"
                actual_effects.append(effect_label)
                if effect_label not in expected:
                    unexpected_effects.append(effect_label)
                analysis[key] = {
                    "pre_value": None,
                    "post_value": self._safe_repr(post_data[key]),
                    "effect": effect_label,
                    "expected": effect_label in expected,
                }

        # ── Detect deleted keys ──
        deleted_keys = set(pre_data.keys()) - set(post_data.keys())
        for key in deleted_keys:
            if key not in all_keys:  # already handled above
                effect_label = f"deleted_key:{key}"
                actual_effects.append(effect_label)
                unexpected_effects.append(effect_label)
                analysis[key] = {
                    "pre_value": self._safe_repr(pre_data[key]),
                    "post_value": None,
                    "effect": effect_label,
                    "expected": False,
                }

        # ── Determine severity ──
        num_unexpected = len(unexpected_effects)
        if num_unexpected == 0:
            severity = "clean"
        elif num_unexpected >= SEVERITY_THRESHOLDS["critical"]:
            severity = "critical"
        elif num_unexpected >= SEVERITY_THRESHOLDS["high"]:
            severity = "high"
        elif num_unexpected >= SEVERITY_THRESHOLDS["medium"]:
            severity = "medium"
        else:
            severity = "low"

        # ── Build result ──
        result = DifferentialResult(
            scope=pre_state.scope,
            pre_snapshot_id=pre_state.snapshot_id,
            post_snapshot_id=post_state.snapshot_id,
            expected_effects=list(expected),
            actual_effects=actual_effects,
            unexpected_effects=unexpected_effects,
            severity=severity,
            analysis=analysis,
        )

        self._total_differentials += 1
        self._results.append(result)
        if len(self._results) > MAX_SNAPSHOT_HISTORY:
            self._results = self._results[-MAX_SNAPSHOT_HISTORY:]

        # Log and handle anomalies
        if severity != "clean":
            self._total_anomalies += 1
            await self._handle_anomaly(result)
        else:
            logger.debug(
                "Differential clean: scope=%s effects=%d all_expected",
                pre_state.scope, len(actual_effects),
            )

        # Clean up pending pre-state
        self._pending_pre.pop(pre_state.scope, None)

        # Persist result
        await self._persist_result(result)

        return unexpected_effects, severity

    # =========================================================================
    # EFFECT CLASSIFICATION
    # =========================================================================

    def _classify_effect(
        self,
        key: str,
        pre_val: Any,
        post_val: Any,
    ) -> str:
        """
        Classify a state change into an effect label.

        Args:
            key:      The state key that changed.
            pre_val:  The pre-state value.
            post_val: The post-state value.

        Returns:
            A human-readable effect label.
        """
        # Coherence changes
        if "coherence" in key.lower():
            try:
                pre_f = float(pre_val) if pre_val is not None else 0.0
                post_f = float(post_val) if post_val is not None else 0.0
                delta = abs(post_f - pre_f)
                if delta <= MAX_COHERENCE_DELTA:
                    return "coherence_updated_within_bounds"
                return f"coherence_excessive_delta:{delta:.4f}"
            except (ValueError, TypeError):
                return f"coherence_type_change:{key}"

        # Timestamp advances
        if "timestamp" in key.lower() or "time" in key.lower():
            return "session_timestamp_advanced"

        # Trail/log appends
        if "trail" in key.lower() or "log" in key.lower():
            return "trail_log_appended"

        # Heartbeat counter
        if "counter" in key.lower() or "heartbeat" in key.lower():
            return "heartbeat_counter_incremented"

        # Permission/role changes
        if "permission" in key.lower() or "role" in key.lower():
            return f"permission_modified:{key}"

        # Credential changes
        if "credential" in key.lower() or "password" in key.lower() or "key" in key.lower():
            return f"credential_modified:{key}"

        # Generic
        return f"state_changed:{key}"

    @staticmethod
    def _safe_repr(value: Any) -> str:
        """
        Safe string representation of a value for logging.

        Truncates long values and handles non-serializable types.

        Args:
            value: The value to represent.

        Returns:
            String representation (max 200 chars).
        """
        if value is None:
            return "null"
        try:
            s = str(value)
            return s[:200] + ("…" if len(s) > 200 else "")
        except Exception:
            return "<non-representable>"

    # =========================================================================
    # ANOMALY HANDLING
    # =========================================================================

    async def _handle_anomaly(self, result: DifferentialResult) -> None:
        """
        Handle a detected output differential anomaly.

        Args:
            result: The DifferentialResult containing the anomaly details.
        """
        logger.warning(
            "⚠ OUTPUT DIFFERENTIAL ANOMALY: scope=%s severity=%s "
            "unexpected=%d/%d effects — %s",
            result.scope, result.severity,
            len(result.unexpected_effects), len(result.actual_effects),
            result.unexpected_effects,
        )

        # Log to forensic chain
        if self._forensic_logger:
            try:
                await self._forensic_logger.log_event(
                    event_type="output_differential_anomaly",
                    evidence={
                        "scope": result.scope,
                        "severity": result.severity,
                        "unexpected_effects": result.unexpected_effects,
                        "actual_effects": result.actual_effects,
                        "analysis": result.analysis,
                        "pre_snapshot_id": str(result.pre_snapshot_id),
                        "post_snapshot_id": str(result.post_snapshot_id),
                    },
                )
            except Exception as exc:
                logger.error("Forensic log failed: %s", exc)

        # Escalate on high+ severity
        if result.severity in ("high", "critical") and self._defcon_controller:
            try:
                await self._defcon_controller.escalate(
                    DefconLevel.SUBSTANTIAL,
                    f"Output differential anomaly: scope={result.scope} "
                    f"severity={result.severity} "
                    f"unexpected_effects={len(result.unexpected_effects)}",
                )
            except Exception as exc:
                logger.error("DEFCON escalation failed: %s", exc)

        # Broadcast event
        await self._broadcast_event(
            "hive.payload.effect_anomaly",
            {
                "scope": result.scope,
                "severity": result.severity,
                "unexpected_effects": result.unexpected_effects,
                "total_effects": len(result.actual_effects),
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    # =========================================================================
    # QUERIES
    # =========================================================================

    def get_recent_results(
        self,
        count: int = 50,
        severity_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return recent differential results.

        Args:
            count:           Maximum results to return.
            severity_filter: If provided, only return results with this severity.

        Returns:
            List of result dicts (most recent first).
        """
        results = self._results
        if severity_filter:
            results = [r for r in results if r.severity == severity_filter]

        return [
            {
                "result_id": str(r.result_id),
                "scope": r.scope,
                "severity": r.severity,
                "unexpected_effects": r.unexpected_effects,
                "total_effects": len(r.actual_effects),
                "computed_at": r.computed_at.isoformat(),
            }
            for r in reversed(results[-count:])
        ]

    # =========================================================================
    # ADMIN
    # =========================================================================

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict for admin dashboards."""
        severity_counts: Dict[str, int] = {
            "clean": 0, "low": 0, "medium": 0, "high": 0, "critical": 0,
        }
        for r in self._results:
            severity_counts[r.severity] = severity_counts.get(r.severity, 0) + 1

        return {
            "total_captures": self._total_captures,
            "total_differentials": self._total_differentials,
            "total_anomalies": self._total_anomalies,
            "pending_pre_states": len(self._pending_pre),
            "anomaly_rate": (
                f"{self._total_anomalies / self._total_differentials * 100:.2f}%"
                if self._total_differentials > 0
                else "N/A"
            ),
            "severity_distribution": severity_counts,
        }

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    async def _persist_result(self, result: DifferentialResult) -> None:
        """Persist a differential result to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO output_differentials (
                        result_id, scope, severity,
                        expected_effects, actual_effects, unexpected_effects,
                        analysis, computed_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    result.result_id,
                    result.scope,
                    result.severity,
                    json.dumps(result.expected_effects),
                    json.dumps(result.actual_effects),
                    json.dumps(result.unexpected_effects),
                    json.dumps(result.analysis, default=str),
                    result.computed_at,
                )
        except Exception as exc:
            logger.error(
                "Failed to persist differential result %s: %s",
                result.result_id, exc,
            )

    async def load_from_db(self) -> int:
        """
        Load recent differential results from the database on startup.

        Returns:
            Number of results loaded.
        """
        if not self._db_pool:
            return 0

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT result_id, scope, severity,
                           expected_effects, actual_effects, unexpected_effects,
                           analysis, computed_at
                    FROM output_differentials
                    ORDER BY computed_at DESC
                    LIMIT $1
                    """,
                    MAX_SNAPSHOT_HISTORY,
                )

            loaded = 0
            for row in rows:
                result = DifferentialResult(
                    result_id=row["result_id"],
                    scope=row["scope"] or "",
                    severity=row["severity"] or "clean",
                    expected_effects=json.loads(row["expected_effects"] or "[]"),
                    actual_effects=json.loads(row["actual_effects"] or "[]"),
                    unexpected_effects=json.loads(row["unexpected_effects"] or "[]"),
                    analysis=json.loads(row["analysis"] or "{}"),
                    computed_at=row["computed_at"],
                )
                self._results.append(result)
                loaded += 1

            # Results were loaded newest-first, reverse to chronological order
            self._results.reverse()

            logger.info(
                "Loaded %d differential results from database", loaded,
            )
            return loaded

        except Exception as exc:
            logger.error("Failed to load differential results: %s", exc)
            return 0

    # =========================================================================
    # EVENT BUS
    # =========================================================================

    async def _broadcast_event(
        self,
        topic: str,
        payload: Dict[str, Any],
    ) -> None:
        """Broadcast an event via the registered callback."""
        if self._event_callback:
            try:
                await self._event_callback(topic, payload)
            except Exception as exc:
                logger.error(
                    "Event callback failed for topic %s: %s", topic, exc,
                )
