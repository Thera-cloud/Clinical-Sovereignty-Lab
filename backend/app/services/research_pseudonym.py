"""Deterministic pseudonymization for the research schema (Slice 5).

Pseudonym = HMAC-SHA256(user_id_bytes, RESEARCH_HMAC_KEY) as 64-char hex.

Design rules
------------
1. Deterministic — same user + same key ⇒ same pseudonym across days.
2. Non-reversible without the key.
3. Fail-closed — if RESEARCH_HMAC_KEY is not set (and not explicitly relaxed
   via RESEARCH_ALLOW_MISSING_KEY=1 for tests), any call raises
   ResearchKeyMissing. Callers must be prepared to skip aggregation rather
   than silently emit unkeyed pseudonyms.
4. Rotation — changing the key rotates every pseudonym. This is deliberate;
   the aggregator's uniqueness constraint (pseudonym, day) tolerates
   duplicate days across key epochs because the old pseudonyms are dead.
5. No mapping table — recovering identity requires the key. Do not store
   the key inside the DB.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional
from uuid import UUID


class ResearchKeyMissing(RuntimeError):
    """Raised when RESEARCH_HMAC_KEY is unset and no relaxation flag is on."""


_ENV_KEY = "RESEARCH_HMAC_KEY"
_ENV_RELAX = "RESEARCH_ALLOW_MISSING_KEY"


def _load_key() -> bytes:
    raw = os.getenv(_ENV_KEY, "").strip()
    if raw:
        return raw.encode("utf-8")
    if os.getenv(_ENV_RELAX, "").strip().lower() in ("1", "true", "yes", "on"):
        # Test/dev-only path. Uses a fixed sentinel that anyone reading the
        # source can identify; never let this leak into production data.
        return b"__RESEARCH_KEY_UNSET_TEST_ONLY__"
    raise ResearchKeyMissing(
        f"{_ENV_KEY} is not set. Refusing to emit unkeyed pseudonyms."
    )


def pseudonymize(user_id: str | UUID | bytes | None) -> Optional[str]:
    """Return a 64-char hex HMAC pseudonym, or ``None`` for a null input.

    Accepts ``str``, ``UUID``, or ``bytes``. Everything else raises
    ``TypeError`` so callers can't accidentally feed rows or dicts through.
    """
    if user_id is None:
        return None
    if isinstance(user_id, UUID):
        payload = str(user_id).encode("utf-8")
    elif isinstance(user_id, bytes):
        payload = user_id
    elif isinstance(user_id, str):
        payload = user_id.strip().encode("utf-8")
        if not payload:
            return None
    else:
        raise TypeError(
            f"pseudonymize expects str/UUID/bytes/None, got {type(user_id).__name__}"
        )
    key = _load_key()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def is_configured() -> bool:
    """True if RESEARCH_HMAC_KEY is set (does not consult the relax flag)."""
    return bool(os.getenv(_ENV_KEY, "").strip())
