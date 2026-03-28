"""
Code Cycle Detector — Proactive Pre-Warming via FFT Pattern Recognition.

Extends the CycleDetectionEngine's code_learning domain with:
  1. Divergence cycle tracking — when dual-brain (edge vs sovereign) disagrees
     repeatedly on the same topic, log and predict recurrence.
  2. Bug recurrence detection — FFT on topic frequency in TENSION crystals to
     find recurring problem domains (e.g., "asyncpg pool exhaustion" every 5 days).
  3. Temporal clustering — identifies time-of-day and day-of-week patterns in
     coding queries to pre-warm relevant crystals before peak usage.
  4. Pre-warm trigger — pushes predicted high-demand crystals to SUMMON_CACHE KV
     before the query arrives, collapsing cold path (90ms) to KV hit (5ms).

EXA v5: This is the bridge between CycleDetectionEngine intelligence and the
cron worker's crystal pre-warming system.  When a cycle is detected, the
detector writes a pre-warm manifest to R2 that the cron worker reads on its
next hourly sweep.
"""

import asyncio
import hashlib
import json
import logging
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

DIVERGENCE_THRESHOLD = 0.85
MIN_CYCLE_OBSERVATIONS = 7
PREWARM_MANIFEST_KEY = "code_crystals/prewarm_manifest.json"
MAX_PREWARM_CRYSTALS = 200


class CodeCycleDetector:
    """
    Proactive pre-warming engine for code intelligence crystals.

    Analyzes dual-brain divergence patterns, TENSION resolution frequency,
    and temporal query clustering to predict which crystals will be needed
    next — then pushes them to edge KV before the query arrives.
    """

    def __init__(self, db_pool=None, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._r2_storage = None
        self._vectorize_service = None
        self._cycle_engine = None
        logger.info("CodeCycleDetector initialized")

    async def start(self):
        if self._app_state:
            self._r2_storage = getattr(self._app_state, "r2_storage", None)
            self._vectorize_service = getattr(self._app_state, "vectorize_service", None)
            self._cycle_engine = getattr(self._app_state, "cycle_detection_engine", None)

    async def stop(self):
        logger.info("CodeCycleDetector stopped")

    # ------------------------------------------------------------------
    # 1. Divergence Cycle Detection
    # ------------------------------------------------------------------

    async def detect_divergence_cycles(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Find topics where dual-brain disagreements recur.
        Queries code_divergence_log for repeated low-similarity events
        on the same topic cluster.
        """
        if not self._db_pool:
            return []

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT topic_hash, topic_label,
                           COUNT(*) as divergence_count,
                           AVG(cosine_similarity) as avg_similarity,
                           MIN(detected_at) as first_seen,
                           MAX(detected_at) as last_seen
                    FROM code_divergence_log
                    WHERE detected_at > NOW() - ($1 || ' days')::INTERVAL
                    GROUP BY topic_hash, topic_label
                    HAVING COUNT(*) >= 3
                    ORDER BY COUNT(*) DESC
                    LIMIT 20
                """, str(days))

            cycles = []
            for row in rows:
                span_days = max(
                    (row["last_seen"] - row["first_seen"]).total_seconds() / 86400,
                    1.0,
                )
                frequency = row["divergence_count"] / span_days

                cycles.append({
                    "topic_hash": row["topic_hash"],
                    "topic_label": row["topic_label"],
                    "divergence_count": row["divergence_count"],
                    "avg_similarity": round(float(row["avg_similarity"]), 4),
                    "frequency_per_day": round(frequency, 3),
                    "span_days": round(span_days, 1),
                    "predicted_next": (
                        row["last_seen"] + timedelta(days=1.0 / max(frequency, 0.01))
                    ).isoformat(),
                    "prewarm_priority": "high" if row["divergence_count"] >= 5 else "medium",
                })

            logger.info("CodeCycleDetector: found %d divergence cycles in %d days",
                        len(cycles), days)
            return cycles
        except Exception as e:
            logger.warning("CodeCycleDetector: divergence detection failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # 2. Bug Recurrence Detection (FFT on TENSION resolutions)
    # ------------------------------------------------------------------

    async def detect_bug_recurrence(self, days: int = 60) -> List[Dict[str, Any]]:
        """
        Apply FFT to TENSION crystal creation timestamps grouped by topic tag.
        Finds recurring problem domains (e.g., 'asyncpg' issues every 5 days).
        """
        if not self._db_pool:
            return []

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT DATE(created_at) as day, topics, crystal_text
                    FROM nate_intelligence_crystals
                    WHERE domain = 'coding'
                      AND scope != 'archived'
                      AND created_at > NOW() - ($1 || ' days')::INTERVAL
                    ORDER BY created_at
                """, str(days))

            if len(rows) < MIN_CYCLE_OBSERVATIONS:
                return []

            tag_daily = defaultdict(lambda: defaultdict(int))
            for row in rows:
                day_str = row["day"].isoformat()
                topics = row["topics"] if isinstance(row["topics"], list) else []
                for tag in topics:
                    tag_daily[tag][day_str] += 1

            recurrences = []
            for tag, daily_counts in tag_daily.items():
                if len(daily_counts) < MIN_CYCLE_OBSERVATIONS:
                    continue

                sorted_days = sorted(daily_counts.keys())
                start = datetime.fromisoformat(sorted_days[0])
                end = datetime.fromisoformat(sorted_days[-1])
                span = (end - start).days + 1

                signal = np.zeros(span)
                for day_str, count in daily_counts.items():
                    idx = (datetime.fromisoformat(day_str) - start).days
                    if 0 <= idx < span:
                        signal[idx] = count

                if np.sum(signal) < MIN_CYCLE_OBSERVATIONS:
                    continue

                fft_result = np.fft.rfft(signal - np.mean(signal))
                magnitudes = np.abs(fft_result)
                if len(magnitudes) < 3:
                    continue
                magnitudes[0] = 0

                median_mag = np.median(magnitudes[1:])
                threshold = max(median_mag * 2.5, 0.1)

                for i in range(1, len(magnitudes)):
                    if magnitudes[i] > threshold:
                        period = span / i
                        if period < 2 or period > span * 0.8:
                            continue

                        confidence = min(float(magnitudes[i]) / (np.max(magnitudes[1:]) + 0.001), 0.99)
                        recurrences.append({
                            "tag": tag,
                            "period_days": round(period, 1),
                            "amplitude": round(float(magnitudes[i]) / span, 4),
                            "confidence": round(confidence, 2),
                            "total_occurrences": int(np.sum(signal)),
                            "predicted_next_peak": (
                                end + timedelta(days=period - ((end - start).days % period))
                            ).isoformat(),
                        })

            recurrences.sort(key=lambda r: r["confidence"], reverse=True)
            logger.info("CodeCycleDetector: found %d bug recurrence patterns", len(recurrences))
            return recurrences[:15]
        except Exception as e:
            logger.warning("CodeCycleDetector: bug recurrence detection failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # 3. Temporal Clustering
    # ------------------------------------------------------------------

    async def detect_temporal_clusters(self, days: int = 30) -> Dict[str, Any]:
        """
        Identify time-of-day and day-of-week patterns in coding queries.
        Used to schedule pre-warming before peak usage windows.
        """
        if not self._db_pool:
            return {}

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT created_at FROM nevedal_coherence_log
                    WHERE domain = 'coding'
                      AND created_at > NOW() - ($1 || ' days')::INTERVAL
                    ORDER BY created_at
                """, str(days))

            if not rows:
                return {"status": "no_data"}

            hour_counts = Counter()
            dow_counts = Counter()
            for row in rows:
                ts = row["created_at"]
                hour_counts[ts.hour] += 1
                dow_counts[ts.strftime("%A")] += 1

            total = len(rows)
            peak_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            peak_days = sorted(dow_counts.items(), key=lambda x: x[1], reverse=True)[:3]

            prewarm_schedule = []
            for hour, count in peak_hours:
                if count / max(total, 1) > 0.1:
                    prewarm_hour = (hour - 1) % 24
                    prewarm_schedule.append({
                        "prewarm_at_utc_hour": prewarm_hour,
                        "peak_hour_utc": hour,
                        "query_density": round(count / max(total, 1), 3),
                    })

            return {
                "peak_hours_utc": peak_hours,
                "peak_days": peak_days,
                "prewarm_schedule": prewarm_schedule,
                "total_queries_analyzed": total,
            }
        except Exception as e:
            logger.warning("CodeCycleDetector: temporal clustering failed: %s", e)
            return {"status": "error", "error": str(e)}

    # ------------------------------------------------------------------
    # 4. Log Divergence Event
    # ------------------------------------------------------------------

    async def log_divergence(
        self,
        query: str,
        edge_response: str,
        sovereign_response: str,
        cosine_similarity: float,
        topic_tags: Optional[List[str]] = None,
    ):
        """
        Called by sovereign_chat_client after dual-brain comparison.
        Logs a divergence event when similarity < DIVERGENCE_THRESHOLD.
        """
        if cosine_similarity >= DIVERGENCE_THRESHOLD:
            return
        if not self._db_pool:
            return

        topic_label = ", ".join((topic_tags or [])[:5]) or query[:80]
        topic_hash = hashlib.sha256(topic_label.encode()).hexdigest()[:16]

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO code_divergence_log
                    (topic_hash, topic_label, query_text, cosine_similarity,
                     edge_provider, sovereign_provider)
                    VALUES ($1, $2, $3, $4, 'workers_ai', 'sovereign')
                """, topic_hash, topic_label, query[:500], cosine_similarity)
        except Exception as e:
            logger.warning("CodeCycleDetector: log_divergence failed: %s", e)

    # ------------------------------------------------------------------
    # 5. Build Pre-Warm Manifest
    # ------------------------------------------------------------------

    async def build_prewarm_manifest(self) -> Dict[str, Any]:
        """
        Combine divergence cycles, bug recurrence, and temporal data
        to produce a ranked list of crystals that should be pre-warmed.
        Writes manifest to R2 for the cron worker to consume.
        """
        if not self._db_pool:
            return {"status": "no_db"}

        divergence_cycles = await self.detect_divergence_cycles(days=30)
        bug_patterns = await self.detect_bug_recurrence(days=60)
        temporal = await self.detect_temporal_clusters(days=30)

        prewarm_topics = set()
        for cycle in divergence_cycles:
            prewarm_topics.add(cycle["topic_label"])
        for pattern in bug_patterns:
            prewarm_topics.add(pattern["tag"])

        if not prewarm_topics:
            logger.info("CodeCycleDetector: no patterns detected, using top-recall crystals")
            prewarm_topics = {"python", "fastapi", "flutter", "asyncpg", "postgresql"}

        crystal_ids = []
        try:
            async with self._db_pool.acquire() as conn:
                for topic in list(prewarm_topics)[:30]:
                    rows = await conn.fetch("""
                        SELECT id::text, crystal_text, confidence, recall_count
                        FROM nate_intelligence_crystals
                        WHERE domain = 'coding'
                          AND scope != 'archived'
                          AND superseded_by IS NULL
                          AND (crystal_text ILIKE '%' || $1 || '%'
                               OR $1 = ANY(topics))
                        ORDER BY recall_count DESC, confidence DESC
                        LIMIT 10
                    """, topic)

                    for row in rows:
                        crystal_ids.append({
                            "id": row["id"],
                            "text": row["crystal_text"][:2000],
                            "confidence": float(row["confidence"]),
                            "recall_count": row["recall_count"],
                            "topic": topic,
                        })
        except Exception as e:
            logger.warning("CodeCycleDetector: crystal query failed: %s", e)
            return {"status": "error", "error": str(e)}

        seen_ids = set()
        unique_crystals = []
        for c in sorted(crystal_ids, key=lambda x: x["recall_count"], reverse=True):
            if c["id"] not in seen_ids:
                seen_ids.add(c["id"])
                unique_crystals.append(c)
            if len(unique_crystals) >= MAX_PREWARM_CRYSTALS:
                break

        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "crystal_count": len(unique_crystals),
            "source_patterns": {
                "divergence_cycles": len(divergence_cycles),
                "bug_recurrences": len(bug_patterns),
                "temporal_clusters": len(temporal.get("prewarm_schedule", [])),
            },
            "crystals": unique_crystals,
        }

        if self._r2_storage:
            try:
                await asyncio.to_thread(
                    self._r2_storage.upload_bytes,
                    json.dumps(manifest).encode(),
                    PREWARM_MANIFEST_KEY,
                    content_type="application/json",
                )
                logger.info("CodeCycleDetector: wrote pre-warm manifest (%d crystals) to R2",
                            len(unique_crystals))
            except Exception as e:
                logger.warning("CodeCycleDetector: R2 manifest write failed: %s", e)

        await self._log_prewarm_event(manifest)
        return manifest

    # ------------------------------------------------------------------
    # 6. Log pre-warm activity
    # ------------------------------------------------------------------

    async def _log_prewarm_event(self, manifest: Dict):
        if not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO crystal_prewarm_log
                    (crystal_count, source_divergence, source_recurrence,
                     source_temporal, manifest_key)
                    VALUES ($1, $2, $3, $4, $5)
                """,
                    manifest["crystal_count"],
                    manifest["source_patterns"]["divergence_cycles"],
                    manifest["source_patterns"]["bug_recurrences"],
                    manifest["source_patterns"]["temporal_clusters"],
                    PREWARM_MANIFEST_KEY,
                )
        except Exception as e:
            logger.warning("CodeCycleDetector: prewarm log failed: %s", e)

    # ------------------------------------------------------------------
    # 7. Full analysis cycle (called by main.py schedule or admin API)
    # ------------------------------------------------------------------

    async def run_cycle(self) -> Dict[str, Any]:
        """Full detection + manifest build cycle."""
        result = {
            "divergence_cycles": await self.detect_divergence_cycles(),
            "bug_recurrences": await self.detect_bug_recurrence(),
            "temporal_clusters": await self.detect_temporal_clusters(),
        }
        result["manifest"] = await self.build_prewarm_manifest()
        return result
