"""
SOVEREIGN SWARM — Nevedal Report Generator
Generates 5 report types from nevedal_metrics, coherence_measurements,
and session data per SC_07 (Nevedal Research Laboratory) specification.

Report Types:
    1. individual_coherence  — Single user C_emo trends, CEE events, biometric summary
    2. dyad_comparison       — Coach-client synchrony, correlation, shared CEE moments
    3. family_dynamics        — Multi-member coherence matrix, family wellness index
    4. longitudinal_trends   — 12-week C_emo trend with statistical analysis
    5. coach_efficacy        — Coach effectiveness across clients
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID


class NevedalReportGenerator:
    """Generates structured research reports from Nevedal data."""

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def generate(
        self,
        report_type: str,
        subject_ids: List[UUID],
        date_range_days: int = 84,  # default 12 weeks
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Dispatch to the correct report generator.
        Returns a structured report dictionary.
        """
        generators = {
            "individual_coherence": self._individual_coherence,
            "dyad_comparison": self._dyad_comparison,
            "family_dynamics": self._family_dynamics,
            "longitudinal_trends": self._longitudinal_trends,
            "coach_efficacy": self._coach_efficacy,
        }
        gen = generators.get(report_type)
        if not gen:
            return {"error": f"Unknown report type: {report_type}",
                    "available": list(generators.keys())}

        return await gen(subject_ids, date_range_days, **kwargs)

    # ─── 1. Individual Coherence Report ──────────────────────────────────

    async def _individual_coherence(
        self, subject_ids: List[UUID], days: int, **kw
    ) -> Dict[str, Any]:
        user_id = subject_ids[0] if subject_ids else None
        if not user_id:
            return {"error": "user_id required"}

        async with self.db_pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT name, role, family_id FROM users WHERE id = $1", user_id
            )
            weekly_or_raw = await conn.fetch(
                self._WEEKLY_C_EMO_SQL, user_id, int(days),
            )
            stats = None
            if not self._looks_like_raw_metric_rows(weekly_or_raw):
                stats = await conn.fetchrow(
                    self._METRICS_SUMMARY_SQL, user_id, int(days),
                )

        if self._looks_like_raw_metric_rows(weekly_or_raw):
            return self._individual_from_raw_rows(
                user_id, days, user, weekly_or_raw,
            )

        n = int((stats or {}).get("n") or 0)
        if n <= 0:
            return {
                "report_type": "individual_coherence",
                "user_id": str(user_id),
                "status": "no_data",
                "period_days": days,
            }

        first_half = self._num((stats or {}).get("first_half_avg"))
        second_half = self._num((stats or {}).get("second_half_avg"))
        trend_direction = self._trend_label(first_half, second_half)
        return {
            "report_type": "individual_coherence",
            "user_id": str(user_id),
            "user_name": user["name"] if user else None,
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_measurements": n,
                "avg_c_emo": round(self._num((stats or {}).get("avg_c_emo")), 4),
                "max_c_emo": round(self._num((stats or {}).get("max_c_emo")), 4),
                "min_c_emo": round(self._num((stats or {}).get("min_c_emo")), 4),
                "cee_events": int((stats or {}).get("cee_events") or 0),
                "trend": trend_direction,
                "trend_change": round(second_half - first_half, 4),
            },
            "weekly_averages": self._records_to_weekly(weekly_or_raw),
        }

    # ─── 2. Dyad Comparison Report ───────────────────────────────────────

    async def _dyad_comparison(
        self, subject_ids: List[UUID], days: int, **kw
    ) -> Dict[str, Any]:
        if len(subject_ids) < 2:
            return {"error": "Two subject_ids required (client + coach)"}

        subject_a, subject_b = subject_ids[0], subject_ids[1]

        async with self.db_pool.acquire() as conn:
            rows_a = await conn.fetch(
                """SELECT c_emo, cee_window, recorded_at FROM nevedal_metrics
                   WHERE user_id = $1 AND recorded_at > NOW() - ($2 || ' days')::interval
                   ORDER BY recorded_at""",
                subject_a, str(days),
            )
            rows_b = await conn.fetch(
                """SELECT c_emo, cee_window, recorded_at FROM nevedal_metrics
                   WHERE user_id = $1 AND recorded_at > NOW() - ($2 || ' days')::interval
                   ORDER BY recorded_at""",
                subject_b, str(days),
            )
            name_a = await conn.fetchval("SELECT name FROM users WHERE id = $1", subject_a)
            name_b = await conn.fetchval("SELECT name FROM users WHERE id = $1", subject_b)

        a_vals = [float(r["c_emo"] or 0) for r in rows_a]
        b_vals = [float(r["c_emo"] or 0) for r in rows_b]

        avg_a = sum(a_vals) / max(len(a_vals), 1)
        avg_b = sum(b_vals) / max(len(b_vals), 1)

        synchrony = 1.0 - abs(avg_a - avg_b)
        if synchrony >= 0.85:
            grade = "EXCELLENT"
        elif synchrony >= 0.70:
            grade = "GOOD"
        elif synchrony >= 0.55:
            grade = "MODERATE"
        else:
            grade = "DEVELOPING"

        # Shared CEE events (timestamps within 5 minutes of each other)
        a_cees = [r["recorded_at"] for r in rows_a if r["cee_window"]]
        b_cees = [r["recorded_at"] for r in rows_b if r["cee_window"]]
        shared_cees = 0
        for a_t in a_cees:
            for b_t in b_cees:
                if abs((a_t - b_t).total_seconds()) < 300:
                    shared_cees += 1
                    break

        return {
            "report_type": "dyad_comparison",
            "subject_a": {"id": str(subject_a), "name": name_a, "avg_c_emo": round(avg_a, 4)},
            "subject_b": {"id": str(subject_b), "name": name_b, "avg_c_emo": round(avg_b, 4)},
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "synchrony": {
                "score": round(synchrony, 4),
                "grade": grade,
                "shared_cee_events": shared_cees,
            },
            "weekly_a": self._group_by_week(rows_a, "c_emo"),
            "weekly_b": self._group_by_week(rows_b, "c_emo"),
        }

    # ─── 3. Family Dynamics Report ───────────────────────────────────────

    async def _family_dynamics(
        self, subject_ids: List[UUID], days: int, **kw
    ) -> Dict[str, Any]:
        family_id = kw.get("family_id") or (subject_ids[0] if subject_ids else None)
        if not family_id:
            return {"error": "family_id required"}

        async with self.db_pool.acquire() as conn:
            members = await conn.fetch(
                "SELECT id, name FROM users WHERE family_id = $1", family_id
            )
            if not members:
                return {"report_type": "family_dynamics", "status": "no_members"}

            member_data = {}
            for m in members:
                rows = await conn.fetch(
                    """SELECT c_emo FROM nevedal_metrics
                       WHERE user_id = $1 AND recorded_at > NOW() - ($2 || ' days')::interval""",
                    m["id"], str(days),
                )
                vals = [float(r["c_emo"] or 0) for r in rows]
                avg = sum(vals) / max(len(vals), 1) if vals else 0
                member_data[str(m["id"])] = {
                    "name": m["name"],
                    "avg_c_emo": round(avg, 4),
                    "measurements": len(vals),
                }

        # Pairwise coherence matrix
        ids = list(member_data.keys())
        matrix = {}
        for i, id_a in enumerate(ids):
            for id_b in ids[i + 1:]:
                pair_key = f"{id_a}:{id_b}"
                a_val = member_data[id_a]["avg_c_emo"]
                b_val = member_data[id_b]["avg_c_emo"]
                matrix[pair_key] = round(1.0 - abs(a_val - b_val), 4)

        # Family wellness index
        all_avgs = [d["avg_c_emo"] for d in member_data.values() if d["measurements"] > 0]
        wellness_index = round(sum(all_avgs) / max(len(all_avgs), 1), 4)

        return {
            "report_type": "family_dynamics",
            "family_id": str(family_id),
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "members": member_data,
            "coherence_matrix": matrix,
            "family_wellness_index": wellness_index,
            "member_count": len(member_data),
        }

    # ─── 4. Longitudinal Trends (12-week) ────────────────────────────────

    async def _longitudinal_trends(
        self, subject_ids: List[UUID], days: int, **kw
    ) -> Dict[str, Any]:
        user_id = subject_ids[0] if subject_ids else None
        if not user_id:
            return {"error": "user_id required"}

        days = max(days, 84)  # Minimum 12 weeks

        async with self.db_pool.acquire() as conn:
            name = await conn.fetchval("SELECT name FROM users WHERE id = $1", user_id)
            weekly_or_raw = await conn.fetch(
                self._WEEKLY_C_EMO_SQL, user_id, int(days),
            )
            stats_row = None
            cee_weekly_rows = []
            if not self._looks_like_raw_metric_rows(weekly_or_raw):
                stats_row = await conn.fetchrow(
                    self._METRICS_SUMMARY_SQL, user_id, int(days),
                )
                cee_weekly_rows = await conn.fetch(
                    self._WEEKLY_CEE_SQL, user_id, int(days),
                )

        if self._looks_like_raw_metric_rows(weekly_or_raw):
            return self._longitudinal_from_raw_rows(
                user_id, days, name, weekly_or_raw,
            )

        n = int((stats_row or {}).get("n") or 0)
        if n <= 0:
            return {"report_type": "longitudinal_trends", "status": "no_data"}

        weekly = self._records_to_weekly(weekly_or_raw)
        slope, r_squared = self._regression([self._num(w.get("avg")) for w in weekly])
        trend = (
            "improving"
            if slope > 0.0001
            else ("declining" if slope < -0.0001 else "stable")
        )
        stats = {
            "total_measurements": n,
            "mean_c_emo": round(self._num((stats_row or {}).get("avg_c_emo")), 4),
            "std_dev": round(self._num((stats_row or {}).get("std_dev")), 4),
            "slope_per_measurement": round(slope, 6),
            "r_squared": round(r_squared, 4),
            "total_cees": int((stats_row or {}).get("cee_events") or 0),
            "trend": trend,
        }
        return {
            "report_type": "longitudinal_trends",
            "user_id": str(user_id),
            "user_name": name,
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "statistics": stats,
            "summary": stats,
            "weekly_c_emo": weekly,
            "weekly_averages": weekly,
            "weekly_cee_count": self._records_to_weekly_counts(cee_weekly_rows),
        }

    # ─── 5. Coach Efficacy Analysis ──────────────────────────────────────

    async def _coach_efficacy(
        self, subject_ids: List[UUID], days: int, **kw
    ) -> Dict[str, Any]:
        coach_id = subject_ids[0] if subject_ids else None
        if not coach_id:
            return {"error": "coach_id required"}

        async with self.db_pool.acquire() as conn:
            coach = await conn.fetchrow(
                "SELECT name, role FROM users WHERE id = $1", coach_id
            )

            # Get all clients of this coach with sessions
            clients = await conn.fetch(
                """SELECT DISTINCT s.user_id, u.name
                   FROM sessions s
                   JOIN users u ON s.user_id = u.id
                   WHERE s.coach_id = $1
                     AND s.started_at > NOW() - ($2 || ' days')::interval""",
                coach_id, str(days),
            )

            client_results = []
            for client in clients:
                # Get C_emo before and after sessions with this coach
                first = await conn.fetchval(
                    """SELECT c_emo FROM nevedal_metrics
                       WHERE user_id = $1
                       ORDER BY recorded_at ASC LIMIT 1""",
                    client["user_id"],
                )
                latest = await conn.fetchval(
                    """SELECT c_emo FROM nevedal_metrics
                       WHERE user_id = $1
                       ORDER BY recorded_at DESC LIMIT 1""",
                    client["user_id"],
                )
                sessions_count = await conn.fetchval(
                    """SELECT COUNT(*) FROM sessions
                       WHERE user_id = $1 AND coach_id = $2""",
                    client["user_id"], coach_id,
                )
                cee_count = await conn.fetchval(
                    """SELECT COUNT(*) FROM nevedal_metrics
                       WHERE user_id = $1 AND cee_window = TRUE""",
                    client["user_id"],
                )

                first_val = float(first or 0)
                latest_val = float(latest or 0)
                improvement = latest_val - first_val

                client_results.append({
                    "client_id": str(client["user_id"]),
                    "client_name": client["name"],
                    "sessions": sessions_count or 0,
                    "initial_c_emo": round(first_val, 4),
                    "current_c_emo": round(latest_val, 4),
                    "improvement": round(improvement, 4),
                    "cee_events": cee_count or 0,
                })

        # Aggregate coach metrics
        total_improvement = sum(c["improvement"] for c in client_results)
        avg_improvement = total_improvement / max(len(client_results), 1)
        total_cees = sum(c["cee_events"] for c in client_results)

        return {
            "report_type": "coach_efficacy",
            "coach_id": str(coach_id),
            "coach_name": coach["name"] if coach else None,
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_clients": len(client_results),
                "avg_c_emo_improvement": round(avg_improvement, 4),
                "total_cee_events": total_cees,
                "clients_improved": sum(1 for c in client_results if c["improvement"] > 0),
                "clients_declined": sum(1 for c in client_results if c["improvement"] < 0),
            },
            "client_details": client_results,
        }

    # ─── Helpers ─────────────────────────────────────────────────────────

    _METRICS_SUMMARY_SQL = """
        SELECT COUNT(*)::int AS n,
               COALESCE(AVG(c_emo), 0) AS avg_c_emo,
               COALESCE(MAX(c_emo), 0) AS max_c_emo,
               COALESCE(MIN(c_emo), 0) AS min_c_emo,
               COUNT(*) FILTER (WHERE cee_window IS TRUE)::int AS cee_events,
               AVG(c_emo) FILTER (
                   WHERE recorded_at < NOW() - make_interval(days => $2 / 2)
               ) AS first_half_avg,
               AVG(c_emo) FILTER (
                   WHERE recorded_at >= NOW() - make_interval(days => $2 / 2)
               ) AS second_half_avg,
               COALESCE(STDDEV_SAMP(c_emo), 0) AS std_dev
        FROM nevedal_metrics
        WHERE user_id = $1
          AND recorded_at > NOW() - make_interval(days => $2)
    """

    _WEEKLY_C_EMO_SQL = """
        SELECT to_char(date_trunc('week', recorded_at), 'IYYY-"W"IW') AS week,
               ROUND(AVG(c_emo)::numeric, 4) AS avg,
               COUNT(*)::int AS count
        FROM nevedal_metrics
        WHERE user_id = $1
          AND recorded_at > NOW() - make_interval(days => $2)
        GROUP BY 1
        ORDER BY 1
    """

    _WEEKLY_CEE_SQL = """
        SELECT to_char(date_trunc('week', recorded_at), 'IYYY-"W"IW') AS week,
               COUNT(*)::int AS count
        FROM nevedal_metrics
        WHERE user_id = $1
          AND cee_window IS TRUE
          AND recorded_at > NOW() - make_interval(days => $2)
        GROUP BY 1
        ORDER BY 1
    """

    @staticmethod
    def _num(v: Any, default: float = 0.0) -> float:
        if v is None:
            return default
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _trend_label(first_half: float, second_half: float, eps: float = 0.02) -> str:
        if second_half > first_half + eps:
            return "improving"
        if second_half < first_half - eps:
            return "declining"
        return "stable"

    @staticmethod
    def _looks_like_raw_metric_row(row: Any) -> bool:
        try:
            keys = set(row.keys()) if hasattr(row, "keys") else set()
        except Exception:
            return False
        return "recorded_at" in keys and "c_emo" in keys

    @classmethod
    def _looks_like_raw_metric_rows(cls, rows: Any) -> bool:
        return bool(rows) and cls._looks_like_raw_metric_row(rows[0])

    def _individual_from_raw_rows(
        self, user_id, days: int, user, rows: List,
    ) -> Dict[str, Any]:
        if not rows:
            return {
                "report_type": "individual_coherence",
                "user_id": str(user_id),
                "status": "no_data",
                "period_days": days,
            }
        c_emo_values = [self._num(r["c_emo"]) for r in rows]
        cee_count = sum(1 for r in rows if r["cee_window"])
        avg_c_emo = sum(c_emo_values) / len(c_emo_values)
        mid = len(c_emo_values) // 2
        first_half_avg = sum(c_emo_values[:mid]) / max(mid, 1)
        second_half_avg = sum(c_emo_values[mid:]) / max(len(c_emo_values) - mid, 1)
        return {
            "report_type": "individual_coherence",
            "user_id": str(user_id),
            "user_name": user["name"] if user else None,
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_measurements": len(rows),
                "avg_c_emo": round(avg_c_emo, 4),
                "max_c_emo": round(max(c_emo_values), 4),
                "min_c_emo": round(min(c_emo_values), 4),
                "cee_events": cee_count,
                "trend": self._trend_label(first_half_avg, second_half_avg),
                "trend_change": round(second_half_avg - first_half_avg, 4),
            },
            "weekly_averages": self._group_by_week(rows, "c_emo"),
        }

    def _longitudinal_from_raw_rows(
        self, user_id, days: int, name, rows: List,
    ) -> Dict[str, Any]:
        if not rows:
            return {"report_type": "longitudinal_trends", "status": "no_data"}
        weekly = self._group_by_week(rows, "c_emo")
        c_emo_values = [self._num(r["c_emo"]) for r in rows]
        n = len(c_emo_values)
        slope, r_squared = self._regression(c_emo_values)
        cee_rows = [r for r in rows if r["cee_window"]]
        cee_weekly = self._group_by_week(cee_rows, "cee_duration_seconds", agg="count")
        trend = (
            "improving"
            if slope > 0.0001
            else ("declining" if slope < -0.0001 else "stable")
        )
        mean = sum(c_emo_values) / n
        stats = {
            "total_measurements": n,
            "mean_c_emo": round(mean, 4),
            "std_dev": round(
                math.sqrt(
                    sum((v - mean) ** 2 for v in c_emo_values) / max(n - 1, 1)
                ),
                4,
            ),
            "slope_per_measurement": round(slope, 6),
            "r_squared": round(r_squared, 4),
            "total_cees": len(cee_rows),
            "trend": trend,
        }
        return {
            "report_type": "longitudinal_trends",
            "user_id": str(user_id),
            "user_name": name,
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "statistics": stats,
            "summary": stats,
            "weekly_c_emo": weekly,
            "weekly_averages": weekly,
            "weekly_cee_count": cee_weekly,
        }

    @staticmethod
    def _regression(values: List[float]) -> tuple:
        n = len(values)
        if n < 2:
            return 0.0, 0.0
        x_mean = (n - 1) / 2
        y_mean = sum(values) / n
        num = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
        den = sum((i - x_mean) ** 2 for i in range(n))
        ss_y = sum((y - y_mean) ** 2 for y in values)
        slope = num / den if den != 0 else 0.0
        r_squared = (num ** 2) / (den * ss_y) if den != 0 and ss_y != 0 else 0.0
        return slope, r_squared

    def _records_to_weekly(self, rows: List) -> List[Dict[str, Any]]:
        if self._looks_like_raw_metric_rows(rows):
            return self._group_by_week(rows, "c_emo")
        result = []
        for r in rows or []:
            result.append({
                "week": str(r["week"]),
                "avg": round(self._num(r["avg"] if "avg" in r.keys() else 0), 4),
                "count": int(r["count"] or 0),
            })
        return result

    @staticmethod
    def _records_to_weekly_counts(rows: List) -> List[Dict[str, Any]]:
        result = []
        for r in rows or []:
            result.append({
                "week": str(r["week"]),
                "count": int(r["count"] or 0),
            })
        return result

    @staticmethod
    def _group_by_week(
        rows: List, field: str, agg: str = "avg"
    ) -> List[Dict[str, Any]]:
        """Group rows by ISO week and compute average or count of a field."""
        weeks: Dict[str, List[float]] = {}
        for r in rows:
            ts = r["recorded_at"]
            if ts:
                week_key = ts.strftime("%Y-W%W")
                weeks.setdefault(week_key, [])
                if agg == "count":
                    weeks[week_key].append(1)
                else:
                    weeks[week_key].append(float(r[field] or 0))

        result = []
        for week, vals in sorted(weeks.items()):
            if agg == "count":
                result.append({"week": week, "count": len(vals)})
            else:
                result.append({
                    "week": week,
                    "avg": round(sum(vals) / len(vals), 4),
                    "count": len(vals),
                })
        return result
