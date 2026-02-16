"""
SOVEREIGN SWARM — Pattern Engine API Router
REST endpoints for transgenerational pattern analysis:
  - Full family analysis
  - Emotional theme correlation
  - Coping mechanism inheritance
  - Trigger pattern mapping
  - Coherence trajectory correlation
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from app.services.api_server import require_admin
from app.services.pattern_engine import TransgenerationalPatternEngine
from app.services.exceptions import InsufficientDataException, LegacyVaultException


router = APIRouter(
    prefix="/api/patterns",
    tags=["Pattern Engine"],
    dependencies=[Depends(require_admin)],
)


@router.get("/status")
async def pattern_engine_status():
    """Lightweight health-check for architecture diagrams."""
    return {"status": "active", "service": "pattern_engine"}


# =============================================================================
# HELPERS
# =============================================================================


def _get_engine(request: Request) -> TransgenerationalPatternEngine:
    """Get TransgenerationalPatternEngine instance from app state."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not available")
    return TransgenerationalPatternEngine(db_pool)


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("/family/{family_id}")
async def full_transgenerational_analysis(
    request: Request,
    family_id: UUID,
) -> dict:
    """
    Run full transgenerational analysis for a family.
    Combines emotional themes, coping inheritance, trigger patterns, and coherence trajectories.
    """
    engine = _get_engine(request)
    try:
        return await engine.full_analysis(family_id)
    except InsufficientDataException as e:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient data: {e.message}",
        )
    except LegacyVaultException as e:
        raise HTTPException(
            status_code=400,
            detail=str(e.message),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/themes/{family_id}")
async def emotional_theme_correlation(
    request: Request,
    family_id: UUID,
) -> dict:
    """
    Get emotional theme correlation across family members.
    Identifies shared themes and unique member-specific themes.
    """
    engine = _get_engine(request)
    try:
        return await engine.analyze_emotional_themes(family_id)
    except InsufficientDataException as e:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient data: {e.message}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/coping/{family_id}")
async def coping_mechanism_inheritance(
    request: Request,
    family_id: UUID,
) -> dict:
    """
    Detect coping mechanism inheritance across generations.
    Maps adaptive strategies as inherited, adapted, or novel.
    """
    engine = _get_engine(request)
    try:
        return await engine.detect_coping_inheritance(family_id)
    except InsufficientDataException as e:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient data: {e.message}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/triggers/{family_id}")
async def trigger_pattern_mapping(
    request: Request,
    family_id: UUID,
) -> dict:
    """
    Map trigger patterns that activate inherited patterns across family members.
    Identifies environmental/relational triggers and temporal correlation.
    """
    engine = _get_engine(request)
    try:
        return await engine.map_trigger_patterns(family_id)
    except InsufficientDataException as e:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient data: {e.message}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/coherence/{family_id}")
async def coherence_trajectory_correlation(
    request: Request,
    family_id: UUID,
) -> dict:
    """
    Correlate coherence trajectories across family members.
    Measures whether therapeutic progress in one member correlates with changes in others.
    """
    engine = _get_engine(request)
    try:
        return await engine.correlate_trajectories(family_id)
    except InsufficientDataException as e:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient data: {e.message}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
