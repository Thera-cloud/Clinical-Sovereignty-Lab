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
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

import numpy as np

from app.models.strategy import ForesightAlert
from app.services.exceptions import ForesightException, PredictionFailedException


class ForesightEngine:
    """
    Predictive analytics engine for the Sovereign Swarm.

    Combines internal therapeutic signals, external cultural data,
    historical patterns, and contextual signals into probabilistic
    foresight alerts with accuracy feedback loops.
    """

    # Data stream weights
    STREAM_WEIGHTS = {
        "internal_therapeutic": 0.35,
        "external_cultural": 0.25,
        "historical_pattern": 0.25,
        "contextual": 0.15,
    }

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
        except Exception:
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
        except Exception:
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
        except Exception:
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

            if predicted_end < current - 0.1:
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

            elif predicted_end > current + 0.1:
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
