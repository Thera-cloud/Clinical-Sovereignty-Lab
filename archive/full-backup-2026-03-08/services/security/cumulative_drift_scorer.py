"""
HIVE DEFENSE PROTOCOL — Cumulative Drift Scorer (Phase 8B)
Slow infiltration detection through multi-dimensional behavioral drift analysis.

The Cumulative Drift Scorer (CDS) detects attackers who move so slowly that any
single observation looks like random noise.  It tracks drift across six behavioral
dimensions, each modeled as a vector with magnitude and direction.  Random noise
cancels out (opposite directions offset), but *consistent directional drift*
compounds over time, eventually crossing detection thresholds.

Six Drift Dimensions:
    1. data_access        — Changes in data access patterns
    2. communication      — Changes in communication graph topology
    3. coherence          — Drift in emotional coherence baseline
    4. trail_emission     — Changes in trail emission fingerprint
    5. journal_trajectory — Evolution journal trajectory deviation
    6. timing_pattern     — Timing regularity changes

Detection Thresholds (base values, multiplied by DEFCON cds_multiplier):
    NOTICE  = 0.15  — Minor drift detected, increase monitoring
    INTEREST = 0.30 — Significant drift, cross-verify with ring
    CONCERN = 0.50  — Confirmed directional drift, Three-Cord Verification
    ALARM   = 0.75  — Sustained attack vector, mesh isolation

Weekly Example:
    An attacker drifting 0.001/week in a single dimension would be detected at
    week 16 (0.016 combined).  But an attacker drifting 0.001/week across ALL
    six dimensions would hit NOTICE at week 16 because:
        combined = sqrt(6 × 0.016²) ≈ 0.039 (still below)
    But at week 62: combined = sqrt(6 × 0.062²) ≈ 0.152 → NOTICE triggered.
    Consistent drift in one dimension: detected at ~week 150 (0.15/0.001).
    With DEFCON 3 multiplier (0.50): detected at ~week 75.

Patent-Pending — Claim 37
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from app.models.hive_defense import (
    CuriosityLevel,
    DefconLevel,
    DefconState,
    DriftScore,
)

logger = logging.getLogger("hive.cumulative_drift_scorer")


# =============================================================================
# CONSTANTS
# =============================================================================

#: The six drift dimensions tracked by the CDS.
DRIFT_DIMENSIONS: Tuple[str, ...] = (
    "data_access",
    "communication",
    "coherence",
    "trail_emission",
    "journal_trajectory",
    "timing_pattern",
)

#: Base CDS thresholds.  These are multiplied by the current DEFCON
#: ``cds_threshold_multiplier`` to make the system more sensitive under
#: heightened alert conditions.
CDS_THRESHOLDS: Dict[str, float] = {
    "NOTICE": 0.15,
    "INTEREST": 0.30,
    "CONCERN": 0.50,
    "ALARM": 0.75,
}

#: Default DEFCON CDS multiplier map.  Lower DEFCON → lower multiplier →
#: tighter thresholds (more sensitive detection).
DEFCON_CDS_MULTIPLIER: Dict[DefconLevel, float] = {
    DefconLevel.PEACE: 1.00,
    DefconLevel.ELEVATED: 0.85,
    DefconLevel.SUBSTANTIAL: 0.50,
    DefconLevel.SEVERE: 0.30,
    DefconLevel.CRITICAL: 0.15,
}

#: Maximum number of observations to keep per entity per dimension
#: in the rolling history buffer.
MAX_HISTORY_PER_DIMENSION: int = 500


# =============================================================================
# DRIFT VECTOR — Per-Dimension Accumulator
# =============================================================================

@dataclass
class DriftVector:
    """
    A single-dimension drift accumulator.

    Tracks the rolling vector sum of observed deltas.  Opposite-direction
    observations offset each other (noise cancellation), while consistent
    directional observations compound (attack detection).

    Attributes:
        dimension:       The dimension name (e.g. "data_access").
        vector_sum:      The cumulative signed sum of observed deltas.
        observation_count: Total observations recorded.
        last_updated:    Timestamp of the most recent observation.
        history:         Rolling buffer of recent observations for auditing.
    """
    dimension: str = ""
    vector_sum: float = 0.0
    observation_count: int = 0
    last_updated: Optional[datetime] = None
    history: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def magnitude(self) -> float:
        """Absolute magnitude of the cumulative drift vector."""
        return abs(self.vector_sum)

    @property
    def direction(self) -> str:
        """Human-readable direction of drift."""
        if self.vector_sum > 0.001:
            return "positive"
        elif self.vector_sum < -0.001:
            return "negative"
        return "neutral"

    def add_observation(self, delta: float) -> None:
        """
        Add a new drift observation.

        Args:
            delta: The observed behavioral delta.  Positive values indicate
                   drift in the 'positive' direction; negative values indicate
                   drift in the 'negative' direction.  Random noise will have
                   roughly equal positive and negative deltas, causing the
                   vector_sum to stay near zero.
        """
        self.vector_sum += delta
        self.observation_count += 1
        self.last_updated = datetime.utcnow()

        # Maintain rolling history buffer
        self.history.append({
            "delta": delta,
            "cumulative": self.vector_sum,
            "timestamp": self.last_updated.isoformat(),
        })
        if len(self.history) > MAX_HISTORY_PER_DIMENSION:
            self.history = self.history[-MAX_HISTORY_PER_DIMENSION:]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for API responses."""
        return {
            "dimension": self.dimension,
            "vector_sum": round(self.vector_sum, 6),
            "magnitude": round(self.magnitude, 6),
            "direction": self.direction,
            "observation_count": self.observation_count,
            "last_updated": (
                self.last_updated.isoformat() if self.last_updated else None
            ),
        }


# =============================================================================
# ENTITY DRIFT STATE — Aggregate of All 6 Dimensions
# =============================================================================

@dataclass
class EntityDriftState:
    """
    Complete drift state for a single entity across all six dimensions.

    Attributes:
        entity_id:  UUID of the tracked entity.
        vectors:    Mapping of dimension name → DriftVector.
        created_at: When tracking began for this entity.
    """
    entity_id: UUID = field(default_factory=uuid4)
    vectors: Dict[str, DriftVector] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self) -> None:
        """Ensure all six dimensions have a DriftVector."""
        for dim in DRIFT_DIMENSIONS:
            if dim not in self.vectors:
                self.vectors[dim] = DriftVector(dimension=dim)

    @property
    def combined_magnitude(self) -> float:
        """
        Combined drift magnitude across all dimensions.

        Computed as the L2 norm (Euclidean distance) of the per-dimension
        magnitudes: sqrt(sum of squared vector magnitudes).

        This is the core CDS metric.  Random noise across dimensions tends
        to cancel out within each dimension, keeping individual magnitudes
        small.  Consistent drift compounds, causing individual magnitudes
        to grow, which in turn grows the combined magnitude.
        """
        return math.sqrt(
            sum(v.magnitude ** 2 for v in self.vectors.values())
        )

    def to_drift_score(self) -> DriftScore:
        """Convert to the Pydantic DriftScore model for persistence."""
        score = DriftScore(
            entity_id=self.entity_id,
            data_access=self.vectors["data_access"].magnitude,
            communication=self.vectors["communication"].magnitude,
            coherence=self.vectors["coherence"].magnitude,
            trail_emission=self.vectors["trail_emission"].magnitude,
            journal_trajectory=self.vectors["journal_trajectory"].magnitude,
            timing_pattern=self.vectors["timing_pattern"].magnitude,
            last_updated=datetime.utcnow(),
        )
        score.compute_magnitude()
        return score

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for API responses."""
        return {
            "entity_id": str(self.entity_id),
            "combined_magnitude": round(self.combined_magnitude, 6),
            "dimensions": {
                dim: vec.to_dict() for dim, vec in self.vectors.items()
            },
            "created_at": self.created_at.isoformat(),
        }


# =============================================================================
# CUMULATIVE DRIFT SCORER
# =============================================================================

class CumulativeDriftScorer:
    """
    Slow infiltration detection through cumulative multi-dimensional drift analysis.

    The CDS monitors behavioral drift across six dimensions for every hive entity.
    Random fluctuations cancel out (noise), but consistent directional drift
    compounds over time until it crosses detection thresholds.

    Thresholds are DEFCON-adaptive: at higher alert levels, the CDS multiplier
    is reduced, making thresholds tighter (more sensitive).

    Integration points:
        - CuriosityProtocol — receives CDS curiosity level assessments
        - ForensicLogger    — drift events persisted to immutable chain
        - DefconManager     — provides current DEFCON state for threshold scaling
        - Hive event bus    — publishes drift detection events

    Usage::

        scorer = CumulativeDriftScorer(db_pool=pool)
        await scorer.update_drift(entity_id, "data_access", 0.002)
        result = await scorer.evaluate_entity(entity_id)
        report = await scorer.get_drift_report(entity_id)

    Patent-Pending — Claim 37.
    """

    def __init__(
        self,
        db_pool=None,
        forensic_logger=None,
        event_bus=None,
        defcon_state: Optional[DefconState] = None,
    ) -> None:
        """
        Initialize the Cumulative Drift Scorer.

        Args:
            db_pool:         asyncpg connection pool for persistence.
            forensic_logger: ForensicLogger instance for immutable evidence chain.
            event_bus:       Hive event bus for publishing drift detection events.
            defcon_state:    Current DEFCON state (provides cds_threshold_multiplier).
                             If None, defaults to PEACE (multiplier 1.0).
        """
        self.db_pool = db_pool
        self._forensic_logger = forensic_logger
        self._event_bus = event_bus
        self._defcon_state: DefconState = defcon_state or DefconState()

        # In-memory entity drift states
        self._entity_states: Dict[UUID, EntityDriftState] = {}

        logger.info(
            ">>> [CDS] Cumulative Drift Scorer initialized "
            "(DEFCON=%d, cds_multiplier=%.2f)",
            self._defcon_state.level.value,
            self._defcon_state.cds_threshold_multiplier,
        )

    # =========================================================================
    # DEFCON STATE
    # =========================================================================

    def update_defcon(self, defcon_state: DefconState) -> None:
        """
        Update the current DEFCON state.

        This adjusts all CDS thresholds via the ``cds_threshold_multiplier``.

        Args:
            defcon_state: The new DEFCON state.
        """
        old_multiplier = self._defcon_state.cds_threshold_multiplier
        self._defcon_state = defcon_state
        logger.info(
            ">>> [CDS] DEFCON updated: level=%d, cds_multiplier=%.2f → %.2f",
            defcon_state.level.value,
            old_multiplier,
            defcon_state.cds_threshold_multiplier,
        )

    def _effective_threshold(self, base_threshold: float) -> float:
        """
        Compute the effective threshold after DEFCON scaling.

        Args:
            base_threshold: The base CDS threshold value.

        Returns:
            Effective threshold (base × cds_multiplier).  A lower multiplier
            means tighter thresholds — more sensitive detection.
        """
        return base_threshold * self._defcon_state.cds_threshold_multiplier

    # =========================================================================
    # STATE MANAGEMENT
    # =========================================================================

    def _get_state(self, entity_id: UUID) -> EntityDriftState:
        """
        Retrieve or create the drift state for an entity.

        Args:
            entity_id: UUID of the entity.

        Returns:
            EntityDriftState for the given entity.
        """
        if entity_id not in self._entity_states:
            self._entity_states[entity_id] = EntityDriftState(entity_id=entity_id)
        return self._entity_states[entity_id]

    # =========================================================================
    # DRIFT OBSERVATION
    # =========================================================================

    async def update_drift(
        self,
        entity_id: UUID,
        dimension: str,
        observed_delta: float,
    ) -> Dict[str, Any]:
        """
        Record a new behavioral drift observation for an entity.

        Each observation is a signed delta representing the magnitude and
        direction of behavioral change in a single dimension.  Random noise
        produces deltas that cancel over time; consistent attacker drift
        compounds.

        Args:
            entity_id:      UUID of the entity.
            dimension:       One of the six drift dimensions.
            observed_delta:  The signed behavioral delta.  Positive = drift
                             in one direction, negative = drift in the other.

        Returns:
            Dictionary with updated drift state summary.

        Raises:
            ValueError: If ``dimension`` is not one of the six valid dimensions.
        """
        if dimension not in DRIFT_DIMENSIONS:
            raise ValueError(
                f"Invalid drift dimension '{dimension}'. "
                f"Must be one of: {', '.join(DRIFT_DIMENSIONS)}"
            )

        state = self._get_state(entity_id)
        vector = state.vectors[dimension]
        vector.add_observation(observed_delta)

        combined = state.combined_magnitude

        logger.debug(
            ">>> [CDS] Drift update: entity=%s dim=%s delta=%.6f "
            "vec_sum=%.6f combined=%.6f",
            entity_id, dimension, observed_delta,
            vector.vector_sum, combined,
        )

        # Persist to database
        await self._persist_drift(entity_id, state)

        return {
            "entity_id": str(entity_id),
            "dimension": dimension,
            "observed_delta": observed_delta,
            "dimension_magnitude": round(vector.magnitude, 6),
            "dimension_direction": vector.direction,
            "combined_magnitude": round(combined, 6),
            "observation_count": vector.observation_count,
        }

    # =========================================================================
    # ENTITY EVALUATION
    # =========================================================================

    async def evaluate_entity(self, entity_id: UUID) -> Dict[str, Any]:
        """
        Evaluate an entity's cumulative drift and determine its curiosity level.

        Compares the entity's combined drift magnitude against DEFCON-adjusted
        thresholds and returns the appropriate CuriosityLevel.

        Args:
            entity_id: UUID of the entity to evaluate.

        Returns:
            Dictionary containing:
                - curiosity_level: The assessed CuriosityLevel
                - combined_magnitude: Current combined drift magnitude
                - effective_thresholds: DEFCON-adjusted threshold values
                - per_dimension: Individual dimension drift summaries
                - defcon_multiplier: Current DEFCON CDS multiplier
        """
        state = self._get_state(entity_id)
        combined = state.combined_magnitude

        # Compute effective (DEFCON-scaled) thresholds
        thresholds = {
            level_name: self._effective_threshold(base_val)
            for level_name, base_val in CDS_THRESHOLDS.items()
        }

        # Determine curiosity level from combined magnitude
        if combined >= thresholds["ALARM"]:
            curiosity = CuriosityLevel.ALARM
        elif combined >= thresholds["CONCERN"]:
            curiosity = CuriosityLevel.CONCERN
        elif combined >= thresholds["INTEREST"]:
            curiosity = CuriosityLevel.INTEREST
        elif combined >= thresholds["NOTICE"]:
            curiosity = CuriosityLevel.NOTICE
        else:
            curiosity = CuriosityLevel.NONE

        # Log significant detections
        if curiosity != CuriosityLevel.NONE:
            logger.warning(
                ">>> [CDS] Drift detected: entity=%s level=%s "
                "combined=%.6f threshold=%.4f (DEFCON=%d, mult=%.2f)",
                entity_id,
                curiosity.value,
                combined,
                thresholds.get(curiosity.value.upper(), 0),
                self._defcon_state.level.value,
                self._defcon_state.cds_threshold_multiplier,
            )

            # Log to forensic chain
            if self._forensic_logger:
                try:
                    await self._forensic_logger.log_event(
                        event_type=f"cds_drift_{curiosity.value}",
                        source_entity=str(entity_id),
                        evidence={
                            "combined_magnitude": combined,
                            "level": curiosity.value,
                            "effective_thresholds": thresholds,
                            "per_dimension": {
                                dim: {
                                    "magnitude": round(vec.magnitude, 6),
                                    "direction": vec.direction,
                                    "observations": vec.observation_count,
                                }
                                for dim, vec in state.vectors.items()
                            },
                        },
                    )
                except Exception as exc:
                    logger.error(">>> [CDS] Forensic log failed: %s", exc)

            # Fire hive event
            if self._event_bus:
                try:
                    await self._event_bus.publish(
                        "hive.snapshot.drift_detected",
                        {
                            "entity_id": str(entity_id),
                            "level": curiosity.value,
                            "combined_magnitude": combined,
                            "timestamp": datetime.utcnow().isoformat(),
                        },
                    )
                except Exception as exc:
                    logger.error(">>> [CDS] Event bus publish failed: %s", exc)

        return {
            "entity_id": str(entity_id),
            "curiosity_level": curiosity.value,
            "combined_magnitude": round(combined, 6),
            "effective_thresholds": {
                k: round(v, 4) for k, v in thresholds.items()
            },
            "per_dimension": {
                dim: vec.to_dict() for dim, vec in state.vectors.items()
            },
            "defcon_level": self._defcon_state.level.value,
            "defcon_multiplier": self._defcon_state.cds_threshold_multiplier,
            "total_observations": sum(
                v.observation_count for v in state.vectors.values()
            ),
        }

    # =========================================================================
    # DRIFT REPORT
    # =========================================================================

    async def get_drift_report(self, entity_id: UUID) -> DriftScore:
        """
        Generate a DriftScore report for an entity.

        Returns the Pydantic DriftScore model with all six dimension magnitudes
        and the combined magnitude, suitable for API responses and persistence.

        Args:
            entity_id: UUID of the entity.

        Returns:
            DriftScore Pydantic model with current drift state.
        """
        state = self._get_state(entity_id)
        return state.to_drift_score()

    # =========================================================================
    # BATCH OPERATIONS
    # =========================================================================

    async def evaluate_all(self) -> List[Dict[str, Any]]:
        """
        Evaluate all tracked entities and return those with non-NONE levels.

        Returns:
            List of evaluation results for entities with detected drift.
        """
        results = []
        for entity_id in list(self._entity_states.keys()):
            result = await self.evaluate_entity(entity_id)
            if result["curiosity_level"] != CuriosityLevel.NONE.value:
                results.append(result)
        return results

    def get_all_tracked_entities(self) -> List[Dict[str, Any]]:
        """
        Return summary information for all tracked entities.

        Returns:
            List of entity drift state summaries.
        """
        return [
            {
                "entity_id": str(eid),
                "combined_magnitude": round(state.combined_magnitude, 6),
                "total_observations": sum(
                    v.observation_count for v in state.vectors.values()
                ),
                "created_at": state.created_at.isoformat(),
            }
            for eid, state in self._entity_states.items()
        ]

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    async def _persist_drift(self, entity_id: UUID, state: EntityDriftState) -> None:
        """
        Persist the entity's drift score to the database.

        Upserts the drift_scores table with current dimension magnitudes
        and combined magnitude.

        Args:
            entity_id: UUID of the entity.
            state:     The EntityDriftState to persist.
        """
        if not self.db_pool:
            return

        score = state.to_drift_score()

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO drift_scores (
                        entity_id, data_access, communication, coherence,
                        trail_emission, journal_trajectory, timing_pattern,
                        combined_magnitude, last_updated
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                    ON CONFLICT (entity_id)
                    DO UPDATE SET
                        data_access = EXCLUDED.data_access,
                        communication = EXCLUDED.communication,
                        coherence = EXCLUDED.coherence,
                        trail_emission = EXCLUDED.trail_emission,
                        journal_trajectory = EXCLUDED.journal_trajectory,
                        timing_pattern = EXCLUDED.timing_pattern,
                        combined_magnitude = EXCLUDED.combined_magnitude,
                        last_updated = NOW()
                """,
                    entity_id,
                    score.data_access,
                    score.communication,
                    score.coherence,
                    score.trail_emission,
                    score.journal_trajectory,
                    score.timing_pattern,
                    score.combined_magnitude,
                )
        except Exception as exc:
            logger.error(
                ">>> [CDS] Drift persistence failed for %s: %s",
                entity_id, exc,
            )

    async def load_persisted_scores(self) -> int:
        """
        Load all persisted drift scores from the database on startup.

        Restores in-memory entity drift states so that drift tracking
        continues seamlessly after a restart.  Note that per-observation
        history is NOT restored (only aggregate magnitudes).

        Returns:
            Number of entity scores restored.
        """
        if not self.db_pool:
            return 0

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT entity_id, data_access, communication, coherence,
                           trail_emission, journal_trajectory, timing_pattern,
                           combined_magnitude, last_updated
                    FROM drift_scores
                    WHERE combined_magnitude > 0
                """)

            restored = 0
            for row in rows:
                entity_id = row["entity_id"]
                state = self._get_state(entity_id)

                # Restore vector sums from persisted magnitudes.
                # Direction is unknown after restart — we store magnitude only.
                # This is conservative: magnitude-only restoration means the
                # entity will need to re-accumulate to cross thresholds again,
                # which is a safe default.
                for dim in DRIFT_DIMENSIONS:
                    vec = state.vectors[dim]
                    persisted_magnitude = float(row[dim] or 0.0)
                    # Set vector_sum to the persisted magnitude (positive direction)
                    vec.vector_sum = persisted_magnitude
                    if row["last_updated"]:
                        vec.last_updated = row["last_updated"]

                restored += 1

            logger.info(
                ">>> [CDS] Restored %d persisted drift scores", restored
            )
            return restored

        except Exception as exc:
            logger.error(">>> [CDS] Score restoration failed: %s", exc)
            return 0

    # =========================================================================
    # ADMIN / RESET
    # =========================================================================

    async def reset_entity(
        self,
        entity_id: UUID,
        authorized_by: str,
    ) -> Dict[str, Any]:
        """
        Administratively reset an entity's drift state to zero.

        Requires human authorization.  Used after an investigation concludes
        and the entity is cleared.

        Args:
            entity_id:     UUID of the entity to reset.
            authorized_by: Identifier of the authorizing administrator.

        Returns:
            Reset confirmation with audit trail.
        """
        state = self._get_state(entity_id)
        old_magnitude = state.combined_magnitude

        # Log the administrative reset
        if self._forensic_logger:
            try:
                await self._forensic_logger.log_event(
                    event_type="cds_admin_reset",
                    source_entity=str(entity_id),
                    evidence={
                        "old_combined_magnitude": old_magnitude,
                        "authorized_by": authorized_by,
                        "per_dimension": {
                            dim: round(vec.magnitude, 6)
                            for dim, vec in state.vectors.items()
                        },
                    },
                )
            except Exception as exc:
                logger.error(">>> [CDS] Forensic log error: %s", exc)

        # Reset all dimension vectors
        for dim in DRIFT_DIMENSIONS:
            state.vectors[dim] = DriftVector(dimension=dim)

        # Persist the reset
        await self._persist_drift(entity_id, state)

        logger.info(
            ">>> [CDS] Entity %s drift reset by %s (was combined=%.6f)",
            entity_id, authorized_by, old_magnitude,
        )

        return {
            "entity_id": str(entity_id),
            "previous_combined_magnitude": round(old_magnitude, 6),
            "current_combined_magnitude": 0.0,
            "authorized_by": authorized_by,
            "reset_at": datetime.utcnow().isoformat(),
        }
