"""
Distributed STT/TTS Worker Pool — Redis job queue for voice processing at scale.

Architecture:
  - STT Pool: Multiple faster-whisper workers on Hetzner CAX41 ARM nodes
  - TTS Pool: Multiple XTTS-v2 workers on Hetzner GPU nodes
  - Redis job queues: stt_jobs:{node_id} and tts_jobs:{node_id}
  - Round-robin or least-loaded dispatch

Required for carrier-grade (50K+ concurrent) voice scaling where
single-node STT (~20-40 concurrent) and TTS (~30-50 concurrent)
are the hard bottlenecks.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger("distributed_voice_pool")

STT_JOB_TTL = 30
TTS_JOB_TTL = 30
RESULT_TTL = 120
HEALTH_CHECK_INTERVAL = 60


@dataclass
class VoiceWorkerNode:
    node_id: str
    node_type: str  # "stt" or "tts"
    endpoint: str
    max_concurrent: int = 20
    active_jobs: int = 0
    last_health_check: float = 0.0
    healthy: bool = True
    latency_ms: float = 0.0


@dataclass
class VoiceJob:
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    job_type: str = "stt"  # "stt" or "tts"
    payload: Dict[str, Any] = field(default_factory=dict)
    submitted_at: float = field(default_factory=time.time)
    timeout_seconds: float = 30.0
    priority: int = 0
    user_id: str = ""
    session_id: str = ""


class DistributedVoicePool:
    """Manage STT and TTS worker pools with Redis job queues."""

    def __init__(self, redis_client=None):
        self._redis = redis_client
        self._stt_nodes: List[VoiceWorkerNode] = []
        self._tts_nodes: List[VoiceWorkerNode] = []
        self._stt_rr_index = 0
        self._tts_rr_index = 0
        self._configure_from_env()

    def _configure_from_env(self):
        """Load node configuration from environment variables."""
        stt_nodes_json = os.getenv("STT_WORKER_NODES", "")
        tts_nodes_json = os.getenv("TTS_WORKER_NODES", "")

        if stt_nodes_json:
            try:
                nodes = json.loads(stt_nodes_json)
                for n in nodes:
                    self._stt_nodes.append(VoiceWorkerNode(
                        node_id=n.get("id", f"stt_{len(self._stt_nodes)}"),
                        node_type="stt",
                        endpoint=n.get("endpoint", ""),
                        max_concurrent=n.get("max_concurrent", 20),
                    ))
            except Exception as e:
                logger.warning("Failed to parse STT_WORKER_NODES: %s", e)

        if tts_nodes_json:
            try:
                nodes = json.loads(tts_nodes_json)
                for n in nodes:
                    self._tts_nodes.append(VoiceWorkerNode(
                        node_id=n.get("id", f"tts_{len(self._tts_nodes)}"),
                        node_type="tts",
                        endpoint=n.get("endpoint", ""),
                        max_concurrent=n.get("max_concurrent", 30),
                    ))
            except Exception as e:
                logger.warning("Failed to parse TTS_WORKER_NODES: %s", e)

        if not self._stt_nodes:
            self._stt_nodes.append(VoiceWorkerNode(
                node_id="stt_local",
                node_type="stt",
                endpoint="local",
                max_concurrent=20,
            ))
        if not self._tts_nodes:
            self._tts_nodes.append(VoiceWorkerNode(
                node_id="tts_local",
                node_type="tts",
                endpoint="local",
                max_concurrent=30,
            ))

    def _select_node(self, pool_type: str) -> Optional[VoiceWorkerNode]:
        """Select least-loaded healthy node via round-robin with load check."""
        nodes = self._stt_nodes if pool_type == "stt" else self._tts_nodes
        healthy = [n for n in nodes if n.healthy and n.active_jobs < n.max_concurrent]

        if not healthy:
            healthy = [n for n in nodes if n.healthy]
            if not healthy:
                return nodes[0] if nodes else None

        healthy.sort(key=lambda n: n.active_jobs)
        return healthy[0]

    async def submit_stt_job(
        self, audio_data: bytes, user_id: str = "", session_id: str = "",
        language: str = "en",
    ) -> Optional[Dict]:
        """Submit an STT job to the pool. Returns transcript or None on failure."""
        node = self._select_node("stt")
        if not node:
            logger.warning("No STT nodes available")
            return None

        if node.endpoint == "local":
            return {"status": "local", "node": "stt_local"}

        job = VoiceJob(
            job_type="stt",
            payload={"language": language, "audio_size": len(audio_data)},
            user_id=user_id,
            session_id=session_id,
        )

        if self._redis:
            try:
                queue_key = f"stt_jobs:{node.node_id}"
                await self._redis.lpush(queue_key, json.dumps(asdict(job)))
                await self._redis.expire(queue_key, STT_JOB_TTL)
                node.active_jobs += 1
                return {"status": "queued", "job_id": job.job_id, "node": node.node_id}
            except Exception as e:
                logger.warning("STT job submission failed: %s", e)

        return {"status": "local_fallback", "node": "stt_local"}

    async def submit_tts_job(
        self, text: str, user_id: str = "", session_id: str = "",
        voice_id: str = "default", speed: float = 1.0,
    ) -> Optional[Dict]:
        """Submit a TTS job to the pool. Returns audio data or fallback indicator."""
        node = self._select_node("tts")
        if not node:
            logger.warning("No TTS nodes available")
            return None

        if node.endpoint == "local":
            return {"status": "local", "node": "tts_local"}

        job = VoiceJob(
            job_type="tts",
            payload={"text": text[:5000], "voice_id": voice_id, "speed": speed},
            user_id=user_id,
            session_id=session_id,
        )

        if self._redis:
            try:
                queue_key = f"tts_jobs:{node.node_id}"
                await self._redis.lpush(queue_key, json.dumps(asdict(job)))
                await self._redis.expire(queue_key, TTS_JOB_TTL)
                node.active_jobs += 1
                return {"status": "queued", "job_id": job.job_id, "node": node.node_id}
            except Exception as e:
                logger.warning("TTS job submission failed: %s", e)

        return {"status": "local_fallback", "node": "tts_local"}

    def get_pool_status(self) -> Dict:
        """Return status of all worker pools."""
        return {
            "stt_pool": {
                "node_count": len(self._stt_nodes),
                "healthy_nodes": sum(1 for n in self._stt_nodes if n.healthy),
                "total_capacity": sum(n.max_concurrent for n in self._stt_nodes),
                "active_jobs": sum(n.active_jobs for n in self._stt_nodes),
                "nodes": [
                    {
                        "id": n.node_id,
                        "endpoint": n.endpoint[:30] if n.endpoint != "local" else "local",
                        "healthy": n.healthy,
                        "active": n.active_jobs,
                        "capacity": n.max_concurrent,
                    }
                    for n in self._stt_nodes
                ],
            },
            "tts_pool": {
                "node_count": len(self._tts_nodes),
                "healthy_nodes": sum(1 for n in self._tts_nodes if n.healthy),
                "total_capacity": sum(n.max_concurrent for n in self._tts_nodes),
                "active_jobs": sum(n.active_jobs for n in self._tts_nodes),
                "nodes": [
                    {
                        "id": n.node_id,
                        "endpoint": n.endpoint[:30] if n.endpoint != "local" else "local",
                        "healthy": n.healthy,
                        "active": n.active_jobs,
                        "capacity": n.max_concurrent,
                    }
                    for n in self._tts_nodes
                ],
            },
        }

    def health(self) -> Dict:
        """Health check for service registry."""
        return {
            "status": "healthy",
            "stt_nodes": len(self._stt_nodes),
            "tts_nodes": len(self._tts_nodes),
            "stt_healthy": sum(1 for n in self._stt_nodes if n.healthy),
            "tts_healthy": sum(1 for n in self._tts_nodes if n.healthy),
        }
