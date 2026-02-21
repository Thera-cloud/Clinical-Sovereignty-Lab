"""
LITTLE NATE — Autonomous Livestream Scheduler
Picks optimal times for live sessions based on audience analytics,
runs pre-flight connection checks, goes live autonomously, and
handles failures with rescheduling.

Little Nate doesn't do pro-bono work into the void — he verifies
real connection before he starts coaching.
"""

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("skyeye.livestream.scheduler")

DEFAULT_SESSIONS_PER_WEEK = 3
DEFAULT_SESSION_DURATION = 1800
MAX_PREFLIGHT_RETRIES = 2
PREFLIGHT_RETRY_DELAY = 30


class LivestreamScheduler:
    """Autonomous scheduler for Little Nate livestream sessions."""

    def __init__(self, db_pool, livestream_engine=None):
        self.db_pool = db_pool
        self._engine = livestream_engine
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._scheduled_slots: List[Dict] = []
        self._sessions_per_week = DEFAULT_SESSIONS_PER_WEEK
        self._session_duration = DEFAULT_SESSION_DURATION

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("Livestream scheduler started")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("Livestream scheduler stopped")

    async def get_schedule(self) -> List[Dict]:
        """Return upcoming scheduled sessions."""
        return [s for s in self._scheduled_slots
                if s["scheduled_for"] > datetime.now(timezone.utc)]

    async def get_config(self) -> Dict:
        return {
            "sessions_per_week": self._sessions_per_week,
            "session_duration": self._session_duration,
            "scheduled_slots": [
                {
                    "time": s["scheduled_for"].isoformat(),
                    "platforms": s["platforms"],
                    "topic": s["topic"],
                }
                for s in await self.get_schedule()
            ],
        }

    async def update_config(self, sessions_per_week: int = None,
                            session_duration: int = None):
        if sessions_per_week is not None:
            self._sessions_per_week = max(1, min(7, sessions_per_week))
        if session_duration is not None:
            self._session_duration = max(300, min(3600, session_duration))
        logger.info(
            f"Schedule config updated: {self._sessions_per_week}x/week, "
            f"{self._session_duration}s duration"
        )

    async def _scheduler_loop(self):
        """Main loop: plan sessions, wait for scheduled times, go live."""
        try:
            await asyncio.sleep(10)

            while self._running:
                upcoming = await self.get_schedule()
                if len(upcoming) < self._sessions_per_week:
                    needed = self._sessions_per_week - len(upcoming)
                    new_slots = await self._plan_sessions(needed)
                    self._scheduled_slots.extend(new_slots)
                    for slot in new_slots:
                        logger.info(
                            f"Scheduled session: {slot['scheduled_for'].isoformat()} "
                            f"on {slot['platforms']}"
                        )

                now = datetime.now(timezone.utc)
                for slot in list(self._scheduled_slots):
                    if slot["scheduled_for"] <= now and not slot.get("executed"):
                        slot["executed"] = True
                        asyncio.create_task(self._execute_session(slot))

                self._scheduled_slots = [
                    s for s in self._scheduled_slots
                    if s["scheduled_for"] > now - timedelta(hours=2) or not s.get("executed")
                ]

                await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("Scheduler loop cancelled")
        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")

    async def _plan_sessions(self, count: int) -> List[Dict]:
        """Pick optimal times for upcoming sessions using audience data."""
        optimal_hours = await self._get_optimal_hours()
        rtmp_keys = await self._get_stored_rtmp_keys()
        platforms = list(rtmp_keys.keys()) if rtmp_keys else ["x"]
        topics = await self._pick_topics(count)

        slots = []
        now = datetime.now(timezone.utc)
        existing_times = {s["scheduled_for"].date() for s in self._scheduled_slots}

        for i in range(count):
            day_offset = 1
            while day_offset < 14:
                candidate = now + timedelta(days=day_offset)
                if candidate.date() not in existing_times:
                    break
                day_offset += 1

            hour = random.choice(optimal_hours) if optimal_hours else random.choice([10, 14, 18, 20])
            minute = random.choice([0, 15, 30])

            scheduled_time = candidate.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if scheduled_time <= now:
                scheduled_time += timedelta(days=1)

            slots.append({
                "scheduled_for": scheduled_time,
                "platforms": platforms,
                "rtmp_keys": rtmp_keys,
                "topic": topics[i] if i < len(topics) else None,
                "executed": False,
            })
            existing_times.add(scheduled_time.date())

        return slots

    async def _get_optimal_hours(self) -> List[int]:
        """Query SkyEye analytics to find hours with peak engagement."""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT EXTRACT(HOUR FROM created_at) AS hour,
                           COUNT(*) as activity_count
                    FROM skyeye_activity
                    WHERE created_at > NOW() - INTERVAL '30 days'
                    GROUP BY hour
                    ORDER BY activity_count DESC
                    LIMIT 6
                """)
                if rows:
                    return [int(r["hour"]) for r in rows]
        except Exception as e:
            logger.warning(f"Could not fetch optimal hours: {e}")

        return [10, 12, 14, 17, 19, 20]

    async def _get_stored_rtmp_keys(self) -> Dict[str, str]:
        """Load RTMP keys from the config session in the database."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT rtmp_keys FROM livestream_sessions
                    WHERE status = 'config'
                    ORDER BY created_at DESC LIMIT 1
                """)
                if row and row["rtmp_keys"]:
                    keys = row["rtmp_keys"]
                    if isinstance(keys, str):
                        keys = json.loads(keys)
                    return keys
        except Exception as e:
            logger.error(f"Failed to load RTMP keys: {e}")
        return {}

    async def _pick_topics(self, count: int) -> List[Optional[str]]:
        """Pick topics informed by past livestream questions, therapy themes,
        coherence data, and web wisdom — not random."""
        data_topics = []

        try:
            async with self.db_pool.acquire() as conn:
                # What viewers asked about most in past livestreams
                live_themes = await conn.fetch("""
                    SELECT viewer_question FROM livestream_wisdom
                    ORDER BY created_at DESC LIMIT 30
                """)
                theme_counts = {}
                for r in live_themes:
                    q = r["viewer_question"].lower()
                    for kw in ["anxiety", "stress", "relationship", "grief", "purpose",
                               "meaning", "depression", "anger", "fear", "growth",
                               "loneliness", "self-worth", "boundaries", "change"]:
                        if kw in q:
                            theme_counts[kw] = theme_counts.get(kw, 0) + 1
                if theme_counts:
                    top = sorted(theme_counts, key=theme_counts.get, reverse=True)[:3]
                    for t in top:
                        data_topics.append(f"Navigating {t} with presence and coherence")

                # What therapy sessions are uncovering
                try:
                    therapy = await conn.fetch("""
                        SELECT insight_type, insight_text FROM wisdom_extractions
                        WHERE created_at > NOW() - INTERVAL '14 days'
                        ORDER BY confidence DESC LIMIT 5
                    """)
                    for t in therapy[:2]:
                        data_topics.append(
                            f"What I'm learning about {t['insight_type']}: "
                            f"a conversation about real growth"
                        )
                except Exception:
                    pass

                # What's trending in external content
                try:
                    web = await conn.fetch("""
                        SELECT title, themes FROM web_wisdom
                        WHERE relevance_score > 0.6
                        ORDER BY fetched_at DESC LIMIT 5
                    """)
                    for w in web[:2]:
                        themes = w["themes"] if isinstance(w["themes"], list) else []
                        if themes:
                            data_topics.append(
                                f"Responding to what the world is talking about: {themes[0]}"
                            )
                except Exception:
                    pass

                # Insights from the journal
                try:
                    insights = await conn.fetch("""
                        SELECT title FROM sovereign_insight_journal
                        WHERE insight_type IN ('therapy_pattern', 'livestream_learning')
                          AND created_at > NOW() - INTERVAL '7 days'
                        ORDER BY impact_score DESC NULLS LAST LIMIT 3
                    """)
                    for i in insights:
                        data_topics.append(i["title"])
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"Data-driven topic selection failed: {e}")

        fallback = [
            "Open mic — bring your one question",
            "Emotional coherence in daily life",
            "The liminal space between where you are and where you're going",
            "Real talk — no scripts, just presence",
            None,
        ]

        all_topics = data_topics + fallback
        selected = []
        for i in range(count):
            if i < len(data_topics):
                selected.append(data_topics[i])
            else:
                selected.append(random.choice(fallback))
        return selected

    async def _execute_session(self, slot: Dict):
        """Run the full autonomous session lifecycle:
        pre-flight -> go live -> coach -> end -> log."""
        logger.info(f"Executing scheduled session for {slot['scheduled_for']}")

        if not self._engine:
            logger.error("No livestream engine available")
            await self._log_failure(slot, "no_engine")
            return

        if self._engine.is_live:
            logger.warning("Engine already live, skipping scheduled session")
            return

        rtmp_keys = slot.get("rtmp_keys") or await self._get_stored_rtmp_keys()
        if not rtmp_keys:
            logger.error("No RTMP keys available")
            await self._log_failure(slot, "no_rtmp_keys")
            await self._reschedule(slot, "No RTMP keys configured")
            return

        from app.services.livestream_renderer import LivestreamRenderer
        test_renderer = LivestreamRenderer(rtmp_keys)
        connected = False

        for attempt in range(1, MAX_PREFLIGHT_RETRIES + 2):
            logger.info(f"Pre-flight attempt {attempt}/{MAX_PREFLIGHT_RETRIES + 1}")
            connected = await test_renderer.preflight_check()
            if connected:
                break
            if attempt <= MAX_PREFLIGHT_RETRIES:
                logger.warning(
                    f"Pre-flight failed, retrying in {PREFLIGHT_RETRY_DELAY}s..."
                )
                await asyncio.sleep(PREFLIGHT_RETRY_DELAY)

        await test_renderer.stop()

        if not connected:
            logger.error(
                "Pre-flight FAILED after all retries — "
                "Little Nate is NOT going to coach into the void"
            )
            await self._log_failure(slot, "preflight_failed")
            await self._reschedule(
                slot, "Connection to platform could not be verified"
            )
            return

        logger.info("Pre-flight PASSED — going live")

        result = await self._engine.start_session(
            platforms=slot["platforms"],
            rtmp_keys=rtmp_keys,
            topic=slot.get("topic"),
            duration_limit=self._session_duration,
        )

        if result.get("error"):
            logger.error(f"Failed to start session: {result['error']}")
            await self._log_failure(slot, f"start_error: {result['error']}")
            await self._reschedule(slot, result["error"])

    async def _log_failure(self, slot: Dict, reason: str):
        """Log session failure to database."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO livestream_sessions
                        (session_id, status, platforms, topic,
                         duration_limit, summary, metadata)
                    VALUES (gen_random_uuid(), 'failed', $1, $2, $3, $4, $5)
                """,
                    json.dumps(slot.get("platforms", [])),
                    slot.get("topic"),
                    self._session_duration,
                    f"Autonomous session failed: {reason}",
                    json.dumps({
                        "failure_reason": reason,
                        "scheduled_for": slot["scheduled_for"].isoformat(),
                        "autonomous": True,
                    }),
                )
        except Exception as e:
            logger.error(f"Failed to log failure: {e}")

    async def _reschedule(self, failed_slot: Dict, reason: str):
        """Reschedule a failed session for the next optimal window."""
        next_time = datetime.now(timezone.utc) + timedelta(hours=4)
        optimal_hours = await self._get_optimal_hours()
        if optimal_hours:
            target_hour = min(optimal_hours, key=lambda h: abs(h - next_time.hour))
            next_time = next_time.replace(
                hour=target_hour, minute=0, second=0, microsecond=0
            )
            if next_time <= datetime.now(timezone.utc):
                next_time += timedelta(days=1)

        new_slot = {
            "scheduled_for": next_time,
            "platforms": failed_slot.get("platforms", ["x"]),
            "rtmp_keys": failed_slot.get("rtmp_keys"),
            "topic": failed_slot.get("topic"),
            "executed": False,
        }
        self._scheduled_slots.append(new_slot)
        logger.info(
            f"Rescheduled session for {next_time.isoformat()} "
            f"(reason: {reason})"
        )
