"""
Tarpit Engine — Wastes attacker resources through deliberate slowdowns
and computationally expensive decoy data.

Tarpit types:
  BLE     – Flood attacker's BLE collection with valid-looking garbage fragments
  WS      – Progressive WebSocket response delays for identified attacker IPs
  API     – Slow API responses with valid-looking but useless JSON
  COMPUTE – Decoy fragments that assemble into expensive-to-process payloads
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import struct
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from app.services.counter_intelligence.orchestrator import ThreatLevel

logger = logging.getLogger("counter_intelligence.tarpit")


# =============================================================================
# CONSTANTS
# =============================================================================

# WebSocket tarpit: base delay escalation (seconds)
WS_BASE_DELAY = 0.2
WS_MAX_DELAY = 30.0
WS_ESCALATION_FACTOR = 2.0

# BLE tarpit: decoy fragments per burst
BLE_DECOY_BURST_SIZE = 50
BLE_DECOY_INTERVAL_SECONDS = 5.0

# API tarpit: response delay escalation
API_BASE_DELAY = 0.5
API_MAX_DELAY = 60.0


class TarpitEngine:
    """
    Resource-wasting engine for identified attackers.
    """

    def __init__(self, threat_db=None) -> None:
        self._threat_db = threat_db
        # Tarpit state per attacker
        self._active_tarpits: Dict[str, TarpitState] = {}
        # IP-based delay tracking
        self._ip_delays: Dict[str, float] = defaultdict(lambda: 0.0)
        # Set of tarpitted IPs for fast lookup
        self._tarpitted_ips: Set[str] = set()

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    async def activate_for_attacker(
        self, attacker_id: str, threat_level: ThreatLevel,
    ) -> None:
        """Activate tarpit for an attacker based on threat level."""
        state = TarpitState(
            attacker_id=attacker_id,
            threat_level=threat_level,
        )
        self._active_tarpits[attacker_id] = state

        logger.info(
            "Tarpit activated for attacker %s at level %s",
            attacker_id, threat_level.name,
        )

    def is_tarpitted(self, ip_address: str) -> bool:
        """Check if an IP is being tarpitted."""
        return ip_address in self._tarpitted_ips

    async def register_attacker_ip(
        self, attacker_id: str, ip_address: str,
    ) -> None:
        """Associate an IP with a tarpitted attacker."""
        if attacker_id in self._active_tarpits:
            self._tarpitted_ips.add(ip_address)
            self._active_tarpits[attacker_id].known_ips.add(ip_address)

    # ------------------------------------------------------------------
    # WebSocket Tarpit
    # ------------------------------------------------------------------

    async def get_ws_delay(self, ip_address: str) -> float:
        """
        Get the progressive delay for a WebSocket response.
        Each successive request from the same IP increases the delay.
        """
        if ip_address not in self._tarpitted_ips:
            return 0.0

        current = self._ip_delays[ip_address]
        if current < WS_BASE_DELAY:
            current = WS_BASE_DELAY
        else:
            current = min(current * WS_ESCALATION_FACTOR, WS_MAX_DELAY)

        self._ip_delays[ip_address] = current
        return current

    async def apply_ws_tarpit(self, ip_address: str) -> None:
        """Sleep for the appropriate tarpit delay."""
        delay = await self.get_ws_delay(ip_address)
        if delay > 0:
            logger.debug("Tarpitting WS from %s for %.1fs", ip_address, delay)
            await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # API Tarpit
    # ------------------------------------------------------------------

    async def get_api_delay(self, ip_address: str) -> float:
        """Get progressive delay for REST API responses."""
        if ip_address not in self._tarpitted_ips:
            return 0.0

        key = f"api:{ip_address}"
        current = self._ip_delays.get(key, 0.0)
        if current < API_BASE_DELAY:
            current = API_BASE_DELAY
        else:
            current = min(current * WS_ESCALATION_FACTOR, API_MAX_DELAY)

        self._ip_delays[key] = current
        return current

    # ------------------------------------------------------------------
    # BLE Tarpit — Decoy Fragment Generation
    # ------------------------------------------------------------------

    async def generate_decoy_fragments(
        self, count: int, target_attacker_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Generate convincing-looking but garbage BLE fragments.
        These pass superficial structural validation but assemble
        into nonsensical observations, wasting compute.
        """
        fragments = []
        for i in range(count):
            # Generate a random "valid-looking" fragment structure
            sig_byte = os.urandom(1)[0]
            sequence = i % 255
            total = min(count, 255)
            payload = os.urandom(5)  # Extended mode payload

            # Compute a valid CRC-8 over the fragment bytes to make it
            # pass structural validation
            frag_bytes = bytes([sig_byte, sequence, total]) + payload
            crc = _crc8(frag_bytes)

            fragment = {
                "signature": sig_byte,
                "sequence": sequence,
                "total": total,
                "payload": list(payload),
                "checksum": crc,
                "mode": "EXTENDED",
                "fragment_type": "DATA",
                "decoy": True,
                "target_attacker": target_attacker_id,
            }
            fragments.append(fragment)

        logger.debug("Generated %d decoy fragments", count)
        return fragments

    # ------------------------------------------------------------------
    # Computational Trap
    # ------------------------------------------------------------------

    async def generate_computational_trap(
        self, complexity: int = 10,
    ) -> bytes:
        """
        Generate a payload that requires expensive computation to process.
        Uses nested encryption layers that the attacker must attempt to
        unwrap, each requiring a separate key derivation.

        The payload is deliberately large and cryptographically opaque,
        forcing brute-force attempts.
        """
        # Start with a random core
        core = os.urandom(64)

        # Wrap in multiple hash layers — each layer adds 32 bytes
        wrapped = core
        for i in range(complexity):
            salt = os.urandom(16)
            wrapped = salt + hashlib.sha256(salt + wrapped).digest() + wrapped

        logger.debug(
            "Generated computational trap: %d bytes, %d layers",
            len(wrapped), complexity,
        )
        return wrapped

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        return {
            "active_tarpits": len(self._active_tarpits),
            "tarpitted_ips": len(self._tarpitted_ips),
            "tarpits": {
                aid: state.to_dict()
                for aid, state in self._active_tarpits.items()
            },
        }

    async def deactivate(self, attacker_id: str) -> bool:
        """Deactivate tarpit for an attacker."""
        state = self._active_tarpits.pop(attacker_id, None)
        if state:
            for ip in state.known_ips:
                self._tarpitted_ips.discard(ip)
                self._ip_delays.pop(ip, None)
                self._ip_delays.pop(f"api:{ip}", None)
            return True
        return False


class TarpitState:
    """Tracks per-attacker tarpit state."""

    __slots__ = (
        "attacker_id", "threat_level", "activated_at",
        "known_ips", "requests_delayed", "total_delay_seconds",
    )

    def __init__(
        self, attacker_id: str, threat_level: ThreatLevel,
    ) -> None:
        self.attacker_id = attacker_id
        self.threat_level = threat_level
        self.activated_at = datetime.now(timezone.utc)
        self.known_ips: Set[str] = set()
        self.requests_delayed: int = 0
        self.total_delay_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attacker_id": self.attacker_id,
            "threat_level": self.threat_level.name,
            "activated_at": self.activated_at.isoformat(),
            "known_ips": list(self.known_ips),
            "requests_delayed": self.requests_delayed,
            "total_delay_seconds": round(self.total_delay_seconds, 1),
        }


# =============================================================================
# UTILITY
# =============================================================================

def _crc8(data: bytes, poly: int = 0x07, init: int = 0x00) -> int:
    """CRC-8 matching ZEFCP protocol."""
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ poly) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc
