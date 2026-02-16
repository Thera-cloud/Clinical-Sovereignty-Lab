"""
HIVE DEFENSE PROTOCOL — Adaptive Load Simulator (Phase 8C, Third Cord)
Real-time load-matched mirror latency that co-varies with the real system.

The mirror's response timing must be indistinguishable from the real
system's under all load conditions.  This service continuously ingests
real system metrics (CPU %, memory %, request rate) and produces
simulated delays that match the real system's current load profile.

When the real system is under heavy load and responding slowly, the
mirror slows proportionally.  When the real system is idle and fast,
the mirror speeds up.  An attacker comparing timing between the two
environments sees statistically identical distributions at every
sample window.

Load Model
----------
The delay function is a weighted combination of three signals:

    delay(t) = α · f_cpu(cpu_pct) + β · f_mem(mem_pct) + γ · f_rate(rps)

Where:
    - f_cpu  models CPU contention (exponential above 70%)
    - f_mem  models memory pressure (linear degradation)
    - f_rate models queuing delay (Little's Law approximation)
    - α, β, γ are configurable weight coefficients

Gaussian noise is added on top to simulate real-world jitter.

Patent-Pending — Claim 48
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import struct
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("hive.adaptive_load_simulator")


# =============================================================================
# CONSTANTS
# =============================================================================

# Default load model weights
DEFAULT_ALPHA = 0.45   # CPU weight
DEFAULT_BETA = 0.25    # Memory weight
DEFAULT_GAMMA = 0.30   # Request rate weight

# Baseline latency (seconds) at zero load — minimum possible delay
BASELINE_LATENCY = 0.003  # 3 ms

# Maximum simulated delay cap (seconds)
MAX_SIMULATED_DELAY = 2.0  # 2 seconds

# Jitter magnitude as fraction of computed delay
JITTER_FRACTION = 0.10  # ±10%

# Rolling window size for metric smoothing (number of samples)
METRIC_WINDOW_SIZE = 60

# CPU model: delay starts climbing exponentially above this threshold
CPU_KNEE_THRESHOLD = 0.70


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class LoadSample:
    """
    A single snapshot of real system load metrics.

    Attributes
    ----------
    cpu_pct : float
        CPU utilization as a fraction in [0.0, 1.0].
    memory_pct : float
        Memory utilization as a fraction in [0.0, 1.0].
    request_rate : float
        Requests per second currently being served.
    sampled_at : float
        Monotonic timestamp when this sample was recorded.
    """
    cpu_pct: float = 0.0
    memory_pct: float = 0.0
    request_rate: float = 0.0
    sampled_at: float = field(default_factory=time.monotonic)


@dataclass
class LoadProfile:
    """
    Smoothed load profile derived from a rolling window of samples.

    Attributes
    ----------
    avg_cpu : float
        Exponentially weighted average CPU utilization.
    avg_memory : float
        Exponentially weighted average memory utilization.
    avg_request_rate : float
        Exponentially weighted average request rate.
    sample_count : int
        Total number of samples ingested.
    last_updated : datetime
        Wall-clock time of last profile recomputation.
    """
    avg_cpu: float = 0.0
    avg_memory: float = 0.0
    avg_request_rate: float = 0.0
    sample_count: int = 0
    last_updated: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# ADAPTIVE LOAD SIMULATOR
# =============================================================================

class AdaptiveLoadSimulator:
    """
    Mirror latency engine that matches the real system's load profile.

    Feed real metrics via :meth:`record_real_load` and call
    :meth:`get_simulated_delay` on each mirror request to obtain a
    delay value that mirrors the real system's current response time.

    Parameters
    ----------
    alpha : float
        Weight for CPU contribution to delay (default 0.45).
    beta : float
        Weight for memory contribution to delay (default 0.25).
    gamma : float
        Weight for request-rate contribution to delay (default 0.30).
    baseline_latency : float
        Minimum latency in seconds at zero load (default 0.003).
    max_delay : float
        Hard ceiling on simulated delay in seconds (default 2.0).
    window_size : int
        Rolling window size for metric smoothing (default 60).

    Usage
    -----
    ::

        sim = AdaptiveLoadSimulator()

        # Periodically feed real metrics
        await sim.record_real_load(cpu_pct=0.65, memory_pct=0.40, request_rate=120.0)

        # Per-request: get load-matched delay
        delay = await sim.get_simulated_delay()
        await asyncio.sleep(delay)
    """

    def __init__(
        self,
        *,
        alpha: float = DEFAULT_ALPHA,
        beta: float = DEFAULT_BETA,
        gamma: float = DEFAULT_GAMMA,
        baseline_latency: float = BASELINE_LATENCY,
        max_delay: float = MAX_SIMULATED_DELAY,
        window_size: int = METRIC_WINDOW_SIZE,
    ) -> None:
        self._alpha = alpha
        self._beta = beta
        self._gamma = gamma
        self._baseline = baseline_latency
        self._max_delay = max_delay
        self._window_size = window_size

        # Rolling metric windows
        self._cpu_window: Deque[float] = deque(maxlen=window_size)
        self._mem_window: Deque[float] = deque(maxlen=window_size)
        self._rate_window: Deque[float] = deque(maxlen=window_size)
        self._samples: Deque[LoadSample] = deque(maxlen=window_size)

        # Current smoothed profile
        self._profile = LoadProfile()

        # Peak rate tracking for normalization
        self._peak_request_rate: float = 1.0  # avoid division by zero

        # Concurrency control
        self._lock = asyncio.Lock()

        # Stats
        self._total_samples_ingested: int = 0
        self._total_delays_served: int = 0

        logger.info(
            "AdaptiveLoadSimulator initialised — weights(α=%.2f, β=%.2f, γ=%.2f), "
            "baseline=%.3fs, max=%.1fs, window=%d",
            self._alpha,
            self._beta,
            self._gamma,
            self._baseline,
            self._max_delay,
            self._window_size,
        )

    # --------------------------------------------------------------------- #
    # METRIC INGESTION
    # --------------------------------------------------------------------- #

    async def record_real_load(
        self,
        cpu_pct: float,
        memory_pct: float,
        request_rate: float,
    ) -> LoadProfile:
        """
        Feed a real system load sample into the simulator.

        The sample is appended to the rolling window and the smoothed
        profile is recomputed.  Call this periodically (e.g. every 1–5
        seconds) from a metrics collector.

        Parameters
        ----------
        cpu_pct : float
            Current CPU utilization as a percentage (0–100).
            Values are clamped to [0, 100] and stored as fractions.
        memory_pct : float
            Current memory utilization as a percentage (0–100).
        request_rate : float
            Current requests per second being served.

        Returns
        -------
        LoadProfile
            The updated smoothed load profile.
        """
        # Normalize to fractions
        cpu = max(0.0, min(1.0, cpu_pct / 100.0))
        mem = max(0.0, min(1.0, memory_pct / 100.0))
        rate = max(0.0, request_rate)

        sample = LoadSample(
            cpu_pct=cpu,
            memory_pct=mem,
            request_rate=rate,
        )

        async with self._lock:
            self._cpu_window.append(cpu)
            self._mem_window.append(mem)
            self._rate_window.append(rate)
            self._samples.append(sample)
            self._total_samples_ingested += 1

            # Track peak rate for normalization
            if rate > self._peak_request_rate:
                self._peak_request_rate = rate

            # Recompute smoothed profile (exponentially weighted moving average)
            self._profile = self._compute_profile()

        logger.debug(
            "Load sample recorded — cpu=%.1f%%, mem=%.1f%%, rate=%.1f rps → "
            "profile(cpu=%.3f, mem=%.3f, rate=%.1f)",
            cpu_pct,
            memory_pct,
            request_rate,
            self._profile.avg_cpu,
            self._profile.avg_memory,
            self._profile.avg_request_rate,
        )

        return self._profile

    def _compute_profile(self) -> LoadProfile:
        """
        Compute an exponentially weighted moving average over the
        current rolling windows.

        Uses a decay factor of 2/(N+1) where N is the current window
        length, giving recent samples exponentially more weight.

        Returns
        -------
        LoadProfile
        """
        if not self._cpu_window:
            return LoadProfile()

        n = len(self._cpu_window)
        decay = 2.0 / (n + 1)

        def ewma(window: Deque[float]) -> float:
            avg = window[0]
            for val in list(window)[1:]:
                avg = decay * val + (1 - decay) * avg
            return avg

        return LoadProfile(
            avg_cpu=ewma(self._cpu_window),
            avg_memory=ewma(self._mem_window),
            avg_request_rate=ewma(self._rate_window),
            sample_count=self._total_samples_ingested,
            last_updated=datetime.utcnow(),
        )

    # --------------------------------------------------------------------- #
    # DELAY COMPUTATION
    # --------------------------------------------------------------------- #

    async def get_simulated_delay(self) -> float:
        """
        Compute a simulated delay that matches the real system's current
        load profile.

        The delay is a weighted combination of CPU, memory, and
        request-rate contributions, plus Gaussian jitter for realism.

        Returns
        -------
        float
            Delay in seconds to inject into the mirror's response path.
        """
        async with self._lock:
            profile = self._profile
            peak_rate = self._peak_request_rate

        # CPU contribution: exponential above knee, linear below
        cpu_delay = self._cpu_delay_model(profile.avg_cpu)

        # Memory contribution: linear degradation
        mem_delay = self._memory_delay_model(profile.avg_memory)

        # Request rate contribution: queuing theory approximation
        rate_delay = self._rate_delay_model(
            profile.avg_request_rate, peak_rate
        )

        # Weighted combination
        raw_delay = (
            self._alpha * cpu_delay
            + self._beta * mem_delay
            + self._gamma * rate_delay
        )

        # Add baseline
        delay = self._baseline + raw_delay

        # Add Gaussian jitter
        jitter = self._cryptographic_jitter(delay * JITTER_FRACTION)
        delay += jitter

        # Clamp to bounds
        delay = max(self._baseline, min(self._max_delay, delay))

        async with self._lock:
            self._total_delays_served += 1

        logger.debug(
            "Simulated delay=%.4fs (cpu=%.4f, mem=%.4f, rate=%.4f, jitter=%.4f)",
            delay,
            cpu_delay,
            mem_delay,
            rate_delay,
            jitter,
        )

        return delay

    # --------------------------------------------------------------------- #
    # COMPONENT DELAY MODELS
    # --------------------------------------------------------------------- #

    @staticmethod
    def _cpu_delay_model(cpu_fraction: float) -> float:
        """
        Model CPU contention delay.

        Below the knee threshold (70%), delay grows linearly.  Above it,
        delay grows exponentially to simulate context-switch thrashing.

        Parameters
        ----------
        cpu_fraction : float
            CPU utilization in [0.0, 1.0].

        Returns
        -------
        float
            Delay contribution in seconds.
        """
        if cpu_fraction <= CPU_KNEE_THRESHOLD:
            # Linear region: 0 → 0.05s at the knee
            return cpu_fraction * (0.05 / CPU_KNEE_THRESHOLD)
        else:
            # Exponential region above the knee
            excess = cpu_fraction - CPU_KNEE_THRESHOLD
            linear_base = 0.05
            exponential_component = (math.exp(excess * 8.0) - 1.0) * 0.1
            return linear_base + exponential_component

    @staticmethod
    def _memory_delay_model(mem_fraction: float) -> float:
        """
        Model memory pressure delay.

        Linear degradation: as memory fills, page faults and GC pauses
        increase proportionally.

        Parameters
        ----------
        mem_fraction : float
            Memory utilization in [0.0, 1.0].

        Returns
        -------
        float
            Delay contribution in seconds.
        """
        # 0% → 0s, 100% → 0.15s
        return mem_fraction * 0.15

    @staticmethod
    def _rate_delay_model(
        current_rate: float,
        peak_rate: float,
    ) -> float:
        """
        Model queuing delay using a simplified M/M/1 approximation.

        As request rate approaches peak capacity, queuing delay grows
        hyperbolically (Little's Law).

        Parameters
        ----------
        current_rate : float
            Current requests per second.
        peak_rate : float
            Observed peak capacity (requests per second).

        Returns
        -------
        float
            Delay contribution in seconds.
        """
        if peak_rate <= 0:
            return 0.0

        utilization = min(0.98, current_rate / peak_rate)
        if utilization < 0.01:
            return 0.0

        # M/M/1 queue average wait: ρ / (μ * (1 - ρ))
        # Simplified with a constant service rate factor
        service_time = 0.01  # 10ms baseline service time
        if utilization >= 0.98:
            return 0.5  # Near-saturation cap
        return service_time * utilization / (1.0 - utilization)

    @staticmethod
    def _cryptographic_jitter(magnitude: float) -> float:
        """
        Generate Gaussian-like jitter using cryptographic randomness.

        Uses Box-Muller transform on two uniform random values from
        ``os.urandom`` to produce normally distributed jitter.

        Parameters
        ----------
        magnitude : float
            Standard deviation of the jitter (in seconds).

        Returns
        -------
        float
            Signed jitter value in seconds.
        """
        if magnitude <= 0:
            return 0.0

        # Two uniform random values in (0, 1)
        raw = struct.unpack("QQ", os.urandom(16))
        u1 = max(1e-15, raw[0] / (2**64))  # Avoid log(0)
        u2 = raw[1] / (2**64)

        # Box-Muller transform
        z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        return z * magnitude

    # --------------------------------------------------------------------- #
    # PROFILE ACCESS
    # --------------------------------------------------------------------- #

    async def get_current_profile(self) -> LoadProfile:
        """
        Return the current smoothed load profile.

        Returns
        -------
        LoadProfile
        """
        async with self._lock:
            return self._profile

    async def get_recent_samples(
        self,
        count: int = 10,
    ) -> List[LoadSample]:
        """
        Return the most recent N raw load samples.

        Parameters
        ----------
        count : int
            Number of samples to return (default 10).

        Returns
        -------
        list[LoadSample]
        """
        async with self._lock:
            samples = list(self._samples)
        return samples[-count:]

    # --------------------------------------------------------------------- #
    # DIAGNOSTICS
    # --------------------------------------------------------------------- #

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary of simulator state."""
        return {
            "total_samples_ingested": self._total_samples_ingested,
            "total_delays_served": self._total_delays_served,
            "current_window_size": len(self._cpu_window),
            "peak_request_rate": round(self._peak_request_rate, 2),
            "current_profile": {
                "avg_cpu": round(self._profile.avg_cpu, 4),
                "avg_memory": round(self._profile.avg_memory, 4),
                "avg_request_rate": round(self._profile.avg_request_rate, 2),
            },
            "weights": {
                "alpha_cpu": self._alpha,
                "beta_mem": self._beta,
                "gamma_rate": self._gamma,
            },
            "baseline_latency_ms": round(self._baseline * 1000, 2),
            "max_delay_ms": round(self._max_delay * 1000, 2),
        }

    def __repr__(self) -> str:
        return (
            f"<AdaptiveLoadSimulator samples={self._total_samples_ingested} "
            f"delays_served={self._total_delays_served} "
            f"cpu={self._profile.avg_cpu:.2f} "
            f"mem={self._profile.avg_memory:.2f} "
            f"rate={self._profile.avg_request_rate:.1f}>"
        )
