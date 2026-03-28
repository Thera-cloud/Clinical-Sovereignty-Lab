"""
SOVEREIGN SWARM — 5-Layer Coherence Engine
Extends the Nevedal Engine's individual CEE detection into a full
multi-layer coherence measurement system.

Layers:
    1. Individual   — Per-user C_emo aggregation + quiz + behavioral signals
    2. Family       — Family system resonance across related members
    3. Community    — Aggregate of 50+ family systems (geo/demographic)
    4. Cultural     — Internal therapeutic vs. external SkyEye gap
    5. Global       — Planetary emotional weather report

Theoretical Basis:
    - Layer 1 (Individual): Emotional coherence measurement draws on affective neuroscience
      (Damasio, 1994) and the somatic marker hypothesis.
    - Layer 2 (Family): Bowen Family Systems Theory (Bowen, 1978) — differentiation of self,
      multigenerational transmission process, and family emotional system.
    - Layer 3 (Community): Social Identity Theory (Tajfel & Turner, 1979) — group cohesion,
      in-group solidarity, and collective identity coherence.
    - Layer 4 (Cultural): Hofstede Cultural Dimensions (Hofstede, 1980, 2001) — cultural
      incoherence index measuring alignment between internal therapeutic values and external
      cultural messaging.
    - Layer 5 (Global): Multi-scale coherence synthesis (Nevedal, 2026) — weighted integration
      across all ecological layers of human experience.

    References:
        Bowen, M. (1978). Family Therapy in Clinical Practice. Jason Aronson.
        Damasio, A. (1994). Descartes' Error: Emotion, Reason, and the Human Brain.
        Hofstede, G. (2001). Culture's Consequences (2nd ed.). Sage Publications.
        Tajfel, H. & Turner, J.C. (1979). An Integrative Theory of Intergroup Conflict.

Phase 2A — Code Guidelines Section V.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import numpy as np

from app.models.coherence import (
    CoherenceGap,
    CoherenceLayer,
    CoherenceMeasurement,
    LayerThresholds,
    PulseSnapshot,
)
from app.services.exceptions import CoherenceException, InsufficientDataException

logger = logging.getLogger(__name__)


class CoherenceEngine:
    """
    Multi-layer coherence measurement engine.

    Usage:
        engine = CoherenceEngine(db_pool)
        measurement = await engine.measure_individual(user_id=42)
        snapshot = await engine.generate_pulse_snapshot()
    """

    def __init__(self, db_pool, thresholds: Optional[LayerThresholds] = None):
        self.db_pool = db_pool
        self.thresholds = thresholds or LayerThresholds()

    # =========================================================================
    # LAYER 1 — INDIVIDUAL COHERENCE
    # =========================================================================

    async def measure_individual(self, user_id) -> CoherenceMeasurement:
        """
        Aggregate per-user C_emo measurements, quiz response signals,
        and behavioral indicators from session patterns.
        """
        async with self.db_pool.acquire() as conn:
            # 1. C_emo from nevedal_metrics (last 30 days)
            metrics = await conn.fetch("""
                SELECT c_emo, cee_window, recorded_at
                FROM nevedal_metrics
                WHERE user_id = $1 AND recorded_at > NOW() - INTERVAL '30 days'
                ORDER BY recorded_at DESC
            """, user_id)

            # 2. Quiz response signals (responses is JSONB, compute avg of scale answers)
            quiz_rows = await conn.fetch("""
                SELECT qr.responses, qr.created_at
                FROM quiz_responses qr
                WHERE qr.user_id = $1 AND qr.created_at > NOW() - INTERVAL '30 days'
                ORDER BY qr.created_at DESC
            """, user_id)

            # 3. Session frequency / consistency
            sessions = await conn.fetch("""
                SELECT id, started_at, ended_at
                FROM sessions
                WHERE user_id = $1 AND started_at > NOW() - INTERVAL '30 days'
                ORDER BY started_at DESC
            """, user_id)

        if not metrics and not quiz_rows and not sessions:
            # No data at all — cannot produce any meaningful measurement
            raise InsufficientDataException(
                layer="individual",
                required=self.thresholds.individual_min_sessions,
                available=0,
            )
        elif len(metrics) < self.thresholds.individual_min_sessions:
            # Sparse data — produce measurement with low confidence (no exception)
            pass

        # Compute components
        cee_values = [float(m["c_emo"]) for m in metrics if m["c_emo"] is not None]
        cee_aggregate = float(np.mean(cee_values)) if cee_values else 0.0
        cee_aggregate = max(0.0, min(1.0, cee_aggregate))

        cee_count = sum(1 for m in metrics if m.get("cee_window"))
        cee_ratio = cee_count / max(len(metrics), 1)

        # Compute quiz signal from JSONB responses (average scale-type answers)
        quiz_values = []
        for qr in quiz_rows:
            responses = qr["responses"]
            if isinstance(responses, str):
                responses = json.loads(responses)
            for r in (responses or []):
                if r.get("type") == "scale" and r.get("answer") is not None:
                    try:
                        quiz_values.append(float(r["answer"]))
                    except (ValueError, TypeError):
                        pass
        quiz_signal = float(np.mean(quiz_values)) / 10.0 if quiz_values else 0.5
        quiz_signal = max(0.0, min(1.0, quiz_signal))

        session_count = len(sessions)
        behavioral = min(1.0, session_count / 12.0)  # 12 sessions/month = 1.0

        # Weighted composite (weights from swarm_config)
        from app.swarm_config import swarm_settings
        _iw = swarm_settings.COHERENCE_INDIVIDUAL_WEIGHTS
        score = (
            _iw["cee_aggregate"] * cee_aggregate +
            _iw["cee_ratio"] * cee_ratio +
            _iw["quiz_signal"] * quiz_signal +
            _iw["behavioral"] * behavioral
        )
        score = max(0.0, min(1.0, score))

        confidence = min(1.0, len(metrics) / 10.0)

        # Delta calculations
        delta_24h = await self._calculate_delta(
            CoherenceLayer.INDIVIDUAL, score, hours=24, user_id=user_id
        )
        delta_7d = await self._calculate_delta(
            CoherenceLayer.INDIVIDUAL, score, hours=168, user_id=user_id
        )

        measurement = CoherenceMeasurement(
            layer=CoherenceLayer.INDIVIDUAL,
            score=round(score, 4),
            confidence=round(confidence, 2),
            user_id=user_id,
            components={
                "cee_aggregate": round(cee_aggregate, 4),
                "cee_ratio": round(cee_ratio, 4),
                "quiz_signal": round(quiz_signal, 4),
                "behavioral": round(behavioral, 4),
            },
            delta_24h=delta_24h,
            delta_7d=delta_7d,
            sample_size=len(metrics),
        )

        await self._store_measurement(measurement)
        return measurement

    # =========================================================================
    # LAYER 2 — FAMILY SYSTEM COHERENCE
    # =========================================================================

    async def measure_family(self, family_id) -> CoherenceMeasurement:
        """
        Calculate family system coherence by examining correlated
        coherence movements across family members, enriched with
        Sanctuary emotional weather data when available.
        """
        async with self.db_pool.acquire() as conn:
            # Get family members
            members = await conn.fetch("""
                SELECT u.id, u.name
                FROM users u
                WHERE u.family_id = $1
            """, family_id)

            if len(members) < self.thresholds.family_min_members:
                raise InsufficientDataException(
                    layer="family", required=self.thresholds.family_min_members,
                    available=len(members)
                )

        # Get individual coherence for each member
        member_scores = []
        for member in members:
            try:
                latest = await self._get_latest_measurement(
                    CoherenceLayer.INDIVIDUAL, user_id=member["id"]
                )
                if latest:
                    member_scores.append(latest["score"])
            except Exception as e:
                logger.debug("DB query _get_latest_measurement for family member: %s", e)

        if len(member_scores) < 2:
            raise InsufficientDataException(
                layer="family", required=2, available=len(member_scores)
            )

        # System resonance — correlation of individual scores
        scores_array = np.array(member_scores)
        mean_score = float(np.mean(scores_array))
        variance = float(np.var(scores_array))

        # Low variance among family members = high resonance
        resonance = 1.0 - min(1.0, variance * 4)  # scale factor

        # Pattern transmission rate (parent→child coherence correlation)
        transmission = mean_score  # simplified: avg family coherence

        # Interruption efficacy (improvement trend)
        efficacy = await self._measure_family_improvement(family_id)

        # Emotional weather enrichment from Sanctuary sessions
        weather_data = await self._get_sanctuary_weather_enrichment(str(family_id))

        from app.swarm_config import swarm_settings
        _fw = swarm_settings.COHERENCE_FAMILY_WEIGHTS

        if weather_data and weather_data["session_count"] > 0:
            # Blend individual-metric score with relational Sanctuary data.
            # Weather enrichment modulates resonance and adds a relational signal.
            sanctuary_coherence = weather_data["avg_system_coherence"]
            sanctuary_volatility = weather_data["avg_volatility"]
            cee_frequency = weather_data["cee_frequency"]

            # Relational resonance: blend dyadic weather coherence with individual variance
            relational_resonance = (resonance * 0.6) + (sanctuary_coherence * 0.4)
            # Volatility penalty: high volatility reduces effective resonance
            volatility_dampener = max(0.0, 1.0 - sanctuary_volatility * 2.0)
            relational_resonance *= (0.7 + 0.3 * volatility_dampener)
            # CEE windows in relational context boost efficacy
            relational_efficacy = efficacy + (cee_frequency * 0.15)
            relational_efficacy = min(1.0, relational_efficacy)

            score = (
                _fw["mean_score"] * mean_score +
                _fw["resonance"] * relational_resonance +
                _fw["transmission"] * transmission +
                _fw["efficacy"] * relational_efficacy
            )
        else:
            score = (
                _fw["mean_score"] * mean_score +
                _fw["resonance"] * resonance +
                _fw["transmission"] * transmission +
                _fw["efficacy"] * efficacy
            )

        score = max(0.0, min(1.0, score))
        confidence = min(1.0, len(member_scores) / 4.0)
        if weather_data and weather_data["session_count"] > 0:
            confidence = min(1.0, confidence + 0.1)

        delta_24h = await self._calculate_delta(
            CoherenceLayer.FAMILY, score, hours=24, family_id=family_id
        )

        components = {
            "mean_individual": round(mean_score, 4),
            "resonance": round(resonance, 4),
            "transmission": round(transmission, 4),
            "efficacy": round(efficacy, 4),
            "member_count": len(member_scores),
        }

        if weather_data and weather_data["session_count"] > 0:
            components["sanctuary_sessions"] = weather_data["session_count"]
            components["sanctuary_avg_coherence"] = round(weather_data["avg_system_coherence"], 4)
            components["sanctuary_avg_volatility"] = round(weather_data["avg_volatility"], 4)
            components["sanctuary_cee_frequency"] = round(weather_data["cee_frequency"], 4)
            components["relational_resonance"] = round(
                (resonance * 0.6) + (weather_data["avg_system_coherence"] * 0.4), 4
            )

        measurement = CoherenceMeasurement(
            layer=CoherenceLayer.FAMILY,
            score=round(score, 4),
            confidence=round(confidence, 2),
            family_id=family_id,
            components=components,
            delta_24h=delta_24h,
            sample_size=len(member_scores),
        )

        await self._store_measurement(measurement)
        return measurement

    # =========================================================================
    # LAYER 3 — COMMUNITY COHERENCE
    # =========================================================================

    async def measure_community(self, community_id: str = "default") -> CoherenceMeasurement:
        """
        Aggregate family system coherence across 50+ family systems.
        Identifies shared emotional themes and collective trauma signatures.
        """
        async with self.db_pool.acquire() as conn:
            # Get all family measurements from last 7 days
            rows = await conn.fetch("""
                SELECT score, components, family_id
                FROM coherence_measurements
                WHERE layer = 'family' AND measured_at > NOW() - INTERVAL '7 days'
                ORDER BY measured_at DESC
            """)

        # Deduplicate by family (latest only)
        seen_families = set()
        family_scores = []
        for r in rows:
            fid = r["family_id"]
            if fid and fid not in seen_families:
                seen_families.add(fid)
                family_scores.append(float(r["score"]))

        if len(family_scores) < self.thresholds.community_min_families:
            raise InsufficientDataException(
                layer="community",
                required=self.thresholds.community_min_families,
                available=len(family_scores),
            )

        scores_array = np.array(family_scores)
        mean_score = float(np.mean(scores_array))
        std_score = float(np.std(scores_array))

        # Community coherence: high mean + low spread = coherent
        cohesion = 1.0 - min(1.0, std_score * 3)
        from app.swarm_config import swarm_settings
        _cw = swarm_settings.COHERENCE_COMMUNITY_WEIGHTS
        score = _cw["mean_score"] * mean_score + _cw["cohesion"] * cohesion
        score = max(0.0, min(1.0, score))
        confidence = min(1.0, len(family_scores) / 100.0)

        measurement = CoherenceMeasurement(
            layer=CoherenceLayer.COMMUNITY,
            score=round(score, 4),
            confidence=round(confidence, 2),
            community_id=community_id,
            components={
                "mean_family": round(mean_score, 4),
                "cohesion": round(cohesion, 4),
                "std_deviation": round(std_score, 4),
                "family_count": len(family_scores),
            },
            sample_size=len(family_scores),
        )

        await self._store_measurement(measurement)
        return measurement

    # =========================================================================
    # LAYER 4 — CULTURAL COHERENCE (Inside/Outside Gap)
    # =========================================================================

    async def measure_cultural(self, cultural_context: str = "general") -> CoherenceMeasurement:
        """
        Bridge internal therapeutic data (Layers 1-3) with external SkyEye
        sentiment signals. Calculate the Cultural Incoherence Index.
        """
        # Internal signal: latest community coherence
        internal_score = 0.5
        try:
            internal = await self._get_latest_measurement(CoherenceLayer.COMMUNITY)
            if internal:
                internal_score = internal["score"]
        except Exception as e:
            logger.debug("DB query _get_latest_measurement community: %s", e)

        # External signal: SkyEye sentiment analysis
        external_score = await self._get_skyeye_sentiment()

        # Gap = internal - external (positive = we're more coherent than public narrative)
        gap = internal_score - external_score
        gap_magnitude = abs(gap)

        # Cultural coherence: alignment between internal and external
        score = 1.0 - gap_magnitude
        score = max(0.0, min(1.0, score))

        # Confidence depends on data availability
        confidence = 0.3  # base confidence, increases with more data

        gap_analysis = CoherenceGap(
            internal_score=round(internal_score, 4),
            external_score=round(external_score, 4),
            gap_magnitude=round(gap, 4),
            cultural_context=cultural_context,
        )

        measurement = CoherenceMeasurement(
            layer=CoherenceLayer.CULTURAL,
            score=round(score, 4),
            confidence=round(confidence, 2),
            cultural_context=cultural_context,
            components={
                "internal": round(internal_score, 4),
                "external": round(external_score, 4),
                "gap": round(gap, 4),
                "gap_magnitude": round(gap_magnitude, 4),
            },
            sample_size=1,
        )

        await self._store_measurement(measurement)
        return measurement

    # =========================================================================
    # LAYER 5 — GLOBAL COHERENCE
    # =========================================================================

    async def measure_global(self) -> CoherenceMeasurement:
        """
        Synthesize all lower layers + cross-platform SkyEye monitoring
        into a probabilistic emotional weather report.
        """
        layer_scores = {}

        # Collect latest from each lower layer
        for layer in [CoherenceLayer.INDIVIDUAL, CoherenceLayer.FAMILY,
                       CoherenceLayer.COMMUNITY, CoherenceLayer.CULTURAL]:
            try:
                latest = await self._get_latest_aggregate(layer)
                if latest is not None:
                    layer_scores[layer.value] = latest
            except Exception as e:
                logger.debug("DB query _get_latest_aggregate for layer %s: %s", layer.value, e)

        if not layer_scores:
            layer_scores = {"individual": 0.5}

        # Weighted synthesis
        from app.swarm_config import swarm_settings
        weights = swarm_settings.COHERENCE_GLOBAL_WEIGHTS
        weighted_sum = 0.0
        total_weight = 0.0
        for layer_name, score in layer_scores.items():
            w = weights.get(layer_name, 0.25)
            weighted_sum += w * score
            total_weight += w

        global_score = weighted_sum / total_weight if total_weight > 0 else 0.5
        global_score = max(0.0, min(1.0, global_score))

        confidence = min(1.0, len(layer_scores) / 4.0)

        measurement = CoherenceMeasurement(
            layer=CoherenceLayer.GLOBAL,
            score=round(global_score, 4),
            confidence=round(confidence, 2),
            components=layer_scores,
            sample_size=len(layer_scores),
        )

        await self._store_measurement(measurement)
        return measurement

    # =========================================================================
    # INSIDE/OUTSIDE GAP ANALYSIS
    # =========================================================================

    async def compute_gap_analysis(self) -> CoherenceGap:
        """Compute the inside/outside coherence gap with trending themes."""
        internal_score = 0.5
        try:
            internal = await self._get_latest_aggregate(CoherenceLayer.INDIVIDUAL)
            if internal is not None:
                internal_score = internal
        except Exception as e:
            logger.debug("DB query _get_latest_aggregate individual: %s", e)

        external_score = await self._get_skyeye_sentiment()
        gap = internal_score - external_score

        # Get trending themes from SkyEye
        external_themes = await self._get_external_themes()
        internal_themes = await self._get_internal_themes()

        # Statistical significance (simplified — based on sample sizes)
        significance = min(0.95, 0.3 + abs(gap) * 2)

        return CoherenceGap(
            internal_score=round(internal_score, 4),
            external_score=round(external_score, 4),
            gap_magnitude=round(gap, 4),
            statistical_significance=round(significance, 2),
            trending_themes_internal=internal_themes,
            trending_themes_external=external_themes,
        )

    # =========================================================================
    # PULSE SNAPSHOT (for dashboard)
    # =========================================================================

    async def generate_pulse_snapshot(self) -> PulseSnapshot:
        """Generate aggregated data for The Pulse dashboard."""
        # Measure global (which cascades through all layers)
        try:
            global_m = await self.measure_global()
            global_index = global_m.score
            layer_scores = global_m.components
        except Exception as e:
            logger.debug("DB query measure_global: %s", e)
            global_index = 0.0
            layer_scores = {}

        # Gap analysis
        try:
            gap = await self.compute_gap_analysis()
        except Exception as e:
            logger.debug("DB query compute_gap_analysis: %s", e)
            gap = None

        # Active foresight alerts
        alert_count = 0
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) as cnt FROM foresight_alerts WHERE resolved_at IS NULL"
                )
                alert_count = row["cnt"] if row else 0
        except Exception as e:
            logger.debug("DB query foresight_alerts count: %s", e)

        # Notable changes
        notable = await self._detect_notable_changes()

        # Trending themes
        themes = await self._get_internal_themes()

        return PulseSnapshot(
            global_coherence_index=round(global_index, 4),
            layer_scores=layer_scores,
            trending_themes=themes,
            gap_analysis=gap,
            active_alerts=alert_count,
            notable_changes=notable,
        )

    # =========================================================================
    # COHERENCE BRIEFING GENERATION
    # =========================================================================

    async def generate_briefing(self, persist: bool = True) -> Dict[str, Any]:
        """
        Generate a periodic coherence briefing (for Strategic Memory Layer 4).
        If persist=True, stores the briefing in Strategic Memory automatically.
        """
        now = datetime.utcnow()
        period_start = now - timedelta(hours=24)

        snapshot = await self.generate_pulse_snapshot()

        briefing = {
            "period_start": period_start,
            "period_end": now,
            "global_coherence_index": snapshot.global_coherence_index,
            "layer_summaries": snapshot.layer_scores,
            "trending_themes": snapshot.trending_themes,
            "gap_analysis_summary": (
                f"Internal: {snapshot.gap_analysis.internal_score:.2f}, "
                f"External: {snapshot.gap_analysis.external_score:.2f}, "
                f"Gap: {snapshot.gap_analysis.gap_magnitude:+.2f}"
                if snapshot.gap_analysis else "Insufficient data"
            ),
            "notable_changes": snapshot.notable_changes,
            "recommendations": [],
        }

        # Persist to Strategic Memory Layer 4
        if persist:
            try:
                from app.services.strategic_memory import StrategicMemoryService
                memory = StrategicMemoryService(self.db_pool)
                await memory.store_coherence_briefing(briefing)
            except Exception as e:
                print(f">>> [COHERENCE] Failed to store briefing: {e}")

        return briefing

    # =========================================================================
    # PRIVATE HELPERS
    # =========================================================================

    async def _store_measurement(self, m: CoherenceMeasurement) -> None:
        """Persist a coherence measurement."""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO coherence_measurements
                        (measurement_id, layer, score, confidence, user_id, family_id,
                         community_id, cultural_context, region, components,
                         delta_24h, delta_7d, sample_size, metadata, measured_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                """, m.measurement_id, m.layer.value, m.score, m.confidence,
                     m.user_id, m.family_id, m.community_id, m.cultural_context,
                     m.region, json.dumps(m.components),
                     m.delta_24h, m.delta_7d, m.sample_size,
                     json.dumps(m.metadata), m.measured_at)
        except Exception as e:
            print(f">>> [COHERENCE] Failed to store measurement: {e}")

    async def _get_latest_measurement(
        self, layer: CoherenceLayer, user_id=None,
        family_id=None,
    ) -> Optional[Dict]:
        async with self.db_pool.acquire() as conn:
            if user_id:
                row = await conn.fetchrow("""
                    SELECT * FROM coherence_measurements
                    WHERE layer = $1 AND user_id = $2
                    ORDER BY measured_at DESC LIMIT 1
                """, layer.value, user_id)
            elif family_id:
                row = await conn.fetchrow("""
                    SELECT * FROM coherence_measurements
                    WHERE layer = $1 AND family_id = $2
                    ORDER BY measured_at DESC LIMIT 1
                """, layer.value, family_id)
            else:
                row = await conn.fetchrow("""
                    SELECT * FROM coherence_measurements
                    WHERE layer = $1
                    ORDER BY measured_at DESC LIMIT 1
                """, layer.value)
            return dict(row) if row else None

    async def _get_latest_aggregate(self, layer: CoherenceLayer) -> Optional[float]:
        """Get average score for a layer from the last 24h."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT AVG(score) as avg_score
                FROM coherence_measurements
                WHERE layer = $1 AND measured_at > NOW() - INTERVAL '24 hours'
            """, layer.value)
            if row and row["avg_score"] is not None:
                return float(row["avg_score"])
            # Fallback to latest
            row = await conn.fetchrow("""
                SELECT score FROM coherence_measurements
                WHERE layer = $1
                ORDER BY measured_at DESC LIMIT 1
            """, layer.value)
            return float(row["score"]) if row else None

    async def _calculate_delta(
        self, layer: CoherenceLayer, current_score: float,
        hours: int = 24, user_id=None,
        family_id=None,
    ) -> Optional[float]:
        """Calculate change from N hours ago."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        async with self.db_pool.acquire() as conn:
            conditions = ["layer = $1", "measured_at <= $2"]
            params: list = [layer.value, cutoff]
            idx = 3
            if user_id:
                conditions.append(f"user_id = ${idx}")
                params.append(user_id)
                idx += 1
            if family_id:
                conditions.append(f"family_id = ${idx}")
                params.append(family_id)
                idx += 1

            where = " AND ".join(conditions)
            row = await conn.fetchrow(
                f"SELECT score FROM coherence_measurements WHERE {where} "
                f"ORDER BY measured_at DESC LIMIT 1", *params
            )
            if row:
                return round(current_score - float(row["score"]), 4)
        return None

    async def _measure_family_improvement(self, family_id) -> float:
        """Measure improvement trend in family coherence over 30 days.
        Returns 0.5 (neutral) when insufficient data to compute a trend.
        """
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT score, measured_at
                    FROM coherence_measurements
                    WHERE layer = 'family' AND family_id = $1
                      AND measured_at > NOW() - INTERVAL '30 days'
                    ORDER BY measured_at ASC
                """, family_id)

            if len(rows) < 2:
                return 0.5  # neutral — insufficient data for trend

            scores = [float(r["score"]) for r in rows]
            first_half = np.mean(scores[:len(scores)//2])
            second_half = np.mean(scores[len(scores)//2:])
            improvement = second_half - first_half
            return max(0.0, min(1.0, 0.5 + improvement))
        except Exception as e:
            logger.warning("Family improvement measurement error: %s", e)
            return 0.5  # neutral fallback on error

    async def _get_sanctuary_weather_enrichment(self, family_id: str) -> Optional[dict]:
        """Pull aggregate Sanctuary weather data from emotional_weather_snapshots.
        Returns None if no Sanctuary sessions exist for this family.
        """
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT
                        COUNT(*) as snapshot_count,
                        COUNT(DISTINCT sanctuary_id) as session_count,
                        AVG(system_coherence) as avg_system_coherence,
                        AVG(system_volatility) as avg_volatility,
                        SUM(CASE WHEN cee_window_open THEN 1 ELSE 0 END) as cee_count
                    FROM emotional_weather_snapshots
                    WHERE family_id = $1
                      AND created_at > NOW() - INTERVAL '90 days'
                """, family_id)

            if not row or row["session_count"] == 0:
                return None

            return {
                "snapshot_count": row["snapshot_count"],
                "session_count": row["session_count"],
                "avg_system_coherence": float(row["avg_system_coherence"] or 0),
                "avg_volatility": float(row["avg_volatility"] or 0),
                "cee_frequency": row["cee_count"] / max(row["snapshot_count"], 1),
            }
        except Exception as e:
            logger.debug("Sanctuary weather enrichment query: %s", e)
            return None

    async def _get_skyeye_sentiment(self) -> float:
        """Get aggregate sentiment from SkyEye social media monitoring."""
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT AVG(
                        CASE WHEN metadata::jsonb ? 'sentiment'
                        THEN (metadata::jsonb->>'sentiment')::float
                        ELSE 0.5 END
                    ) as avg_sentiment
                    FROM skyeye_activity
                    WHERE created_at > NOW() - INTERVAL '7 days'
                """)
                if row and row["avg_sentiment"] is not None:
                    return max(0.0, min(1.0, float(row["avg_sentiment"])))
        except Exception as e:
            logger.debug("DB query SkyEye sentiment: %s", e)
        return 0.5  # neutral default

    async def _get_external_themes(self) -> List[str]:
        """Extract trending themes from SkyEye activity."""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT type, COUNT(*) as cnt
                    FROM skyeye_activity
                    WHERE created_at > NOW() - INTERVAL '7 days'
                    GROUP BY type
                    ORDER BY cnt DESC LIMIT 5
                """)
                return [r["type"] for r in rows if r["type"]]
        except Exception as e:
            logger.debug("DB query external themes: %s", e)
            return []

    async def _get_internal_themes(self) -> List[str]:
        """Extract trending themes from session data and insights."""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT DISTINCT unnest(tags) as theme, COUNT(*) as cnt
                    FROM insight_log
                    WHERE created_at > NOW() - INTERVAL '7 days'
                    GROUP BY theme
                    ORDER BY cnt DESC LIMIT 5
                """)
                return [r["theme"] for r in rows if r["theme"]]
        except Exception as e:
            logger.debug("DB query internal themes: %s", e)
            return []

    async def _detect_notable_changes(self) -> List[str]:
        """Detect notable changes across all layers in the last 24h."""
        changes = []
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT layer, score, delta_24h
                    FROM coherence_measurements
                    WHERE measured_at > NOW() - INTERVAL '24 hours'
                      AND delta_24h IS NOT NULL
                      AND ABS(delta_24h) > 0.1
                    ORDER BY ABS(delta_24h) DESC
                    LIMIT 5
                """)
                for r in rows:
                    direction = "increased" if r["delta_24h"] > 0 else "decreased"
                    changes.append(
                        f"{r['layer'].capitalize()} coherence {direction} by "
                        f"{abs(r['delta_24h']):.2f} (now {r['score']:.2f})"
                    )
        except Exception as e:
            logger.debug("DB query notable changes: %s", e)
        return changes
