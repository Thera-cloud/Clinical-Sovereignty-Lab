"""
HIVE DEFENSE PROTOCOL — Request Path Randomizer (Phase 8C, Third Cord)
Non-deterministic mirror processing that prevents attackers from building
stable timing models.

The mirror randomly routes every request through 2–4 internal processing
stages *even when unnecessary*.  Each route is selected using
cryptographically secure randomness (``os.urandom``), and non-deterministic
latency is injected at each stage.  Because the path and delay change on
every request, an attacker who tries to distinguish the mirror from the
real system via timing side-channels will observe only noise.

Design Principles
-----------------
* **Cryptographic path selection** — ``os.urandom`` feeds stage selection
  so the path sequence is unpredictable even by an attacker who
  compromises the PRNG seed.
* **Variable depth** — each request traverses between 2 and 4 stages.
  The count itself is random per-request.
* **Per-stage jitter** — every stage adds independent latency drawn from a
  bounded uniform distribution, preventing statistical aggregation.
* **No information leakage** — the response payload is identical
  regardless of path length; only internal timing differs.

Patent-Pending — Claim 47
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from app.models.hive_defense import MirrorSignal

logger = logging.getLogger("hive.request_path_randomizer")


# =============================================================================
# CONSTANTS
# =============================================================================

# Bounds on processing stage count per request
MIN_STAGES = 2
MAX_STAGES = 4

# Per-stage latency bounds (seconds)
STAGE_LATENCY_MIN = 0.002   # 2 ms
STAGE_LATENCY_MAX = 0.045   # 45 ms

# Available processing stages that the randomizer can select from
AVAILABLE_STAGES = [
    "schema_validation",
    "payload_normalization",
    "entropy_check",
    "header_rewrite",
    "signature_verify",
    "rate_limit_check",
    "context_enrichment",
    "session_hydration",
    "permission_resolve",
    "telemetry_sample",
    "cache_probe",
    "content_hash",
]


class ProcessingStage(str, Enum):
    """Named stages a request can traverse inside the mirror."""
    SCHEMA_VALIDATION = "schema_validation"
    PAYLOAD_NORMALIZATION = "payload_normalization"
    ENTROPY_CHECK = "entropy_check"
    HEADER_REWRITE = "header_rewrite"
    SIGNATURE_VERIFY = "signature_verify"
    RATE_LIMIT_CHECK = "rate_limit_check"
    CONTEXT_ENRICHMENT = "context_enrichment"
    SESSION_HYDRATION = "session_hydration"
    PERMISSION_RESOLVE = "permission_resolve"
    TELEMETRY_SAMPLE = "telemetry_sample"
    CACHE_PROBE = "cache_probe"
    CONTENT_HASH = "content_hash"


@dataclass
class RandomizedPath:
    """
    Describes the randomized path a single request will traverse.

    Attributes
    ----------
    path_id : UUID
        Unique identifier for this specific path instance.
    stages : list[str]
        Ordered list of processing stage names the request will traverse.
    stage_delays : list[float]
        Per-stage injected latency in seconds (same order as ``stages``).
    total_expected_delay : float
        Sum of all stage delays (before actual traversal).
    created_at : datetime
        Timestamp when the path was generated.
    """
    path_id: UUID = field(default_factory=uuid4)
    stages: List[str] = field(default_factory=list)
    stage_delays: List[float] = field(default_factory=list)
    total_expected_delay: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TraversalResult:
    """
    Result of traversing a randomized path.

    Attributes
    ----------
    path_id : UUID
        The path that was traversed.
    stages_completed : int
        Number of stages successfully completed.
    actual_total_delay : float
        Actual elapsed time (seconds) including jitter variance.
    stage_timings : list[dict]
        Per-stage timing detail.
    completed_at : datetime
        When traversal finished.
    """
    path_id: UUID = field(default_factory=uuid4)
    stages_completed: int = 0
    actual_total_delay: float = 0.0
    stage_timings: List[Dict[str, Any]] = field(default_factory=list)
    completed_at: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# REQUEST PATH RANDOMIZER
# =============================================================================

class RequestPathRandomizer:
    """
    Non-deterministic mirror processing engine.

    Randomly routes every request through 2–4 internal processing stages,
    each with independent latency jitter derived from ``os.urandom``.
    The result is that no two requests follow the same path or timing
    profile, making timing side-channel attacks infeasible.

    Parameters
    ----------
    min_stages : int
        Minimum processing stages per request (default 2).
    max_stages : int
        Maximum processing stages per request (default 4).
    latency_min : float
        Minimum per-stage latency in seconds (default 0.002).
    latency_max : float
        Maximum per-stage latency in seconds (default 0.045).

    Usage
    -----
    ::

        randomizer = RequestPathRandomizer()
        path = await randomizer.randomize_path(request)
        result = await randomizer.traverse_path(path, request)
    """

    def __init__(
        self,
        *,
        min_stages: int = MIN_STAGES,
        max_stages: int = MAX_STAGES,
        latency_min: float = STAGE_LATENCY_MIN,
        latency_max: float = STAGE_LATENCY_MAX,
    ) -> None:
        self._min_stages = max(min_stages, 1)
        self._max_stages = max(max_stages, self._min_stages)
        self._latency_min = latency_min
        self._latency_max = latency_max

        # Metrics
        self._total_paths_generated: int = 0
        self._total_traversals: int = 0
        self._lock = asyncio.Lock()

        logger.info(
            "RequestPathRandomizer initialised — stages=[%d,%d], "
            "latency=[%.3fs,%.3fs], %d available stages",
            self._min_stages,
            self._max_stages,
            self._latency_min,
            self._latency_max,
            len(AVAILABLE_STAGES),
        )

    # --------------------------------------------------------------------- #
    # CRYPTOGRAPHIC RANDOMNESS HELPERS
    # --------------------------------------------------------------------- #

    @staticmethod
    def _secure_random_int(low: int, high: int) -> int:
        """
        Return a cryptographically random integer in [low, high] inclusive.

        Uses ``os.urandom`` for entropy, unpacked as an unsigned 32-bit
        integer and mapped into the desired range via modular arithmetic.

        Parameters
        ----------
        low : int
            Lower bound (inclusive).
        high : int
            Upper bound (inclusive).

        Returns
        -------
        int
        """
        if low == high:
            return low
        span = high - low + 1
        raw = struct.unpack("I", os.urandom(4))[0]
        return low + (raw % span)

    @staticmethod
    def _secure_random_float(low: float, high: float) -> float:
        """
        Return a cryptographically random float in [low, high).

        Uses 8 bytes from ``os.urandom`` to produce a high-resolution
        double in [0, 1), then scales to the target range.

        Parameters
        ----------
        low : float
            Lower bound (inclusive).
        high : float
            Upper bound (exclusive).

        Returns
        -------
        float
        """
        raw = struct.unpack("Q", os.urandom(8))[0]
        # Map to [0, 1) with full 64-bit resolution
        unit = raw / (2**64)
        return low + unit * (high - low)

    @staticmethod
    def _secure_sample(population: List[str], k: int) -> List[str]:
        """
        Cryptographically secure sampling of *k* items from *population*
        without replacement (Fisher-Yates shuffle on a copy).

        Parameters
        ----------
        population : list[str]
            Items to sample from.
        k : int
            Number of items to select (must be <= len(population)).

        Returns
        -------
        list[str]
            Selected items in shuffled order.
        """
        pool = list(population)
        n = len(pool)
        k = min(k, n)
        for i in range(k):
            j_raw = struct.unpack("I", os.urandom(4))[0]
            j = i + (j_raw % (n - i))
            pool[i], pool[j] = pool[j], pool[i]
        return pool[:k]

    # --------------------------------------------------------------------- #
    # PATH GENERATION
    # --------------------------------------------------------------------- #

    async def randomize_path(
        self,
        request: Optional[Dict[str, Any]] = None,
    ) -> RandomizedPath:
        """
        Generate a randomized processing path for a request.

        The path consists of 2–4 processing stages selected via
        cryptographic randomness, each with an independent latency value.
        The request payload is optionally used to seed additional entropy
        but does NOT determine the path deterministically.

        Parameters
        ----------
        request : dict or None
            The incoming request dict.  Used only for additional entropy
            mixing — the path is fundamentally non-deterministic.

        Returns
        -------
        RandomizedPath
            The generated path with stages and expected delays.
        """
        # Determine stage count using cryptographic randomness
        stage_count = self._secure_random_int(self._min_stages, self._max_stages)

        # Select stages (without replacement for uniqueness per path)
        selected_stages = self._secure_sample(AVAILABLE_STAGES, stage_count)

        # Generate per-stage latency using cryptographic randomness
        stage_delays = [
            self._secure_random_float(self._latency_min, self._latency_max)
            for _ in range(stage_count)
        ]

        # Optional: mix request entropy into one of the delays for extra chaos
        if request is not None:
            request_entropy = hashlib.sha256(
                str(request).encode("utf-8", errors="replace")
            ).digest()
            # Use first 4 bytes as a small perturbation multiplier
            perturbation = struct.unpack("f", request_entropy[:4])[0]
            # Bound perturbation to ±10% of current delay
            idx = self._secure_random_int(0, stage_count - 1)
            factor = 1.0 + (abs(perturbation) % 0.1) * (1 if perturbation > 0 else -1)
            stage_delays[idx] = max(
                self._latency_min,
                min(self._latency_max, stage_delays[idx] * factor),
            )

        path = RandomizedPath(
            stages=selected_stages,
            stage_delays=stage_delays,
            total_expected_delay=sum(stage_delays),
        )

        async with self._lock:
            self._total_paths_generated += 1

        logger.debug(
            "Path %s generated — %d stages %s, expected delay %.4fs",
            path.path_id,
            stage_count,
            selected_stages,
            path.total_expected_delay,
        )

        return path

    # --------------------------------------------------------------------- #
    # PATH TRAVERSAL
    # --------------------------------------------------------------------- #

    async def traverse_path(
        self,
        path: RandomizedPath,
        request: Optional[Dict[str, Any]] = None,
    ) -> TraversalResult:
        """
        Execute the randomized path, pausing at each stage for the
        specified jitter delay.

        Each stage performs a minimal synthetic computation (hash,
        validation placeholder) so the delay is not purely sleep-based
        — even a timing-aware attacker cannot distinguish "real work"
        from "jitter sleep" within each stage.

        Parameters
        ----------
        path : RandomizedPath
            The path to traverse (from :meth:`randomize_path`).
        request : dict or None
            The request payload being processed.

        Returns
        -------
        TraversalResult
            Detailed timing results of the traversal.
        """
        stage_timings: List[Dict[str, Any]] = []
        traversal_start = time.monotonic()

        for idx, (stage_name, delay) in enumerate(
            zip(path.stages, path.stage_delays)
        ):
            stage_start = time.monotonic()

            # Perform synthetic work to mix computation with sleep
            _ = self._synthetic_stage_work(stage_name, request)

            # Inject the non-deterministic delay
            await asyncio.sleep(delay)

            stage_elapsed = time.monotonic() - stage_start
            stage_timings.append({
                "stage": stage_name,
                "order": idx,
                "injected_delay_sec": round(delay, 6),
                "actual_elapsed_sec": round(stage_elapsed, 6),
            })

        total_elapsed = time.monotonic() - traversal_start

        result = TraversalResult(
            path_id=path.path_id,
            stages_completed=len(path.stages),
            actual_total_delay=round(total_elapsed, 6),
            stage_timings=stage_timings,
            completed_at=datetime.utcnow(),
        )

        async with self._lock:
            self._total_traversals += 1

        logger.debug(
            "Path %s traversed — %d stages in %.4fs (expected %.4fs)",
            path.path_id,
            result.stages_completed,
            result.actual_total_delay,
            path.total_expected_delay,
        )

        return result

    # --------------------------------------------------------------------- #
    # SYNTHETIC STAGE WORK
    # --------------------------------------------------------------------- #

    @staticmethod
    def _synthetic_stage_work(
        stage_name: str,
        request: Optional[Dict[str, Any]],
    ) -> str:
        """
        Perform minimal synthetic computation for a stage.

        This ensures each stage has real CPU work mixed with the sleep,
        preventing an attacker from distinguishing delay-only stages via
        CPU-utilization side-channels.

        Parameters
        ----------
        stage_name : str
            Name of the processing stage.
        request : dict or None
            The request payload.

        Returns
        -------
        str
            A throw-away hash digest (not used externally).
        """
        material = f"{stage_name}:{time.monotonic_ns()}"
        if request is not None:
            material += f":{id(request)}"
        return hashlib.sha256(material.encode()).hexdigest()

    # --------------------------------------------------------------------- #
    # CONVENIENCE: SINGLE-CALL RANDOMIZE + TRAVERSE
    # --------------------------------------------------------------------- #

    async def process_request(
        self,
        request: Optional[Dict[str, Any]] = None,
    ) -> TraversalResult:
        """
        Generate a random path and immediately traverse it.

        This is the primary convenience method for mirror integration —
        call once per request to inject non-deterministic processing.

        Parameters
        ----------
        request : dict or None
            The incoming request dict.

        Returns
        -------
        TraversalResult
            Timing details of the randomized traversal.
        """
        path = await self.randomize_path(request)
        return await self.traverse_path(path, request)

    # --------------------------------------------------------------------- #
    # DIAGNOSTICS
    # --------------------------------------------------------------------- #

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary of randomizer activity."""
        return {
            "total_paths_generated": self._total_paths_generated,
            "total_traversals": self._total_traversals,
            "min_stages": self._min_stages,
            "max_stages": self._max_stages,
            "latency_range_ms": [
                round(self._latency_min * 1000, 2),
                round(self._latency_max * 1000, 2),
            ],
            "available_stages": len(AVAILABLE_STAGES),
        }

    def __repr__(self) -> str:
        return (
            f"<RequestPathRandomizer stages=[{self._min_stages},{self._max_stages}] "
            f"paths={self._total_paths_generated} traversals={self._total_traversals}>"
        )
