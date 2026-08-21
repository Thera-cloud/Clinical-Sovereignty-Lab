"""Cohort (program) policy helpers.

Single source of truth for which ``users.program_id`` values get a stricter
privacy/security posture. Consumed by:

- ``mfa_gate`` — tighter MFA re-verification window for cohort members.
- ``retention_policy`` — already implements per-cohort retention days; kept
  aligned via the ``STRICT_COHORT_PROGRAM_IDS`` set below.
- ``enrollment_api`` — validates redemption ``code.program_id`` values are
  known cohorts before stamping ``users.program_id``.

Design notes
------------
- No feature flag. This module is pure policy metadata; callers control
  whether to consult it via their own flags (e.g. ``ENABLE_PHI_MFA_GATE``
  gates ``mfa_gate``). Off-cohort users pay a single frozenset membership
  check, so this is safe to import unconditionally.
- Case-insensitive matching — callers should pass raw ``program_id`` from
  the DB; normalization happens here.
- Additive: extending to a new cohort is a one-line edit here plus any
  cohort-specific windows in the tables below.

Legal grounding
---------------
- BAA §8.7A (program isolation) — cohorts must not bleed into general pool.
- HIPAA §164.312(a)(2)(i) — access controls proportional to risk. Cohorts
  handling higher-risk PHI get tighter step-up windows.
"""

from __future__ import annotations

import os
from typing import Optional

# --------------------------------------------------------------------------- #
# Cohort membership                                                           #
# --------------------------------------------------------------------------- #

# Program IDs that opt into the stricter privacy/security posture. Add new
# cohorts here as they are onboarded. Values MUST be lower-case.
STRICT_COHORT_PROGRAM_IDS = frozenset({"bee_hiv_plus"})


def normalize_program_id(program_id: Optional[str]) -> Optional[str]:
    """Return a lower-case, whitespace-trimmed program_id or None."""
    if not program_id:
        return None
    val = str(program_id).strip().lower()
    return val or None


def is_strict_cohort(program_id: Optional[str]) -> bool:
    """Return True iff ``program_id`` is in ``STRICT_COHORT_PROGRAM_IDS``."""
    norm = normalize_program_id(program_id)
    if norm is None:
        return False
    return norm in STRICT_COHORT_PROGRAM_IDS


def is_known_cohort(program_id: Optional[str]) -> bool:
    """Return True iff ``program_id`` matches any cohort we know about.

    Currently identical to ``is_strict_cohort`` — kept as a separate name so
    that future non-strict cohorts (e.g. a research pilot with looser
    retention) can be added without churning callers.
    """
    return is_strict_cohort(program_id)


# --------------------------------------------------------------------------- #
# MFA freshness window                                                        #
# --------------------------------------------------------------------------- #

_ENV_STRICT_MFA_WINDOW = "MFA_GATE_STRICT_WINDOW_SECONDS"

# Default tighter re-verification window for strict cohorts (5 minutes).
# Global default in ``mfa_gate`` is 1800s (30 minutes); strict cohort members
# must re-authenticate more often when the gate is enabled. Overridable per
# deploy via env, clamped to [60s, 24h] matching mfa_gate's own clamp.
_DEFAULT_STRICT_MFA_WINDOW = 300


def get_strict_mfa_window_seconds() -> int:
    """Return the strict-cohort MFA freshness window in seconds.

    Reads ``MFA_GATE_STRICT_WINDOW_SECONDS`` each call so tests / operators
    can retune without a restart. Falls back to 300s on missing / malformed
    input. Clamped to ``[60, 86_400]`` to prevent pathological configs.
    """
    raw = (os.getenv(_ENV_STRICT_MFA_WINDOW) or "").strip()
    if not raw:
        return _DEFAULT_STRICT_MFA_WINDOW
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_STRICT_MFA_WINDOW
    return max(60, min(n, 86_400))


__all__ = [
    "STRICT_COHORT_PROGRAM_IDS",
    "get_strict_mfa_window_seconds",
    "is_known_cohort",
    "is_strict_cohort",
    "normalize_program_id",
]
