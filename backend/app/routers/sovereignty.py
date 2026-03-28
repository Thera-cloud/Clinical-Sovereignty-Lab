from typing import Any, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

import app.services.patient_sovereignty as sovereignty_service
from app.config import settings
from app.routers.auth import get_current_active_user
from app.core.security import verify_token

from pydantic import BaseModel

router = APIRouter(
    prefix="/api/sovereignty",
    tags=["patient-sovereignty"],
    responses={404: {"description": "Not found"}},
)

class PatientRecord(BaseModel):
    patient_id: str
    data_category: str
    data_hash: str
    consent_status: str
    access_token: Optional[str] = None

class SovereigntyRequest(BaseModel):
    patient_id: str
    action: str  # 'claim', 'release', 'audit'
    data_category: str

@router.post("/claim", response_model=dict, status_code=status.HTTP_201_CREATED)
async def claim_sovereignty(
    request: SovereigntyRequest,
    current_user: dict = Depends(get_current_active_user),
    db_pool: asyncpg.Pool = Depends(lambda: db_pool)
) -> dict:
    """
    Claim sovereignty over patient data record.
    HIPAA-grade encryption + audit trail.
    """
    if current_user["id"] != request.patient_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Patient ID mismatch - sovereignty violation"
        )
    
    result = await sovereignty_service.claim_sovereignty(
        db_pool, request.patient_id, request.data_category, current_user["id"]
    )
    return {"status": "claimed", "record_id": result["record_id"]}

@router.post("/release", response_model=dict)
async def release_sovereignty(
    request: SovereigntyRequest,
    current_user: dict = Depends(get_current_active_user),
    db_pool: asyncpg.Pool = Depends(lambda: db_pool)
) -> dict:
    """
    Release sovereignty (data deletion/destruction).
    """
    if current_user["id"] != request.patient_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only sovereign patient can release data"
        )
    
    await sovereignty_service.release_sovereignty(
        db_pool, request.patient_id, request.data_category
    )
    return {"status": "released", "data_category": request.data_category}

@router.get("/{patient_id}/audit", response_model=List[dict])
async def get_sovereignty_audit(
    patient_id: str,
    current_user: dict = Depends(get_current_active_user),
    db_pool: asyncpg.Pool = Depends(lambda: db_pool)
) -> List[dict]:
    """
    Immutable audit trail of all sovereignty actions.
    """
    if current_user["id"] != patient_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Audit access restricted to sovereign patient"
        )
    
    records = await sovereignty_service.get_audit_trail(db_pool, patient_id)
    return records

@router.get("/{patient_id}/status", response_model=dict)
async def get_sovereignty_status(
    patient_id: str,
    current_user: dict = Depends(get_current_active_user),
    db_pool: asyncpg.Pool = Depends(lambda: db_pool)
) -> dict:
    """
    Current sovereignty status across all data categories.
    """
    records = await sovereignty_service.get_status(db_pool, patient_id)
    return {"patient_id": patient_id, "records": records}