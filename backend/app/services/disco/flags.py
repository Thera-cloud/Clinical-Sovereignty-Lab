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
