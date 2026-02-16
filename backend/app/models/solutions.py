"""
SOVEREIGN SWARM — Applied Solutions Models (S1-S10)
Data contracts for all 10 clinical application patterns built on the
8-layer Sovereign Swarm foundation.

Patent-Pending — Clinical Sovereignty Lab
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# S1: SILENT CRISIS DETECTOR
# =============================================================================

class RiskTier(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    ORANGE = "orange"
    RED = "red"
    CRITICAL = "critical"


class MemberHealthView(BaseModel):
    """Trail Map aggregation: real-time view of a member's engagement health."""
    member_id: str
    last_interaction: Optional[datetime] = None
    hours_since_interaction: float = 0.0
    c_emo_at_last_interaction: float = 0.0
    c_emo_trajectory: str = "unknown"  # rising, stable, declining, unknown
    interaction_frequency_7d: float = 0.0
    interaction_frequency_30d: float = 0.0
    deviation_from_norm: float = 0.0
    risk_tier: RiskTier = RiskTier.GREEN


class SilentAlert(BaseModel):
    """Alert generated when a member exceeds inactivity thresholds."""
    alert_id: str = Field(default_factory=lambda: str(uuid4()))
    member_id: str
    alert_level: RiskTier
    hours_silent: float
    last_known_c_emo: float = 0.0
    c_emo_trajectory: str = "unknown"
    last_session_topic: Optional[str] = None
    predicted_reason: Optional[str] = None
    recommended_action: str = "gentle_checkin"
    outreach_channel: str = "preferred"
    cosmic_ring_partners: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RampUpActivation(BaseModel):
    """Quakete Ramp-Up protocol activation for silent crisis."""
    target_member_id: str
    trigger: str = "silent_crisis"
    activation_time: datetime = Field(default_factory=datetime.utcnow)
    cosmic_ring_id: Optional[str] = None
    partner_fibres: List[str] = Field(default_factory=list)
    actions: List[Dict[str, Any]] = Field(default_factory=list)


class SilentCrisisBriefing(BaseModel):
    """Coach briefing generated for silent crisis escalation."""
    member_id: str
    member_name: str
    coach_id: str
    briefing_type: str = "silent_crisis_alert"
    days_silent: int = 0
    last_interaction_date: Optional[datetime] = None
    last_interaction_summary: Optional[str] = None
    last_c_emo: float = 0.0
    c_emo_trend_30d: List[Tuple[str, float]] = Field(default_factory=list)
    foresight_assessment: Optional[str] = None
    transgenerational_context: Optional[str] = None
    previous_silence_episodes: List[Dict[str, Any]] = Field(default_factory=list)
    recommended_approach: Optional[str] = None
    outreach_history: List[Dict[str, Any]] = Field(default_factory=list)
    cosmic_ring_partner_status: List[Dict[str, Any]] = Field(default_factory=list)


# =============================================================================
# S2: FAMILY SANCTUARY EMOTIONAL WEATHER SYSTEM
# =============================================================================

class CommunicationMode(str, Enum):
    ATTACKING = "attacking"
    PURSUING = "pursuing"
    WITHDRAWING = "withdrawing"
    STONEWALLING = "stonewalling"
    REFLECTIVE = "reflective"
    VULNERABLE = "vulnerable"


class AttachmentActivation(str, Enum):
    SECURE_BASE = "secure_base"
    ANXIOUS_PROTEST = "anxious_protest"
    AVOIDANT_WITHDRAWAL = "avoidant_withdrawal"
    DISORGANIZED_FREEZE = "disorganized_freeze"


class MemberEmotionalState(BaseModel):
    """Per-member emotional state during a Family Sanctuary session."""
    member_id: str
    member_name: str = ""
    role_in_family: str = ""
    current_c_emo: float = 0.0
    c_emo_velocity: float = 0.0
    decoherence_gamma: float = 0.0
    tunneling_t: float = 0.0
    attachment_activation: AttachmentActivation = AttachmentActivation.SECURE_BASE
    communication_mode: CommunicationMode = CommunicationMode.REFLECTIVE
    emotional_primary: str = ""
    message_count: int = 0
    last_message_timestamp: Optional[datetime] = None
    silence_duration: float = 0.0


class DyadCoherence(BaseModel):
    """Coherence measurement between two family members in a live session."""
    member_a: str
    member_b: str
    coherence_score: float = 0.0
    entanglement: float = 0.0
    tunneling: float = 0.0
    pattern: str = "mutual_engagement"
    direction: Optional[str] = None
    repair_attempts: int = 0
    repair_success_rate: float = 0.0
    a_decoherence_when_b_speaks: float = 0.0
    b_decoherence_when_a_speaks: float = 0.0
    a_tunneling_when_b_speaks: float = 0.0
    b_tunneling_when_a_speaks: float = 0.0


class EmotionalWeatherMap(BaseModel):
    """Real-time emotional topology of an active Family Sanctuary session."""
    sanctuary_id: str
    family_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    member_states: Dict[str, MemberEmotionalState] = Field(default_factory=dict)
    dyad_coherence: Dict[str, DyadCoherence] = Field(default_factory=dict)
    system_coherence: float = 0.0
    system_volatility: float = 0.0
    dominant_pattern: str = "harmonious"
    escalation_risk: float = 0.0
    cee_window_open: bool = False
    cee_window_dyad: Optional[Tuple[str, str]] = None
    influence_map: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    bridge_member: Optional[str] = None
    isolated_member: Optional[str] = None


class WeatherInformedIntervention(BaseModel):
    """Little Nate's decision output during Family Sanctuary."""
    intervention_type: str = "observe"
    target_member: Optional[str] = None
    bridge_member: Optional[str] = None
    isolated_member: Optional[str] = None
    therapeutic_frame: str = "EFT"
    tone: str = "warm"
    urgency: str = "next_pause"
    clinical_reasoning: Optional[str] = None


# =============================================================================
# S3: PREDICTIVE COACH PREPARATION ENGINE
# =============================================================================

class CurrentStateSection(BaseModel):
    c_emo_current: float = 0.0
    c_emo_7day_average: float = 0.0
    primary_emotion: str = ""
    secondary_emotion: str = ""
    attachment_activation: str = ""
    active_themes: List[str] = Field(default_factory=list)
    unresolved_from_last_session: List[str] = Field(default_factory=list)
    homework_completion: str = "unknown"
    between_session_events: List[str] = Field(default_factory=list)
    family_sanctuary_activity: Dict[str, Any] = Field(default_factory=dict)


class TrajectorySection(BaseModel):
    c_emo_direction: str = "stable"
    c_emo_velocity: float = 0.0
    gamma_trend: str = "stable"
    tunneling_trend: str = "stable"
    engagement_trend: str = "stable"
    key_shift: Optional[str] = None


class PredictionSection(BaseModel):
    predicted_theme: Optional[str] = None
    confidence: float = 0.0
    prediction_basis: List[str] = Field(default_factory=list)
    predicted_emotional_state: Optional[str] = None
    predicted_defense: Optional[str] = None
    cee_opportunity: Optional[str] = None
    risk_if_missed: Optional[str] = None


class RecommendedFocusSection(BaseModel):
    primary_recommendation: Optional[str] = None
    opening_approach: Optional[str] = None
    therapeutic_frame: str = "EFT"
    specific_techniques: List[str] = Field(default_factory=list)
    things_to_avoid: List[str] = Field(default_factory=list)


class SessionContextSection(BaseModel):
    total_sessions: int = 0
    sessions_since_last_major_shift: int = 0
    session_frequency: str = "weekly"
    therapeutic_alliance_score: float = 0.0
    presenting_problem_original: Optional[str] = None
    presenting_problem_current: Optional[str] = None
    treatment_goals: List[str] = Field(default_factory=list)
    goal_progress: Dict[str, float] = Field(default_factory=dict)
    medications_if_known: List[str] = Field(default_factory=list)
    external_providers: List[str] = Field(default_factory=list)


class RiskSection(BaseModel):
    current_risk_level: str = "low"
    risk_factors_present: List[str] = Field(default_factory=list)
    protective_factors_present: List[str] = Field(default_factory=list)
    safety_plan_active: bool = False
    last_safety_assessment_date: Optional[datetime] = None
    recommended_safety_action: str = "routine_monitoring"


class PredictiveCoachBriefing(BaseModel):
    """Pre-session briefing generated 2 hours before every scheduled session."""
    briefing_id: str = Field(default_factory=lambda: str(uuid4()))
    coach_id: str
    member_id: str
    member_name: str = ""
    session_datetime: Optional[datetime] = None
    briefing_generated: datetime = Field(default_factory=datetime.utcnow)
    current_state: CurrentStateSection = Field(default_factory=CurrentStateSection)
    trajectory: TrajectorySection = Field(default_factory=TrajectorySection)
    prediction: PredictionSection = Field(default_factory=PredictionSection)
    recommended_focus: RecommendedFocusSection = Field(default_factory=RecommendedFocusSection)
    session_context: SessionContextSection = Field(default_factory=SessionContextSection)
    risk_assessment: RiskSection = Field(default_factory=RiskSection)


# =============================================================================
# S4: QUAKETE RESCUE IN LIVE THERAPY
# =============================================================================

class QuaketeRescueProtocol(BaseModel):
    """CEE window Quakete activation protocol — must complete in <500ms."""
    rescue_id: str = Field(default_factory=lambda: str(uuid4()))
    cee_detection_source: str = "nevedal_realtime"
    target_fibre_id: str
    target_fibre_health: float = 0.0
    target_fibre_latency_ms: float = 0.0
    latency_threshold_ms: float = 500.0
    cosmic_ring_id: Optional[str] = None
    partner_fibres: List[str] = Field(default_factory=list)
    partner_health_scores: List[float] = Field(default_factory=list)
    energy_donation_amount: float = 0.0
    transfer_type: str = "ion_donation"
    lorentz_boost_factor: float = 1.0
    briefing_generated: bool = False
    briefing_delivery_ms: float = 0.0
    cee_window_still_open: bool = True


class CEEWindowBriefing(BaseModel):
    """Real-time briefing delivered to coach during a CEE window."""
    urgency: str = "CEE_WINDOW_OPEN"
    member_name: str = ""
    emotional_state: str = ""
    recommended_action: str = ""
    avoid: str = ""
    estimated_window_duration_seconds: int = 60
    prediction_error: Optional[str] = None


# =============================================================================
# S5: CULTURAL SENTINEL COMMUNITY EARLY WARNING
# =============================================================================

class CulturalSignal(BaseModel):
    """External cultural signal detected by SkyEye + Cultural Sentinel."""
    signal_id: str = Field(default_factory=lambda: str(uuid4()))
    source_platform: str = ""
    signal_type: str = ""  # economic, political, health, community, cultural
    description: str = ""
    keywords: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    sentiment: float = 0.0
    volume: int = 0
    velocity: float = 0.0
    geographic_scope: str = "national"
    affected_demographics: List[str] = Field(default_factory=list)
    first_detected: datetime = Field(default_factory=datetime.utcnow)
    confidence: float = 0.0


class MemberImpactAssessment(BaseModel):
    """Assessment of how a cultural signal impacts a specific member."""
    member_id: str
    match_confidence: float = 0.0
    match_reason: str = ""
    predicted_impact_severity: str = "low"
    predicted_impact_timeline: Optional[str] = None
    recommended_coach_action: Optional[str] = None


class CommunityEarlyWarning(BaseModel):
    """Community-level early warning event."""
    warning_id: str = Field(default_factory=lambda: str(uuid4()))
    signal: Optional[CulturalSignal] = None
    affected_members: List[MemberImpactAssessment] = Field(default_factory=list)
    total_families_affected: int = 0
    severity: str = "advisory"  # advisory, watch, warning, urgent
    recommended_platform_response: Optional[str] = None
    coach_alerts: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    content_response: Optional[str] = None
    outcome_tracking: bool = True


# =============================================================================
# S6: AUTONOMOUS COACH RECRUITMENT PIPELINE
# =============================================================================

class CoachRecruitmentCampaign(BaseModel):
    """Campaign targeting a specific coach specialty."""
    campaign_id: str = Field(default_factory=lambda: str(uuid4()))
    target_specialty: str = ""
    target_platforms: List[str] = Field(default_factory=list)
    content_pillars: List[str] = Field(default_factory=list)
    posting_cadence: Dict[str, int] = Field(default_factory=dict)
    engagement_rules: Dict[str, str] = Field(default_factory=dict)
    autonomy_level: str = "observation"
    approval_required: bool = True
    impressions: int = 0
    engagements: int = 0
    quiz_starts: int = 0
    quiz_completions: int = 0
    golden_tickets_sent: int = 0
    coaches_onboarded: int = 0
    conversion_rate: float = 0.0


class CoachAssessmentResult(BaseModel):
    """Result of a coach's therapeutic orientation assessment quiz."""
    quiz_id: str = Field(default_factory=lambda: str(uuid4()))
    prospect_name: str = ""
    prospect_email: Optional[str] = None
    therapeutic_orientation: Dict[str, float] = Field(default_factory=dict)
    ai_comfort_level: float = 0.0
    relational_values_score: float = 0.0
    platform_fit_score: float = 0.0
    match_score: float = 0.0
    specialty_match: Dict[str, float] = Field(default_factory=dict)
    recommended_dojos: List[str] = Field(default_factory=list)
    golden_ticket_eligible: bool = False


# =============================================================================
# S7: MEMORIAL ENCODING WISDOM PRESERVATION (extends quakete Memorial)
# =============================================================================

class WisdomEntry(BaseModel):
    """Distilled clinical wisdom from a Fibre's Evolution Journal."""
    pattern_observed: str = ""
    evidence_count: int = 0
    confidence: float = 0.0
    context: str = ""
    therapeutic_implication: str = ""
    recommended_application: str = ""


class MemorialExtended(BaseModel):
    """Extended Memorial with full wisdom distillation."""
    memorial_id: str = Field(default_factory=lambda: str(uuid4()))
    source_fibre_id: str
    source_fibre_type: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    dissolved_at: Optional[datetime] = None
    lifespan_days: int = 0
    wisdom_entries: List[WisdomEntry] = Field(default_factory=list)
    member_knowledge: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    cross_member_patterns: List[Dict[str, Any]] = Field(default_factory=list)
    failures: List[Dict[str, Any]] = Field(default_factory=list)
    ring_legacy: Dict[str, Any] = Field(default_factory=dict)
    inheritor_fibre_id: Optional[str] = None
    inheritance_priority: List[str] = Field(default_factory=list)


# =============================================================================
# S8: GRADUATED AUTONOMY
# =============================================================================

class AutonomyLevel(str, Enum):
    OBSERVATION = "observation"
    RESTRICTED = "restricted"
    AUTONOMOUS = "autonomous"


class AutonomyAuditTrail(BaseModel):
    """Fibre autonomy tracking and audit record."""
    fibre_id: str
    fibre_type: str = ""
    current_level: AutonomyLevel = AutonomyLevel.OBSERVATION
    promotion_history: List[Dict[str, Any]] = Field(default_factory=list)
    demotion_history: List[Dict[str, Any]] = Field(default_factory=list)
    total_proposals: int = 0
    approved_proposals: int = 0
    rejected_proposals: int = 0
    total_autonomous_actions: int = 0
    successful_actions: int = 0
    failed_actions: int = 0
    member_feedback_scores: List[float] = Field(default_factory=list)
    coherence_impact_scores: List[float] = Field(default_factory=list)


# =============================================================================
# S9: TRANSGENERATIONAL PATTERN RECOGNITION
# =============================================================================

class TransgenerationalPattern(BaseModel):
    """Cross-family pattern detected by the Convergence Engine."""
    pattern_id: str = Field(default_factory=lambda: str(uuid4()))
    pattern_name: str = ""
    description: str = ""
    observation: str = ""
    families_observed: int = 0
    confidence: float = 0.0
    statistical_method: str = "correlation"
    p_value: float = 1.0
    effect_size: float = 0.0
    early_indicators: List[str] = Field(default_factory=list)
    predicted_manifestation: Optional[str] = None
    recommended_intervention: Optional[str] = None
    anonymization_verified: bool = True
    min_family_threshold: int = 50


# =============================================================================
# S10: NEVEDAL-QUAKETE RESONANCE BRIDGE IN COUPLES WORK
# =============================================================================

class OscillationPeak(BaseModel):
    """A detected peak in the withdrawer's Quakete frequency."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    peak_magnitude: float = 0.0
    peak_duration_seconds: float = 0.0
    correlated_message: Optional[str] = None
    message_characteristics: str = ""


class CoupleResonanceMonitor(BaseModel):
    """Continuous monitoring of a couple's Quakete frequency coupling."""
    monitor_id: str = Field(default_factory=lambda: str(uuid4()))
    partner_a_id: str
    partner_b_id: str
    partner_a_role: str = "pursuer"
    partner_b_role: str = "withdrawer"
    frequency_history_a: List[Tuple[str, float]] = Field(default_factory=list)
    frequency_history_b: List[Tuple[str, float]] = Field(default_factory=list)
    coupling_history: List[Tuple[str, float]] = Field(default_factory=list)
    detected_peaks: List[OscillationPeak] = Field(default_factory=list)
    coupling_insight: Optional[str] = None


# =============================================================================
# NOTIFICATION TIERS (Coach Experience)
# =============================================================================

class NotificationTier(str, Enum):
    WHISPER = "whisper"
    NUDGE = "nudge"
    ALERT = "alert"
    CRISIS = "crisis"


class LiveSessionNotification(BaseModel):
    """Notification delivered to a coach during a live session."""
    notification_id: str = Field(default_factory=lambda: str(uuid4()))
    tier: NotificationTier = NotificationTier.WHISPER
    message: str = ""
    suppressible: bool = True
    target_coach_id: str = ""
    session_id: Optional[str] = None
    member_id: Optional[str] = None
    auto_dismiss_seconds: Optional[int] = 10
    created_at: datetime = Field(default_factory=datetime.utcnow)
