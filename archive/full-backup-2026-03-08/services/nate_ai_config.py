"""
Centralized AI configuration for Little Nate's intelligence engine.

All chat/completions calls across the platform should use these helpers
to ensure consistent model, temperature, and authentication.
"""

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

_mood_seed = time.time()


def _is_elevated(user_id: str | None) -> bool:
    """Check whether a user belongs to the elevated-temperature test cohort."""
    return bool(user_id and user_id in _ELEVATED_USERS)


def nate_temperature(user_id: str | None = None) -> float:
    """Return a mood-adjusted temperature.

    Standard users: drifts around 1.37 within [1.1, 1.52].
    Elevated test cohort: drifts around 1.56 within [1.1, 2.0].
    """
    global _mood_seed
    _mood_seed += random.random()

    if _is_elevated(user_id):
        drift = random.gauss(0, 0.12)
        temp = _ELEVATED_HOME + drift
        temp = _TEMP_DRIFT_WEIGHT * temp + (1 - _TEMP_DRIFT_WEIGHT) * _ELEVATED_HOME
        return round(max(_ELEVATED_LOW, min(_ELEVATED_HIGH, temp)), 3)

    drift = random.gauss(0, 0.08)
    temp = _TEMP_HOME + drift
    temp = _TEMP_DRIFT_WEIGHT * temp + (1 - _TEMP_DRIFT_WEIGHT) * _TEMP_HOME
    return round(max(_TEMP_LOW, min(_TEMP_HIGH, temp)), 3)


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
