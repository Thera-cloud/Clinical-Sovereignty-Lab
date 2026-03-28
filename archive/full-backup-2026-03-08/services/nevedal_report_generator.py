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
            # Fetch metrics over the period
            rows = await conn.fetch(
                """SELECT c_emo, p_ent, cee_window, cee_duration_seconds,
                          biometrics, recorded_at
                   FROM nevedal_metrics
                   WHERE user_id = $1 AND recorded_at > NOW() - ($2 || ' days')::interval
                   ORDER BY recorded_at""",
                user_id, str(days),
            )

            # User info
            user = await conn.fetchrow(
                "SELECT name, role, family_id FROM users WHERE id = $1", user_id
            )

        if not rows:
            return {"report_type": "individual_coherence", "user_id": str(user_id),
                    "status": "no_data", "period_days": days}

        c_emo_values = [float(r["c_emo"] or 0) for r in rows]
        cee_count = sum(1 for r in rows if r["cee_window"])

        avg_c_emo = sum(c_emo_values) / len(c_emo_values)
        max_c_emo = max(c_emo_values)
        min_c_emo = min(c_emo_values)

        # Trend: compare first half to second half
        mid = len(c_emo_values) // 2
        first_half_avg = sum(c_emo_values[:mid]) / max(mid, 1)
        second_half_avg = sum(c_emo_values[mid:]) / max(len(c_emo_values) - mid, 1)
        trend_direction = "improving" if second_half_avg > first_half_avg + 0.02 else (
            "declining" if second_half_avg < first_half_avg - 0.02 else "stable"
        )

        # Weekly averages for charting
        weekly = self._group_by_week(rows, "c_emo")

        return {
            "report_type": "individual_coherence",
            "user_id": str(user_id),
            "user_name": user["name"] if user else None,
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_measurements": len(rows),
                "avg_c_emo": round(avg_c_emo, 4),
                "max_c_emo": round(max_c_emo, 4),
                "min_c_emo": round(min_c_emo, 4),
                "cee_events": cee_count,
                "trend": trend_direction,
                "trend_change": round(second_half_avg - first_half_avg, 4),
            },
            "weekly_averages": weekly,
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
            rows = await conn.fetch(
                """SELECT c_emo, cee_window, cee_duration_seconds, recorded_at
                   FROM nevedal_metrics
                   WHERE user_id = $1 AND recorded_at > NOW() - ($2 || ' days')::interval
                   ORDER BY recorded_at""",
                user_id, str(days),
            )
            name = await conn.fetchval("SELECT name FROM users WHERE id = $1", user_id)

        if not rows:
            return {"report_type": "longitudinal_trends", "status": "no_data"}

        weekly = self._group_by_week(rows, "c_emo")
        c_emo_values = [float(r["c_emo"] or 0) for r in rows]

        # Linear regression (simple)
        n = len(c_emo_values)
        if n >= 2:
            x_mean = (n - 1) / 2
            y_mean = sum(c_emo_values) / n
            num = sum((i - x_mean) * (c_emo_values[i] - y_mean) for i in range(n))
            den = sum((i - x_mean) ** 2 for i in range(n))
            slope = num / den if den != 0 else 0
            r_squared = (num ** 2) / (den * sum((y - y_mean) ** 2 for y in c_emo_values)) if den != 0 and sum((y - y_mean) ** 2 for y in c_emo_values) != 0 else 0
        else:
            slope = 0
            r_squared = 0

        # CEE frequency by week
        cee_rows = [r for r in rows if r["cee_window"]]
        cee_weekly = self._group_by_week(cee_rows, "cee_duration_seconds", agg="count")

        return {
            "report_type": "longitudinal_trends",
            "user_id": str(user_id),
            "user_name": name,
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "statistics": {
                "total_measurements": n,
                "mean_c_emo": round(sum(c_emo_values) / n, 4),
                "std_dev": round(math.sqrt(sum((v - sum(c_emo_values) / n) ** 2 for v in c_emo_values) / max(n - 1, 1)), 4),
                "slope_per_measurement": round(slope, 6),
                "r_squared": round(r_squared, 4),
                "total_cees": len(cee_rows),
            },
            "weekly_c_emo": weekly,
            "weekly_cee_count": cee_weekly,
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
