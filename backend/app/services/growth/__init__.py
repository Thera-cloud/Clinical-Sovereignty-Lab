"""Adaptive Growth Engine — non-social marketing substrate.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import os


def growth_engine_enabled() -> bool:
    return os.getenv("ENABLE_GROWTH_ENGINE", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def content_factory_enabled() -> bool:
    return os.getenv("ENABLE_CONTENT_FACTORY", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def outreach_engine_enabled() -> bool:
    return os.getenv("ENABLE_OUTREACH_ENGINE", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def bwas_enabled() -> bool:
    return os.getenv("ENABLE_BWAS", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def try_theme_telemetry_enabled() -> bool:
    return os.getenv("ENABLE_TRY_THEME_TELEMETRY", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def growth_diagnostics_enabled() -> bool:
    return os.getenv("ENABLE_GROWTH_DIAGNOSTICS", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
