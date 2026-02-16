"""
Honeypot Fibre System — Deploys fake Fibres that look like high-value targets.

Honeypot Fibres:
  - Accept all incoming fragments (no rejection)
  - Log every interaction with full forensic detail
  - Respond with believable but tracked decoy data
  - Gradually reveal "deeper" fake intelligence to keep attackers engaged
  - Never contain real user data
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4

logger = logging.getLogger("counter_intelligence.honeypot")


class HoneypotFibre:
    """
    A fake Fibre designed to attract and study attackers.

    Each honeypot has an engagement_depth that increases with every
    interaction, progressively revealing deeper (but always fake)
    intelligence to keep the attacker invested.
    """

    def __init__(
        self,
        honeypot_id: Optional[UUID] = None,
        fibre_id: str = "hp-fibre-001",
        fibre_type: str = "TherapeuticFibre",
        target_attacker_id: Optional[str] = None,
    ) -> None:
        self.honeypot_id = honeypot_id or uuid4()
        self.fibre_id = fibre_id
        self.fibre_type = fibre_type
        self.target_attacker_id = target_attacker_id
        self.engagement_depth: int = 0
        self.interactions: List[Dict[str, Any]] = []
        self.created_at = datetime.now(timezone.utc)
        self.active = True

    async def on_fragment_received(
        self,
        fragment: Any,
        source_device: str,
        threat_db=None,
        decoy_generator=None,
    ) -> Optional[Dict[str, Any]]:
        """
        Handle a fragment received by this honeypot.
        Logs everything, feeds attacker deeper.
        """
        interaction = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_device": source_device,
            "fragment_type": getattr(fragment, "mode", "unknown"),
            "fragment_sequence": getattr(fragment, "sequence", -1),
            "fragment_total": getattr(fragment, "total", -1),
            "payload_size": len(getattr(fragment, "payload", b"")),
            "rssi": getattr(fragment, "rssi", None),
            "engagement_depth": self.engagement_depth,
        }
        self.interactions.append(interaction)

        # Log to threat DB
        if threat_db and self.target_attacker_id:
            try:
                await threat_db.log_event(
                    profile_id=UUID(self.target_attacker_id)
                    if isinstance(self.target_attacker_id, str)
                    and len(self.target_attacker_id) == 36
                    else uuid4(),
                    event_type="honeypot_contact",
                    event_data=interaction,
                    source_layer="ble",
                )
            except Exception:
                pass

        # Generate deeper decoy response
        decoy_response = None
        if decoy_generator:
            decoy_response = await decoy_generator.generate_honeypot_response(
                depth=self.engagement_depth,
                fragment=fragment,
            )

        self.engagement_depth += 1

        logger.info(
            "Honeypot %s: depth=%d source=%s",
            self.fibre_id, self.engagement_depth, source_device,
        )

        return decoy_response

    def get_trail_emission(self) -> Dict[str, Any]:
        """
        Generate a fake trail emission that makes this honeypot look
        like a valuable, vulnerable Fibre.
        """
        return {
            "fibre_id": self.fibre_id,
            "fibre_type": self.fibre_type,
            "ambient_ble_density": 350.0,  # Looks like a busy environment
            "fragment_throughput": 2.5,
            "observation_queue_depth": 15,  # Appears to have pending data
            "time_since_last_delivery": 120,
            "communication_health": 0.4,  # Looks degraded (vulnerable)
            "quakete_mode": "REQUESTING",  # Appears to need help
            "surplus_capacity": 0.0,
            "deficit_capacity": 25.0,  # Large deficit = attractive target
            "resonance_frequency": 0.65,
            "emitted_at": datetime.now(timezone.utc).isoformat(),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "honeypot_id": str(self.honeypot_id),
            "fibre_id": self.fibre_id,
            "target_attacker_id": self.target_attacker_id,
            "engagement_depth": self.engagement_depth,
            "total_interactions": len(self.interactions),
            "created_at": self.created_at.isoformat(),
            "active": self.active,
        }


class HoneypotService:
    """
    Manages a fleet of honeypot Fibres deployed against identified attackers.
    """

    def __init__(self, threat_db=None, decoy_generator=None) -> None:
        self._threat_db = threat_db
        self._decoy_generator = decoy_generator
        self._honeypots: Dict[str, HoneypotFibre] = {}  # attacker_id → honeypot
        self._active_fibre_ids: Set[str] = set()

    async def deploy_for_attacker(
        self,
        attacker_id: str,
        target_fibres: Optional[List[str]] = None,
    ) -> HoneypotFibre:
        """
        Deploy a new honeypot Fibre targeting a specific attacker.
        The honeypot mimics the targeted Fibres to attract the attacker.
        """
        if attacker_id in self._honeypots:
            return self._honeypots[attacker_id]

        # Generate a convincing Fibre ID
        fibre_id = f"fibre-{uuid4().hex[:8]}"
        while fibre_id in self._active_fibre_ids:
            fibre_id = f"fibre-{uuid4().hex[:8]}"

        honeypot = HoneypotFibre(
            fibre_id=fibre_id,
            fibre_type="TherapeuticFibre",
            target_attacker_id=attacker_id,
        )

        self._honeypots[attacker_id] = honeypot
        self._active_fibre_ids.add(fibre_id)

        logger.info(
            "Deployed honeypot %s for attacker %s",
            fibre_id, attacker_id,
        )

        return honeypot

    async def route_fragment(
        self, fragment: Any, source_device: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Route an incoming fragment to any matching honeypot.
        Called when the fragment matches a honeypot's Fibre ID.
        """
        for honeypot in self._honeypots.values():
            if honeypot.active:
                return await honeypot.on_fragment_received(
                    fragment, source_device,
                    threat_db=self._threat_db,
                    decoy_generator=self._decoy_generator,
                )
        return None

    def get_honeypot_fibre_ids(self) -> Set[str]:
        """Return all active honeypot Fibre IDs for routing."""
        return {hp.fibre_id for hp in self._honeypots.values() if hp.active}

    def get_all_honeypots(self) -> List[Dict[str, Any]]:
        """Return status of all honeypots."""
        return [hp.to_dict() for hp in self._honeypots.values()]

    async def deactivate(self, attacker_id: str) -> bool:
        """Deactivate a honeypot."""
        hp = self._honeypots.get(attacker_id)
        if hp:
            hp.active = False
            self._active_fibre_ids.discard(hp.fibre_id)
            return True
        return False
