"""
SOVEREIGN SWARM — Data Portability Models
Sovereign Legacy Format (SLF) export schema for full data portability.

Operational Specifications §6 — Data Portability.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# =============================================================================
# SLF SCHEMA
# =============================================================================

class SLFSection(str, Enum):
    """Sections included in a Sovereign Legacy Format export."""
    IDENTITY = "identity"
    SESSIONS = "sessions"
    COHERENCE = "coherence"
    VOICE_BIOMETRICS = "voice_biometrics"
    FAMILY_SANCTUARY = "family_sanctuary"
    NIGHT_SCHOOL = "night_school"
    FORESIGHT = "foresight"
    PATTERNS = "patterns"
    ME2ME_CRYSTAL = "me2me_crystal"
    ME2ME_IMPRINTS = "me2me_imprints"
    ME2ME_AVATAR = "me2me_avatar"
    TREATMENT_PLANS = "treatment_plans"
    SAFETY_PLANS = "safety_plans"
    BILLING = "billing"
    TRUST = "trust"


class SLFExportRequest(BaseModel):
    """Request to generate an SLF export."""
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    requested_by: str = ""  # user_id, coach_id, guardian_id
    sections: List[SLFSection] = Field(default_factory=lambda: list(SLFSection))
    include_me2me: bool = True
    include_raw_sessions: bool = False
    encryption_key_provided: bool = False
    encryption_algorithm: str = "AES-256-GCM"
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    approved: bool = False
    approved_at: Optional[datetime] = None


class SLFManifest(BaseModel):
    """Manifest file included in every SLF archive."""
    version: str = "1.0.0"
    export_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    user_display_name: str = ""
    exported_at: datetime = Field(default_factory=datetime.utcnow)
    sections_included: List[str] = Field(default_factory=list)
    total_files: int = 0
    total_size_bytes: int = 0
    encryption: str = "AES-256-GCM"
    checksum_algorithm: str = "SHA-256"
    checksums: Dict[str, str] = Field(default_factory=dict)
    platform_version: str = "1.0.0"
    schema_version: str = "1.0.0"


class SLFImportRequest(BaseModel):
    """Request to import an SLF archive."""
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    archive_path: str = ""
    archive_size_bytes: int = 0
    manifest_validated: bool = False
    checksum_verified: bool = False
    sections_to_import: List[SLFSection] = Field(default_factory=list)
    conflict_resolution: str = "skip_existing"
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    status: str = "pending"  # pending, validating, importing, complete, failed
    errors: List[str] = Field(default_factory=list)
