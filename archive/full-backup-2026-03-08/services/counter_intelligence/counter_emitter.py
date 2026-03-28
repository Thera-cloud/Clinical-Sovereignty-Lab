"""
Counter-Fragment Emitter — Coordinates BLE advertisement of retrieval seeds
and counter-fragments targeting attacker devices.

The key insight: an attacker scanning BLE traffic is also RECEIVING BLE
advertisements from every device in range — including Sovereign Sanctuary
devices.  This is the reverse osmosis channel.

The emitter:
  1. Receives crafted seeds from RetrievalSeedCrafter
  2. Encodes them as ZEFCP-compatible fragments
  3. Assigns them to the nearest Sovereign device to the attacker
  4. Coordinates emission via WebSocket to mobile/edge devices
"""

from __future__ import annotations

import asyncio
import logging
import struct
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, Deque, List, Optional, Set
from uuid import UUID, uuid4

logger = logging.getLogger("counter_intelligence.counter_emitter")


class CounterFragmentEmitter:
    """
    Coordinates emission of counter-fragments across the device fleet.
    """

    def __init__(
        self,
        threat_db=None,
        wisdom_mesh=None,
        max_queue_per_device: int = 100,
    ) -> None:
        self._threat_db = threat_db
        self._wisdom_mesh = wisdom_mesh
        # Seed queue per target device
        self._device_queues: Dict[str, Deque[Dict]] = defaultdict(
            lambda: deque(maxlen=max_queue_per_device)
        )
        # Active targeting assignments
        self._targeting: Dict[str, str] = {}  # attacker_id → device_id
        # Known sovereign device registry (device_id → metadata)
        self._sovereign_devices: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Device Registration
    # ------------------------------------------------------------------

    def register_sovereign_device(
        self,
        device_id: str,
        device_type: str = "mobile",
        rssi_capability: bool = True,
        advertising_capability: bool = True,
    ) -> None:
        """Register a Sovereign device capable of BLE advertising."""
        self._sovereign_devices[device_id] = {
            "device_id": device_id,
            "device_type": device_type,
            "rssi_capability": rssi_capability,
            "advertising_capability": advertising_capability,
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "fragments_emitted": 0,
        }
        logger.info("Registered sovereign device: %s (%s)", device_id, device_type)

    # ------------------------------------------------------------------
    # Targeting
    # ------------------------------------------------------------------

    async def target_attacker(self, attacker_profile: Dict[str, Any]) -> None:
        """
        Assign the nearest sovereign device to target an attacker.
        Uses RSSI correlation to find proximity.
        """
        attacker_id = attacker_profile.get("profile_id", "unknown")

        # Find the best device to use for counter-emission
        best_device = self._find_nearest_device(attacker_profile)
        if not best_device:
            logger.warning(
                "No sovereign devices available for counter-emission against %s",
                attacker_id,
            )
            return

        self._targeting[attacker_id] = best_device
        logger.info(
            "Targeting attacker %s via device %s",
            attacker_id, best_device,
        )

    def _find_nearest_device(
        self, attacker_profile: Dict[str, Any],
    ) -> Optional[str]:
        """
        Find the sovereign device nearest to the attacker.
        Falls back to any available device if RSSI data is unavailable.
        """
        advertising_devices = [
            did for did, meta in self._sovereign_devices.items()
            if meta.get("advertising_capability")
        ]
        if not advertising_devices:
            return None

        # TODO: When RSSI triangulation data is available from multiple
        # devices, use it to find the physically closest device.
        # For now, use round-robin assignment.
        return advertising_devices[0]

    # ------------------------------------------------------------------
    # Seed Queuing
    # ------------------------------------------------------------------

    async def queue_seed(self, seed) -> None:
        """
        Queue a retrieval seed for emission via BLE.
        Encodes the seed payload into ZEFCP-compatible fragment format.
        """
        target_attacker = getattr(seed, "target_attacker", None)
        device_id = self._targeting.get(target_attacker or "")

        if not device_id:
            # Queue to all devices
            for did in self._sovereign_devices:
                self._device_queues[did].append(
                    self._encode_seed_as_fragment(seed)
                )
        else:
            self._device_queues[device_id].append(
                self._encode_seed_as_fragment(seed)
            )

        logger.debug("Queued seed %s for emission", getattr(seed, "seed_id", "?"))

    def _encode_seed_as_fragment(self, seed) -> Dict[str, Any]:
        """
        Encode a retrieval seed as a ZEFCP-compatible fragment structure.
        The fragment looks like normal traffic but carries the seed payload.
        """
        payload = getattr(seed, "payload", b"")
        seed_id = str(getattr(seed, "seed_id", uuid4()))

        # Break payload into 5-byte chunks (extended mode fragment payloads)
        chunks = []
        for i in range(0, len(payload), 5):
            chunks.append(payload[i:i + 5])

        return {
            "seed_id": seed_id,
            "seed_type": getattr(seed, "seed_type", "unknown"),
            "tracking_endpoint": getattr(seed, "tracking_endpoint", ""),
            "chunks": [list(c) for c in chunks],
            "total_chunks": len(chunks),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Fragment Retrieval (called by devices to get their assignments)
    # ------------------------------------------------------------------

    async def get_pending_fragments(
        self, device_id: str, max_count: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get pending counter-fragments for a device to emit via BLE.
        Called by mobile/edge devices polling for work.
        """
        queue = self._device_queues.get(device_id)
        if not queue:
            return []

        fragments = []
        while queue and len(fragments) < max_count:
            fragments.append(queue.popleft())

        # Update device stats
        dev_meta = self._sovereign_devices.get(device_id)
        if dev_meta:
            dev_meta["fragments_emitted"] = (
                dev_meta.get("fragments_emitted", 0) + len(fragments)
            )
            dev_meta["last_seen"] = datetime.now(timezone.utc).isoformat()

        return fragments

    # ------------------------------------------------------------------
    # Broadcast via Wisdom Mesh
    # ------------------------------------------------------------------

    async def broadcast_counter_assignment(
        self, device_id: str, fragments: List[Dict],
    ) -> None:
        """
        Push counter-fragment assignment to a device via Wisdom Mesh.
        Used for proactive delivery instead of polling.
        """
        if not self._wisdom_mesh:
            return

        try:
            from app.models.mesh import MeshMessage, MeshMessageType, MeshPriority

            msg = MeshMessage(
                sender_id=UUID("00000000-0000-0000-0000-000000000000"),
                message_type=MeshMessageType.DIRECTIVE,
                body={
                    "directive_type": "counter_emission",
                    "target_device": device_id,
                    "fragments": fragments,
                },
                domain_tags=["counter-intelligence", "ble-emission"],
                priority=MeshPriority.HIGH,
            )
            await self._wisdom_mesh.publish(msg)
        except Exception as exc:
            logger.error("Failed to broadcast counter assignment: %s", exc)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        return {
            "sovereign_devices": len(self._sovereign_devices),
            "active_targeting": dict(self._targeting),
            "queued_fragments": {
                did: len(q) for did, q in self._device_queues.items()
            },
            "devices": self._sovereign_devices,
        }
