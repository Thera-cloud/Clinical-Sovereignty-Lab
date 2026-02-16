"""
Nevedal Research Reports API
Generates 5 report types for the Nevedal Research Laboratory (SC_07).
"""

from fastapi import APIRouter, Depends, Request, HTTPException
from uuid import UUID
from typing import List, Optional

from app.services.api_server import require_admin

router = APIRouter(
    prefix="/api/research/nevedal/reports",
    tags=["nevedal_reports"],
    dependencies=[Depends(require_admin)],
)


@router.post("/generate")
async def generate_report(request: Request):
    """
    Generate a Nevedal research report.

    Body:
        report_type: individual_coherence | dyad_comparison | family_dynamics
                     | longitudinal_trends | coach_efficacy
        subject_ids: list of UUID strings (user/coach IDs)
        date_range_days: int (default 84 = 12 weeks)
        family_id: optional UUID (for family_dynamics)
    """
    body = await request.json()
    report_type = body.get("report_type")
    subject_ids_raw = body.get("subject_ids", [])
    date_range_days = body.get("date_range_days", 84)
    family_id = body.get("family_id")

    if not report_type:
        raise HTTPException(400, "report_type is required")
    if not subject_ids_raw and report_type != "family_dynamics":
        raise HTTPException(400, "subject_ids is required")

    subject_ids = [UUID(sid) if isinstance(sid, str) else sid for sid in subject_ids_raw]

    from app.services.nevedal_report_generator import NevedalReportGenerator

    db = request.app.state.db_pool
    gen = NevedalReportGenerator(db)

    kwargs = {}
    if family_id:
        kwargs["family_id"] = UUID(family_id) if isinstance(family_id, str) else family_id

    report = await gen.generate(
        report_type=report_type,
        subject_ids=subject_ids,
        date_range_days=date_range_days,
        **kwargs,
    )

    return report


@router.get("/types")
async def list_report_types():
    """List available report types."""
    return {
        "report_types": [
            {
                "id": "individual_coherence",
                "name": "Individual Coherence Report",
                "description": "Single user C_emo trends, CEE events, biometric summary",
                "required_ids": ["user_id"],
            },
            {
                "id": "dyad_comparison",
                "name": "Dyad Comparison Report",
                "description": "Coach-client synchrony, correlation, shared CEE moments",
                "required_ids": ["subject_a_id", "subject_b_id"],
            },
            {
                "id": "family_dynamics",
                "name": "Family Dynamics Report",
                "description": "Multi-member coherence matrix, family wellness index",
                "required_ids": ["family_id"],
            },
            {
                "id": "longitudinal_trends",
                "name": "Longitudinal Trends (12-week)",
                "description": "C_emo trend with statistical analysis over 12+ weeks",
                "required_ids": ["user_id"],
            },
            {
                "id": "coach_efficacy",
                "name": "Coach Efficacy Analysis",
                "description": "Coach effectiveness across all assigned clients",
                "required_ids": ["coach_id"],
            },
        ]
    }
