from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.services.coherence_time_crystal import CoherenceTimeCrystal

logger = logging.getLogger(__name__)


class TimeCrystalForge:
    """Detects recurring co-activation patterns and forges coherence time crystals."""

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def forge_for_user(self, user_id: str) -> List[CoherenceTimeCrystal]:
        if not self.db_pool:
            return []
        recalls = await self._get_recall_history(user_id)
        if len(recalls) < 6:
            return []

        clusters = self._find_co_activations(recalls)
        forged: List[CoherenceTimeCrystal] = []
        for crystal_ids, timestamps in clusters:
            periodicity = self._detect_periodicity(timestamps)
            if not periodicity:
                continue
            if periodicity["confidence"] < 0.60:
                continue

            tc = CoherenceTimeCrystal(
                user_id=user_id,
                crystal_ids=crystal_ids,
                period_days=periodicity["period_days"],
                phase_offset_days=periodicity["phase_offset"],
                temporal_confidence=periodicity["confidence"],
                next_activation_at=datetime.now(timezone.utc),
                synthesized_meaning=await self._synthesize_meaning(crystal_ids),
            )
            tc.next_activation_at = tc.predict_next_activation()
            await self._store_time_crystal(tc)
            forged.append(tc)
        return forged

    async def forge_all_users(self) -> Dict[str, int]:
        if not self.db_pool:
            return {"users_processed": 0, "time_crystals_forged": 0}
        users_processed = 0
        forged_total = 0
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT user_id
                FROM crystal_recall_log
                WHERE user_id IS NOT NULL AND user_id != ''
                """
            )
        for row in rows:
            user_id = str(row["user_id"])
            try:
                forged = await self.forge_for_user(user_id)
                users_processed += 1
                forged_total += len(forged)
            except Exception as exc:
                logger.warning("TimeCrystalForge failed for user=%s: %s", user_id, exc)
        return {"users_processed": users_processed, "time_crystals_forged": forged_total}

    async def _get_recall_history(self, user_id: str) -> List[Dict[str, Any]]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT crystal_hash, crystal_id, recalled_at, session_id, call_sid
                FROM crystal_recall_log
                WHERE user_id = $1
                  AND recalled_at > NOW() - INTERVAL '90 days'
                ORDER BY recalled_at ASC
                """,
                user_id,
            )
        out: List[Dict[str, Any]] = []
        for r in rows:
            crystal_key = str(r["crystal_hash"] or r["crystal_id"] or "")
            if not crystal_key:
                continue
            out.append(
                {
                    "crystal_key": crystal_key,
                    "recalled_at": r["recalled_at"],
                    "session_id": r["session_id"],
                    "call_sid": r["call_sid"],
                }
            )
        return out

    def _find_co_activations(self, recalls: List[Dict[str, Any]]) -> List[Tuple[List[str], List[datetime]]]:
        windows: Dict[str, List[Dict[str, Any]]] = {}
        for rec in recalls:
            sid = rec.get("session_id") or rec.get("call_sid")
            if sid:
                key = f"sid:{sid}"
            else:
                bucket = rec["recalled_at"].replace(minute=(rec["recalled_at"].minute // 10) * 10, second=0, microsecond=0)
                key = f"bucket:{bucket.isoformat()}"
            windows.setdefault(key, []).append(rec)

        pair_counts: Dict[Tuple[str, str], int] = {}
        pair_times: Dict[Tuple[str, str], List[datetime]] = {}
        for records in windows.values():
            crystal_keys = sorted({r["crystal_key"] for r in records})
            if len(crystal_keys) < 2:
                continue
            ts = min(r["recalled_at"] for r in records)
            for i, a in enumerate(crystal_keys):
                for b in crystal_keys[i + 1 :]:
                    pair = (a, b)
                    pair_counts[pair] = pair_counts.get(pair, 0) + 1
                    pair_times.setdefault(pair, []).append(ts)

        out: List[Tuple[List[str], List[datetime]]] = []
        for pair, count in pair_counts.items():
            if count >= 3:
                out.append(([pair[0], pair[1]], pair_times[pair]))
        return out

    def _detect_periodicity(self, timestamps: List[datetime]) -> Optional[Dict[str, float]]:
        if len(timestamps) < 3:
            return None
        ordered = sorted(timestamps)
        intervals = []
        for i in range(1, len(ordered)):
            days = (ordered[i] - ordered[i - 1]).total_seconds() / 86400.0
            if 3.0 <= days <= 400.0:
                intervals.append(days)
        if len(intervals) < 2:
            return None
        mean_interval = sum(intervals) / len(intervals)
        variance = sum((x - mean_interval) ** 2 for x in intervals) / len(intervals)
        std_dev = math.sqrt(variance)
        cv = std_dev / mean_interval if mean_interval > 0 else 1.0
        if cv >= 0.30:
            return None
        days_since_last = (datetime.now(timezone.utc) - ordered[-1]).total_seconds() / 86400.0
        phase = days_since_last % mean_interval
        confidence = min(0.90, 0.50 + (0.10 * len(intervals)) - (cv * 0.50))
        return {"period_days": round(mean_interval, 2), "phase_offset": round(phase, 2), "confidence": round(confidence, 3)}

    async def _synthesize_meaning(self, crystal_keys: List[str]) -> str:
        if not self.db_pool:
            return "Recurring recall pattern detected."
        ids = []
        for k in crystal_keys:
            if k.isdigit():
                ids.append(int(k))
        if not ids:
            return "Recurring recall pattern detected."
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT crystal_text
                FROM nate_intelligence_crystals
                WHERE id = ANY($1::int[])
                ORDER BY confidence DESC
                LIMIT 3
                """,
                ids,
            )
        snippets = [str(r["crystal_text"])[:80] for r in rows if r.get("crystal_text")]
        if not snippets:
            return "Recurring recall pattern detected."
        return "Recurring activation: " + " | ".join(snippets)

    async def _store_time_crystal(self, tc: CoherenceTimeCrystal) -> None:
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO coherence_time_crystals
                    (user_id, crystal_ids, period_days, phase_offset_days, next_activation_at,
                     temporal_confidence, activation_count, total_predictions, prediction_accuracy,
                     synthesized_meaning, therapeutic_implication, signal, last_activation_at, updated_at)
                VALUES
                    ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW())
                """,
                tc.user_id,
                tc.crystal_ids,
                tc.period_days,
                tc.phase_offset_days,
                tc.next_activation_at,
                tc.temporal_confidence,
                tc.activation_count,
                tc.total_predictions,
                tc.prediction_accuracy,
                tc.synthesized_meaning,
                tc.therapeutic_implication,
                tc.signal,
                tc.last_activation_at,
            )
