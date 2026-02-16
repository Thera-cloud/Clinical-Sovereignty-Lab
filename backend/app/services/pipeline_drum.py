"""
HIVE DEFENSE v4.3 — Pipeline Drum
Environmental sensing through 4 Tastes + Resonance Engine.

Taste 1 (Moisture): KL divergence + Wasserstein distance on request distributions
Taste 2 (Smoke): Breadth/depth metrics + error harvesting + timing probes
Taste 3 (Burn): Shannon entropy + character class analysis + encoding detection
Taste 4 (Clot): Internal pipeline metrics + trend analysis + variance correlation

Resonance Engine: Cross-sensor interaction multipliers, 5-level response.
30-day learning baseline with EMA adaptation.
"""

import asyncio
import collections
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

_logger = logging.getLogger("pipeline_drum")

SAMPLE_WINDOW_SEC = 3600  # 1-hour sampling window
LEARNING_PERIOD_DAYS = 30

# Response levels
LEVEL_NAMES = {
    1: "OBSERVE",
    2: "ALERT",
    3: "INVESTIGATE",
    4: "RESTRICT",
    5: "LOCKDOWN",
}


class MoistureSensor:
    """Taste 1: Detects distribution shifts in request patterns."""

    def __init__(self):
        self._request_distribution: Deque[Dict] = collections.deque(maxlen=10000)
        self._baseline_distribution: Dict[str, float] = {}

    def record_request(self, endpoint: str, method: str, status_code: int) -> None:
        """Record a request for distribution analysis."""
        key = f"{method}:{endpoint}:{status_code // 100}xx"
        self._request_distribution.append({
            "key": key,
            "ts": time.time(),
        })

    def compute_kl_divergence(self) -> float:
        """Compute KL divergence between current and baseline distributions."""
        if not self._baseline_distribution or len(self._request_distribution) < 100:
            return 0.0

        # Build current distribution
        cutoff = time.time() - SAMPLE_WINDOW_SEC
        recent = [r for r in self._request_distribution if r["ts"] > cutoff]
        if not recent:
            return 0.0

        current_counts: Dict[str, int] = {}
        for r in recent:
            current_counts[r["key"]] = current_counts.get(r["key"], 0) + 1

        total = sum(current_counts.values())
        current_dist = {k: v / total for k, v in current_counts.items()}

        # KL divergence: sum(p(x) * log(p(x)/q(x)))
        kl = 0.0
        all_keys = set(current_dist) | set(self._baseline_distribution)
        for key in all_keys:
            p = current_dist.get(key, 1e-10)
            q = self._baseline_distribution.get(key, 1e-10)
            if p > 0:
                kl += p * math.log(p / q)

        return abs(kl)

    def compute_wasserstein(self) -> float:
        """Simplified Wasserstein distance on request rates."""
        if not self._baseline_distribution:
            return 0.0

        cutoff = time.time() - SAMPLE_WINDOW_SEC
        recent = [r for r in self._request_distribution if r["ts"] > cutoff]
        current_rate = len(recent)
        baseline_rate = sum(self._baseline_distribution.values()) * len(recent) if self._baseline_distribution else current_rate

        if baseline_rate == 0:
            return 0.0

        return abs(current_rate - baseline_rate) / max(baseline_rate, 1)

    def update_baseline(self) -> None:
        """Update baseline distribution from recent data."""
        cutoff = time.time() - SAMPLE_WINDOW_SEC
        recent = [r for r in self._request_distribution if r["ts"] > cutoff]
        if not recent:
            return

        counts: Dict[str, int] = {}
        for r in recent:
            counts[r["key"]] = counts.get(r["key"], 0) + 1

        total = sum(counts.values())
        alpha = 0.02  # EMA smoothing
        for key in set(counts) | set(self._baseline_distribution):
            new_val = counts.get(key, 0) / total
            old_val = self._baseline_distribution.get(key, new_val)
            self._baseline_distribution[key] = old_val * (1 - alpha) + new_val * alpha


class SmokeSensor:
    """Taste 2: Detects reconnaissance and probing patterns."""

    def __init__(self):
        self._endpoint_hits: Deque[Dict] = collections.deque(maxlen=10000)
        self._errors: Deque[Dict] = collections.deque(maxlen=5000)
        self._response_times: Deque[float] = collections.deque(maxlen=5000)

    def record_request(
        self, endpoint: str, status_code: int, response_time_ms: float,
    ) -> None:
        """Record a request for smoke analysis."""
        now = time.time()
        self._endpoint_hits.append({"endpoint": endpoint, "ts": now})
        self._response_times.append(response_time_ms)

        if status_code >= 400:
            self._errors.append({"endpoint": endpoint, "code": status_code, "ts": now})

    def compute_breadth(self) -> float:
        """How many unique endpoints hit in the last hour."""
        cutoff = time.time() - SAMPLE_WINDOW_SEC
        recent = [r for r in self._endpoint_hits if r["ts"] > cutoff]
        return len(set(r["endpoint"] for r in recent))

    def compute_error_rate(self) -> float:
        """Error rate in the last hour."""
        cutoff = time.time() - SAMPLE_WINDOW_SEC
        total = sum(1 for r in self._endpoint_hits if r["ts"] > cutoff)
        errors = sum(1 for r in self._errors if r["ts"] > cutoff)
        return errors / max(total, 1)

    def compute_avg_response_time(self) -> float:
        """Average response time (ms) of recent requests."""
        if not self._response_times:
            return 0.0
        return sum(self._response_times) / len(self._response_times)


class BurnSensor:
    """Taste 3: Detects payload manipulation via entropy analysis."""

    def __init__(self):
        self._entropy_samples: Deque[float] = collections.deque(maxlen=5000)

    def analyze_payload(self, payload: bytes) -> Dict[str, Any]:
        """Analyze a payload for entropy and encoding anomalies."""
        if not payload:
            return {"entropy": 0, "unusual_encoding": False}

        entropy = self._shannon_entropy(payload)
        self._entropy_samples.append(entropy)

        # Character class analysis
        printable_ratio = sum(1 for b in payload if 32 <= b <= 126) / len(payload)
        null_ratio = sum(1 for b in payload if b == 0) / len(payload)

        unusual_encoding = (
            entropy > 7.5 or  # Near-random (encrypted/compressed)
            null_ratio > 0.1 or  # Binary data in text endpoint
            printable_ratio < 0.5  # Mostly non-printable
        )

        return {
            "entropy": entropy,
            "printable_ratio": printable_ratio,
            "null_ratio": null_ratio,
            "unusual_encoding": unusual_encoding,
        }

    def get_avg_entropy(self) -> float:
        """Average entropy of recent payloads."""
        if not self._entropy_samples:
            return 0.0
        return sum(self._entropy_samples) / len(self._entropy_samples)

    @staticmethod
    def _shannon_entropy(data: bytes) -> float:
        """Calculate Shannon entropy of byte data."""
        if not data:
            return 0.0
        freq = [0] * 256
        for b in data:
            freq[b] += 1
        length = len(data)
        entropy = 0.0
        for f in freq:
            if f > 0:
                p = f / length
                entropy -= p * math.log2(p)
        return entropy


class ClotSensor:
    """Taste 4: Detects internal pipeline anomalies (DB, cache, queue, Redis)."""

    def __init__(self):
        self._db_queries: Deque[float] = collections.deque(maxlen=5000)
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._queue_depths: Deque[int] = collections.deque(maxlen=1000)
        # Redis monitoring (v4.3)
        self._redis_ops: Deque[Dict] = collections.deque(maxlen=10000)
        self._redis_errors: int = 0
        self._redis_latencies: Deque[float] = collections.deque(maxlen=5000)

    def record_db_query(self, duration_ms: float) -> None:
        """Record a database query."""
        self._db_queries.append(time.time())

    def record_cache_access(self, hit: bool) -> None:
        """Record a cache hit or miss."""
        if hit:
            self._cache_hits += 1
        else:
            self._cache_misses += 1

    def record_queue_depth(self, depth: int) -> None:
        """Record current queue depth."""
        self._queue_depths.append(depth)

    # ─── Redis Monitoring (v4.3) ──────────────────────────────────────────────

    def record_redis_op(
        self, operation: str, key_pattern: str, latency_ms: float, success: bool = True,
    ) -> None:
        """Record a Redis operation for flow analysis."""
        self._redis_ops.append({
            "op": operation,
            "key": key_pattern,
            "ts": time.time(),
            "latency_ms": latency_ms,
        })
        self._redis_latencies.append(latency_ms)
        if not success:
            self._redis_errors += 1

    def compute_redis_ops_rate(self) -> float:
        """Redis operations per minute in the last 5 minutes."""
        cutoff = time.time() - 300
        recent = sum(1 for op in self._redis_ops if op["ts"] > cutoff)
        return recent / 5.0

    def compute_redis_avg_latency(self) -> float:
        """Average Redis latency (ms) of recent operations."""
        if not self._redis_latencies:
            return 0.0
        return sum(self._redis_latencies) / len(self._redis_latencies)

    def compute_redis_error_rate(self) -> float:
        """Redis error rate."""
        total = len(self._redis_ops)
        if total == 0:
            return 0.0
        return self._redis_errors / total

    def compute_redis_key_diversity(self) -> float:
        """Unique Redis key patterns in the last hour (breadth indicator)."""
        cutoff = time.time() - SAMPLE_WINDOW_SEC
        recent = [op for op in self._redis_ops if op["ts"] > cutoff]
        return len(set(op["key"] for op in recent)) if recent else 0

    # ─── Standard Metrics ─────────────────────────────────────────────────────

    def compute_db_query_rate(self) -> float:
        """Queries per minute in the last 5 minutes."""
        cutoff = time.time() - 300
        recent = sum(1 for ts in self._db_queries if ts > cutoff)
        return recent / 5.0

    def compute_cache_hit_ratio(self) -> float:
        """Cache hit ratio."""
        total = self._cache_hits + self._cache_misses
        if total == 0:
            return 1.0
        return self._cache_hits / total

    def compute_avg_queue_depth(self) -> float:
        """Average queue depth."""
        if not self._queue_depths:
            return 0.0
        return sum(self._queue_depths) / len(self._queue_depths)


class ResonanceEngine:
    """Cross-sensor interaction analysis with 5-level response."""

    def __init__(self):
        # Interaction multipliers: when multiple sensors fire, the combined
        # threat is multiplicative, not additive
        self._multipliers = {
            ("moisture", "smoke"): 1.5,     # Distribution shift + probing = recon
            ("moisture", "burn"): 2.0,      # Distribution shift + entropy = exfil
            ("smoke", "burn"): 1.8,         # Probing + encoding = injection
            ("smoke", "clot"): 1.6,         # Probing + pipeline stress = DDoS
            ("burn", "clot"): 2.0,          # Encoding + pipeline = data manipulation
            ("moisture", "clot"): 1.4,      # Distribution shift + pipeline = slow attack
        }

    def compute_resonance(self, sensor_scores: Dict[str, float]) -> Dict[str, Any]:
        """
        Compute resonance across sensors.
        Returns alert level (1-5) and recommended actions.
        """
        # Base score is the max individual sensor score
        active_sensors = {k: v for k, v in sensor_scores.items() if v > 0.5}
        if not active_sensors:
            return {"level": 0, "resonance_multiplier": 1.0, "actions": []}

        base_score = max(active_sensors.values())

        # Apply interaction multipliers
        resonance_multiplier = 1.0
        sensor_names = list(active_sensors.keys())
        for i in range(len(sensor_names)):
            for j in range(i + 1, len(sensor_names)):
                pair = tuple(sorted([sensor_names[i], sensor_names[j]]))
                if pair in self._multipliers:
                    resonance_multiplier = max(resonance_multiplier, self._multipliers[pair])

        final_score = base_score * resonance_multiplier

        # Map to response level
        if final_score >= 8:
            level = 5  # LOCKDOWN
        elif final_score >= 5:
            level = 4  # RESTRICT
        elif final_score >= 3:
            level = 3  # INVESTIGATE
        elif final_score >= 1.5:
            level = 2  # ALERT
        elif final_score >= 0.5:
            level = 1  # OBSERVE
        else:
            level = 0

        actions = self._get_actions(level)
        return {
            "level": level,
            "level_name": LEVEL_NAMES.get(level, "NORMAL"),
            "final_score": final_score,
            "resonance_multiplier": resonance_multiplier,
            "active_sensors": list(active_sensors.keys()),
            "actions": actions,
        }

    @staticmethod
    def _get_actions(level: int) -> List[str]:
        """Get recommended actions for a response level."""
        actions_map = {
            1: ["increase_logging", "extend_retention"],
            2: ["alert_admin", "increase_sampling", "enable_deep_inspection"],
            3: ["activate_mirrors", "isolate_suspicious_sessions", "begin_forensics"],
            4: ["restrict_new_connections", "throttle_api", "activate_guardian_sentinel"],
            5: ["lockdown_mode", "block_external_access", "emergency_snapshot", "alert_nathan"],
        }
        return actions_map.get(level, [])


class PipelineDrum:
    """Environmental sensing engine: 4 Tastes + Resonance."""

    def __init__(self, db_pool=None):
        self._db = db_pool
        self.moisture = MoistureSensor()
        self.smoke = SmokeSensor()
        self.burn = BurnSensor()
        self.clot = ClotSensor()
        self.resonance = ResonanceEngine()
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def is_ready(self) -> bool:
        """Check if PipelineDrum is operational (background loop running)."""
        return self._running and self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the Pipeline Drum analysis loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._analysis_loop())
        _logger.info("PipelineDrum started")

    async def stop(self) -> None:
        """Stop the analysis loop."""
        self._running = False
        if self._task:
            self._task.cancel()

    async def _analysis_loop(self) -> None:
        """Periodic analysis of all 4 sensors."""
        while self._running:
            try:
                await self._run_analysis()
            except Exception as exc:
                _logger.error("PipelineDrum analysis error: %s", exc)
            await asyncio.sleep(60)  # Every minute

    async def _run_analysis(self) -> None:
        """Run all 4 sensors and compute resonance."""
        sensor_scores = {}

        # Moisture: distribution shift
        kl = self.moisture.compute_kl_divergence()
        wd = self.moisture.compute_wasserstein()
        moisture_score = (kl + wd) / 2
        sensor_scores["moisture"] = moisture_score
        await self._update_baseline("moisture", "kl_divergence", kl)

        # Smoke: reconnaissance detection
        breadth = self.smoke.compute_breadth()
        error_rate = self.smoke.compute_error_rate()
        avg_rt = self.smoke.compute_avg_response_time()
        smoke_score = (breadth / 50) + (error_rate * 10) + (max(0, avg_rt - 500) / 500)
        sensor_scores["smoke"] = smoke_score
        await self._update_baseline("smoke", "unique_endpoints_per_hour", breadth)
        await self._update_baseline("smoke", "error_rate_per_hour", error_rate)

        # Burn: entropy anomaly
        avg_entropy = self.burn.get_avg_entropy()
        burn_score = max(0, abs(avg_entropy - 4.0) - 1.0)  # Normal text entropy ~3.5-4.5
        sensor_scores["burn"] = burn_score
        await self._update_baseline("burn", "avg_entropy", avg_entropy)

        # Clot: pipeline health (includes Redis monitoring since v4.3)
        db_rate = self.clot.compute_db_query_rate()
        cache_ratio = self.clot.compute_cache_hit_ratio()
        queue_depth = self.clot.compute_avg_queue_depth()
        redis_ops_rate = self.clot.compute_redis_ops_rate()
        redis_avg_latency = self.clot.compute_redis_avg_latency()
        redis_error_rate = self.clot.compute_redis_error_rate()
        redis_key_diversity = self.clot.compute_redis_key_diversity()

        clot_score = (
            (max(0, db_rate - 100) / 50)
            + (max(0, 0.5 - cache_ratio) * 5)
            + (queue_depth / 20)
            + (max(0, redis_avg_latency - 50) / 100)  # Redis latency > 50ms is abnormal
            + (redis_error_rate * 10)                   # Redis errors are serious
            + (max(0, redis_key_diversity - 100) / 50)  # Too many unique keys = scanning
        )
        sensor_scores["clot"] = clot_score
        await self._update_baseline("clot", "db_query_rate_per_min", db_rate)
        await self._update_baseline("clot", "redis_ops_rate_per_min", redis_ops_rate)
        await self._update_baseline("clot", "redis_avg_latency_ms", redis_avg_latency)

        # Resonance
        result = self.resonance.compute_resonance(sensor_scores)

        if result["level"] >= 2:
            _logger.warning(
                "PIPELINE DRUM [%s]: score=%.2f, sensors=%s, resonance=%.1fx",
                result["level_name"], result["final_score"],
                result["active_sensors"], result["resonance_multiplier"],
            )
            await self._record_alert(result, sensor_scores)

        # Update moisture baseline periodically
        self.moisture.update_baseline()

    async def _update_baseline(self, sensor: str, metric: str, value: float) -> None:
        """Update EMA baseline for a metric."""
        if not self._db:
            return
        try:
            await self._db.execute(
                """UPDATE drum_baselines
                   SET baseline_mean = baseline_mean * (1 - ema_alpha) + $3 * ema_alpha,
                       sample_count = sample_count + 1,
                       updated_at = NOW()
                   WHERE sensor_name = $1 AND metric_name = $2""",
                sensor, metric, value,
            )
        except Exception:
            pass

    async def _record_alert(self, result: Dict, sensor_scores: Dict) -> None:
        """Record a Pipeline Drum alert."""
        if not self._db:
            return
        try:
            for sensor, score in sensor_scores.items():
                if score > 0.5:
                    await self._db.execute(
                        """INSERT INTO drum_alerts
                           (sensor_name, alert_level, observed_value, resonance_multiplier, description, created_at)
                           VALUES ($1, $2, $3, $4, $5, NOW())""",
                        sensor, result["level"], score,
                        result["resonance_multiplier"],
                        f"{result['level_name']}: {', '.join(result['actions'])}",
                    )
        except Exception as exc:
            _logger.error("Drum alert record error: %s", exc)

    def tap_request(
        self, endpoint: str, method: str, status_code: int,
        response_time_ms: float, payload: bytes = b"",
    ) -> None:
        """Tap a request/response for all sensors."""
        self.moisture.record_request(endpoint, method, status_code)
        self.smoke.record_request(endpoint, status_code, response_time_ms)
        if payload:
            self.burn.analyze_payload(payload)

    def tap_redis(
        self, operation: str, key_pattern: str,
        latency_ms: float, success: bool = True,
    ) -> None:
        """Tap a Redis operation for Clot Sensor monitoring."""
        self.clot.record_redis_op(operation, key_pattern, latency_ms, success)
