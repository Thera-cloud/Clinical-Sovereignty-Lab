"""
ZEFCP Signature Rotation — Time-based fragment validation.
Patent Claim 25.3: Zero-Energy BLE Communication — Rotation-scheduled
signature byte to reject replay and off-swarm traffic.
"""

from __future__ import annotations

import hmac
import hashlib
import time
from typing import Set


# =============================================================================
# ROTATION PARAMETERS
# =============================================================================

ROTATION_PERIOD_MINUTES = 15


# =============================================================================
# SIGNATURE COMPUTATION
# =============================================================================


def compute_signature(epoch_minute: int, swarm_secret: bytes) -> int:
    """
    Compute the signature byte for a given epoch minute.
    Patent Claim 25.3: rotation_period = epoch_minute // 15; HMAC-SHA256
    over rotation period yields a single-byte signature for this period.
    """
    rotation_period = epoch_minute // ROTATION_PERIOD_MINUTES
    hmac_input = rotation_period.to_bytes(8, "big")
    digest = hmac.new(swarm_secret, hmac_input, hashlib.sha256).digest()
    return digest[0]


def get_valid_signatures(swarm_secret: bytes) -> Set[int]:
    """
    Return current, previous (-15 min), and next (+15 min) rotation period
    signatures. Patent Claim 25.3: Accept window of ±1 period for clock skew.
    """
    epoch_minute = int(time.time() / 60)
    result: Set[int] = set()
    for offset in (-ROTATION_PERIOD_MINUTES, 0, ROTATION_PERIOD_MINUTES):
        em = epoch_minute + offset
        result.add(compute_signature(em, swarm_secret))
    return result


# =============================================================================
# SIGNATURE ROTATOR
# =============================================================================


class SignatureRotator:
    """
    Caches current signature and updates on rotation.
    Patent Claim 25.3: Endpoints use this to encode fragments with the
    correct rotating signature; detectors use get_valid_signatures.
    """

    def __init__(self, swarm_secret: bytes) -> None:
        self._swarm_secret = swarm_secret
        self._cached_period: int = -1
        self._cached_sig: int = 0

    @property
    def current_sig(self) -> int:
        """Current rotation period signature; updates on period change."""
        epoch_minute = int(time.time() / 60)
        period = epoch_minute // ROTATION_PERIOD_MINUTES
        if period != self._cached_period:
            self._cached_period = period
            self._cached_sig = compute_signature(epoch_minute, self._swarm_secret)
        return self._cached_sig

    def is_valid(self, sig_byte: int) -> bool:
        """True if sig_byte matches any valid signature in the ±1 window."""
        return sig_byte in get_valid_signatures(self._swarm_secret)
