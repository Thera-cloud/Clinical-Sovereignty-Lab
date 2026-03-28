"""
Sovereign Sanctuary — Subconscious Bootstrap
==============================================
Integration point: starts the subconscious engine alongside
the existing Python bridge server. Hooks into the same Redis
instance, GPU, and edge infrastructure.

Usage in bridge server startup:

    from app.services.subconscious_bootstrap import boot_subconscious

    async def main():
        redis = await create_redis_pool()
        subconscious = await boot_subconscious(redis)

        # ... start bridge server, WebSocket handlers, etc.

        # On shutdown:
        await subconscious.shutdown()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .crystallization_engine import (
    SubconsciousMonitor,
    CrystallizationScheduler,
    CrystallizationOrchestrator,
)

logger = logging.getLogger("sovereign.subconscious")


# ---------------------------------------------------------------------------
# Infrastructure Adapters
# ---------------------------------------------------------------------------

class NvidiaGPUMonitor:
    """
    Polls nvidia-smi for GPU utilization metrics.
    Works with RTX 5090 (32GB VRAM, Blackwell architecture).
    Returns empty dict if nvidia-smi is not available (e.g., on VPS).
    """

    async def poll(self) -> Dict[str, Any]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            line = stdout.decode().strip()
            if not line:
                return {"available": False}

            parts = [p.strip() for p in line.split(",")]
            return {
                "available": True,
                "utilization_pct": float(parts[0]),
                "memory_used_mb": float(parts[1]),
                "memory_total_mb": float(parts[2]),
                "temperature_c": float(parts[3]) if len(parts) > 3 else 0.0,
            }
        except (FileNotFoundError, asyncio.TimeoutError, Exception):
            return {"available": False}


class CloudflareEdgeMetricsClient:
    """
    Fetches edge utilization from the Cloudflare metrics Worker endpoint.
    Falls back gracefully if the endpoint is unreachable.
    """

    def __init__(self, metrics_endpoint: str = "http://localhost:8787/api/edge/metrics"):
        self._endpoint = metrics_endpoint

    async def poll(self) -> Dict[str, Any]:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(self._endpoint, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status == 200:
                        return await resp.json()
            return {}
        except Exception:
            return {}


class RedisStateAdapter:
    """Redis operations for subconscious state persistence."""

    def __init__(self, redis_client: Any):
        self.redis = redis_client

    async def get_crystallization_state(self) -> Dict[str, Any]:
        try:
            data = await self.redis.get("subconscious:state")
            return json.loads(data) if data else {}
        except Exception:
            return {}

    async def save_crystallization_state(self, state: Dict[str, Any]):
        try:
            await self.redis.set("subconscious:state", json.dumps(state))
        except Exception:
            pass

    async def get_crystallization_stats(self) -> Dict[str, Any]:
        try:
            keys = await self.redis.keys("crystallization:stats:*")
            stats = {}
            for key in keys:
                val = await self.redis.get(key)
                name = key.decode().split(":")[-1] if isinstance(key, bytes) else key.split(":")[-1]
                stats[name] = json.loads(val) if val else {}
            return stats
        except Exception:
            return {}

    async def store_crystallization_result(self, job_id: str, result: dict):
        try:
            await self.redis.set(
                f"crystallization:result:{job_id}",
                json.dumps(result),
            )
            await self.redis.expire(f"crystallization:result:{job_id}", 7 * 86400)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class SubconsciousConfig:
    """Configuration for Little Nate's subconscious engine."""

    # Monitoring
    poll_interval_seconds: float = 5.0

    # Scheduling thresholds
    full_idle_threshold: float = 0.8
    full_idle_sustain_seconds: float = 30.0
    medium_idle_threshold: float = 0.6
    medium_idle_sustain_seconds: float = 60.0
    gpu_opportunistic_threshold: float = 0.4

    # Concurrency
    max_concurrent_jobs: int = 3
    max_concurrent_gpu_jobs: int = 1
    max_concurrent_api_jobs: int = 2

    # Orchestration
    orchestrator_check_interval: float = 2.0

    # Edge metrics
    edge_metrics_endpoint: str = "http://localhost:8787/api/edge/metrics"

    # Feature flags
    enable_gpu_crystallization: bool = True
    enable_api_crystallization: bool = True
    enable_emotional_arc_synthesis: bool = True

    # Logging
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "SubconsciousConfig":
        """Load config from environment variables."""
        return cls(
            poll_interval_seconds=float(os.environ.get("SUBCONSCIOUS_POLL_INTERVAL", "5")),
            edge_metrics_endpoint=os.environ.get(
                "SUBCONSCIOUS_EDGE_METRICS_URL",
                "http://localhost:8787/api/edge/metrics",
            ),
            enable_gpu_crystallization=os.environ.get(
                "SUBCONSCIOUS_GPU_ENABLED", "true"
            ).lower() == "true",
        )


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------

class SubconsciousRuntime:
    """
    Manages the lifecycle of Little Nate's subconscious processing.
    Provides clean start/stop and status reporting.
    """

    def __init__(
        self,
        monitor: SubconsciousMonitor,
        scheduler: CrystallizationScheduler,
        orchestrator: CrystallizationOrchestrator,
        config: SubconsciousConfig,
    ):
        self.monitor = monitor
        self.scheduler = scheduler
        self.orchestrator = orchestrator
        self.config = config
        self._tasks: List[asyncio.Task] = []
        self._running = False

    async def start(self):
        """Boot the subconscious — begins monitoring and crystallization."""
        if self._running:
            logger.warning("Subconscious already running")
            return

        self._running = True
        self._tasks = [
            asyncio.create_task(self.monitor.run_loop()),
            asyncio.create_task(self.orchestrator.run_loop()),
        ]
        logger.info(">>> [SUBCONSCIOUS] Engine started — monitoring + orchestrating")

    async def shutdown(self):
        """Gracefully stop all subconscious processing."""
        self._running = False
        self.monitor.stop()
        self.orchestrator.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info(">>> [SUBCONSCIOUS] Engine stopped")

    def status(self) -> Dict[str, Any]:
        """Full status report for dashboard/API."""
        return {
            "running": self._running,
            "monitor": {
                "idle_score": round(self.monitor.idle_score, 3),
                "snapshots_buffered": len(self.monitor.snapshots),
                "latest": self.monitor.latest.__dict__ if self.monitor.latest else None,
            },
            "scheduler": {
                "idle_level": self.scheduler.idle_level.value,
            },
            "orchestrator": self.orchestrator.status(),
        }


# ---------------------------------------------------------------------------
# Bootstrap Function
# ---------------------------------------------------------------------------

async def boot_subconscious(
    redis_client: Optional[Any] = None,
    config: Optional[SubconsciousConfig] = None,
) -> SubconsciousRuntime:
    """
    One-call bootstrap for the subconscious engine.

    Call from bridge server startup:

        subconscious = await boot_subconscious(redis)

    The engine immediately begins monitoring infrastructure and
    will start crystallizing during idle windows automatically.
    """
    if config is None:
        config = SubconsciousConfig.from_env()

    logging.getLogger("sovereign.subconscious").setLevel(
        getattr(logging, config.log_level.upper(), logging.INFO)
    )

    # Infrastructure adapters
    gpu_monitor = NvidiaGPUMonitor() if config.enable_gpu_crystallization else None
    edge_metrics = CloudflareEdgeMetricsClient(
        metrics_endpoint=config.edge_metrics_endpoint,
    )

    # Core components
    monitor = SubconsciousMonitor(
        poll_interval_seconds=config.poll_interval_seconds,
        redis_client=redis_client,
        gpu_monitor=gpu_monitor,
        edge_metrics_client=edge_metrics,
    )

    scheduler = CrystallizationScheduler(monitor=monitor)
    scheduler.FULL_CRYSTALLIZATION_THRESHOLD = config.full_idle_threshold
    scheduler.FULL_CRYSTALLIZATION_SUSTAIN_SECONDS = config.full_idle_sustain_seconds
    scheduler.MEDIUM_THRESHOLD = config.medium_idle_threshold
    scheduler.MEDIUM_SUSTAIN_SECONDS = config.medium_idle_sustain_seconds
    scheduler.GPU_OPPORTUNISTIC_THRESHOLD = config.gpu_opportunistic_threshold

    orchestrator = CrystallizationOrchestrator(
        scheduler=scheduler,
        monitor=monitor,
        check_interval=config.orchestrator_check_interval,
    )
    orchestrator.max_concurrent_jobs = config.max_concurrent_jobs
    orchestrator.max_concurrent_gpu_jobs = config.max_concurrent_gpu_jobs
    orchestrator.max_concurrent_api_jobs = config.max_concurrent_api_jobs

    runtime = SubconsciousRuntime(
        monitor=monitor,
        scheduler=scheduler,
        orchestrator=orchestrator,
        config=config,
    )

    await runtime.start()
    return runtime
