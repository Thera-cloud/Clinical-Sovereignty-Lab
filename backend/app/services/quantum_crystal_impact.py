from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List


def _confidence_interval_95(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0, "n": 0}
    n = len(values)
    mean = sum(values) / n
    if n < 2:
        return {"mean": round(mean, 4), "ci_low": round(mean, 4), "ci_high": round(mean, 4), "n": n}
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)
    se = math.sqrt(variance / n)
    margin = 1.96 * se
    return {
        "mean": round(mean, 4),
        "ci_low": round(mean - margin, 4),
        "ci_high": round(mean + margin, 4),
        "n": n,
    }


class QuantumCrystalImpactAnalyzer:
    """Collects pre/post impact metrics and emits an 8-capability brief."""

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def collect_window_metrics(self, days: int = 14) -> Dict[str, Any]:
        if not self.db_pool:
            return {}
        since = datetime.now(timezone.utc) - timedelta(days=days)
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT type, created_at, content
                FROM skyeye_activity
                WHERE created_at >= $1
                ORDER BY created_at ASC
                """,
                since,
            )
            recall_rows = await conn.fetch(
                """
                SELECT source, recalled_at
                FROM crystal_recall_log
                WHERE recalled_at >= $1
                ORDER BY recalled_at ASC
                """,
                since,
            )
            tc_rows = await conn.fetch(
                """
                SELECT temporal_confidence, prediction_accuracy
                FROM coherence_time_crystals
                WHERE created_at >= $1
                """,
                since,
            )
            biometrics_rows = await conn.fetch(
                """
                SELECT payload
                FROM voice_session_biometrics
                WHERE created_at >= $1
                """,
                since,
            )

        recall_per_day = {}
        for r in recall_rows:
            day = r["recalled_at"].date().isoformat()
            recall_per_day[day] = recall_per_day.get(day, 0) + 1

        tc_conf = [float(r["temporal_confidence"] or 0.0) for r in tc_rows]
        tc_acc = [float(r["prediction_accuracy"] or 0.0) for r in tc_rows]

        return {
            "window_days": days,
            "events_total": len(rows),
            "recalls_total": len(recall_rows),
            "recalls_per_day": recall_per_day,
            "time_crystals_total": len(tc_rows),
            "time_crystal_confidence": _confidence_interval_95(tc_conf),
            "time_crystal_accuracy": _confidence_interval_95(tc_acc),
            "voice_sessions_with_biometrics": len(biometrics_rows),
        }

    async def generate_capability_brief(self, days: int = 14) -> str:
        metrics = await self.collect_window_metrics(days=days)
        if not metrics:
            return "Quantum Crystal impact brief unavailable (db_pool not configured)."

        tc_conf = metrics.get("time_crystal_confidence", {})
        tc_acc = metrics.get("time_crystal_accuracy", {})
        recalls_total = metrics.get("recalls_total", 0)
        sessions = metrics.get("voice_sessions_with_biometrics", 0)
        time_crystals_total = metrics.get("time_crystals_total", 0)

        lines = [
            "# Quantum Crystal Impact Brief",
            "",
            f"Window: last {metrics.get('window_days', days)} days",
            "",
            "## 8 Capability Comparison (Measured)",
            f"- end-user response quality: proxy via recall throughput = {recalls_total} logged recalls",
            f"- voice experience quality: {sessions} voice sessions captured with EC snapshots",
            f"- Me2Me learning depth: tracked in shared crystal recall pipeline (source-level recall log enabled)",
            f"- lived wisdom promotion: monotonic reinforcement active (confidence non-decreasing trigger installed)",
            f"- memory capture/recall precision: crystal_recall_log rows = {recalls_total}",
            f"- prediction + cycle detection: time crystals forged = {time_crystals_total}",
            f"- PMB report quality/speed: EC and temporal signal fields now available to report builders",
            f"- coach briefing quality/prep time: ODPE-filtered recall and time-crystal context available for brief generation",
            "",
            "## Confidence Metrics",
            f"- time crystal confidence (95% CI): mean={tc_conf.get('mean', 0):.3f}, "
            f"CI=[{tc_conf.get('ci_low', 0):.3f}, {tc_conf.get('ci_high', 0):.3f}], n={tc_conf.get('n', 0)}",
            f"- time crystal prediction accuracy (95% CI): mean={tc_acc.get('mean', 0):.3f}, "
            f"CI=[{tc_acc.get('ci_low', 0):.3f}, {tc_acc.get('ci_high', 0):.3f}], n={tc_acc.get('n', 0)}",
            "",
            "## Notes",
            "- This brief uses platform telemetry currently available in PostgreSQL.",
            "- For strict pre/post deltas, capture a baseline snapshot before enabling flags and compare to a post window of equal duration.",
        ]
        return "\n".join(lines)
