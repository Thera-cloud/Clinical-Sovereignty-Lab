"""
LITTLE NATE — Configuration Management
Loads all settings from environment variables
"""

import os
from typing import Optional
from urllib.parse import quote_plus
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment."""
    
    # -------------------------------------------------------------------------
    # Network
    # -------------------------------------------------------------------------
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8000
    WEBSOCKET_PORT: int = 8765
    ADMIN_PORT: int = 3000
    BASE_URL: str = "http://localhost:8000"
    WS_URL: str = "ws://localhost:8765"
    DOMAIN: Optional[str] = None
    PUBLIC_BASE_URL: str = ""  # Public-facing API URL (e.g. https://api.sovereignsanctuary.net) for OAuth redirects

    @property
    def public_api_url(self) -> str:
        """Resolved public API base URL. Falls back to the canonical production URL
        when PUBLIC_BASE_URL is empty and ENVIRONMENT is production — prevents
        OAuth redirect_uri from resolving to http://localhost:8000 inside Docker."""
        if self.PUBLIC_BASE_URL:
            return self.PUBLIC_BASE_URL.rstrip("/")
        if self.ENVIRONMENT == "production":
            return "https://api.sovereignsanctuary.net"
        return ""
    
    # -------------------------------------------------------------------------
    # Azure OpenAI
    # -------------------------------------------------------------------------
    AZURE_API_KEY: str
    AZURE_OPENAI_ENDPOINT: str
    AZURE_OPENAI_DEPLOYMENT: str = "gpt-4o-realtime-preview"
    AZURE_OPENAI_CHAT_DEPLOYMENT: str = "gpt-4o"       # For insight engine (chat completions, not realtime WS)
    AZURE_OPENAI_MINI_TTS_DEPLOYMENT: str = "gpt-4o-mini-tts"  # Cost-effective TTS + text generation
    
    @property
    def AZURE_REALTIME_URL(self) -> str:
        """Construct Azure OpenAI Realtime WebSocket URL."""
        # Clean endpoint - remove https://, wss://, and trailing slashes
        endpoint = self.AZURE_OPENAI_ENDPOINT.replace("https://", "").replace("wss://", "").replace("/", "")
        # Handle both standard OpenAI endpoints and Azure AI services endpoints
        if "services.ai.azure.com" in endpoint:
            # Azure AI Services format
            return f"wss://{endpoint}/openai/realtime?api-version=2024-10-01-preview&deployment={self.AZURE_OPENAI_DEPLOYMENT}"
        else:
            # Standard Azure OpenAI format
            return f"wss://{endpoint}/openai/realtime?api-version=2024-10-01-preview&deployment={self.AZURE_OPENAI_DEPLOYMENT}"
    
    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "little_nate"
    POSTGRES_USER: str = "nate_admin"
    POSTGRES_PASSWORD: str
    DATABASE_URL: Optional[str] = None
    
    @property
    def database_url(self) -> str:
        """Get database URL (explicit or constructed)."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        # URL-encode the password to handle special chars like & in passwords
        encoded_password = quote_plus(self.POSTGRES_PASSWORD)
        return f"postgresql://{self.POSTGRES_USER}:{encoded_password}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    # -------------------------------------------------------------------------
    # Redis
    # -------------------------------------------------------------------------
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_URL: Optional[str] = None
    
    @property
    def redis_url(self) -> str:
        """Get Redis URL."""
        if self.REDIS_URL:
            return self.REDIS_URL
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}"
    
    # -------------------------------------------------------------------------
    # Stripe
    # -------------------------------------------------------------------------
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_STANDARD: str = ""
    STRIPE_PRICE_TOP_TIER: str = ""
    STRIPE_PRICE_FAMILY_MEMBER: str = ""
    STRIPE_PRICE_COACHING_SINGLE: str = ""
    STRIPE_PRICE_COACHING_4PACK: str = ""
    STRIPE_PRICE_COACHING_8PACK: str = ""
    STRIPE_PRICE_TOKEN_LIGHT: str = ""
    STRIPE_PRICE_TOKEN_STANDARD: str = ""
    STRIPE_PRICE_TOKEN_POWER: str = ""
    STRIPE_PRICE_TOKEN_ULTIMATE: str = ""
    STRIPE_PRICE_TOKEN_SHARE_FEE: str = ""
    STRIPE_PRICE_DOJO_THERAPIST: str = ""
    STRIPE_PRICE_DOJO_PROJECT_PM: str = ""
    STRIPE_PRICE_DOJO_BUSINESS: str = ""
    STRIPE_PRICE_DOJO_CNC: str = ""
    STRIPE_PRICE_DOJO_MCAT: str = ""
    STRIPE_PRICE_DOJO_TEACHER: str = ""
    STRIPE_PRICE_DOJO_JUDGE: str = ""
    STRIPE_PRICE_DOJO_COACH_NATE: str = ""
    
    # -------------------------------------------------------------------------
    # Email
    # -------------------------------------------------------------------------
    SMTP_HOST: str = "smtp.sendgrid.net"
    SMTP_PORT: int = 587
    SMTP_USER: str = "apikey"
    SMTP_PASSWORD: str = ""
    FROM_EMAIL: str = "sanctuary@littlenate.ai"
    FROM_NAME: str = "Sovereign Sanctuary"
    
    # SendGrid API (for drip campaign dynamic templates)
    SENDGRID_API_KEY: str = ""
    SENDGRID_DRIP_TEMPLATE_DAY1: str = ""
    SENDGRID_DRIP_TEMPLATE_DAY2: str = ""
    SENDGRID_DRIP_TEMPLATE_DAY3: str = ""
    SENDGRID_DRIP_TEMPLATE_DAY4: str = ""
    SENDGRID_DRIP_TEMPLATE_DAY5: str = ""
    SENDGRID_INSIGHT_TEMPLATE: str = ""
    SENDGRID_ASSESSMENT_TEMPLATE: str = ""
    
    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24
    ADMIN_USERNAME: str  # Required — no default (must be set via ADMIN_USERNAME env var)
    ADMIN_PASSWORD: str  # Required — no default (must be set via ADMIN_PASSWORD env var)
    
    # -------------------------------------------------------------------------
    # Security
    # -------------------------------------------------------------------------
    CORS_ORIGINS: str = "http://localhost:3000,https://app.sovereignsanctuary.net,https://coach.sovereignsanctuary.net,https://command.sovereignsanctuary.net"
    RATE_LIMIT_PER_MINUTE: int = 60
    
    # Admin Contact Shield — protected PII (comma-separated, loaded from env)
    ADMIN_PROTECTED_EMAILS: str = ""
    ADMIN_PROTECTED_PHONES: str = ""
    ADMIN_ALERT_PHONE: str = ""
    ADMIN_ALERT_EMAILS: str = ""
    
    # -------------------------------------------------------------------------
    # Secure Internet Search (DOJO)
    # -------------------------------------------------------------------------
    BING_SEARCH_API_KEY: str = ""
    TOTP_ENCRYPTION_KEY: str = ""
    
    # -------------------------------------------------------------------------
    # Drip Campaign
    # -------------------------------------------------------------------------
    DRIP_DEFAULT_DELAY_HOURS: int = 24
    DRIP_SCHEDULER_CHECK_INTERVAL_MINUTES: int = 5
    DRIP_SMS_FALLBACK_DELAY_HOURS: int = 4
    GOLDEN_TICKET_DEFAULT_WINDOW_DAYS: int = 7
    GOLDEN_TICKET_REMINDER_DAY_3: bool = True
    GOLDEN_TICKET_REMINDER_DAY_6: bool = True
    
    # -------------------------------------------------------------------------
    # Feature Flags
    # -------------------------------------------------------------------------
    ENABLE_NEVEDAL: bool = True
    ENABLE_NIGHT_SCHOOL: bool = True
    ENABLE_CRISIS_DETECTION: bool = True
    ENABLE_VOICE_MODE: bool = True
    ENABLE_COACHING: bool = False
    ENABLE_STRIPE: bool = False
    ENABLE_ZOOM: bool = False
    # Workspace pairing + voice campaign (plan v1.5.2) — default OFF until Queens
    ENABLE_WS_OAUTH: bool = False
    ENABLE_WS_CALENDAR_SYNC: bool = False
    ENABLE_WS_GMAIL_DRAFTS: bool = False
    ENABLE_WS_DRIVE_DELIVERY: bool = False
    ENABLE_VOICE_CAMPAIGN: bool = False
    ENABLE_COACH_VIDEO_INGEST: bool = False
    ENABLE_CAMPAIGN_NUDGES: bool = False
    ENABLE_AUDIO_BRIEFS: bool = False
    ENABLE_COACH_LINKEDIN: bool = False
    ENABLE_STUDIO_WEBHOOKS: bool = False
    ENABLE_COACH_NEWSLETTER: bool = False
    ENABLE_COACH_TASKS: bool = False
    ENABLE_SUPERVISION_VIEW: bool = False
    ENABLE_PRACTICE_LIBRARIES: bool = False
    ENABLE_CLINICAL_ERASURE: bool = False
    ENABLE_CRISIS_ESCALATION: bool = False
    CLIENT_ENVELOPE_KEK: str = ""
    GOOGLE_WS_CLIENT_ID: str = ""
    GOOGLE_WS_CLIENT_SECRET: str = ""
    GOOGLE_WS_TEST_USERS: str = ""
    ENABLE_DRIP_CAMPAIGN: bool = True
    ENABLE_SKYEYE: bool = True
    ENABLE_SKYEYE_SESSIONS: bool = True  # Auto session engine — autonomous posting enabled
    ENABLE_LN_OBSERVER: bool = False  # QUANTUM-CRYSTAL-ARCH — Coach LN-Observer
    ENABLE_SOVEREIGN_SWARM: bool = True   # Sovereign Swarm Intelligence Framework
    ENABLE_NATE_NUDGE: bool = True        # Nate the Nudge proactive notification system
    # QUANTUM-CRYSTAL-ARCH: progressive rollout flags default OFF
    ENABLE_QUANTUM_CRYSTAL_ORCHESTRATOR: bool = False
    ENABLE_VOICE_TRANSCRIPT_CRYSTALLIZATION: bool = False
    ENABLE_TIME_CRYSTAL_FORGE: bool = False
    # QUANTUM-CRYSTAL-ARCH: 4h Vectorize rebuild (~209k queries/cycle). Paused — recall uses crystal_recall_bridge.
    ENABLE_CRYSTAL_GRAPH: bool = False
    # Agentic Roadmap Phases 0–5 — all default OFF until adversarial walk + staging flip
    ENABLE_PROACTIVE_TOUCH_POLICY: bool = False
    ENABLE_PROACTIVE_COMMITMENTS: bool = False
    ENABLE_NATE_TOOL_EXECUTOR: bool = False
    ENABLE_THERAPEUTIC_PLANS: bool = False
    ENABLE_SELF_MONITOR_AGENT: bool = False
    ENABLE_SELF_MONITOR_COACH_ALERT: bool = False
    ENABLE_SELF_MONITOR_TOUCH: bool = False
    ENABLE_SYMBOLIC_EXTRACTION: bool = False
    ENABLE_SYMBOLIC_VERIFIER: bool = False
    ENABLE_FORWARD_REASONING: bool = False

    # User Registry backend
    USE_POSTGRES_REGISTRY: bool = True    # When True, bridge stores users in PostgreSQL (recommended)
    
    # Sovereign Swarm secrets
    SWARM_SECRET: Optional[str] = None    # HMAC secret for ZEFCP fragments (auto-derived from master key if unset)
    AZURE_STORAGE_CONNECTION_STRING: Optional[str] = None  # Azure Blob Storage for warm/cold memory tiering
    
    # -------------------------------------------------------------------------
    # Nate the Nudge — Timing & Thresholds
    # -------------------------------------------------------------------------
    NUDGE_MOOD_CHECK_INTERVAL_HOURS: int = 24       # Hours between mood-check nudges
    NUDGE_SESSION_PREP_LOOKAHEAD_HOURS: int = 3     # How far ahead to look for sessions
    NUDGE_SCHEDULER_INTERVAL_MINUTES: int = 30      # How often the scheduler runs nudge checks

    # -------------------------------------------------------------------------
    # Sovereign Swarm Identity Chain (Ed25519 master key PEM)
    # Generate with: python3 -c "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; from cryptography.hazmat.primitives import serialization; k=Ed25519PrivateKey.generate(); print(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())"
    # -------------------------------------------------------------------------
    SOVEREIGN_MIND_MASTER_KEY: str = ""

    # -------------------------------------------------------------------------
    # SkyEye — Token Encryption
    # Generate with: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # -------------------------------------------------------------------------
    SKYEYE_TOKEN_ENCRYPTION_KEY: str = ""

    # When False, pauses SendGrid + SMS for social token issues: “Token Renewal
    # Required” (TokenRenewalAgent) and proactive expiry warnings (TokenLifecycle
    # Predictor). Activity still logs to skyeye_activity. Default True.
    SKYEYE_SOCIAL_TOKEN_ALERT_EMAILS_ENABLED: bool = True

    # Comma-separated skyeye_platform_tokens.platform keys (e.g. x,linkedin).
    # Pauses renewal SMS/email and audit-gap "missed notification" alerts only for those platforms.
    SKYEYE_TOKEN_ALERT_PAUSED_PLATFORMS: str = ""

    # -------------------------------------------------------------------------
    # SkyEye — Social Media Platform Credentials (all optional)
    # -------------------------------------------------------------------------
    # TikTok (Content Posting API)
    TIKTOK_CLIENT_KEY: str = ""
    TIKTOK_CLIENT_SECRET: str = ""

    # Instagram / Facebook (Meta Graph API — shared credentials)
    INSTAGRAM_APP_ID: str = ""
    INSTAGRAM_APP_SECRET: str = ""
    FACEBOOK_APP_ID: str = ""
    FACEBOOK_APP_SECRET: str = ""

    # YouTube (Data API v3)
    YOUTUBE_CLIENT_ID: str = ""
    YOUTUBE_CLIENT_SECRET: str = ""
    YOUTUBE_API_KEY: str = ""

    # Reddit
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USERNAME: str = ""
    REDDIT_PASSWORD: str = ""

    # LinkedIn — personal profile posting (Share on LinkedIn)
    LINKEDIN_CLIENT_ID: str = ""
    LINKEDIN_CLIENT_SECRET: str = ""
    # LinkedIn — company page posting (Marketing Developer Platform / w_organization_social)
    LINKEDIN_COMPANY_CLIENT_ID: str = ""
    LINKEDIN_COMPANY_CLIENT_SECRET: str = ""
    # LinkedIn — Community Management API (comments/reactions)
    LINKEDIN_COMMUNITY_CLIENT_ID: str = ""
    LINKEDIN_COMMUNITY_CLIENT_SECRET: str = ""

    # X (Twitter) — OAuth 2.0 with PKCE
    X_CLIENT_ID: str = ""
    X_CLIENT_SECRET: str = ""

    # Pinterest
    PINTEREST_APP_ID: str = ""
    PINTEREST_APP_SECRET: str = ""

    # -------------------------------------------------------------------------
    # Zoom (Server-to-Server OAuth + Webhooks)
    # -------------------------------------------------------------------------
    # Create a Server-to-Server OAuth app in Zoom Marketplace (recommended for automation).
    ZOOM_ACCOUNT_ID: str = ""
    ZOOM_CLIENT_ID: str = ""
    ZOOM_CLIENT_SECRET: str = ""
    # Zoom "Secret Token" for webhook signature verification (x-zm-signature)
    ZOOM_WEBHOOK_SECRET_TOKEN: str = ""
    # Which Zoom user to create meetings under ("me" or an email/userId)
    ZOOM_HOST_USER: str = "me"
    # Default meeting timezone (Zoom expects IANA TZ)
    ZOOM_DEFAULT_TIMEZONE: str = "America/Los_Angeles"
    # Default meeting settings
    ZOOM_DEFAULT_WAITING_ROOM: bool = True
    ZOOM_DEFAULT_JOIN_BEFORE_HOST: bool = False
    ZOOM_DEFAULT_AUTO_RECORDING: str = "cloud"  # none|cloud|local - auto records to Zoom cloud
    
    # -------------------------------------------------------------------------
    # Paths
    # -------------------------------------------------------------------------
    DATA_DIR: str = "/app/data"           # Root data directory for session/registry files
    WORKBOOKS_DIR: str = "/app/workbooks" # Workbook templates and exports

    # -------------------------------------------------------------------------
    # Application URLs
    # -------------------------------------------------------------------------
    APP_URL: str = "https://app.sovereignsanctuary.net"  # Public-facing app URL for email links and notifications

    # -------------------------------------------------------------------------
    # Environment
    # -------------------------------------------------------------------------
    ENVIRONMENT: str = "production"  # Safe default — override to "development" in .env for local dev
    DEBUG: bool = False  # Safe default — override to True in .env for local dev
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Singleton instance
settings = get_settings()
