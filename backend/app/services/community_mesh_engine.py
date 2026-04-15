"""
LITTLE NATE — Community Mesh Engine
Server-side group wisdom for Nate-to-Nate BLE/NFC group sessions (AA, SA, therapy groups).
Handles anonymized wisdom aggregation, attendance tracking, and convergence detection.

Never stores which specific users participated in wisdom—only anonymous insight data.
Stagger delay: 300s. Loop interval: 6 hours.
"""

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("nate.community_mesh")

LOOP_INTERVAL_SECONDS = 21600  # 6 hours
STAGGER_DELAY = 300
CONVERGENCE_LOOKBACK_HOURS = 72
MAX_INSIGHTS_PER_TOPIC = 500


class CommunityMeshEngine:
    """Engine for Community Mesh group wisdom and attendance."""

    def __init__(
        self,
        db_pool,
        app_state=None,
        notification_system=None,
    ):
        self.db_pool = db_pool
        self._app_state = app_state
        self.notification_system = notification_system
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("CommunityMeshEngine started (every 6h, stagger 300s)")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CommunityMeshEngine stopped")

    async def _run_loop(self) -> None:
        await asyncio.sleep(STAGGER_DELAY)
        while self._running:
            try:
                await self._run_convergence_detection()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("CommunityMeshEngine convergence failed: %s", e, exc_info=True)
            await asyncio.sleep(LOOP_INTERVAL_SECONDS)

    # ── Wisdom (anonymous only) ───────────────────────────────────────

    async def process_community_data(
        self,
        session_id: str,
        anonymized_wisdom: str,
        topic_tags: Union[List[str], str],
        peer_count: int = 1,
        location: Optional[str] = None,
    ) -> int:
        """
        Store anonymized wisdom from a group session. Never stores participant identities.
        Returns the id of the inserted/updated community_wisdom row.
        """
        topic = self._normalize_topic(topic_tags)
        insight_text = (anonymized_wisdom or "").strip()
        if not insight_text:
            logger.warning("process_community_data: empty insight_text, skipping")
            return 0

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, convergence_count, source_session_count
                    FROM community_wisdom
                    WHERE topic = $1 AND LOWER(TRIM(insight_text)) = LOWER(TRIM($2))
                    LIMIT 1
                    """,
                    topic,
                    insight_text[:10000],
                )
                if row:
                    await conn.execute(
                        """
                        UPDATE community_wisdom
                        SET convergence_count = convergence_count + 1,
                            source_session_count = source_session_count + $2
                        WHERE id = $1
                        """,
                        row["id"],
                        max(1, peer_count),
                    )
                    return row["id"]
                else:
                    rid = await conn.fetchval(
                        """
                        INSERT INTO community_wisdom
                            (topic, insight_text, convergence_count, source_session_count, location_name)
                        VALUES ($1, $2, 1, $3, $4)
                        RETURNING id
                        """,
                        topic,
                        insight_text[:10000],
                        max(1, peer_count),
                        (location or "")[:256] if location else None,
                    )
                    return rid or 0
        except Exception as e:
            logger.error("process_community_data failed: %s", e, exc_info=True)
            raise

    async def get_community_insights(
        self,
        topic: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Retrieve community wisdom, optionally filtered by topic."""
        try:
            async with self.db_pool.acquire() as conn:
                if topic:
                    rows = await conn.fetch(
                        """
                        SELECT id, topic, insight_text, convergence_count,
                               source_session_count, location_name, created_at
                        FROM community_wisdom
                        WHERE topic = $1
                        ORDER BY convergence_count DESC, created_at DESC
                        LIMIT $2
                        """,
                        topic,
                        min(limit, MAX_INSIGHTS_PER_TOPIC),
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT id, topic, insight_text, convergence_count,
                               source_session_count, location_name, created_at
                        FROM community_wisdom
                        ORDER BY convergence_count DESC, created_at DESC
                        LIMIT $1
                        """,
                        min(limit, MAX_INSIGHTS_PER_TOPIC),
                    )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error("get_community_insights failed: %s", e, exc_info=True)
            raise

    # ── Session metadata ──────────────────────────────────────────────

    async def record_session(
        self,
        session_id: str,
        group_name: Optional[str] = None,
        peer_count: int = 0,
        topic_tags: Optional[Union[List[str], str]] = None,
        location_lat: Optional[float] = None,
        location_lng: Optional[float] = None,
        location_name: Optional[str] = None,
        manager_user_id: Optional[str] = None,
    ) -> None:
        """Store or update session metadata."""
        tags_json = self._topic_tags_to_jsonb(topic_tags)
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO community_sessions
                        (session_id, group_name, peer_count, topic_tags,
                         location_lat, location_lng, location_name, manager_user_id)
                    VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8)
                    ON CONFLICT (session_id) DO UPDATE SET
                        group_name = COALESCE(EXCLUDED.group_name, community_sessions.group_name),
                        peer_count = EXCLUDED.peer_count,
                        topic_tags = COALESCE(EXCLUDED.topic_tags, community_sessions.topic_tags),
                        location_lat = COALESCE(EXCLUDED.location_lat, community_sessions.location_lat),
                        location_lng = COALESCE(EXCLUDED.location_lng, community_sessions.location_lng),
                        location_name = COALESCE(EXCLUDED.location_name, community_sessions.location_name),
                        manager_user_id = COALESCE(EXCLUDED.manager_user_id, community_sessions.manager_user_id)
                    """,
                    session_id,
                    (group_name or "")[:128] if group_name else None,
                    peer_count,
                    tags_json,
                    location_lat,
                    location_lng,
                    (location_name or "")[:256] if location_name else None,
                    manager_user_id,
                )
        except Exception as e:
            logger.error("record_session failed: %s", e, exc_info=True)
            raise

    async def _ensure_community_group_entity(
        self, session_id: str, group_name: Optional[str]
    ) -> None:
        """Auto-create a group_entity for community sessions with checked-in users."""
        try:
            async with self.db_pool.acquire() as conn:
                participants = await conn.fetch(
                    "SELECT user_id FROM community_check_ins "
                    "WHERE session_id = $1", session_id)
                if len(participants) < 2:
                    return

                label = (group_name or session_id)[:64]
                ge_id = await conn.fetchval(
                    "INSERT INTO group_entities (group_type, group_name, scene_context) "
                    "VALUES ('community_session', $1, 'therapy_circle') "
                    "RETURNING group_entity_id", label)

                for p in participants:
                    await conn.execute(
                        "INSERT INTO group_entity_members (group_entity_id, client_id) "
                        "VALUES ($1, $2::uuid) "
                        "ON CONFLICT (group_entity_id, client_id) DO NOTHING",
                        ge_id, p["user_id"])

            from app.sse.adapters.group_lora_manager import compile_group_lora_folder
            asyncio.create_task(compile_group_lora_folder(str(ge_id), self.db_pool))
            logger.info("Community group entity created: %s (%d members)",
                        ge_id, len(participants))
        except Exception as e:
            logger.warning("Community group entity enrollment failed: %s", e)

    # ── Check-in / Check-out ────────────────────────────────────────────

    async def record_check_in(
        self,
        session_id: str,
        user_id: str,
        mood_valence: Optional[float] = None,
        location_lat: Optional[float] = None,
        location_lng: Optional[float] = None,
        location_name: Optional[str] = None,
    ) -> None:
        """Record a user's check-in to a session."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO community_check_ins
                        (session_id, user_id, mood_valence, location_lat, location_lng, location_name)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    session_id,
                    user_id,
                    mood_valence,
                    location_lat,
                    location_lng,
                    (location_name or "")[:256] if location_name else None,
                )
        except Exception as e:
            logger.error("record_check_in failed: %s", e, exc_info=True)
            raise
        asyncio.create_task(self._ensure_community_group_entity(session_id, None))

    async def record_check_out(self, session_id: str, user_id: str) -> None:
        """Record a user's check-out from a session."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE community_check_ins
                    SET check_out_time = NOW()
                    WHERE session_id = $1 AND user_id = $2 AND check_out_time IS NULL
                    """,
                    session_id,
                    user_id,
                )
        except Exception as e:
            logger.error("record_check_out failed: %s", e, exc_info=True)
            raise

    # ── Attendance records (for export / compliance) ────────────────────

    async def record_attendance(
        self,
        session_id: str,
        user_id: str,
        check_in_time: datetime,
        session_date: date,
        display_name: Optional[str] = None,
        check_out_time: Optional[datetime] = None,
        location_name: Optional[str] = None,
        group_name: Optional[str] = None,
        duration_minutes: Optional[int] = None,
        verified_by_manager: bool = False,
        signature_b64: Optional[str] = None,
    ) -> None:
        """Store an attendance record for export/compliance."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO community_attendance_records
                        (session_id, user_id, display_name, check_in_time, check_out_time,
                         location_name, group_name, session_date, duration_minutes,
                         verified_by_manager, signature_b64)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    """,
                    session_id,
                    user_id,
                    (display_name or "")[:128] if display_name else None,
                    check_in_time,
                    check_out_time,
                    (location_name or "")[:256] if location_name else None,
                    (group_name or "")[:128] if group_name else None,
                    session_date,
                    duration_minutes,
                    verified_by_manager,
                    signature_b64,
                )
        except Exception as e:
            logger.error("record_attendance failed: %s", e, exc_info=True)
            raise

    async def get_attendance_records(
        self,
        user_id: str,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """Return attendance records for a user, optionally filtered by date range."""
        try:
            async with self.db_pool.acquire() as conn:
                if from_date and to_date:
                    rows = await conn.fetch(
                        """
                        SELECT id, session_id, user_id, display_name, check_in_time, check_out_time,
                               location_name, group_name, session_date, duration_minutes,
                               verified_by_manager, signature_b64
                        FROM community_attendance_records
                        WHERE user_id = $1 AND session_date >= $2 AND session_date <= $3
                        ORDER BY session_date DESC, check_in_time DESC
                        """,
                        user_id,
                        from_date,
                        to_date,
                    )
                elif from_date:
                    rows = await conn.fetch(
                        """
                        SELECT id, session_id, user_id, display_name, check_in_time, check_out_time,
                               location_name, group_name, session_date, duration_minutes,
                               verified_by_manager, signature_b64
                        FROM community_attendance_records
                        WHERE user_id = $1 AND session_date >= $2
                        ORDER BY session_date DESC, check_in_time DESC
                        """,
                        user_id,
                        from_date,
                    )
                elif to_date:
                    rows = await conn.fetch(
                        """
                        SELECT id, session_id, user_id, display_name, check_in_time, check_out_time,
                               location_name, group_name, session_date, duration_minutes,
                               verified_by_manager, signature_b64
                        FROM community_attendance_records
                        WHERE user_id = $1 AND session_date <= $2
                        ORDER BY session_date DESC, check_in_time DESC
                        """,
                        user_id,
                        to_date,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT id, session_id, user_id, display_name, check_in_time, check_out_time,
                               location_name, group_name, session_date, duration_minutes,
                               verified_by_manager, signature_b64
                        FROM community_attendance_records
                        WHERE user_id = $1
                        ORDER BY session_date DESC, check_in_time DESC
                        """,
                        user_id,
                    )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error("get_attendance_records failed: %s", e, exc_info=True)
            raise

    # ── Convergence detection (background) ──────────────────────────────

    async def _run_convergence_detection(self) -> None:
        """
        Merge near-duplicate wisdom entries from recent data.
        Groups by (topic, normalized insight_text) and consolidates convergence counts.
        """
        since = datetime.now(timezone.utc) - timedelta(hours=CONVERGENCE_LOOKBACK_HOURS)
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, topic, insight_text, convergence_count, source_session_count
                    FROM community_wisdom
                    WHERE created_at >= $1
                    ORDER BY created_at ASC
                    """,
                    since,
                )
                if not rows:
                    logger.debug("CommunityMeshEngine: no recent wisdom for convergence")
                    return

                # Group by (topic, normalized_text)
                groups: Dict[tuple, List[Dict[str, Any]]] = {}
                for r in rows:
                    key = (r["topic"], (r["insight_text"] or "").strip().lower())
                    if key not in groups:
                        groups[key] = []
                    groups[key].append(dict(r))

                merged = 0
                for (topic, norm_text), entries in groups.items():
                    if len(entries) <= 1:
                        continue
                    # Keep first (oldest), merge rest into it
                    keep = entries[0]
                    total_conv = sum(e["convergence_count"] for e in entries)
                    total_sess = sum(e["source_session_count"] for e in entries)
                    to_delete = [e["id"] for e in entries[1:]]

                    await conn.execute(
                        """
                        UPDATE community_wisdom
                        SET convergence_count = $2, source_session_count = $3
                        WHERE id = $1
                        """,
                        keep["id"],
                        total_conv,
                        total_sess,
                    )
                    await conn.execute(
                        "DELETE FROM community_wisdom WHERE id = ANY($1)",
                        to_delete,
                    )
                    merged += len(to_delete)

                if merged > 0:
                    logger.info(
                        "CommunityMeshEngine: merged %d duplicate wisdom entries",
                        merged,
                    )
                    await self._log_activity(
                        "community_mesh",
                        "convergence_detection",
                        f"Merged {merged} duplicate wisdom entries (lookback {CONVERGENCE_LOOKBACK_HOURS}h)",
                        "info",
                    )
        except Exception as e:
            logger.error("Convergence detection failed: %s", e, exc_info=True)
            raise

    async def _log_activity(
        self,
        platform: str,
        activity_type: str,
        content: str,
        severity: str = "info",
    ) -> None:
        """Log engine activity to skyeye_activity."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO skyeye_activity (platform, type, content, severity, created_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    """,
                    platform,
                    activity_type,
                    content[:2000],
                    severity,
                )
        except Exception as e:
            logger.debug("_log_activity failed: %s", e)

    # ── Helpers ───────────────────────────────────────────────────────

    def _normalize_topic(self, topic_tags: Union[List[str], str]) -> str:
        """Extract primary topic from tags."""
        if isinstance(topic_tags, str):
            return (topic_tags or "general")[:128]
        if isinstance(topic_tags, list) and topic_tags:
            return (str(topic_tags[0]) or "general")[:128]
        return "general"

    def _topic_tags_to_jsonb(self, topic_tags: Optional[Union[List[str], str]]) -> str:
        """Convert topic_tags to JSON array string for JSONB column."""
        if topic_tags is None:
            return "[]"
        if isinstance(topic_tags, str):
            return json.dumps([topic_tags[:128]]) if topic_tags else "[]"
        if isinstance(topic_tags, list):
            return json.dumps([str(t)[:128] for t in topic_tags])
        return "[]"
