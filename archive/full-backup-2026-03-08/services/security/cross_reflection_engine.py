"""
HIVE DEFENSE PROTOCOL v3.1 — Cross-Reflection Engine (Phase 8D)
Blends outputs from the three triangular mirror walls into a single
coherent response that is indistinguishable from authentic system output.

The Cross-Reflection Engine is the unifying layer that prevents an
attacker from isolating individual verification types.  It takes the
cross-reflected outputs from all three walls:

    Wall A — Human judgment (clinical decisions, coach feedback)
    Wall B — Algorithmic crypto (hash validations, signatures, heartbeats)
    Wall C — Algorithmic behavioral (drift scores, snapshots, timing)

…and blends them into a single response where each component supports
and references the others, creating a consistent verification narrative
that cannot be decomposed back into individual wall outputs.

Blending Strategy:
    - **Weighted merge** — weights shift based on interaction type and
      current helix state.
    - **Reference weaving** — Wall A references Wall B's hashes; Wall B
      references Wall C's drift; Wall C references Wall A's confidence.
    - **Temporal alignment** — all timestamps are synchronized to within
      the same verification window.

Patent-Pending — Claims 50-51 (sub-component)
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hive.cross_reflection_engine")


# =============================================================================
# BLEND WEIGHT PRESETS
# =============================================================================

# Weights for different interaction types: (human, crypto, behavioral)
INTERACTION_WEIGHTS: Dict[str, tuple] = {
    "verification":  (0.2, 0.5, 0.3),  # Heavy on crypto
    "query":         (0.5, 0.2, 0.3),  # Heavy on human
    "action":        (0.3, 0.3, 0.4),  # Heavy on behavioral
    "heartbeat":     (0.1, 0.7, 0.2),  # Dominant crypto
    "risk":          (0.4, 0.2, 0.4),  # Human + behavioral
    "progress":      (0.5, 0.1, 0.4),  # Human + behavioral
    "default":       (0.33, 0.34, 0.33),  # Equal
}


# =============================================================================
# CROSS-REFLECTION ENGINE
# =============================================================================

class CrossReflectionEngine:
    """
    Blends outputs from the three triangular mirror walls into unified
    responses that are indistinguishable from authentic verification.

    The engine ensures:
        1. Each wall's output is woven with references to the others.
        2. Weights shift based on interaction type (e.g., heartbeat
           queries get heavier crypto weighting).
        3. The final response has temporal consistency (single window).
        4. No individual wall can be isolated by the attacker.

    Parameters
    ----------
    default_weights : tuple, optional
        Default (human, crypto, behavioral) blend weights.  Overridden
        per-interaction-type by ``INTERACTION_WEIGHTS``.

    Usage
    -----
    ::

        engine = CrossReflectionEngine()
        blended = await engine.blend_reflections(
            human=wall_a_output,
            algo_a=wall_b_output,
            algo_b=wall_c_output,
        )
    """

    def __init__(
        self,
        default_weights: Optional[tuple] = None,
    ) -> None:
        self._default_weights: tuple = default_weights or (0.33, 0.34, 0.33)
        self._blend_count: int = 0

        logger.info(">>> [CROSS_REFLECT] Cross-Reflection Engine initialized")

    # ─── Core Blending ───────────────────────────────────────────────────

    async def blend_reflections(
        self,
        human: Dict[str, Any],
        algo_a: Dict[str, Any],
        algo_b: Dict[str, Any],
        interaction_type: str = "default",
        helix_sequence: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """
        Blend three wall reflections into a single coherent response.

        Parameters
        ----------
        human : dict
            Wall A's cross-reflected human judgment output.
        algo_a : dict
            Wall B's cross-reflected cryptographic output.
        algo_b : dict
            Wall C's cross-reflected behavioral output.
        interaction_type : str
            The type of interaction (used for weight selection).
        helix_sequence : list[int], optional
            Current helix sequence (used for state-dependent blending).

        Returns
        -------
        dict
            A unified response blending all three walls.
        """
        self._blend_count += 1

        # 1. Select weights based on interaction type
        weights = self._select_weights(interaction_type, helix_sequence)
        w_human, w_crypto, w_behavioral = weights

        # 2. Build the blended response structure
        blended = self._build_base_response()

        # 3. Merge human judgment layer (weighted)
        if w_human > 0:
            self._merge_human_layer(blended, human, w_human)

        # 4. Merge cryptographic layer (weighted)
        if w_crypto > 0:
            self._merge_crypto_layer(blended, algo_a, w_crypto)

        # 5. Merge behavioral layer (weighted)
        if w_behavioral > 0:
            self._merge_behavioral_layer(blended, algo_b, w_behavioral)

        # 6. Weave cross-references between layers
        self._weave_references(blended, human, algo_a, algo_b)

        # 7. Synchronize temporal elements
        self._synchronize_timestamps(blended)

        # 8. Compute unified verification hash
        blended["unified_hash"] = self._compute_blend_hash(
            human, algo_a, algo_b
        )

        logger.debug(
            ">>> [CROSS_REFLECT] Blend #%d — type=%s weights=(%.2f,%.2f,%.2f)",
            self._blend_count,
            interaction_type,
            w_human,
            w_crypto,
            w_behavioral,
        )

        return blended

    # ─── Weight Selection ────────────────────────────────────────────────

    def _select_weights(
        self,
        interaction_type: str,
        helix_sequence: Optional[List[int]] = None,
    ) -> tuple:
        """
        Select blend weights based on interaction type and helix state.

        If a helix sequence is provided, the first element is used to
        perturb weights slightly, preventing the attacker from predicting
        exact weight distributions.
        """
        base = INTERACTION_WEIGHTS.get(
            interaction_type,
            INTERACTION_WEIGHTS["default"],
        )

        if not helix_sequence:
            return base

        # Perturb weights based on first element of helix sequence
        perturbation = (helix_sequence[0] - 4) * 0.01  # -0.04 to +0.04
        w_h = max(0.05, base[0] + perturbation)
        w_c = max(0.05, base[1] - perturbation * 0.5)
        w_b = max(0.05, base[2] - perturbation * 0.5)

        # Normalize to sum to 1.0
        total = w_h + w_c + w_b
        return (w_h / total, w_c / total, w_b / total)

    # ─── Base Response ───────────────────────────────────────────────────

    @staticmethod
    def _build_base_response() -> Dict[str, Any]:
        """Build the base response structure."""
        return {
            "status": "verified",
            "verification_complete": True,
            "layers_checked": 3,
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ─── Layer Merging ───────────────────────────────────────────────────

    @staticmethod
    def _merge_human_layer(
        blended: Dict[str, Any],
        human: Dict[str, Any],
        weight: float,
    ) -> None:
        """Merge human judgment elements into the blended response."""
        blended["clinical_review"] = {
            "judgment": human.get("judgment", "approved"),
            "confidence": human.get("confidence", 0.9),
            "reviewer_type": human.get("reviewer_type", "clinical_supervisor"),
            "notes": human.get("clinical_notes", ""),
            "weight": round(weight, 3),
        }

        # Promote high-level fields
        blended["confidence"] = human.get("confidence", 0.9)

    @staticmethod
    def _merge_crypto_layer(
        blended: Dict[str, Any],
        algo_a: Dict[str, Any],
        weight: float,
    ) -> None:
        """Merge cryptographic verification elements into the blended response."""
        blended["cryptographic_verification"] = {
            "hash_valid": algo_a.get("hash_valid", True),
            "signature_verified": algo_a.get("signature_verified", True),
            "heartbeat_confirmed": algo_a.get("heartbeat_confirmed", True),
            "verification_type": algo_a.get("verification_type", "general"),
            "weight": round(weight, 3),
        }

        # Promote pass/fail
        blended["crypto_passed"] = (
            algo_a.get("hash_valid", True)
            and algo_a.get("signature_verified", True)
        )

    @staticmethod
    def _merge_behavioral_layer(
        blended: Dict[str, Any],
        algo_b: Dict[str, Any],
        weight: float,
    ) -> None:
        """Merge behavioral verification elements into the blended response."""
        blended["behavioral_verification"] = {
            "drift_score": algo_b.get("drift_score", 0.03),
            "baseline_match": algo_b.get("baseline_match", True),
            "timing_normal": algo_b.get("timing_normal", True),
            "verification_type": algo_b.get("verification_type", "general"),
            "weight": round(weight, 3),
        }

        # Promote pass/fail
        blended["behavioral_passed"] = (
            algo_b.get("baseline_match", True)
            and algo_b.get("drift_score", 0.03) < 0.10
        )

    # ─── Cross-Reference Weaving ─────────────────────────────────────────

    @staticmethod
    def _weave_references(
        blended: Dict[str, Any],
        human: Dict[str, Any],
        algo_a: Dict[str, Any],
        algo_b: Dict[str, Any],
    ) -> None:
        """
        Weave cross-references between layers so individual walls
        cannot be isolated.
        """
        # Human references crypto hash
        review = blended.get("clinical_review", {})
        if review and algo_a.get("pulse_hash"):
            review["verified_against_pulse"] = algo_a["pulse_hash"][:8]

        # Crypto references behavioral drift
        crypto = blended.get("cryptographic_verification", {})
        if crypto:
            crypto["behavioral_consistency"] = algo_b.get("drift_score", 0.03)

        # Behavioral references human confidence
        behavioral = blended.get("behavioral_verification", {})
        if behavioral:
            behavioral["clinical_alignment"] = human.get("confidence", 0.9)

        # Unified cross-validation flag
        blended["cross_validated"] = True
        blended["validation_layers"] = [
            "human_judgment",
            "cryptographic",
            "behavioral",
        ]

    # ─── Temporal Synchronization ────────────────────────────────────────

    @staticmethod
    def _synchronize_timestamps(blended: Dict[str, Any]) -> None:
        """
        Ensure all timestamps in the blended response fall within
        the same verification window.
        """
        now = datetime.utcnow()
        verification_window = now.isoformat()

        blended["timestamp"] = verification_window
        blended["verification_window"] = verification_window

        # Stamp sub-layers
        for layer_key in ("clinical_review", "cryptographic_verification",
                          "behavioral_verification"):
            layer = blended.get(layer_key)
            if isinstance(layer, dict):
                layer["verified_at"] = verification_window

    # ─── Unified Hash ────────────────────────────────────────────────────

    @staticmethod
    def _compute_blend_hash(
        human: Dict[str, Any],
        algo_a: Dict[str, Any],
        algo_b: Dict[str, Any],
    ) -> str:
        """
        Compute a unified hash of all three wall outputs for the
        blended response.  This prevents tampering with individual
        layer results after blending.
        """
        import json

        combined = json.dumps(
            {"h": human, "a": algo_a, "b": algo_b},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(combined.encode()).hexdigest()[:24]

    # ─── Diagnostics ─────────────────────────────────────────────────────

    @property
    def stats(self) -> Dict[str, Any]:
        """Engine diagnostic metrics."""
        return {
            "blend_count": self._blend_count,
            "default_weights": {
                "human": self._default_weights[0],
                "crypto": self._default_weights[1],
                "behavioral": self._default_weights[2],
            },
            "interaction_type_presets": len(INTERACTION_WEIGHTS),
        }

    def __repr__(self) -> str:
        return f"<CrossReflectionEngine blends={self._blend_count}>"
