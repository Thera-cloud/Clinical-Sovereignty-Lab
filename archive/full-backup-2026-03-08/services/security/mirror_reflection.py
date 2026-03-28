"""
HIVE DEFENSE PROTOCOL — Phase 8A: Mirror Reflection System
Behavioral baseline management for every entity in the hive.

The Mirror Reflection is the second cord — the projection that faces
the outside world. For every entity born inside the hive, a Mirror
Reflection is maintained: a cryptographic snapshot of what the entity
SHOULD look like. Its heartbeat rhythm, its communication patterns,
its data access fingerprint, its coherence baseline, its journal
trajectory, and its trail emission signature.

When current behavior diverges from the reflection, the Curiosity
Protocol activates. Small divergence is natural (entities evolve).
Large divergence is suspicious. Sudden divergence is alarming.

Six divergence dimensions are tracked:
    1. Heartbeat Continuity   — Is the heartbeat rhythm consistent?
    2. Journal Trajectory     — Is the evolution journal growing naturally?
    3. Communication Pattern  — Is the entity talking to expected peers?
    4. Data Access Pattern    — Is the entity accessing expected resources?
    5. Coherence Drift        — Has the entity's emotional coherence shifted?
    6. Trail Emission Anomaly — Is the trail signature consistent?

Patent-Pending — Claim 30
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from app.models.hive_defense import (
    CuriosityLevel,
    ForensicRecord,
    MirrorReflection,
)

logger = logging.getLogger("hive.mirror_reflection")


# =============================================================================
# DIVERGENCE TYPES
# =============================================================================

DIVERGENCE_HEARTBEAT_CONTINUITY = "heartbeat_continuity"
DIVERGENCE_JOURNAL_TRAJECTORY = "journal_trajectory"
DIVERGENCE_COMMUNICATION_PATTERN = "communication_pattern"
DIVERGENCE_DATA_ACCESS_PATTERN = "data_access_pattern"
DIVERGENCE_COHERENCE_DRIFT = "coherence_drift"
DIVERGENCE_TRAIL_EMISSION_ANOMALY = "trail_emission_anomaly"

ALL_DIVERGENCE_TYPES = [
    DIVERGENCE_HEARTBEAT_CONTINUITY,
    DIVERGENCE_JOURNAL_TRAJECTORY,
    DIVERGENCE_COMMUNICATION_PATTERN,
    DIVERGENCE_DATA_ACCESS_PATTERN,
    DIVERGENCE_COHERENCE_DRIFT,
    DIVERGENCE_TRAIL_EMISSION_ANOMALY,
]


# =============================================================================
# DIVERGENCE RESULT
# =============================================================================

class DivergenceResult:
    """
    The result of comparing an entity's current behavior against its
    Mirror Reflection baseline.

    Attributes:
        entity_id: The entity that was compared.
        divergence_score: Combined magnitude of all divergence vectors (0.0–1.0+).
        divergence_types: List of specific divergence categories that were flagged.
        dimension_scores: Per-dimension divergence scores.
        curiosity_level: The recommended Curiosity Protocol escalation level.
        timestamp: When the comparison was performed.
    """

    def __init__(
        self,
        entity_id: UUID,
        divergence_score: float,
        divergence_types: List[str],
        dimension_scores: Dict[str, float],
    ) -> None:
        self.entity_id = entity_id
        self.divergence_score = divergence_score
        self.divergence_types = divergence_types
        self.dimension_scores = dimension_scores
        self.curiosity_level = self._compute_curiosity_level()
        self.timestamp = datetime.utcnow()

    def _compute_curiosity_level(self) -> CuriosityLevel:
        """
        Map combined divergence score to a Curiosity Protocol level.

        Thresholds (calibrated through operational experience):
            < 0.15  → NONE      — Normal operational variance.
            < 0.30  → NOTICE    — Single anomaly; 24h passive monitoring.
            < 0.50  → INTEREST  — Multiple anomalies; 72h ring cross-verify.
            < 0.75  → CONCERN   — Ring confirms divergence; Three-Cord Verification.
            ≥ 0.75  → ALARM    — Three-Cord failure; mesh isolation + alert Nathan.
        """
        score = self.divergence_score
        if score < 0.15:
            return CuriosityLevel.NONE
        elif score < 0.30:
            return CuriosityLevel.NOTICE
        elif score < 0.50:
            return CuriosityLevel.INTEREST
        elif score < 0.75:
            return CuriosityLevel.CONCERN
        else:
            return CuriosityLevel.ALARM

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage or API response."""
        return {
            "entity_id": str(self.entity_id),
            "divergence_score": round(self.divergence_score, 6),
            "divergence_types": self.divergence_types,
            "dimension_scores": {
                k: round(v, 6) for k, v in self.dimension_scores.items()
            },
            "curiosity_level": self.curiosity_level.value,
            "timestamp": self.timestamp.isoformat(),
        }

    def __repr__(self) -> str:
        return (
            f"<DivergenceResult entity={self.entity_id} "
            f"score={self.divergence_score:.4f} "
            f"types={self.divergence_types} "
            f"curiosity={self.curiosity_level.value}>"
        )


# =============================================================================
# BEHAVIORAL VECTOR — Internal representation
# =============================================================================

class _BehavioralVector:
    """
    Internal representation of an entity's behavioral state across
    the six monitored dimensions.

    Each dimension is stored as a SHA-256 hash of the raw behavioral
    data, enabling efficient comparison without retaining sensitive
    raw data in memory.
    """

    __slots__ = (
        "heartbeat_hash",
        "journal_hash",
        "communication_hash",
        "data_access_hash",
        "coherence_hash",
        "trail_emission_hash",
        "raw_metrics",
        "captured_at",
    )

    def __init__(
        self,
        heartbeat_hash: str = "",
        journal_hash: str = "",
        communication_hash: str = "",
        data_access_hash: str = "",
        coherence_hash: str = "",
        trail_emission_hash: str = "",
        raw_metrics: Optional[Dict[str, float]] = None,
    ) -> None:
        self.heartbeat_hash = heartbeat_hash
        self.journal_hash = journal_hash
        self.communication_hash = communication_hash
        self.data_access_hash = data_access_hash
        self.coherence_hash = coherence_hash
        self.trail_emission_hash = trail_emission_hash
        self.raw_metrics = raw_metrics or {}
        self.captured_at = datetime.utcnow()

    @staticmethod
    def hash_dimension(data: Any) -> str:
        """
        Compute a SHA-256 hash of a behavioral dimension's data.

        The data is serialized to a canonical string form before hashing,
        ensuring deterministic results regardless of dict ordering.
        """
        canonical = str(sorted(data.items()) if isinstance(data, dict) else data)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_reflection(self, entity_id: UUID) -> MirrorReflection:
        """Convert this vector to a MirrorReflection model instance."""
        return MirrorReflection(
            entity_id=entity_id,
            data_access_hash=self.data_access_hash,
            communication_graph_hash=self.communication_hash,
            trail_emission_fingerprint=self.trail_emission_hash,
            coherence_baseline_hash=self.coherence_hash,
            journal_trajectory_hash=self.journal_hash,
            snapshot_timestamp=self.captured_at,
        )


# =============================================================================
# MIRROR REFLECTION MANAGER
# =============================================================================

class MirrorReflectionManager:
    """
    Maintains per-entity behavioral baselines and compares current behavior
    against those baselines to detect divergence.

    The reflection system is the hive's immune memory — it remembers what
    every entity SHOULD look like, so it can detect when something has
    changed. Natural evolution updates the baseline gradually. Sudden
    shifts trigger the Curiosity Protocol.

    Usage:
        manager = MirrorReflectionManager()
        await manager.create_reflection(entity_id, birth_params)
        ...
        result = await manager.compare_reflection(entity_id, current_behavior)
        if result.curiosity_level >= CuriosityLevel.CONCERN:
            # Escalate to Three-Cord Verification
            ...
    """

    # ── Class-level constants ────────────────────────────────────────────

    PATENT_CLAIM = 30

    # Divergence thresholds per dimension (hash mismatch = 1.0, match = 0.0)
    # Metric-based dimensions use continuous scores
    HASH_MISMATCH_WEIGHT = 0.20  # Weight when a hash dimension fully mismatches
    METRIC_SENSITIVITY = 0.25     # Sensitivity for continuous-metric dimensions

    # Persistence interval (seconds)
    PERSISTENCE_INTERVAL_SEC = 300  # 5 minutes

    def __init__(self, forensic_logger: Optional[Any] = None) -> None:
        """
        Initialize the Mirror Reflection Manager.

        Args:
            forensic_logger: Optional ForensicLogger for recording divergence
                             events into the immutable forensic chain.
        """
        self._reflections: Dict[UUID, _BehavioralVector] = {}
        self._observation_history: Dict[UUID, List[_BehavioralVector]] = {}
        self._forensic = forensic_logger
        self._last_persistence: float = time.monotonic()
        self._comparison_count: int = 0
        self._divergence_events: int = 0

        logger.info(
            "MirrorReflectionManager initialized (patent claim %d)",
            self.PATENT_CLAIM,
        )

    # ── Reflection lifecycle ─────────────────────────────────────────────

    async def create_reflection(
        self,
        entity_id: UUID,
        birth_parameters: Dict[str, Any],
    ) -> MirrorReflection:
        """
        Build the initial behavioral baseline for a newly born entity.

        The birth parameters establish the entity's identity anchor — the
        behavioral 'zero point' against which all future behavior is measured.

        Args:
            entity_id: The unique identifier of the entity.
            birth_parameters: Dictionary containing initial behavioral data:
                - 'heartbeat_data': Initial heartbeat rhythm parameters.
                - 'journal_state': Initial evolution journal state.
                - 'communication_peers': Initial expected communication peers.
                - 'data_access_scope': Initial data access scope.
                - 'coherence_state': Initial emotional coherence parameters.
                - 'trail_signature': Initial trail emission signature.

        Returns:
            The created MirrorReflection model instance.

        Raises:
            ValueError: If entity_id already has a reflection (use update instead).
        """
        if entity_id in self._reflections:
            raise ValueError(
                f"Reflection already exists for entity {entity_id}. "
                f"Use update_reflection() to modify."
            )

        vector = _BehavioralVector(
            heartbeat_hash=_BehavioralVector.hash_dimension(
                birth_parameters.get("heartbeat_data", {})
            ),
            journal_hash=_BehavioralVector.hash_dimension(
                birth_parameters.get("journal_state", {})
            ),
            communication_hash=_BehavioralVector.hash_dimension(
                birth_parameters.get("communication_peers", [])
            ),
            data_access_hash=_BehavioralVector.hash_dimension(
                birth_parameters.get("data_access_scope", {})
            ),
            coherence_hash=_BehavioralVector.hash_dimension(
                birth_parameters.get("coherence_state", {})
            ),
            trail_emission_hash=_BehavioralVector.hash_dimension(
                birth_parameters.get("trail_signature", {})
            ),
            raw_metrics=self._extract_metrics(birth_parameters),
        )

        self._reflections[entity_id] = vector
        self._observation_history[entity_id] = [vector]

        reflection = vector.to_reflection(entity_id)

        logger.info(
            "Reflection created for entity %s — baseline established "
            "(heartbeat=%s..., journal=%s..., coherence=%s...)",
            entity_id,
            vector.heartbeat_hash[:12],
            vector.journal_hash[:12],
            vector.coherence_hash[:12],
        )

        return reflection

    async def update_reflection(
        self,
        entity_id: UUID,
        observation: Dict[str, Any],
    ) -> MirrorReflection:
        """
        Update an entity's behavioral baseline with a new observation.

        The baseline evolves gradually — each observation blends with the
        existing baseline using exponential moving average for metric
        dimensions, and hash replacement for categorical dimensions.

        This is how the hive learns that an entity has naturally evolved
        (e.g., a Fibre that has grown wiser over time has a different
        coherence baseline than at birth — and that's expected).

        Args:
            entity_id: The entity to update.
            observation: Dictionary with the same structure as birth_parameters.

        Returns:
            The updated MirrorReflection model instance.

        Raises:
            KeyError: If no reflection exists for this entity.
        """
        if entity_id not in self._reflections:
            raise KeyError(
                f"No reflection found for entity {entity_id}. "
                f"Call create_reflection() first."
            )

        current = self._reflections[entity_id]
        new_metrics = self._extract_metrics(observation)

        # Update hash dimensions (replace if new data provided)
        if "heartbeat_data" in observation:
            current.heartbeat_hash = _BehavioralVector.hash_dimension(
                observation["heartbeat_data"]
            )
        if "journal_state" in observation:
            current.journal_hash = _BehavioralVector.hash_dimension(
                observation["journal_state"]
            )
        if "communication_peers" in observation:
            current.communication_hash = _BehavioralVector.hash_dimension(
                observation["communication_peers"]
            )
        if "data_access_scope" in observation:
            current.data_access_hash = _BehavioralVector.hash_dimension(
                observation["data_access_scope"]
            )
        if "coherence_state" in observation:
            current.coherence_hash = _BehavioralVector.hash_dimension(
                observation["coherence_state"]
            )
        if "trail_signature" in observation:
            current.trail_emission_hash = _BehavioralVector.hash_dimension(
                observation["trail_signature"]
            )

        # Blend metric dimensions with exponential moving average (α = 0.3)
        alpha = 0.3
        for key, value in new_metrics.items():
            if key in current.raw_metrics:
                current.raw_metrics[key] = (
                    alpha * value + (1 - alpha) * current.raw_metrics[key]
                )
            else:
                current.raw_metrics[key] = value

        current.captured_at = datetime.utcnow()

        # Store observation in history (bounded to last 100)
        snapshot = _BehavioralVector(
            heartbeat_hash=current.heartbeat_hash,
            journal_hash=current.journal_hash,
            communication_hash=current.communication_hash,
            data_access_hash=current.data_access_hash,
            coherence_hash=current.coherence_hash,
            trail_emission_hash=current.trail_emission_hash,
            raw_metrics=dict(current.raw_metrics),
        )
        history = self._observation_history.setdefault(entity_id, [])
        history.append(snapshot)
        if len(history) > 100:
            history[:] = history[-100:]

        # Periodic persistence check
        await self._maybe_persist()

        reflection = current.to_reflection(entity_id)

        logger.debug(
            "Reflection updated for entity %s (observations=%d)",
            entity_id, len(history),
        )

        return reflection

    # ── Comparison engine ────────────────────────────────────────────────

    async def compare_reflection(
        self,
        entity_id: UUID,
        current_behavior: Dict[str, Any],
    ) -> DivergenceResult:
        """
        Compare an entity's current behavior against its baseline reflection.

        This is the core detection method. It evaluates all six divergence
        dimensions, computes a combined divergence score, and returns a
        DivergenceResult with the recommended Curiosity Protocol level.

        Args:
            entity_id: The entity to evaluate.
            current_behavior: Dictionary with the same structure as
                birth_parameters, representing the entity's current state.

        Returns:
            A DivergenceResult containing the divergence score, flagged
            dimensions, and recommended curiosity level.

        Raises:
            KeyError: If no reflection exists for this entity.
        """
        if entity_id not in self._reflections:
            raise KeyError(
                f"No reflection found for entity {entity_id}. "
                f"Cannot compare without a baseline."
            )

        self._comparison_count += 1
        baseline = self._reflections[entity_id]
        current_metrics = self._extract_metrics(current_behavior)

        # Build current behavioral vector for comparison
        current_vector = _BehavioralVector(
            heartbeat_hash=_BehavioralVector.hash_dimension(
                current_behavior.get("heartbeat_data", {})
            ),
            journal_hash=_BehavioralVector.hash_dimension(
                current_behavior.get("journal_state", {})
            ),
            communication_hash=_BehavioralVector.hash_dimension(
                current_behavior.get("communication_peers", [])
            ),
            data_access_hash=_BehavioralVector.hash_dimension(
                current_behavior.get("data_access_scope", {})
            ),
            coherence_hash=_BehavioralVector.hash_dimension(
                current_behavior.get("coherence_state", {})
            ),
            trail_emission_hash=_BehavioralVector.hash_dimension(
                current_behavior.get("trail_signature", {})
            ),
            raw_metrics=current_metrics,
        )

        # ── Run all 6 divergence checks ─────────────────────────────────
        dimension_scores: Dict[str, float] = {}
        divergence_types: List[str] = []

        # 1. Heartbeat continuity
        hb_score = self._check_heartbeat_continuity(baseline, current_vector)
        dimension_scores[DIVERGENCE_HEARTBEAT_CONTINUITY] = hb_score
        if hb_score > 0.0:
            divergence_types.append(DIVERGENCE_HEARTBEAT_CONTINUITY)

        # 2. Journal trajectory
        jt_score = self._check_journal_trajectory(baseline, current_vector)
        dimension_scores[DIVERGENCE_JOURNAL_TRAJECTORY] = jt_score
        if jt_score > 0.0:
            divergence_types.append(DIVERGENCE_JOURNAL_TRAJECTORY)

        # 3. Communication pattern
        cp_score = self._check_communication_pattern(baseline, current_vector)
        dimension_scores[DIVERGENCE_COMMUNICATION_PATTERN] = cp_score
        if cp_score > 0.0:
            divergence_types.append(DIVERGENCE_COMMUNICATION_PATTERN)

        # 4. Data access pattern
        da_score = self._check_data_access_pattern(baseline, current_vector)
        dimension_scores[DIVERGENCE_DATA_ACCESS_PATTERN] = da_score
        if da_score > 0.0:
            divergence_types.append(DIVERGENCE_DATA_ACCESS_PATTERN)

        # 5. Coherence drift
        cd_score = self._check_coherence_drift(baseline, current_vector)
        dimension_scores[DIVERGENCE_COHERENCE_DRIFT] = cd_score
        if cd_score > 0.0:
            divergence_types.append(DIVERGENCE_COHERENCE_DRIFT)

        # 6. Trail emission anomaly
        te_score = self._check_trail_emission_anomaly(baseline, current_vector)
        dimension_scores[DIVERGENCE_TRAIL_EMISSION_ANOMALY] = te_score
        if te_score > 0.0:
            divergence_types.append(DIVERGENCE_TRAIL_EMISSION_ANOMALY)

        # ── Combined divergence magnitude ────────────────────────────────
        combined_score = math.sqrt(
            sum(s ** 2 for s in dimension_scores.values())
        )

        result = DivergenceResult(
            entity_id=entity_id,
            divergence_score=combined_score,
            divergence_types=divergence_types,
            dimension_scores=dimension_scores,
        )

        # ── Log if divergence detected ───────────────────────────────────
        if divergence_types:
            self._divergence_events += 1
            logger.info(
                "Divergence detected for entity %s: score=%.4f types=%s curiosity=%s",
                entity_id,
                combined_score,
                divergence_types,
                result.curiosity_level.value,
            )

            if self._forensic is not None:
                await self._log_divergence_forensic(entity_id, result)
        else:
            logger.debug(
                "Entity %s behavioral comparison clean (score=%.4f)",
                entity_id, combined_score,
            )

        return result

    # ── Individual divergence checks ─────────────────────────────────────

    def _check_heartbeat_continuity(
        self,
        baseline: _BehavioralVector,
        current: _BehavioralVector,
    ) -> float:
        """
        Check if the heartbeat rhythm remains consistent with baseline.

        A mismatched heartbeat hash indicates the entity's birth coherence
        signal has changed — which should be impossible for a legitimately
        born entity. Hash mismatch scores the full weight; metric-based
        rhythm comparison provides continuous scoring.

        Returns:
            Divergence score for this dimension (0.0 = match, 0.2+ = mismatch).
        """
        if baseline.heartbeat_hash != current.heartbeat_hash:
            return self.HASH_MISMATCH_WEIGHT

        # Check metric-level rhythm stability if available
        baseline_rate = baseline.raw_metrics.get("heartbeat_rate", 0.0)
        current_rate = current.raw_metrics.get("heartbeat_rate", 0.0)
        if baseline_rate > 0 and current_rate > 0:
            ratio = abs(current_rate - baseline_rate) / max(baseline_rate, 1e-9)
            return min(ratio * self.METRIC_SENSITIVITY, self.HASH_MISMATCH_WEIGHT)

        return 0.0

    def _check_journal_trajectory(
        self,
        baseline: _BehavioralVector,
        current: _BehavioralVector,
    ) -> float:
        """
        Check if the evolution journal is growing along its natural trajectory.

        Journals grow monotonically — they never shrink, never reset, and
        their hash changes predictably as new entries are appended. A sudden
        journal hash change without corresponding growth metrics indicates
        journal tampering or entity replacement.

        Returns:
            Divergence score for this dimension.
        """
        if baseline.journal_hash == current.journal_hash:
            return 0.0  # No change — consistent (entity hasn't evolved yet)

        # Journal changed — check if growth is natural
        baseline_size = baseline.raw_metrics.get("journal_entry_count", 0)
        current_size = current.raw_metrics.get("journal_entry_count", 0)

        if current_size < baseline_size:
            # Journal shrank — critical anomaly
            return self.HASH_MISMATCH_WEIGHT

        if current_size == baseline_size and baseline.journal_hash != current.journal_hash:
            # Hash changed but size didn't — tampering suspected
            return self.HASH_MISMATCH_WEIGHT * 0.8

        # Journal grew — check if growth rate is reasonable
        growth = current_size - baseline_size
        expected_max_growth = baseline.raw_metrics.get("max_journal_growth_per_check", 10)
        if growth > expected_max_growth:
            # Abnormally fast growth
            return min(
                (growth / max(expected_max_growth, 1)) * self.METRIC_SENSITIVITY * 0.5,
                self.HASH_MISMATCH_WEIGHT,
            )

        return 0.0

    def _check_communication_pattern(
        self,
        baseline: _BehavioralVector,
        current: _BehavioralVector,
    ) -> float:
        """
        Check if the entity's communication graph matches expectations.

        Entities communicate with specific peers in specific patterns.
        A sudden change in communication partners, frequency, or message
        types indicates potential compromise or impersonation.

        Returns:
            Divergence score for this dimension.
        """
        if baseline.communication_hash != current.communication_hash:
            # Check metric overlap
            baseline_peers = baseline.raw_metrics.get("peer_count", 0)
            current_peers = current.raw_metrics.get("peer_count", 0)

            if baseline_peers > 0 and current_peers > 0:
                # Score based on how much the peer set changed
                overlap = baseline.raw_metrics.get("peer_overlap_ratio", 1.0)
                current_overlap = current.raw_metrics.get("peer_overlap_ratio", 1.0)
                drift = abs(current_overlap - overlap)
                return min(drift + 0.05, self.HASH_MISMATCH_WEIGHT)

            return self.HASH_MISMATCH_WEIGHT

        return 0.0

    def _check_data_access_pattern(
        self,
        baseline: _BehavioralVector,
        current: _BehavioralVector,
    ) -> float:
        """
        Check if the entity is accessing the data resources it should.

        Every entity has a scope — the set of data it's authorized to
        access and typically does access. Accessing outside scope, or
        stopping access to expected resources, is a divergence signal.

        Returns:
            Divergence score for this dimension.
        """
        if baseline.data_access_hash != current.data_access_hash:
            # Check for scope expansion (more concerning than contraction)
            baseline_scope_size = baseline.raw_metrics.get("access_scope_size", 0)
            current_scope_size = current.raw_metrics.get("access_scope_size", 0)

            if current_scope_size > baseline_scope_size * 1.5:
                # Significant scope expansion — high concern
                return self.HASH_MISMATCH_WEIGHT
            elif current_scope_size > baseline_scope_size:
                # Mild scope expansion
                expansion = (current_scope_size - baseline_scope_size) / max(
                    baseline_scope_size, 1
                )
                return min(expansion * self.METRIC_SENSITIVITY, self.HASH_MISMATCH_WEIGHT)

            return self.HASH_MISMATCH_WEIGHT * 0.5

        return 0.0

    def _check_coherence_drift(
        self,
        baseline: _BehavioralVector,
        current: _BehavioralVector,
    ) -> float:
        """
        Check if the entity's emotional coherence has drifted from baseline.

        Coherence is derived from the Nevedal Formula's C_emo(t). Natural
        coherence drift is gradual and bounded. Sudden coherence shifts
        indicate external manipulation or entity replacement.

        Returns:
            Divergence score for this dimension.
        """
        if baseline.coherence_hash == current.coherence_hash:
            return 0.0

        # Use coherence magnitude if available
        baseline_c = baseline.raw_metrics.get("coherence_magnitude", 0.0)
        current_c = current.raw_metrics.get("coherence_magnitude", 0.0)

        if baseline_c > 0:
            drift = abs(current_c - baseline_c) / max(baseline_c, 1e-9)
            if drift > 0.5:
                # Massive coherence shift — very suspicious
                return self.HASH_MISMATCH_WEIGHT
            return min(drift * self.METRIC_SENSITIVITY, self.HASH_MISMATCH_WEIGHT)

        # No metrics — fall back to hash comparison
        return self.HASH_MISMATCH_WEIGHT * 0.6

    def _check_trail_emission_anomaly(
        self,
        baseline: _BehavioralVector,
        current: _BehavioralVector,
    ) -> float:
        """
        Check if the entity's trail emission signature is consistent.

        Trail emissions are the ambient signals an entity produces during
        normal operation — analogous to body language. Each entity has a
        unique emission fingerprint. Forged entities produce emissions that
        look plausible but don't match the entity's personal rhythm.

        Returns:
            Divergence score for this dimension.
        """
        if baseline.trail_emission_hash == current.trail_emission_hash:
            return 0.0

        # Check emission rate consistency
        baseline_rate = baseline.raw_metrics.get("trail_emission_rate", 0.0)
        current_rate = current.raw_metrics.get("trail_emission_rate", 0.0)

        if baseline_rate > 0 and current_rate > 0:
            ratio = abs(current_rate - baseline_rate) / max(baseline_rate, 1e-9)
            # Trail emissions should be very stable — flag any drift
            return min(ratio * self.METRIC_SENSITIVITY + 0.02, self.HASH_MISMATCH_WEIGHT)

        return self.HASH_MISMATCH_WEIGHT * 0.7

    # ── Forensic logging ─────────────────────────────────────────────────

    async def _log_divergence_forensic(
        self,
        entity_id: UUID,
        result: DivergenceResult,
    ) -> None:
        """
        Record a divergence event in the immutable forensic chain.
        """
        try:
            record = ForensicRecord(
                record_id=uuid4(),
                event_type="mirror_reflection.divergence_detected",
                source_entity=str(entity_id),
                evidence={
                    "divergence_score": result.divergence_score,
                    "divergence_types": result.divergence_types,
                    "dimension_scores": result.dimension_scores,
                    "curiosity_level": result.curiosity_level.value,
                    "timestamp": result.timestamp.isoformat(),
                },
                timestamp=datetime.utcnow(),
            )
            await self._forensic.log(record)
        except Exception as exc:
            logger.error(
                "Failed to write forensic divergence record for entity %s: %s",
                entity_id, exc,
            )

    # ── Persistence ──────────────────────────────────────────────────────

    async def _maybe_persist(self) -> None:
        """
        Check if it's time to persist reflections to durable storage.

        Reflections are kept in memory for speed but periodically flushed
        to the database to survive restarts.
        """
        now = time.monotonic()
        if now - self._last_persistence >= self.PERSISTENCE_INTERVAL_SEC:
            await self.persist_all()
            self._last_persistence = now

    async def persist_all(self) -> int:
        """
        Persist all current reflections to durable storage.

        Returns:
            The number of reflections persisted.
        """
        count = len(self._reflections)
        if count == 0:
            return 0

        # In production, this writes to PostgreSQL via asyncpg.
        # For now, the persistence layer is a hook for the database adapter.
        logger.info(
            "Persisting %d reflections to durable storage "
            "(comparisons=%d, divergence_events=%d)",
            count,
            self._comparison_count,
            self._divergence_events,
        )
        return count

    # ── Queries & introspection ──────────────────────────────────────────

    async def get_reflection(self, entity_id: UUID) -> Optional[MirrorReflection]:
        """
        Retrieve the current MirrorReflection for an entity.

        Returns:
            The MirrorReflection if the entity has a baseline, else None.
        """
        vector = self._reflections.get(entity_id)
        if vector is None:
            return None
        return vector.to_reflection(entity_id)

    async def get_observation_history(
        self, entity_id: UUID
    ) -> List[MirrorReflection]:
        """
        Retrieve the observation history for an entity.

        Returns:
            A list of MirrorReflection snapshots in chronological order.
        """
        history = self._observation_history.get(entity_id, [])
        return [v.to_reflection(entity_id) for v in history]

    async def remove_reflection(self, entity_id: UUID) -> bool:
        """
        Remove a reflection (e.g., when an entity is decommissioned).

        The reflection data is purged from memory. Forensic records in the
        immutable chain are NOT affected (they are permanent).

        Returns:
            True if a reflection was removed, False if not found.
        """
        removed = self._reflections.pop(entity_id, None)
        self._observation_history.pop(entity_id, None)
        if removed is not None:
            logger.info("Reflection removed for entity %s", entity_id)
            return True
        return False

    @property
    def entity_count(self) -> int:
        """Return the number of entities with active reflections."""
        return len(self._reflections)

    @property
    def metrics(self) -> Dict[str, int]:
        """Return current mirror reflection metrics."""
        return {
            "entities_tracked": len(self._reflections),
            "total_comparisons": self._comparison_count,
            "divergence_events": self._divergence_events,
            "total_observations": sum(
                len(h) for h in self._observation_history.values()
            ),
        }

    # ── Utility ──────────────────────────────────────────────────────────

    @staticmethod
    def _extract_metrics(parameters: Dict[str, Any]) -> Dict[str, float]:
        """
        Extract continuous numeric metrics from behavioral parameters.

        These metrics enable fine-grained divergence scoring beyond simple
        hash comparison. Only numeric values are extracted.

        Args:
            parameters: The behavioral parameter dictionary.

        Returns:
            A flat dictionary of metric_name → float_value.
        """
        metrics: Dict[str, float] = {}
        metric_keys = [
            "heartbeat_rate",
            "journal_entry_count",
            "max_journal_growth_per_check",
            "peer_count",
            "peer_overlap_ratio",
            "access_scope_size",
            "coherence_magnitude",
            "trail_emission_rate",
        ]
        for key in metric_keys:
            if key in parameters:
                try:
                    metrics[key] = float(parameters[key])
                except (TypeError, ValueError):
                    pass
        return metrics

    def __repr__(self) -> str:
        return (
            f"<MirrorReflectionManager entities={self.entity_count} "
            f"comparisons={self._comparison_count} "
            f"divergences={self._divergence_events}>"
        )
