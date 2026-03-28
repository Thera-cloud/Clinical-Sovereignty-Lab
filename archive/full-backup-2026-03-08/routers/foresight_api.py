"""
SOVEREIGN SWARM — Foresight Engine API
REST endpoints for predictions, forecasting, and accuracy tracking.

Phase 5A — Code Guidelines Section VII.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.api_server import require_admin

router = APIRouter(
    prefix="/api/foresight",
    tags=["Foresight Engine"],
    dependencies=[Depends(require_admin)],
)


@router.get("/status")
async def foresight_engine_status():
    """Lightweight health-check for architecture diagrams."""
    return {"status": "active", "service": "foresight_engine"}


# =============================================================================
# REQUEST MODELS
# =============================================================================


class ValidatePredictionRequest(BaseModel):
    """Body for validating a past prediction with actual outcome."""

    actual_outcome: str = Field(..., min_length=1)


# =============================================================================
# HELPERS
# =============================================================================


def _get_foresight_engine(request: Request):
    """Get ForesightEngine from app state."""
    engine = getattr(request.app.state, "foresight_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="Foresight Engine not available")
    return engine


def _serialize_row(row: Any) -> Dict:
    """Convert asyncpg row to JSON-serializable dict."""
    result = {}
    for k, v in (row.items() if hasattr(row, "items") else row._mapping.items()):
        if isinstance(v, UUID):
            result[k] = str(v)
        elif hasattr(v, "isoformat"):
            result[k] = v.isoformat() if v else None
        elif isinstance(v, list):
            result[k] = [str(x) if isinstance(x, UUID) else x for x in v]
        else:
            result[k] = v
    return result


# =============================================================================
# PREDICTIONS
# =============================================================================


@router.get("/predictions")
async def list_predictions(request: Request):
    """
    List active foresight alerts (unresolved predictions).
    Queries foresight_alerts WHERE resolved_at IS NULL.
    """
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT *
            FROM foresight_alerts
            WHERE resolved_at IS NULL
            ORDER BY confidence DESC, created_at DESC
        """)

    return {
        "predictions": [_serialize_row(r) for r in rows],
        "total": len(rows),
    }


@router.get("/predictions/{alert_id}")
async def get_prediction_detail(request: Request, alert_id: UUID):
    """
    Get single prediction detail by alert_id.
    """
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM foresight_alerts WHERE alert_id = $1", alert_id
        )

    if not row:
        raise HTTPException(status_code=404, detail="Prediction not found")

    return _serialize_row(row)


# =============================================================================
# FORECAST
# =============================================================================


@router.post("/forecast")
async def trigger_forecast(request: Request):
    """
    Trigger a new forecast: synthesize streams and generate alerts.
    Calls ForesightEngine.synthesize_streams() + generate_alerts().
    """
    engine = _get_foresight_engine(request)

    try:
        synthesis = await engine.synthesize_streams()
        alerts = await engine.generate_alerts()
        return {
            "status": "completed",
            "synthesis": synthesis,
            "alerts_generated": len(alerts),
            "alerts": alerts,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# VALIDATE PAST PREDICTION
# =============================================================================


@router.post("/predictions/{alert_id}/validate")
async def validate_prediction(
    request: Request, alert_id: UUID, body: ValidatePredictionRequest
):
    """
    Validate a past prediction with actual outcome.
    Updates the foresight alert with accuracy score and marks resolved.
    """
    engine = _get_foresight_engine(request)

    try:
        result = await engine.track_accuracy(alert_id, body.actual_outcome)
        return result
    except Exception as e:
        err_msg = str(e)
        if "not found" in err_msg.lower():
            raise HTTPException(status_code=404, detail=err_msg)
        raise HTTPException(status_code=500, detail=err_msg)


# =============================================================================
# ACCURACY METRICS
# =============================================================================


@router.get("/accuracy")
async def get_accuracy_metrics(request: Request):
    """
    Historical accuracy metrics.
    AVG accuracy_score from foresight_alerts WHERE accuracy_score IS NOT NULL.
    """
    engine = _get_foresight_engine(request)

    try:
        report = await engine.get_accuracy_report()
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
