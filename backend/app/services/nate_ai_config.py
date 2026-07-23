"""
Centralized AI configuration for Little Nate's intelligence engine.

All chat/completions calls across the platform should use these helpers
to ensure consistent model, temperature, and authentication.
"""
from __future__ import annotations

import os
import random
import time

NATE_CHAT_URL = (
    os.getenv(
        "NATE_CHAT_URL",
        "https://nathanlhr-0393-resource.services.ai.azure.com"
        "/models/chat/completions?api-version=2024-05-01-preview",
    )
)

NATE_CHAT_KEY = os.getenv(
    "NATE_CHAT_KEY",
    os.getenv("AZURE_API_KEY", ""),
)

NATE_CHAT_MODEL = os.getenv(
    "NATE_CHAT_MODEL",
    "grok-4-1-fast-non-reasoning",
)

# Command Terminal LN-FAB/DEBUG / Sovereign IDE code model (Phase A0)
# Prefer NATE_CLI_REASONING_MODEL; NATE_CLI_CODE_MODEL is the clean alias.
NATE_CLI_REASONING_MODEL = (
    os.getenv("NATE_CLI_REASONING_MODEL")
    or os.getenv("NATE_CLI_CODE_MODEL")
    or ""
)
NATE_CLI_CODE_MODEL = os.getenv("NATE_CLI_CODE_MODEL", "") or NATE_CLI_REASONING_MODEL
NATE_CLI_CODE_URL = os.getenv("NATE_CLI_CODE_URL", "")
NATE_CLI_CODE_KEY = os.getenv("NATE_CLI_CODE_KEY", "") or os.getenv("XAI_API_KEY", "")

# ---------------------------------------------------------------------------
# Standard temperature range (all users)
# ---------------------------------------------------------------------------
_TEMP_LOW = 1.1
_TEMP_HIGH = 1.52
_TEMP_HOME = 1.37
_TEMP_DRIFT_WEIGHT = 0.6

# ---------------------------------------------------------------------------
# Elevated temperature test cohort
# ---------------------------------------------------------------------------
_ELEVATED_USERS = frozenset({
    "sweet2noend",              # Kristy Moore (COACH)
    "sweet2noend@yahoo.com",    # Kristy Moore (CLIENT)
    "client_wilsnaw",           # Ava
    "FAM_5D6AC5DF",             # Ava family ID
})

_ELEVATED_LOW = 1.1
_ELEVATED_HIGH = 2.0
_ELEVATED_HOME = 1.56

# Client therapeutic chat cap (Lisa policy 2026-05-19)
_CLINICAL_TEMP_CAP = float(os.getenv("NATE_CLINICAL_TEMPERATURE", "1.2"))

_mood_seed = time.time()


def _is_elevated(user_id: str | None) -> bool:
    """Check whether a user belongs to the elevated-temperature test cohort."""
    return bool(user_id and user_id in _ELEVATED_USERS)


def nate_temperature(user_id: str | None = None, *, clinical: bool = False) -> float:
    """Return a mood-adjusted temperature.

    Standard users: drifts around 1.37 within [1.1, 1.52].
    Elevated test cohort: drifts around 1.56 within [1.1, 2.0].
    When ``clinical=True``, result is capped at ``NATE_CLINICAL_TEMPERATURE`` (default 1.2).
    """
    global _mood_seed
    _mood_seed += random.random()

    if _is_elevated(user_id):
        drift = random.gauss(0, 0.12)
        temp = _ELEVATED_HOME + drift
        temp = _TEMP_DRIFT_WEIGHT * temp + (1 - _TEMP_DRIFT_WEIGHT) * _ELEVATED_HOME
        temp = max(_ELEVATED_LOW, min(_ELEVATED_HIGH, temp))
    else:
        drift = random.gauss(0, 0.08)
        temp = _TEMP_HOME + drift
        temp = _TEMP_DRIFT_WEIGHT * temp + (1 - _TEMP_DRIFT_WEIGHT) * _TEMP_HOME
        temp = max(_TEMP_LOW, min(_TEMP_HIGH, temp))

    if clinical:
        temp = min(temp, _CLINICAL_TEMP_CAP)
    return round(temp, 3)


def nate_chat_headers() -> dict:
    """Return the authentication headers for Nate's chat API."""
    return {
        "Content-Type": "application/json",
        "api-key": NATE_CHAT_KEY,
    }


def nate_chat_payload(
    messages: list,
    max_tokens: int = 4000,
    temperature: float | None = None,
    user_id: str | None = None,
) -> dict:
    """Build a standardized chat/completions request payload.

    Pass ``user_id`` to apply per-user temperature overrides (e.g. the
    elevated test cohort gets a wider, higher temperature range).
    """
    return {
        "model": NATE_CHAT_MODEL,
        "messages": messages,
        "max_completion_tokens": max_tokens,
        "temperature": (
            temperature if temperature is not None
            else nate_temperature(user_id)
        ),
    }
