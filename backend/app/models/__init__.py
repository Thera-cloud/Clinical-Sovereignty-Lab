"""
SOVEREIGN SWARM — Pydantic Models
Shared data contracts for all swarm intelligence services.
"""

from app.models.fibre import (
    FibreType, FibreStatus, AutonomyLevel, FibreConfig,
    FibreTask, FibreResult, FibreLifespan, Fibre
)
from app.models.coherence import (
    CoherenceLayer, CoherenceMeasurement, CoherenceGap,
    LayerThresholds
)
from app.models.strategy import (
    StandingOrder, Insight, StrategyProposal, ProposalStatus,
    ProposalRisk, CoherenceBriefing, ForesightAlert as StrategyForesightAlert,
    SwarmOversightEntry, ApprovalDecisionAudit, FibreBehavioralBaseline,
    LegacyVaultConsent
)
from app.models.mesh import (
    MeshMessageType, MeshPriority, MeshMessage, ConvergenceAlert as MeshConvergenceAlert,
    MeshHealth
)
from app.models.notification import (
    NotificationChannel, ApprovalNotification, ApprovalResponse
)
from app.models.zefcp import (
    FragmentMode, FragmentType, MicroFragment, FibreObservation,
    ObservationAssembly, ADStructure, BLEAdvertisingPDU,
    BLETransportConfig, TransportMetrics, NFCProvisioningPayload
)
from app.models.quakete import (
    QuaketeMode, RingState, FibreTrailEmission, QuaketeIon,
    RingCord, CosmicRelationalRing, QuaketeAllocation,
    ReconnectionPlan, FragmentAcceleration, ParticleBeam,
    QuaketeBoost, QuaketeTransferResult, Memorial, RampUpPlan
)
from app.models.swarm import (
    FibreSummary, SwarmState, ConvergenceAlert, SwarmDirective
)
from app.models.foresight import (
    ForesightStreamType, ForesightScale, AlertSeverity,
    ForesightStream, ForesightAlert, PatternActivation
)

# Platinum Finish Line Models
from app.models.solutions import (
    RiskTier, MemberHealthView, SilentAlert, EmotionalWeatherMap,
    PredictiveCoachBriefing, CommunityEarlyWarning, AutonomyLevel as SolutionAutonomyLevel,
    AutonomyAuditTrail, TransgenerationalPattern, CoupleResonanceMonitor,
    NotificationTier, LiveSessionNotification,
)
from app.models.onboarding import (
    OnboardingStage, OnboardingInitiation, WelcomeConversation,
    NevedalColdStart, CoachMatchResult,
)
from app.models.me2me import (
    ConsentLevel, ConsentRecord, IdentityCrystal, AvatarCore as Me2MeAvatarCore,
    AvatarStatus, GrowthLayer, FamilyFabric, MigrationPhase, MigrationRecord,
    ImprintEntry, SovereignLegacyTrust, TrustBeneficiary,
)
from app.models.billing_metered import (
    BillingTier, UsageType, MeteredBillingLayer, LegacyVaultBilling,
    CostThresholdConfig,
)
from app.models.governance import (
    BoundaryType, ScopeOfPractice, ReportingTrigger,
    MandatoryReportingProtocol, ClinicalRecordType, ClinicalRecord,
)
from app.models.portability import (
    SLFSection, SLFExportRequest, SLFManifest, SLFImportRequest,
)
from app.models.vault import (
    ContentType, VaultFolder, VaultItem, TransferCrystal, VaultActivity,
    VaultStats, PreviewData, VaultSuggestion,
)
from app.models.hive_defense import (
    GateDecision, CuriosityLevel, DefconLevel, ContentVerdict,
    PenetratorPhase, GhostType, HelixVerdict, ProjectionStatus,
    HeartbeatPulse, ThreeCordVerification,
    MirrorNamespace, MirrorSignal,
    CuriosityEvent, MirrorReflection,
    DefconState, DriftScore, ContentSentinelResult,
    PenetratorReport, GhostMission,
    AttackerProfile, ForensicRecord,
    EphemeralCertificate, HelixState, InvertedSpace,
    ProjectedHelixDeployment, RecursiveLearningState,
    QuarantineRecord, BehavioralSnapshot,
    ConservationLedgerEntry, CanaryCredential, TripwireActivation,
    HIVE_EVENT_TOPICS,
)

__all__ = [
    # Fibre
    "FibreType", "FibreStatus", "AutonomyLevel", "FibreConfig",
    "FibreTask", "FibreResult", "FibreLifespan", "Fibre",
    # Coherence
    "CoherenceLayer", "CoherenceMeasurement", "CoherenceGap",
    "LayerThresholds",
    # Strategy
    "StandingOrder", "Insight", "StrategyProposal", "ProposalStatus",
    "ProposalRisk", "CoherenceBriefing", "StrategyForesightAlert",
    "SwarmOversightEntry", "ApprovalDecisionAudit", "FibreBehavioralBaseline",
    "LegacyVaultConsent",
    # Mesh
    "MeshMessageType", "MeshPriority", "MeshMessage", "MeshConvergenceAlert",
    "MeshHealth",
    # Notification
    "NotificationChannel", "ApprovalNotification", "ApprovalResponse",
    # ZEFCP (Layer 1)
    "FragmentMode", "FragmentType", "MicroFragment", "FibreObservation",
    "ObservationAssembly", "ADStructure", "BLEAdvertisingPDU",
    "BLETransportConfig", "TransportMetrics", "NFCProvisioningPayload",
    # Quakete (Layer 8)
    "QuaketeMode", "RingState", "FibreTrailEmission", "QuaketeIon",
    "RingCord", "CosmicRelationalRing", "QuaketeAllocation",
    "ReconnectionPlan", "FragmentAcceleration", "ParticleBeam",
    "QuaketeBoost", "QuaketeTransferResult", "Memorial", "RampUpPlan",
    # Swarm
    "FibreSummary", "SwarmState", "ConvergenceAlert", "SwarmDirective",
    # Foresight
    "ForesightStreamType", "ForesightScale", "AlertSeverity",
    "ForesightStream", "ForesightAlert", "PatternActivation",
    # Solutions (Platinum)
    "RiskTier", "MemberHealthView", "SilentAlert", "EmotionalWeatherMap",
    "PredictiveCoachBriefing", "CommunityEarlyWarning",
    "SolutionAutonomyLevel", "AutonomyAuditTrail", "TransgenerationalPattern",
    "CoupleResonanceMonitor", "NotificationTier", "LiveSessionNotification",
    # Onboarding (Platinum)
    "OnboardingStage", "OnboardingInitiation", "WelcomeConversation",
    "NevedalColdStart", "CoachMatchResult",
    # Me-2-Me (Platinum)
    "ConsentLevel", "ConsentRecord", "IdentityCrystal", "Me2MeAvatarCore",
    "AvatarStatus", "GrowthLayer", "FamilyFabric", "MigrationPhase",
    "MigrationRecord", "ImprintEntry", "SovereignLegacyTrust", "TrustBeneficiary",
    # Billing Metered (Platinum)
    "BillingTier", "UsageType", "MeteredBillingLayer", "LegacyVaultBilling",
    "CostThresholdConfig",
    # Governance (Platinum)
    "BoundaryType", "ScopeOfPractice", "ReportingTrigger",
    "MandatoryReportingProtocol", "ClinicalRecordType", "ClinicalRecord",
    # Portability (Platinum)
    "SLFSection", "SLFExportRequest", "SLFManifest", "SLFImportRequest",
    # Hive Defense (Phase 8)
    "GateDecision", "CuriosityLevel", "DefconLevel", "ContentVerdict",
    "PenetratorPhase", "GhostType", "HelixVerdict", "ProjectionStatus",
    "HeartbeatPulse", "ThreeCordVerification",
    "MirrorNamespace", "MirrorSignal",
    "CuriosityEvent", "MirrorReflection",
    "DefconState", "DriftScore", "ContentSentinelResult",
    "PenetratorReport", "GhostMission",
    "AttackerProfile", "ForensicRecord",
    "EphemeralCertificate", "HelixState", "InvertedSpace",
    "ProjectedHelixDeployment", "RecursiveLearningState",
    "QuarantineRecord", "BehavioralSnapshot",
    "ConservationLedgerEntry", "CanaryCredential", "TripwireActivation",
    "HIVE_EVENT_TOPICS",
]
