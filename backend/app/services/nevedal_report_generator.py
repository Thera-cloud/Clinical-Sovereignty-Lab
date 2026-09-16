"""
SOVEREIGN SWARM — Nevedal Report Generator
Generates 5 report types per SC_07 (Nevedal Research Laboratory).

Coach Insights instruments (must not overlap):
    1. individual_coherence  — PLATFORM metrics: C_emo level, range, CEE density
    4. longitudinal_trends   — INDUSTRY / Review Board Investigation packet:
       treatment-plan growth, anxiety/depression, dissatisfaction, dissociation,
       shame, blaming circumstances, cycle detections, transgenerational/PMB,
       Little Nate predictions + observed tactics + LN performance review.
       Does NOT reuse C_emo / CEE as its evidence.

RBI = Review Board Investigation (mental health board / institution), not a
C_emo reliability score. Each payload includes instrument, rbi, and
nate_scientific_insight so the coach can discuss both packets separately.

Other types:
    2. dyad_comparison       — Coach-client synchrony, correlation, shared CEE moments
    3. family_dynamics        — Multi-member coherence matrix, family wellness index
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
        return self._finalize_individual(
            user_id=user_id,
            days=days,
            user_name=user["name"] if user else None,
            n=n,
            avg_c_emo=self._num((stats or {}).get("avg_c_emo")),
            min_c_emo=self._num((stats or {}).get("min_c_emo")),
            max_c_emo=self._num((stats or {}).get("max_c_emo")),
            cee_events=int((stats or {}).get("cee_events") or 0),
            first_half=first_half,
            second_half=second_half,
            weekly=self._records_to_weekly(weekly_or_raw),
        )

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

        days = max(int(days or 0), 84)

        async with self.db_pool.acquire() as conn:
            user = await self._safe_fetchrow(
                conn,
                """SELECT id::text AS id,
                          COALESCE(name, profile_data->>'name') AS name,
                          username,
                          hardware_id,
                          family_id::text AS family_id
                   FROM users WHERE id = $1""",
                user_id,
            )
            identities = self._identity_keys(user, user_id)

            metrics = await self._safe_fetchrow(
                conn, self._CLIENT_INDUSTRY_SQL, user_id,
            )
            language = await self._safe_fetchrow(
                conn, self._INDUSTRY_LANGUAGE_SQL, identities, int(days),
            )
            cycles = await self._safe_fetch(
                conn, self._CYCLE_DETECTIONS_SQL, identities,
            )
            cycle_preds = await self._safe_fetch(
                conn, self._CYCLE_PREDICTIONS_SQL, identities,
            )
            tx_preds = await self._safe_fetch(
                conn, self._THERAPEUTIC_PREDICTIONS_SQL, identities, int(days),
            )
            habits = await self._safe_fetch(
                conn, self._HABIT_SQL, identities,
            )
            plans = await self._safe_fetch(
                conn, self._TREATMENT_PLAN_SQL, identities, int(days),
            )
            tg_catalog = await self._safe_fetch(conn, self._TG_CATALOG_SQL)
            nate_tactics = await self._safe_fetchrow(
                conn, self._NATE_TACTICS_SQL, identities, int(days),
            )

        packet = self._assemble_industry_packet(
            metrics=metrics,
            language=language,
            cycles=cycles,
            cycle_preds=cycle_preds,
            tx_preds=tx_preds,
            habits=habits,
            plans=plans,
            tg_catalog=tg_catalog,
            nate_tactics=nate_tactics,
        )
        if packet["evidence_count"] <= 0:
            return {"report_type": "longitudinal_trends", "status": "no_data"}

        return self._finalize_longitudinal(
            user_id=user_id,
            days=days,
            user_name=self._row_get(user, "name"),
            packet=packet,
        )

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

    _CLIENT_INDUSTRY_SQL = """
        SELECT anxiety_level, depression_indicators, stress_level,
               homework_completion_rate, breakthrough_count, mood_trend,
               shame_profile, pmb, crisis_perception, session_count,
               updated_at
        FROM client_metrics
        WHERE user_id = $1
        LIMIT 1
    """

    _INDUSTRY_LANGUAGE_SQL = """
        SELECT
            COUNT(*) FILTER (
                WHERE created_at < NOW() - make_interval(days => $2 / 2)
            )::int AS early_n,
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - make_interval(days => $2 / 2)
            )::int AS late_n,
            COUNT(*) FILTER (
                WHERE created_at < NOW() - make_interval(days => $2 / 2)
                  AND user_text ~* 'anxi|panic|worried|worry|overwhelm|restless'
            )::int AS early_anxiety,
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - make_interval(days => $2 / 2)
                  AND user_text ~* 'anxi|panic|worried|worry|overwhelm|restless'
            )::int AS late_anxiety,
            COUNT(*) FILTER (
                WHERE created_at < NOW() - make_interval(days => $2 / 2)
                  AND user_text ~* 'depress|hopeless|empty|worthless|no energy'
            )::int AS early_depression,
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - make_interval(days => $2 / 2)
                  AND user_text ~* 'depress|hopeless|empty|worthless|no energy'
            )::int AS late_depression,
            COUNT(*) FILTER (
                WHERE created_at < NOW() - make_interval(days => $2 / 2)
                  AND user_text ~* 'dissatisf|unsatisf|nothing works|fed up|pointless'
            )::int AS early_dissatisfaction,
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - make_interval(days => $2 / 2)
                  AND user_text ~* 'dissatisf|unsatisf|nothing works|fed up|pointless'
            )::int AS late_dissatisfaction,
            COUNT(*) FILTER (
                WHERE created_at < NOW() - make_interval(days => $2 / 2)
                  AND user_text ~* 'dissociat|numb|checked out|not real|brain fog|spaced out|detached'
            )::int AS early_dissociation,
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - make_interval(days => $2 / 2)
                  AND user_text ~* 'dissociat|numb|checked out|not real|brain fog|spaced out|detached'
            )::int AS late_dissociation,
            COUNT(*) FILTER (
                WHERE created_at < NOW() - make_interval(days => $2 / 2)
                  AND user_text ~* 'shame|ashamed|embarrass|humiliat'
            )::int AS early_shame,
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - make_interval(days => $2 / 2)
                  AND user_text ~* 'shame|ashamed|embarrass|humiliat'
            )::int AS late_shame,
            COUNT(*) FILTER (
                WHERE created_at < NOW() - make_interval(days => $2 / 2)
                  AND user_text ~* 'blame|their fault|they made me|because of them'
            )::int AS early_blaming,
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - make_interval(days => $2 / 2)
                  AND user_text ~* 'blame|their fault|they made me|because of them'
            )::int AS late_blaming
        FROM conversation_history
        WHERE user_id = ANY($1::text[])
          AND created_at > NOW() - make_interval(days => $2)
    """

    _CYCLE_DETECTIONS_SQL = """
        SELECT domain, detected_period_days, amplitude, confidence, method,
               detected_at
        FROM cycle_detections
        WHERE user_id = ANY($1::text[])
          AND detected_at > NOW() - INTERVAL '30 days'
        ORDER BY confidence DESC
        LIMIT 24
    """

    _CYCLE_PREDICTIONS_SQL = """
        SELECT domain, predicted_event, predicted_at, confidence,
               intervention_window_start, intervention_window_end,
               convergence_risk, status, actual_outcome
        FROM cycle_predictions
        WHERE user_id = ANY($1::text[])
          AND created_at > NOW() - INTERVAL '30 days'
        ORDER BY predicted_at DESC
        LIMIT 16
    """

    _THERAPEUTIC_PREDICTIONS_SQL = """
        SELECT prediction_type, goal_type, success_probability, confidence_score,
               accuracy_score, optimal_intervention_plan, key_amplifiers,
               key_resistances, created_at
        FROM therapeutic_predictions
        WHERE user_id = ANY($1::text[])
          AND created_at > NOW() - make_interval(days => $2)
        ORDER BY created_at DESC
        LIMIT 12
    """

    _HABIT_SQL = """
        SELECT habit_type, habit_description, status, current_streak,
               longest_streak, total_completions, total_misses,
               predicted_maintenance_probability
        FROM therapeutic_habit_tracking
        WHERE user_id = ANY($1::text[])
        ORDER BY updated_at DESC
        LIMIT 12
    """

    _TREATMENT_PLAN_SQL = """
        SELECT record_id, record_type, LEFT(content, 280) AS excerpt,
               coach_reviewed, created_at
        FROM clinical_records
        WHERE user_id = ANY($1::text[])
          AND record_type = 'treatment_plan'
          AND created_at > NOW() - make_interval(days => $2)
        ORDER BY created_at DESC
        LIMIT 8
    """

    _TG_CATALOG_SQL = """
        SELECT pattern_name, description, confidence, effect_size,
               families_observed, early_indicators
        FROM transgenerational_patterns
        WHERE anonymization_verified IS TRUE
        ORDER BY confidence DESC NULLS LAST
        LIMIT 6
    """

    _NATE_TACTICS_SQL = """
        SELECT
            COUNT(*)::int AS replies,
            COUNT(*) FILTER (WHERE ai_text ~* 'i hear|i''m with you|sit with|hold (the )?space')::int AS witness,
            COUNT(*) FILTER (WHERE ai_text ~* 'breath|body|ground|somatic|in your chest')::int AS somatic,
            COUNT(*) FILTER (WHERE ai_text ~* 'notice how|pause|slow down|interrupt')::int AS interrupt,
            COUNT(*) FILTER (WHERE ai_text ~* 'pattern|cycle|this keeps|comes around')::int AS cycle_naming,
            COUNT(*) FILTER (WHERE ai_text ~* 'when this (shows|comes)|i expect|likely to')::int AS prediction,
            COUNT(*) FILTER (WHERE ai_text ~* 'what''s coming up|what is that like|stay with')::int AS redirect
        FROM conversation_history
        WHERE user_id = ANY($1::text[])
          AND created_at > NOW() - make_interval(days => $2)
          AND COALESCE(ai_text, '') <> ''
    """

    _CYCLE_LABELS = {
        "addiction": "Addiction",
        "sexual_desire": "Sexual desire",
        "harm_risk": "Harm risk",
        "emotional_state": "Emotional state",
        "financial": "Financial",
        "coping": "Coping",
        "economic": "Economic",
        "cultural": "Cultural / religious",
        "group_dynamics": "Group dynamics",
        "legacy": "Legacy / transgenerational",
        "healing": "Healing",
        "pornography": "Pornography",
        "code_learning": "Code learning",
        "pgsd_field": "PGSD field",
    }

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
        mid = len(c_emo_values) // 2
        first_half_avg = sum(c_emo_values[:mid]) / max(mid, 1)
        second_half_avg = sum(c_emo_values[mid:]) / max(len(c_emo_values) - mid, 1)
        return self._finalize_individual(
            user_id=user_id,
            days=days,
            user_name=user["name"] if user else None,
            n=len(rows),
            avg_c_emo=sum(c_emo_values) / len(c_emo_values),
            min_c_emo=min(c_emo_values),
            max_c_emo=max(c_emo_values),
            cee_events=sum(1 for r in rows if r["cee_window"]),
            first_half=first_half_avg,
            second_half=second_half_avg,
            weekly=self._group_by_week(rows, "c_emo"),
        )

    @staticmethod
    async def _safe_fetch(conn, sql: str, *args) -> List:
        try:
            return list(await conn.fetch(sql, *args) or [])
        except Exception:
            return []

    @staticmethod
    async def _safe_fetchrow(conn, sql: str, *args):
        try:
            return await conn.fetchrow(sql, *args)
        except Exception:
            return None

    @staticmethod
    def _row_map(row: Any) -> Dict[str, Any]:
        if row is None:
            return {}
        if isinstance(row, dict):
            return row
        try:
            return {k: row[k] for k in row.keys()}
        except Exception:
            return {}

    @classmethod
    def _row_get(cls, row: Any, key: str, default=None):
        m = cls._row_map(row)
        return m.get(key, default)

    @classmethod
    def _identity_keys(cls, user, user_id) -> List[str]:
        keys = [str(user_id)]
        m = cls._row_map(user)
        for k in ("username", "hardware_id", "id"):
            v = m.get(k)
            if v:
                keys.append(str(v))
        seen = set()
        out: List[str] = []
        for k in keys:
            if k and k not in seen:
                seen.add(k)
                out.append(k)
        return out

    @staticmethod
    def _json_obj(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}

    def _rate_change(
        self, early_hits: Any, early_n: Any, late_hits: Any, late_n: Any,
    ) -> Dict[str, Any]:
        e_n = int(early_n or 0)
        l_n = int(late_n or 0)
        e_h = int(early_hits or 0)
        l_h = int(late_hits or 0)
        e = e_h / e_n if e_n else 0.0
        l = l_h / l_n if l_n else 0.0
        delta = round(e - l, 4)
        if e_n + l_n <= 0:
            direction = "insufficient"
        elif delta > 0.02:
            direction = "improving"
        elif delta < -0.02:
            direction = "worsening"
        else:
            direction = "stable"
        return {
            "early_rate": round(e, 4),
            "late_rate": round(l, 4),
            "delta": delta,
            "direction": direction,
            "late_hits": l_h,
            "early_hits": e_h,
        }

    def _assemble_industry_packet(
        self,
        *,
        metrics,
        language,
        cycles,
        cycle_preds,
        tx_preds,
        habits,
        plans,
        tg_catalog,
        nate_tactics,
    ) -> Dict[str, Any]:
        snap = self._row_map(metrics)
        if snap and "anxiety_level" not in snap:
            snap = {}
        shame = self._json_obj(snap.get("shame_profile"))
        pmb = self._json_obj(snap.get("pmb"))
        lang = self._row_map(language)
        if lang and "early_anxiety" not in lang:
            lang = {}

        constructs = {}
        for name in (
            "anxiety", "depression", "dissatisfaction",
            "dissociation", "shame", "blaming",
        ):
            constructs[name] = self._rate_change(
                lang.get(f"early_{name}"), lang.get("early_n"),
                lang.get(f"late_{name}"), lang.get("late_n"),
            )

        cycle_rows = []
        for row in cycles or []:
            m = self._row_map(row)
            if "domain" not in m:
                continue
            dom = str(m.get("domain") or "")
            cycle_rows.append({
                "domain": dom,
                "label": self._CYCLE_LABELS.get(dom, dom.replace("_", " ")),
                "period_days": round(self._num(m.get("detected_period_days")), 2),
                "amplitude": round(self._num(m.get("amplitude")), 4),
                "confidence": round(self._num(m.get("confidence")), 4),
                "method": m.get("method"),
                "detected_at": str(m.get("detected_at") or ""),
            })

        pred_rows = []
        scored = 0
        score_sum = 0.0
        for row in cycle_preds or []:
            m = self._row_map(row)
            if "domain" not in m:
                continue
            pred_rows.append({
                "domain": m.get("domain"),
                "label": self._CYCLE_LABELS.get(
                    str(m.get("domain") or ""), str(m.get("domain") or ""),
                ),
                "predicted_event": m.get("predicted_event"),
                "confidence": round(self._num(m.get("confidence")), 4),
                "convergence_risk": round(self._num(m.get("convergence_risk")), 4),
                "status": m.get("status"),
                "actual_outcome": m.get("actual_outcome"),
                "window_start": str(m.get("intervention_window_start") or ""),
                "window_end": str(m.get("intervention_window_end") or ""),
            })

        nate_preds = []
        for row in tx_preds or []:
            m = self._row_map(row)
            if "success_probability" not in m and "prediction_type" not in m:
                continue
            acc = m.get("accuracy_score")
            if acc is not None:
                scored += 1
                score_sum += self._num(acc)
            plan = self._json_obj(m.get("optimal_intervention_plan"))
            nate_preds.append({
                "prediction_type": m.get("prediction_type"),
                "goal_type": m.get("goal_type"),
                "success_probability": round(self._num(m.get("success_probability")), 4),
                "confidence": round(self._num(m.get("confidence_score")), 4),
                "accuracy_score": None if acc is None else round(self._num(acc), 4),
                "intervention": plan,
                "amplifiers": self._json_obj(m.get("key_amplifiers")),
                "resistances": self._json_obj(m.get("key_resistances")),
                "created_at": str(m.get("created_at") or ""),
            })

        habit_rows = []
        for row in habits or []:
            m = self._row_map(row)
            if "habit_type" not in m:
                continue
            habit_rows.append({
                "habit_type": m.get("habit_type"),
                "description": m.get("habit_description"),
                "status": m.get("status"),
                "current_streak": int(m.get("current_streak") or 0),
                "longest_streak": int(m.get("longest_streak") or 0),
                "completions": int(m.get("total_completions") or 0),
                "misses": int(m.get("total_misses") or 0),
            })

        plan_rows = []
        for row in plans or []:
            m = self._row_map(row)
            if "record_id" not in m and "excerpt" not in m:
                continue
            plan_rows.append({
                "record_id": m.get("record_id"),
                "excerpt": m.get("excerpt") or "",
                "coach_reviewed": bool(m.get("coach_reviewed")),
                "created_at": str(m.get("created_at") or ""),
            })

        tg_rows = []
        for row in tg_catalog or []:
            m = self._row_map(row)
            if "pattern_name" not in m and "description" not in m:
                continue
            tg_rows.append({
                "pattern_name": m.get("pattern_name"),
                "description": m.get("description"),
                "confidence": round(self._num(m.get("confidence")), 4),
                "effect_size": round(self._num(m.get("effect_size")), 4),
                "families_observed": int(m.get("families_observed") or 0),
            })

        tactics = self._row_map(nate_tactics)
        if tactics and "replies" not in tactics:
            tactics = {}
        tactic_counts = {
            "witness": int(tactics.get("witness") or 0),
            "somatic": int(tactics.get("somatic") or 0),
            "interrupt": int(tactics.get("interrupt") or 0),
            "cycle_naming": int(tactics.get("cycle_naming") or 0),
            "prediction": int(tactics.get("prediction") or 0),
            "redirect": int(tactics.get("redirect") or 0),
        }
        replies = int(tactics.get("replies") or 0)
        observed = [k for k, v in tactic_counts.items() if v > 0]
        dominant = max(tactic_counts, key=tactic_counts.get) if observed else None

        language_turns = int(lang.get("early_n") or 0) + int(lang.get("late_n") or 0)
        evidence = 0
        if snap:
            evidence += 1
        if language_turns > 0:
            evidence += 1
        if cycle_rows:
            evidence += 1
        if pred_rows:
            evidence += 1
        if nate_preds:
            evidence += 1
        if habit_rows:
            evidence += 1
        if plan_rows:
            evidence += 1
        if replies > 0:
            evidence += 1
        if tg_rows:
            evidence += 1
        if pmb:
            evidence += 1

        directions = [c["direction"] for c in constructs.values()]
        improving = directions.count("improving")
        worsening = directions.count("worsening")
        if improving > worsening and improving >= 2:
            overall = "improving"
        elif worsening > improving and worsening >= 2:
            overall = "worsening"
        elif any(d != "insufficient" for d in directions):
            overall = "mixed"
        else:
            overall = "insufficient"

        return {
            "evidence_count": evidence,
            "snapshot": {
                "anxiety_level": round(self._num(snap.get("anxiety_level")), 4) if snap else None,
                "depression_indicators": round(
                    self._num(snap.get("depression_indicators")), 4
                ) if snap else None,
                "stress_level": round(self._num(snap.get("stress_level")), 4) if snap else None,
                "shame_index": round(self._num(shame.get("shame_index")), 4) if shame else None,
                "homework_completion_rate": round(
                    self._num(snap.get("homework_completion_rate")), 4
                ) if snap else None,
                "breakthrough_count": int(snap.get("breakthrough_count") or 0) if snap else 0,
                "mood_trend": snap.get("mood_trend") if snap else None,
                "session_count": int(snap.get("session_count") or 0) if snap else 0,
            },
            "constructs": constructs,
            "language_turns": language_turns,
            "cycles": cycle_rows,
            "cycle_predictions": pred_rows,
            "nate_predictions": nate_preds,
            "habits": habit_rows,
            "treatment_plans": plan_rows,
            "transgenerational": {
                "legacy_depth": None if not pmb else pmb.get("legacy_depth"),
                "reconsolidation_readiness": None if not pmb else pmb.get(
                    "reconsolidation_readiness"
                ),
                "reactivity_type": None if not pmb else pmb.get("reactivity_type"),
                "catalog": tg_rows,
                "legacy_cycles": [c for c in cycle_rows if c["domain"] == "legacy"],
            },
            "nate_tactics": {
                "replies": replies,
                "counts": tactic_counts,
                "observed": observed,
                "dominant": dominant,
                "accuracy": None if scored <= 0 else round(score_sum / scored, 4),
                "scored_predictions": scored,
            },
            "overall_clinical_direction": overall,
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

    # ─── RBI + Little Nate scientific insight (coach instruments) ─────────

    @staticmethod
    def _cee_per_10k(cee: int, n: int) -> float:
        if n <= 0:
            return 0.0
        return round(cee * 10000.0 / n, 4)

    @staticmethod
    def _level_band(avg: float) -> str:
        if avg < 0.30:
            return "concerning"
        if avg < 0.60:
            return "developing"
        return "coherent"

    @staticmethod
    def _amplitude_band(amp: float) -> str:
        if amp < 0.15:
            return "compressed"
        if amp < 0.45:
            return "typical"
        return "wide"

    @staticmethod
    def _cee_rarity(per_10k: float, cee: int) -> str:
        if cee <= 0:
            return "absent"
        if per_10k < 1.0:
            return "rare"
        if per_10k < 20.0:
            return "present"
        return "frequent"

    @staticmethod
    def _trend_reliability(r_squared: float, weeks: int) -> str:
        if weeks < 8:
            return "insufficient"
        if r_squared < 0.10:
            return "insufficient"
        if r_squared < 0.30:
            return "weak"
        if r_squared < 0.50:
            return "moderate"
        return "strong"

    @staticmethod
    def _volatility_class(std_dev: float, mean: float) -> str:
        if mean <= 0:
            return "unknown"
        cv = std_dev / mean
        if cv < 0.15:
            return "low"
        if cv < 0.35:
            return "moderate"
        return "high"

    def _finalize_individual(
        self,
        user_id,
        days: int,
        user_name: Optional[str],
        n: int,
        avg_c_emo: float,
        min_c_emo: float,
        max_c_emo: float,
        cee_events: int,
        first_half: float,
        second_half: float,
        weekly: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        avg = round(self._num(avg_c_emo), 4)
        lo = round(self._num(min_c_emo), 4)
        hi = round(self._num(max_c_emo), 4)
        amplitude = round(hi - lo, 4)
        pos = 0.5 if amplitude < 1e-9 else round((avg - lo) / amplitude, 4)
        shift = self._trend_label(first_half, second_half)
        delta = round(second_half - first_half, 4)
        density = self._cee_per_10k(cee_events, n)
        level = self._level_band(avg)
        amp_band = self._amplitude_band(amplitude)
        rarity = self._cee_rarity(density, cee_events)
        name = user_name or "This client"

        if n < 50:
            reliability = "low"
            reliability_basis = f"n={n} is thin for a stable level estimate."
        elif n < 500:
            reliability = "moderate"
            reliability_basis = f"n={n} supports a usable level estimate; CEE counts remain noisy."
        else:
            reliability = "high"
            reliability_basis = (
                f"n={n} makes the mean/range stable; CEE density, not raw CEE count, is the "
                "engagement fact."
            )

        if rarity == "absent":
            cee_line = (
                "No CEE windows in this period. Do not treat that as failure — CEE is a rare "
                "engagement event, not a session grade."
            )
        elif rarity == "rare":
            cee_line = (
                f"{cee_events} CEE window(s) in {n} samples ({density}/10k). That is a sparse "
                "signal. Coach the conditions around those moments; do not chase a higher count."
            )
        elif rarity == "present":
            cee_line = (
                f"{cee_events} CEE windows ({density}/10k) are present enough to review as "
                "engagement episodes, still not a volume contest."
            )
        else:
            cee_line = (
                f"CEE density is frequent ({density}/10k). Check whether sessions are actually "
                "opening windows or the logger is over-firing."
            )

        if shift == "improving":
            shift_line = (
                f"Second-half level is {delta:+.4f} vs first half. That is a recent-level "
                "contrast, not a 12-week slope."
            )
        elif shift == "declining":
            shift_line = (
                f"Second-half level is {delta:+.4f} vs first half. Treat as a present-window "
                "dip to explore, not as proven decline."
            )
        else:
            shift_line = (
                "Half-window levels agree. Stability here is a state fact, not proof of a flat "
                "trajectory."
            )

        coach_move = (
            f"Work from the {level} band and {amp_band} C_emo range. Use the {rarity} CEE "
            "density as the platform engagement clue. For anxiety, depression, shame, "
            "cycles, treatment-plan growth, or how Little Nate is intervening, generate "
            "Longitudinal Trends (Review Board Investigation)."
        )
        narrative = (
            f"{name}: Individual Coherence is the Nevedal PLATFORM packet — where C_emo sits "
            "in this window — not an industry symptom or treatment-plan report.\n\n"
            f"Quantitative: n={n}; mean C_emo {avg} ({level}); range {lo}–{hi} "
            f"(amplitude {amplitude}, {amp_band}); position in range {pos:.0%}; "
            f"CEE {cee_events} ({density}/10k, {rarity}); half-window shift {shift} "
            f"(Δ {delta}).\n\n"
            f"Qualitative: {cee_line} {shift_line} {coach_move}\n\n"
            "Review Board Investigation: this packet qualifies platform C_emo / CEE only. "
            "It does not qualify anxiety, depression, dissociation, shame, blaming, "
            "cycles, transgenerational load, or Little Nate's tactics."
        )
        summary = {
            "total_measurements": n,
            "avg_c_emo": avg,
            "min_c_emo": lo,
            "max_c_emo": hi,
            "amplitude": amplitude,
            "position_in_range": pos,
            "cee_events": cee_events,
            "cee_per_10k": density,
            "recent_shift": shift,
            "recent_shift_delta": delta,
            "trend": shift,
            "trend_change": delta,
        }
        return {
            "report_type": "individual_coherence",
            "user_id": str(user_id),
            "user_name": user_name,
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "instrument": {
                "id": "individual_coherence",
                "name": "Nevedal Individual (platform C_emo)",
                "question": "Where do platform C_emo and CEE sit in the selected window?",
                "method": (
                    "Nevedal level statistics (mean, min, max, amplitude), CEE density, and "
                    "first-half vs second-half C_emo contrast."
                ),
                "does_not_measure": [
                    "anxiety / depression industry change",
                    "dissatisfaction / dissociation",
                    "shame / blaming circumstances",
                    "treatment-plan growth or intervention adherence",
                    "cycle detections / transgenerational patterns",
                    "Little Nate tactics or prediction accuracy",
                ],
                "pair_with": "longitudinal_trends",
                "series_label": "Weekly C_emo levels (platform only)",
            },
            "summary": summary,
            "weekly_averages": weekly,
            "weekly_levels": weekly,
            "rbi": {
                "title": "Review Board Investigation",
                "audience": "mental health board / licensing institution",
                "construct": (
                    "Platform-special Nevedal metrics: C_emo (0–1 coherence) and CEE windows"
                ),
                "method": "State portrait: mean/range + CEE density + half-window contrast",
                "sample_size": n,
                "coverage_days": days,
                "reliability": {"label": reliability, "basis": reliability_basis},
                "inference": (
                    f"A board may be told present C_emo level ({level}), personal range, and "
                    f"CEE rarity ({rarity}) as platform measurements."
                ),
                "do_not_infer": (
                    "Do not report anxiety, depression, shame, cycles, treatment-plan growth, "
                    "or Little Nate intervention quality from this packet."
                ),
                "completes_with": "longitudinal_trends",
            },
            "nate_scientific_insight": {
                "lens": "state",
                "quantitative": [
                    f"Mean C_emo {avg} ({level})",
                    f"Range {lo}–{hi} (amplitude {amplitude}, {amp_band})",
                    f"CEE {cee_events} = {density}/10k ({rarity})",
                    f"Half-window shift {shift} (Δ {delta})",
                ],
                "qualitative": [cee_line, shift_line, coach_move],
                "coach_translation": coach_move,
                "complement": (
                    "This is the Nevedal platform packet. Generate Longitudinal Trends for "
                    "the industry Review Board Investigation (symptoms, cycles, PMB, LN review)."
                ),
                "narrative": narrative,
            },
        }

    def _finalize_longitudinal(
        self,
        user_id,
        days: int,
        user_name: Optional[str],
        packet: Dict[str, Any],
    ) -> Dict[str, Any]:
        name = user_name or "This client"
        snap = packet.get("snapshot") or {}
        constructs = packet.get("constructs") or {}
        cycles = packet.get("cycles") or []
        cycle_preds = packet.get("cycle_predictions") or []
        nate_preds = packet.get("nate_predictions") or []
        habits = packet.get("habits") or []
        plans = packet.get("treatment_plans") or []
        tg = packet.get("transgenerational") or {}
        tactics = packet.get("nate_tactics") or {}
        overall = packet.get("overall_clinical_direction") or "insufficient"
        turns = int(packet.get("language_turns") or 0)
        sources = packet.get("evidence_count") or 0

        def _dir(key: str) -> str:
            return (constructs.get(key) or {}).get("direction") or "insufficient"

        anx = constructs.get("anxiety") or {}
        dep = constructs.get("depression") or {}
        shame_c = constructs.get("shame") or {}
        blame = constructs.get("blaming") or {}
        dissoc = constructs.get("dissociation") or {}
        dissat = constructs.get("dissatisfaction") or {}

        if sources >= 5:
            grade, grade_basis = "high", f"{sources} independent industry sources in the window."
        elif sources >= 3:
            grade, grade_basis = "moderate", f"{sources} industry sources; name gaps before a board."
        else:
            grade, grade_basis = "limited", f"Only {sources} industry source(s). Treat as incomplete."

        symptom_line = (
            f"Language change ({turns} turns): anxiety {_dir('anxiety')}, depression "
            f"{_dir('depression')}, dissatisfaction {_dir('dissatisfaction')}, "
            f"dissociation {_dir('dissociation')}, shame {_dir('shame')}, blaming "
            f"{_dir('blaming')}."
        )
        snap_line = (
            "Latest clinician-facing snapshot: "
            f"anxiety={snap.get('anxiety_level')}, depression={snap.get('depression_indicators')}, "
            f"shame_index={snap.get('shame_index')}, homework="
            f"{snap.get('homework_completion_rate')}."
            if snap.get("anxiety_level") is not None or snap.get("shame_index") is not None
            else "No client_metrics industry snapshot is on file yet."
        )
        cycle_line = (
            f"{len(cycles)} cycle detection(s) Little Nate observed; "
            f"{len(cycle_preds)} cycle forecast(s) with intervention windows."
            if cycles or cycle_preds
            else "No stored cycle detections or forecasts in the last 30 days."
        )
        tg_line = (
            f"PMB legacy_depth={tg.get('legacy_depth')}, reconsolidation_readiness="
            f"{tg.get('reconsolidation_readiness')}; {len(tg.get('catalog') or [])} "
            "anonymized transgenerational catalog pattern(s) available for coach review."
        )
        acc = tactics.get("accuracy")
        tactic_line = (
            f"Little Nate observed tactics: {', '.join(tactics.get('observed') or []) or 'none tagged'}; "
            f"dominant={tactics.get('dominant') or 'n/a'}; "
            f"prediction accuracy={acc if acc is not None else 'unscored'} "
            f"({tactics.get('scored_predictions') or 0} scored)."
        )
        plan_line = (
            f"Treatment-plan records={len(plans)}; active/tracked habits={len(habits)}; "
            f"homework completion={snap.get('homework_completion_rate')}."
        )
        coach_move = (
            f"Review Board packet is {overall}. Discuss LN's {tactics.get('dominant') or 'untagged'} "
            "tactic mix and whether predictions are being scored. Pair with Nevedal Individual "
            "only if the board also needs C_emo / CEE."
        )
        narrative = (
            f"{name}: Longitudinal Trends is the industry Review Board Investigation — "
            "treatment-plan growth, symptom handling, cycles, transgenerational load, and "
            "Little Nate accountability — not a C_emo slope.\n\n"
            f"Quantitative: {snap_line} {symptom_line} {plan_line} {cycle_line}\n\n"
            f"Qualitative: {tg_line} {tactic_line} {coach_move}\n\n"
            "Review Board Investigation: do not quote C_emo, CEE density, amplitude, or R² "
            "from this packet. Those belong to the Nevedal Individual report."
        )

        summary = {
            "overall_clinical_direction": overall,
            "evidence_sources": sources,
            "language_turns": turns,
            "anxiety_level": snap.get("anxiety_level"),
            "anxiety_direction": _dir("anxiety"),
            "depression_indicators": snap.get("depression_indicators"),
            "depression_direction": _dir("depression"),
            "dissatisfaction_direction": _dir("dissatisfaction"),
            "dissociation_direction": _dir("dissociation"),
            "shame_index": snap.get("shame_index"),
            "shame_direction": _dir("shame"),
            "blaming_direction": _dir("blaming"),
            "homework_completion_rate": snap.get("homework_completion_rate"),
            "treatment_plan_records": len(plans),
            "active_habits": len(habits),
            "cycle_count": len(cycles),
            "cycle_prediction_count": len(cycle_preds),
            "nate_prediction_count": len(nate_preds),
            "nate_accuracy": acc,
            "nate_dominant_tactic": tactics.get("dominant"),
            "trend": overall,
        }
        industry_series = [
            {
                "week": key,
                "avg": (constructs.get(key) or {}).get("late_rate") or 0.0,
                "count": (constructs.get(key) or {}).get("late_hits") or 0,
            }
            for key in (
                "anxiety", "depression", "dissatisfaction",
                "dissociation", "shame", "blaming",
            )
        ]
        return {
            "report_type": "longitudinal_trends",
            "user_id": str(user_id),
            "user_name": user_name,
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "instrument": {
                "id": "longitudinal_trends",
                "name": "Longitudinal Trends (industry / Review Board)",
                "question": (
                    "What treatment-plan, symptom, cycle, transgenerational, and Little Nate "
                    "performance picture would a mental health board use?"
                ),
                "method": (
                    "client_metrics industry snapshot + conversation language rates + cycle "
                    "engine + therapeutic predictions + PMB/transgenerational + LN tactic audit"
                ),
                "does_not_measure": [
                    "C_emo mean / min / max / amplitude",
                    "CEE density or CEE timing",
                    "OLS slope or R² on coherence",
                    "half-window C_emo shift",
                ],
                "pair_with": "individual_coherence",
                "series_label": "Late-window industry language rates",
            },
            "statistics": summary,
            "summary": summary,
            "industry_metrics": {
                "snapshot": snap,
                "constructs": constructs,
            },
            "treatment_plan": {
                "records": plans,
                "habits": habits,
                "homework_completion_rate": snap.get("homework_completion_rate"),
            },
            "cycle_detections": cycles,
            "cycle_predictions": cycle_preds,
            "transgenerational": tg,
            "nate_tactics": tactics,
            "nate_predictions": nate_preds,
            "industry_series": industry_series,
            "weekly_averages": industry_series,
            "rbi": {
                "title": "Review Board Investigation",
                "audience": "mental health board / licensing institution",
                "construct": (
                    "Industry clinical change: anxiety, depression, dissatisfaction, "
                    "dissociation, shame, blaming circumstances, treatment-plan growth, "
                    "observed cycles, transgenerational/PMB, Little Nate tactics and accuracy"
                ),
                "method": (
                    "Multi-source harvest outside C_emo; language first-half vs second-half "
                    "rates plus stored cycle/prediction/habit/plan rows"
                ),
                "sample_size": turns,
                "coverage_days": days,
                "reliability": {"label": grade, "basis": grade_basis},
                "inference": (
                    f"A board may be briefed on {overall} industry direction, named cycles "
                    f"({len(cycles)}), treatment-plan/habit adherence, and how Little Nate "
                    "is intervening."
                ),
                "do_not_infer": (
                    "Do not treat C_emo, CEE, amplitude, or coherence R² as this instrument. "
                    "Those are Nevedal platform metrics only."
                ),
                "completes_with": "individual_coherence",
            },
            "nate_scientific_insight": {
                "lens": "industry_clinical",
                "quantitative": [
                    f"Overall industry direction {overall} ({sources} sources)",
                    f"Anxiety language {_dir('anxiety')}; depression {_dir('depression')}",
                    f"Shame {_dir('shame')}; blaming {_dir('blaming')}",
                    f"Cycles {len(cycles)}; LN accuracy {acc if acc is not None else 'unscored'}",
                ],
                "qualitative": [
                    symptom_line, plan_line, cycle_line, tg_line, tactic_line, coach_move,
                ],
                "coach_translation": coach_move,
                "complement": (
                    "This is the board-facing industry packet. Generate Nevedal Individual "
                    "only if the reviewer also needs platform C_emo / CEE."
                ),
                "narrative": narrative,
            },
        }
