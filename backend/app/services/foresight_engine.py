"""
SOVEREIGN SWARM — Full Foresight Engine
Time-series analysis and predictive modeling with accuracy tracking.

Features:
    - 4-stream data synthesis with weighted confidence scoring
    - Time-series forecasting (ARIMA/exponential smoothing via statsmodels)
    - Structured output: signal, confidence, horizon, populations, actions, scenarios
    - Historical accuracy tracking (every prediction tracked against outcomes)
    - Model refinement loop

Phase 5A — Code Guidelines Section VII.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

import numpy as np

from app.models.strategy import ForesightAlert
from app.services.exceptions import ForesightException, PredictionFailedException

logger = logging.getLogger(__name__)


class ForesightEngine:
    """
    Predictive analytics engine for the Sovereign Swarm.

    Combines internal therapeutic signals, external cultural data,
    historical patterns, and contextual signals into probabilistic
    foresight alerts with accuracy feedback loops.
    """

    # Data stream weights (from centralized swarm config, overridable via SWARM_* env vars)
    from app.swarm_config import swarm_settings as _cfg
    STREAM_WEIGHTS = _cfg.FORESIGHT_STREAM_WEIGHTS.copy()

    def __init__(self, db_pool):
        self.db_pool = db_pool

    # =========================================================================
    # TIME-SERIES FORECASTING
    # =========================================================================

    async def forecast_coherence(
        self, layer: str = "individual",
        horizon_days: int = 7,
        method: str = "exponential_smoothing",
    ) -> Dict[str, Any]:
        """
        Forecast coherence scores using time-series analysis.
        Methods: exponential_smoothing, arima, linear_trend
        """
        # Get historical data
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT DATE(measured_at) as day, AVG(score) as avg_score,
                       COUNT(*) as sample_count
                FROM coherence_measurements
                WHERE layer = $1
                  AND measured_at > NOW() - INTERVAL '90 days'
                GROUP BY DATE(measured_at)
                ORDER BY day
            """, layer)

        if len(rows) < 7:
            raise PredictionFailedException(
                f"Insufficient data for {layer} forecast: {len(rows)} days (need 7+)"
            )

        dates = [r["day"] for r in rows]
        scores = np.array([float(r["avg_score"]) for r in rows])

        # Attempt statsmodels forecasting
        forecast = None
        confidence_intervals = None

        try:
            if method == "exponential_smoothing":
                forecast, confidence_intervals = self._exponential_smoothing(scores, horizon_days)
            elif method == "arima":
                forecast, confidence_intervals = self._arima_forecast(scores, horizon_days)
            else:
                forecast, confidence_intervals = self._linear_trend(scores, horizon_days)
        except Exception as e:
            # Fall back to linear trend
            print(f">>> [FORESIGHT] {method} failed, falling back to linear: {e}")
            forecast, confidence_intervals = self._linear_trend(scores, horizon_days)

        # Build forecast result
        forecast_dates = []
        last_date = dates[-1]
        for i in range(1, horizon_days + 1):
            forecast_dates.append((last_date + timedelta(days=i)).isoformat())

        return {
            "layer": layer,
            "method": method,
            "historical_days": len(rows),
            "forecast_horizon": horizon_days,
            "current_value": round(float(scores[-1]), 4),
            "forecast": [
                {
                    "date": forecast_dates[i],
                    "predicted": round(float(forecast[i]), 4),
                    "lower": round(float(confidence_intervals[i][0]), 4),
                    "upper": round(float(confidence_intervals[i][1]), 4),
                }
                for i in range(len(forecast))
            ],
            "trend": "rising" if forecast[-1] > scores[-1] else "falling" if forecast[-1] < scores[-1] else "stable",
            "generated_at": datetime.utcnow().isoformat(),
        }

    def _exponential_smoothing(
        self, data: np.ndarray, horizon: int
    ) -> Tuple[np.ndarray, List[Tuple[float, float]]]:
        """Simple exponential smoothing with prediction intervals."""
        try:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing

            model = ExponentialSmoothing(
                data,
                trend="add",
                seasonal=None,
                initialization_method="estimated",
            )
            fitted = model.fit(optimized=True)
            forecast = fitted.forecast(horizon)

            # Prediction intervals (approximate)
            residual_std = np.std(fitted.resid)
            intervals = []
            for i in range(horizon):
                margin = 1.96 * residual_std * math.sqrt(1 + i * 0.1)
                intervals.append((
                    max(0, float(forecast[i] - margin)),
                    min(1, float(forecast[i] + margin)),
                ))

            return np.clip(forecast, 0, 1), intervals

        except ImportError:
            print(">>> [FORESIGHT] statsmodels not available, using linear trend")
            return self._linear_trend(data, horizon)

    def _arima_forecast(
        self, data: np.ndarray, horizon: int
    ) -> Tuple[np.ndarray, List[Tuple[float, float]]]:
        """ARIMA time-series forecast."""
        try:
            from statsmodels.tsa.arima.model import ARIMA

            model = ARIMA(data, order=(1, 1, 1))
            fitted = model.fit()
            result = fitted.get_forecast(steps=horizon)
            forecast = result.predicted_mean
            conf_int = result.conf_int(alpha=0.05)

            intervals = [
                (max(0, float(conf_int[i, 0])), min(1, float(conf_int[i, 1])))
                for i in range(len(conf_int))
            ]

            return np.clip(forecast, 0, 1), intervals

        except (ImportError, Exception) as e:
            print(f">>> [FORESIGHT] ARIMA failed: {e}")
            return self._linear_trend(data, horizon)

    def _linear_trend(
        self, data: np.ndarray, horizon: int
    ) -> Tuple[np.ndarray, List[Tuple[float, float]]]:
        """Simple linear trend extrapolation (fallback)."""
        x = np.arange(len(data))
        coeffs = np.polyfit(x, data, 1)
        slope, intercept = coeffs

        forecast_x = np.arange(len(data), len(data) + horizon)
        forecast = slope * forecast_x + intercept
        forecast = np.clip(forecast, 0, 1)

        residual_std = float(np.std(data - (slope * x + intercept)))
        intervals = [
            (max(0, float(forecast[i] - 1.96 * residual_std)),
             min(1, float(forecast[i] + 1.96 * residual_std)))
            for i in range(horizon)
        ]

        return forecast, intervals

    # =========================================================================
    # 4-STREAM SYNTHESIS
    # =========================================================================

    async def synthesize_streams(self) -> Dict[str, Any]:
        """Synthesize all 4 data streams into a unified foresight view."""
        streams = {}

        # Stream 1: Internal therapeutic
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT AVG(score) as avg, STDDEV(score) as std, COUNT(*) as cnt
                    FROM coherence_measurements
                    WHERE measured_at > NOW() - INTERVAL '7 days'
                """)
                streams["internal_therapeutic"] = {
                    "average_coherence": round(float(row["avg"] or 0.5), 4),
                    "volatility": round(float(row["std"] or 0), 4),
                    "sample_count": row["cnt"] or 0,
                    "confidence": min(1.0, (row["cnt"] or 0) / 50),
                }
        except Exception as e:
            logger.debug("DB query internal therapeutic stream: %s", e)
            streams["internal_therapeutic"] = {"confidence": 0, "status": "unavailable"}

        # Stream 2: External cultural
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT platform, COUNT(*) as cnt,
                           AVG(COALESCE((metadata::jsonb->>'sentiment')::float, 0.5)) as sentiment
                    FROM skyeye_activity
                    WHERE created_at > NOW() - INTERVAL '7 days'
                    GROUP BY platform
                """)
                streams["external_cultural"] = {
                    "platforms": len(rows),
                    "avg_sentiment": round(float(sum(r["sentiment"] or 0.5 for r in rows) / max(len(rows), 1)), 4),
                    "total_activity": sum(r["cnt"] for r in rows),
                    "confidence": min(1.0, sum(r["cnt"] for r in rows) / 100),
                }
        except Exception as e:
            logger.debug("DB query external cultural stream: %s", e)
            streams["external_cultural"] = {"confidence": 0, "status": "unavailable"}

        # Stream 3: Historical pattern
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT confidence, accuracy_score
                    FROM foresight_alerts
                    WHERE resolved_at IS NOT NULL AND accuracy_score IS NOT NULL
                    ORDER BY resolved_at DESC LIMIT 50
                """)
                if rows:
                    accuracies = [float(r["accuracy_score"]) for r in rows]
                    streams["historical_pattern"] = {
                        "predictions_tracked": len(rows),
                        "average_accuracy": round(float(np.mean(accuracies)), 4),
                        "accuracy_trend": "improving" if len(accuracies) >= 3 and accuracies[-1] > accuracies[0] else "stable",
                        "confidence": round(float(np.mean(accuracies)), 4),
                    }
                else:
                    streams["historical_pattern"] = {"predictions_tracked": 0, "confidence": 0.3}
        except Exception as e:
            logger.debug("DB query historical pattern stream: %s", e)
            streams["historical_pattern"] = {"confidence": 0, "status": "unavailable"}

        # Stream 4: Contextual
        now = datetime.utcnow()
        streams["contextual"] = {
            "day_of_week": now.strftime("%A"),
            "hour": now.hour,
            "is_weekend": now.weekday() >= 5,
            "confidence": 0.5,
        }

        # Weighted confidence
        total_confidence = sum(
            streams[name].get("confidence", 0) * weight
            for name, weight in self.STREAM_WEIGHTS.items()
            if name in streams
        )

        return {
            "streams": streams,
            "overall_confidence": round(total_confidence, 4),
            "synthesized_at": now.isoformat(),
        }

    # =========================================================================
    # FORESIGHT ALERT GENERATION
    # =========================================================================

    async def generate_alerts(self) -> List[Dict[str, Any]]:
        """
        Generate foresight alerts based on stream synthesis and forecasts.
        """
        alerts = []

        synthesis = await self.synthesize_streams()
        confidence = synthesis["overall_confidence"]

        # Check coherence forecast
        try:
            forecast = await self.forecast_coherence(layer="individual", horizon_days=7)
            current = forecast["current_value"]
            predicted_end = forecast["forecast"][-1]["predicted"]

            if predicted_end < current - self._cfg.FORESIGHT_DECLINE_THRESHOLD:
                alert = {
                    "signal_description": f"Individual coherence forecasted to decline from {current:.2f} to {predicted_end:.2f} over 7 days",
                    "confidence": round(confidence * 0.8, 2),
                    "confidence_interval_lower": forecast["forecast"][-1]["lower"],
                    "confidence_interval_upper": forecast["forecast"][-1]["upper"],
                    "time_horizon_hours": 168,
                    "affected_populations": ["individual_clients"],
                    "recommended_actions": [
                        "Increase session availability",
                        "Deploy supportive check-in content",
                        "Alert coaches with at-risk client lists",
                    ],
                    "alternative_scenarios": [
                        {"scenario": "Stabilization", "probability": 0.3,
                         "description": "External factors improve, coherence stabilizes"},
                        {"scenario": "Accelerated decline", "probability": 0.15,
                         "description": "Crisis event causes faster decline"},
                    ],
                    "monitoring_indicators": [
                        "Daily coherence score", "Session cancellation rate",
                        "Crisis detection triggers",
                    ],
                    "source_data_streams": list(self.STREAM_WEIGHTS.keys()),
                }
                alerts.append(alert)

            elif predicted_end > current + self._cfg.FORESIGHT_IMPROVEMENT_THRESHOLD:
                alert = {
                    "signal_description": f"Individual coherence forecasted to improve from {current:.2f} to {predicted_end:.2f} over 7 days",
                    "confidence": round(confidence * 0.7, 2),
                    "time_horizon_hours": 168,
                    "affected_populations": ["individual_clients"],
                    "recommended_actions": [
                        "Capitalize on momentum with deeper therapeutic content",
                        "Consider launching new community programs",
                    ],
                    "source_data_streams": list(self.STREAM_WEIGHTS.keys()),
                }
                alerts.append(alert)

        except Exception as e:
            print(f">>> [FORESIGHT] Forecast alert generation failed: {e}")

        # Store alerts
        for alert_data in alerts:
            try:
                from app.services.strategic_memory import StrategicMemoryService
                memory = StrategicMemoryService(self.db_pool)
                await memory.create_foresight_alert(alert_data)
            except Exception as e:
                print(f">>> [FORESIGHT] Alert storage failed: {e}")

        return alerts

    # =========================================================================
    # ACCURACY TRACKING
    # =========================================================================

    async def track_accuracy(self, alert_id: UUID, actual_outcome: str) -> Dict[str, Any]:
        """
        Track a prediction's accuracy against the actual outcome.
        Updates the foresight alert and feeds the refinement loop.
        """
        async with self.db_pool.acquire() as conn:
            alert = await conn.fetchrow(
                "SELECT * FROM foresight_alerts WHERE alert_id = $1", alert_id
            )
            if not alert:
                raise ForesightException(f"Alert {alert_id} not found")

            # Simple accuracy scoring based on outcome alignment
            # In production, this would use NLP comparison and metric matching
            predicted_direction = "decline" if "decline" in alert["signal_description"].lower() else "improve"
            actual_direction = "decline" if any(w in actual_outcome.lower() for w in ["decline", "decrease", "worse", "drop"]) else "improve"
            accuracy = 0.8 if predicted_direction == actual_direction else 0.3

            # Update alert
            await conn.execute("""
                UPDATE foresight_alerts
                SET actual_outcome = $2, accuracy_score = $3, resolved_at = NOW()
                WHERE alert_id = $1
            """, alert_id, actual_outcome, accuracy)

        return {
            "alert_id": str(alert_id),
            "predicted": alert["signal_description"],
            "actual": actual_outcome,
            "accuracy_score": accuracy,
            "resolved_at": datetime.utcnow().isoformat(),
        }

    async def validate_past_predictions(self) -> int:
        """
        Find unresolved foresight alerts that have passed their time horizon
        and auto-resolve them. For each, check whether the predicted direction
        materialized in actual coherence data and assign an accuracy score.

        Returns:
            Number of predictions validated.
        """
        async with self.db_pool.acquire() as conn:
            # Find expired, unresolved alerts
            expired = await conn.fetch("""
                SELECT alert_id, signal_description, confidence,
                       time_horizon_hours, created_at
                FROM foresight_alerts
                WHERE resolved_at IS NULL
                  AND created_at + (time_horizon_hours || ' hours')::INTERVAL <= NOW()
                ORDER BY created_at ASC
            """)

            if not expired:
                return 0

            validated = 0
            for alert in expired:
                alert_id = alert["alert_id"]
                description = alert["signal_description"].lower()
                horizon_hours = alert["time_horizon_hours"] or 24

                # Determine predicted direction
                predicted_decline = any(w in description for w in [
                    "decline", "decrease", "drop", "risk", "crisis", "deteriorat"
                ])

                # Check actual coherence trend over the prediction window
                actual_outcome = "indeterminate"
                accuracy = 0.5  # neutral default

                try:
                    trend_row = await conn.fetchrow("""
                        SELECT
                            AVG(CASE WHEN measured_at < NOW() - ($1 || ' hours')::INTERVAL / 2
                                     THEN score END) as first_half,
                            AVG(CASE WHEN measured_at >= NOW() - ($1 || ' hours')::INTERVAL / 2
                                     THEN score END) as second_half
                        FROM coherence_measurements
                        WHERE layer = 'individual'
                          AND measured_at > NOW() - ($1 || ' hours')::INTERVAL
                    """, str(horizon_hours))

                    if trend_row and trend_row["first_half"] and trend_row["second_half"]:
                        first = float(trend_row["first_half"])
                        second = float(trend_row["second_half"])
                        actual_declined = second < first - 0.05

                        if predicted_decline and actual_declined:
                            accuracy = 0.85
                            actual_outcome = "Predicted decline confirmed"
                        elif not predicted_decline and not actual_declined:
                            accuracy = 0.80
                            actual_outcome = "Predicted stability/improvement confirmed"
                        elif predicted_decline and not actual_declined:
                            accuracy = 0.25
                            actual_outcome = "Predicted decline did not materialize"
                        else:
                            accuracy = 0.30
                            actual_outcome = "Unexpected decline occurred"
                    else:
                        actual_outcome = "Insufficient data to validate"
                        accuracy = 0.5
                except Exception as e:
                    logger.debug("DB query validate past predictions: %s", e)
                    actual_outcome = "Validation error — insufficient data"
                    accuracy = 0.5

                # Resolve the alert
                await conn.execute("""
                    UPDATE foresight_alerts
                    SET actual_outcome = $2, accuracy_score = $3, resolved_at = NOW()
                    WHERE alert_id = $1
                """, alert_id, actual_outcome, accuracy)
                validated += 1

        return validated

    async def get_accuracy_report(self) -> Dict[str, Any]:
        """Get overall prediction accuracy report."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT accuracy_score, confidence, created_at, resolved_at
                FROM foresight_alerts
                WHERE resolved_at IS NOT NULL AND accuracy_score IS NOT NULL
                ORDER BY resolved_at DESC
            """)

        if not rows:
            return {"total_predictions": 0, "status": "no_resolved_predictions"}

        accuracies = [float(r["accuracy_score"]) for r in rows]
        confidences = [float(r["confidence"]) for r in rows]

        return {
            "total_predictions": len(rows),
            "average_accuracy": round(float(np.mean(accuracies)), 4),
            "accuracy_std": round(float(np.std(accuracies)), 4),
            "average_confidence": round(float(np.mean(confidences)), 4),
            "calibration": round(abs(float(np.mean(accuracies)) - float(np.mean(confidences))), 4),
            "recent_trend": "improving" if len(accuracies) >= 5 and np.mean(accuracies[-5:]) > np.mean(accuracies[:5]) else "stable",
            "generated_at": datetime.utcnow().isoformat(),
        }

    # =========================================================================
    # INTERVENTION TIMING OPTIMIZATION (PhD Spec §7.3)
    # =========================================================================

    async def suggest_intervention_window(
        self, user_id, horizon_hours: int = 24
    ) -> Dict[str, Any]:
        """
        Identify optimal intervention timing from trajectory inflection points.

        Uses second-derivative analysis on coherence trajectory to find moments
        where coherence is about to decline — the ideal time for a nudge,
        session prompt, or coach outreach.
        """
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT score, measured_at
                FROM coherence_measurements
                WHERE user_id = $1
                  AND layer = 'individual'
                  AND measured_at > NOW() - ($2 || ' hours')::INTERVAL
                ORDER BY measured_at ASC
            """, user_id, str(horizon_hours))

        if len(rows) < 5:
            return {
                "user_id": str(user_id),
                "status": "insufficient_data",
                "data_points": len(rows),
            }

        scores = np.array([float(r["score"]) for r in rows])
        timestamps = [r["measured_at"] for r in rows]

        # First derivative (velocity) and second derivative (acceleration)
        velocity = np.diff(scores)
        acceleration = np.diff(velocity)

        # Find inflection points: where acceleration crosses zero
        # (trajectory is about to reverse direction)
        inflection_indices = []
        for i in range(len(acceleration) - 1):
            if acceleration[i] * acceleration[i + 1] < 0:  # sign change
                inflection_indices.append(i + 2)  # offset for double diff

        # Rank inflection points by coherence decline potential
        windows = []
        for idx in inflection_indices:
            if idx < len(scores) and velocity[min(idx - 1, len(velocity) - 1)] < 0:
                # Coherence is about to decline — optimal intervention moment
                windows.append({
                    "timestamp": timestamps[idx].isoformat(),
                    "coherence_at_point": round(float(scores[idx]), 4),
                    "decline_velocity": round(float(velocity[min(idx - 1, len(velocity) - 1)]), 4),
                    "urgency": "high" if scores[idx] < 0.4 else "moderate",
                })

        # If no inflection-based windows, fall back to lowest-point prediction
        if not windows:
            min_idx = int(np.argmin(scores[-max(5, len(scores) // 3):]))
            actual_idx = len(scores) - max(5, len(scores) // 3) + min_idx
            windows.append({
                "timestamp": timestamps[actual_idx].isoformat(),
                "coherence_at_point": round(float(scores[actual_idx]), 4),
                "decline_velocity": 0.0,
                "urgency": "low",
            })

        return {
            "user_id": str(user_id),
            "horizon_hours": horizon_hours,
            "data_points": len(scores),
            "intervention_windows": windows[:5],  # Top 5 windows
            "current_coherence": round(float(scores[-1]), 4),
            "trajectory_direction": "declining" if velocity[-1] < -0.01 else "rising" if velocity[-1] > 0.01 else "stable",
            "generated_at": datetime.utcnow().isoformat(),
        }

    # =========================================================================
    # FAMILY SYSTEM PROPAGATION PREDICTIONS (PhD Spec §7.4)
    # =========================================================================

    async def predict_family_propagation(
        self, family_id, horizon_hours: int = 72
    ) -> Dict[str, Any]:
        """
        Predict how coherence changes in one family member propagate to others.

        Cross-member propagation model: measures Pearson correlation between
        members' coherence trajectories and predicts how an intervention on
        one member may ripple through the family system.
        """
        async with self.db_pool.acquire() as conn:
            # Get family members
            members = await conn.fetch(
                "SELECT id, name FROM users WHERE family_id = $1 AND role = 'CLIENT'",
                family_id,
            )
            if len(members) < 2:
                return {
                    "family_id": str(family_id),
                    "status": "insufficient_members",
                    "member_count": len(members),
                }

            # Collect per-member coherence trajectories
            trajectories: Dict[str, List[float]] = {}
            member_names: Dict[str, str] = {}
            for m in members:
                uid = m["id"]
                member_names[str(uid)] = m["name"] or "Unknown"
                rows = await conn.fetch("""
                    SELECT score FROM coherence_measurements
                    WHERE user_id = $1 AND layer = 'individual'
                      AND measured_at > NOW() - ($2 || ' hours')::INTERVAL
                    ORDER BY measured_at ASC
                """, uid, str(horizon_hours))
                trajectories[str(uid)] = [float(r["score"]) for r in rows]

        # Normalize trajectories to same length (interpolate shorter ones)
        max_len = max(len(t) for t in trajectories.values()) if trajectories else 0
        if max_len < 5:
            return {
                "family_id": str(family_id),
                "status": "insufficient_data",
                "data_points": max_len,
            }

        normalized = {}
        for uid, t in trajectories.items():
            if len(t) >= 3:
                indices = np.linspace(0, len(t) - 1, max_len)
                normalized[uid] = np.interp(indices, range(len(t)), t)
            else:
                normalized[uid] = np.zeros(max_len)

        # Pairwise Pearson correlation and lead/lag analysis
        member_ids = list(normalized.keys())
        propagation_links = []

        for i, uid_a in enumerate(member_ids):
            for uid_b in member_ids[i + 1:]:
                arr_a = normalized[uid_a]
                arr_b = normalized[uid_b]

                # Direct correlation
                if np.std(arr_a) > 0 and np.std(arr_b) > 0:
                    corr = float(np.corrcoef(arr_a, arr_b)[0, 1])
                else:
                    corr = 0.0

                # Lead/lag: check if shifting A forward by 1-3 steps
                # increases correlation with B (A influences B)
                best_lag = 0
                best_lag_corr = corr
                for lag in range(1, min(4, max_len // 3)):
                    shifted_a = arr_a[:-lag]
                    trimmed_b = arr_b[lag:]
                    if len(shifted_a) > 3 and np.std(shifted_a) > 0 and np.std(trimmed_b) > 0:
                        lag_corr = float(np.corrcoef(shifted_a, trimmed_b)[0, 1])
                        if lag_corr > best_lag_corr:
                            best_lag = lag
                            best_lag_corr = lag_corr

                direction = "bidirectional"
                if best_lag > 0:
                    direction = f"{member_names.get(uid_a, uid_a)} → {member_names.get(uid_b, uid_b)}"

                if abs(corr) > 0.2:
                    propagation_links.append({
                        "member_a": uid_a,
                        "member_b": uid_b,
                        "name_a": member_names.get(uid_a, ""),
                        "name_b": member_names.get(uid_b, ""),
                        "correlation": round(corr, 4),
                        "propagation_lag": best_lag,
                        "lag_correlation": round(best_lag_corr, 4),
                        "direction": direction,
                        "strength": "strong" if abs(corr) > 0.5 else "moderate",
                    })

        # Identify highest-influence member (most strong outgoing links)
        influence_count: Dict[str, int] = {uid: 0 for uid in member_ids}
        for link in propagation_links:
            if link["propagation_lag"] > 0:
                influence_count[link["member_a"]] += 1

        most_influential = max(influence_count, key=influence_count.get) if influence_count else None

        return {
            "family_id": str(family_id),
            "horizon_hours": horizon_hours,
            "members_analyzed": len(members),
            "propagation_links": propagation_links,
            "most_influential_member": {
                "user_id": most_influential,
                "name": member_names.get(most_influential, ""),
                "outgoing_influence_links": influence_count.get(most_influential, 0),
            } if most_influential else None,
            "family_coherence_coupling": round(
                float(np.mean([abs(l["correlation"]) for l in propagation_links])), 4
            ) if propagation_links else 0.0,
            "generated_at": datetime.utcnow().isoformat(),
        }
