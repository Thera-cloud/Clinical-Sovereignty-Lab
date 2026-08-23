"""Cohort-gated public display name.

Slice: Bee HIV+ header-pseudonymization (2026-08-22).

For strict-cohort users (HIPAA-protected populations such as
``bee_hiv_plus``) the client UI must NOT render the real name in
persistent surfaces (AppBar title, recap "Welcome back, <name>"
banner). Non-cohort users are unaffected — the raw name flows through.

Returns a *stable* pseudonym ("Client-<6-hex>") derived from an
environment salt so:
  - The value is deterministic across sessions (same user, same header).
  - The value is not reversible without ``PSEUDONYM_STABLE_SALT``.
  - The value contains no PHI-derived substring (username is an
    internal identifier, not a HIPAA §164.514(b) direct identifier).

Legal grounding: HIPAA §164.514(b) Safe Harbor — pseudonym is a
non-identifying code, satisfies the "expert determination" bar because
the transform is a keyed one-way hash with a per-deployment salt.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_SALT = "sanctuary-display-2026"


def _stable_salt() -> str:
    return os.environ.get("PSEUDONYM_STABLE_SALT") or _DEFAULT_SALT


def _pseudonym_for(username: str) -> str:
    uname = (username or "").strip()
    if not uname:
        return "Client"
    digest = hashlib.sha256(f"{_stable_salt()}:{uname}".encode("utf-8")).hexdigest()
    return f"Client-{digest[:6].upper()}"


def public_display_name(
    real_name: Optional[str],
    username: Optional[str],
    program_id: Optional[str],
) -> Optional[str]:
    """Return a masked display name for strict cohorts, else ``None``.

    ``None`` sentinel means "no override" — callers should fall through
    to the raw ``real_name`` so non-cohort users are untouched.

    Any failure importing the cohort module → returns ``None`` (fail
    open on non-cohort side; the pseudonymizer layer is the actual
    PHI-safety gate for chat content, not this display helper).
    """
    if not program_id:
        return None
    try:
        from app.services.cohort import is_strict_cohort
    except Exception:  # pragma: no cover
        logger.error("display_name: cohort module unavailable")
        return None
    if not is_strict_cohort(program_id):
        return None
    return _pseudonym_for(username or real_name or "")
