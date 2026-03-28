"""
Sovereign Sanctuary — Little Nate's Subconscious Crystallization Engine
=======================================================================
Resource-aware autonomous processing that harvests idle compute cycles
to consolidate clinical learning, extract cross-session patterns, and
refine the Nevedal Emotional Coherence model.

Architecture:
  - SubconsciousMonitor: polls infrastructure utilization metrics
  - CrystallizationScheduler: decides WHEN to crystallize based on idle windows
  - CrystallizationOrchestrator: decides WHAT to crystallize (priority queue)
  - BaseCrystallizationWorker: base class for individual crystallization jobs
  - CrystallizationWorkerFactory: registry for worker types

Patent-relevant: Self-aware therapeutic AI system that monitors its own
infrastructure utilization to opportunistically consolidate clinical
learning during idle compute cycles.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Type

logger = logging.getLogger("sovereign.subconscious")


# ---------------------------------------------------------------------------
# Domain Types
# ---------------------------------------------------------------------------

class CrystallizationPriority(Enum):
    """Priority tiers — higher value = run first."""
    CRITICAL = 100    # Nevedal recalibration after anomaly detection
    HIGH = 75         # Cross-client pattern extraction
    MEDIUM = 50       # Warm-to-cold memory tier migration
    LOW = 25          # Night School curriculum refinement
    AMBIENT = 10      # Speculative pre-computation


class CrystallizationType(Enum):
    """Categories of subconscious work Little Nate can perform."""
    NEVEDAL_RECALIBRATION = "nevedal_recalibration"
    CROSS_SESSION_PATTERNS = "cross_session_patterns"
    MEMORY_TIER_MIGRATION = "memory_tier_migration"
    NIGHT_SCHOOL_REFINEMENT = "night_school_refinement"
    RESISTANCE_MAPPING = "resistance_mapping"
    EMOTIONAL_ARC_SYNTHESIS = "emotional_arc_synthesis"
    CRYSTAL_CONSOLIDATION = "crystal_consolidation"
    MODALITY_WEIGHT_TUNING = "modality_weight_tuning"
    LIMINAL_RESOLVE_PROCESSING = "liminal_resolve_processing"  # QUANTUM-CRYSTAL-ARCH


class IdleLevel(Enum):
    """How idle the infrastructure is — determines what can run."""
    ACTIVE = "active"               # Serving live sessions — no crystallization
    LIGHT_IDLE = "light_idle"       # Some headroom — ambient jobs only
    MEDIUM_IDLE = "medium_idle"     # Moderate headroom — medium+ priority
    FULL_IDLE = "full_idle"         # Near-zero load — full queue open
    GPU_OPPORTUNISTIC = "gpu_idle"  # GPU specifically free — GPU jobs only


# ---------------------------------------------------------------------------
# Infrastructure Snapshot
# ---------------------------------------------------------------------------

@dataclass
class InfraSnapshot:
    """Point-in-time reading of infrastructure utilization."""
    timestamp: float = field(default_factory=time.time)

    # WebSocket / session metrics
    active_ws_connections: int = 0
    active_inference_calls: int = 0

    # Redis metrics
    redis_connected: bool = False
    redis_memory_used_mb: float = 0.0
    redis_ops_per_sec: float = 0.0

    # GPU metrics (RTX 5090 / local inference)
    gpu_available: bool = False
    gpu_utilization_pct: float = 0.0    # 0-100
    gpu_memory_used_mb: float = 0.0
    gpu_memory_total_mb: float = 32768.0  # 32GB VRAM for RTX 5090
    gpu_temperature_c: float = 0.0

    # Edge metrics (Cloudflare)
    edge_requests_per_min: float = 0.0
    durable_objects_active: int = 0

    @property
    def gpu_memory_pct(self) -> float:
        if self.gpu_memory_total_mb == 0:
            return 0.0
        return (self.gpu_memory_used_mb / self.gpu_memory_total_mb) * 100

    @property
    def idle_score(self) -> float:
        """
        Weighted idle score from 0.0 (fully loaded) to 1.0 (completely idle).
        Weights reflect what matters most for crystallization headroom.
        """
        weights = {
            "inference": 0.35,   # Active inference is the hardest veto
            "ws": 0.20,          # Active WebSocket sessions
            "gpu": 0.25,         # GPU availability
            "edge": 0.10,        # Edge request load
            "redis": 0.10,       # Redis headroom
        }

        inference_idle = 1.0 if self.active_inference_calls == 0 else 0.0
        ws_idle = max(0.0, 1.0 - (self.active_ws_connections / 50.0))
        gpu_idle = (1.0 - self.gpu_utilization_pct / 100.0) if self.gpu_available else 0.5
        edge_idle = max(0.0, 1.0 - (self.edge_requests_per_min / 500.0))
        redis_idle = max(0.0, 1.0 - (self.redis_ops_per_sec / 1000.0)) if self.redis_connected else 0.5

        return (
            weights["inference"] * inference_idle +
            weights["ws"] * ws_idle +
            weights["gpu"] * gpu_idle +
            weights["edge"] * edge_idle +
            weights["redis"] * redis_idle
        )


# ---------------------------------------------------------------------------
# SubconsciousMonitor
# ---------------------------------------------------------------------------

class SubconsciousMonitor:
    """
    Polls infrastructure metrics at configurable intervals.
    Maintains a rolling window of snapshots for trend analysis.
    """

    def __init__(
        self,
        poll_interval_seconds: float = 5.0,
        window_size: int = 60,
        redis_client: Optional[Any] = None,
        gpu_monitor: Optional[Any] = None,
        edge_metrics_client: Optional[Any] = None,
    ):
        self._interval = poll_interval_seconds
        self._window_size = window_size
        self._redis = redis_client
        self._gpu_monitor = gpu_monitor
        self._edge_client = edge_metrics_client
        self._snapshots: List[InfraSnapshot] = []
        self._running = False
        self._active_inference_count = 0
        self._active_ws_count = 0

    @property
    def latest(self) -> Optional[InfraSnapshot]:
        return self._snapshots[-1] if self._snapshots else None

    @property
    def idle_score(self) -> float:
        return self.latest.idle_score if self.latest else 0.0

    @property
    def snapshots(self) -> List[InfraSnapshot]:
        return list(self._snapshots)

    def notify_inference_start(self):
        """Called by bridge when an inference call begins."""
        self._active_inference_count += 1

    def notify_inference_end(self):
        """Called by bridge when an inference call completes."""
        self._active_inference_count = max(0, self._active_inference_count - 1)

    def notify_ws_change(self, count: int):
        """Called by bridge when WebSocket connection count changes."""
        self._active_ws_count = count

    async def poll_once(self) -> InfraSnapshot:
        """Take a single infrastructure snapshot."""
        snap = InfraSnapshot(
            active_inference_calls=self._active_inference_count,
            active_ws_connections=self._active_ws_count,
        )

        # Redis metrics
        if self._redis:
            try:
                info = await self._redis.info("memory")
                snap.redis_connected = True
                snap.redis_memory_used_mb = info.get("used_memory", 0) / (1024 * 1024)
                stats = await self._redis.info("stats")
                snap.redis_ops_per_sec = stats.get("instantaneous_ops_per_sec", 0)
            except Exception:
                snap.redis_connected = False

        # GPU metrics
        if self._gpu_monitor:
            try:
                gpu_data = await self._gpu_monitor.poll()
                snap.gpu_available = gpu_data.get("available", False)
                snap.gpu_utilization_pct = gpu_data.get("utilization_pct", 0.0)
                snap.gpu_memory_used_mb = gpu_data.get("memory_used_mb", 0.0)
                snap.gpu_memory_total_mb = gpu_data.get("memory_total_mb", 32768.0)
                snap.gpu_temperature_c = gpu_data.get("temperature_c", 0.0)
            except Exception:
                snap.gpu_available = False

        # Edge metrics
        if self._edge_client:
            try:
                edge_data = await self._edge_client.poll()
                snap.edge_requests_per_min = edge_data.get("requests_per_min", 0.0)
                snap.durable_objects_active = edge_data.get("durable_objects_active", 0)
            except Exception:
                pass

        self._snapshots.append(snap)
        if len(self._snapshots) > self._window_size:
            self._snapshots = self._snapshots[-self._window_size:]

        return snap

    async def run_loop(self):
        """Background polling loop — start via asyncio.create_task()."""
        self._running = True
        logger.info("SubconsciousMonitor started — polling every %ss", self._interval)
        while self._running:
            try:
                await self.poll_once()
            except Exception as e:
                logger.error("Monitor poll error: %s", e)
            await asyncio.sleep(self._interval)

    def stop(self):
        self._running = False

    def sustained_idle(self, threshold: float, seconds: float) -> bool:
        """Check if idle_score has been above threshold for N seconds."""
        if not self._snapshots:
            return False
        cutoff = time.time() - seconds
        recent = [s for s in self._snapshots if s.timestamp >= cutoff]
        if len(recent) < 2:
            return False
        return all(s.idle_score >= threshold for s in recent)


# ---------------------------------------------------------------------------
# CrystallizationScheduler
# ---------------------------------------------------------------------------

class CrystallizationScheduler:
    """
    Watches the monitor's idle score and determines the current idle level.
    The orchestrator queries this to decide what jobs to dispatch.
    """

    FULL_CRYSTALLIZATION_THRESHOLD = 0.8
    FULL_CRYSTALLIZATION_SUSTAIN_SECONDS = 30.0
    MEDIUM_THRESHOLD = 0.6
    MEDIUM_SUSTAIN_SECONDS = 60.0
    LIGHT_THRESHOLD = 0.4
    LIGHT_SUSTAIN_SECONDS = 90.0
    GPU_OPPORTUNISTIC_THRESHOLD = 0.4

    def __init__(self, monitor: SubconsciousMonitor):
        self._monitor = monitor

    @property
    def idle_level(self) -> IdleLevel:
        """Current idle classification based on sustained metrics."""
        snap = self._monitor.latest
        if snap is None:
            return IdleLevel.ACTIVE

        # Hard veto: any active inference = ACTIVE
        if snap.active_inference_calls > 0:
            return IdleLevel.ACTIVE

        if self._monitor.sustained_idle(
            self.FULL_CRYSTALLIZATION_THRESHOLD,
            self.FULL_CRYSTALLIZATION_SUSTAIN_SECONDS,
        ):
            return IdleLevel.FULL_IDLE

        if self._monitor.sustained_idle(
            self.MEDIUM_THRESHOLD,
            self.MEDIUM_SUSTAIN_SECONDS,
        ):
            return IdleLevel.MEDIUM_IDLE

        if self._monitor.sustained_idle(
            self.LIGHT_THRESHOLD,
            self.LIGHT_SUSTAIN_SECONDS,
        ):
            return IdleLevel.LIGHT_IDLE

        if (snap.gpu_available and
                snap.gpu_utilization_pct < self.GPU_OPPORTUNISTIC_THRESHOLD):
            return IdleLevel.GPU_OPPORTUNISTIC

        return IdleLevel.ACTIVE

    def can_run(self, priority: CrystallizationPriority, requires_gpu: bool = False) -> bool:
        """Check if a job of this priority is allowed to run now."""
        level = self.idle_level

        if level == IdleLevel.ACTIVE:
            return False

        if level == IdleLevel.FULL_IDLE:
            return True

        if level == IdleLevel.MEDIUM_IDLE:
            return priority.value >= CrystallizationPriority.MEDIUM.value

        if level == IdleLevel.LIGHT_IDLE:
            return priority.value >= CrystallizationPriority.HIGH.value

        if level == IdleLevel.GPU_OPPORTUNISTIC:
            return requires_gpu and priority.value >= CrystallizationPriority.MEDIUM.value

        return False


# ---------------------------------------------------------------------------
# Crystallization Job
# ---------------------------------------------------------------------------

@dataclass
class CrystallizationJob:
    """A single unit of subconscious work."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    job_type: CrystallizationType = CrystallizationType.CRYSTAL_CONSOLIDATION
    priority: CrystallizationPriority = CrystallizationPriority.MEDIUM
    requires_gpu: bool = False
    requires_api_call: bool = False
    estimated_duration_seconds: int = 60
    params: Dict[str, Any] = field(default_factory=dict)

    # Runtime state
    created_at: Optional[datetime] = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result_summary: Optional[str] = None
    insights_generated: int = 0
    error: Optional[str] = None
    preempted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        status = "pending"
        if self.preempted:
            status = "preempted"
        elif self.error:
            status = "error"
        elif self.completed_at:
            status = "completed"
        elif self.started_at:
            status = "running"

        return {
            "id": self.id,
            "type": self.job_type.value,
            "priority": self.priority.name,
            "status": status,
            "requires_gpu": self.requires_gpu,
            "requires_api_call": self.requires_api_call,
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result_summary": self.result_summary,
            "insights_generated": self.insights_generated,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Base Worker + Factory
# ---------------------------------------------------------------------------

class PreemptionRequested(Exception):
    """Raised when a worker should stop because infrastructure needs are higher."""
    pass


class BaseCrystallizationWorker(ABC):
    """
    Base class for crystallization workers. Each worker type processes
    one category of subconscious work.
    """

    def __init__(self, job: CrystallizationJob, monitor: SubconsciousMonitor):
        self.job = job
        self.monitor = monitor
        self._cancelled = False

    async def check_preemption(self):
        """
        Call between expensive steps. If infrastructure is no longer idle,
        raises PreemptionRequested so the worker exits cleanly.
        Conscious processing always wins.
        """
        if self._cancelled:
            raise PreemptionRequested("Worker cancelled")
        snap = self.monitor.latest
        if snap and snap.active_inference_calls > 0:
            self.job.preempted = True
            raise PreemptionRequested("Active inference detected — yielding to conscious processing")

    def cancel(self):
        self._cancelled = True

    @abstractmethod
    async def execute(self) -> dict:
        """Run the crystallization job. Return a result dict."""
        ...


class CrystallizationWorkerFactory:
    """Registry mapping job types to worker classes."""

    _registry: Dict[CrystallizationType, Type[BaseCrystallizationWorker]] = {}

    @classmethod
    def register(cls, job_type: CrystallizationType):
        """Decorator to register a worker class for a job type."""
        def decorator(worker_cls: Type[BaseCrystallizationWorker]):
            cls._registry[job_type] = worker_cls
            return worker_cls
        return decorator

    @classmethod
    def create(cls, job: CrystallizationJob, monitor: SubconsciousMonitor) -> BaseCrystallizationWorker:
        worker_cls = cls._registry.get(job.job_type)
        if not worker_cls:
            raise ValueError(f"No worker registered for {job.job_type}")
        return worker_cls(job, monitor)

    @classmethod
    def available_types(cls) -> List[CrystallizationType]:
        return list(cls._registry.keys())


# ---------------------------------------------------------------------------
# CrystallizationOrchestrator
# ---------------------------------------------------------------------------

class CrystallizationOrchestrator:
    """
    Manages the queue of crystallization jobs and dispatches workers
    based on the scheduler's idle level assessment.

    Runs as a background asyncio task alongside the monitor.
    """

    def __init__(
        self,
        scheduler: CrystallizationScheduler,
        monitor: SubconsciousMonitor,
        check_interval: float = 2.0,
    ):
        self._scheduler = scheduler
        self._monitor = monitor
        self._check_interval = check_interval
        self._queue: List[CrystallizationJob] = []
        self._running_jobs: Dict[str, asyncio.Task] = {}
        self._completed_jobs: List[CrystallizationJob] = []
        self._running = False

        # Concurrency limits
        self.max_concurrent_jobs = 3
        self.max_concurrent_gpu_jobs = 1
        self.max_concurrent_api_jobs = 2

        # Stats
        self.total_jobs_completed = 0
        self.total_insights_generated = 0
        self.total_preemptions = 0

    def enqueue(self, job: CrystallizationJob):
        """Add a job to the priority queue."""
        self._queue.append(job)
        self._queue.sort(key=lambda j: j.priority.value, reverse=True)
        logger.debug("Enqueued %s (priority=%s)", job.job_type.value, job.priority.name)

    def enqueue_standard_jobs(self):
        """Populate the queue with the standard set of crystallization jobs."""
        standard = [
            CrystallizationJob(
                job_type=CrystallizationType.CRYSTAL_CONSOLIDATION,
                priority=CrystallizationPriority.HIGH,
                estimated_duration_seconds=120,
            ),
            CrystallizationJob(
                job_type=CrystallizationType.CROSS_SESSION_PATTERNS,
                priority=CrystallizationPriority.HIGH,
                requires_api_call=True,
                estimated_duration_seconds=180,
            ),
            CrystallizationJob(
                job_type=CrystallizationType.MEMORY_TIER_MIGRATION,
                priority=CrystallizationPriority.MEDIUM,
                estimated_duration_seconds=90,
            ),
            CrystallizationJob(
                job_type=CrystallizationType.NEVEDAL_RECALIBRATION,
                priority=CrystallizationPriority.CRITICAL,
                requires_gpu=True,
                estimated_duration_seconds=300,
            ),
            CrystallizationJob(
                job_type=CrystallizationType.NIGHT_SCHOOL_REFINEMENT,
                priority=CrystallizationPriority.LOW,
                requires_api_call=True,
                estimated_duration_seconds=240,
            ),
            CrystallizationJob(
                job_type=CrystallizationType.RESISTANCE_MAPPING,
                priority=CrystallizationPriority.MEDIUM,
                requires_api_call=True,
                estimated_duration_seconds=150,
            ),
            CrystallizationJob(
                job_type=CrystallizationType.EMOTIONAL_ARC_SYNTHESIS,
                priority=CrystallizationPriority.LOW,
                requires_gpu=True,
                requires_api_call=True,
                estimated_duration_seconds=360,
            ),
            CrystallizationJob(
                job_type=CrystallizationType.MODALITY_WEIGHT_TUNING,
                priority=CrystallizationPriority.AMBIENT,
                estimated_duration_seconds=120,
            ),
            # QUANTUM-CRYSTAL-ARCH — LIMINAL RESOLVE idle-cycle processing
            CrystallizationJob(
                job_type=CrystallizationType.LIMINAL_RESOLVE_PROCESSING,
                priority=CrystallizationPriority.MEDIUM,
                requires_api_call=False,
                estimated_duration_seconds=180,
            ),
        ]
        for job in standard:
            self.enqueue(job)
        logger.info("Enqueued %d standard crystallization jobs", len(standard))

    async def _run_worker(self, job: CrystallizationJob):
        """Execute a single crystallization job via its registered worker."""
        job.started_at = datetime.now(timezone.utc)
        try:
            worker = CrystallizationWorkerFactory.create(job, self._monitor)
            result = await worker.execute()
            job.completed_at = datetime.now(timezone.utc)
            job.result_summary = result.get("summary", "Completed")
            job.insights_generated = result.get("insights_generated", 0)
            self.total_jobs_completed += 1
            self.total_insights_generated += job.insights_generated
            logger.info(
                "Completed %s: %s (%d insights)",
                job.job_type.value, job.result_summary, job.insights_generated,
            )
        except PreemptionRequested:
            job.preempted = True
            self.total_preemptions += 1
            logger.info("Preempted %s — yielding to conscious processing", job.job_type.value)
        except Exception as e:
            job.error = str(e)
            job.completed_at = datetime.now(timezone.utc)
            logger.error("Worker error for %s: %s", job.job_type.value, e)
        finally:
            self._completed_jobs.append(job)
            self._running_jobs.pop(job.id, None)

    def _count_running(self, gpu: bool = False, api: bool = False) -> int:
        """Count running jobs filtered by resource type."""
        count = 0
        for jid in self._running_jobs:
            for j in self._completed_jobs + self._queue:
                if j.id == jid:
                    if gpu and j.requires_gpu:
                        count += 1
                    elif api and j.requires_api_call:
                        count += 1
                    elif not gpu and not api:
                        count += 1
        return len(self._running_jobs) if not gpu and not api else count

    async def run_loop(self):
        """Background orchestration loop — dispatches jobs when idle."""
        self._running = True
        logger.info("CrystallizationOrchestrator started")

        while self._running:
            try:
                # Replenish queue if empty
                if not self._queue and not self._running_jobs:
                    self.enqueue_standard_jobs()

                # Try to dispatch next eligible job
                dispatched = False
                for i, job in enumerate(self._queue):
                    if len(self._running_jobs) >= self.max_concurrent_jobs:
                        break

                    if not self._scheduler.can_run(job.priority, job.requires_gpu):
                        continue

                    if job.requires_gpu and self._count_running(gpu=True) >= self.max_concurrent_gpu_jobs:
                        continue
                    if job.requires_api_call and self._count_running(api=True) >= self.max_concurrent_api_jobs:
                        continue

                    self._queue.pop(i)
                    task = asyncio.create_task(self._run_worker(job))
                    self._running_jobs[job.id] = task
                    dispatched = True
                    logger.debug("Dispatched %s (idle=%s)", job.job_type.value, self._scheduler.idle_level.value)
                    break

                if not dispatched and self._scheduler.idle_level == IdleLevel.ACTIVE:
                    for jid, task in list(self._running_jobs.items()):
                        task.cancel()

            except Exception as e:
                logger.error("Orchestrator error: %s", e)

            await asyncio.sleep(self._check_interval)

    def stop(self):
        self._running = False
        for task in self._running_jobs.values():
            task.cancel()
        logger.info("CrystallizationOrchestrator stopped")

    def status(self) -> Dict[str, Any]:
        """Current orchestrator state for dashboard/API."""
        return {
            "idle_level": self._scheduler.idle_level.value,
            "idle_score": round(self._monitor.idle_score, 3),
            "queue_depth": len(self._queue),
            "running_count": len(self._running_jobs),
            "total_completed": self.total_jobs_completed,
            "total_insights": self.total_insights_generated,
            "total_preemptions": self.total_preemptions,
            "queue": [j.to_dict() for j in self._queue[:5]],
            "running": [jid for jid in self._running_jobs.keys()],
        }


# ---------------------------------------------------------------------------
# QUANTUM-CRYSTAL-ARCH — LIMINAL RESOLVE Worker
# ---------------------------------------------------------------------------

@CrystallizationWorkerFactory.register(CrystallizationType.LIMINAL_RESOLVE_PROCESSING)
class LiminalResolveWorker(BaseCrystallizationWorker):
    """
    Idle-cycle processor for LIMINAL RESOLVE protocol:
    1. Detect cross-client LIMINAL themes (shame topology patterns)
    2. Process curiosity registry — resolve answered questions, surface new ones
    3. Generate anticipatory crystals for clients with active/carried_forward LR states
    4. Backfill affect metadata on crystals missing emotional_valence
    """

    async def execute(self) -> dict:
        insights = 0
        summary_parts = []

        try:
            from app.services.liminal_detectors import score_affect
        except ImportError:
            return {"summary": "liminal_detectors not available", "insights_generated": 0}

        # Phase 1: Cross-client theme detection
        await self.check_preemption()
        try:
            insights += await self._detect_cross_client_themes()
            summary_parts.append("themes")
        except Exception as e:
            logger.warning("LR worker: cross-client themes: %s", e)

        # Phase 2: Curiosity registry processing
        await self.check_preemption()
        try:
            insights += await self._process_curiosity_registry()
            summary_parts.append("curiosity")
        except Exception as e:
            logger.warning("LR worker: curiosity registry: %s", e)

        # Phase 3: Anticipatory crystal generation
        await self.check_preemption()
        try:
            insights += await self._generate_anticipatory_crystals()
            summary_parts.append("anticipatory")
        except Exception as e:
            logger.warning("LR worker: anticipatory crystals: %s", e)

        # Phase 4: Affect metadata backfill
        await self.check_preemption()
        try:
            filled = await self._backfill_affect_metadata(score_affect)
            if filled > 0:
                summary_parts.append(f"affect-fill({filled})")
        except Exception as e:
            logger.warning("LR worker: affect backfill: %s", e)

        return {
            "summary": f"LR processing: {', '.join(summary_parts) or 'no-op'}",
            "insights_generated": insights,
        }

    async def _detect_cross_client_themes(self) -> int:
        """Find recurring LIMINAL themes across multiple clients."""
        try:
            import app.services.liminal_resolve_engine as _lre
            if not hasattr(_lre, "db_pool") or not _lre.db_pool:
                return 0
            db = _lre.db_pool
            async with db.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT shame_topology, parts_map
                       FROM liminal_resolve_states
                       WHERE status IN ('active', 'carried_forward')
                         AND shame_topology IS NOT NULL
                       ORDER BY updated_at DESC LIMIT 50"""
                )
            if len(rows) < 3:
                return 0
            import json
            domain_counts: Dict[str, int] = {}
            for r in rows:
                topo = r["shame_topology"]
                if isinstance(topo, str):
                    topo = json.loads(topo)
                for d in (topo or {}).get("domains", []):
                    domain_counts[d] = domain_counts.get(d, 0) + 1
            recurring = {d: c for d, c in domain_counts.items() if c >= 3}
            return len(recurring)
        except Exception as e:
            logger.warning("LR worker: cross-client theme detection: %s", e)
            return 0

    async def _process_curiosity_registry(self) -> int:
        """Check if any curiosity questions have been answered by new crystals."""
        try:
            import app.services.liminal_resolve_engine as _lre
            if not hasattr(_lre, "db_pool") or not _lre.db_pool:
                return 0
            db = _lre.db_pool
            resolved = 0
            async with db.acquire() as conn:
                questions = await conn.fetch(
                    """SELECT id, question, domain
                       FROM liminal_curiosity_registry
                       WHERE status = 'active'
                       ORDER BY created_at ASC LIMIT 20"""
                )
                for q in questions:
                    high_conf = await conn.fetchval(
                        """SELECT id FROM nate_intelligence_crystals
                           WHERE domain = $1
                             AND confidence >= 0.70
                             AND crystal_text ILIKE '%' || $2 || '%'
                           LIMIT 1""",
                        q["domain"] or "general",
                        (q["question"] or "")[:50],
                    )
                    if high_conf:
                        await conn.execute(
                            """UPDATE liminal_curiosity_registry
                               SET status = 'resolved',
                                   resolved_by_crystal_id = $1,
                                   resolved_at = NOW()
                               WHERE id = $2""",
                            high_conf, q["id"],
                        )
                        resolved += 1
            return resolved
        except Exception as e:
            logger.warning("LR worker: curiosity registry: %s", e)
            return 0

    async def _generate_anticipatory_crystals(self) -> int:
        """Pre-compute evocative imagery context for upcoming sessions."""
        try:
            import app.services.liminal_resolve_engine as _lre
            if not hasattr(_lre, "db_pool") or not _lre.db_pool:
                return 0
            db = _lre.db_pool
            generated = 0
            async with db.acquire() as conn:
                active_states = await conn.fetch(
                    """SELECT user_id, current_task, shame_topology, parts_map
                       FROM liminal_resolve_states
                       WHERE status IN ('active', 'carried_forward')
                         AND cycle_count >= 2
                       ORDER BY updated_at DESC LIMIT 10"""
                )
                import json
                for s in active_states:
                    existing = await conn.fetchval(
                        """SELECT COUNT(*) FROM nate_intelligence_crystals
                           WHERE metadata->>'anticipatory' = 'true'
                             AND metadata->>'target_user_id' = $1
                             AND created_at > NOW() - INTERVAL '7 days'""",
                        s["user_id"],
                    )
                    if existing and existing >= 3:
                        continue
                    topo = s["shame_topology"]
                    if isinstance(topo, str):
                        topo = json.loads(topo)
                    domains = (topo or {}).get("domains", [])
                    if not domains:
                        continue
                    crystal_text = (
                        f"Anticipatory context for LIMINAL RESOLVE: "
                        f"client has cycled through {', '.join(domains[:3])} themes. "
                        f"Current task: {s['current_task']}. "
                        f"Prepare evocative imagery around these domains."
                    )
                    meta = json.dumps({
                        "anticipatory": "true",
                        "target_user_id": s["user_id"],
                        "source_task": s["current_task"],
                    })
                    import hashlib
                    content_hash = hashlib.sha256(crystal_text.encode()).hexdigest()
                    await conn.execute(
                        """INSERT INTO nate_intelligence_crystals
                           (crystal_text, content_hash, domain, confidence,
                            scope, metadata, source_count)
                           VALUES ($1, $2, 'liminal_resolve', 0.45, 'user:' || $3,
                                   $4::jsonb, 1)
                           ON CONFLICT DO NOTHING""",
                        crystal_text, content_hash, s["user_id"], meta,
                    )
                    generated += 1
            return generated
        except Exception as e:
            logger.warning("LR worker: anticipatory crystals: %s", e)
            return 0

    async def _backfill_affect_metadata(self, score_affect: Callable) -> int:
        """Lazy-fill emotional_valence/arousal_level/attachment_activation on older crystals."""
        try:
            import app.services.liminal_resolve_engine as _lre
            if not hasattr(_lre, "db_pool") or not _lre.db_pool:
                return 0
            db = _lre.db_pool
            filled = 0
            async with db.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT id, crystal_text FROM nate_intelligence_crystals
                       WHERE (metadata IS NULL OR metadata->>'emotional_valence' IS NULL)
                         AND crystal_text IS NOT NULL
                         AND LENGTH(crystal_text) > 20
                       ORDER BY created_at DESC LIMIT 100"""
                )
                import json
                for r in rows:
                    affect = score_affect(r["crystal_text"])
                    await conn.execute(
                        """UPDATE nate_intelligence_crystals
                           SET metadata = COALESCE(metadata, '{}'::jsonb) || $1::jsonb
                           WHERE id = $2""",
                        json.dumps(affect), r["id"],
                    )
                    filled += 1
            return filled
        except Exception as e:
            logger.warning("LR worker: affect backfill: %s", e)
            return 0
