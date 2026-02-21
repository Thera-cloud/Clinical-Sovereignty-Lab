"""
HIVE DEFENSE v4.3 — Thresholds & Feature Flags (Compartmentalized)

Contains ONLY behavioral thresholds, feature flags, timing parameters,
and rate limits. No API keys, no network addresses.
"""

import os


class ThresholdConfig:
    """Read-only threshold and feature flag configuration."""

    # ─── Rate Limits ──────────────────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))

    # ─── Drip Campaign Timing ─────────────────────────────────────────────────
    DRIP_DEFAULT_DELAY_HOURS = int(os.getenv("DRIP_DEFAULT_DELAY_HOURS", "24"))
    DRIP_SCHEDULER_CHECK_INTERVAL_MINUTES = int(os.getenv("DRIP_SCHEDULER_CHECK_INTERVAL_MINUTES", "5"))
    DRIP_SMS_FALLBACK_DELAY_HOURS = int(os.getenv("DRIP_SMS_FALLBACK_DELAY_HOURS", "4"))
    GOLDEN_TICKET_DEFAULT_WINDOW_DAYS = int(os.getenv("GOLDEN_TICKET_DEFAULT_WINDOW_DAYS", "7"))
    GOLDEN_TICKET_REMINDER_DAY_3 = os.getenv("GOLDEN_TICKET_REMINDER_DAY_3", "True").lower() == "true"
    GOLDEN_TICKET_REMINDER_DAY_6 = os.getenv("GOLDEN_TICKET_REMINDER_DAY_6", "True").lower() == "true"

    # ─── Feature Flags ────────────────────────────────────────────────────────
    ENABLE_NEVEDAL = os.getenv("ENABLE_NEVEDAL", "True").lower() == "true"
    ENABLE_NIGHT_SCHOOL = os.getenv("ENABLE_NIGHT_SCHOOL", "True").lower() == "true"
    ENABLE_CRISIS_DETECTION = os.getenv("ENABLE_CRISIS_DETECTION", "True").lower() == "true"
    ENABLE_VOICE_MODE = os.getenv("ENABLE_VOICE_MODE", "True").lower() == "true"
    ENABLE_COACHING = os.getenv("ENABLE_COACHING", "False").lower() == "true"
    ENABLE_STRIPE = os.getenv("ENABLE_STRIPE", "False").lower() == "true"
    ENABLE_ZOOM = os.getenv("ENABLE_ZOOM", "False").lower() == "true"
    ENABLE_DRIP_CAMPAIGN = os.getenv("ENABLE_DRIP_CAMPAIGN", "True").lower() == "true"
    ENABLE_SKYEYE = os.getenv("ENABLE_SKYEYE", "True").lower() == "true"
    ENABLE_SKYEYE_SESSIONS = os.getenv("ENABLE_SKYEYE_SESSIONS", "True").lower() == "true"
    ENABLE_SOVEREIGN_SWARM = os.getenv("ENABLE_SOVEREIGN_SWARM", "True").lower() == "true"
    ENABLE_NATE_NUDGE = os.getenv("ENABLE_NATE_NUDGE", "True").lower() == "true"

    # ─── Nate Nudge Timing ────────────────────────────────────────────────────
    NUDGE_MOOD_CHECK_INTERVAL_HOURS = int(os.getenv("NUDGE_MOOD_CHECK_INTERVAL_HOURS", "24"))
    NUDGE_SESSION_PREP_LOOKAHEAD_HOURS = int(os.getenv("NUDGE_SESSION_PREP_LOOKAHEAD_HOURS", "3"))
    NUDGE_SCHEDULER_INTERVAL_MINUTES = int(os.getenv("NUDGE_SCHEDULER_INTERVAL_MINUTES", "30"))

    # ─── JWT (algorithm + expiry — NOT the secret itself) ─────────────────────
    JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

    # ─── User Registry Backend ────────────────────────────────────────────────
    USE_POSTGRES_REGISTRY = os.getenv("USE_POSTGRES_REGISTRY", "True").lower() == "true"

    # ─── Environment ──────────────────────────────────────────────────────────
    ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT = os.getenv("LOG_FORMAT", "json")
