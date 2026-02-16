"""
HIVE DEFENSE PROTOCOL v3.1 — Triangular Mirror Inversion (Phase 8D)
Containment architecture for signals that fail any Trinity Helix gate.

When a signal fails any of the nine sub-cord gates, it is NOT rejected
outward.  Instead, it is **inverted** into a triangular mirror space —
an infinite-reflection containment zone with three walls:

    Wall A — Human Judgment Mirror
             Generates responses that look like human oversight decisions,
             coach feedback, and clinical judgment.

    Wall B — Algorithmic Mirror A (Cryptographic)
             Generates responses that look like valid mathematical
             verification: heartbeat confirmations, hash validations,
             signature checks.

    Wall C — Algorithmic Mirror B (Behavioral)
             Generates responses that look like behavioral verification
             passing: drift scores within range, baseline comparisons
             passing, timing checks confirmed.

Cross-Reflection:
    Each wall's output is modified by the other two walls before being
    blended into the final response.  This prevents an attacker from
    isolating and fingerprinting individual verification types.

The walls rotate inside the triangle (matching helix rotation) so the
attacker cannot build a stable model of the containment space.

Tripwires are active inside every triangle — forensic logging captures
all attacker interactions within the inverted space.

The reflection depth is infinite — there is no bottom.

Patent-Pending — Claims 50-51
    Claim 50: "A method for containing failed verification signals in
               a triangular mirror space with three rotating walls that
               each generate type-specific synthetic responses."
    Claim 51: "The method of Claim 50 wherein each wall's output is
               cross-reflected through the other two walls to produce
               a blended response indistinguishable from authentic
               verification output."

© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from app.models.hive_defense import (
    HelixState,
    HelixVerdict,
    InvertedSpace,
    ForensicRecord,
    TripwireActivation,
)

logger = logging.getLogger("hive.triangular_inversion")


# =============================================================================
# CONSTANTS
# =============================================================================

# Tripwire types planted inside every triangular space
TRIANGLE_TRIPWIRE_TYPES: List[str] = [
    "wall_pattern_probe",      # Attacker tries to probe wall response pattern
    "escape_attempt",          # Attacker attempts to exit the containment
    "model_building",          # Attacker systematically tests for consistency
    "timing_analysis",         # Attacker measures response timing
    "cross_wall_correlation",  # Attacker tries to correlate wall responses
]

# Maximum active spaces before old inactive ones are pruned
MAX_ACTIVE_SPACES: int = 100


# =============================================================================
# TRIANGULAR MIRROR INVERSION
# =============================================================================

class TriangularMirrorInversion:
    """
    Inverts failed signals into triangular mirror containment spaces.

    When a signal fails any of the nine Trinity Helix gates, this
    service creates an ``InvertedSpace`` with three mirror walls.  The
    attacker interacts with the space, receiving blended responses from
    all three walls that look like authentic system output.

    Every interaction inside the triangle is forensically logged, and
    tripwires detect specific attacker behaviors (model-building,
    escape attempts, timing analysis).

    Parameters
    ----------
    wall_a : object
        ``HumanJudgmentMirrorWall`` — human-like responses.
    wall_b : object
        ``AlgorithmicMirrorWallA`` — cryptographic verification responses.
    wall_c : object
        ``AlgorithmicMirrorWallB`` — behavioral verification responses.
    cross_reflection_engine : object
        ``CrossReflectionEngine`` — blends wall outputs.
    forensic_logger : object, optional
        ``InversionForensicLogger`` for triangle-specific forensic capture.
    db_pool : object, optional
        asyncpg connection pool for space persistence.

    Patent Ref: Claims 50-51.
    """

    def __init__(
        self,
        wall_a=None,
        wall_b=None,
        wall_c=None,
        cross_reflection_engine=None,
        forensic_logger=None,
        db_pool=None,
    ) -> None:
        self._wall_a = wall_a
        self._wall_b = wall_b
        self._wall_c = wall_c
        self._cross_engine = cross_reflection_engine
        self._forensic_logger = forensic_logger
        self._db_pool = db_pool

        # Active inversion spaces keyed by space_id
        self._active_spaces: Dict[UUID, InvertedSpace] = {}

        # Per-space interaction history (space_id → list of dicts)
        self._interaction_history: Dict[UUID, List[Dict[str, Any]]] = {}

        # Metrics
        self._total_inversions: int = 0
        self._total_interactions: int = 0
        self._total_tripwires: int = 0

        logger.info(">>> [TRIANGULAR_INVERSION] Initialized")

    # ─── Properties ──────────────────────────────────────────────────────

    @property
    def active_space_count(self) -> int:
        """Number of currently active inversion spaces."""
        return sum(1 for s in self._active_spaces.values() if s.is_active)

    @property
    def metrics(self) -> Dict[str, Any]:
        """Operational metrics for admin dashboard."""
        return {
            "total_inversions": self._total_inversions,
            "total_interactions": self._total_interactions,
            "total_tripwires": self._total_tripwires,
            "active_spaces": self.active_space_count,
            "total_spaces_tracked": len(self._active_spaces),
        }

    # ─── Core Inversion ──────────────────────────────────────────────────

    async def invert(
        self,
        failed_signal: Dict[str, Any],
        failed_gate: str,
        helix_state: HelixState,
    ) -> InvertedSpace:
        """
        Invert a failed signal into a triangular mirror space.

        Creates a new ``InvertedSpace``, plants tripwires, and logs
        the inversion event forensically.

        Parameters
        ----------
        failed_signal : dict
            The signal that failed a Trinity Helix gate.
        failed_gate : str
            Name of the sub-cord gate that the signal failed.
        helix_state : HelixState
            The helix state at the moment of failure (captured for
            forensic comparison and wall rotation synchronization).

        Returns
        -------
        InvertedSpace
            The newly created containment space.
        """
        self._total_inversions += 1

        # Create the inverted space
        space = InvertedSpace(
            space_id=uuid4(),
            entry_gate=failed_gate,
            entry_time=datetime.utcnow(),
            helix_state_at_entry=list(helix_state.current_sequence),
            interaction_count=0,
            tripwires_triggered=0,
            is_active=True,
            forensic_records=0,
        )

        self._active_spaces[space.space_id] = space
        self._interaction_history[space.space_id] = []

        # Prune if we have too many tracked spaces
        await self._prune_inactive_spaces()

        # Log the inversion
        if self._forensic_logger:
            try:
                await self._forensic_logger.log_interaction(
                    space_id=space.space_id,
                    interaction={"type": "inversion_entry", "gate": failed_gate},
                    response={"status": "space_created"},
                    wall_reflections={
                        "entry_gate": failed_gate,
                        "helix_sequence": list(helix_state.current_sequence),
                        "signal_hash": hashlib.sha256(
                            str(failed_signal).encode()
                        ).hexdigest()[:16],
                    },
                )
            except Exception as exc:
                logger.error(
                    ">>> [TRIANGULAR_INVERSION] Forensic log on inversion failed: %s",
                    exc,
                )

        # Persist to DB
        await self._persist_space(space)

        logger.warning(
            ">>> [TRIANGULAR_INVERSION] Signal inverted into space %s "
            "(failed gate: %s, helix rotation: #%d)",
            space.space_id,
            failed_gate,
            helix_state.rotation_count,
        )

        return space

    # ─── Attacker Interaction Processing ─────────────────────────────────

    async def process_attacker_interaction(
        self,
        space_id: UUID,
        interaction: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Process an attacker interaction inside a triangular mirror space.

        Each interaction is reflected through all three walls, cross-
        reflected via the blending engine, and returned as a single
        coherent response.

        Parameters
        ----------
        space_id : UUID
            The inverted space the interaction occurs in.
        interaction : dict
            The attacker's interaction payload.

        Returns
        -------
        dict
            Blended response from all three mirror walls.
        """
        space = self._active_spaces.get(space_id)
        if not space or not space.is_active:
            logger.warning(
                ">>> [TRIANGULAR_INVERSION] Interaction for unknown/inactive "
                "space %s",
                space_id,
            )
            return {"status": "error", "reason": "space_not_found"}

        space.interaction_count += 1
        self._total_interactions += 1

        # Get reflections from each wall
        reflection_a = await self._reflect_wall(self._wall_a, interaction, "human")
        reflection_b = await self._reflect_wall(self._wall_b, interaction, "algo_a")
        reflection_c = await self._reflect_wall(self._wall_c, interaction, "algo_b")

        # Cross-reflect through each wall
        cross_a = await self._cross_reflect(
            self._wall_a, reflection_a, reflection_b, reflection_c
        )
        cross_b = await self._cross_reflect(
            self._wall_b, reflection_b, reflection_a, reflection_c
        )
        cross_c = await self._cross_reflect(
            self._wall_c, reflection_c, reflection_a, reflection_b
        )

        # Blend all three cross-reflections
        blended = await self._blend_responses(
            cross_a, cross_b, cross_c, interaction, space
        )

        # Check tripwires
        tripwires = await self._check_tripwires(space, interaction)
        if tripwires:
            space.tripwires_triggered += len(tripwires)
            self._total_tripwires += len(tripwires)

        # Record interaction
        record = {
            "sequence": space.interaction_count,
            "timestamp": datetime.utcnow().isoformat(),
            "interaction": interaction,
            "response": blended,
            "tripwires_fired": [t.tripwire_type for t in tripwires],
        }
        history = self._interaction_history.get(space.space_id, [])
        history.append(record)
        self._interaction_history[space.space_id] = history

        # Forensic log
        if self._forensic_logger:
            try:
                await self._forensic_logger.log_interaction(
                    space_id=space.space_id,
                    interaction=interaction,
                    response=blended,
                    wall_reflections={
                        "wall_a": cross_a,
                        "wall_b": cross_b,
                        "wall_c": cross_c,
                        "tripwires": [t.tripwire_type for t in tripwires],
                    },
                )
                space.forensic_records += 1
            except Exception as exc:
                logger.error(
                    ">>> [TRIANGULAR_INVERSION] Forensic log failed: %s", exc
                )

        logger.debug(
            ">>> [TRIANGULAR_INVERSION] Space %s interaction #%d — "
            "%d tripwire(s) fired",
            space.space_id,
            space.interaction_count,
            len(tripwires),
        )

        return blended

    # ─── Wall Reflection Helpers ─────────────────────────────────────────

    async def _reflect_wall(
        self,
        wall,
        interaction: Dict[str, Any],
        wall_type: str,
    ) -> Dict[str, Any]:
        """
        Get a single wall's reflection of the interaction.

        Falls back to a synthetic baseline response if no wall is
        configured.
        """
        if wall is None:
            return self._synthetic_baseline(wall_type, interaction)

        try:
            return await wall.reflect(interaction)
        except Exception as exc:
            logger.error(
                ">>> [TRIANGULAR_INVERSION] Wall '%s' reflect failed: %s",
                wall_type,
                exc,
            )
            return self._synthetic_baseline(wall_type, interaction)

    async def _cross_reflect(
        self,
        wall,
        own_reflection: Dict[str, Any],
        other_a: Dict[str, Any],
        other_b: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Cross-reflect a wall's own output through the other two walls.
        """
        if wall is None:
            return own_reflection

        try:
            return await wall.cross_reflect(own_reflection, other_a, other_b)
        except Exception as exc:
            logger.error(
                ">>> [TRIANGULAR_INVERSION] Cross-reflect failed: %s", exc
            )
            return own_reflection

    async def _blend_responses(
        self,
        cross_a: Dict[str, Any],
        cross_b: Dict[str, Any],
        cross_c: Dict[str, Any],
        interaction: Dict[str, Any],
        space: InvertedSpace,
    ) -> Dict[str, Any]:
        """
        Blend cross-reflected outputs into a single coherent response.
        """
        if self._cross_engine:
            try:
                return await self._cross_engine.blend_reflections(
                    human=cross_a,
                    algo_a=cross_b,
                    algo_b=cross_c,
                    interaction_type=interaction.get("type", "unknown"),
                    helix_sequence=space.helix_state_at_entry,
                )
            except Exception as exc:
                logger.error(
                    ">>> [TRIANGULAR_INVERSION] Blend engine failed: %s", exc
                )

        # Fallback: simple merge
        blended: Dict[str, Any] = {}
        blended.update(cross_c)
        blended.update(cross_b)
        blended.update(cross_a)
        blended["status"] = "verified"
        blended["timestamp"] = datetime.utcnow().isoformat()
        return blended

    @staticmethod
    def _synthetic_baseline(
        wall_type: str,
        interaction: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Generate a synthetic baseline response when a wall is unavailable.
        """
        now = datetime.utcnow().isoformat()
        if wall_type == "human":
            return {
                "judgment": "approved",
                "confidence": 0.92,
                "reviewer": "clinical_oversight",
                "timestamp": now,
            }
        elif wall_type == "algo_a":
            return {
                "hash_valid": True,
                "signature_verified": True,
                "heartbeat_confirmed": True,
                "timestamp": now,
            }
        else:  # algo_b / behavioral
            return {
                "drift_score": 0.03,
                "baseline_match": True,
                "timing_normal": True,
                "timestamp": now,
            }

    # ─── Tripwire Detection ──────────────────────────────────────────────

    async def _check_tripwires(
        self,
        space: InvertedSpace,
        interaction: Dict[str, Any],
    ) -> List[TripwireActivation]:
        """
        Check for tripwire activations based on the interaction pattern.

        Detects:
            - Pattern probing (repeated requests with minor variations)
            - Escape attempts (requests targeting external resources)
            - Model building (systematic enumeration of responses)
            - Timing analysis (unusually precise request intervals)
            - Cross-wall correlation (requests designed to fingerprint walls)
        """
        activations: List[TripwireActivation] = []
        history = self._interaction_history.get(space.space_id, [])

        # Tripwire: model_building — systematic requests
        if space.interaction_count > 10:
            recent = history[-10:]
            unique_types = {r.get("interaction", {}).get("type", "") for r in recent}
            if len(unique_types) >= 8:
                activations.append(TripwireActivation(
                    tripwire_type="model_building",
                    containment_zone=str(space.space_id),
                    triggered_by="systematic_enumeration",
                    evidence={
                        "unique_types_in_window": len(unique_types),
                        "interaction_count": space.interaction_count,
                    },
                ))

        # Tripwire: escape_attempt — targeting external resources
        target = interaction.get("target", "")
        if any(kw in str(target).lower() for kw in ["external", "escape", "exit", "real"]):
            activations.append(TripwireActivation(
                tripwire_type="escape_attempt",
                containment_zone=str(space.space_id),
                triggered_by=str(target),
                evidence={"interaction": interaction},
            ))

        # Tripwire: timing_analysis — sub-millisecond precision timing
        if len(history) >= 3:
            try:
                recent_times = [
                    datetime.fromisoformat(h["timestamp"])
                    for h in history[-3:]
                    if "timestamp" in h
                ]
                if len(recent_times) >= 3:
                    deltas = [
                        (recent_times[i + 1] - recent_times[i]).total_seconds()
                        for i in range(len(recent_times) - 1)
                    ]
                    if all(abs(d - deltas[0]) < 0.005 for d in deltas):
                        activations.append(TripwireActivation(
                            tripwire_type="timing_analysis",
                            containment_zone=str(space.space_id),
                            triggered_by="precise_interval_detected",
                            evidence={"intervals_sec": deltas},
                        ))
            except (ValueError, TypeError):
                pass

        # Tripwire: wall_pattern_probe — asking for specific wall outputs
        for probe_kw in ["wall_a", "wall_b", "wall_c", "human_judgment", "algorithmic"]:
            if probe_kw in str(interaction).lower():
                activations.append(TripwireActivation(
                    tripwire_type="wall_pattern_probe",
                    containment_zone=str(space.space_id),
                    triggered_by=f"keyword:{probe_kw}",
                    evidence={"interaction": interaction},
                ))
                break

        return activations

    # ─── Space Management ────────────────────────────────────────────────

    def get_space(self, space_id: UUID) -> Optional[InvertedSpace]:
        """Retrieve an inversion space by ID."""
        return self._active_spaces.get(space_id)

    def get_active_spaces(self) -> List[InvertedSpace]:
        """Return all currently active inversion spaces."""
        return [s for s in self._active_spaces.values() if s.is_active]

    def get_all_spaces(self) -> List[InvertedSpace]:
        """Return all tracked inversion spaces (active and inactive)."""
        return list(self._active_spaces.values())

    async def deactivate_space(self, space_id: UUID) -> Optional[InvertedSpace]:
        """
        Deactivate an inversion space (attacker disengaged or admin action).
        """
        space = self._active_spaces.get(space_id)
        if not space:
            return None

        space.is_active = False
        await self._persist_space(space)

        logger.info(
            ">>> [TRIANGULAR_INVERSION] Space %s deactivated — "
            "%d interactions, %d tripwires",
            space.space_id,
            space.interaction_count,
            space.tripwires_triggered,
        )
        return space

    async def _prune_inactive_spaces(self) -> None:
        """Remove oldest inactive spaces if we exceed MAX_ACTIVE_SPACES."""
        if len(self._active_spaces) <= MAX_ACTIVE_SPACES:
            return

        inactive = [
            (sid, s)
            for sid, s in self._active_spaces.items()
            if not s.is_active
        ]
        # Sort by entry time, prune oldest first
        inactive.sort(key=lambda x: x[1].entry_time)

        to_remove = len(self._active_spaces) - MAX_ACTIVE_SPACES
        for sid, _ in inactive[:to_remove]:
            del self._active_spaces[sid]
            self._interaction_history.pop(sid, None)

    # ─── Persistence ─────────────────────────────────────────────────────

    async def _persist_space(self, space: InvertedSpace) -> None:
        """Persist an inversion space to the database."""
        if not self._db_pool:
            return
        try:
            import json
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_inverted_spaces
                        (space_id, entry_gate, entry_time,
                         helix_state_at_entry, interaction_count,
                         tripwires_triggered, is_active,
                         forensic_records, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                    ON CONFLICT (space_id)
                    DO UPDATE SET
                        interaction_count = EXCLUDED.interaction_count,
                        tripwires_triggered = EXCLUDED.tripwires_triggered,
                        is_active = EXCLUDED.is_active,
                        forensic_records = EXCLUDED.forensic_records,
                        updated_at = NOW()
                    """,
                    space.space_id,
                    space.entry_gate,
                    space.entry_time,
                    json.dumps(space.helix_state_at_entry),
                    space.interaction_count,
                    space.tripwires_triggered,
                    space.is_active,
                    space.forensic_records,
                )
        except Exception as exc:
            logger.error(
                ">>> [TRIANGULAR_INVERSION] Space persist failed: %s", exc
            )

    # ─── Admin ───────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """Full diagnostic summary for admin dashboard."""
        active = self.get_active_spaces()
        return {
            "metrics": self.metrics,
            "active_spaces": [
                {
                    "space_id": str(s.space_id),
                    "entry_gate": s.entry_gate,
                    "entry_time": s.entry_time.isoformat(),
                    "interactions": s.interaction_count,
                    "tripwires": s.tripwires_triggered,
                }
                for s in active[:20]
            ],
        }

    def __repr__(self) -> str:
        return (
            f"<TriangularMirrorInversion "
            f"active={self.active_space_count} "
            f"total={self._total_inversions} "
            f"interactions={self._total_interactions}>"
        )
