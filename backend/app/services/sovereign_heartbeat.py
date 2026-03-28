"""
Sovereign Heartbeat — R2 heartbeat exchange and Edge Queue Drainer.

Two responsibilities:
1. Write a heartbeat JSON to R2 every 2 minutes so the Edge Worker can detect
   Sovereign Brain health without a direct HTTP call.
2. Drain the Edge Queue (R2 prefix edge-queue/) for events the Edge Brain
   stored while the Sovereign was unreachable, and replay them.

Patent-Pending — Claims 30-56
(c) 2026 Clinical Sovereignty Lab. All rights reserved.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 120
EDGE_QUEUE_DRAIN_INTERVAL = 300
MAX_QUEUE_ITEMS_PER_DRAIN = 50


class SovereignHeartbeat:
    """Background agent that writes heartbeats to R2 and drains the edge queue."""

    def __init__(self, db_pool=None, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._heartbeat_count = 0
        self._queue_drained = 0
        self._last_heartbeat: Optional[float] = None

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("SovereignHeartbeat started (heartbeat: %ds, drain: %ds)",
                     HEARTBEAT_INTERVAL, EDGE_QUEUE_DRAIN_INTERVAL)

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
            "heartbeat_count": self._heartbeat_count,
            "queue_drained": self._queue_drained,
            "last_heartbeat": self._last_heartbeat,
            "running": self._running,
        }

    async def _run_loop(self):
        await asyncio.sleep(10)
        last_drain = 0.0
        while self._running:
            try:
                await self._write_heartbeat()
                now = time.time()
                if now - last_drain >= EDGE_QUEUE_DRAIN_INTERVAL:
                    await self._drain_edge_queue()
                    last_drain = now
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("SovereignHeartbeat cycle error: %s", e)
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def _write_heartbeat(self):
        """Write heartbeat JSON to R2 for Edge Worker to read."""
        try:
            from app.services.blob_storage import upload_bytes
        except ImportError:
            logger.warning("SovereignHeartbeat: blob_storage not available")
            return

        now = datetime.now(timezone.utc)
        service_count = 0
        if self._app_state:
            service_count = getattr(self._app_state, "_healthy_service_count", 0)

        immune_status = "HEALTHY"
        immune_sentinel = getattr(self._app_state, "immune_sentinel", None) if self._app_state else None
        if immune_sentinel:
            status = immune_sentinel.get_status()
            immune_status = status.get("sovereign", {}).get("state", "HEALTHY")

        heartbeat = {
            "timestamp": now.isoformat(),
            "epoch": int(now.timestamp()),
            "service_count": service_count,
            "immune_state": immune_status,
            "version": "1.0",
        }

        try:
            await asyncio.to_thread(
                upload_bytes,
                rel_path="heartbeat/sovereign.json",
                content=json.dumps(heartbeat).encode(),
            )
            self._heartbeat_count += 1
            self._last_heartbeat = time.time()
        except Exception as e:
            logger.warning("SovereignHeartbeat: R2 write failed: %s", e)

    async def _drain_edge_queue(self):
        """Process events from the edge-queue/ R2 prefix."""
        try:
            from app.services.r2_storage import R2Storage
            r2 = R2Storage()
            if not r2._client:
                return
        except Exception:
            return

        try:
            response = r2._client.list_objects_v2(
                Bucket=r2._default_bucket,
                Prefix="edge-queue/",
                MaxKeys=MAX_QUEUE_ITEMS_PER_DRAIN,
            )
            items = response.get("Contents", [])
            if not items:
                return

            processed = 0
            for item in items:
                key = item["Key"]
                try:
                    obj = r2._client.get_object(Bucket=r2._default_bucket, Key=key)
                    body = obj["Body"].read()
                    event = json.loads(body)
                    await self._process_edge_event(event)
                    r2._client.delete_object(Bucket=r2._default_bucket, Key=key)
                    processed += 1
                except Exception as e:
                    logger.warning("SovereignHeartbeat: edge queue item %s failed: %s", key, e)

            if processed:
                self._queue_drained += processed
                logger.info("SovereignHeartbeat: drained %d edge queue items", processed)

        except Exception as e:
            logger.warning("SovereignHeartbeat: edge queue drain failed: %s", e)

    async def _process_edge_event(self, event: Dict[str, Any]):
        """Process a single edge queue event."""
        event_type = event.get("type", "unknown")

        if event_type == "summon_interaction":
            if self._db_pool:
                try:
                    async with self._db_pool.acquire() as conn:
                        await conn.execute(
                            """INSERT INTO skyeye_activity (type, content, platform, created_at)
                               VALUES ('edge_queue_replay', $1, 'system', NOW())""",
                            json.dumps(event),
                        )
                except Exception as e:
                    logger.warning("SovereignHeartbeat: edge event log failed: %s", e)

        elif event_type == "anomaly_report":
            immune_sentinel = getattr(self._app_state, "immune_sentinel", None) if self._app_state else None
            if immune_sentinel:
                immune_sentinel.record_anomaly(
                    brain="edge",
                    anomaly_type=event.get("anomaly_type", "edge_reported"),
                    score=event.get("score", 1.0),
                    details=event.get("details", ""),
                )
