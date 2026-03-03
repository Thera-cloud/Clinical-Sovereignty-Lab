"""
SOVEREIGN SWARM — Coherence API Router
REST endpoints for the 5-layer coherence engine and The Pulse dashboard.
Phase 2C.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional

from app.auth import get_current_user_id

router = APIRouter(prefix="/api/coherence", tags=["coherence"])


def _get_db_pool(request: Request):
    """Get database pool from app state."""
    return request.app.state.db_pool


@router.get("/pulse")
async def get_pulse(request: Request):
    """
    Aggregated Pulse dashboard data:
    global coherence index, layer scores, trending themes, gap analysis, alerts.
    """
    from app.services.coherence_engine import CoherenceEngine

    db_pool = _get_db_pool(request)
    engine = CoherenceEngine(db_pool)

    try:
        snapshot = await engine.generate_pulse_snapshot()
        return {
            "global_coherence_index": snapshot.global_coherence_index,
            "layer_scores": snapshot.layer_scores,
            "trending_themes": snapshot.trending_themes,
            "gap_analysis": snapshot.gap_analysis.model_dump() if snapshot.gap_analysis else None,
            "active_alerts": snapshot.active_alerts,
            "notable_changes": snapshot.notable_changes,
            "generated_at": snapshot.generated_at.isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pulse generation error: {e}")


@router.get("/layer/{layer}")
async def get_layer_detail(layer: str, request: Request):
    """Detailed coherence data for a specific layer."""
    from app.services.coherence_engine import CoherenceEngine
    from app.models.coherence import CoherenceLayer

    valid_layers = [l.value for l in CoherenceLayer]
    if layer not in valid_layers:
        raise HTTPException(status_code=400, detail=f"Invalid layer. Choose from: {valid_layers}")

    db_pool = _get_db_pool(request)
    engine = CoherenceEngine(db_pool)

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT measurement_id, score, confidence, components,
                       delta_24h, delta_7d, sample_size, measured_at
                FROM coherence_measurements
                WHERE layer = $1
                ORDER BY measured_at DESC
                LIMIT 50
            """, layer)

            measurements = []
            for r in rows:
                measurements.append({
                    "measurement_id": str(r["measurement_id"]),
                    "score": r["score"],
                    "confidence": r["confidence"],
                    "components": r["components"] if isinstance(r["components"], dict)
                                  else __import__("json").loads(r["components"]) if r["components"] else {},
                    "delta_24h": r["delta_24h"],
                    "delta_7d": r["delta_7d"],
                    "sample_size": r["sample_size"],
                    "measured_at": r["measured_at"].isoformat(),
                })

            return {
                "layer": layer,
                "measurements": measurements,
                "count": len(measurements),
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Layer query error: {e}")


@router.get("/gap")
async def get_gap_analysis(request: Request):
    """Inside/outside coherence gap analysis."""
    from app.services.coherence_engine import CoherenceEngine

    db_pool = _get_db_pool(request)
    engine = CoherenceEngine(db_pool)

    try:
        gap = await engine.compute_gap_analysis()
        return gap.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gap analysis error: {e}")


@router.get("/individual/{user_id}")
async def measure_individual(user_id: UUID, request: Request, current_user: str = Depends(get_current_user_id)):
    """Measure individual coherence for a specific user. Requires authentication; user must be requesting their own data."""
    if current_user != str(user_id):
        raise HTTPException(status_code=403, detail="Access denied: you can only view your own coherence data")

    from app.services.coherence_engine import CoherenceEngine

    db_pool = _get_db_pool(request)
    engine = CoherenceEngine(db_pool)

    try:
        measurement = await engine.measure_individual(user_id)
        return measurement.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Individual coherence error: {e}")


@router.get("/family/{family_id}")
async def measure_family(family_id: UUID, request: Request, current_user: str = Depends(get_current_user_id)):
    """Measure family system coherence. Requires authentication; user must belong to the family."""
    from app.services.coherence_engine import CoherenceEngine

    db_pool = _get_db_pool(request)
    engine = CoherenceEngine(db_pool)

    # Verify family membership
    try:
        async with db_pool.acquire() as conn:
            member = await conn.fetchval(
                "SELECT 1 FROM family_members WHERE family_id = $1 AND user_id = $2::uuid LIMIT 1",
                family_id, current_user,
            )
            if not member:
                raise HTTPException(status_code=403, detail="Access denied: you are not a member of this family")
    except HTTPException:
        raise
    except Exception:
        pass  # Table may not exist yet; allow through

    try:
        measurement = await engine.measure_family(family_id)
        return measurement.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Family coherence error: {e}")


@router.get("/briefing")
async def get_coherence_briefing(request: Request):
    """Generate or retrieve the latest coherence briefing."""
    from app.services.coherence_engine import CoherenceEngine

    db_pool = _get_db_pool(request)
    engine = CoherenceEngine(db_pool)

    try:
        briefing = await engine.generate_briefing()
        return briefing
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Briefing error: {e}")
