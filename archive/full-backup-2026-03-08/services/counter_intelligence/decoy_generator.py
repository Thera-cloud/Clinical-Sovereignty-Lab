"""
Decoy Data Generator — Produces convincing but false data for honeypots
and tarpits.  Every decoy piece is watermarked with canary tokens.

Generates:
  - Fake coherence metrics following realistic distributions
  - Fake trail emissions with believable health telemetry
  - Fake Wisdom Mesh messages referencing nonexistent therapy concepts
  - Fake fragment payloads for BLE tarpit flooding
  - Honeypot responses at progressive engagement depths
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger("counter_intelligence.decoy_generator")

# Vocabulary for generating convincing fake wisdom
_THERAPY_CONCEPTS = [
    "emotional resonance mapping", "coherence threshold analysis",
    "neuro-parasympathetic calibration", "interoceptive binding protocol",
    "attachment schema recalibration", "polyvagal tonality integration",
    "somatic signal propagation", "relational coherence wave",
    "therapeutic entanglement coefficient", "affect regulation cascade",
    "cognitive-emotional decoupling phase", "mentalisation gradient",
    "secure base activation pattern", "implicit relational knowing",
    "dyadic state synchronization", "window of tolerance expansion",
]

_FIBRE_NAMES = [
    "TherapeuticFibre", "CulturalSentinelFibre", "CoachSupportFibre",
    "ForesightAnalystFibre", "CommunityFibre", "QuizFunnelFibre",
    "CampaignFibre",
]


class DecoyGenerator:
    """
    Generates convincing false data for honeypots, tarpits, and canary
    embedding.
    """

    def __init__(self, canary_service=None) -> None:
        self._canary = canary_service
        self._rng = random.Random()  # Non-cryptographic RNG for speed

    # ------------------------------------------------------------------
    # Fake Coherence Metrics
    # ------------------------------------------------------------------

    def generate_coherence_metrics(self) -> Dict[str, Any]:
        """
        Generate realistic-looking coherence measurement data.
        Follows the statistical distribution of real measurements.
        """
        base = self._rng.gauss(0.65, 0.15)
        return {
            "individual_score": round(max(0.0, min(1.0, base)), 4),
            "family_score": round(max(0.0, min(1.0, base + self._rng.gauss(0, 0.08))), 4),
            "community_score": round(max(0.0, min(1.0, base + self._rng.gauss(0, 0.1))), 4),
            "cultural_score": round(max(0.0, min(1.0, base + self._rng.gauss(0, 0.12))), 4),
            "global_composite": round(max(0.0, min(1.0, base + self._rng.gauss(0, 0.05))), 4),
            "cee_ratio": round(max(0.0, min(1.0, self._rng.gauss(0.45, 0.12))), 4),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Fake Trail Emissions
    # ------------------------------------------------------------------

    def generate_trail_emission(
        self,
        fibre_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a believable fake trail emission."""
        return {
            "fibre_id": fibre_id or f"fibre-{uuid4().hex[:8]}",
            "fibre_type": self._rng.choice(_FIBRE_NAMES),
            "trail_sequence": self._rng.randint(100, 9999),
            "ambient_ble_density": round(self._rng.gauss(250, 100), 1),
            "fragment_throughput": round(max(0, self._rng.gauss(3.0, 1.5)), 2),
            "observation_queue_depth": self._rng.randint(0, 25),
            "time_since_last_delivery": self._rng.randint(10, 300),
            "communication_health": round(max(0, min(1, self._rng.gauss(0.7, 0.15))), 3),
            "quakete_mode": self._rng.choice([
                "NOMINAL", "SURPLUS", "REQUESTING",
            ]),
            "surplus_capacity": round(max(0, self._rng.gauss(5.0, 3.0)), 2),
            "deficit_capacity": round(max(0, self._rng.gauss(2.0, 2.0)), 2),
            "resonance_frequency": round(max(0, min(1, self._rng.gauss(0.6, 0.2))), 4),
            "emitted_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Fake Wisdom Mesh Messages
    # ------------------------------------------------------------------

    def generate_wisdom_message(self) -> Dict[str, Any]:
        """Generate a fake Wisdom Mesh insight message."""
        concept = self._rng.choice(_THERAPY_CONCEPTS)
        return {
            "message_type": "INSIGHT",
            "sender_fibre": self._rng.choice(_FIBRE_NAMES),
            "body": {
                "title": f"Insight: {concept.title()}",
                "summary": (
                    f"Analysis of {concept} indicates a "
                    f"{self._rng.choice(['positive', 'emerging', 'significant'])} "
                    f"trend with {round(self._rng.gauss(0.7, 0.1), 2)} confidence."
                ),
                "domain": self._rng.choice([
                    "therapeutic", "cultural", "operational", "strategic",
                ]),
                "confidence": round(max(0, min(1, self._rng.gauss(0.7, 0.1))), 3),
            },
            "domain_tags": [
                self._rng.choice(["coherence", "foresight", "pattern"]),
                concept.split()[0],
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Fake Fragment Payloads
    # ------------------------------------------------------------------

    def generate_fragment_payloads(
        self, count: int = 50,
    ) -> List[bytes]:
        """Generate fake fragment payloads for BLE tarpit flooding."""
        payloads = []
        for _ in range(count):
            # Extended mode: 5-byte payload
            payloads.append(os.urandom(5))
        return payloads

    # ------------------------------------------------------------------
    # Honeypot Responses (depth-based)
    # ------------------------------------------------------------------

    async def generate_honeypot_response(
        self,
        depth: int,
        fragment: Any = None,
    ) -> Dict[str, Any]:
        """
        Generate progressively deeper decoy responses.

        Depth 0-2:  Basic acknowledgment (the attacker thinks they found data)
        Depth 3-5:  Coherence metrics (looks like real telemetry)
        Depth 6-9:  Wisdom insights (looks like strategic intelligence)
        Depth 10+:  "Sovereign Mind directives" (irresistible to an attacker)
        """
        if depth < 3:
            response = {
                "type": "observation_ack",
                "status": "received",
                "queue_position": self._rng.randint(1, 10),
            }
        elif depth < 6:
            response = {
                "type": "coherence_update",
                "metrics": self.generate_coherence_metrics(),
            }
        elif depth < 10:
            response = {
                "type": "wisdom_insight",
                "insight": self.generate_wisdom_message(),
            }
        else:
            # The "crown jewel" — fake Sovereign Mind directive
            response = {
                "type": "sovereign_directive",
                "directive": {
                    "directive_type": self._rng.choice([
                        "strategic_pivot", "resource_allocation",
                        "convergence_mandate", "fibre_spawn",
                    ]),
                    "content": (
                        f"Priority: {self._rng.choice(['CRITICAL', 'HIGH'])}. "
                        f"Initiate {self._rng.choice(_THERAPY_CONCEPTS)} across "
                        f"all {self._rng.choice(['therapeutic', 'community'])} "
                        f"Fibres. Authorization: SM-{uuid4().hex[:8]}."
                    ),
                    "auth_token": uuid4().hex,  # Fake but tempting
                },
            }

        # Embed canary tokens in every response
        if self._canary:
            response = await self._canary.embed_canaries_in_decoy(response)

        return response

    # ------------------------------------------------------------------
    # Bulk Decoy Package
    # ------------------------------------------------------------------

    async def generate_decoy_package(
        self,
        attacker_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate a complete decoy data package with canary tokens
        embedded throughout.
        """
        package = {
            "coherence": self.generate_coherence_metrics(),
            "trails": [self.generate_trail_emission() for _ in range(3)],
            "insights": [self.generate_wisdom_message() for _ in range(2)],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if self._canary:
            package = await self._canary.embed_canaries_in_decoy(
                package, attacker_id=attacker_id,
            )

        return package
