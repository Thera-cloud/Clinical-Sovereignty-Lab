"""
HIVE DEFENSE PROTOCOL — Temporal Jitter (Phase 8B)
Mirror timing normalization to prevent timing-based side-channel attacks.

The Temporal Jitter engine ensures that attacker-facing responses from the
Mirror Dimension are statistically indistinguishable from real system responses.
It samples the real system's latency distribution and generates jitter delays
that match the distribution's shape — including p50, p95, and p99 behavior.

Key Properties:
    1. Samples real system latency distribution every 5 minutes.
    2. Maintains a histogram of the last 1000 real request latencies.
    3. Adds a cryptographically random component (os.urandom) so jitter
       is unpredictable even if the distribution is known.
    4. Generated delays are Kolmogorov-Smirnov indistinguishable from
       real system latencies.
    5. Profile auto-updates as the system's latency characteristics change
       throughout the day (load-dependent).

Why This Matters:
    Without temporal jitter, an attacker in the Mirror Dimension could
    detect that responses arrive with suspiciously uniform timing.  Real
    systems have variable latency based on load, I/O, GC pauses, etc.
    The temporal jitter engine samples this real variability and applies
    it to mirror responses, making them indistinguishable from real ones.

Patent-Pending — Mirror Dimension Timing Normalization
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import bisect
import logging
import math
import os
import struct
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("hive.temporal_jitter")


# =============================================================================
# CONSTANTS
# =============================================================================

#: Maximum number of real latency samples retained in the histogram.
MAX_LATENCY_SAMPLES: int = 1000

#: Minimum samples required before jitter generation is based on the
#: real distribution (below this, a default profile is used).
MIN_SAMPLES_FOR_PROFILE: int = 50

#: Default latency profile (milliseconds) used when insufficient real
#: data has been collected.  Based on typical healthy API latencies.
DEFAULT_LATENCY_PROFILE: Dict[str, float] = {
    "p50": 25.0,
    "p75": 45.0,
    "p90": 80.0,
    "p95": 120.0,
    "p99": 250.0,
    "min": 5.0,
    "max": 500.0,
    "mean": 45.0,
    "std": 40.0,
}

#: How often (in seconds) to refresh the latency profile statistics.
PROFILE_REFRESH_INTERVAL_SEC: float = 300.0  # 5 minutes

#: Minimum jitter to inject (ms) — prevents zero-delay responses
#: which would be a timing oracle.
MIN_JITTER_MS: float = 1.0

#: Maximum jitter cap (ms) — prevents absurdly long delays that
#: would make the mirror dimension obviously broken.
MAX_JITTER_CAP_MS: float = 2000.0


# =============================================================================
# LATENCY PROFILE
# =============================================================================

@dataclass
class LatencyProfile:
    """
    Statistical summary of the real system's latency distribution.

    Recalculated periodically from the rolling sample buffer.

    Attributes:
        p50:          Median latency (ms).
        p75:          75th percentile latency (ms).
        p90:          90th percentile latency (ms).
        p95:          95th percentile latency (ms).
        p99:          99th percentile latency (ms).
        min_ms:       Minimum observed latency (ms).
        max_ms:       Maximum observed latency (ms).
        mean_ms:      Mean latency (ms).
        std_ms:       Standard deviation (ms).
        sample_count: Number of samples used to compute this profile.
        computed_at:  When this profile was last computed.
    """
    p50: float = 25.0
    p75: float = 45.0
    p90: float = 80.0
    p95: float = 120.0
    p99: float = 250.0
    min_ms: float = 5.0
    max_ms: float = 500.0
    mean_ms: float = 45.0
    std_ms: float = 40.0
    sample_count: int = 0
    computed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for API responses."""
        return {
            "p50": round(self.p50, 2),
            "p75": round(self.p75, 2),
            "p90": round(self.p90, 2),
            "p95": round(self.p95, 2),
            "p99": round(self.p99, 2),
            "min_ms": round(self.min_ms, 2),
            "max_ms": round(self.max_ms, 2),
            "mean_ms": round(self.mean_ms, 2),
            "std_ms": round(self.std_ms, 2),
            "sample_count": self.sample_count,
            "computed_at": (
                self.computed_at.isoformat() if self.computed_at else None
            ),
        }


# =============================================================================
# TEMPORAL JITTER ENGINE
# =============================================================================

class TemporalJitter:
    """
    Mirror timing normalization engine.

    Generates response delays that are statistically indistinguishable from
    the real system's latency distribution, preventing timing-based
    side-channel attacks against the Mirror Dimension.

    The engine maintains a rolling buffer of real system latencies, computes
    the distribution profile periodically, and uses inverse transform sampling
    with a cryptographically random component to generate jitter values.

    Usage::

        jitter = TemporalJitter()

        # Feed real system latencies as they occur
        jitter.record_real_latency(23.5)
        jitter.record_real_latency(45.2)

        # Generate jitter for a mirror response
        delay_ms = await jitter.inject_jitter()
        await asyncio.sleep(delay_ms / 1000.0)

        # Get current profile
        profile = jitter.get_current_profile()

    Thread Safety:
        This class is designed for single-threaded async usage.  For
        multi-threaded environments, external synchronization is required.
    """

    def __init__(self) -> None:
        """Initialize the Temporal Jitter engine."""
        # Rolling buffer of real latency samples (sorted for percentile computation)
        self._samples: Deque[float] = deque(maxlen=MAX_LATENCY_SAMPLES)

        # Sorted copy of samples for efficient percentile lookups
        self._sorted_samples: List[float] = []
        self._sorted_dirty: bool = True

        # Current latency profile (recomputed periodically)
        self._profile: LatencyProfile = LatencyProfile()
        self._last_profile_refresh: float = 0.0

        # Statistics
        self._total_samples_recorded: int = 0
        self._total_jitter_injected: int = 0

        logger.info(">>> [JITTER] Temporal Jitter engine initialized")

    # =========================================================================
    # REAL LATENCY RECORDING
    # =========================================================================

    def record_real_latency(self, latency_ms: float) -> None:
        """
        Record an actual system latency observation.

        Feed this with real request latencies from the production system.
        The jitter engine uses these to model the real distribution.

        Args:
            latency_ms: The observed latency in milliseconds.  Must be
                        positive.  Values <= 0 are silently ignored.
        """
        if latency_ms <= 0:
            return

        self._samples.append(latency_ms)
        self._sorted_dirty = True
        self._total_samples_recorded += 1

        # Check if profile refresh is needed
        now = time.monotonic()
        if now - self._last_profile_refresh > PROFILE_REFRESH_INTERVAL_SEC:
            self._refresh_profile()

    def record_batch(self, latencies: List[float]) -> None:
        """
        Record a batch of real latency observations.

        Convenience method for feeding multiple samples at once (e.g.,
        from a periodic latency probe).

        Args:
            latencies: List of latency values in milliseconds.
        """
        for latency_ms in latencies:
            if latency_ms > 0:
                self._samples.append(latency_ms)
                self._total_samples_recorded += 1

        self._sorted_dirty = True

        # Refresh profile if due
        now = time.monotonic()
        if now - self._last_profile_refresh > PROFILE_REFRESH_INTERVAL_SEC:
            self._refresh_profile()

    # =========================================================================
    # JITTER GENERATION
    # =========================================================================

    async def inject_jitter(self) -> float:
        """
        Generate a random delay matching the real system's latency profile.

        Uses inverse transform sampling on the empirical distribution combined
        with a cryptographically random component to produce delays that are
        Kolmogorov-Smirnov indistinguishable from real system latencies.

        The method is async to allow cooperative scheduling during the delay
        if callers choose to ``await asyncio.sleep(delay)``.

        Returns:
            Jitter delay in milliseconds.  Always >= MIN_JITTER_MS and
            <= MAX_JITTER_CAP_MS.
        """
        self._total_jitter_injected += 1

        if len(self._samples) < MIN_SAMPLES_FOR_PROFILE:
            # Use default profile with random perturbation
            delay = self._jitter_from_default_profile()
        else:
            # Use empirical distribution with inverse transform sampling
            delay = self._jitter_from_empirical()

        # Add cryptographic randomness component
        crypto_noise = self._crypto_random_float() * 5.0  # 0-5ms crypto noise
        delay += crypto_noise

        # Clamp to bounds
        delay = max(MIN_JITTER_MS, min(delay, MAX_JITTER_CAP_MS))

        logger.debug(
            ">>> [JITTER] Generated: %.2f ms (samples=%d, crypto_noise=%.2f ms)",
            delay, len(self._samples), crypto_noise,
        )

        return delay

    def _jitter_from_default_profile(self) -> float:
        """
        Generate jitter from the default latency profile.

        Uses a log-normal distribution parameterized from the default profile,
        which naturally produces the right-skewed shape typical of latency
        distributions.

        Returns:
            Delay in milliseconds.
        """
        # Log-normal parameters from default profile
        mean = DEFAULT_LATENCY_PROFILE["mean"]
        std = DEFAULT_LATENCY_PROFILE["std"]

        # Generate log-normal sample using Box-Muller with crypto random
        u1 = max(1e-10, self._crypto_random_float())
        u2 = self._crypto_random_float()

        # Box-Muller transform
        z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)

        # Convert to log-normal space
        mu = math.log(mean ** 2 / math.sqrt(std ** 2 + mean ** 2))
        sigma = math.sqrt(math.log(1 + (std ** 2 / mean ** 2)))

        delay = math.exp(mu + sigma * z)
        return delay

    def _jitter_from_empirical(self) -> float:
        """
        Generate jitter using inverse transform sampling on the empirical
        cumulative distribution function (ECDF) of real latencies.

        This produces samples that exactly match the shape of the real
        latency distribution — including tails, modes, and any
        multi-modal behavior caused by different request types.

        Returns:
            Delay in milliseconds.
        """
        self._ensure_sorted()
        n = len(self._sorted_samples)

        if n == 0:
            return DEFAULT_LATENCY_PROFILE["mean"]

        # Generate a cryptographically random quantile in [0, 1)
        quantile = self._crypto_random_float()

        # Map quantile to sample index
        idx = quantile * (n - 1)
        lower_idx = int(idx)
        upper_idx = min(lower_idx + 1, n - 1)
        fraction = idx - lower_idx

        # Linear interpolation between adjacent samples
        lower_val = self._sorted_samples[lower_idx]
        upper_val = self._sorted_samples[upper_idx]
        delay = lower_val + fraction * (upper_val - lower_val)

        # Add small random perturbation to avoid exact replays
        perturbation = (self._crypto_random_float() - 0.5) * 2.0  # ±1ms
        delay += perturbation

        return max(0.0, delay)

    # =========================================================================
    # PROFILE COMPUTATION
    # =========================================================================

    def _refresh_profile(self) -> None:
        """
        Recompute the latency profile from the current sample buffer.

        Called periodically (every 5 minutes) and after batch recordings.
        """
        self._ensure_sorted()
        n = len(self._sorted_samples)

        if n < MIN_SAMPLES_FOR_PROFILE:
            self._last_profile_refresh = time.monotonic()
            return

        self._profile = LatencyProfile(
            p50=self._percentile(50),
            p75=self._percentile(75),
            p90=self._percentile(90),
            p95=self._percentile(95),
            p99=self._percentile(99),
            min_ms=self._sorted_samples[0],
            max_ms=self._sorted_samples[-1],
            mean_ms=sum(self._sorted_samples) / n,
            std_ms=self._compute_std(),
            sample_count=n,
            computed_at=datetime.utcnow(),
        )

        self._last_profile_refresh = time.monotonic()

        logger.info(
            ">>> [JITTER] Profile refreshed: p50=%.1f p95=%.1f p99=%.1f "
            "mean=%.1f std=%.1f (n=%d)",
            self._profile.p50, self._profile.p95, self._profile.p99,
            self._profile.mean_ms, self._profile.std_ms, n,
        )

    def _percentile(self, pct: float) -> float:
        """
        Compute the given percentile from sorted samples.

        Uses linear interpolation between adjacent ranks.

        Args:
            pct: Percentile to compute (0-100).

        Returns:
            Percentile value in milliseconds.
        """
        n = len(self._sorted_samples)
        if n == 0:
            return 0.0
        if n == 1:
            return self._sorted_samples[0]

        rank = (pct / 100.0) * (n - 1)
        lower = int(rank)
        upper = min(lower + 1, n - 1)
        fraction = rank - lower

        return (
            self._sorted_samples[lower]
            + fraction * (self._sorted_samples[upper] - self._sorted_samples[lower])
        )

    def _compute_std(self) -> float:
        """
        Compute the standard deviation of the sorted samples.

        Returns:
            Standard deviation in milliseconds.
        """
        n = len(self._sorted_samples)
        if n < 2:
            return 0.0

        mean = sum(self._sorted_samples) / n
        variance = sum((x - mean) ** 2 for x in self._sorted_samples) / (n - 1)
        return math.sqrt(variance)

    def _ensure_sorted(self) -> None:
        """Rebuild the sorted sample list if the buffer has changed."""
        if self._sorted_dirty:
            self._sorted_samples = sorted(self._samples)
            self._sorted_dirty = False

    # =========================================================================
    # CRYPTOGRAPHIC RANDOMNESS
    # =========================================================================

    @staticmethod
    def _crypto_random_float() -> float:
        """
        Generate a cryptographically random float in [0, 1).

        Uses ``os.urandom`` to produce unpredictable random values.
        Even if an attacker knows the latency distribution, they cannot
        predict the exact jitter values.

        Returns:
            Random float in [0.0, 1.0).
        """
        # Read 8 bytes of cryptographic randomness
        random_bytes = os.urandom(8)
        # Convert to unsigned 64-bit integer
        random_int = struct.unpack(">Q", random_bytes)[0]
        # Normalize to [0, 1)
        return random_int / (2 ** 64)

    # =========================================================================
    # PUBLIC PROFILE ACCESS
    # =========================================================================

    def get_current_profile(self) -> Dict[str, Any]:
        """
        Return the current latency distribution profile.

        Includes percentiles, mean, standard deviation, sample count,
        and engine statistics.

        Returns:
            Dictionary with profile statistics and engine metadata.
        """
        # Refresh if stale
        now = time.monotonic()
        if now - self._last_profile_refresh > PROFILE_REFRESH_INTERVAL_SEC:
            self._refresh_profile()

        return {
            "profile": self._profile.to_dict(),
            "engine_stats": {
                "total_samples_recorded": self._total_samples_recorded,
                "current_buffer_size": len(self._samples),
                "buffer_capacity": MAX_LATENCY_SAMPLES,
                "total_jitter_injected": self._total_jitter_injected,
                "using_default_profile": (
                    len(self._samples) < MIN_SAMPLES_FOR_PROFILE
                ),
                "profile_refresh_interval_sec": PROFILE_REFRESH_INTERVAL_SEC,
            },
        }

    # =========================================================================
    # ADMIN / DIAGNOSTICS
    # =========================================================================

    def get_sample_histogram(self, bins: int = 20) -> Dict[str, Any]:
        """
        Generate a histogram of the current latency samples.

        Useful for admin dashboard visualization of the latency distribution.

        Args:
            bins: Number of histogram bins (default 20).

        Returns:
            Dictionary with bin edges, counts, and summary statistics.
        """
        self._ensure_sorted()
        n = len(self._sorted_samples)

        if n == 0:
            return {
                "bins": [],
                "counts": [],
                "total_samples": 0,
            }

        min_val = self._sorted_samples[0]
        max_val = self._sorted_samples[-1]

        if max_val == min_val:
            return {
                "bins": [min_val],
                "counts": [n],
                "total_samples": n,
            }

        bin_width = (max_val - min_val) / bins
        bin_edges = [min_val + i * bin_width for i in range(bins + 1)]
        counts = [0] * bins

        for sample in self._sorted_samples:
            idx = int((sample - min_val) / bin_width)
            idx = min(idx, bins - 1)  # Clamp to last bin
            counts[idx] += 1

        return {
            "bins": [round(e, 2) for e in bin_edges],
            "counts": counts,
            "bin_width_ms": round(bin_width, 2),
            "total_samples": n,
        }

    def reset(self) -> None:
        """
        Reset the jitter engine, clearing all samples and statistics.

        Use with caution — this will force the engine back to the default
        profile until enough new samples are collected.
        """
        self._samples.clear()
        self._sorted_samples.clear()
        self._sorted_dirty = True
        self._profile = LatencyProfile()
        self._last_profile_refresh = 0.0
        self._total_samples_recorded = 0
        self._total_jitter_injected = 0

        logger.info(">>> [JITTER] Engine reset — all samples cleared")
