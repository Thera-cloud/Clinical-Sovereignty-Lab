"""
HIVE DEFENSE PROTOCOL — Attacker Fingerprint Database (Phase 8A)
Behavioural signature database for identifying and tracking threat actors.

Each attacker is represented by an :class:`AttackerProfile` containing
behavioural vectors (communication cadence, tool signatures, timing
patterns, sophistication metrics).  New observations are compared against
the database using cosine similarity on normalised behavioural vectors,
allowing the system to recognise returning attackers even when surface
indicators (IP addresses, user-agents) change.

Patent-Pending — Claim 34
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from app.models.hive_defense import AttackerProfile

logger = logging.getLogger("hive.attacker_fingerprint")


# =============================================================================
# BEHAVIOURAL VECTOR KEYS
# =============================================================================

# Canonical ordered keys used to construct fixed-length behavioural vectors.
# Each key maps to a float in [0, 1] that quantifies one dimension of
# attacker behaviour.
BEHAVIORAL_VECTOR_KEYS: List[str] = [
    "scan_frequency",          # How often the actor probes
    "payload_entropy",         # Shannon entropy of payloads
    "protocol_diversity",      # Number of distinct protocols used (normalised)
    "timing_regularity",       # How periodic the activity is (0=random, 1=clockwork)
    "evasion_sophistication",  # Complexity of obfuscation / anti-detection
    "lateral_movement",        # Degree of east–west traversal
    "data_exfil_volume",       # Normalised volume of outbound data
    "persistence_attempts",    # Re-entry / persistence mechanisms observed
    "tool_reuse_ratio",        # Fraction of known-tool signatures reused
    "response_latency",        # Average C&C → action latency (normalised)
]


# =============================================================================
# ATTACKER FINGERPRINT DATABASE
# =============================================================================

class AttackerFingerprintDB:
    """
    In-memory + PostgreSQL-backed database of attacker behavioural fingerprints.

    Core operations
    ---------------
    * **add_fingerprint** — register a new :class:`AttackerProfile`.
    * **match_fingerprint** — find the closest known profile using cosine
      similarity on behavioural vectors.
    * **update_fingerprint** — enrich an existing profile with fresh
      observations.
    * **get_all_fingerprints** — dump the full database for analysis.
    * **flush_to_db** — persist the in-memory store to the
      ``attacker_fingerprints`` PostgreSQL table.

    Matching algorithm
    ------------------
    Observed behaviour is projected into a fixed-dimension vector space
    defined by ``BEHAVIORAL_VECTOR_KEYS``.  The cosine similarity between
    the observation vector and every stored profile vector is computed;
    the best match above a configurable threshold is returned.

    Usage
    -----
    ::

        db = AttackerFingerprintDB(similarity_threshold=0.80)
        db.add_fingerprint(profile)
        match = db.match_fingerprint(observed_behavior)
        if match:
            print(f"Recognised attacker: {match.profile_id}")
    """

    def __init__(
        self,
        *,
        similarity_threshold: float = 0.80,
    ) -> None:
        """
        Parameters
        ----------
        similarity_threshold:
            Minimum cosine similarity (0–1) required to declare a match.
        """
        # profile_id → AttackerProfile
        self._profiles: Dict[UUID, AttackerProfile] = {}

        # profile_id → normalised behavioural vector
        self._vectors: Dict[UUID, List[float]] = {}

        # Profiles that have been modified since the last flush
        self._dirty: set[UUID] = set()

        # Concurrency guard
        self._lock: asyncio.Lock = asyncio.Lock()

        self._similarity_threshold = similarity_threshold

        logger.info(
            "AttackerFingerprintDB initialised — threshold=%.2f, "
            "vector_dims=%d",
            similarity_threshold,
            len(BEHAVIORAL_VECTOR_KEYS),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def add_fingerprint(self, profile: AttackerProfile) -> None:
        """
        Store a new attacker profile and pre-compute its behavioural vector.

        Parameters
        ----------
        profile:
            A fully populated :class:`AttackerProfile`.
        """
        async with self._lock:
            vector = self._extract_vector(profile.behavioral_patterns)
            self._profiles[profile.profile_id] = profile
            self._vectors[profile.profile_id] = vector
            self._dirty.add(profile.profile_id)

        logger.info(
            "Added attacker fingerprint %s — sophistication=%d, "
            "tools=%d, channels=%d",
            profile.profile_id,
            profile.sophistication_level,
            len(profile.tool_signatures),
            len(profile.active_channels),
        )

    async def match_fingerprint(
        self,
        observed_behavior: Dict[str, Any],
    ) -> Optional[AttackerProfile]:
        """
        Compare *observed_behavior* against every stored profile and return
        the best match (if any exceeds the similarity threshold).

        Parameters
        ----------
        observed_behavior:
            A dict whose keys are a superset of ``BEHAVIORAL_VECTOR_KEYS``
            with float values in [0, 1].

        Returns
        -------
        AttackerProfile or None
            The closest matching profile, or ``None`` if no match exceeds
            the threshold.
        """
        query_vector = self._extract_vector(observed_behavior)

        async with self._lock:
            best_match: Optional[AttackerProfile] = None
            best_similarity: float = -1.0

            for pid, stored_vector in self._vectors.items():
                sim = self._cosine_similarity(query_vector, stored_vector)
                if sim > best_similarity:
                    best_similarity = sim
                    best_match = self._profiles.get(pid)

        if best_similarity >= self._similarity_threshold and best_match:
            logger.info(
                "Fingerprint match: profile=%s similarity=%.4f",
                best_match.profile_id,
                best_similarity,
            )
            return best_match

        logger.debug(
            "No fingerprint match — best similarity=%.4f (threshold=%.2f)",
            best_similarity,
            self._similarity_threshold,
        )
        return None

    async def update_fingerprint(
        self,
        profile_id: UUID,
        new_observations: Dict[str, Any],
    ) -> Optional[AttackerProfile]:
        """
        Enrich an existing attacker profile with fresh observations.

        The profile's ``behavioral_patterns`` are merged (new keys added,
        existing keys updated), its ``last_seen`` timestamp is refreshed,
        and its behavioural vector is recomputed.

        Parameters
        ----------
        profile_id:
            The UUID of the profile to update.
        new_observations:
            A dict of new behavioural observations to merge in.

        Returns
        -------
        AttackerProfile or None
            The updated profile, or ``None`` if *profile_id* was not found.
        """
        async with self._lock:
            profile = self._profiles.get(profile_id)
            if profile is None:
                logger.warning(
                    "update_fingerprint: profile %s not found", profile_id
                )
                return None

            # Merge observations
            profile.behavioral_patterns.update(new_observations)
            profile.last_seen = datetime.utcnow()

            # Merge tool signatures if provided
            if "tool_signatures" in new_observations:
                new_tools = new_observations["tool_signatures"]
                if isinstance(new_tools, list):
                    existing = set(profile.tool_signatures)
                    existing.update(new_tools)
                    profile.tool_signatures = sorted(existing)

            # Merge active channels if provided
            if "active_channels" in new_observations:
                new_channels = new_observations["active_channels"]
                if isinstance(new_channels, list):
                    existing_ch = set(profile.active_channels)
                    existing_ch.update(new_channels)
                    profile.active_channels = sorted(existing_ch)

            # Recompute vector
            self._vectors[profile_id] = self._extract_vector(
                profile.behavioral_patterns
            )
            self._dirty.add(profile_id)

        logger.info(
            "Updated attacker fingerprint %s — %d new observation keys",
            profile_id,
            len(new_observations),
        )
        return profile

    async def get_all_fingerprints(self) -> List[AttackerProfile]:
        """
        Retrieve all stored attacker profiles.

        Returns
        -------
        list[AttackerProfile]
            A shallow copy of all profiles, ordered by ``first_seen``.
        """
        async with self._lock:
            profiles = sorted(
                self._profiles.values(),
                key=lambda p: p.first_seen,
            )
        return profiles

    async def get_fingerprint(self, profile_id: UUID) -> Optional[AttackerProfile]:
        """Retrieve a single profile by ID."""
        async with self._lock:
            return self._profiles.get(profile_id)

    async def flush_to_db(self, pool) -> int:
        """
        Persist dirty (new or modified) profiles to the
        ``attacker_fingerprints`` PostgreSQL table.

        Parameters
        ----------
        pool:
            An ``asyncpg.Pool`` instance.

        Returns
        -------
        int
            Number of profiles written.
        """
        async with self._lock:
            if not self._dirty:
                return 0
            to_flush = [
                self._profiles[pid]
                for pid in self._dirty
                if pid in self._profiles
            ]
            self._dirty.clear()

        flushed = 0
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    for profile in to_flush:
                        await conn.execute(
                            """
                            INSERT INTO attacker_fingerprints (
                                profile_id,
                                communication_protocol,
                                network_topology,
                                tool_signatures,
                                behavioral_patterns,
                                working_hours,
                                timezone_estimate,
                                sophistication_level,
                                first_seen,
                                last_seen,
                                active_channels,
                                expected_responses
                            ) VALUES (
                                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
                            )
                            ON CONFLICT (profile_id) DO UPDATE SET
                                communication_protocol = EXCLUDED.communication_protocol,
                                network_topology = EXCLUDED.network_topology,
                                tool_signatures = EXCLUDED.tool_signatures,
                                behavioral_patterns = EXCLUDED.behavioral_patterns,
                                working_hours = EXCLUDED.working_hours,
                                timezone_estimate = EXCLUDED.timezone_estimate,
                                sophistication_level = EXCLUDED.sophistication_level,
                                last_seen = EXCLUDED.last_seen,
                                active_channels = EXCLUDED.active_channels,
                                expected_responses = EXCLUDED.expected_responses
                            """,
                            profile.profile_id,
                            json.dumps(profile.communication_protocol),
                            json.dumps(profile.network_topology),
                            profile.tool_signatures,
                            json.dumps(profile.behavioral_patterns),
                            profile.working_hours,
                            profile.timezone_estimate,
                            profile.sophistication_level,
                            profile.first_seen,
                            profile.last_seen,
                            profile.active_channels,
                            json.dumps(profile.expected_responses),
                        )
                        flushed += 1

            logger.info(
                "Flushed %d attacker fingerprint(s) to database", flushed
            )
        except Exception:
            # Re-mark as dirty so the next flush retries
            async with self._lock:
                for profile in to_flush:
                    self._dirty.add(profile.profile_id)
            logger.exception(
                "Failed to flush %d attacker fingerprints — re-marked dirty",
                len(to_flush),
            )
            raise

        return flushed

    # ------------------------------------------------------------------
    # Similarity engine
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_vector(behavioral_data: Dict[str, Any]) -> List[float]:
        """
        Project a behavioural data dict into the canonical fixed-dimension
        vector space.  Missing keys default to 0.0; values are clamped to
        [0, 1].

        Parameters
        ----------
        behavioral_data:
            Arbitrary dict — only keys present in
            ``BEHAVIORAL_VECTOR_KEYS`` are used.

        Returns
        -------
        list[float]
            A vector of length ``len(BEHAVIORAL_VECTOR_KEYS)``.
        """
        vector: List[float] = []
        for key in BEHAVIORAL_VECTOR_KEYS:
            raw = behavioral_data.get(key, 0.0)
            try:
                val = float(raw)
            except (TypeError, ValueError):
                val = 0.0
            # Clamp to [0, 1]
            vector.append(max(0.0, min(1.0, val)))
        return vector

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """
        Compute cosine similarity between two equal-length float vectors.

        Returns a value in [-1, 1]; higher means more similar.
        For our non-negative behavioural vectors the range is [0, 1].

        Parameters
        ----------
        a, b:
            Vectors of equal length.

        Returns
        -------
        float
            Cosine similarity, or 0.0 if either vector has zero magnitude.
        """
        if len(a) != len(b):
            return 0.0

        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(y * y for y in b))

        if mag_a == 0.0 or mag_b == 0.0:
            return 0.0

        return dot / (mag_a * mag_b)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def profile_count(self) -> int:
        """Number of stored attacker profiles."""
        return len(self._profiles)

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics."""
        return {
            "profile_count": self.profile_count,
            "dirty_count": len(self._dirty),
            "similarity_threshold": self._similarity_threshold,
            "vector_dimensions": len(BEHAVIORAL_VECTOR_KEYS),
        }

    def __repr__(self) -> str:
        return (
            f"<AttackerFingerprintDB profiles={self.profile_count} "
            f"threshold={self._similarity_threshold:.2f}>"
        )
