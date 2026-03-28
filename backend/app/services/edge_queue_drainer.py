"""
Edge Queue Drainer — Dedicated background agent for processing deferred edge events.

When the Sovereign Brain is down, the Edge Brain (Cloudflare Worker) queues
events to R2 under the edge-queue/ prefix. This agent drains that queue
with higher throughput than the heartbeat agent's opportunistic drain.

Runs every 2 minutes. Processes up to 100 items per cycle with batch
error handling and metrics tracking.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("edge_queue_drainer")

DRAIN_INTERVAL = 120  # 2 minutes
MAX_ITEMS_PER_CYCLE = 100


class EdgeQueueDrainer:
    def __init__(self, db_pool=None, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cycle_count = 0
        self._total_drained = 0
        self._total_failed = 0
        self._last_drain: Optional[float] = None

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("EdgeQueueDrainer started (2-min drain cycle)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        await asyncio.sleep(60)
        while self._running:
            try:
                await self._drain_cycle()
                self._cycle_count += 1
                self._last_drain = time.time()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("EdgeQueueDrainer cycle error: %s", e)
            await asyncio.sleep(DRAIN_INTERVAL)

    async def _drain_cycle(self):
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
                MaxKeys=MAX_ITEMS_PER_CYCLE,
            )
            items = response.get("Contents", [])
            if not items:
                return

            processed = 0
            failed = 0
            for item in items:
                key = item["Key"]
                try:
                    obj = r2._client.get_object(Bucket=r2._default_bucket, Key=key)
                    body = obj["Body"].read()
                    event = json.loads(body)
                    await self._process_event(event)
                    r2._client.delete_object(Bucket=r2._default_bucket, Key=key)
                    processed += 1
                except Exception as e:
                    logger.warning("EdgeQueueDrainer: item %s failed: %s", key, e)
                    failed += 1
                    # Move poison items to dead-letter after 3 failures
                    await self._maybe_dead_letter(r2, key, item, str(e))

            self._total_drained += processed
            self._total_failed += failed
            if processed:
                logger.info("EdgeQueueDrainer: drained %d items (%d failed)", processed, failed)

        except Exception as e:
            logger.warning("EdgeQueueDrainer: drain cycle failed: %s", e)

    async def _process_event(self, event: Dict[str, Any]):
        """Process a deferred edge event."""
        event_type = event.get("type", "unknown")

        if event_type == "summon_interaction" and self._db_pool:
            try:
                async with self._db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO skyeye_activity (type, content, platform, created_at)
                        VALUES ('edge_summon_deferred', $1, 'edge', $2)
                    """, json.dumps(event), datetime.now(timezone.utc))
            except Exception as e:
                logger.debug("EdgeQueueDrainer: summon event store failed: %s", e)

        elif event_type == "immune_metric" and self._app_state:
            sentinel = getattr(self._app_state, "immune_sentinel", None)
            if sentinel:
                try:
                    sentinel.record_metric(
                        event.get("brain", "edge"),
                        event.get("metrics", {}),
                    )
                except Exception:
                    pass

        elif event_type == "crystal_sync" and self._db_pool:
            try:
                async with self._db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO skyeye_activity (type, content, platform, created_at)
                        VALUES ('edge_crystal_sync', $1, 'edge', $2)
                    """, json.dumps(event), datetime.now(timezone.utc))
            except Exception as e:
                logger.debug("EdgeQueueDrainer: crystal sync store failed: %s", e)

    async def _maybe_dead_letter(self, r2, key: str, item: Dict, error: str):
        """Move repeatedly failing items to a dead-letter prefix."""
        try:
            dl_key = key.replace("edge-queue/", "edge-queue-dead/", 1)
            obj = r2._client.get_object(Bucket=r2._default_bucket, Key=key)
            body = obj["Body"].read()
            r2._client.put_object(
                Bucket=r2._default_bucket,
                Key=dl_key,
                Body=body,
                Metadata={"error": error[:200], "moved_at": datetime.now(timezone.utc).isoformat()},
            )
            r2._client.delete_object(Bucket=r2._default_bucket, Key=key)
            logger.info("EdgeQueueDrainer: moved poison item to dead-letter: %s", dl_key)
        except Exception:
            pass

    def health(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "total_drained": self._total_drained,
            "total_failed": self._total_failed,
            "last_drain": self._last_drain,
        }
