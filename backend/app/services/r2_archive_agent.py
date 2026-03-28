"""
R2 Archive Agent — Archive old data from PostgreSQL to R2 cold storage.

Runs every 6 hours. Archives:
  - conversation_history older than 90 days
  - nevedal_metrics older than 30 days
  - skyeye_activity older than 30 days

PostgreSQL stays small and fast (active data only).
R2 holds infinite history at near-zero cost ($0.015/GB/month, $0 egress).
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("r2_archive_agent")

ARCHIVE_INTERVAL_SECONDS = 21600  # 6 hours
CONVERSATION_RETENTION_DAYS = 90
METRICS_RETENTION_DAYS = 30
ACTIVITY_RETENTION_DAYS = 30
BATCH_SIZE = 500


class R2ArchiveAgent:
    def __init__(self, db_pool=None, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cycle_count = 0
        self._total_archived = {
            "conversation_history": 0,
            "nevedal_metrics": 0,
            "skyeye_activity": 0,
        }
        self._last_archive: Optional[float] = None

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("R2ArchiveAgent started (6h archive cycle)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        await asyncio.sleep(270)
        while self._running:
            try:
                await self._archive_cycle()
                self._cycle_count += 1
                self._last_archive = time.time()
            except Exception as e:
                logger.warning("R2ArchiveAgent cycle error: %s", e)
            await asyncio.sleep(ARCHIVE_INTERVAL_SECONDS)

    async def _archive_cycle(self):
        if not self._db_pool:
            return

        await self._archive_conversation_history()
        await self._archive_nevedal_metrics()
        await self._archive_skyeye_activity()
        await self._cleanup_old_analytics_jsonl()

    async def _cleanup_old_analytics_jsonl(self):
        """Delete analytics JSONL files from R2 older than 365 days."""
        try:
            from app.services.r2_storage import R2Storage
            r2 = R2Storage()
            if not r2._client:
                return
        except Exception:
            return

        try:
            cutoff = time.time() - (365 * 86400)
            response = r2._client.list_objects_v2(
                Bucket=r2._default_bucket,
                Prefix="analytics/",
                MaxKeys=200,
            )
            items = response.get("Contents", [])
            deleted = 0
            for item in items:
                last_mod = item.get("LastModified")
                if last_mod and last_mod.timestamp() < cutoff:
                    try:
                        r2._client.delete_object(Bucket=r2._default_bucket, Key=item["Key"])
                        deleted += 1
                    except Exception:
                        pass
            if deleted:
                self._total_archived.setdefault("analytics_cleaned", 0)
                self._total_archived["analytics_cleaned"] += deleted
                logger.info("R2ArchiveAgent: cleaned %d expired analytics JSONL files", deleted)
        except Exception as e:
            logger.debug("R2ArchiveAgent: analytics cleanup skipped: %s", e)

    async def _upload_to_r2(self, rel_path: str, data: bytes) -> bool:
        try:
            from app.services.blob_storage import upload_bytes
            await asyncio.to_thread(upload_bytes, rel_path=rel_path, content=data)
            return True
        except Exception as e:
            logger.warning("R2 archive upload failed for %s: %s", rel_path, e)
            return False

    async def _archive_conversation_history(self):
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(f"""
                    SELECT id, user_id, session_id, user_text, ai_text, created_at
                    FROM conversation_history
                    WHERE created_at < NOW() - INTERVAL '{CONVERSATION_RETENTION_DAYS} days'
                    ORDER BY created_at ASC
                    LIMIT {BATCH_SIZE}
                """)

            if not rows:
                return

            archive_data = []
            ids_to_prune = []
            for row in rows:
                entry = {
                    "id": str(row["id"]),
                    "user_id": row["user_id"],
                    "session_id": row.get("session_id", ""),
                    "user_text": row.get("user_text", ""),
                    "ai_text": row.get("ai_text", ""),
                    "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
                }
                archive_data.append(entry)
                ids_to_prune.append(row["id"])

            date_prefix = datetime.now(timezone.utc).strftime("%Y/%m/%d")
            archive_path = f"archive/conversation_history/{date_prefix}/{int(time.time())}.jsonl"
            jsonl = "\n".join(json.dumps(entry) for entry in archive_data)

            if await self._upload_to_r2(archive_path, jsonl.encode()):
                async with self._db_pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM conversation_history WHERE id = ANY($1::int[])",
                        ids_to_prune,
                    )
                self._total_archived["conversation_history"] += len(ids_to_prune)
                logger.info("Archived %d conversation_history rows to R2", len(ids_to_prune))

        except Exception as e:
            logger.warning("conversation_history archive error: %s", e)

    async def _archive_nevedal_metrics(self):
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(f"""
                    SELECT id, user_id, c_emo, p_ent, t_tunnel, gamma_env,
                           e_g_joint, tau_emo, d_distance, cee_window,
                           cee_duration_seconds, biometrics, recorded_at
                    FROM nevedal_metrics
                    WHERE recorded_at < NOW() - INTERVAL '{METRICS_RETENTION_DAYS} days'
                    ORDER BY recorded_at ASC
                    LIMIT {BATCH_SIZE}
                """)

            if not rows:
                return

            archive_data = []
            ids_to_prune = []
            for row in rows:
                entry = {
                    "id": str(row["id"]),
                    "user_id": str(row.get("user_id", "")),
                    "c_emo": float(row["c_emo"]) if row.get("c_emo") is not None else None,
                    "p_ent": float(row["p_ent"]) if row.get("p_ent") is not None else None,
                    "t_tunnel": float(row["t_tunnel"]) if row.get("t_tunnel") is not None else None,
                    "gamma_env": float(row["gamma_env"]) if row.get("gamma_env") is not None else None,
                    "e_g_joint": float(row["e_g_joint"]) if row.get("e_g_joint") is not None else None,
                    "tau_emo": float(row["tau_emo"]) if row.get("tau_emo") is not None else None,
                    "d_distance": float(row["d_distance"]) if row.get("d_distance") is not None else None,
                    "cee_window": bool(row.get("cee_window", False)),
                    "cee_duration_seconds": row.get("cee_duration_seconds"),
                    "recorded_at": row["recorded_at"].isoformat() if row.get("recorded_at") else "",
                }
                archive_data.append(entry)
                ids_to_prune.append(row["id"])

            date_prefix = datetime.now(timezone.utc).strftime("%Y/%m/%d")
            archive_path = f"archive/nevedal_metrics/{date_prefix}/{int(time.time())}.jsonl"
            jsonl = "\n".join(json.dumps(entry) for entry in archive_data)

            if await self._upload_to_r2(archive_path, jsonl.encode()):
                async with self._db_pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM nevedal_metrics WHERE id = ANY($1::int[])",
                        ids_to_prune,
                    )
                self._total_archived["nevedal_metrics"] += len(ids_to_prune)
                logger.info("Archived %d nevedal_metrics rows to R2", len(ids_to_prune))

        except Exception as e:
            logger.warning("nevedal_metrics archive error: %s", e)

    async def _archive_skyeye_activity(self):
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(f"""
                    SELECT id, type, content, platform, created_at
                    FROM skyeye_activity
                    WHERE created_at < NOW() - INTERVAL '{ACTIVITY_RETENTION_DAYS} days'
                      AND type NOT LIKE '%audit%'
                      AND type NOT LIKE '%trust%'
                    ORDER BY created_at ASC
                    LIMIT {BATCH_SIZE}
                """)

            if not rows:
                return

            archive_data = []
            ids_to_prune = []
            for row in rows:
                entry = {
                    "id": str(row["id"]),
                    "type": row.get("type", ""),
                    "content": row.get("content", ""),
                    "platform": row.get("platform", ""),
                    "created_at": row["created_at"].isoformat() if row.get("created_at") else "",
                }
                archive_data.append(entry)
                ids_to_prune.append(row["id"])

            date_prefix = datetime.now(timezone.utc).strftime("%Y/%m/%d")
            archive_path = f"archive/skyeye_activity/{date_prefix}/{int(time.time())}.jsonl"
            jsonl = "\n".join(json.dumps(entry) for entry in archive_data)

            if await self._upload_to_r2(archive_path, jsonl.encode()):
                async with self._db_pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM skyeye_activity WHERE id = ANY($1::int[])",
                        ids_to_prune,
                    )
                self._total_archived["skyeye_activity"] += len(ids_to_prune)
                logger.info("Archived %d skyeye_activity rows to R2", len(ids_to_prune))

        except Exception as e:
            logger.warning("skyeye_activity archive error: %s", e)

    def health(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "total_archived": self._total_archived,
            "last_archive": self._last_archive,
            "retention_days": {
                "conversation": CONVERSATION_RETENTION_DAYS,
                "metrics": METRICS_RETENTION_DAYS,
                "activity": ACTIVITY_RETENTION_DAYS,
            },
        }
