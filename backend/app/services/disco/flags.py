"""Server-side kill flags. Default OFF — partial never ships (MASTER §17.0)."""

from __future__ import annotations

import os

DISCO_FLAGS = (
    "DISCO_RENDER",
    "DISCO_ONBOARD",
    "DISCO_HUBS",
    "DISCO_CREDSTATE",
    "DISCO_LIFECYCLE",
    "DISCO_DRIFT",
    "DISCO_ROTATION",
    "DISCO_TRENDS",
    "DISCO_PANEL",
    "DISCO_ATTRIB",
    "DISCO_DEMAND",
    "DISCO_REVIEWS",
    "DISCO_AGENT_API",
    "DISCO_BUILD",
    "DISCO_LINT",
    "DISCO_AREA",
    "DISCO_DECAY",
    "DISCO_COMPWATCH",
    "DISCO_FUNNEL",
    "DISCO_SCHEMA",
    "DISCO_INDEXWATCH",
    "DISCO_LISTINGS",
    "DISCO_GBP",
    "DISCO_CORRECT",
    "DISCO_CREDCHECK",
    "DISCO_LISTTRACK",
    "DISCO_QUEUE",
    "DISCO_SCHEDULE",
    "DISCO_AUTHORITY",
    "DISCO_ADAPT_TAXONOMY",
    "DISCO_WIDGET",
)


def disco_flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes", "on")


def disco_render_coach() -> str:
    """Single-coach allowlist. Empty = all active profiles (do not use at T1)."""
    return os.getenv("DISCO_RENDER_COACH", "").strip()


def disco_render_metro() -> str:
    """Service-area label, e.g. 'Detroit, MI, USA'."""
    return os.getenv("DISCO_RENDER_METRO", "").strip()


def disco_render_hub() -> str:
    """Programmatic hub path, e.g. coaches/trauma-coaches/detroit-mi."""
    return os.getenv("DISCO_RENDER_HUB", "").strip()
