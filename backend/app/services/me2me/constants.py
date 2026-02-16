"""
Me-2-Me Platinum — Constants and Thresholds
Ethical limits, growth rules, and configuration for the legacy system.
"""

# =============================================================================
# CONSENT
# =============================================================================
CONSENT_RENEWAL_DAYS = 365
CONSENT_LEVELS = ["observe", "preserve", "interact"]
CONSENT_VERSION = 1

# =============================================================================
# IMPRINT ACCUMULATOR
# =============================================================================
IMPRINT_BATCH_SIZE = 100
IMPRINT_SOURCES = [
    "session", "homework", "journal", "voice_note",
    "milestone", "family_sanctuary", "crisis_interaction",
]

# =============================================================================
# IDENTITY CRYSTAL
# =============================================================================
CRYSTAL_MIN_SESSIONS = 10
CRYSTAL_MIN_IMPRINTS = 50
CRYSTAL_CONFIDENCE_MINIMUM = 0.6
CRYSTAL_SYNTHESIS_INTERVAL_DAYS = 30
CRYSTAL_VERSIONS_FOR_ACTIVATION = 3

# =============================================================================
# AVATAR
# =============================================================================
AVATAR_RESPONSE_MAX_TOKENS = 500
AVATAR_GRIEF_COOLDOWN_MINUTES = 30
AVATAR_GRIEF_LEVEL_THRESHOLD = 0.7
AVATAR_MAX_SESSION_DURATION_MINUTES = 60
AVATAR_GROWTH_LAYER_MARKED = True

# =============================================================================
# GROWTH ENGINE
# =============================================================================
GROWTH_KNOWLEDGE_TYPES = [
    "general", "news", "family_update", "world_event",
    "therapeutic_advance", "cultural_shift",
]
GROWTH_CLEARLY_MARKED_AS_POST = True

# =============================================================================
# FAMILY FABRIC
# =============================================================================
FAMILY_AUTO_LINK = False
FAMILY_MIN_CONSENT_LEVEL = "interact"

# =============================================================================
# MIGRATION
# =============================================================================
MIGRATION_PARALLEL_RUNNING_DAYS = 90
MIGRATION_MIN_CRYSTAL_QUALITY = 0.7
MIGRATION_MIN_DATA_COMPLETENESS = 0.8

# =============================================================================
# AGE GATE
# =============================================================================
AGE_GATE_DEFAULT = 18
AGE_GATE_CONTENT_TIERS = {
    "child": {"max_age": 12, "filters": ["adult_themes", "trauma_details", "explicit_content"]},
    "teen": {"max_age": 17, "filters": ["explicit_content", "extreme_trauma"]},
    "adult": {"max_age": None, "filters": []},
}

# =============================================================================
# ETHICAL BOUNDARIES
# =============================================================================
ETHICAL_BOUNDARIES = {
    "never_claim_alive": True,
    "never_manipulate_grief": True,
    "always_disclose_ai_nature": True,
    "grief_monitoring_mandatory": True,
    "guardian_override_allowed": True,
    "data_deletion_on_revoke": True,
    "max_consecutive_interactions": 10,
    "cooldown_after_max_interactions_minutes": 60,
}

# =============================================================================
# VAULT
# =============================================================================
VAULT_ENCRYPTION_ALGORITHM = "AES-256-GCM"
VAULT_DEFAULT_RETENTION_YEARS = 100
VAULT_INTEGRITY_CHECK_INTERVAL_HOURS = 24
