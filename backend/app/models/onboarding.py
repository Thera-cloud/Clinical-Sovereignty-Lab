"""
SOVEREIGN SWARM — Onboarding Models
Data contracts for the onboarding flow: welcome conversation, cold-start
Nevedal calibration, and coach matching.

Operational Specifications §1 — Onboarding.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# ENUMERATIONS
# =============================================================================

class OnboardingStage(str, Enum):
    WELCOME = "welcome"
    INITIAL_ASSESSMENT = "initial_assessment"
    NEVEDAL_COLD_START = "nevedal_cold_start"
    COACH_MATCH = "coach_match"
    FIBRE_ASSIGNMENT = "fibre_assignment"
    COMPLETE = "complete"


class WelcomeConversationType(str, Enum):
    CASUAL = "casual"         # Low-pressure opener
    GUIDED = "guided"         # Structured questionnaire
    VOICE_INTRO = "voice_intro"  # Voice-enabled intro


class MatchCriteria(str, Enum):
    ORIENTATION_FIT = "orientation_fit"
    ATTACHMENT_COMPATIBILITY = "attachment_compatibility"
    SPECIALTY_RELEVANCE = "specialty_relevance"
    AI_COMFORT = "ai_comfort"
    AVAILABILITY = "availability"
    CULTURAL_MATCH = "cultural_match"


# =============================================================================
# ONBOARDING INITIATION
# =============================================================================

class OnboardingInitiation(BaseModel):
    """Master onboarding record for a new member."""
    initiation_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    referral_source: Optional[str] = None
    subscription_tier: str = "threshold"
    stage: OnboardingStage = OnboardingStage.WELCOME
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    abandoned_at: Optional[datetime] = None
    welcome_conversation_id: Optional[str] = None
    cold_start_complete: bool = False
    initial_c_emo: Optional[float] = None
    initial_gamma_env: Optional[float] = None
    initial_p_ent: Optional[float] = None
    assigned_coach_id: Optional[str] = None
    assigned_fibre_ids: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# WELCOME CONVERSATION
# =============================================================================

class WelcomeTurn(BaseModel):
    """A single turn in the welcome conversation."""
    role: str = "nate"  # nate | member
    content: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    detected_themes: List[str] = Field(default_factory=list)
    detected_emotions: List[str] = Field(default_factory=list)
    pii_redacted: bool = False


class WelcomeConversation(BaseModel):
    """The initial conversation between Little Nate and a new member."""
    conversation_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    conversation_type: WelcomeConversationType = WelcomeConversationType.CASUAL
    turns: List[WelcomeTurn] = Field(default_factory=list)
    presenting_concern: Optional[str] = None
    initial_mood: Optional[str] = None
    therapy_history: Optional[str] = None
    safety_screen_passed: bool = True
    safety_flag: bool = False
    safety_flag_reason: Optional[str] = None
    preferences: Dict[str, Any] = Field(default_factory=dict)
    goals: List[str] = Field(default_factory=list)
    completed: bool = False
    duration_seconds: int = 0


# =============================================================================
# NEVEDAL COLD-START
# =============================================================================

class NevedalColdStart(BaseModel):
    """Cold-start calibration for a new member's Nevedal parameters."""
    user_id: str
    initiated_at: datetime = Field(default_factory=datetime.utcnow)
    voice_sample_collected: bool = False
    text_exchanges: int = 0
    initial_pitch_mean: Optional[float] = None
    initial_pitch_variance: Optional[float] = None
    initial_energy: Optional[float] = None
    initial_speech_rate: Optional[float] = None
    initial_pause_ratio: Optional[float] = None
    computed_p_ent: float = 0.5
    computed_gamma_env: float = 0.5
    computed_t_tunnel: float = 0.3
    cold_start_c_emo: float = 0.0
    baseline_established: bool = False
    calibration_confidence: float = 0.0
    calibration_exchanges_needed: int = 3


# =============================================================================
# COACH MATCHING ENGINE
# =============================================================================

class CoachProfile(BaseModel):
    """Coach attributes relevant to matching."""
    coach_id: str
    name: str = ""
    therapeutic_orientation: Dict[str, float] = Field(default_factory=dict)
    specialties: List[str] = Field(default_factory=list)
    ai_comfort_level: float = 0.0
    attachment_style_expertise: List[str] = Field(default_factory=list)
    cultural_competencies: List[str] = Field(default_factory=list)
    current_caseload: int = 0
    max_caseload: int = 30
    availability_hours: Dict[str, List[str]] = Field(default_factory=dict)
    average_alliance_score: float = 0.0
    match_acceptance_rate: float = 0.0


class MatchScore(BaseModel):
    """Match scoring between a member and a coach."""
    coach_id: str
    member_id: str
    overall_score: float = 0.0
    orientation_fit: float = 0.0
    attachment_compatibility: float = 0.0
    specialty_relevance: float = 0.0
    ai_comfort_match: float = 0.0
    availability_overlap: float = 0.0
    cultural_match: float = 0.0
    caseload_factor: float = 1.0
    reasons: List[str] = Field(default_factory=list)


class CoachMatchResult(BaseModel):
    """Final result of the coach matching engine."""
    member_id: str
    top_matches: List[MatchScore] = Field(default_factory=list)
    selected_coach_id: Optional[str] = None
    selection_method: str = "algorithm"  # algorithm | member_choice | manual
    match_confidence: float = 0.0
    match_timestamp: datetime = Field(default_factory=datetime.utcnow)
