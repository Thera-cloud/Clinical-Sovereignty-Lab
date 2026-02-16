"""
SOVEREIGN SWARM — Background Workers
Periodic async tasks for swarm maintenance and monitoring.
"""

from app.workers.ble_assembly_worker import BLEAssemblyWorker
from app.workers.coherence_worker import CoherenceWorker
from app.workers.convergence_worker import ConvergenceWorker
from app.workers.fibre_worker import FibreLifecycleWorker
from app.workers.foresight_worker import ForesightWorker
from app.workers.pattern_worker import PatternWorker
from app.workers.ring_worker import RingWorker
from app.workers.trail_worker import TrailWorker

# Platinum Finish Line Workers
from app.workers.onboarding_worker import OnboardingWorker
from app.workers.silent_detector_worker import SilentDetectorWorker
from app.workers.autonomy_review_worker import AutonomyReviewWorker
from app.workers.weather_worker import WeatherWorker
from app.workers.briefing_worker import BriefingWorker
from app.workers.community_warning_worker import CommunityWarningWorker
from app.workers.night_school_worker import NightSchoolWorker
from app.workers.billing_worker import BillingWorker
from app.workers.imprint_accumulator_worker import ImprintAccumulatorWorker
from app.workers.crystal_synthesizer_worker import CrystalSynthesizerWorker
from app.workers.growth_engine_worker import GrowthEngineWorker
from app.workers.migration_worker import MigrationWorker
from app.workers.vault_integrity_worker import VaultIntegrityWorker
from app.workers.ingestion_safety_worker import IngestionSafetyWorker

# Hive Defense Protocol (Phase 8A)
from app.workers.heartbeat_monitor_worker import HeartbeatMonitorWorker
from app.workers.curiosity_scanner_worker import CuriosityScannerWorker
from app.workers.trap_monitor_worker import TrapMonitorWorker

# Hive Defense Protocol (Phase 8B)
from app.workers.cds_computation_worker import CdsComputationWorker
from app.workers.defcon_evaluator_worker import DefconEvaluatorWorker
from app.workers.canary_monitor_worker import CanaryMonitorWorker
from app.workers.backup_audit_worker import BackupAuditWorker

__all__ = [
    # Core Swarm Workers
    "BLEAssemblyWorker",
    "CoherenceWorker",
    "ConvergenceWorker",
    "FibreLifecycleWorker",
    "ForesightWorker",
    "PatternWorker",
    "RingWorker",
    "TrailWorker",
    # Platinum Finish Line Workers
    "OnboardingWorker",
    "SilentDetectorWorker",
    "AutonomyReviewWorker",
    "WeatherWorker",
    "BriefingWorker",
    "CommunityWarningWorker",
    "NightSchoolWorker",
    "BillingWorker",
    "ImprintAccumulatorWorker",
    "CrystalSynthesizerWorker",
    "GrowthEngineWorker",
    "MigrationWorker",
    "VaultIntegrityWorker",
    "IngestionSafetyWorker",
    # Hive Defense Protocol (Phase 8A)
    "HeartbeatMonitorWorker",
    "CuriosityScannerWorker",
    "TrapMonitorWorker",
    # Hive Defense Protocol (Phase 8B)
    "CdsComputationWorker",
    "DefconEvaluatorWorker",
    "CanaryMonitorWorker",
    "BackupAuditWorker",
]
