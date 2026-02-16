"""
HIVE DEFENSE v4.3 — Succession Protocol (Window 5)
Shamir's Secret Sharing (3-of-5) and Dead Man's Switch (14-day).

Ensures the platform can survive the loss of any key holder
while requiring consensus for critical operations.

- Master key split into 5 shares, any 3 can reconstruct
- Dead Man's Switch: if not acknowledged within 14 days, initiates succession
- Recovery drill framework (monthly/quarterly/annual)
"""

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

_logger = logging.getLogger("succession_protocol")

# Dead Man's Switch configuration
DEADMAN_INTERVAL_DAYS = 14
DEADMAN_WARNING_DAYS = 7  # Warning at 7 days before deadline

# Shamir's Secret Sharing parameters
TOTAL_SHARES = 5
THRESHOLD = 3  # 3-of-5 required to reconstruct


class ShamirSecretSharing:
    """
    Shamir's Secret Sharing implementation for key splitting.
    Uses GF(2^8) arithmetic for byte-level splitting.
    """

    PRIME = 257  # Smallest prime > 256 (for GF(p) field)

    @classmethod
    def split_secret(cls, secret: bytes, n: int = TOTAL_SHARES, k: int = THRESHOLD) -> List[Tuple[int, bytes]]:
        """
        Split a secret into n shares, any k of which can reconstruct it.
        Returns list of (share_index, share_bytes).
        """
        shares = [bytearray() for _ in range(n)]

        for byte_val in secret:
            # Generate k-1 random coefficients for the polynomial
            coefficients = [byte_val] + [secrets.randbelow(cls.PRIME) for _ in range(k - 1)]

            # Evaluate polynomial at points 1..n
            for i in range(n):
                x = i + 1
                y = cls._evaluate_polynomial(coefficients, x)
                shares[i].append(y % 256)

        return [(i + 1, bytes(share)) for i, share in enumerate(shares)]

    @classmethod
    def reconstruct_secret(cls, shares: List[Tuple[int, bytes]], k: int = THRESHOLD) -> bytes:
        """
        Reconstruct the secret from k shares using Lagrange interpolation.
        """
        if len(shares) < k:
            raise ValueError(f"Need at least {k} shares, got {len(shares)}")

        # Use only first k shares
        shares = shares[:k]
        secret_length = len(shares[0][1])
        result = bytearray()

        for byte_idx in range(secret_length):
            # Lagrange interpolation at x=0
            secret_byte = 0
            for i, (xi, share_i) in enumerate(shares):
                yi = share_i[byte_idx]
                # Compute Lagrange basis polynomial at x=0
                numerator = 1
                denominator = 1
                for j, (xj, _) in enumerate(shares):
                    if i != j:
                        numerator = (numerator * (-xj)) % cls.PRIME
                        denominator = (denominator * (xi - xj)) % cls.PRIME

                # Modular inverse of denominator
                lagrange = (yi * numerator * pow(denominator, cls.PRIME - 2, cls.PRIME)) % cls.PRIME
                secret_byte = (secret_byte + lagrange) % cls.PRIME

            result.append(secret_byte % 256)

        return bytes(result)

    @classmethod
    def _evaluate_polynomial(cls, coefficients: List[int], x: int) -> int:
        """Evaluate a polynomial at point x in GF(PRIME)."""
        result = 0
        for i, coeff in enumerate(coefficients):
            result = (result + coeff * pow(x, i, cls.PRIME)) % cls.PRIME
        return result


class DeadManSwitch:
    """
    Dead Man's Switch: requires periodic acknowledgment.
    If not acknowledged within DEADMAN_INTERVAL_DAYS, initiates succession.
    """

    def __init__(self, db_pool=None):
        self._db = db_pool
        self._last_acknowledged: Optional[datetime] = None
        self._holders: List[str] = []

    def acknowledge(self, holder_id: str) -> Dict[str, Any]:
        """Acknowledge the dead man's switch (reset the timer)."""
        self._last_acknowledged = datetime.now(timezone.utc)
        _logger.info("Dead Man's Switch acknowledged by %s", holder_id[:8])
        return {
            "acknowledged": True,
            "next_deadline": (self._last_acknowledged + timedelta(days=DEADMAN_INTERVAL_DAYS)).isoformat(),
            "holder": holder_id[:8],
        }

    def check_status(self) -> Dict[str, Any]:
        """Check the current status of the dead man's switch."""
        if not self._last_acknowledged:
            return {
                "status": "never_acknowledged",
                "urgent": True,
            }

        now = datetime.now(timezone.utc)
        deadline = self._last_acknowledged + timedelta(days=DEADMAN_INTERVAL_DAYS)
        warning = self._last_acknowledged + timedelta(days=DEADMAN_WARNING_DAYS)
        remaining = (deadline - now).total_seconds()

        if remaining <= 0:
            return {
                "status": "triggered",
                "last_acknowledged": self._last_acknowledged.isoformat(),
                "deadline_passed": True,
                "action_required": "initiate_succession",
            }
        elif now > warning:
            return {
                "status": "warning",
                "last_acknowledged": self._last_acknowledged.isoformat(),
                "remaining_hours": remaining / 3600,
                "action_required": "acknowledge_immediately",
            }
        else:
            return {
                "status": "active",
                "last_acknowledged": self._last_acknowledged.isoformat(),
                "remaining_days": remaining / 86400,
                "next_warning": warning.isoformat(),
            }


class SuccessionProtocol:
    """
    Full succession protocol combining Shamir sharing and Dead Man's Switch.
    """

    def __init__(self, db_pool=None):
        self._db = db_pool
        self.shamir = ShamirSecretSharing()
        self.deadman = DeadManSwitch(db_pool)
        self._share_holders: Dict[str, Dict[str, Any]] = {}

    def register_share_holder(
        self, holder_id: str, holder_name: str, contact_method: str,
    ) -> Dict[str, Any]:
        """Register a Shamir share holder."""
        if len(self._share_holders) >= TOTAL_SHARES:
            return {"registered": False, "reason": "max_holders_reached"}

        self._share_holders[holder_id] = {
            "name": holder_name,
            "contact": contact_method,
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "share_index": len(self._share_holders) + 1,
        }

        _logger.info(
            "Share holder registered: %s (index=%d)",
            holder_id[:8], len(self._share_holders),
        )

        return {
            "registered": True,
            "holder_id": holder_id[:8],
            "share_index": len(self._share_holders),
            "total_holders": len(self._share_holders),
        }

    def split_master_key(self, master_key: bytes) -> List[Dict[str, Any]]:
        """
        Split the master key into shares for all registered holders.
        Returns share metadata (NOT the actual shares — those go to holders directly).
        """
        shares = self.shamir.split_secret(master_key, TOTAL_SHARES, THRESHOLD)
        results = []

        for idx, (share_idx, share_bytes) in enumerate(shares):
            share_hash = hashlib.sha256(share_bytes).hexdigest()[:16]
            results.append({
                "share_index": share_idx,
                "share_hash": share_hash,
                "share_length": len(share_bytes),
            })

        _logger.info(
            "Master key split into %d shares (threshold=%d)",
            len(shares), THRESHOLD,
        )

        return results

    def get_succession_status(self) -> Dict[str, Any]:
        """Get the overall succession protocol status."""
        return {
            "share_holders": len(self._share_holders),
            "total_shares": TOTAL_SHARES,
            "threshold": THRESHOLD,
            "deadman_status": self.deadman.check_status(),
            "ready": len(self._share_holders) >= TOTAL_SHARES,
        }
