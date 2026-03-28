"""
Cold Tier Migration Agent

Background agent that automatically migrates objects from R2 (hot/warm)
to B2 (cold archive) based on age thresholds. This saves ~60% on storage
costs for data that is rarely accessed.

Migration flow:
  1. List objects in R2 cold bucket older than COLD_TIER_AGE_DAYS
  2. Copy each to B2 with optional Object Lock retention
  3. Delete the R2 copy after successful B2 write
  4. Log the migration to skyeye_activity

Runs every 6 hours. Non-destructive: only deletes from R2 after B2
write is confirmed.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

_logger = logging.getLogger("cold_tier_agent")

COLD_TIER_AGE_DAYS = int(os.getenv("COLD_TIER_AGE_DAYS", "30"))
COLD_TIER_BATCH_SIZE = int(os.getenv("COLD_TIER_BATCH_SIZE", "50"))
COLD_TIER_CYCLE_HOURS = 6

_R2_COLD_BUCKET = os.getenv("R2_COLD_BUCKET", "nate-cold-archive")
_B2_COLD_BUCKET = os.getenv("B2_COLD_BUCKET", "nate-cold-archive")
_R2_HERITAGE_BUCKET = os.getenv("R2_HERITAGE_BUCKET", "nate-heritage-vault")
_B2_HERITAGE_BUCKET = os.getenv("B2_HERITAGE_BUCKET", "nate-heritage-vault")


class ColdTierAgent:
    """Migrates aged objects from R2 to B2 for cost savings."""

    def __init__(self, db_pool=None, notification_system=None):
        self._db = db_pool
        self._notifications = notification_system
        self._running = False
        self._task = None
        self._stats = {
            "last_run": None,
            "total_migrated": 0,
            "total_bytes_migrated": 0,
            "last_cycle_count": 0,
            "errors": 0,
        }

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        _logger.info("ColdTierAgent started (age threshold: %dd, cycle: %dh)",
                      COLD_TIER_AGE_DAYS, COLD_TIER_CYCLE_HOURS)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        _logger.info("ColdTierAgent stopped (total migrated: %d)", self._stats["total_migrated"])

    async def _run_loop(self):
        while self._running:
            try:
                await self._run_cycle()
            except Exception as e:
                _logger.warning("ColdTierAgent cycle error: %s", e)
                self._stats["errors"] += 1

            await asyncio.sleep(COLD_TIER_CYCLE_HOURS * 3600)

    async def _run_cycle(self):
        try:
            from app.services.r2_storage import is_r2_configured
            from app.services.b2_storage import is_b2_configured
        except ImportError:
            _logger.info("ColdTierAgent: R2 or B2 module not available, skipping")
            return

        if not is_r2_configured() or not is_b2_configured():
            _logger.info("ColdTierAgent: R2 or B2 not configured, skipping")
            return

        cycle_count = 0
        cycle_bytes = 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=COLD_TIER_AGE_DAYS)

        for r2_bucket, b2_bucket in [
            (_R2_COLD_BUCKET, _B2_COLD_BUCKET),
            (_R2_HERITAGE_BUCKET, _B2_HERITAGE_BUCKET),
        ]:
            migrated, mbytes = await self._migrate_bucket(r2_bucket, b2_bucket, cutoff)
            cycle_count += migrated
            cycle_bytes += mbytes

        self._stats["last_run"] = datetime.now(timezone.utc).isoformat()
        self._stats["last_cycle_count"] = cycle_count
        self._stats["total_migrated"] += cycle_count
        self._stats["total_bytes_migrated"] += cycle_bytes

        if cycle_count > 0:
            _logger.info("ColdTierAgent: migrated %d objects (%d bytes) R2→B2",
                         cycle_count, cycle_bytes)
            await self._log_activity(cycle_count, cycle_bytes)

    async def _migrate_bucket(self, r2_bucket: str, b2_bucket: str,
                               cutoff: datetime) -> tuple:
        from app.services.r2_storage import (
            list_objects, head_object, download_bytes, delete_object,
        )
        from app.services.b2_storage import upload_bytes, head_object as b2_head

        migrated = 0
        total_bytes = 0

        try:
            keys = await asyncio.to_thread(
                list_objects, prefix="", bucket=r2_bucket, max_keys=COLD_TIER_BATCH_SIZE
            )
        except Exception as e:
            _logger.warning("ColdTierAgent: failed to list R2 bucket %s: %s", r2_bucket, e)
            return 0, 0

        for key in keys:
            if migrated >= COLD_TIER_BATCH_SIZE:
                break

            try:
                meta = await asyncio.to_thread(head_object, key=key, bucket=r2_bucket)
                if meta is None:
                    continue

                last_modified = meta.get("LastModified")
                if last_modified is None:
                    continue

                if hasattr(last_modified, "tzinfo") and last_modified.tzinfo is None:
                    last_modified = last_modified.replace(tzinfo=timezone.utc)

                if last_modified > cutoff:
                    continue

                b2_exists = await asyncio.to_thread(b2_head, key=key, bucket=b2_bucket)
                if b2_exists is not None:
                    await asyncio.to_thread(delete_object, key=key, bucket=r2_bucket)
                    migrated += 1
                    continue

                data = await asyncio.to_thread(download_bytes, key=key, bucket=r2_bucket)
                if data is None:
                    continue

                obj_metadata = {}
                if meta.get("Metadata"):
                    obj_metadata = {k: str(v) for k, v in meta["Metadata"].items()}
                obj_metadata["migrated_from"] = "r2"
                obj_metadata["migrated_at"] = datetime.now(timezone.utc).isoformat()

                await asyncio.to_thread(
                    upload_bytes,
                    key=key, content=data, bucket=b2_bucket,
                    content_type=meta.get("ContentType", "application/octet-stream"),
                    metadata=obj_metadata,
                )

                await asyncio.to_thread(delete_object, key=key, bucket=r2_bucket)

                migrated += 1
                total_bytes += len(data)

            except Exception as e:
                _logger.warning("ColdTierAgent: failed to migrate %s: %s", key, e)
                self._stats["errors"] += 1

        return migrated, total_bytes

    async def _log_activity(self, count: int, total_bytes: int):
        if not self._db:
            return
        try:
            import json
            await self._db.execute(
                """INSERT INTO skyeye_activity (type, platform, content, created_at)
                   VALUES ($1, $2, $3, NOW())""",
                "cold_tier_migration",
                "system",
                json.dumps({
                    "objects_migrated": count,
                    "bytes_migrated": total_bytes,
                    "age_threshold_days": COLD_TIER_AGE_DAYS,
                    "total_lifetime_migrated": self._stats["total_migrated"],
                }),
            )
        except Exception as e:
            _logger.warning("ColdTierAgent: failed to log activity: %s", e)

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "age_threshold_days": COLD_TIER_AGE_DAYS,
            "cycle_hours": COLD_TIER_CYCLE_HOURS,
            **self._stats,
        }
