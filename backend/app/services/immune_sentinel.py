"""
Dual Brain Immune Sentinel — Behavioral anomaly detection for cross-brain communication.

Monitors both the Sovereign Brain (VPS) and Edge Brain (Cloudflare Worker) for
behavioral anomalies that indicate infection, compromise, or degradation.

Three-state immune response: NOTICE → ALERT → QUARANTINE
Each brain can be quarantined independently while the other continues operating.

Patent-Pending — Claims 30-56
(c) 2026 Clinical Sovereignty Lab. All rights reserved.
"""

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SOVEREIGN_METRICS_WINDOW = 300
EDGE_METRICS_WINDOW = 300
ANOMALY_THRESHOLD_NOTICE = 3
ANOMALY_THRESHOLD_ALERT = 6
ANOMALY_THRESHOLD_QUARANTINE = 10
QUARANTINE_DURATION = 600
REPAIR_VERIFICATION_CHECKS = 3
REPAIR_VERIFICATION_INTERVAL = 30
SENTINEL_CYCLE_SECONDS = 60


class ImmuneState(str, Enum):
    HEALTHY = "HEALTHY"
    NOTICE = "NOTICE"
    ALERT = "ALERT"
    QUARANTINE = "QUARANTINE"


class BrainTarget(str, Enum):
    SOVEREIGN = "sovereign"
    EDGE = "edge"


@dataclass
class AnomalyEvent:
    brain: str
    anomaly_type: str
    score: float
    details: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class BrainHealthMetrics:
    error_rate: float = 0.0
    avg_latency_ms: float = 0.0
    request_count: int = 0
    poison_detections: int = 0
    signature_failures: int = 0
    response_validation_failures: int = 0


class ImmuneSentinel:
    """Monitors cross-brain communication for behavioral anomalies."""

    def __init__(self, db_pool=None, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None

        self._sovereign_state = ImmuneState.HEALTHY
        self._edge_state = ImmuneState.HEALTHY
        self._sovereign_score = 0.0
        self._edge_score = 0.0

        self._sovereign_events: deque = deque(maxlen=100)
        self._edge_events: deque = deque(maxlen=100)

        self._sovereign_quarantine_start: Optional[float] = None
        self._edge_quarantine_start: Optional[float] = None

        self._sovereign_metrics_buffer: List[Dict] = []
        self._edge_metrics_buffer: List[Dict] = []

        self._repair_in_progress: Dict[str, bool] = {
            "sovereign": False,
            "edge": False,
        }
        self._repair_verification_count: Dict[str, int] = {
            "sovereign": 0,
            "edge": 0,
        }

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("ImmuneSentinel started (cycle: %ds)", SENTINEL_CYCLE_SECONDS)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def get_status(self) -> Dict[str, Any]:
        return {
            "sovereign": {
                "state": self._sovereign_state.value,
                "anomaly_score": round(self._sovereign_score, 2),
                "events_count": len(self._sovereign_events),
                "quarantine_start": self._sovereign_quarantine_start,
                "repair_in_progress": self._repair_in_progress["sovereign"],
            },
            "edge": {
                "state": self._edge_state.value,
                "anomaly_score": round(self._edge_score, 2),
                "events_count": len(self._edge_events),
                "quarantine_start": self._edge_quarantine_start,
                "repair_in_progress": self._repair_in_progress["edge"],
            },
        }

    def record_anomaly(self, brain: str, anomaly_type: str, score: float, details: str = ""):
        """Record a behavioral anomaly from either brain."""
        event = AnomalyEvent(brain=brain, anomaly_type=anomaly_type, score=score, details=details)

        if brain == BrainTarget.SOVEREIGN:
            self._sovereign_events.append(event)
            self._sovereign_score += score
        elif brain == BrainTarget.EDGE:
            self._edge_events.append(event)
            self._edge_score += score

        logger.warning(
            "ImmuneSentinel anomaly: brain=%s type=%s score=%.2f details=%s",
            brain, anomaly_type, score, details[:100],
        )

        self._evaluate_state(brain)

    def record_metric(self, brain: str, metric: Dict[str, Any]):
        """Record a health metric observation."""
        metric["timestamp"] = time.time()
        if brain == BrainTarget.SOVEREIGN:
            self._sovereign_metrics_buffer.append(metric)
            if len(self._sovereign_metrics_buffer) > 1000:
                self._sovereign_metrics_buffer = self._sovereign_metrics_buffer[-500:]
        elif brain == BrainTarget.EDGE:
            self._edge_metrics_buffer.append(metric)
            if len(self._edge_metrics_buffer) > 1000:
                self._edge_metrics_buffer = self._edge_metrics_buffer[-500:]

    def is_quarantined(self, brain: str) -> bool:
        if brain == BrainTarget.SOVEREIGN:
            return self._sovereign_state == ImmuneState.QUARANTINE
        elif brain == BrainTarget.EDGE:
            return self._edge_state == ImmuneState.QUARANTINE
        return False

    def _evaluate_state(self, brain: str):
        """Re-evaluate immune state based on anomaly score."""
        if brain == BrainTarget.SOVEREIGN:
            score = self._sovereign_score
            current = self._sovereign_state
        else:
            score = self._edge_score
            current = self._edge_state

        if score >= ANOMALY_THRESHOLD_QUARANTINE and current != ImmuneState.QUARANTINE:
            new_state = ImmuneState.QUARANTINE
            if brain == BrainTarget.SOVEREIGN:
                self._sovereign_quarantine_start = time.time()
            else:
                self._edge_quarantine_start = time.time()
            logger.error("ImmuneSentinel: %s brain QUARANTINED (score=%.2f)", brain, score)
            asyncio.create_task(self._write_immune_r2("quarantine", brain, {
                "score": score, "previous_state": current,
                "metrics": self._compute_metrics(brain).__dict__,
            }))
        elif score >= ANOMALY_THRESHOLD_ALERT:
            new_state = ImmuneState.ALERT
        elif score >= ANOMALY_THRESHOLD_NOTICE:
            new_state = ImmuneState.NOTICE
        else:
            new_state = ImmuneState.HEALTHY

        if brain == BrainTarget.SOVEREIGN:
            self._sovereign_state = new_state
        else:
            self._edge_state = new_state

    def _compute_metrics(self, brain: str) -> BrainHealthMetrics:
        """Compute health metrics from recent observations."""
        now = time.time()
        window = SOVEREIGN_METRICS_WINDOW if brain == BrainTarget.SOVEREIGN else EDGE_METRICS_WINDOW
        buffer = (
            self._sovereign_metrics_buffer
            if brain == BrainTarget.SOVEREIGN
            else self._edge_metrics_buffer
        )
        recent = [m for m in buffer if now - m.get("timestamp", 0) < window]

        if not recent:
            return BrainHealthMetrics()

        errors = sum(1 for m in recent if m.get("error", False))
        latencies = [m["latency_ms"] for m in recent if "latency_ms" in m]

        return BrainHealthMetrics(
            error_rate=errors / len(recent) if recent else 0.0,
            avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0.0,
            request_count=len(recent),
            poison_detections=sum(1 for m in recent if m.get("poison_detected", False)),
            signature_failures=sum(1 for m in recent if m.get("signature_failure", False)),
            response_validation_failures=sum(1 for m in recent if m.get("response_invalid", False)),
        )

    async def _run_loop(self):
        """Main sentinel cycle."""
        while self._running:
            try:
                await asyncio.sleep(SENTINEL_CYCLE_SECONDS)
                await self._cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("ImmuneSentinel cycle error: %s", e)

    async def _cycle(self):
        """Evaluate metrics, decay scores, check quarantine expiry, attempt repair."""
        now = time.time()

        for brain in (BrainTarget.SOVEREIGN, BrainTarget.EDGE):
            metrics = self._compute_metrics(brain)

            if metrics.error_rate > 0.5 and metrics.request_count >= 5:
                self.record_anomaly(brain, "high_error_rate", 2.0,
                                    f"error_rate={metrics.error_rate:.2f}")
            if metrics.avg_latency_ms > 5000 and metrics.request_count >= 3:
                self.record_anomaly(brain, "high_latency", 1.0,
                                    f"avg_latency={metrics.avg_latency_ms:.0f}ms")
            if metrics.poison_detections > 0:
                self.record_anomaly(brain, "poison_detected", 3.0,
                                    f"count={metrics.poison_detections}")
            if metrics.signature_failures > 2:
                self.record_anomaly(brain, "signature_failures", 2.0,
                                    f"count={metrics.signature_failures}")

        # Score decay — 0.5 per cycle (1 minute)
        self._sovereign_score = max(0, self._sovereign_score - 0.5)
        self._edge_score = max(0, self._edge_score - 0.5)

        # Re-evaluate states after decay
        self._evaluate_state(BrainTarget.SOVEREIGN)
        self._evaluate_state(BrainTarget.EDGE)

        # Auto-quarantine expiry → repair attempt
        for brain, start_time in [
            (BrainTarget.SOVEREIGN, self._sovereign_quarantine_start),
            (BrainTarget.EDGE, self._edge_quarantine_start),
        ]:
            if start_time and (now - start_time) > QUARANTINE_DURATION:
                if not self._repair_in_progress[brain]:
                    await self._attempt_repair(brain)

        # Log to DB
        await self._log_status()

    async def _attempt_repair(self, brain: str):
        """Attempt to bring a quarantined brain back online."""
        self._repair_in_progress[brain] = True
        self._repair_verification_count[brain] = 0
        logger.info("ImmuneSentinel: starting repair for %s brain", brain)

        for i in range(REPAIR_VERIFICATION_CHECKS):
            await asyncio.sleep(REPAIR_VERIFICATION_INTERVAL)
            metrics = self._compute_metrics(brain)

            if metrics.error_rate < 0.2 and metrics.poison_detections == 0:
                self._repair_verification_count[brain] += 1
                logger.info(
                    "ImmuneSentinel: %s repair check %d/%d PASSED",
                    brain, i + 1, REPAIR_VERIFICATION_CHECKS,
                )
            else:
                logger.warning(
                    "ImmuneSentinel: %s repair check %d/%d FAILED (error_rate=%.2f)",
                    brain, i + 1, REPAIR_VERIFICATION_CHECKS, metrics.error_rate,
                )
                break

        if self._repair_verification_count[brain] >= REPAIR_VERIFICATION_CHECKS:
            if brain == BrainTarget.SOVEREIGN:
                self._sovereign_state = ImmuneState.HEALTHY
                self._sovereign_score = 0.0
                self._sovereign_quarantine_start = None
            else:
                self._edge_state = ImmuneState.HEALTHY
                self._edge_score = 0.0
                self._edge_quarantine_start = None

            logger.info("ImmuneSentinel: %s brain REPAIRED and brought back online", brain)
            asyncio.create_task(self._write_immune_r2("repair", brain, {
                "result": "success", "checks_passed": REPAIR_VERIFICATION_CHECKS,
            }))
        else:
            logger.warning(
                "ImmuneSentinel: %s brain repair FAILED — extending quarantine",
                brain,
            )
            asyncio.create_task(self._write_immune_r2("repair", brain, {
                "result": "failed",
                "checks_passed": self._repair_verification_count.get(brain, 0),
                "checks_required": REPAIR_VERIFICATION_CHECKS,
            }))
            if brain == BrainTarget.SOVEREIGN:
                self._sovereign_quarantine_start = time.time()
            else:
                self._edge_quarantine_start = time.time()

        self._repair_in_progress[brain] = False

    async def _write_immune_r2(self, event_type: str, brain: str, data: Dict[str, Any]):
        """Write immune events to R2 immune/ prefix for cross-brain visibility."""
        try:
            from app.services.blob_storage import upload_bytes
            now = datetime.now(timezone.utc)
            ts = int(now.timestamp())

            if event_type == "status":
                path = f"immune/status/{brain}.json"
            elif event_type == "quarantine":
                path = f"immune/quarantine/{brain}/{ts}.json"
            elif event_type == "repair":
                path = f"immune/repair/{brain}/{ts}.json"
            else:
                path = f"immune/events/{brain}/{ts}_{event_type}.json"

            payload = {**data, "timestamp": now.isoformat(), "brain": brain, "event": event_type}
            await asyncio.to_thread(upload_bytes, rel_path=path, content=json.dumps(payload).encode())
        except Exception as e:
            logger.debug("ImmuneSentinel: R2 immune write failed (non-fatal): %s", e)

    async def _log_status(self):
        """Log sentinel status to skyeye_activity and R2 immune/ prefix."""
        if not self._db_pool:
            return
        try:
            status = self.get_status()
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO skyeye_activity (type, content, platform, created_at)
                       VALUES ('immune_sentinel_cycle', $1, 'system', $2)""",
                    json.dumps(status),
                    datetime.now(timezone.utc),
                )
            for brain in (BrainTarget.SOVEREIGN, BrainTarget.EDGE):
                brain_status = status.get(brain, {})
                if brain_status.get("state") != "HEALTHY":
                    await self._write_immune_r2("status", brain, brain_status)
        except Exception as e:
            logger.warning("ImmuneSentinel: failed to log status: %s", e)
