"""
HIVE DEFENSE v4.3 — Compartmentalized Configuration

API keys and secrets are organized into separate modules by concern area.
This limits the blast radius if any single config module is compromised:

- network.py    — Server addresses, ports, CORS, URLs
- thresholds.py — Feature flags, timing, rate limits, scoring parameters
- canaries.py   — API keys for upstream providers (Azure, Stripe, SendGrid, etc.)

The main Settings class in app/config.py remains the single source of truth,
but these modules provide scoped access points so that services only import
the keys they need.
"""

from .network import NetworkConfig
from .thresholds import ThresholdConfig
from .canaries import CanaryConfig

__all__ = ["NetworkConfig", "ThresholdConfig", "CanaryConfig"]
