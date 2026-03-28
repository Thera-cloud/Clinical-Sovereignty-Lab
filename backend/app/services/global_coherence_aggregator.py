"""
Global Coherence Aggregation Pipeline.

30-second cycle background agent that:
- Aggregates C_emo from active sessions (nevedal_metrics)
- Reads ODPE signal distribution (odpe_signal_log)
- Reads coherence layer scores (coherence_measurements)
- Computes anonymized GlobalCoherenceSnapshot
- Stores to Redis (hot path) and PostgreSQL (every 5 min)
- Publishes to MoQ global/coherence-aggregate via voice-edge worker

All snapshots are fully anonymized — no user IDs, session IDs, or
identifiable data. Only aggregate counts and metrics.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)

CYCLE_INTERVAL_S = 30
PERSIST_EVERY_N_CYCLES = 10  # every 5 min (10 × 30s)
ACTIVE_WINDOW_S = 300  # sessions active in last 5 min
REDIS_KEY = "nate:global:coherence:latest"
REDIS_TTL_S = 120


class GlobalCoherenceSnapshot:
    """Anonymized aggregate coherence state."""

    __slots__ = (
        "global_c_emo", "active_sessions", "active_users",
        "cee_density", "odpe_distribution", "layer_scores",
        "cycle_signals", "trend_1h", "trend_6h", "trend_24h",
        "timestamp",
    )

    def __init__(self):
        self.global_c_emo: float = 0.0
        self.active_sessions: int = 0
        self.active_users: int = 0
        self.cee_density: float = 0.0
        self.odpe_distribution: Dict[str, int] = {}
        self.layer_scores: Dict[str, float] = {}
        self.cycle_signals: Dict[str, Any] = {}
        self.trend_1h: Optional[float] = None
        self.trend_6h: Optional[float] = None
        self.trend_24h: Optional[float] = None
        self.timestamp: str = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "global_c_emo": round(self.global_c_emo, 5),
            "active_sessions": self.active_sessions,
            "active_users": self.active_users,
            "cee_density": round(self.cee_density, 5),
            "odpe_distribution": self.odpe_distribution,
            "layer_scores": {k: round(v, 5) for k, v in self.layer_scores.items()},
            "cycle_signals": self.cycle_signals,
            "trend_1h": round(self.trend_1h, 5) if self.trend_1h is not None else None,
            "trend_6h": round(self.trend_6h, 5) if self.trend_6h is not None else None,
            "trend_24h": round(self.trend_24h, 5) if self.trend_24h is not None else None,
            "timestamp": self.timestamp,
        }


class GlobalCoherenceAggregator:
    """
    Background agent running a 30-second aggregation loop.

    Reads from nevedal_metrics, odpe_signal_log, and coherence_measurements
    to produce an anonymized global coherence snapshot. Stores to Redis for
    sub-second API reads and to PostgreSQL every 5 minutes for history.
    """

    def __init__(
        self,
        db_pool=None,
        redis_client=None,
        coherence_engine=None,
        cycle_detection_engine=None,
    ):
        self._db_pool = db_pool
        self._redis = redis_client
        self._coherence_engine = coherence_engine
        self._cycle_detection_engine = cycle_detection_engine
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cycle_count = 0
        self._moq_publish_url = os.getenv(
            "MOQ_COHERENCE_PUBLISH_URL",
            "https://api.sovereignsanctuary.net/api/voice/moq/publish-coherence",
        )
        self._moq_hmac_secret = os.getenv("COHERENCE_HMAC_SECRET", "")

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(">>> [GLOBAL_COHERENCE] Aggregator started (cycle=%ds)", CYCLE_INTERVAL_S)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(">>> [GLOBAL_COHERENCE] Aggregator stopped")

    async def _run_loop(self):
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("GLOBAL_COHERENCE: cycle error: %s", e)
            await asyncio.sleep(CYCLE_INTERVAL_S)

    async def _tick(self):
        self._cycle_count += 1
        snapshot = await self._compute_snapshot()

        await self._store_redis(snapshot)

        if self._cycle_count % PERSIST_EVERY_N_CYCLES == 0:
            await self._persist_snapshot(snapshot)

        await self._publish_moq(snapshot)

    # ─── Data Gathering ────────────────────────────────────────

    async def _compute_snapshot(self) -> GlobalCoherenceSnapshot:
        snap = GlobalCoherenceSnapshot()

        if not self._db_pool:
            return snap

        try:
            async with self._db_pool.acquire() as conn:
                # Active sessions: C_emo from nevedal_metrics in the last 5 min
                active = await conn.fetch(f"""
                    SELECT
                        COUNT(DISTINCT session_id) AS session_count,
                        COUNT(DISTINCT user_id)    AS user_count,
                        AVG(c_emo)                 AS avg_c_emo,
                        SUM(CASE WHEN cee_window THEN 1 ELSE 0 END)::float
                            / GREATEST(COUNT(*), 1) AS cee_ratio
                    FROM nevedal_metrics
                    WHERE recorded_at > NOW() - INTERVAL '{ACTIVE_WINDOW_S} seconds'
                """)
                if active and active[0]["avg_c_emo"] is not None:
                    row = active[0]
                    snap.active_sessions = row["session_count"] or 0
                    snap.active_users = row["user_count"] or 0
                    snap.global_c_emo = float(row["avg_c_emo"])
                    snap.cee_density = float(row["cee_ratio"])

                # ODPE signal distribution from the last 5 min
                odpe_rows = await conn.fetch(f"""
                    SELECT dominant_signal, COUNT(*) AS cnt
                    FROM odpe_signal_log
                    WHERE created_at > NOW() - INTERVAL '{ACTIVE_WINDOW_S} seconds'
                    GROUP BY dominant_signal
                """)
                snap.odpe_distribution = {
                    r["dominant_signal"]: r["cnt"] for r in odpe_rows
                }

                # Coherence layer scores (latest per layer)
                layer_rows = await conn.fetch("""
                    SELECT DISTINCT ON (layer) layer, score
                    FROM coherence_measurements
                    ORDER BY layer, measured_at DESC
                """)
                snap.layer_scores = {
                    r["layer"]: float(r["score"]) for r in layer_rows
                }

                # Trend computation: compare current avg vs 1h/6h/24h ago
                snap.trend_1h = await self._compute_trend(conn, 3600, snap.global_c_emo)
                snap.trend_6h = await self._compute_trend(conn, 21600, snap.global_c_emo)
                snap.trend_24h = await self._compute_trend(conn, 86400, snap.global_c_emo)

        except Exception as e:
            logger.warning("GLOBAL_COHERENCE: snapshot computation error: %s", e)

        # Cycle signals from CycleDetectionEngine (if available)
        if self._cycle_detection_engine:
            try:
                pop_signals = getattr(
                    self._cycle_detection_engine, "get_population_signals", None
                )
                if pop_signals:
                    snap.cycle_signals = await pop_signals() if asyncio.iscoroutinefunction(pop_signals) else pop_signals()
            except Exception:
                pass

        snap.timestamp = datetime.now(timezone.utc).isoformat()
        return snap

    async def _compute_trend(
        self, conn, seconds_ago: int, current_c_emo: float,
    ) -> Optional[float]:
        """Compare current global C_emo against a prior window."""
        try:
            row = await conn.fetchrow(f"""
                SELECT AVG(global_c_emo) AS past_avg
                FROM global_coherence_snapshots
                WHERE captured_at BETWEEN
                    NOW() - INTERVAL '{seconds_ago + 300} seconds'
                    AND NOW() - INTERVAL '{seconds_ago} seconds'
            """)
            if row and row["past_avg"] is not None:
                return current_c_emo - float(row["past_avg"])
        except Exception:
            pass
        return None

    # ─── Storage ───────────────────────────────────────────────

    async def _store_redis(self, snapshot: GlobalCoherenceSnapshot):
        """Write snapshot to Redis for sub-second API reads."""
        if not self._redis:
            return
        try:
            payload = json.dumps(snapshot.to_dict())
            await self._redis.setex(REDIS_KEY, REDIS_TTL_S, payload)
        except Exception as e:
            logger.debug("GLOBAL_COHERENCE: Redis write skipped: %s", e)

    async def _persist_snapshot(self, snapshot: GlobalCoherenceSnapshot):
        """Write snapshot to PostgreSQL (every 5 min)."""
        if not self._db_pool:
            return
        try:
            d = snapshot.to_dict()
            async with self._db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO global_coherence_snapshots
                        (global_c_emo, active_sessions, active_users,
                         cee_density, odpe_distribution, layer_scores,
                         cycle_signals, trend_1h, trend_6h, trend_24h, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                    d["global_c_emo"],
                    d["active_sessions"],
                    d["active_users"],
                    d["cee_density"],
                    json.dumps(d["odpe_distribution"]),
                    json.dumps(d["layer_scores"]),
                    json.dumps(d["cycle_signals"]),
                    d["trend_1h"],
                    d["trend_6h"],
                    d["trend_24h"],
                    json.dumps({"cycle": self._cycle_count}),
                )
        except Exception as e:
            logger.warning("GLOBAL_COHERENCE: PostgreSQL persist error: %s", e)

    # ─── MoQ Publishing ───────────────────────────────────────

    async def _publish_moq(self, snapshot: GlobalCoherenceSnapshot):
        """Publish anonymized snapshot to voice-edge worker for MoQ fan-out."""
        if not self._moq_publish_url:
            return
        try:
            payload = snapshot.to_dict()
            body_bytes = json.dumps(payload, separators=(",", ":")).encode()
            headers = {"Content-Type": "application/json"}
            if self._moq_hmac_secret:
                sig = hmac.new(
                    self._moq_hmac_secret.encode(),
                    body_bytes,
                    hashlib.sha256,
                ).hexdigest()
                headers["X-Coherence-Signature"] = sig
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._moq_publish_url,
                    data=body_bytes,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status not in (200, 201):
                        logger.warning(
                            "GLOBAL_COHERENCE: MoQ publish returned %d", resp.status
                        )
        except Exception as e:
            logger.debug("GLOBAL_COHERENCE: MoQ publish skipped: %s", e)

    # ─── Public Read (for API fallback) ────────────────────────

    async def get_latest_snapshot(self) -> Optional[Dict[str, Any]]:
        """Read latest snapshot from Redis, fall back to PostgreSQL."""
        if self._redis:
            try:
                raw = await self._redis.get(REDIS_KEY)
                if raw:
                    return json.loads(raw)
            except Exception as e:
                logger.warning("GlobalCoherenceAggregator: Redis read failed: %s", e)

        if self._db_pool:
            try:
                async with self._db_pool.acquire() as conn:
                    row = await conn.fetchrow("""
                        SELECT global_c_emo, active_sessions, active_users,
                               cee_density, odpe_distribution, layer_scores,
                               cycle_signals, trend_1h, trend_6h, trend_24h,
                               captured_at
                        FROM global_coherence_snapshots
                        ORDER BY captured_at DESC LIMIT 1
                    """)
                    if row:
                        return {
                            "global_c_emo": float(row["global_c_emo"]),
                            "active_sessions": row["active_sessions"],
                            "active_users": row["active_users"],
                            "cee_density": float(row["cee_density"]),
                            "odpe_distribution": json.loads(row["odpe_distribution"])
                                if isinstance(row["odpe_distribution"], str)
                                else row["odpe_distribution"],
                            "layer_scores": json.loads(row["layer_scores"])
                                if isinstance(row["layer_scores"], str)
                                else row["layer_scores"],
                            "cycle_signals": json.loads(row["cycle_signals"])
                                if isinstance(row["cycle_signals"], str)
                                else row["cycle_signals"],
                            "trend_1h": float(row["trend_1h"]) if row["trend_1h"] else None,
                            "trend_6h": float(row["trend_6h"]) if row["trend_6h"] else None,
                            "trend_24h": float(row["trend_24h"]) if row["trend_24h"] else None,
                            "timestamp": row["captured_at"].isoformat(),
                        }
            except Exception as e:
                logger.warning("GlobalCoherenceAggregator: DB fallback read failed: %s", e)
        return None
