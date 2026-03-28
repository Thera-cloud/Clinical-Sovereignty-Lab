"""
Attack Fingerprinter — Captures identity signals from every failed interaction
across BLE, WebSocket, REST, and Mesh layers.  Builds persistent AttackerProfile
objects that correlate signals from the same source.

Fingerprint dimensions:
  BLE  – source address, AD pattern hash, RSSI history, timing cadence
  NET  – IP address, TLS fingerprint (JA3/JA4), User-Agent
  BEHV – attack method, cadence, signature guesses, target Fibres
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

from app.services.counter_intelligence.orchestrator import (
    AttackSignal,
    AttackSource,
    ThreatLevel,
)

logger = logging.getLogger("counter_intelligence.fingerprinter")


# =============================================================================
# ATTACKER PROFILE
# =============================================================================

class AttackerProfile:
    """Composite fingerprint of a suspected attacker."""

    __slots__ = (
        "profile_id", "first_seen", "last_seen",
        # BLE fingerprint
        "ble_addresses", "ad_pattern_hash", "rssi_history",
        # Network fingerprint
        "ip_addresses", "tls_fingerprints", "user_agents",
        # Behavioral fingerprint
        "attack_methods", "attack_cadence_history", "signature_guesses",
        "target_fibres", "total_events",
        # Classification
        "threat_level", "confidence",
    )

    def __init__(self, profile_id: Optional[UUID] = None) -> None:
        self.profile_id = profile_id or uuid4()
        now = datetime.now(timezone.utc)
        self.first_seen = now
        self.last_seen = now
        # BLE
        self.ble_addresses: Set[str] = set()
        self.ad_pattern_hash: Optional[str] = None
        self.rssi_history: List[Tuple[float, int]] = []  # (timestamp, rssi)
        # Network
        self.ip_addresses: Set[str] = set()
        self.tls_fingerprints: Set[str] = set()
        self.user_agents: Set[str] = set()
        # Behavioral
        self.attack_methods: Set[str] = set()
        self.attack_cadence_history: List[float] = []  # timestamps of events
        self.signature_guesses: List[int] = []
        self.target_fibres: Set[str] = set()
        self.total_events: int = 0
        # Classification
        self.threat_level = ThreatLevel.LOW
        self.confidence: float = 0.0

    @property
    def attack_cadence(self) -> float:
        """Events per minute over the last 60 seconds."""
        now = time.time()
        recent = [t for t in self.attack_cadence_history if now - t < 60]
        return len(recent)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": str(self.profile_id),
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "ble_addresses": list(self.ble_addresses),
            "ad_pattern_hash": self.ad_pattern_hash,
            "ip_addresses": list(self.ip_addresses),
            "tls_fingerprints": list(self.tls_fingerprints),
            "user_agents": list(self.user_agents),
            "attack_methods": list(self.attack_methods),
            "signature_guesses": self.signature_guesses[-50:],
            "target_fibres": list(self.target_fibres),
            "total_events": self.total_events,
            "attack_cadence": self.attack_cadence,
            "threat_level": self.threat_level.name,
            "confidence": self.confidence,
        }


# =============================================================================
# CORRELATION CONFIG
# =============================================================================

# Maximum time window for correlating signals to the same attacker
CORRELATION_WINDOW_SECONDS = 3600  # 1 hour
# Minimum confidence to consider two signals from the same attacker
MIN_CORRELATION_CONFIDENCE = 0.4


# =============================================================================
# FINGERPRINTER
# =============================================================================

class AttackFingerprinter:
    """
    Builds and maintains AttackerProfile objects from raw AttackSignals.
    Correlates signals across layers to identify the same attacker using
    different vectors.
    """

    def __init__(self, threat_db=None) -> None:
        self._threat_db = threat_db
        # In-memory profile registry
        self._profiles: Dict[UUID, AttackerProfile] = {}
        # Lookup indexes for correlation
        self._ble_to_profile: Dict[str, UUID] = {}
        self._ip_to_profile: Dict[str, UUID] = {}
        self._ua_hash_to_profile: Dict[str, UUID] = {}

    # ------------------------------------------------------------------
    # Signal Processing
    # ------------------------------------------------------------------

    async def process_signal(self, signal: AttackSignal) -> UUID:
        """
        Process an attack signal: find or create an AttackerProfile,
        update it with signal data, return the profile_id.
        """
        profile = self._correlate_to_profile(signal)
        self._update_profile(profile, signal)

        # Persist
        if self._threat_db:
            await self._threat_db.upsert_profile(profile)

        return profile.profile_id

    # ------------------------------------------------------------------
    # Correlation — find existing profile or create new one
    # ------------------------------------------------------------------

    def _correlate_to_profile(self, signal: AttackSignal) -> AttackerProfile:
        """
        Attempt to match the signal to an existing attacker profile using:
          1. BLE address match
          2. IP address match
          3. User-Agent hash match
          4. Temporal + behavioral correlation
        If no match found, create a new profile.
        """
        candidates: List[Tuple[UUID, float]] = []  # (profile_id, confidence)

        # BLE address correlation
        if signal.device_address:
            pid = self._ble_to_profile.get(signal.device_address)
            if pid and pid in self._profiles:
                candidates.append((pid, 0.9))

        # IP address correlation
        if signal.ip_address:
            pid = self._ip_to_profile.get(signal.ip_address)
            if pid and pid in self._profiles:
                candidates.append((pid, 0.7))

        # User-Agent hash correlation
        if signal.user_agent:
            ua_hash = self._hash_user_agent(signal.user_agent)
            pid = self._ua_hash_to_profile.get(ua_hash)
            if pid and pid in self._profiles:
                candidates.append((pid, 0.5))

        # Pick best match
        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            best_pid, best_conf = candidates[0]
            if best_conf >= MIN_CORRELATION_CONFIDENCE:
                profile = self._profiles[best_pid]
                profile.confidence = max(profile.confidence, best_conf)
                return profile

        # No match — create new profile
        profile = AttackerProfile()
        self._profiles[profile.profile_id] = profile
        logger.info("New attacker profile created: %s", profile.profile_id)
        return profile

    # ------------------------------------------------------------------
    # Profile Update
    # ------------------------------------------------------------------

    def _update_profile(
        self, profile: AttackerProfile, signal: AttackSignal,
    ) -> None:
        """Merge signal data into the attacker profile and update indexes."""
        now = datetime.now(timezone.utc)
        profile.last_seen = now
        profile.total_events += 1
        profile.attack_cadence_history.append(time.time())

        # Trim cadence history to last 1000 events
        if len(profile.attack_cadence_history) > 1000:
            profile.attack_cadence_history = profile.attack_cadence_history[-500:]

        # BLE fingerprint
        if signal.device_address:
            profile.ble_addresses.add(signal.device_address)
            self._ble_to_profile[signal.device_address] = profile.profile_id

        # Compute AD pattern hash from metadata
        ad_hash = signal.metadata.get("ad_pattern_hash")
        if ad_hash:
            profile.ad_pattern_hash = ad_hash

        # RSSI
        rssi = signal.metadata.get("rssi")
        if rssi is not None:
            profile.rssi_history.append((time.time(), rssi))
            if len(profile.rssi_history) > 500:
                profile.rssi_history = profile.rssi_history[-250:]

        # Network fingerprint
        if signal.ip_address:
            profile.ip_addresses.add(signal.ip_address)
            self._ip_to_profile[signal.ip_address] = profile.profile_id

        if signal.user_agent:
            profile.user_agents.add(signal.user_agent)
            ua_hash = self._hash_user_agent(signal.user_agent)
            self._ua_hash_to_profile[ua_hash] = profile.profile_id

        tls_fp = signal.metadata.get("tls_fingerprint")
        if tls_fp:
            profile.tls_fingerprints.add(tls_fp)

        # Behavioral
        profile.attack_methods.add(signal.failure_type)

        sig_guess = signal.metadata.get("signature_guess")
        if sig_guess is not None:
            profile.signature_guesses.append(sig_guess)
            if len(profile.signature_guesses) > 500:
                profile.signature_guesses = profile.signature_guesses[-250:]

        if signal.target_fibre_id:
            profile.target_fibres.add(signal.target_fibre_id)

    # ------------------------------------------------------------------
    # Profile Retrieval
    # ------------------------------------------------------------------

    async def get_profile(self, profile_id: UUID) -> Optional[Dict[str, Any]]:
        """Return profile as dict, or None."""
        profile = self._profiles.get(profile_id)
        if profile:
            return profile.to_dict()
        return None

    async def get_all_active(self) -> List[Dict[str, Any]]:
        """Return all active profiles."""
        return [p.to_dict() for p in self._profiles.values()]

    def get_profile_obj(self, profile_id: UUID) -> Optional[AttackerProfile]:
        """Return raw AttackerProfile object."""
        return self._profiles.get(profile_id)

    # ------------------------------------------------------------------
    # BLE-Specific Fingerprinting Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def compute_ad_pattern_hash(
        ad_types: List[int], ad_lengths: List[int],
        manufacturer_ids: Optional[List[int]] = None,
    ) -> str:
        """
        Compute a stable hash of the BLE advertisement structure pattern.
        Different device models/OS produce characteristic AD patterns.
        """
        parts = [
            ",".join(str(t) for t in sorted(ad_types)),
            ",".join(str(l) for l in ad_lengths),
        ]
        if manufacturer_ids:
            parts.append(",".join(str(m) for m in sorted(manufacturer_ids)))
        data = "|".join(parts).encode()
        return hashlib.sha256(data).hexdigest()[:16]

    @staticmethod
    def _hash_user_agent(ua: str) -> str:
        """Normalised hash of User-Agent for correlation."""
        return hashlib.sha256(ua.strip().lower().encode()).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def prune_stale_profiles(self, max_age_hours: int = 168) -> int:
        """Remove profiles not seen in the last N hours."""
        now = datetime.now(timezone.utc)
        stale = [
            pid for pid, p in self._profiles.items()
            if (now - p.last_seen).total_seconds() > max_age_hours * 3600
        ]
        for pid in stale:
            profile = self._profiles.pop(pid, None)
            if profile:
                for addr in profile.ble_addresses:
                    self._ble_to_profile.pop(addr, None)
                for ip in profile.ip_addresses:
                    self._ip_to_profile.pop(ip, None)
        logger.info("Pruned %d stale attacker profiles", len(stale))
        return len(stale)
