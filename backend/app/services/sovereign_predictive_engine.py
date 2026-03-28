"""
Nevedal-Enhanced Therapeutic Prediction Engine.

Master formula:
  Therapeutic_Success_Probability = (
      (Nevedal_Base * Temporal_Intelligence * Population_Baseline * Individual_History)
      / (Environmental_Resistance * Unconscious_Sabotage * System_Complexity)
  ) * Context_Amplifiers * Intervention_Optimization

Each sub-component reads from existing data sources (client_metrics, nevedal_metrics,
coherence_measurements, coaching_sessions, etc.) and returns a 0.01-1.0 score.
"""

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import numpy as np

logger = logging.getLogger(__name__)


def _geo_mean(*values: float) -> float:
    clamped = [max(v, 0.01) for v in values]
    product = 1.0
    for v in clamped:
        product *= v
    return product ** (1.0 / len(clamped))


def _sigmoid_normalize(raw: float, midpoint: float = 1.0, steepness: float = 3.0) -> float:
    return 100.0 / (1.0 + math.exp(-steepness * (raw - midpoint)))


class SovereignPredictiveEngine:
    def __init__(self, db_pool=None, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._cycle_engine = None
        logger.info("SovereignPredictiveEngine initialized")

    def set_cycle_engine(self, engine):
        self._cycle_engine = engine

    # =========================================================================
    # MASTER FORMULA
    # =========================================================================

    async def calculate_unified_therapeutic_probability(
        self, user_id: str, goal_type: str = "general", context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        ctx = context or {}
        nevedal_base = await self.calculate_enhanced_nevedal_base(user_id)
        temporal = await self.calculate_temporal_intelligence(user_id)
        population = await self.calculate_population_baseline(user_id, ctx)
        individual = await self.calculate_individual_history(user_id)
        env_resistance = await self.calculate_environmental_resistance(user_id)
        sabotage = await self.calculate_unconscious_sabotage(user_id)
        amplifiers = await self.calculate_context_amplifiers(user_id, ctx)
        optimization = await self.calculate_intervention_optimization(user_id, goal_type)

        system_complexity = max(ctx.get("system_complexity", 1.0), 0.5)
        denominator = max(env_resistance * sabotage * system_complexity, 0.01)

        raw = (nevedal_base * temporal * population * individual) / denominator
        raw *= amplifiers * optimization

        probability = _sigmoid_normalize(raw, midpoint=0.5, steepness=4.0)
        confidence = await self._calculate_confidence(user_id)

        components = {
            "nevedal_base": round(nevedal_base, 4),
            "temporal_intelligence": round(temporal, 4),
            "population_baseline": round(population, 4),
            "individual_history": round(individual, 4),
            "environmental_resistance": round(env_resistance, 4),
            "unconscious_sabotage": round(sabotage, 4),
            "context_amplifiers": round(amplifiers, 4),
            "intervention_optimization": round(optimization, 4),
        }

        result = {
            "success_probability": round(probability, 2),
            "confidence_score": round(confidence, 2),
            "nevedal_base_score": round(nevedal_base, 4),
            "components": components,
            "key_amplifiers": self._identify_top_amplifiers(components),
            "key_resistances": self._identify_top_resistances(components),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO therapeutic_predictions
                        (user_id, prediction_type, goal_type, success_probability,
                         confidence_score, nevedal_base_score, components,
                         key_amplifiers, key_resistances, prediction_horizon_days)
                        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9::jsonb, $10)
                    """, user_id, "therapeutic_probability", goal_type,
                        probability, confidence, nevedal_base,
                        __import__("json").dumps(components),
                        __import__("json").dumps(result["key_amplifiers"]),
                        __import__("json").dumps(result["key_resistances"]),
                        30)
            except Exception as e:
                logger.warning("SovereignPredictiveEngine: failed to store prediction: %s", e)

        return result

    # =========================================================================
    # SUB-COMPONENT 1: NEVEDAL BASE
    # =========================================================================

    async def calculate_enhanced_nevedal_base(self, user_id: str) -> float:
        if not self.db_pool:
            return 0.5

        try:
            async with self.db_pool.acquire() as conn:
                metrics = await conn.fetchrow("""
                    SELECT c_emo, anxiety_level, stress_level, engagement,
                           homework_completion_rate, mood_trend,
                           breakthrough_count, session_count,
                           shame_profile, nevedal_state
                    FROM client_metrics
                    WHERE hardware_id = $1 OR user_id::text = $1
                    ORDER BY updated_at DESC LIMIT 1
                """, user_id)

                voice_row = await conn.fetchrow("""
                    SELECT biometrics FROM nevedal_metrics
                    WHERE user_id::text = $1
                    ORDER BY recorded_at DESC LIMIT 1
                """, user_id)

            if not metrics:
                return 0.5

            c_emo = float(metrics.get("c_emo") or 0.5)
            warmth = 0.5
            if voice_row and voice_row.get("biometrics"):
                bio = voice_row["biometrics"]
                if isinstance(bio, str):
                    bio = __import__("json").loads(bio)
                warmth = float(bio.get("warmth_index", 0.5))

            authenticity = _geo_mean(c_emo, warmth, c_emo)

            engagement = float(metrics.get("engagement") or 0.5)
            awareness = _geo_mean(engagement, c_emo, engagement)

            hw_rate = float(metrics.get("homework_completion_rate") or 0.3)
            bt_count = int(metrics.get("breakthrough_count") or 0)
            sess_count = max(int(metrics.get("session_count") or 1), 1)
            bt_ratio = min(bt_count / sess_count, 1.0)
            mood_dir = 0.6 if (metrics.get("mood_trend") or "stable") == "improving" else 0.4
            integration = _geo_mean(hw_rate, bt_ratio, mood_dir)

            anxiety = float(metrics.get("anxiety_level") or 0.3)
            stress = float(metrics.get("stress_level") or 0.3)
            shame = 0.3
            shame_prof = metrics.get("shame_profile")
            if shame_prof:
                if isinstance(shame_prof, str):
                    shame_prof = __import__("json").loads(shame_prof)
                shame = float(shame_prof.get("shame_index", 0.3))
            resistance = _geo_mean(anxiety, stress, shame)

            return max(min((authenticity * awareness * integration) / max(resistance, 0.01), 1.0), 0.01)

        except Exception as e:
            logger.warning("SovereignPredictiveEngine: nevedal_base error: %s", e)
            return 0.5

    # =========================================================================
    # SUB-COMPONENT 2: TEMPORAL INTELLIGENCE
    # =========================================================================

    async def calculate_temporal_intelligence(self, user_id: str) -> float:
        if self._cycle_engine:
            try:
                gen_score = await self._cycle_engine.get_generational_score(user_id)
                habit_score = await self._cycle_engine.get_habit_timeline_score(user_id)
                timing_score = await self._cycle_engine.get_optimal_timing_score(user_id)
                pattern_score = await self._cycle_engine.get_historical_pattern_score(user_id)
                return _geo_mean(gen_score, habit_score, timing_score, pattern_score)
            except Exception as e:
                logger.warning("SovereignPredictiveEngine: temporal cycle error: %s", e)

        if not self.db_pool:
            return 0.5

        try:
            async with self.db_pool.acquire() as conn:
                sess_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM coaching_sessions
                    WHERE client_id = $1 AND status = 'completed'
                    AND scheduled_start > NOW() - INTERVAL '90 days'
                """, user_id)
            consistency = min((sess_count or 0) / 12.0, 1.0)
            return _geo_mean(consistency, 0.5, 0.5, 0.5)
        except Exception as e:
            logger.warning("SovereignPredictiveEngine: temporal error: %s", e)
            return 0.5

    # =========================================================================
    # SUB-COMPONENT 3: POPULATION BASELINE
    # =========================================================================

    async def calculate_population_baseline(self, user_id: str, ctx: Dict) -> float:
        if not self.db_pool:
            return 0.5
        try:
            async with self.db_pool.acquire() as conn:
                community = await conn.fetchval("""
                    SELECT AVG(score) FROM coherence_measurements
                    WHERE layer = 'community'
                    AND measured_at > NOW() - INTERVAL '30 days'
                """)
                cultural = await conn.fetchval("""
                    SELECT AVG(score) FROM coherence_measurements
                    WHERE layer = 'cultural'
                    AND measured_at > NOW() - INTERVAL '30 days'
                """)
                pop_bt = await conn.fetchrow("""
                    SELECT AVG(CASE WHEN session_count > 0
                        THEN breakthrough_count::float / session_count ELSE 0 END) as avg_bt
                    FROM client_metrics WHERE session_count > 3
                """)

            comm = float(community or 0.5)
            cult = float(cultural or 0.5)
            bt_rate = float(pop_bt["avg_bt"]) if pop_bt and pop_bt["avg_bt"] else 0.3
            return _geo_mean(comm, bt_rate, cult, 0.5)
        except Exception as e:
            logger.warning("SovereignPredictiveEngine: population error: %s", e)
            return 0.5

    # =========================================================================
    # SUB-COMPONENT 4: INDIVIDUAL HISTORY
    # =========================================================================

    async def calculate_individual_history(self, user_id: str) -> float:
        if not self.db_pool:
            return 0.5
        try:
            async with self.db_pool.acquire() as conn:
                metrics = await conn.fetchrow("""
                    SELECT c_emo, breakthrough_count, session_count
                    FROM client_metrics
                    WHERE hardware_id = $1 OR user_id::text = $1
                    ORDER BY updated_at DESC LIMIT 1
                """, user_id)
                voice_rows = await conn.fetch("""
                    SELECT biometrics FROM nevedal_metrics
                    WHERE user_id::text = $1
                    ORDER BY recorded_at DESC LIMIT 5
                """, user_id)

            if not metrics:
                return 0.5

            c_emo = float(metrics.get("c_emo") or 0.5)
            bt_count = int(metrics.get("breakthrough_count") or 0)
            sess_count = max(int(metrics.get("session_count") or 1), 1)
            success_rate = min(bt_count / sess_count, 1.0)

            warmth_vals = []
            stress_vals = []
            for vr in (voice_rows or []):
                bio = vr.get("biometrics")
                if bio:
                    if isinstance(bio, str):
                        bio = __import__("json").loads(bio)
                    warmth_vals.append(float(bio.get("warmth_index", 0.5)))
                    stress_vals.append(float(bio.get("stress_index", 0.5)))

            warmth_consistency = 1.0 - np.std(warmth_vals) if len(warmth_vals) >= 3 else 0.5
            stress_trend = 0.5
            if len(stress_vals) >= 3:
                slope = np.polyfit(range(len(stress_vals)), stress_vals, 1)[0]
                stress_trend = max(0.01, min(1.0 - slope, 1.0))

            return _geo_mean(c_emo, warmth_consistency, stress_trend, success_rate)
        except Exception as e:
            logger.warning("SovereignPredictiveEngine: individual_history error: %s", e)
            return 0.5

    # =========================================================================
    # SUB-COMPONENT 5: ENVIRONMENTAL RESISTANCE
    # =========================================================================

    async def calculate_environmental_resistance(self, user_id: str) -> float:
        if not self.db_pool:
            return 0.5
        try:
            async with self.db_pool.acquire() as conn:
                weather = await conn.fetchrow("""
                    SELECT system_volatility, system_coherence
                    FROM emotional_weather_snapshots
                    WHERE sanctuary_id = $1
                    ORDER BY created_at DESC LIMIT 1
                """, user_id)
                community_inv = await conn.fetchval("""
                    SELECT 1.0 - COALESCE(AVG(score), 0.5) FROM coherence_measurements
                    WHERE layer = 'community'
                    AND measured_at > NOW() - INTERVAL '30 days'
                """)
                cancel_rate = await conn.fetchval("""
                    SELECT COUNT(*) FILTER (WHERE status = 'cancelled')::float
                        / GREATEST(COUNT(*), 1)
                    FROM coaching_sessions
                    WHERE client_id = $1
                    AND scheduled_start > NOW() - INTERVAL '90 days'
                """, user_id)

            volatility = float(weather["system_volatility"]) if weather else 0.3
            comm_stress = float(community_inv or 0.3)
            cancellation = float(cancel_rate or 0.1)
            family_push = max(1.0 - float(weather["system_coherence"]) if weather else 0.3, 0.01)

            return _geo_mean(family_push, comm_stress, cancellation, volatility)
        except Exception as e:
            logger.warning("SovereignPredictiveEngine: env_resistance error: %s", e)
            return 0.5

    # =========================================================================
    # SUB-COMPONENT 6: UNCONSCIOUS SABOTAGE
    # =========================================================================

    async def calculate_unconscious_sabotage(self, user_id: str) -> float:
        if not self.db_pool:
            return 0.5
        try:
            async with self.db_pool.acquire() as conn:
                metrics = await conn.fetchrow("""
                    SELECT shame_profile, crisis_perception, pmb
                    FROM client_metrics
                    WHERE hardware_id = $1 OR user_id::text = $1
                    ORDER BY updated_at DESC LIMIT 1
                """, user_id)

            if not metrics:
                return 0.5

            shame_prof = metrics.get("shame_profile") or {}
            if isinstance(shame_prof, str):
                shame_prof = __import__("json").loads(shame_prof)
            crisis_perc = metrics.get("crisis_perception") or {}
            if isinstance(crisis_perc, str):
                crisis_perc = __import__("json").loads(crisis_perc)
            pmb = metrics.get("pmb") or {}
            if isinstance(pmb, str):
                pmb = __import__("json").loads(pmb)

            masking = float(crisis_perc.get("masking_score", 0.3))
            shame_idx = float(shame_prof.get("shame_index", 0.3))
            legacy_d = float(pmb.get("legacy_depth", 0.3))
            recon = float(pmb.get("reconsolidation_readiness", 0.5))

            trauma_trigger = shame_idx * legacy_d
            resistance_inv = max(1.0 - recon, 0.01)

            return _geo_mean(masking, trauma_trigger, 0.3, resistance_inv)
        except Exception as e:
            logger.warning("SovereignPredictiveEngine: sabotage error: %s", e)
            return 0.5

    # =========================================================================
    # SUB-COMPONENT 7: CONTEXT AMPLIFIERS
    # =========================================================================

    async def calculate_context_amplifiers(self, user_id: str, ctx: Dict) -> float:
        vr_enhancement = 1.0

        odpe_map = {"LOCKED": 1.5, "PROMOTED": 1.2, "TENSION": 0.8, "PROVISIONAL": 1.0, "NOISE": 0.5}
        odpe_signal = "PROVISIONAL"
        if self.app_state:
            odpe = getattr(self.app_state, "odpe_engine", None)
            if odpe:
                try:
                    status = odpe.get_status()
                    odpe_signal = status.get("last_signal", "PROVISIONAL")
                except Exception:
                    pass
        micro_opt = odpe_map.get(odpe_signal, 1.0)

        helix_conf = 1.0
        if self.app_state:
            helix = getattr(self.app_state, "helix_orchestrator", None)
            if helix:
                try:
                    status = helix.get_status()
                    helix_conf = min(float(status.get("last_confidence", 0.7)), 1.5)
                except Exception:
                    pass

        cee_freq = 0.5
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    cee_count = await conn.fetchval("""
                        SELECT COUNT(*) FROM nevedal_metrics
                        WHERE user_id::text = $1 AND cee_window = TRUE
                        AND recorded_at > NOW() - INTERVAL '90 days'
                    """, user_id)
                    total = await conn.fetchval("""
                        SELECT COUNT(*) FROM nevedal_metrics
                        WHERE user_id::text = $1
                        AND recorded_at > NOW() - INTERVAL '90 days'
                    """, user_id)
                if total and total > 0:
                    cee_freq = min(float(cee_count or 0) / float(total), 1.0)
            except Exception:
                pass

        return _geo_mean(vr_enhancement, micro_opt, helix_conf, max(cee_freq, 0.1))

    # =========================================================================
    # SUB-COMPONENT 8: INTERVENTION OPTIMIZATION
    # =========================================================================

    async def calculate_intervention_optimization(self, user_id: str, goal_type: str) -> float:
        crystal_density = 0.5
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    crystal_count = await conn.fetchval("""
                        SELECT COUNT(*) FROM nate_intelligence_crystals
                        WHERE scope LIKE $1 AND superseded_by IS NULL
                    """, f"user:{user_id}%")
                crystal_density = min(float(crystal_count or 0) / 20.0, 1.0)
            except Exception:
                pass

        checkin_resp = 0.5
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    resp_rate = await conn.fetchval("""
                        SELECT COUNT(*) FILTER (WHERE responded = TRUE)::float
                            / GREATEST(COUNT(*), 1)
                        FROM nate_checkin_log
                        WHERE user_id = $1
                        AND created_at > NOW() - INTERVAL '30 days'
                    """, user_id)
                checkin_resp = float(resp_rate or 0.3)
            except Exception:
                pass

        return _geo_mean(crystal_density, 0.7, 0.6, checkin_resp)

    # =========================================================================
    # HABIT PREDICTION
    # =========================================================================

    async def predict_habit_success_timeline(
        self, user_id: str, habit_type: str, habit_description: str = ""
    ) -> Dict[str, Any]:
        nevedal = await self.calculate_enhanced_nevedal_base(user_id)
        env_res = await self.calculate_environmental_resistance(user_id)
        sabotage = await self.calculate_unconscious_sabotage(user_id)

        base_days = {"exercise": 66, "meditation": 45, "journaling": 30,
                     "diet": 90, "sleep": 60, "therapy_homework": 40}
        base = base_days.get(habit_type, 66)

        adoption_days = max(7, int(base * (1.0 / max(nevedal, 0.1)) * env_res))
        crystallization_days = max(adoption_days + 14, int(adoption_days * 1.8))
        maintenance_prob = min(nevedal * 0.9 / max(sabotage, 0.1) * 0.5, 0.95) * 100

        sabotage_windows = []
        if sabotage > 0.4:
            window_day = max(7, int(adoption_days * 0.3))
            sabotage_windows.append({
                "day": window_day,
                "risk": round(sabotage, 2),
                "intervention": "Pre-emptive resistance processing session recommended",
            })
            sabotage_windows.append({
                "day": adoption_days - 3,
                "risk": round(sabotage * 0.8, 2),
                "intervention": "Consolidation coaching before crystallization threshold",
            })

        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO therapeutic_habit_tracking
                        (user_id, habit_type, habit_description, target_days,
                         predicted_adoption_days, predicted_crystallization_days,
                         predicted_maintenance_probability, prediction_metadata)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                    """, user_id, habit_type, habit_description, base,
                        adoption_days, crystallization_days,
                        maintenance_prob / 100.0,
                        __import__("json").dumps({
                            "nevedal_base": round(nevedal, 4),
                            "env_resistance": round(env_res, 4),
                            "sabotage_risk": round(sabotage, 4),
                        }))
            except Exception as e:
                logger.warning("SovereignPredictiveEngine: habit store error: %s", e)

        return {
            "habit_type": habit_type,
            "days_to_initial_adoption": adoption_days,
            "days_to_crystallization": crystallization_days,
            "maintenance_probability": round(maintenance_prob, 1),
            "sabotage_windows": sabotage_windows,
            "nevedal_base": round(nevedal, 4),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # =========================================================================
    # FAMILY SYSTEM PREDICTION
    # =========================================================================

    async def predict_family_effectiveness(self, family_id: str) -> Dict[str, Any]:
        if not self.db_pool:
            return {"status": "no_database", "effectiveness": 0}

        try:
            async with self.db_pool.acquire() as conn:
                members = await conn.fetch("""
                    SELECT username, id::text as uid FROM users
                    WHERE family_id::text = $1 AND role = 'CLIENT'
                """, family_id)
                family_coh = await conn.fetchval("""
                    SELECT AVG(score) FROM coherence_measurements
                    WHERE family_id::text = $1 AND layer = 'family'
                    AND measured_at > NOW() - INTERVAL '30 days'
                """, family_id)
                weather = await conn.fetchrow("""
                    SELECT system_coherence, system_volatility
                    FROM emotional_weather_snapshots
                    WHERE family_id = $1
                    ORDER BY created_at DESC LIMIT 1
                """, family_id)

            if not members:
                return {"status": "no_members", "effectiveness": 0}

            member_scores = []
            for m in members:
                score = await self.calculate_enhanced_nevedal_base(m["username"])
                member_scores.append({"username": m["username"], "nevedal_base": round(score, 4)})

            sum_nevedal = sum(ms["nevedal_base"] for ms in member_scores)
            family_coherence = float(family_coh or 0.4)
            sys_coh = float(weather["system_coherence"]) if weather else 0.4
            sys_vol = float(weather["system_volatility"]) if weather else 0.5

            numerator = sum_nevedal * family_coherence * sys_coh
            denominator = max(sys_vol * len(members) * 0.5, 0.1)
            raw_eff = numerator / denominator

            effectiveness = _sigmoid_normalize(raw_eff, midpoint=1.0, steepness=2.0)

            return {
                "family_id": family_id,
                "effectiveness": round(effectiveness, 2),
                "member_count": len(members),
                "member_scores": member_scores,
                "family_coherence": round(family_coherence, 4),
                "system_volatility": round(sys_vol, 4),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.warning("SovereignPredictiveEngine: family prediction error: %s", e)
            return {"status": "error", "effectiveness": 0}

    # =========================================================================
    # REAL-TIME COACHING SCORE
    # =========================================================================

    async def calculate_realtime_coaching_score(
        self, user_id: str, current_context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        ctx = current_context or {}
        nevedal = await self.calculate_enhanced_nevedal_base(user_id)

        micro_receptivity = 0.6
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    bio = await conn.fetchrow("""
                        SELECT biometrics FROM nevedal_metrics
                        WHERE user_id::text = $1
                        ORDER BY recorded_at DESC LIMIT 1
                    """, user_id)
                if bio and bio.get("biometrics"):
                    b = bio["biometrics"]
                    if isinstance(b, str):
                        b = __import__("json").loads(b)
                    stress_inv = max(1.0 - float(b.get("stress_index", 0.5)), 0.1)
                    warmth = float(b.get("warmth_index", 0.5))
                    micro_receptivity = (stress_inv + warmth) / 2.0
            except Exception:
                pass

        timing_score = 0.6
        foresight = getattr(self.app_state, "foresight_engine", None) if self.app_state else None
        if foresight and self.db_pool:
            try:
                window = await foresight.suggest_intervention_window(user_id, horizon_hours=24)
                if window.get("status") != "insufficient_data" and window.get("windows"):
                    timing_score = 0.9
            except Exception:
                pass

        current_resistance = 0.4
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    m = await conn.fetchrow("""
                        SELECT anxiety_level, stress_level FROM client_metrics
                        WHERE hardware_id = $1 OR user_id::text = $1
                        ORDER BY updated_at DESC LIMIT 1
                    """, user_id)
                if m:
                    current_resistance = (float(m.get("anxiety_level") or 0.3) +
                                          float(m.get("stress_level") or 0.3)) / 2.0
            except Exception:
                pass

        raw = (nevedal * micro_receptivity * timing_score) / max(current_resistance, 0.1)

        if ctx.get("breakthrough_opportunity"):
            raw *= 2.5
        if ctx.get("family_support_present"):
            raw *= 1.8
        if ctx.get("high_stress_environment"):
            raw *= 0.6

        score = min(raw * 25, 100.0)

        return {
            "coaching_effectiveness": round(score, 1),
            "nevedal_score": round(nevedal, 4),
            "micro_receptivity": round(micro_receptivity, 4),
            "timing_score": round(timing_score, 4),
            "current_resistance": round(current_resistance, 4),
            "context_multipliers_applied": [k for k in ["breakthrough_opportunity",
                "family_support_present", "high_stress_environment"] if ctx.get(k)],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # =========================================================================
    # CONFIDENCE & HELPERS
    # =========================================================================

    async def _calculate_confidence(self, user_id: str) -> float:
        data_points = 0
        max_points = 5
        if not self.db_pool:
            return 30.0
        try:
            async with self.db_pool.acquire() as conn:
                has_metrics = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM client_metrics WHERE hardware_id = $1 OR user_id::text = $1)", user_id)
                if has_metrics:
                    data_points += 1
                has_nevedal = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM nevedal_metrics WHERE user_id::text = $1)", user_id)
                if has_nevedal:
                    data_points += 1
                sess_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM coaching_sessions WHERE client_id = $1", user_id)
                if (sess_count or 0) >= 5:
                    data_points += 1
                has_coherence = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM coherence_measurements WHERE user_id::text = $1)", user_id)
                if has_coherence:
                    data_points += 1
                has_checkins = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM nate_checkin_log WHERE user_id = $1)", user_id)
                if has_checkins:
                    data_points += 1
        except Exception:
            pass
        return round(max(20.0, (data_points / max_points) * 100.0), 1)

    def _identify_top_amplifiers(self, components: Dict) -> List[Dict]:
        amp_keys = ["context_amplifiers", "intervention_optimization", "population_baseline"]
        results = []
        for k in amp_keys:
            v = components.get(k, 0)
            if v > 0.6:
                results.append({"factor": k, "score": v, "impact": "positive"})
        return sorted(results, key=lambda x: x["score"], reverse=True)[:3]

    def _identify_top_resistances(self, components: Dict) -> List[Dict]:
        res_keys = ["environmental_resistance", "unconscious_sabotage"]
        results = []
        for k in res_keys:
            v = components.get(k, 0)
            if v > 0.4:
                results.append({"factor": k, "score": v, "impact": "negative"})
        return sorted(results, key=lambda x: x["score"], reverse=True)[:3]

    # =========================================================================
    # UNIFIED DASHBOARD
    # =========================================================================

    async def generate_unified_dashboard(self, user_id: str, family_id: Optional[str] = None,
                                          goals: Optional[List[str]] = None) -> Dict[str, Any]:
        therapeutic = await self.calculate_unified_therapeutic_probability(user_id)
        coaching = await self.calculate_realtime_coaching_score(user_id)

        family_pred = None
        if family_id:
            family_pred = await self.predict_family_effectiveness(family_id)

        habit_forecasts = []
        for g in (goals or []):
            hf = await self.predict_habit_success_timeline(user_id, g)
            habit_forecasts.append(hf)

        cycle_data = None
        if self._cycle_engine:
            try:
                cycle_data = await self._cycle_engine.detect_cycles(user_id)
            except Exception:
                pass

        return {
            "individual_therapeutic_success": therapeutic,
            "real_time_coaching": coaching,
            "family_system_prediction": family_pred,
            "habit_forecasts": habit_forecasts,
            "cycle_analysis": cycle_data,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
