"""
SOVEREIGN SWARM — Clinical Governance Models
Data contracts for scope of practice enforcement, mandatory reporting,
and clinical record keeping.

Operational Specifications §5 — Clinical Governance.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# =============================================================================
# SCOPE OF PRACTICE
# =============================================================================

class BoundaryType(str, Enum):
    DIAGNOSIS = "diagnosis"
    MEDICATION = "medication"
    LEGAL = "legal"
    MEDICAL = "medical"
    RELIGIOUS = "religious"
    FINANCIAL = "financial"


class ScopeOfPractice(BaseModel):
    """Clinical boundary enforcement for Little Nate."""
    boundary_type: BoundaryType
    description: str = ""
    trigger_phrases: List[str] = Field(default_factory=list)
    response_template: str = ""
    redirect_to: str = "coach"  # coach, crisis_line, medical, legal
    severity: str = "standard"  # standard, high, critical
    log_required: bool = True


class ScopeViolationLog(BaseModel):
    """Log entry when a scope boundary is triggered."""
    log_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    session_id: Optional[str] = None
    boundary_type: BoundaryType
    trigger_content: str = ""
    nate_response: str = ""
    escalated_to: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# MANDATORY REPORTING
# =============================================================================

class ReportingTrigger(str, Enum):
    CHILD_ABUSE = "child_abuse"
    ELDER_ABUSE = "elder_abuse"
    SELF_HARM = "self_harm"
    HARM_TO_OTHERS = "harm_to_others"
    DOMESTIC_VIOLENCE = "domestic_violence"
    SUBSTANCE_CRISIS = "substance_crisis"


class MandatoryReportingProtocol(BaseModel):
    """Protocol for mandatory reporting situations."""
    protocol_id: str = Field(default_factory=lambda: str(uuid4()))
    trigger: ReportingTrigger
    detection_source: str = ""  # ai_detection, coach_flag, self_report
    user_id: str
    session_id: Optional[str] = None
    coach_id: Optional[str] = None
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    severity: str = "high"
    immediate_actions: List[str] = Field(default_factory=list)
    escalation_chain: List[str] = Field(default_factory=list)
    coach_notified: bool = False
    coach_notified_at: Optional[datetime] = None
    supervisor_notified: bool = False
    report_filed: bool = False
    report_filed_at: Optional[datetime] = None
    outcome: Optional[str] = None
    audit_trail: List[Dict[str, Any]] = Field(default_factory=list)


# =============================================================================
# CLINICAL RECORD KEEPING
# =============================================================================

class ClinicalRecordType(str, Enum):
    SESSION_NOTE = "session_note"
    PROGRESS_NOTE = "progress_note"
    TREATMENT_PLAN = "treatment_plan"
    SAFETY_PLAN = "safety_plan"
    ASSESSMENT = "assessment"
    DISCHARGE_SUMMARY = "discharge_summary"
    CONSENT_FORM = "consent_form"
    INCIDENT_REPORT = "incident_report"


class ClinicalRecord(BaseModel):
    """Clinical record for compliance and audit."""
    record_id: str = Field(default_factory=lambda: str(uuid4()))
    record_type: ClinicalRecordType
    user_id: str
    coach_id: Optional[str] = None
    session_id: Optional[str] = None
    content: str = ""
    ai_generated: bool = False
    ai_generation_model: Optional[str] = None
    coach_reviewed: bool = False
    coach_reviewed_at: Optional[datetime] = None
    coach_signature: Optional[str] = None
    retention_period_years: int = 7
    encrypted: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None


class ClinicalRecordKeeping(BaseModel):
    """Master clinical record keeping configuration and state."""
    user_id: str
    total_records: int = 0
    last_session_note: Optional[datetime] = None
    last_treatment_plan_update: Optional[datetime] = None
    safety_plan_active: bool = False
    safety_plan_last_review: Optional[datetime] = None
    retention_compliant: bool = True
    pending_coach_reviews: int = 0
    encryption_verified: bool = True
