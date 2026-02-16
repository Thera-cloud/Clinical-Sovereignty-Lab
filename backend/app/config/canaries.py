"""
HIVE DEFENSE v4.3 — Canary Configuration (API Keys & Secrets)
CRITICAL SECURITY MODULE — Compartmentalized

Contains ALL API keys, secrets, and credentials. This is the ONLY module
that should be imported by services needing upstream provider authentication.

Access to this module should be logged and monitored by the
Upstream Canary Network.

Security notes:
- NEVER import this module from client-facing code paths
- NEVER log the contents of any attribute in this module
- NEVER serialize this module's attributes to JSON/responses
- This module should only be imported in service initialization code
"""

import os
from typing import Optional


class CanaryConfig:
    """Read-only API key and secret configuration. Handle with extreme care."""

    # ─── Azure OpenAI ─────────────────────────────────────────────────────────
    AZURE_API_KEY: str = os.getenv("AZURE_API_KEY", "")
    AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    AZURE_OPENAI_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-realtime-preview")
    AZURE_OPENAI_CHAT_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")
    AZURE_OPENAI_MINI_TTS_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_MINI_TTS_DEPLOYMENT", "gpt-4o-mini-tts")

    # ─── Stripe ───────────────────────────────────────────────────────────────
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY: str = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_PRICE_STANDARD: str = os.getenv("STRIPE_PRICE_STANDARD", "")
    STRIPE_PRICE_TOP_TIER: str = os.getenv("STRIPE_PRICE_TOP_TIER", "")
    STRIPE_PRICE_FAMILY_MEMBER: str = os.getenv("STRIPE_PRICE_FAMILY_MEMBER", "")
    STRIPE_PRICE_COACHING_SINGLE: str = os.getenv("STRIPE_PRICE_COACHING_SINGLE", "")
    STRIPE_PRICE_COACHING_4PACK: str = os.getenv("STRIPE_PRICE_COACHING_4PACK", "")
    STRIPE_PRICE_COACHING_8PACK: str = os.getenv("STRIPE_PRICE_COACHING_8PACK", "")

    # ─── SendGrid / Email ─────────────────────────────────────────────────────
    SMTP_USER: str = os.getenv("SMTP_USER", "apikey")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SENDGRID_API_KEY: str = os.getenv("SENDGRID_API_KEY", "")
    FROM_EMAIL: str = os.getenv("FROM_EMAIL", "sanctuary@littlenate.ai")
    FROM_NAME: str = os.getenv("FROM_NAME", "Sovereign Sanctuary")

    # SendGrid drip campaign template IDs
    SENDGRID_DRIP_TEMPLATE_DAY1: str = os.getenv("SENDGRID_DRIP_TEMPLATE_DAY1", "")
    SENDGRID_DRIP_TEMPLATE_DAY2: str = os.getenv("SENDGRID_DRIP_TEMPLATE_DAY2", "")
    SENDGRID_DRIP_TEMPLATE_DAY3: str = os.getenv("SENDGRID_DRIP_TEMPLATE_DAY3", "")
    SENDGRID_DRIP_TEMPLATE_DAY4: str = os.getenv("SENDGRID_DRIP_TEMPLATE_DAY4", "")
    SENDGRID_DRIP_TEMPLATE_DAY5: str = os.getenv("SENDGRID_DRIP_TEMPLATE_DAY5", "")
    SENDGRID_INSIGHT_TEMPLATE: str = os.getenv("SENDGRID_INSIGHT_TEMPLATE", "")
    SENDGRID_ASSESSMENT_TEMPLATE: str = os.getenv("SENDGRID_ASSESSMENT_TEMPLATE", "")
    SENDGRID_WEBHOOK_VERIFICATION_KEY: str = os.getenv("SENDGRID_WEBHOOK_VERIFICATION_KEY", "")

    # ─── Authentication Secrets ───────────────────────────────────────────────
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "")

    # ─── Security Keys ────────────────────────────────────────────────────────
    BING_SEARCH_API_KEY: str = os.getenv("BING_SEARCH_API_KEY", "")
    TOTP_ENCRYPTION_KEY: str = os.getenv("TOTP_ENCRYPTION_KEY", "")
    SOVEREIGN_MIND_MASTER_KEY: str = os.getenv("SOVEREIGN_MIND_MASTER_KEY", "")
    SKYEYE_TOKEN_ENCRYPTION_KEY: str = os.getenv("SKYEYE_TOKEN_ENCRYPTION_KEY", "")
    SWARM_SECRET: Optional[str] = os.getenv("SWARM_SECRET")
    AZURE_STORAGE_CONNECTION_STRING: Optional[str] = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

    # ─── Social Media API Keys (SkyEye) ───────────────────────────────────────
    TIKTOK_CLIENT_KEY: str = os.getenv("TIKTOK_CLIENT_KEY", "")
    TIKTOK_CLIENT_SECRET: str = os.getenv("TIKTOK_CLIENT_SECRET", "")
    INSTAGRAM_APP_ID: str = os.getenv("INSTAGRAM_APP_ID", "")
    INSTAGRAM_APP_SECRET: str = os.getenv("INSTAGRAM_APP_SECRET", "")
    FACEBOOK_APP_ID: str = os.getenv("FACEBOOK_APP_ID", "")
    FACEBOOK_APP_SECRET: str = os.getenv("FACEBOOK_APP_SECRET", "")
    YOUTUBE_CLIENT_ID: str = os.getenv("YOUTUBE_CLIENT_ID", "")
    YOUTUBE_CLIENT_SECRET: str = os.getenv("YOUTUBE_CLIENT_SECRET", "")
    YOUTUBE_API_KEY: str = os.getenv("YOUTUBE_API_KEY", "")
    REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    REDDIT_USERNAME: str = os.getenv("REDDIT_USERNAME", "")
    REDDIT_PASSWORD: str = os.getenv("REDDIT_PASSWORD", "")
    LINKEDIN_CLIENT_ID: str = os.getenv("LINKEDIN_CLIENT_ID", "")
    LINKEDIN_CLIENT_SECRET: str = os.getenv("LINKEDIN_CLIENT_SECRET", "")
    PINTEREST_APP_ID: str = os.getenv("PINTEREST_APP_ID", "")
    PINTEREST_APP_SECRET: str = os.getenv("PINTEREST_APP_SECRET", "")

    # ─── Zoom Credentials ─────────────────────────────────────────────────────
    ZOOM_ACCOUNT_ID: str = os.getenv("ZOOM_ACCOUNT_ID", "")
    ZOOM_CLIENT_ID: str = os.getenv("ZOOM_CLIENT_ID", "")
    ZOOM_CLIENT_SECRET: str = os.getenv("ZOOM_CLIENT_SECRET", "")
    ZOOM_WEBHOOK_SECRET_TOKEN: str = os.getenv("ZOOM_WEBHOOK_SECRET_TOKEN", "")
