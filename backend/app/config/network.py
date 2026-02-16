"""
HIVE DEFENSE v4.3 — Network Configuration (Compartmentalized)

Contains ONLY network-related settings: hosts, ports, URLs, CORS.
No API keys or secrets.
"""

import os


class NetworkConfig:
    """Read-only network configuration."""

    SERVER_HOST = os.getenv("SERVER_HOST", "10.0.0.81")
    SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
    WEBSOCKET_PORT = int(os.getenv("WEBSOCKET_PORT", "8765"))
    ADMIN_PORT = int(os.getenv("ADMIN_PORT", "3000"))

    BASE_URL = os.getenv("BASE_URL", "http://10.0.0.81:8000")
    WS_URL = os.getenv("WS_URL", "ws://10.0.0.81:8765")
    APP_URL = os.getenv("APP_URL", "https://app.sovereignsanctuary.net")
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")
    DOMAIN = os.getenv("DOMAIN")

    CORS_ORIGINS = os.getenv(
        "CORS_ORIGINS",
        "http://10.0.0.81:3000,http://localhost:3000,"
        "https://app.sovereignsanctuary.net,"
        "https://coach.sovereignsanctuary.net,"
        "https://command.sovereignsanctuary.net",
    )

    # Database connectivity
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "10.0.0.81")
    POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB = os.getenv("POSTGRES_DB", "little_nate")
    POSTGRES_USER = os.getenv("POSTGRES_USER", "nate_admin")

    # Redis connectivity (host/port only — no auth secrets)
    REDIS_HOST = os.getenv("REDIS_HOST", "10.0.0.81")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

    # Paths
    DATA_DIR = os.getenv("DATA_DIR", "/app/data")
    WORKBOOKS_DIR = os.getenv("WORKBOOKS_DIR", "/app/workbooks")

    # SMTP connectivity (host/port only — credentials are in canaries)
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.sendgrid.net")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

    # Zoom connectivity (non-secret settings only)
    ZOOM_HOST_USER = os.getenv("ZOOM_HOST_USER", "me")
    ZOOM_DEFAULT_TIMEZONE = os.getenv("ZOOM_DEFAULT_TIMEZONE", "America/Los_Angeles")
    ZOOM_DEFAULT_WAITING_ROOM = os.getenv("ZOOM_DEFAULT_WAITING_ROOM", "True").lower() == "true"
    ZOOM_DEFAULT_JOIN_BEFORE_HOST = os.getenv("ZOOM_DEFAULT_JOIN_BEFORE_HOST", "False").lower() == "true"
    ZOOM_DEFAULT_AUTO_RECORDING = os.getenv("ZOOM_DEFAULT_AUTO_RECORDING", "cloud")
