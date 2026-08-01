"""Per-window HMAC signing for outcome_envelope rows (E4).

Every envelope write is signed with a key derived from a base secret plus a
rotating window id, so evidence collected within one confounded/clean window
(E5) can be verified as a batch and post-hoc row edits (e.g. someone flipping
`shadow_outcome->>'passed'` after the fact to force a promote) are detectable.

Design:
  - The base secret (LN7_ENVELOPE_SIGNING_SECRET) never needs to be stored
    per-row. Each window derives its own subkey via
    HMAC(base_secret, window_id) -- a window key never appears in the DB,
    only the resulting signature does, so leaking one row's signature does
    not help forge a signature in another window.
  - The window granularity matches the E5 change-lease TTL
    (LN7_CHANGE_LEASE_TTL_S, default 900s) so a signing window lines up with
    a scoring/lease window: rows written while the same lease was (or
    wasn't) held share a key and can be checked together.
  - Signing covers every column that participates in the promote decision:
    identity fields, attribution/metrics/provenance JSON, shadow_outcome,
    confounded, and cost_usd. Volatile columns (envelope_id, created_at) are
    excluded because they're server-generated and not attacker-controlled
    inputs to the promote gate.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("ln7_envelope_signing")

_SECRET_ENV = "LN7_ENVELOPE_SIGNING_SECRET"
# Fallback keeps signing self-consistent (sign == verify) in dev/CI where the
# env var isn't set, but every sig produced this way is worthless as a
# tamper-evidence guarantee -- it's a well-known constant, not a secret.
_DEV_FALLBACK_SECRET = "ln7-envelope-signing-dev-fallback-do-not-use-in-prod"
_warned_fallback = False

DEFAULT_WINDOW_S = int(os.getenv("LN7_CHANGE_LEASE_TTL_S", "900"))

# Columns (in this exact order) that participate in the signed payload.
# Callers pass the already-json.dumps()'d strings for JSONB columns so the
# signature covers the exact bytes persisted, not a re-serialization of the
# same dict that could differ in key order/whitespace.
SIGNED_FIELDS = (
    "loop_name",
    "event_kind",
    "revision_id",
    "task_hash",
    "patch_hash",
    "domain_tag",
    "source_node",
    "burst_id",
    "attribution_json",
    "metrics_json",
    "provenance_json",
    "shadow_outcome",
    "confounded",
    "cost_usd",
)


def _base_secret() -> bytes:
    global _warned_fallback
    secret = os.getenv(_SECRET_ENV)
    if secret:
        return secret.encode("utf-8")
    if not _warned_fallback:
        logger.warning(
            "%s not set — using dev fallback signing secret. "
            "Envelope signatures are NOT tamper-evident until this is set.",
            _SECRET_ENV,
        )
        _warned_fallback = True
    return _DEV_FALLBACK_SECRET.encode("utf-8")


def window_id_for(ts: Optional[float] = None, window_s: int = DEFAULT_WINDOW_S) -> str:
    """Bucket a unix timestamp into a fixed-width window id string.

    E4: "per-window signing key" -- window_s defaults to the E5 change-lease
    TTL so signing windows line up with lease/scoring windows.
    """
    window_s = max(1, int(window_s))
    t = time.time() if ts is None else ts
    bucket = int(t // window_s)
    return f"w{window_s}:{bucket}"


def _derive_window_key(window_id: str) -> bytes:
    """HMAC-derived per-window subkey. Never persisted -- recomputed on
    both sign and verify from (base secret, window_id)."""
    return hmac.new(_base_secret(), window_id.encode("utf-8"), hashlib.sha256).digest()


def _canonicalize(fields: Dict[str, Any]) -> bytes:
    parts = []
    for key in SIGNED_FIELDS:
        val = fields.get(key)
        if val is None:
            parts.append(f"{key}=\x00")
        elif isinstance(val, bool):
            parts.append(f"{key}={'1' if val else '0'}")
        else:
            parts.append(f"{key}={val}")
    return "\x1f".join(parts).encode("utf-8")


def sign_fields(fields: Dict[str, Any], *, ts: Optional[float] = None) -> Dict[str, str]:
    """Compute {sig, sig_window} for an envelope's field set.

    `fields` must use the JSONB columns' already-serialized string form
    (attribution_json/metrics_json/provenance_json/shadow_outcome) so the
    signature matches exactly what gets persisted.
    """
    window_id = window_id_for(ts)
    key = _derive_window_key(window_id)
    digest = hmac.new(key, _canonicalize(fields), hashlib.sha256).hexdigest()
    return {"sig": digest, "sig_window": window_id}


def verify_row_signature(row: Dict[str, Any]) -> bool:
    """Recompute the signature for a persisted envelope row and compare.

    Returns False (not True) for legacy rows written before E4 shipped
    (sig/sig_window both NULL) -- callers that need to distinguish
    "unsigned" from "tampered" should check `row.get("sig")` first.
    """
    sig = row.get("sig")
    window_id = row.get("sig_window")
    if not sig or not window_id:
        return False
    key = _derive_window_key(window_id)
    expected = hmac.new(key, _canonicalize(row), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)
