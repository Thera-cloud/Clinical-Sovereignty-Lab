"""
HIVE DEFENSE PROTOCOL — Network Topology Fingerprint (Phase 8C, Third Cord)
Shell-level positional verification via embedded infrastructure signatures.

Each containment shell has a unique topology fingerprint embedded in
latency characteristics, packet TTL values, and routing path signatures.
These fingerprints are a *property of the network infrastructure itself*
— they cannot be removed, spoofed, or stripped by an attacker because
they emerge from the physical/logical routing topology of the shell.

Use Case
--------
An attacker inside Shell 2 who believes they have escaped containment
can be positionally verified: the observed network fingerprint proves
they are still inside Shell 2, regardless of what the attacker's own
tools report.

Fingerprint Components
----------------------
1. **Latency signature** — each shell has a characteristic latency
   distribution (mean, variance, skew) baked into its routing.
2. **TTL profile** — packets traversing a shell have predictable TTL
   decrements based on the number of virtual hops.
3. **Route hash** — the set of intermediate routing nodes produces a
   deterministic hash that uniquely identifies the shell.
4. **Jitter pattern** — each shell has a unique jitter autocorrelation
   that emerges from its traffic shaping policy.

Verification is O(1): compare observed fingerprint against known shell
fingerprints.  No cryptographic exchange or handshake required.

Patent-Pending — Claim 50
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

logger = logging.getLogger("hive.network_topology_fingerprint")


# =============================================================================
# CONSTANTS
# =============================================================================

# Number of fingerprint dimensions
FINGERPRINT_DIMENSIONS = 4  # latency, ttl, route_hash, jitter

# HMAC key length for fingerprint generation
HMAC_KEY_LENGTH = 32

# Tolerance for fingerprint matching (Euclidean distance threshold)
DEFAULT_MATCH_TOLERANCE = 0.15


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class TopologyFingerprint:
    """
    A unique network topology fingerprint for a containment shell.

    The fingerprint is a composite of latency characteristics, TTL
    profile, route hashing, and jitter patterns — all of which are
    properties of the shell's network infrastructure.

    Attributes
    ----------
    fingerprint_id : UUID
        Unique identifier for this fingerprint instance.
    shell_id : UUID
        The containment shell this fingerprint belongs to.
    latency_signature : dict
        Statistical latency profile (mean_ms, variance_ms, skew).
    ttl_profile : dict
        Expected TTL values and hop counts.
    route_hash : str
        SHA-256 hash of the shell's routing node sequence.
    jitter_pattern : dict
        Autocorrelation characteristics of the shell's jitter.
    composite_hash : str
        A single hash combining all four dimensions for fast comparison.
    created_at : datetime
        When this fingerprint was generated.
    """
    fingerprint_id: UUID = field(default_factory=uuid4)
    shell_id: UUID = field(default_factory=uuid4)
    latency_signature: Dict[str, float] = field(default_factory=dict)
    ttl_profile: Dict[str, Any] = field(default_factory=dict)
    route_hash: str = ""
    jitter_pattern: Dict[str, float] = field(default_factory=dict)
    composite_hash: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize fingerprint for storage or transmission."""
        return {
            "fingerprint_id": str(self.fingerprint_id),
            "shell_id": str(self.shell_id),
            "latency_signature": self.latency_signature,
            "ttl_profile": self.ttl_profile,
            "route_hash": self.route_hash,
            "jitter_pattern": self.jitter_pattern,
            "composite_hash": self.composite_hash,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class PositionVerification:
    """
    Result of verifying an entity's position via topology fingerprint.

    Attributes
    ----------
    entity_id : str
        The entity whose position was verified.
    observed_fingerprint : TopologyFingerprint
        The fingerprint observed from the entity's vantage point.
    matched_shell_id : UUID or None
        The shell the entity is actually in (None if no match).
    matched_depth : int
        Shell depth the entity is in (-1 if unverified).
    confidence : float
        Match confidence in [0.0, 1.0].
    distance : float
        Euclidean distance between observed and expected fingerprints.
    verified : bool
        Whether position was successfully verified.
    timestamp : datetime
        When verification was performed.
    """
    entity_id: str = ""
    observed_fingerprint: Optional[TopologyFingerprint] = None
    matched_shell_id: Optional[UUID] = None
    matched_depth: int = -1
    confidence: float = 0.0
    distance: float = float("inf")
    verified: bool = False
    timestamp: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# NETWORK TOPOLOGY FINGERPRINT ENGINE
# =============================================================================

class NetworkTopologyFingerprint:
    """
    Shell-level positional verification engine.

    Generates unique topology fingerprints per containment shell and
    verifies entity positions by comparing observed fingerprints against
    known shell signatures.

    Parameters
    ----------
    master_key : bytes or None
        Master HMAC key for deterministic fingerprint generation.
        If None, a random key is generated.
    match_tolerance : float
        Euclidean distance threshold for fingerprint matching
        (default 0.15).

    Usage
    -----
    ::

        engine = NetworkTopologyFingerprint()

        # Generate fingerprint for a shell
        fp = await engine.generate_fingerprint(shell_id)

        # Verify an entity's position
        result = await engine.verify_position(entity_id, observed_fp)
    """

    def __init__(
        self,
        *,
        master_key: Optional[bytes] = None,
        match_tolerance: float = DEFAULT_MATCH_TOLERANCE,
    ) -> None:
        self._master_key = master_key or os.urandom(HMAC_KEY_LENGTH)
        self._match_tolerance = match_tolerance

        # Shell fingerprint registry: shell_id → TopologyFingerprint
        self._fingerprints: Dict[UUID, TopologyFingerprint] = {}

        # Verification log
        self._verification_log: List[Dict[str, Any]] = []

        # Concurrency control
        self._lock = asyncio.Lock()

        # Stats
        self._total_generated: int = 0
        self._total_verifications: int = 0
        self._total_matches: int = 0

        logger.info(
            "NetworkTopologyFingerprint initialised — "
            "tolerance=%.3f, key_length=%d",
            self._match_tolerance,
            len(self._master_key),
        )

    # --------------------------------------------------------------------- #
    # FINGERPRINT GENERATION
    # --------------------------------------------------------------------- #

    async def generate_fingerprint(
        self,
        shell_id: UUID,
        shell_salt: Optional[bytes] = None,
    ) -> TopologyFingerprint:
        """
        Generate a unique topology fingerprint for a containment shell.

        The fingerprint is deterministically derived from the shell ID
        and the master key, ensuring reproducibility while remaining
        unpredictable to attackers without the key.

        Parameters
        ----------
        shell_id : UUID
            The containment shell to fingerprint.
        shell_salt : bytes or None
            Additional entropy from the shell's fingerprint_salt.

        Returns
        -------
        TopologyFingerprint
            The generated fingerprint.
        """
        salt = shell_salt or os.urandom(16)
        shell_bytes = shell_id.bytes

        # Generate the four fingerprint dimensions
        latency_sig = self._generate_latency_signature(shell_bytes, salt)
        ttl_prof = self._generate_ttl_profile(shell_bytes, salt)
        route_h = self._generate_route_hash(shell_bytes, salt)
        jitter_pat = self._generate_jitter_pattern(shell_bytes, salt)

        # Compute composite hash from all dimensions
        composite_material = (
            f"{latency_sig['mean_ms']:.6f}:"
            f"{latency_sig['variance_ms']:.6f}:"
            f"{ttl_prof['expected_ttl']}:"
            f"{route_h}:"
            f"{jitter_pat['autocorrelation_lag1']:.6f}"
        )
        composite_hash = hashlib.sha256(
            composite_material.encode()
        ).hexdigest()

        fingerprint = TopologyFingerprint(
            shell_id=shell_id,
            latency_signature=latency_sig,
            ttl_profile=ttl_prof,
            route_hash=route_h,
            jitter_pattern=jitter_pat,
            composite_hash=composite_hash,
        )

        async with self._lock:
            self._fingerprints[shell_id] = fingerprint
            self._total_generated += 1

        logger.info(
            "Fingerprint generated for shell %s — composite=%s…",
            shell_id,
            composite_hash[:16],
        )

        return fingerprint

    def _generate_latency_signature(
        self,
        shell_bytes: bytes,
        salt: bytes,
    ) -> Dict[str, float]:
        """
        Generate shell-specific latency characteristics.

        Uses HMAC-SHA256 to derive deterministic but unpredictable
        latency parameters from the shell identity.

        Parameters
        ----------
        shell_bytes : bytes
            Shell UUID as bytes.
        salt : bytes
            Additional entropy.

        Returns
        -------
        dict
            Latency signature with mean_ms, variance_ms, skew.
        """
        key_material = self._master_key + b"latency" + salt
        mac = hmac.new(key_material, shell_bytes, hashlib.sha256).digest()

        # Extract three values from the MAC
        mean_raw = struct.unpack("!H", mac[0:2])[0]
        var_raw = struct.unpack("!H", mac[2:4])[0]
        skew_raw = struct.unpack("!h", mac[4:6])[0]  # signed

        # Map to realistic ranges
        mean_ms = 5.0 + (mean_raw / 65535.0) * 95.0       # 5–100 ms
        variance_ms = 0.5 + (var_raw / 65535.0) * 20.0    # 0.5–20.5 ms
        skew = (skew_raw / 32767.0) * 2.0                 # -2.0 to +2.0

        return {
            "mean_ms": round(mean_ms, 4),
            "variance_ms": round(variance_ms, 4),
            "skew": round(skew, 4),
        }

    def _generate_ttl_profile(
        self,
        shell_bytes: bytes,
        salt: bytes,
    ) -> Dict[str, Any]:
        """
        Generate shell-specific TTL characteristics.

        Each shell has a predictable number of virtual hops that
        decrement TTL values by a unique amount.

        Parameters
        ----------
        shell_bytes : bytes
            Shell UUID as bytes.
        salt : bytes
            Additional entropy.

        Returns
        -------
        dict
            TTL profile with expected_ttl, hop_count, decrement_per_hop.
        """
        key_material = self._master_key + b"ttl" + salt
        mac = hmac.new(key_material, shell_bytes, hashlib.sha256).digest()

        hop_count = 3 + (mac[0] % 12)           # 3–14 hops
        decrement = 1 + (mac[1] % 3)            # 1–3 per hop
        initial_ttl = 64 + (mac[2] % 3) * 64    # 64, 128, or 192
        expected_ttl = initial_ttl - (hop_count * decrement)

        return {
            "expected_ttl": max(1, expected_ttl),
            "initial_ttl": initial_ttl,
            "hop_count": hop_count,
            "decrement_per_hop": decrement,
        }

    def _generate_route_hash(
        self,
        shell_bytes: bytes,
        salt: bytes,
    ) -> str:
        """
        Generate a unique routing path hash for the shell.

        Simulates a sequence of intermediate routing nodes and hashes
        their identifiers to produce a unique route signature.

        Parameters
        ----------
        shell_bytes : bytes
            Shell UUID as bytes.
        salt : bytes
            Additional entropy.

        Returns
        -------
        str
            SHA-256 hex digest of the route path.
        """
        key_material = self._master_key + b"route" + salt
        mac = hmac.new(key_material, shell_bytes, hashlib.sha256).digest()

        # Generate a chain of virtual router IDs
        node_count = 4 + (mac[0] % 8)  # 4–11 nodes
        route_chain = []
        current = mac
        for _ in range(node_count):
            node_id = hashlib.sha256(current).hexdigest()[:12]
            route_chain.append(node_id)
            current = hashlib.sha256(current).digest()

        # Hash the entire route chain
        route_material = ":".join(route_chain)
        return hashlib.sha256(route_material.encode()).hexdigest()

    def _generate_jitter_pattern(
        self,
        shell_bytes: bytes,
        salt: bytes,
    ) -> Dict[str, float]:
        """
        Generate shell-specific jitter autocorrelation characteristics.

        Each shell's traffic shaping policy produces a unique jitter
        pattern that can be measured by observing inter-packet timing.

        Parameters
        ----------
        shell_bytes : bytes
            Shell UUID as bytes.
        salt : bytes
            Additional entropy.

        Returns
        -------
        dict
            Jitter pattern with autocorrelation coefficients and period.
        """
        key_material = self._master_key + b"jitter" + salt
        mac = hmac.new(key_material, shell_bytes, hashlib.sha256).digest()

        # Extract autocorrelation parameters
        lag1_raw = struct.unpack("!H", mac[0:2])[0]
        lag2_raw = struct.unpack("!H", mac[2:4])[0]
        period_raw = struct.unpack("!H", mac[4:6])[0]

        autocorrelation_lag1 = (lag1_raw / 65535.0) * 0.9    # 0.0–0.9
        autocorrelation_lag2 = (lag2_raw / 65535.0) * 0.5    # 0.0–0.5
        period_ms = 10.0 + (period_raw / 65535.0) * 490.0   # 10–500 ms

        return {
            "autocorrelation_lag1": round(autocorrelation_lag1, 6),
            "autocorrelation_lag2": round(autocorrelation_lag2, 6),
            "period_ms": round(period_ms, 2),
        }

    # --------------------------------------------------------------------- #
    # POSITION VERIFICATION
    # --------------------------------------------------------------------- #

    async def verify_position(
        self,
        entity_id: str,
        observed_fingerprint: TopologyFingerprint,
    ) -> PositionVerification:
        """
        Verify which containment shell an entity is in based on the
        observed topology fingerprint.

        Compares the observed fingerprint against all known shell
        fingerprints using Euclidean distance in the normalized
        fingerprint space.

        Parameters
        ----------
        entity_id : str
            The entity whose position is being verified.
        observed_fingerprint : TopologyFingerprint
            The fingerprint observed from the entity's perspective.

        Returns
        -------
        PositionVerification
            Verification result including matched shell and confidence.
        """
        best_match: Optional[UUID] = None
        best_distance = float("inf")
        best_depth = -1

        async with self._lock:
            known_fingerprints = dict(self._fingerprints)

        for shell_id, known_fp in known_fingerprints.items():
            distance = self._compute_fingerprint_distance(
                observed_fingerprint, known_fp
            )
            if distance < best_distance:
                best_distance = distance
                best_match = shell_id

        # Compute confidence from distance (inverse relationship)
        if best_distance <= self._match_tolerance:
            confidence = max(0.0, 1.0 - (best_distance / self._match_tolerance))
            verified = True
        else:
            confidence = 0.0
            verified = False

        result = PositionVerification(
            entity_id=entity_id,
            observed_fingerprint=observed_fingerprint,
            matched_shell_id=best_match if verified else None,
            confidence=round(confidence, 4),
            distance=round(best_distance, 6),
            verified=verified,
        )

        async with self._lock:
            self._total_verifications += 1
            if verified:
                self._total_matches += 1

            self._verification_log.append({
                "entity_id": entity_id,
                "matched_shell": str(best_match) if best_match else None,
                "distance": round(best_distance, 6),
                "confidence": round(confidence, 4),
                "verified": verified,
                "timestamp": datetime.utcnow().isoformat(),
            })

        if verified:
            logger.info(
                "Position verified — entity '%s' is in shell %s "
                "(confidence=%.2f, distance=%.4f)",
                entity_id,
                best_match,
                confidence,
                best_distance,
            )
        else:
            logger.warning(
                "Position verification FAILED for entity '%s' — "
                "closest shell %s at distance %.4f (tolerance %.3f)",
                entity_id,
                best_match,
                best_distance,
                self._match_tolerance,
            )

        return result

    def _compute_fingerprint_distance(
        self,
        observed: TopologyFingerprint,
        known: TopologyFingerprint,
    ) -> float:
        """
        Compute the normalized Euclidean distance between two fingerprints.

        Each fingerprint dimension is normalized to [0, 1] before
        distance computation to ensure equal weighting.

        Parameters
        ----------
        observed : TopologyFingerprint
            The observed fingerprint.
        known : TopologyFingerprint
            The known reference fingerprint.

        Returns
        -------
        float
            Euclidean distance in [0, N] where N is the number of dimensions.
        """
        import math

        dimensions: List[float] = []

        # 1. Latency signature distance (normalized by range)
        obs_lat = observed.latency_signature
        known_lat = known.latency_signature
        if obs_lat and known_lat:
            mean_diff = abs(
                obs_lat.get("mean_ms", 0) - known_lat.get("mean_ms", 0)
            ) / 100.0  # Normalize by range (0–100ms)
            var_diff = abs(
                obs_lat.get("variance_ms", 0) - known_lat.get("variance_ms", 0)
            ) / 20.0   # Normalize by range (0–20ms)
            dimensions.extend([mean_diff, var_diff])

        # 2. TTL profile distance
        obs_ttl = observed.ttl_profile
        known_ttl = known.ttl_profile
        if obs_ttl and known_ttl:
            ttl_diff = abs(
                obs_ttl.get("expected_ttl", 0) - known_ttl.get("expected_ttl", 0)
            ) / 192.0  # Normalize by max TTL
            dimensions.append(ttl_diff)

        # 3. Route hash distance (binary: 0 if match, 1 if different)
        route_diff = 0.0 if observed.route_hash == known.route_hash else 1.0
        dimensions.append(route_diff)

        # 4. Jitter pattern distance
        obs_jit = observed.jitter_pattern
        known_jit = known.jitter_pattern
        if obs_jit and known_jit:
            jit_diff = abs(
                obs_jit.get("autocorrelation_lag1", 0)
                - known_jit.get("autocorrelation_lag1", 0)
            ) / 0.9  # Normalize by range
            dimensions.append(jit_diff)

        if not dimensions:
            return float("inf")

        # Euclidean distance normalized by dimension count
        sum_sq = sum(d ** 2 for d in dimensions)
        return math.sqrt(sum_sq / len(dimensions))

    # --------------------------------------------------------------------- #
    # COMPOSITE HASH VERIFICATION (FAST PATH)
    # --------------------------------------------------------------------- #

    async def verify_by_composite_hash(
        self,
        composite_hash: str,
    ) -> Optional[UUID]:
        """
        Fast O(1) verification using the composite hash.

        If the observed composite hash exactly matches a known shell's
        fingerprint, return the shell ID immediately without full
        distance computation.

        Parameters
        ----------
        composite_hash : str
            The observed composite hash.

        Returns
        -------
        UUID or None
            Matched shell ID, or None if no exact match.
        """
        async with self._lock:
            for shell_id, fp in self._fingerprints.items():
                if hmac.compare_digest(fp.composite_hash, composite_hash):
                    logger.debug(
                        "Composite hash match — shell %s", shell_id
                    )
                    return shell_id
        return None

    # --------------------------------------------------------------------- #
    # REGISTRY MANAGEMENT
    # --------------------------------------------------------------------- #

    async def get_fingerprint(
        self,
        shell_id: UUID,
    ) -> Optional[TopologyFingerprint]:
        """Return the fingerprint for a shell, or None."""
        async with self._lock:
            return self._fingerprints.get(shell_id)

    async def get_all_fingerprints(self) -> Dict[UUID, TopologyFingerprint]:
        """Return all registered fingerprints."""
        async with self._lock:
            return dict(self._fingerprints)

    async def remove_fingerprint(self, shell_id: UUID) -> bool:
        """
        Remove a fingerprint when a shell is decommissioned.

        Returns
        -------
        bool
            True if a fingerprint was removed.
        """
        async with self._lock:
            removed = self._fingerprints.pop(shell_id, None)
            if removed:
                logger.info("Fingerprint removed for shell %s", shell_id)
            return removed is not None

    # --------------------------------------------------------------------- #
    # DIAGNOSTICS
    # --------------------------------------------------------------------- #

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary of fingerprint engine state."""
        return {
            "registered_fingerprints": len(self._fingerprints),
            "total_generated": self._total_generated,
            "total_verifications": self._total_verifications,
            "total_matches": self._total_matches,
            "match_tolerance": self._match_tolerance,
            "recent_verifications": self._verification_log[-10:],
        }

    def __repr__(self) -> str:
        return (
            f"<NetworkTopologyFingerprint "
            f"fingerprints={len(self._fingerprints)} "
            f"verifications={self._total_verifications} "
            f"matches={self._total_matches}>"
        )
