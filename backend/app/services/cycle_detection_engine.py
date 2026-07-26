"""
Generalized Cycle Detection Engine.

Detects, tracks, and predicts 12 behavioral/psychological/sociological cycle domains
using time-series spectral analysis (FFT, autocorrelation). One engine, 12 domain
configurations, same analysis pipeline.

Integrates into SovereignPredictiveEngine as the Temporal Intelligence layer.
"""

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


def _as_utc_dt(value: Any) -> Optional[datetime]:
    """Coerce isoformat strings / datetimes for asyncpg timestamptz params."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            s = value.strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None
    return None


# =============================================================================
# DOMAIN CONFIGURATION
# =============================================================================

@dataclass
class CycleDomainConfig:
    domain_id: str
    display_name: str
    data_sources: List[Dict[str, str]]
    nlp_keywords: List[str] = field(default_factory=list)
    peak_is_risk: bool = True
    min_observations: int = 28
    sensitivity: float = 0.5
    description: str = ""


CYCLE_DOMAINS: Dict[str, CycleDomainConfig] = {
    "addiction": CycleDomainConfig(
        domain_id="addiction",
        display_name="Addiction Cycles",
        data_sources=[{"table": "conversation_history", "mode": "nlp"}],
        nlp_keywords=["craving", "relapse", "using", "sober", "clean", "drink",
                       "substance", "withdrawal", "tempt", "high", "fix", "dose"],
        peak_is_risk=True,
        description="Substance and behavioral addiction cycle detection",
    ),
    "sexual_desire": CycleDomainConfig(
        domain_id="sexual_desire",
        display_name="Sexual Desire Cycles",
        data_sources=[{"table": "conversation_history", "mode": "nlp"}],
        nlp_keywords=["desire", "intimacy", "arousal", "urge", "attraction",
                       "libido", "sexual", "passion", "longing"],
        peak_is_risk=False,
        description="Natural desire cycle detection for therapeutic context",
    ),
    "harm_risk": CycleDomainConfig(
        domain_id="harm_risk",
        display_name="Harm Risk Cycles",
        data_sources=[{"table": "client_metrics", "column": "crisis_count", "mode": "numeric"},
                      {"table": "client_metrics", "column": "shame_profile", "jsonb_key": "shame_index", "mode": "jsonb"}],
        peak_is_risk=True,
        sensitivity=0.7,
        description="Self-harm and violence risk cycle patterns",
    ),
    "criminal_intent": CycleDomainConfig(
        domain_id="criminal_intent",
        display_name="Criminal Intention Cycles",
        data_sources=[{"table": "conversation_history", "mode": "nlp"}],
        nlp_keywords=["anger", "revenge", "hurt them", "violent", "weapon",
                       "steal", "plan", "attack", "kill", "fight", "payback"],
        peak_is_risk=True,
        sensitivity=0.8,
        description="Criminal intention escalation cycle detection",
    ),
    "legacy": CycleDomainConfig(
        domain_id="legacy",
        display_name="Transgenerational Legacy Cycles",
        data_sources=[{"table": "client_metrics", "column": "pmb", "jsonb_key": "legacy_depth", "mode": "jsonb"}],
        peak_is_risk=True,
        min_observations=90,
        description="Transgenerational pattern reactivation cycles",
    ),
    "porn_addiction": CycleDomainConfig(
        domain_id="porn_addiction",
        display_name="Porn Addiction Cycles",
        data_sources=[{"table": "conversation_history", "mode": "nlp"}],
        nlp_keywords=["porn", "explicit", "watched", "browsing", "sites",
                       "images", "video", "screen time", "masturbat", "compulsive"],
        peak_is_risk=True,
        description="Pornography addiction cycle detection",
    ),
    "emotional_state": CycleDomainConfig(
        domain_id="emotional_state",
        display_name="Emotional State Cycles",
        data_sources=[{"table": "client_metrics", "column": "anxiety_level", "mode": "numeric"},
                      {"table": "client_metrics", "column": "stress_level", "mode": "numeric"},
                      {"table": "client_metrics", "column": "c_emo", "mode": "numeric"}],
        peak_is_risk=True,
        min_observations=14,
        description="Mood, anxiety, stress, and depression oscillation cycles",
    ),
    "financial": CycleDomainConfig(
        domain_id="financial",
        display_name="Financial Spending Cycles",
        data_sources=[{"table": "conversation_history", "mode": "nlp"}],
        nlp_keywords=["money", "spending", "debt", "bills", "budget",
                       "impulse buy", "financial", "broke", "shopping", "overspend"],
        peak_is_risk=True,
        description="Financial stress and impulse spending cycle detection",
    ),
    "coping": CycleDomainConfig(
        domain_id="coping",
        display_name="Coping Mechanism Cycles",
        data_sources=[{"table": "client_metrics", "column": "pmb", "jsonb_key": "reactivity_type", "mode": "jsonb"},
                      {"table": "client_metrics", "column": "homework_completion_rate", "mode": "numeric"}],
        peak_is_risk=False,
        description="Adaptive vs maladaptive coping pattern cycling",
    ),
    "economic": CycleDomainConfig(
        domain_id="economic",
        display_name="Economic Macro/Micro Cycles",
        data_sources=[{"table": "cycle_observations", "mode": "manual"}],
        peak_is_risk=True,
        min_observations=90,
        description="External economic cycle impact on therapeutic progress",
    ),
    "cultural": CycleDomainConfig(
        domain_id="cultural",
        display_name="Cultural/Religious Cycles",
        data_sources=[{"table": "conversation_history", "mode": "nlp"}],
        nlp_keywords=["church", "faith", "belief", "congregation", "pastor",
                       "spiritual", "doctrine", "cult", "religion", "prayer",
                       "worship", "sin", "salvation", "fellowship", "scripture"],
        peak_is_risk=False,
        description="Religious, spiritual, and cult movement cycle detection",
    ),
    "group_dynamics": CycleDomainConfig(
        domain_id="group_dynamics",
        display_name="Group Dynamic Cycles",
        data_sources=[{"table": "emotional_weather_snapshots", "column": "system_coherence", "mode": "numeric"},
                      {"table": "emotional_weather_snapshots", "column": "system_volatility", "mode": "numeric"}],
        peak_is_risk=True,
        min_observations=14,
        description="Group coherence and conflict cycling patterns",
    ),
    "code_learning": CycleDomainConfig(
        domain_id="code_learning",
        display_name="Code Intelligence Cycles",
        data_sources=[
            {"table": "nevedal_coherence_log", "column": "C_emo", "mode": "numeric"},
            {"table": "nevedal_coherence_log", "column": "gamma_env", "mode": "numeric"},
            {"table": "nevedal_coherence_log", "column": "p_ent", "mode": "numeric"},
        ],
        peak_is_risk=False,
        min_observations=14,
        sensitivity=0.4,
        description="Code intelligence growth cycles: C_emo oscillation, dual-brain disagreement frequency, knowledge density plateaus",
    ),
    # QUANTUM-CRYSTAL-ARCH — PGSD field rhythm domain
    "pgsd_field": CycleDomainConfig(
        domain_id="pgsd_field",
        display_name="PGSD Field Cycles",
        data_sources=[
            {"table": "pgsd_snapshots", "column": "coherence", "mode": "numeric"},
            {"table": "pgsd_snapshots", "column": "d1_valence", "mode": "numeric"},
            {"table": "pgsd_snapshots", "column": "d5_integration", "mode": "numeric"},
        ],
        peak_is_risk=False,
        min_observations=7,
        sensitivity=0.45,
        description="PGSD emotional GPS rhythm: coherence and 5D coordinate oscillations",
    ),
}


# =============================================================================
# SPECTRAL ANALYZER
# =============================================================================

class SpectralAnalyzer:
    """Applies FFT and autocorrelation to detect dominant periods in time series."""

    @staticmethod
    def analyze(values: np.ndarray, sensitivity: float = 0.5) -> List[Dict[str, Any]]:
        if len(values) < 7:
            return []

        detrended = SpectralAnalyzer._detrend(values)
        fft_result = np.fft.rfft(detrended)
        magnitudes = np.abs(fft_result)
        n = len(detrended)

        if len(magnitudes) < 3:
            return []
        magnitudes[0] = 0  # remove DC component

        median_mag = np.median(magnitudes[1:])
        threshold = max(median_mag * (2.0 + sensitivity), 0.1)

        cycles = []
        for i in range(1, len(magnitudes)):
            if magnitudes[i] > threshold:
                period_days = n / i
                if period_days < 2 or period_days > n * 0.8:
                    continue

                ac_conf = SpectralAnalyzer._autocorrelation_confirm(detrended, period_days)
                if ac_conf < 0.15:
                    continue

                phase = np.angle(fft_result[i])

                cycles.append({
                    "period_days": round(period_days, 2),
                    "amplitude": round(float(magnitudes[i]) / n, 4),
                    "phase_offset": round(float(phase), 4),
                    "confidence": round(min(ac_conf * 1.5, 0.99), 2),
                    "method": "fft+autocorrelation",
                })

        cycles.sort(key=lambda c: c["amplitude"], reverse=True)
        return cycles[:5]

    @staticmethod
    def _detrend(values: np.ndarray) -> np.ndarray:
        x = np.arange(len(values))
        coeffs = np.polyfit(x, values, 1)
        trend = np.polyval(coeffs, x)
        return values - trend

    @staticmethod
    def _autocorrelation_confirm(values: np.ndarray, period: float) -> float:
        lag = int(round(period))
        if lag < 1 or lag >= len(values):
            return 0.0
        n = len(values)
        mean = np.mean(values)
        var = np.var(values)
        if var < 1e-10:
            return 0.0
        autocorr = np.sum((values[:n - lag] - mean) * (values[lag:] - mean)) / (n * var)
        return max(float(autocorr), 0.0)


# =============================================================================
# PHASE TRACKER
# =============================================================================

class CyclePhaseTracker:
    """Determines current phase position within a detected cycle."""

    PHASES = ["rising", "peak", "falling", "trough"]

    @staticmethod
    def compute_phase(values: np.ndarray, period_days: float, phase_offset: float) -> Dict[str, Any]:
        if len(values) < 2:
            return {"phase": "unknown", "phase_angle": 0, "days_to_next_peak": 0}

        n = len(values)
        current_angle = (2 * math.pi * (n % period_days) / period_days) + phase_offset
        current_angle = current_angle % (2 * math.pi)

        quarter = 2 * math.pi / 4
        if current_angle < quarter:
            phase = "rising"
        elif current_angle < 2 * quarter:
            phase = "peak"
        elif current_angle < 3 * quarter:
            phase = "falling"
        else:
            phase = "trough"

        peak_angle = math.pi / 2
        if current_angle <= peak_angle:
            angle_to_peak = peak_angle - current_angle
        else:
            angle_to_peak = (2 * math.pi - current_angle) + peak_angle
        days_to_peak = angle_to_peak / (2 * math.pi) * period_days

        trough_angle = 3 * math.pi / 2
        if current_angle <= trough_angle:
            angle_to_trough = trough_angle - current_angle
        else:
            angle_to_trough = (2 * math.pi - current_angle) + trough_angle
        days_to_trough = angle_to_trough / (2 * math.pi) * period_days

        return {
            "phase": phase,
            "phase_angle": round(current_angle, 4),
            "days_to_next_peak": round(days_to_peak, 1),
            "days_to_next_trough": round(days_to_trough, 1),
            "position_in_cycle": round(current_angle / (2 * math.pi), 2),
        }


# =============================================================================
# PREDICTION GENERATOR
# =============================================================================

class CyclePredictionGenerator:
    """Projects next N peaks/troughs based on detected cycle parameters."""

    @staticmethod
    def generate_predictions(
        detected_cycles: List[Dict], domain: str, horizon_days: int = 30,
        peak_is_risk: bool = True
    ) -> List[Dict[str, Any]]:
        predictions = []
        now = datetime.now(timezone.utc)

        for cycle in detected_cycles:
            period = cycle["period_days"]
            phase_offset = cycle.get("phase_offset", 0)
            confidence = cycle["confidence"]
            amplitude = cycle["amplitude"]

            current_pos = (2 * math.pi * (0 % period) / period) + phase_offset
            peak_target = math.pi / 2
            trough_target = 3 * math.pi / 2

            for day_offset in range(1, horizon_days + 1):
                angle = (2 * math.pi * day_offset / period + phase_offset) % (2 * math.pi)

                if abs(angle - peak_target) < (math.pi / period):
                    event_type = "peak_risk" if peak_is_risk else "peak_opportunity"
                    event_time = now + timedelta(days=day_offset)
                    window_start = event_time - timedelta(days=max(period * 0.1, 1))
                    window_end = event_time + timedelta(days=max(period * 0.05, 0.5))
                    predictions.append({
                        "domain": domain,
                        "predicted_event": event_type,
                        "predicted_at": event_time.isoformat(),
                        "confidence": round(confidence * 0.9, 2),
                        "amplitude": amplitude,
                        "period_days": period,
                        "intervention_window_start": window_start.isoformat(),
                        "intervention_window_end": window_end.isoformat(),
                    })

                if abs(angle - trough_target) < (math.pi / period):
                    event_type = "trough_opportunity" if peak_is_risk else "trough_risk"
                    event_time = now + timedelta(days=day_offset)
                    predictions.append({
                        "domain": domain,
                        "predicted_event": event_type,
                        "predicted_at": event_time.isoformat(),
                        "confidence": round(confidence * 0.85, 2),
                        "amplitude": amplitude,
                        "period_days": period,
                    })

        predictions.sort(key=lambda p: p["predicted_at"])
        return predictions[:20]


# =============================================================================
# INTERVENTION WINDOW CALCULATOR
# =============================================================================

class InterventionWindowCalculator:
    """Identifies optimal intervention timing based on cycle predictions."""

    @staticmethod
    def calculate_windows(predictions: List[Dict], peak_is_risk: bool = True) -> List[Dict[str, Any]]:
        windows = []
        for pred in predictions:
            if peak_is_risk and "peak" in pred.get("predicted_event", ""):
                if "intervention_window_start" in pred:
                    windows.append({
                        "domain": pred["domain"],
                        "window_start": pred["intervention_window_start"],
                        "window_end": pred["intervention_window_end"],
                        "urgency": "high" if pred["confidence"] > 0.6 else "moderate",
                        "recommendation": f"Pre-emptive intervention before predicted {pred['domain']} peak",
                        "confidence": pred["confidence"],
                    })
            elif not peak_is_risk and "trough" in pred.get("predicted_event", ""):
                windows.append({
                    "domain": pred["domain"],
                    "window_start": pred["predicted_at"],
                    "urgency": "moderate",
                    "recommendation": f"Support session during predicted {pred['domain']} low point",
                    "confidence": pred["confidence"],
                })
        return windows


# =============================================================================
# RISK CONVERGENCE DETECTOR
# =============================================================================

class RiskConvergenceDetector:
    """Detects when multiple cycle peaks align within a time window."""

    @staticmethod
    def detect_convergence(
        all_predictions: Dict[str, List[Dict]], window_days: float = 3.0
    ) -> List[Dict[str, Any]]:
        risk_events = []
        for domain, preds in all_predictions.items():
            for p in preds:
                if "risk" in p.get("predicted_event", ""):
                    risk_events.append({
                        "domain": domain,
                        "predicted_at": p["predicted_at"],
                        "confidence": p["confidence"],
                    })

        if len(risk_events) < 2:
            return []

        risk_events.sort(key=lambda e: e["predicted_at"])
        convergences = []

        for i, event in enumerate(risk_events):
            cluster = [event]
            t_i = datetime.fromisoformat(event["predicted_at"].replace("Z", "+00:00"))
            for j in range(i + 1, len(risk_events)):
                t_j = datetime.fromisoformat(risk_events[j]["predicted_at"].replace("Z", "+00:00"))
                if (t_j - t_i).total_seconds() / 86400 <= window_days:
                    cluster.append(risk_events[j])

            if len(cluster) >= 2:
                domains = list(set(c["domain"] for c in cluster))
                if len(domains) >= 2:
                    avg_conf = sum(c["confidence"] for c in cluster) / len(cluster)
                    risk_score = min(avg_conf * len(domains) * 0.4, 1.0)
                    convergences.append({
                        "convergence_date": event["predicted_at"],
                        "converging_domains": domains,
                        "domain_count": len(domains),
                        "convergence_risk": round(risk_score, 2),
                        "avg_confidence": round(avg_conf, 2),
                        "recommendation": f"COMPOUND RISK: {len(domains)} cycle peaks converging. Priority intervention required.",
                    })

        seen = set()
        unique = []
        for c in convergences:
            key = tuple(sorted(c["converging_domains"])) + (c["convergence_date"][:10],)
            if key not in seen:
                seen.add(key)
                unique.append(c)

        return sorted(unique, key=lambda c: c["convergence_risk"], reverse=True)[:10]


# =============================================================================
# TIME SERIES EXTRACTOR
# =============================================================================

class TimeSeriesExtractor:
    """Extracts time-series data from various sources based on domain config."""

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def extract(self, user_id: str, config: CycleDomainConfig, days: int = 180) -> np.ndarray:
        all_values = []

        for source in config.data_sources:
            mode = source.get("mode", "numeric")
            if mode == "nlp":
                vals = await self._extract_nlp(user_id, config.nlp_keywords, days)
                all_values.extend(vals)
            elif mode == "numeric":
                vals = await self._extract_numeric(user_id, source, days)
                all_values.extend(vals)
            elif mode == "jsonb":
                vals = await self._extract_jsonb(user_id, source, days)
                all_values.extend(vals)
            elif mode == "manual":
                vals = await self._extract_manual(user_id, config.domain_id, days)
                all_values.extend(vals)

        if not all_values:
            return np.array([])

        all_values.sort(key=lambda x: x[0])
        return np.array([v[1] for v in all_values])

    async def _extract_nlp(self, user_id: str, keywords: List[str], days: int) -> List[Tuple[str, float]]:
        if not self.db_pool:
            return []
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT DATE(created_at) as day,
                           STRING_AGG(COALESCE(user_text, '') || ' ' || COALESCE(ai_text, ''), ' ') as text
                    FROM conversation_history
                    WHERE user_id = $1
                    AND created_at > NOW() - ($2 || ' days')::INTERVAL
                    GROUP BY DATE(created_at)
                    ORDER BY day
                """, user_id, str(days))

            results = []
            for row in rows:
                text = (row["text"] or "").lower()
                total_words = max(len(text.split()), 1)
                hits = sum(1 for kw in keywords if kw.lower() in text)
                density = hits / total_words * 100
                results.append((row["day"].isoformat(), density))
            return results
        except Exception as e:
            logger.warning("CycleDetection: NLP extraction error: %s", e)
            return []

    async def _extract_numeric(self, user_id: str, source: Dict, days: int) -> List[Tuple[str, float]]:
        if not self.db_pool:
            return []
        table = source["table"]
        column = source["column"]
        try:
            async with self.db_pool.acquire() as conn:
                if table == "client_metrics":
                    rows = await conn.fetch(f"""
                        SELECT DATE(updated_at) as day, AVG({column}) as val
                        FROM client_metrics
                        WHERE (hardware_id = $1 OR user_id::text = $1)
                        AND updated_at > NOW() - ($2 || ' days')::INTERVAL
                        GROUP BY DATE(updated_at)
                        ORDER BY day
                    """, user_id, str(days))
                elif table == "emotional_weather_snapshots":
                    rows = await conn.fetch(f"""
                        SELECT DATE(created_at) as day, AVG({column}) as val
                        FROM emotional_weather_snapshots
                        WHERE (sanctuary_id = $1 OR family_id = $1)
                        AND created_at > NOW() - ($2 || ' days')::INTERVAL
                        GROUP BY DATE(created_at)
                        ORDER BY day
                    """, user_id, str(days))
                elif table == "pgsd_snapshots":
                    # QUANTUM-CRYSTAL-ARCH — user_id = hardware_id (canonical)
                    _allowed = {
                        "coherence", "d1_valence", "d2_arousal", "d3_relational",
                        "d4_temporal_depth", "d5_integration", "purity",
                    }
                    if column not in _allowed:
                        return []
                    rows = await conn.fetch(f"""
                        SELECT DATE(computed_at) as day, AVG({column}) as val
                        FROM pgsd_snapshots
                        WHERE (user_id = $1 OR username = $1)
                        AND computed_at > NOW() - ($2 || ' days')::INTERVAL
                        GROUP BY DATE(computed_at)
                        ORDER BY day
                    """, user_id, str(days))
                else:
                    return []
            return [(r["day"].isoformat(), float(r["val"] or 0)) for r in rows]
        except Exception as e:
            logger.warning("CycleDetection: numeric extraction error for %s.%s: %s", table, column, e)
            return []

    async def _extract_jsonb(self, user_id: str, source: Dict, days: int) -> List[Tuple[str, float]]:
        if not self.db_pool:
            return []
        column = source["column"]
        jsonb_key = source.get("jsonb_key", "")
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(f"""
                    SELECT DATE(updated_at) as day, {column} as jdata
                    FROM client_metrics
                    WHERE (hardware_id = $1 OR user_id::text = $1)
                    AND updated_at > NOW() - ($2 || ' days')::INTERVAL
                    ORDER BY updated_at
                """, user_id, str(days))

            results = []
            for row in rows:
                jdata = row["jdata"]
                if isinstance(jdata, str):
                    jdata = json.loads(jdata)
                if isinstance(jdata, dict) and jsonb_key:
                    val = jdata.get(jsonb_key, 0)
                    try:
                        results.append((row["day"].isoformat(), float(val)))
                    except (TypeError, ValueError):
                        pass
            return results
        except Exception as e:
            logger.warning("CycleDetection: JSONB extraction error: %s", e)
            return []

    async def _extract_manual(self, user_id: str, domain: str, days: int) -> List[Tuple[str, float]]:
        if not self.db_pool:
            return []
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT DATE(observed_at) as day, AVG(value) as val
                    FROM cycle_observations
                    WHERE user_id = $1 AND domain = $2
                    AND observed_at > NOW() - ($3 || ' days')::INTERVAL
                    GROUP BY DATE(observed_at)
                    ORDER BY day
                """, user_id, domain, str(days))
            return [(r["day"].isoformat(), float(r["val"])) for r in rows]
        except Exception as e:
            logger.warning("CycleDetection: manual extraction error: %s", e)
            return []


# =============================================================================
# CYCLE DETECTION ENGINE (ORCHESTRATOR)
# =============================================================================

class CycleDetectionEngine:
    """Main orchestrator for multi-domain behavioral cycle detection."""

    def __init__(self, db_pool=None, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._extractor = TimeSeriesExtractor(db_pool)
        self._analyzer = SpectralAnalyzer()
        self._phase_tracker = CyclePhaseTracker()
        self._predictor = CyclePredictionGenerator()
        self._intervention = InterventionWindowCalculator()
        self._convergence = RiskConvergenceDetector()
        logger.info("CycleDetectionEngine initialized (12 domains)")

    async def detect_cycles(self, user_id: str, domain: str = None) -> Dict[str, Any]:
        domains_to_check = {}
        if domain and domain in CYCLE_DOMAINS:
            domains_to_check[domain] = CYCLE_DOMAINS[domain]
        else:
            domains_to_check = CYCLE_DOMAINS

        results = {}
        for dom_id, config in domains_to_check.items():
            try:
                values = await self._extractor.extract(user_id, config)
                if len(values) < config.min_observations:
                    results[dom_id] = {
                        "status": "insufficient_data",
                        "data_points": len(values),
                        "min_required": config.min_observations,
                    }
                    continue

                cycles = self._analyzer.analyze(values, config.sensitivity)
                if not cycles:
                    results[dom_id] = {"status": "no_cycles_detected", "data_points": len(values)}
                    continue

                phase = self._phase_tracker.compute_phase(
                    values, cycles[0]["period_days"], cycles[0].get("phase_offset", 0))

                results[dom_id] = {
                    "status": "cycles_detected",
                    "data_points": len(values),
                    "detected_cycles": cycles,
                    "current_phase": phase,
                    "display_name": config.display_name,
                    "peak_is_risk": config.peak_is_risk,
                }

                if self.db_pool:
                    try:
                        async with self.db_pool.acquire() as conn:
                            for c in cycles:
                                # QUANTUM-CRYSTAL-ARCH — fetchval for RETURNING (was NameError on det_row)
                                det_row = await conn.fetchval("""
                                    INSERT INTO cycle_detections
                                    (user_id, domain, detected_period_days, amplitude,
                                     phase_offset, confidence, method, expires_at)
                                    VALUES ($1, $2, $3, $4, $5, $6, $7, NOW() + INTERVAL '7 days')
                                    RETURNING id::text
                                """, user_id, dom_id, c["period_days"], c["amplitude"],
                                    c.get("phase_offset", 0), c["confidence"], c.get("method", "fft"))
                                if det_row:
                                    try:
                                        import asyncio
                                        from app.services.vectorize_service import index_cycle_detection, is_vectorize_configured
                                        if is_vectorize_configured():
                                            asyncio.create_task(index_cycle_detection(
                                                user_id=user_id,
                                                detection_id=det_row,
                                                domain=dom_id,
                                                period_days=c["period_days"],
                                                phase=str(c.get("phase_offset", 0)),
                                                amplitude=c["amplitude"],
                                                confidence=c["confidence"],
                                                prediction_text=f"{config.display_name}: {c['period_days']:.1f}-day cycle",
                                                timestamp=datetime.now(timezone.utc).isoformat(),
                                            ))
                                    except Exception:
                                        pass
                    except Exception as e:
                        logger.warning("CycleDetection: store detection error: %s", e)

                # UCD event hook: fire cycle_detected for TMC classification
                try:
                    from app.sse.ucd.event_hooks import fire_ucd_event
                    import asyncio as _aio
                    _aio.create_task(fire_ucd_event(
                        user_id, "cycle_detected",
                        {"domain": dom_id, "cycles": cycles, "phase": phase},
                        self.db_pool, self.app_state,
                    ))
                except Exception:
                    pass

                # Wire detected cycles to ODPE face-path boosting
                odpe_engine = getattr(self.app_state, 'odpe_engine', None) if self.app_state else None
                if odpe_engine:
                    for c in cycles:
                        try:
                            await odpe_engine.boost_from_cycle({
                                "domain": dom_id,
                                "period_days": c["period_days"],
                                "phase": c.get("phase_offset", 0),
                                "amplitude": c["amplitude"],
                                "confidence": c["confidence"],
                            })
                        except Exception:
                            pass

            except Exception as e:
                logger.warning("CycleDetection: domain %s error: %s", dom_id, e)
                results[dom_id] = {"status": "error", "error": str(e)}

        return {
            "user_id": user_id,
            "domains_analyzed": len(domains_to_check),
            "results": results,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def predict_next_events(self, user_id: str, horizon_days: int = 30) -> Dict[str, Any]:
        detection = await self.detect_cycles(user_id)
        all_predictions = {}
        all_windows = []

        for dom_id, result in detection.get("results", {}).items():
            if result.get("status") != "cycles_detected":
                continue
            config = CYCLE_DOMAINS.get(dom_id)
            if not config:
                continue
            preds = self._predictor.generate_predictions(
                result["detected_cycles"], dom_id, horizon_days, config.peak_is_risk)
            all_predictions[dom_id] = preds
            windows = self._intervention.calculate_windows(preds, config.peak_is_risk)
            all_windows.extend(windows)

            if self.db_pool:
                try:
                    async with self.db_pool.acquire() as conn:
                        for p in preds[:5]:
                            # QUANTUM-CRYSTAL-ARCH — asyncpg needs datetime, not isoformat str
                            pat = _as_utc_dt(p.get("predicted_at"))
                            w0 = _as_utc_dt(p.get("intervention_window_start"))
                            w1 = _as_utc_dt(p.get("intervention_window_end"))
                            if pat is None:
                                continue
                            await conn.execute("""
                                INSERT INTO cycle_predictions
                                (user_id, domain, predicted_event, predicted_at, confidence,
                                 intervention_window_start, intervention_window_end)
                                VALUES ($1, $2, $3, $4, $5, $6, $7)
                            """, user_id, dom_id, p["predicted_event"],
                                pat, p["confidence"], w0, w1)
                except Exception as e:
                    logger.warning("CycleDetection: store prediction error: %s", e)

        convergences = self._convergence.detect_convergence(all_predictions)

        return {
            "user_id": user_id,
            "horizon_days": horizon_days,
            "predictions": all_predictions,
            "intervention_windows": all_windows,
            "convergence_alerts": convergences,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_convergence_risk(self, user_id: str, horizon_days: int = 14) -> Dict[str, Any]:
        events = await self.predict_next_events(user_id, horizon_days)
        convergences = events.get("convergence_alerts", [])
        max_risk = max((c["convergence_risk"] for c in convergences), default=0)

        return {
            "user_id": user_id,
            "horizon_days": horizon_days,
            "max_convergence_risk": round(max_risk, 2),
            "risk_level": "critical" if max_risk > 0.7 else "high" if max_risk > 0.5 else "moderate" if max_risk > 0.3 else "low",
            "convergence_count": len(convergences),
            "convergences": convergences,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_family_cycles(self, family_id: str) -> Dict[str, Any]:
        if not self.db_pool:
            return {"status": "no_database"}
        try:
            async with self.db_pool.acquire() as conn:
                members = await conn.fetch("""
                    SELECT username FROM users
                    WHERE family_id::text = $1 AND role = 'CLIENT'
                """, family_id)

            member_cycles = {}
            for m in members:
                result = await self.detect_cycles(m["username"])
                member_cycles[m["username"]] = result

            group_result = await self.detect_cycles(family_id, domain="group_dynamics")

            return {
                "family_id": family_id,
                "member_count": len(members),
                "member_cycles": member_cycles,
                "group_dynamics": group_result,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.warning("CycleDetection: family cycles error: %s", e)
            return {"status": "error", "error": str(e)}

    async def get_group_cycles(self, group_id: str) -> Dict[str, Any]:
        if not self.db_pool:
            return {"status": "no_database"}
        try:
            async with self.db_pool.acquire() as conn:
                members = await conn.fetch("""
                    SELECT username FROM users
                    WHERE profile_data->>'group_id' = $1 AND role = 'CLIENT'
                """, group_id)

            member_cycles = {}
            for m in members:
                result = await self.detect_cycles(m["username"])
                member_cycles[m["username"]] = result

            return {
                "group_id": group_id,
                "member_count": len(members),
                "member_cycles": member_cycles,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.warning("CycleDetection: group cycles error: %s", e)
            return {"status": "error", "error": str(e)}

    async def record_observation(self, user_id: str, domain: str, value: float,
                                  metadata: Optional[Dict] = None) -> Dict[str, Any]:
        if domain not in CYCLE_DOMAINS:
            return {"status": "error", "message": f"Unknown domain: {domain}"}
        if not self.db_pool:
            return {"status": "error", "message": "No database"}
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO cycle_observations (user_id, domain, value, metadata)
                    VALUES ($1, $2, $3, $4::jsonb)
                    ON CONFLICT (user_id, domain, observed_at) DO UPDATE
                    SET value = EXCLUDED.value, metadata = EXCLUDED.metadata
                """, user_id, domain, value, json.dumps(metadata or {}))
            return {"status": "ok", "domain": domain, "value": value}
        except Exception as e:
            logger.warning("CycleDetection: record observation error: %s", e)
            return {"status": "error", "message": str(e)}

    async def get_active_cycles(self, min_confidence: float = 0.5) -> List[Dict]:
        """Return all active cycle detections above a confidence threshold."""
        if not self.db_pool:
            return []
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, user_id, domain,
                           detected_period_days AS period_days,
                           phase_offset AS phase,
                           amplitude,
                           confidence, detected_at
                    FROM cycle_detections
                    WHERE confidence > $1
                      AND detected_at > NOW() - INTERVAL '30 days'
                    ORDER BY confidence DESC LIMIT 100
                """, min_confidence)
                return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("CycleDetection: get_active_cycles error: %s", e)
            return []

    # =========================================================================
    # INTEGRATION HELPERS (for SovereignPredictiveEngine)
    # =========================================================================

    async def get_generational_score(self, user_id: str) -> float:
        try:
            result = await self.detect_cycles(user_id, domain="legacy")
            legacy = result.get("results", {}).get("legacy", {})
            if legacy.get("status") == "cycles_detected":
                cycles = legacy.get("detected_cycles", [])
                if cycles:
                    return max(0.1, min(1.0 - cycles[0]["amplitude"], 1.0))
            return 0.5
        except Exception:
            return 0.5

    async def get_habit_timeline_score(self, user_id: str) -> float:
        try:
            result = await self.detect_cycles(user_id, domain="emotional_state")
            emo = result.get("results", {}).get("emotional_state", {})
            if emo.get("status") == "cycles_detected":
                phase = emo.get("current_phase", {})
                if phase.get("phase") == "trough":
                    return 0.8
                elif phase.get("phase") == "rising":
                    return 0.6
                elif phase.get("phase") == "peak":
                    return 0.3
                return 0.5
            return 0.5
        except Exception:
            return 0.5

    async def get_optimal_timing_score(self, user_id: str) -> float:
        try:
            events = await self.predict_next_events(user_id, horizon_days=7)
            windows = events.get("intervention_windows", [])
            if windows:
                best = max(windows, key=lambda w: w.get("confidence", 0))
                return min(best.get("confidence", 0.5) * 1.3, 1.0)
            return 0.5
        except Exception:
            return 0.5

    async def get_historical_pattern_score(self, user_id: str) -> float:
        try:
            result = await self.detect_cycles(user_id)
            total_domains = 0
            detected = 0
            for dom_id, res in result.get("results", {}).items():
                total_domains += 1
                if res.get("status") == "cycles_detected":
                    detected += 1
            if total_domains == 0:
                return 0.5
            return max(0.2, min(detected / total_domains, 1.0))
        except Exception:
            return 0.5

    # QUANTUM-CRYSTAL-ARCH: background sweep for all active users
    async def sweep_all_users(self) -> int:
        """Run cycle detection for all users with sufficient conversation history."""
        meta = await self.sweep_and_predict(predict=False)
        return int(meta.get("detected") or 0)

    async def sweep_and_predict(
        self, *, predict: bool = True, limit_users: int = 40
    ) -> Dict[str, Any]:
        """
        Detect cycles (+ optional predictions) for active users.
        Feeds D.13 Brier calibration — free labels when predictions resolve.
        """
        # QUANTUM-CRYSTAL-ARCH — clinical AGI-class free-label channel
        if not self.db_pool:
            return {"ok": False, "error": "no_db", "detected": 0, "predicted": 0}
        detected = 0
        predicted = 0
        scanned = 0
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT user_id FROM conversation_history
                       WHERE created_at > NOW() - INTERVAL '180 days'
                       GROUP BY user_id HAVING COUNT(*) >= 20
                       ORDER BY MAX(created_at) DESC
                       LIMIT $1""",
                    max(1, min(int(limit_users or 40), 80)),
                )
            for row in rows:
                uid = row["user_id"]
                scanned += 1
                try:
                    if predict:
                        ev = await self.predict_next_events(uid, horizon_days=30)
                        if any(
                            (ev.get("predictions") or {}).get(d)
                            for d in (ev.get("predictions") or {})
                        ):
                            predicted += 1
                            detected += 1
                        else:
                            result = await self.detect_cycles(uid)
                            if any(
                                r.get("status") == "cycles_detected"
                                for r in (result.get("results") or {}).values()
                            ):
                                detected += 1
                    else:
                        result = await self.detect_cycles(uid)
                        if any(
                            r.get("status") == "cycles_detected"
                            for r in (result.get("results") or {}).values()
                        ):
                            detected += 1
                except Exception:
                    continue
        except Exception as e:
            logger.warning("CycleDetectionEngine sweep_and_predict failed: %s", e)
            return {
                "ok": False,
                "error": str(e)[:160],
                "scanned": scanned,
                "detected": detected,
                "predicted": predicted,
            }
        logger.info(
            "CycleDetectionEngine sweep_and_predict: scanned=%d detected=%d predicted=%d",
            scanned,
            detected,
            predicted,
        )
        return {
            "ok": True,
            "scanned": scanned,
            "detected": detected,
            "predicted": predicted,
            "predict": predict,
        }
