"""
Admission Controller — Semaphore-based concurrent session management.

Controls maximum concurrent voice sessions per VPS node. When at capacity,
returns queue position and estimated wait time. Uses Redis for session
affinity (sticky sessions) so a user's voice call stays on the same node.

Required for carrier-grade (50K+ concurrent) voice scaling.
"""

import asyncio
import logging
import os
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger("admission_controller")

DEFAULT_MAX_CONCURRENT = 200
SESSION_AFFINITY_TTL = 3600
QUEUE_POLL_INTERVAL = 2.0


class AdmissionController:
    """Manage concurrent session admission with graceful queuing."""

    def __init__(self, max_concurrent: int = None, redis_client=None, node_id: str = ""):
        self._max_concurrent = max_concurrent or int(os.getenv("MAX_CONCURRENT_SESSIONS", str(DEFAULT_MAX_CONCURRENT)))
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._active_sessions: Dict[str, float] = {}
        self._queue_position = 0
        self._total_served = 0
        self._total_rejected = 0
        self._redis = redis_client
        self._node_id = node_id or os.getenv("NODE_ID", "primary")

    async def request_admission(
        self, session_id: str, user_id: str = "", timeout: float = 30.0
    ) -> Tuple[bool, Dict]:
        """Request admission for a new session.
        
        Returns (admitted, info_dict).
        If admitted: info_dict has session_id, node_id.
        If rejected: info_dict has queue_position, estimated_wait, message.
        """
        if session_id in self._active_sessions:
            return True, {"session_id": session_id, "node_id": self._node_id, "status": "already_active"}

        if user_id and self._redis:
            try:
                affinity_key = f"session_affinity:{user_id}"
                affinity_node = await self._redis.get(affinity_key)
                if affinity_node and affinity_node != self._node_id:
                    return False, {
                        "status": "redirect",
                        "target_node": affinity_node,
                        "message": "Session affinity: your conversation continues on another node",
                    }
            except Exception as e:
                logger.warning("Session affinity check failed: %s", e)

        try:
            acquired = self._semaphore._value > 0
            if acquired:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=0.1)
                self._active_sessions[session_id] = time.time()
                self._total_served += 1

                if user_id and self._redis:
                    try:
                        await self._redis.setex(
                            f"session_affinity:{user_id}",
                            SESSION_AFFINITY_TTL,
                            self._node_id,
                        )
                    except Exception:
                        pass

                return True, {"session_id": session_id, "node_id": self._node_id, "status": "admitted"}
            else:
                self._queue_position += 1
                queue_pos = self._queue_position
                active_count = len(self._active_sessions)
                avg_duration = self._estimate_avg_duration()
                estimated_wait = (queue_pos * avg_duration) / max(active_count, 1)

                self._total_rejected += 1

                return False, {
                    "status": "queued",
                    "queue_position": queue_pos,
                    "estimated_wait_seconds": round(estimated_wait, 1),
                    "message": (
                        f"Little Nate is helping others right now. "
                        f"You're number {queue_pos} in line. "
                        f"Estimated wait: {int(estimated_wait)}s"
                    ),
                }

        except asyncio.TimeoutError:
            self._total_rejected += 1
            return False, {
                "status": "timeout",
                "message": "Server is at capacity. Please try again in a moment.",
            }

    async def release_session(self, session_id: str, user_id: str = ""):
        """Release a session slot back to the pool."""
        if session_id in self._active_sessions:
            del self._active_sessions[session_id]
            self._semaphore.release()
            
            if self._queue_position > 0:
                self._queue_position = max(0, self._queue_position - 1)

    def _estimate_avg_duration(self) -> float:
        """Estimate average session duration from active sessions."""
        if not self._active_sessions:
            return 300.0
        now = time.time()
        durations = [now - start for start in self._active_sessions.values()]
        return sum(durations) / len(durations) if durations else 300.0

    def get_status(self) -> Dict:
        """Return current admission status for health checks and LB integration."""
        return {
            "node_id": self._node_id,
            "max_concurrent": self._max_concurrent,
            "active_sessions": len(self._active_sessions),
            "available_slots": self._semaphore._value,
            "queue_depth": max(0, self._queue_position),
            "total_served": self._total_served,
            "total_rejected": self._total_rejected,
            "utilization_pct": round(
                len(self._active_sessions) / max(self._max_concurrent, 1) * 100, 1
            ),
            "accepting_new": self._semaphore._value > 0,
        }

    def health(self) -> Dict:
        """Health check for service registry."""
        return {
            "status": "healthy",
            "active": len(self._active_sessions),
            "capacity": self._max_concurrent,
            "available": self._semaphore._value,
        }
