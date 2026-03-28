from datetime import datetime
from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field, validator
from uuid import UUID

class PatientVaultCreate(BaseModel):
    patient_id: UUID
    password: str = Field(..., min_length=12, description="Patient vault password")
    metadata: Dict[str, Union[str, int, float]]

class EncryptedDataStore(BaseModel):
    data_category: str = Field(..., regex="^(medical_history|lab_results|genetics|prescriptions|imaging|notes)$")
    data: Dict[str, Union[str, int, float, List]]
    consent_required: bool = True

class DataConsentGrant(BaseModel):
    data_id: int
    provider_id: UUID
    scope: str = Field(..., regex="^(read|write|share|delete)$")
    expires_at: Optional[datetime] = None

class VaultResponse(BaseModel):
    patient_id: UUID
    vault_status: str

class DataStoreResponse(BaseModel):
    data_id: int
    status: str

class ConsentResponse(BaseModel):
    consent_id: int

class RevokeResponse(BaseModel):
    revoked_consents: str

class DeleteResponse(BaseModel):
    status: str
