"""
SOVEREIGN SWARM — Foresight Analyst Fibre
Synthesizes 4 data streams into predictive foresight alerts:
    1. Internal therapeutic data
    2. External cultural signals (SkyEye)
    3. Historical patterns
    4. Contextual signals

Phase 4D.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.fibres.base_fibre import BaseFibre
from app.models.fibre import FibreConfig, FibreResult, FibreTask, FibreType


class ForesightAnalystFibre(BaseFibre):
    """
    Foresight Analyst — synthesizes multiple data streams into
    predictive alerts with confidence intervals and alternative scenarios.
    """

    def __init__(self, config: FibreConfig, **kwargs):
        super().__init__(config=config, **kwargs)
        self._prediction_history: List[Dict] = []
        self._data_streams = config.wisdom_seed.get("data_streams", [
            "internal_therapeutic", "external_cultural",
            "historical_pattern", "contextual"
        ])

    async def _execute_impl(self, task: FibreTask) -> FibreResult:
        """
        Execute foresight analysis tasks.
        Task types:
            - synthesize: Full 4-stream synthesis
            - predict: Generate a foresight alert
            - validate: Check past predictions against outcomes
            - trend_analysis: Identify trends across data streams
        """
        task_type = task.task_type
        payload = task.payload

        if task_type == "synthesize":
            return await self._synthesize(task, payload)
        elif task_type == "predict":
            return await self._predict(task, payload)
        elif task_type == "validate":
            return await self._validate_predictions(task, payload)
        elif task_type == "trend_analysis":
            return await self._trend_analysis(task, payload)
        else:
            return FibreResult(
                task_id=task.task_id,
                fibre_id=self.fibre_id,
                success=False,
                output={"error": f"Unknown task type: {task_type}"},
            )

    async def _synthesize(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Full 4-stream data synthesis."""
        streams = {}

        # Stream 1: Internal therapeutic
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    row = await conn.fetchrow("""
                        SELECT AVG(score) as avg_coherence,
                               STDDEV(score) as std_coherence,
                               COUNT(*) as sample_count
                        FROM coherence_measurements
                        WHERE layer = 'individual'
                          AND measured_at > NOW() - INTERVAL '7 days'
                    """)
                    streams["internal_therapeutic"] = {
                        "avg_coherence": float(row["avg_coherence"]) if row["avg_coherence"] else 0.5,
                        "std_coherence": float(row["std_coherence"]) if row["std_coherence"] else 0.0,
                        "sample_count": row["sample_count"] or 0,
                    }
            except Exception:
                streams["internal_therapeutic"] = {"status": "unavailable"}

        # Stream 2: External cultural (SkyEye)
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT platform, COUNT(*) as activity,
                               AVG(COALESCE((metadata::jsonb->>'sentiment')::float, 0.5)) as sentiment
                        FROM skyeye_activity
                        WHERE created_at > NOW() - INTERVAL '7 days'
                        GROUP BY platform
                    """)
                    streams["external_cultural"] = {
                        "platforms": {r["platform"]: {
                            "activity": r["activity"],
                            "sentiment": float(r["sentiment"] or 0.5),
                        } for r in rows}
                    }
            except Exception:
                streams["external_cultural"] = {"status": "unavailable"}

        # Stream 3: Historical patterns
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT signal_description, confidence, accuracy_score
                        FROM foresight_alerts
                        WHERE resolved_at IS NOT NULL AND accuracy_score IS NOT NULL
                        ORDER BY resolved_at DESC LIMIT 20
                    """)
                    streams["historical_pattern"] = {
                        "past_predictions": len(rows),
                        "avg_accuracy": float(sum(r["accuracy_score"] for r in rows) / max(len(rows), 1)) if rows else 0.0,
                    }
            except Exception:
                streams["historical_pattern"] = {"status": "unavailable"}

        # Stream 4: Contextual signals
        streams["contextual"] = {
            "day_of_week": datetime.utcnow().strftime("%A"),
            "time_of_day": datetime.utcnow().strftime("%H:%M"),
            "note": "Contextual stream — enriched in Phase 5",
        }

        # Weighted confidence scoring
        confidences = []
        for stream_name, data in streams.items():
            if data.get("status") != "unavailable":
                confidences.append(0.6)  # base confidence when data available
            else:
                confidences.append(0.2)

        overall_confidence = sum(confidences) / len(confidences) if confidences else 0.3

        return FibreResult(
            task_id=task.task_id,
            fibre_id=self.fibre_id,
            success=True,
            output={
                "synthesis": streams,
                "data_streams_active": sum(1 for s in streams.values() if s.get("status") != "unavailable"),
                "overall_confidence": round(overall_confidence, 4),
            },
            tokens_used=400,
            ethical_compliance=1.0,
            self_alignment_score=0.9,
        )

    async def _predict(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Generate a foresight alert from synthesized data."""
        # First synthesize
        synthesis_result = await self._synthesize(task, {})
        synthesis = synthesis_result.output.get("synthesis", {})
        confidence = synthesis_result.output.get("overall_confidence", 0.3)

        # Generate prediction
        internal = synthesis.get("internal_therapeutic", {})
        external = synthesis.get("external_cultural", {})

        predictions = []

        # Coherence trend prediction
        avg_coh = internal.get("avg_coherence", 0.5)
        std_coh = internal.get("std_coherence", 0.0)

        if avg_coh < 0.4:
            predictions.append({
                "signal": "Low coherence trend — therapeutic engagement may decline",
                "confidence": round(min(0.8, confidence + 0.1), 2),
                "time_horizon_hours": 72,
                "recommended_actions": [
                    "Increase session reminders",
                    "Deploy supportive content on social",
                    "Alert coaches to check in with at-risk clients",
                ],
            })

        if std_coh > 0.3:
            predictions.append({
                "signal": "High coherence volatility — emotional instability pattern",
                "confidence": round(min(0.7, confidence), 2),
                "time_horizon_hours": 48,
                "recommended_actions": [
                    "Monitor crisis indicators",
                    "Prepare grounding content",
                ],
            })

        # Store predictions as foresight alerts
        if self.db_pool and predictions:
            try:
                from app.services.strategic_memory import StrategicMemoryService
                memory = StrategicMemoryService(self.db_pool)
                for pred in predictions:
                    await memory.create_foresight_alert({
                        "signal_description": pred["signal"],
                        "confidence": pred["confidence"],
                        "time_horizon_hours": pred["time_horizon_hours"],
                        "recommended_actions": pred["recommended_actions"],
                        "source_fibre_id": self.fibre_id,
                        "source_data_streams": self._data_streams,
                    })
            except Exception as e:
                print(f">>> [FORESIGHT] Alert storage failed: {e}")

        self._prediction_history.extend(predictions)

        return FibreResult(
            task_id=task.task_id,
            fibre_id=self.fibre_id,
            success=True,
            output={
                "predictions": predictions,
                "prediction_count": len(predictions),
                "synthesis_confidence": confidence,
            },
            tokens_used=600,
        )

    async def _validate_predictions(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Validate past predictions against actual outcomes."""
        validated = []
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT alert_id, signal_description, confidence,
                               actual_outcome, accuracy_score
                        FROM foresight_alerts
                        WHERE source_fibre_id = $1
                          AND resolved_at IS NOT NULL
                        ORDER BY resolved_at DESC LIMIT 20
                    """, self.fibre_id)
                    validated = [dict(r) for r in rows]
            except Exception:
                pass

        accuracy_scores = [v["accuracy_score"] for v in validated if v.get("accuracy_score") is not None]
        avg_accuracy = sum(accuracy_scores) / max(len(accuracy_scores), 1) if accuracy_scores else 0.0

        return FibreResult(
            task_id=task.task_id,
            fibre_id=self.fibre_id,
            success=True,
            output={
                "validated_predictions": len(validated),
                "average_accuracy": round(avg_accuracy, 4),
                "details": validated[:10],
            },
            tokens_used=200,
        )

    async def _trend_analysis(self, task: FibreTask, payload: Dict) -> FibreResult:
        """Identify trends across data streams."""
        trends = []
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    # Coherence trend
                    rows = await conn.fetch("""
                        SELECT DATE(measured_at) as day, AVG(score) as avg_score
                        FROM coherence_measurements
                        WHERE layer = 'individual'
                          AND measured_at > NOW() - INTERVAL '14 days'
                        GROUP BY DATE(measured_at)
                        ORDER BY day
                    """)
                    if len(rows) >= 3:
                        scores = [float(r["avg_score"]) for r in rows]
                        trend = "rising" if scores[-1] > scores[0] else "falling" if scores[-1] < scores[0] else "stable"
                        trends.append({
                            "metric": "individual_coherence",
                            "direction": trend,
                            "start": round(scores[0], 4),
                            "end": round(scores[-1], 4),
                            "days": len(rows),
                        })
            except Exception:
                pass

        return FibreResult(
            task_id=task.task_id,
            fibre_id=self.fibre_id,
            success=True,
            output={"trends": trends},
            tokens_used=150,
        )

    async def observe(self) -> Dict[str, Any]:
        """Periodic observation — scan for prediction opportunities."""
        return {
            "fibre_id": str(self.fibre_id),
            "name": self.name,
            "observation_type": "foresight_analyst",
            "predictions_made": len(self._prediction_history),
            "data_streams": self._data_streams,
            "timestamp": datetime.utcnow().isoformat(),
        }
