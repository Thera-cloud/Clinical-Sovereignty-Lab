"""
Predictive Intelligence Engine REST API.

8 endpoints for therapeutic probability, habit forecasting, family prediction,
real-time coaching scores, and unified dashboard.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

try:
    from app.services.api_server import get_current_user, require_coach
except ImportError:
    async def require_coach():
        return {"role": "ADMIN"}
    async def get_current_user():
        return {"role": "ADMIN"}

router = APIRouter(prefix="/api/predictive", tags=["predictive"], dependencies=[Depends(require_coach)])


class HabitRequest(BaseModel):
    habit_type: str
    habit_description: str = ""


class HabitTrackingUpdate(BaseModel):
    completions: int = 0
    misses: int = 0


@router.get("/health")
async def predictive_health(request: Request):
    engine = getattr(request.app.state, "predictive_engine", None)
    cycle = getattr(request.app.state, "cycle_detection_engine", None)
    return {
        "status": "ok",
        "predictive_engine": engine is not None,
        "cycle_engine": cycle is not None,
        "domains_configured": 12 if cycle else 0,
    }


@router.get("/therapeutic-probability/{user_id}")
async def therapeutic_probability(user_id: str, request: Request, goal_type: str = "general"):
    engine = getattr(request.app.state, "predictive_engine", None)
    if not engine:
        raise HTTPException(503, "Predictive engine not initialized")
    return await engine.calculate_unified_therapeutic_probability(user_id, goal_type)


@router.post("/habit-forecast/{user_id}")
async def habit_forecast(user_id: str, body: HabitRequest, request: Request):
    engine = getattr(request.app.state, "predictive_engine", None)
    if not engine:
        raise HTTPException(503, "Predictive engine not initialized")
    return await engine.predict_habit_success_timeline(user_id, body.habit_type, body.habit_description)


@router.get("/family-effectiveness/{family_id}")
async def family_effectiveness(family_id: str, request: Request):
    engine = getattr(request.app.state, "predictive_engine", None)
    if not engine:
        raise HTTPException(503, "Predictive engine not initialized")
    return await engine.predict_family_effectiveness(family_id)


@router.get("/realtime-coaching/{user_id}")
async def realtime_coaching(user_id: str, request: Request):
    engine = getattr(request.app.state, "predictive_engine", None)
    if not engine:
        raise HTTPException(503, "Predictive engine not initialized")
    ctx = {}
    return await engine.calculate_realtime_coaching_score(user_id, ctx)


@router.get("/unified-dashboard/{user_id}")
async def unified_dashboard(user_id: str, request: Request,
                             family_id: Optional[str] = None,
                             goals: Optional[str] = None):
    engine = getattr(request.app.state, "predictive_engine", None)
    if not engine:
        raise HTTPException(503, "Predictive engine not initialized")
    goal_list = goals.split(",") if goals else []
    return await engine.generate_unified_dashboard(user_id, family_id, goal_list)


@router.get("/habit-tracking/{user_id}")
async def get_habit_tracking(user_id: str, request: Request):
    engine = getattr(request.app.state, "predictive_engine", None)
    if not engine or not engine.db_pool:
        return {"habits": []}
    try:
        async with engine.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, habit_type, habit_description, started_at, target_days,
                       current_streak, longest_streak, total_completions, total_misses,
                       status, predicted_adoption_days, predicted_crystallization_days,
                       predicted_maintenance_probability, last_completion_at
                FROM therapeutic_habit_tracking
                WHERE user_id = $1
                ORDER BY created_at DESC
            """, user_id)
        return {"habits": [dict(r) for r in rows]}
    except Exception as e:
        logger.warning("predictive_api: habit tracking query error: %s", e)
        return {"habits": []}


@router.post("/habit-tracking/{user_id}")
async def create_habit_tracking(user_id: str, body: HabitRequest, request: Request):
    engine = getattr(request.app.state, "predictive_engine", None)
    if not engine:
        raise HTTPException(503, "Predictive engine not initialized")
    return await engine.predict_habit_success_timeline(user_id, body.habit_type, body.habit_description)


@router.get("/prediction-accuracy")
async def prediction_accuracy(request: Request, days: int = 90):
    engine = getattr(request.app.state, "predictive_engine", None)
    if not engine or not engine.db_pool:
        return {"status": "no_data", "accuracy": 0}
    try:
        async with engine.db_pool.acquire() as conn:
            total = await conn.fetchval("""
                SELECT COUNT(*) FROM therapeutic_predictions
                WHERE created_at > NOW() - ($1 || ' days')::INTERVAL
            """, str(days))
            with_outcome = await conn.fetchval("""
                SELECT COUNT(*) FROM therapeutic_predictions
                WHERE actual_outcome IS NOT NULL
                AND created_at > NOW() - ($1 || ' days')::INTERVAL
            """, str(days))
            avg_accuracy = await conn.fetchval("""
                SELECT AVG(accuracy_score) FROM therapeutic_predictions
                WHERE accuracy_score IS NOT NULL
                AND created_at > NOW() - ($1 || ' days')::INTERVAL
            """, str(days))
        return {
            "total_predictions": total or 0,
            "predictions_with_outcome": with_outcome or 0,
            "average_accuracy": round(float(avg_accuracy or 0), 2),
            "days_analyzed": days,
        }
    except Exception as e:
        logger.warning("predictive_api: accuracy query error: %s", e)
        return {"status": "error", "accuracy": 0}
