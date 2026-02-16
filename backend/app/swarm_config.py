"""
Sovereign Swarm — Centralized Configuration
Externalizes all hardcoded thresholds, weights, and parameters.
Override via environment variables prefixed with SWARM_.
"""

from pydantic_settings import BaseSettings


class SwarmConfig(BaseSettings):
    """Centralized swarm configuration. All values can be overridden via env vars."""

    # Coherence Engine — Layer Weights
    COHERENCE_INDIVIDUAL_WEIGHTS: dict = {
        "cee_aggregate": 0.40, "cee_ratio": 0.15, "quiz_signal": 0.20, "behavioral": 0.25
    }
    COHERENCE_FAMILY_WEIGHTS: dict = {
        "mean_score": 0.35, "resonance": 0.30, "transmission": 0.20, "efficacy": 0.15
    }
    COHERENCE_COMMUNITY_WEIGHTS: dict = {"mean_score": 0.60, "cohesion": 0.40}
    COHERENCE_GLOBAL_WEIGHTS: dict = {
        "individual": 0.20, "family": 0.25, "community": 0.30, "cultural": 0.25
    }

    # Fibre Manager — Autonomy Thresholds
    AUTONOMY_MIN_HOURS_OBSERVATION: int = 48
    AUTONOMY_MIN_HOURS_RESTRICTED: int = 168
    ALIGNMENT_THRESHOLD_ETHICAL: float = 0.8
    ALIGNMENT_THRESHOLD_STRATEGIC: float = 0.7
    ALIGNMENT_THRESHOLD_STATISTICAL: float = 0.7

    # Wisdom Mesh
    MESH_CONVERGENCE_WINDOW_SECONDS: int = 300
    MESH_MAX_MESSAGES_PER_MINUTE: int = 1000
    MESH_CONVERGENCE_MIN_SCORE: float = 0.75
    MESH_BATCH_WINDOW_SECONDS: float = 10.0  # Temporal batching for low-priority messages (§5.4)

    # Sovereign Immunity
    IMMUNITY_MAX_MESSAGES_PER_MINUTE: int = 60
    IMMUNITY_MAX_UNIQUE_TOPICS_PER_HOUR: int = 50
    IMMUNITY_ANOMALY_SCORE_THRESHOLD: float = 0.7
    IMMUNITY_MAX_TOKEN_USAGE_ALERT: int = 50000

    # Foresight Engine — Stream Weights
    FORESIGHT_STREAM_WEIGHTS: dict = {
        "internal_therapeutic": 0.35, "external_cultural": 0.25,
        "historical_pattern": 0.25, "contextual": 0.15
    }
    FORESIGHT_DECLINE_THRESHOLD: float = 0.1
    FORESIGHT_IMPROVEMENT_THRESHOLD: float = 0.1
    FORESIGHT_MIN_DATA_DAYS: int = 7

    # Pattern Engine
    PATTERN_MIN_SESSIONS_PER_MEMBER: int = 3
    PATTERN_MIN_FAMILY_MEMBERS: int = 2
    PATTERN_TRIGGER_CORRELATION_WINDOW: int = 172800
    PATTERN_STRONG_CORRELATION_THRESHOLD: float = 0.5
    PATTERN_MODERATE_CORRELATION_THRESHOLD: float = 0.2

    # Token Budgets (per hour)
    DEFAULT_TOKEN_BUDGET_PER_HOUR: int = 10000
    TOKEN_BUDGET_RESET_SECONDS: int = 3600

    # Base Fibre — Alignment Update Weights
    ALIGNMENT_DECAY_FACTOR: float = 0.9
    ALIGNMENT_UPDATE_FACTOR: float = 0.1

    # Scheduler Intervals
    FORESIGHT_RUN_INTERVAL_HOURS: int = 6
    COHERENCE_PULSE_INTERVAL_HOURS: int = 4
    APPROVAL_AUTO_EXEC_INTERVAL_MINUTES: int = 10

    class Config:
        env_prefix = "SWARM_"


swarm_settings = SwarmConfig()
