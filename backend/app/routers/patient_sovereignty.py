from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.security import APIKeyHeader

import asyncio
from typing import Dict

from app.services.patient_sovereignty_service import patient_sovereignty
from app.schemas.patient_sovereignty import (
    PatientVaultCreate, 
    EncryptedDataStore, 
    DataConsentGrant,
    VaultResponse,
    DataStoreResponse,
    ConsentResponse,
    RevokeResponse,
    DeleteResponse
)

router = APIRouter(
    prefix="/api/v1/patient-sovereignty",
    tags=["patient-sovereignty"],
    responses={404: {"description": "Not found"}},
)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

@router.post(
    "/vaults",
    response_model=VaultResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create patient data sovereignty vault"
)
async def create_patient_vault(
    vault_data: PatientVaultCreate,
    background_tasks: BackgroundTasks
):
    """Create HIPAA-grade encrypted patient data vault."""
    try:
        result = await patient_sovereignty.create_patient_vault(
            patient_id=str(vault_data.patient_id),
            password=vault_data.password,
            metadata=vault_data.metadata
        )
        return VaultResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post(
    "/{patient_id}/data",
    response_model=DataStoreResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Store encrypted patient data"
)
async def store_encrypted_data(
    patient_id: str,
    data: EncryptedDataStore,
    password: str,
    api_key: str = Depends(api_key_header)
):
    """Store encrypted data in patient vault (patient-only)."""
    if not api_key:
        raise HTTPException(status_code=401, detail="API key required")
    
    patient_key = await patient_sovereignty.generate_patient_key(patient_id, password)
    result = await patient_sovereignty.store_encrypted_data(
        patient_id=patient_id,
        patient_key=patient_key,
        data_category=data.data_category,
        data=data.data
    )
    return DataStoreResponse(**result)

@router.post(
    "/{patient_id}/consents",
    response_model=ConsentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Grant granular data access consent"
)
async def grant_data_consent(
    patient_id: str,
    consent: DataConsentGrant,
    password: str
):
    """Patient grants time-limited consent to provider."""
    patient_key = await patient_sovereignty.generate_patient_key(patient_id, password)
    result = await patient_sovereignty.grant_data_consent(
        patient_id=patient_id,
        data_id=consent.data_id,
        provider_id=str(consent.provider_id),
        scope=consent.scope,
        expires_at=consent.expires_at
    )
    return ConsentResponse(**result)

@router.post(
    "/{patient_id}/revoke-all",
    response_model=RevokeResponse,
    status_code=status.HTTP_200_OK,
    summary="Revoke ALL consents instantly"
)
async def revoke_all_consents(patient_id: str):
    """Patient revokes all consents (one-click)."""
    result = await patient_sovereignty.revoke_all_consents(patient_id)
    return RevokeResponse(**result)

@router.delete(
    "/{patient_id}/vault",
    response_model=DeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete entire patient vault (right to be forgotten)"
)
async def delete_patient_vault(patient_id: str, password: str):
    """Patient deletes entire sovereignty vault + all data."""
    patient_key = await patient_sovereignty.generate_patient_key(patient_id, password)
    result = await patient_sovereignty.delete_patient_vault(patient_id)
    return DeleteResponse(**result)
