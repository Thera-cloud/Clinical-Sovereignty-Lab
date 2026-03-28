"""
SOVEREIGN SWARM — Lorentz Force Fragment Acceleration (Patent Claim 26.5)
"""

from __future__ import annotations

from typing import Any

from app.models.quakete import FragmentAcceleration

from .constants import (
    LORENTZ_CAP_ASSEMBLY,
    LORENTZ_CAP_DETECTION,
    LORENTZ_CAP_EMBEDDING,
    LORENTZ_CAP_FORWARDING,
    PARTICLE_BEAM_HALF_LIFE_SECONDS,
)


# =============================================================================
# LORENTZ FORCE ACCELERATOR
# =============================================================================


class LorentzForceAccelerator:
    """
    Digital analogue of the Lorentz force F=q(E+v×B). Converts Quakete energy
    into directed acceleration at each stage of the ZEFCP pipeline. Detection
    sensitivity, embedding priority, assembly priority, and cloud forwarding
    all receive proportional boosts capped by safety limits.
    """

    def __init__(self) -> None:
        pass

    # -------------------------------------------------------------------------
    # ACCELERATION COMPUTATION
    # -------------------------------------------------------------------------

    def compute_acceleration(self, quakete_energy: float) -> FragmentAcceleration:
        """
        Compute FragmentAcceleration from quakete_energy with Lorentz caps.
        """
        detection = min(1.0 + quakete_energy * 2.0, LORENTZ_CAP_DETECTION)
        embedding = min(1.0 + quakete_energy * 1.0, LORENTZ_CAP_EMBEDDING)
        assembly = min(1.0 + quakete_energy * 1.0, LORENTZ_CAP_ASSEMBLY)
        forwarding = min(1.0 + quakete_energy * 2.0, LORENTZ_CAP_FORWARDING)
        total = detection + embedding + assembly + forwarding
        return FragmentAcceleration(
            detection_sensitivity_boost=detection,
            embedding_priority_boost=embedding,
            reassembly_priority_boost=assembly,
            cloud_forwarding_priority=forwarding,
            total_acceleration=total,
        )

    def apply_to_spider_web(
        self, acceleration: FragmentAcceleration, spider_web: Any
    ) -> None:
        """Set spider_web sensitivity_multiplier."""
        if hasattr(spider_web, "sensitivity_multiplier"):
            spider_web.sensitivity_multiplier = acceleration.detection_sensitivity_boost
        elif hasattr(spider_web, "sensitivity"):
            spider_web.sensitivity = acceleration.detection_sensitivity_boost

    def apply_to_fragment_buffer(
        self, acceleration: FragmentAcceleration, buffer: Any
    ) -> None:
        """Set buffer priority_multiplier."""
        if hasattr(buffer, "priority_multiplier"):
            buffer.priority_multiplier = acceleration.reassembly_priority_boost
        elif hasattr(buffer, "embedding_priority"):
            buffer.embedding_priority = acceleration.embedding_priority_boost

    def decay_acceleration(
        self,
        acceleration: FragmentAcceleration,
        elapsed_seconds: float,
        half_life: float = PARTICLE_BEAM_HALF_LIFE_SECONDS,
    ) -> FragmentAcceleration:
        """
        Apply exponential decay: value = 1.0 + (value - 1.0) * 0.5^(elapsed/half_life)
        for each field.
        """
        factor = 0.5 ** (elapsed_seconds / half_life)
        detection = 1.0 + (acceleration.detection_sensitivity_boost - 1.0) * factor
        embedding = 1.0 + (acceleration.embedding_priority_boost - 1.0) * factor
        assembly = 1.0 + (acceleration.reassembly_priority_boost - 1.0) * factor
        forwarding = 1.0 + (acceleration.cloud_forwarding_priority - 1.0) * factor
        total = detection + embedding + assembly + forwarding
        return FragmentAcceleration(
            detection_sensitivity_boost=detection,
            embedding_priority_boost=embedding,
            reassembly_priority_boost=assembly,
            cloud_forwarding_priority=forwarding,
            total_acceleration=total,
        )
