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
    SERVER_HOST: str = "10.0.0.81"
    SERVER_PORT: int = 8000
    WEBSOCKET_PORT: int = 8765
    ADMIN_PORT: int = 3000
    BASE_URL: str = "http://10.0.0.81:8000"
    WS_URL: str = "ws://10.0.0.81:8765"
    DOMAIN: Optional[str] = None
    
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
    POSTGRES_HOST: str = "10.0.0.81"
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
    REDIS_HOST: str = "10.0.0.81"
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
    ADMIN_USERNAME: str = "sovereign"
    ADMIN_PASSWORD: str = "SovereignDev2026!"
    
    # -------------------------------------------------------------------------
    # Security
    # -------------------------------------------------------------------------
    CORS_ORIGINS: str = "http://10.0.0.81:3000,http://localhost:3000,https://app.sovereignsanctuary.net,null"
    RATE_LIMIT_PER_MINUTE: int = 60
    
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
    ENABLE_DRIP_CAMPAIGN: bool = True
    ENABLE_SKYEYE: bool = True
    ENABLE_SKYEYE_SESSIONS: bool = False  # Auto session engine (set True when platform APIs connected)

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

    # LinkedIn
    LINKEDIN_CLIENT_ID: str = ""
    LINKEDIN_CLIENT_SECRET: str = ""

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
    # Environment
    # -------------------------------------------------------------------------
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Singleton instance
settings = get_settings()
