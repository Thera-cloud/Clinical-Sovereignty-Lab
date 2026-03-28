"""
HIVE DEFENSE v4.3 — Compartmentalized Configuration

API keys and secrets are organized into separate modules by concern area.
This limits the blast radius if any single config module is compromised:

- network.py    — Server addresses, ports, CORS, URLs
- thresholds.py — Feature flags, timing, rate limits, scoring parameters
- canaries.py   — API keys for upstream providers (Azure, Stripe, SendGrid, etc.)

The Settings class provides the single source of truth for all config values.
"""

from .network import NetworkConfig
from .thresholds import ThresholdConfig
from .canaries import CanaryConfig
from ._settings import Settings, get_settings, settings

__all__ = [
    "NetworkConfig",
    "ThresholdConfig",
    "CanaryConfig",
    "Settings",
    "get_settings",
    "settings",
]
