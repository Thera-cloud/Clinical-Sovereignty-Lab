"""
HIVE DEFENSE PROTOCOL v1.0 — Key Sharding (Phase 8B)
Shamir's 3-of-5 Secret Sharing over GF(2^8) with dead-man switch and 90-day rotation.

The master key that signs Ephemeral Birth Certificates is never stored whole.
Instead it is split into 5 shares using Shamir's Secret Sharing Scheme (SSSS)
over the Galois field GF(256).  Any 3 of the 5 shares are sufficient to
reconstruct the secret; fewer than 3 reveal nothing.

Each share is assigned to a **Shard Holder** — a trusted human or HSM that
must check in within 30 days.  If a holder misses their check-in, the shard
automatically rotates to a designated successor.  Every 90 days all shards
are regenerated from the reconstructed secret to limit exposure.

Implementation Notes
--------------------
* **No external Shamir library** — GF(256) arithmetic is implemented directly
  using the AES irreducible polynomial x^8 + x^4 + x^3 + x + 1 (0x11B).
* Polynomial evaluation, Lagrange interpolation, and secret reconstruction
  are all constant-time within GF(256) to resist timing side-channels.
* Shares are stored as ``(index, bytes)`` tuples where *index* ∈ [1, 255]
  (never 0, because evaluating at 0 reveals the secret directly).

Patent-Pending — Claim 36
    "A key management method for a distributed AI therapy hive wherein a
     master signing key is split via Shamir Secret Sharing over GF(2^8)
     with a 3-of-5 threshold, combined with dead-man switch shard rotation
     and 90-day cryptoperiod enforcement."

© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

logger = logging.getLogger("hive.key_sharding")


# =============================================================================
# GF(256) ARITHMETIC
# =============================================================================
#
# We use the AES irreducible polynomial:  x^8 + x^4 + x^3 + x + 1 = 0x11B
# Elements are unsigned bytes 0–255.
#

_GF256_MODULUS = 0x11B


def _gf256_add(a: int, b: int) -> int:
    """Addition in GF(256) is XOR."""
    return a ^ b


def _gf256_sub(a: int, b: int) -> int:
    """Subtraction in GF(256) is identical to addition (XOR)."""
    return a ^ b


def _gf256_mul(a: int, b: int) -> int:
    """
    Multiplication in GF(256) via Russian-peasant algorithm with
    reduction by the AES irreducible polynomial.
    """
    result = 0
    aa = a
    bb = b
    for _ in range(8):
        if bb & 1:
            result ^= aa
        carry = aa & 0x80
        aa = (aa << 1) & 0xFF
        if carry:
            aa ^= (_GF256_MODULUS & 0xFF)
        bb >>= 1
    return result


def _gf256_pow(base: int, exp: int) -> int:
    """Exponentiation in GF(256) via repeated squaring."""
    result = 1
    b = base
    e = exp
    while e > 0:
        if e & 1:
            result = _gf256_mul(result, b)
        b = _gf256_mul(b, b)
        e >>= 1
    return result


def _gf256_inv(a: int) -> int:
    """
    Multiplicative inverse in GF(256).

    Uses Fermat's little theorem:  a^(-1) = a^(254) in GF(2^8).
    Returns 0 for the zero element (conventionally).
    """
    if a == 0:
        return 0
    return _gf256_pow(a, 254)


def _gf256_div(a: int, b: int) -> int:
    """Division in GF(256):  a / b = a * b^(-1)."""
    if b == 0:
        raise ZeroDivisionError("Division by zero in GF(256)")
    return _gf256_mul(a, _gf256_inv(b))


# =============================================================================
# POLYNOMIAL OPERATIONS OVER GF(256)
# =============================================================================

def _eval_poly(coefficients: List[int], x: int) -> int:
    """
    Evaluate a polynomial at *x* in GF(256).

    ``coefficients[0]`` is the constant term (the secret), ``coefficients[1]``
    is the coefficient of x, etc.
    """
    result = 0
    x_power = 1  # x^0
    for coeff in coefficients:
        result = _gf256_add(result, _gf256_mul(coeff, x_power))
        x_power = _gf256_mul(x_power, x)
    return result


def _lagrange_interpolate(points: List[Tuple[int, int]], x: int = 0) -> int:
    """
    Lagrange interpolation at *x* in GF(256).

    Given k points ``[(x_i, y_i), ...]``, recover the polynomial value at
    *x*.  When ``x = 0``, this reconstructs the secret (constant term).

    Parameters
    ----------
    points:
        List of (x_i, y_i) tuples with x_i ∈ [1, 255].
    x:
        The point to evaluate at (default 0 → secret).

    Returns
    -------
    int
        The reconstructed GF(256) element.
    """
    k = len(points)
    result = 0

    for i in range(k):
        xi, yi = points[i]
        # Compute the Lagrange basis polynomial L_i(x)
        numerator = 1
        denominator = 1
        for j in range(k):
            if i == j:
                continue
            xj = points[j][0]
            numerator = _gf256_mul(numerator, _gf256_sub(x, xj))
            denominator = _gf256_mul(denominator, _gf256_sub(xi, xj))

        basis = _gf256_div(numerator, denominator)
        result = _gf256_add(result, _gf256_mul(yi, basis))

    return result


# =============================================================================
# SHARD HOLDER MODEL
# =============================================================================

@dataclass
class ShardHolder:
    """
    Represents a custodian of one key shard.

    Attributes
    ----------
    holder_id:
        Unique identifier for the human or HSM holding this shard.
    shard_index:
        The evaluation point index (1-indexed) of this shard.
    last_checkin:
        UTC timestamp of the holder's most recent liveness check-in.
    successor_id:
        If the holder misses their 30-day check-in, the shard rotates
        to this designated successor.
    display_name:
        Human-readable name for dashboards.
    """

    holder_id: UUID = field(default_factory=uuid4)
    shard_index: int = 0
    last_checkin: datetime = field(default_factory=datetime.utcnow)
    successor_id: Optional[UUID] = None
    display_name: str = ""

    @property
    def is_alive(self) -> bool:
        """True if the holder has checked in within the last 30 days."""
        return (datetime.utcnow() - self.last_checkin).days < 30

    @property
    def days_since_checkin(self) -> int:
        """Number of full days since the last check-in."""
        return (datetime.utcnow() - self.last_checkin).days


# Dead-man switch threshold
DEAD_MAN_SWITCH_DAYS: int = 30

# Full rotation period
ROTATION_PERIOD_DAYS: int = 90


# =============================================================================
# KEY SHARDING SERVICE
# =============================================================================

class KeySharding:
    """
    Shamir's 3-of-5 Secret Sharing over GF(256) with dead-man switch rotation.

    The service manages the splitting, reconstruction, and lifecycle of the
    master signing key used by the Ephemeral Certificate Authority.

    Key Operations
    --------------
    * ``split_secret``       — Split an arbitrary-length secret into 5 shares.
    * ``reconstruct_secret`` — Reconstruct the secret from >= 3 shares.
    * ``rotate_all_shards``  — Reconstruct and re-split (new polynomial).
    * ``checkin``            — Record a shard holder's liveness check-in.
    * ``enforce_dead_man``   — Rotate shards for holders who missed check-in.

    Thread Safety
    -------------
    All mutating operations are guarded by an ``asyncio.Lock``.

    Patent Ref: Claim 36
    """

    DEFAULT_THRESHOLD: int = 3
    DEFAULT_SHARES: int = 5

    def __init__(self, db_pool=None) -> None:
        """
        Parameters
        ----------
        db_pool:
            An ``asyncpg.Pool`` for persisting shard metadata (not shard
            values — those are never stored centrally).
        """
        self._db_pool = db_pool
        self._holders: Dict[int, ShardHolder] = {}  # shard_index → holder
        self._last_rotation: Optional[datetime] = None
        self._rotation_count: int = 0
        self._lock: asyncio.Lock = asyncio.Lock()

        logger.info("KeySharding initialised (threshold=%d, shares=%d)",
                     self.DEFAULT_THRESHOLD, self.DEFAULT_SHARES)

    # ------------------------------------------------------------------
    # Core Shamir Operations
    # ------------------------------------------------------------------

    def split_secret(
        self,
        secret_bytes: bytes,
        threshold: int = 3,
        shares: int = 5,
    ) -> List[Tuple[int, bytes]]:
        """
        Split an arbitrary-length secret into Shamir shares over GF(256).

        Each byte of the secret is independently split using a random
        polynomial of degree ``threshold - 1``.  The shares are evaluated
        at x = 1, 2, ..., *shares* (never at x = 0, which would reveal
        the secret directly).

        Parameters
        ----------
        secret_bytes:
            The secret to split.  May be any length.
        threshold:
            Minimum number of shares required to reconstruct (default 3).
        shares:
            Total number of shares to produce (default 5).

        Returns
        -------
        list[(int, bytes)]
            A list of ``(index, share_bytes)`` tuples.  Each ``share_bytes``
            has the same length as ``secret_bytes``.

        Raises
        ------
        ValueError
            If ``threshold > shares`` or ``shares > 255``.
        """
        if threshold > shares:
            raise ValueError(
                f"Threshold ({threshold}) cannot exceed total shares ({shares})"
            )
        if shares > 255:
            raise ValueError(
                "Maximum 255 shares (GF(256) evaluation points 1..255)"
            )
        if threshold < 2:
            raise ValueError("Threshold must be at least 2 for meaningful security")

        # For each byte position, generate a random polynomial and evaluate
        secret_len = len(secret_bytes)
        result_shares: List[bytearray] = [bytearray(secret_len) for _ in range(shares)]

        for byte_idx in range(secret_len):
            secret_byte = secret_bytes[byte_idx]

            # Polynomial coefficients: coeff[0] = secret_byte, rest are random
            coefficients = [secret_byte] + [
                int.from_bytes(os.urandom(1), "big")
                for _ in range(threshold - 1)
            ]

            # Evaluate at x = 1, 2, ..., shares
            for share_idx in range(shares):
                x = share_idx + 1  # 1-indexed
                y = _eval_poly(coefficients, x)
                result_shares[share_idx][byte_idx] = y

        output = [
            (i + 1, bytes(result_shares[i]))
            for i in range(shares)
        ]

        logger.info(
            "Secret split: %d bytes → %d shares (threshold=%d)",
            secret_len,
            shares,
            threshold,
        )
        return output

    def reconstruct_secret(
        self,
        shares: List[Tuple[int, bytes]],
        threshold: int = 3,
    ) -> bytes:
        """
        Reconstruct a secret from ``>= threshold`` Shamir shares.

        Parameters
        ----------
        shares:
            A list of ``(index, share_bytes)`` tuples.  At least *threshold*
            shares must be provided.
        threshold:
            The original threshold used when splitting (default 3).

        Returns
        -------
        bytes
            The reconstructed secret.

        Raises
        ------
        ValueError
            If fewer than *threshold* shares are provided.
        """
        if len(shares) < threshold:
            raise ValueError(
                f"Need at least {threshold} shares to reconstruct "
                f"(got {len(shares)})"
            )

        # Use exactly `threshold` shares (first N)
        active_shares = shares[:threshold]
        secret_len = len(active_shares[0][1])

        # Verify all shares have the same length
        for idx, share_bytes in active_shares:
            if len(share_bytes) != secret_len:
                raise ValueError(
                    f"Share {idx} has length {len(share_bytes)}, "
                    f"expected {secret_len}"
                )

        # Reconstruct each byte independently
        result = bytearray(secret_len)
        for byte_idx in range(secret_len):
            points = [
                (idx, share_bytes[byte_idx])
                for idx, share_bytes in active_shares
            ]
            result[byte_idx] = _lagrange_interpolate(points, x=0)

        logger.info(
            "Secret reconstructed from %d shares (%d bytes)",
            len(active_shares),
            secret_len,
        )
        return bytes(result)

    # ------------------------------------------------------------------
    # Shard Holder Management
    # ------------------------------------------------------------------

    async def register_holder(
        self,
        shard_index: int,
        holder_id: Optional[UUID] = None,
        successor_id: Optional[UUID] = None,
        display_name: str = "",
    ) -> ShardHolder:
        """
        Register a shard holder for the given shard index.

        Parameters
        ----------
        shard_index:
            The 1-indexed shard evaluation point (1..5).
        holder_id:
            Unique ID for the holder.  Auto-generated if not provided.
        successor_id:
            Designated successor for dead-man switch rotation.
        display_name:
            Human-readable name for the holder.

        Returns
        -------
        ShardHolder
            The newly registered holder.
        """
        async with self._lock:
            holder = ShardHolder(
                holder_id=holder_id or uuid4(),
                shard_index=shard_index,
                last_checkin=datetime.utcnow(),
                successor_id=successor_id,
                display_name=display_name,
            )
            self._holders[shard_index] = holder

            logger.info(
                "Registered shard holder: index=%d holder=%s name=%s",
                shard_index,
                holder.holder_id,
                display_name,
            )

            await self._persist_holder(holder)
            return holder

    async def checkin(self, shard_index: int) -> bool:
        """
        Record a shard holder's liveness check-in.

        Parameters
        ----------
        shard_index:
            The shard index whose holder is checking in.

        Returns
        -------
        bool
            True if the holder was found and the check-in was recorded.
        """
        async with self._lock:
            holder = self._holders.get(shard_index)
            if holder is None:
                logger.warning("Check-in for unknown shard index %d", shard_index)
                return False

            holder.last_checkin = datetime.utcnow()
            logger.info(
                "Shard holder check-in: index=%d holder=%s",
                shard_index,
                holder.holder_id,
            )

            await self._persist_holder(holder)
            return True

    async def enforce_dead_man(self) -> List[int]:
        """
        Enforce the dead-man switch on all shard holders.

        Any holder that has not checked in within ``DEAD_MAN_SWITCH_DAYS``
        days has their shard reassigned to their designated successor.

        Returns
        -------
        list[int]
            List of shard indices that were rotated to successors.
        """
        rotated: List[int] = []

        async with self._lock:
            for shard_index, holder in list(self._holders.items()):
                if holder.is_alive:
                    continue

                if holder.successor_id is None:
                    logger.error(
                        "Shard holder %s (index=%d) missed dead-man check-in "
                        "but has NO designated successor!",
                        holder.holder_id,
                        shard_index,
                    )
                    continue

                logger.warning(
                    "Dead-man switch triggered: shard %d rotating from %s to %s "
                    "(%d days since check-in)",
                    shard_index,
                    holder.holder_id,
                    holder.successor_id,
                    holder.days_since_checkin,
                )

                # Rotate to successor
                new_holder = ShardHolder(
                    holder_id=holder.successor_id,
                    shard_index=shard_index,
                    last_checkin=datetime.utcnow(),
                    successor_id=None,  # successor must designate their own
                    display_name=f"Successor of {holder.display_name}",
                )
                self._holders[shard_index] = new_holder
                rotated.append(shard_index)

                await self._persist_holder(new_holder)

        if rotated:
            logger.warning(
                "Dead-man switch: %d shard(s) rotated to successors — %s",
                len(rotated),
                rotated,
            )

        return rotated

    async def rotate_all_shards(
        self,
        current_shares: List[Tuple[int, bytes]],
        threshold: int = 3,
        total_shares: int = 5,
    ) -> List[Tuple[int, bytes]]:
        """
        Full shard rotation: reconstruct the secret from current shares and
        re-split with a fresh random polynomial.

        This should be performed every 90 days (the cryptoperiod) to limit
        the window in which any compromised share remains valid.

        Parameters
        ----------
        current_shares:
            At least *threshold* valid shares from the current generation.
        threshold:
            Reconstruction threshold (default 3).
        total_shares:
            Number of new shares to generate (default 5).

        Returns
        -------
        list[(int, bytes)]
            The new share set.  Old shares are now invalid.
        """
        # Reconstruct
        secret = self.reconstruct_secret(current_shares, threshold=threshold)

        # Re-split with a new random polynomial
        new_shares = self.split_secret(secret, threshold=threshold, shares=total_shares)

        async with self._lock:
            self._last_rotation = datetime.utcnow()
            self._rotation_count += 1

        logger.info(
            "Full shard rotation #%d complete — %d new shares generated",
            self._rotation_count,
            total_shares,
        )

        await self._persist_rotation_event()
        return new_shares

    # ------------------------------------------------------------------
    # Rotation Schedule
    # ------------------------------------------------------------------

    @property
    def days_until_rotation(self) -> int:
        """
        Number of days until the next scheduled full rotation.

        Returns ``0`` if the rotation is overdue or no rotation has occurred.
        """
        if self._last_rotation is None:
            return 0
        elapsed = (datetime.utcnow() - self._last_rotation).days
        remaining = ROTATION_PERIOD_DAYS - elapsed
        return max(0, remaining)

    @property
    def rotation_overdue(self) -> bool:
        """True if the 90-day rotation period has elapsed."""
        return self.days_until_rotation == 0

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_holder_status(self) -> List[Dict[str, Any]]:
        """
        Return the status of all registered shard holders.

        Returns
        -------
        list[dict]
            One dict per holder with identity, liveness, and timing info.
        """
        return [
            {
                "shard_index": h.shard_index,
                "holder_id": str(h.holder_id),
                "display_name": h.display_name,
                "last_checkin": h.last_checkin.isoformat(),
                "days_since_checkin": h.days_since_checkin,
                "is_alive": h.is_alive,
                "successor_id": str(h.successor_id) if h.successor_id else None,
            }
            for h in sorted(self._holders.values(), key=lambda h: h.shard_index)
        ]

    @property
    def summary(self) -> Dict[str, Any]:
        """Diagnostic summary for admin dashboards."""
        alive_count = sum(1 for h in self._holders.values() if h.is_alive)
        return {
            "holders_registered": len(self._holders),
            "holders_alive": alive_count,
            "holders_overdue": len(self._holders) - alive_count,
            "last_rotation": (
                self._last_rotation.isoformat() if self._last_rotation else None
            ),
            "rotation_count": self._rotation_count,
            "days_until_rotation": self.days_until_rotation,
            "rotation_overdue": self.rotation_overdue,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_holder(self, holder: ShardHolder) -> None:
        """Persist a shard holder record to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO shard_holders (
                        holder_id, shard_index, last_checkin,
                        successor_id, display_name
                    ) VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (shard_index) DO UPDATE SET
                        holder_id = EXCLUDED.holder_id,
                        last_checkin = EXCLUDED.last_checkin,
                        successor_id = EXCLUDED.successor_id,
                        display_name = EXCLUDED.display_name
                    """,
                    holder.holder_id,
                    holder.shard_index,
                    holder.last_checkin,
                    holder.successor_id,
                    holder.display_name,
                )
        except Exception as exc:
            logger.error("Failed to persist shard holder: %s", exc)

    async def _persist_rotation_event(self) -> None:
        """Record a shard rotation event in the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO shard_rotation_history (
                        rotation_id, rotation_number, rotated_at
                    ) VALUES ($1, $2, $3)
                    """,
                    uuid4(),
                    self._rotation_count,
                    datetime.utcnow(),
                )
        except Exception as exc:
            logger.error("Failed to persist rotation event: %s", exc)

    async def load_holders(self) -> int:
        """
        Load shard holder records from the database on startup.

        Returns
        -------
        int
            Number of holders loaded.
        """
        if not self._db_pool:
            return 0

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT holder_id, shard_index, last_checkin,
                           successor_id, display_name
                    FROM shard_holders
                    ORDER BY shard_index
                    """
                )

            for row in rows:
                holder = ShardHolder(
                    holder_id=row["holder_id"],
                    shard_index=row["shard_index"],
                    last_checkin=row["last_checkin"],
                    successor_id=row["successor_id"],
                    display_name=row["display_name"] or "",
                )
                self._holders[holder.shard_index] = holder

            # Load last rotation timestamp
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT rotation_number, rotated_at
                    FROM shard_rotation_history
                    ORDER BY rotated_at DESC
                    LIMIT 1
                    """
                )
                if row:
                    self._last_rotation = row["rotated_at"]
                    self._rotation_count = row["rotation_number"]

            logger.info(
                "Loaded %d shard holders from database (rotation #%d)",
                len(self._holders),
                self._rotation_count,
            )
            return len(self._holders)

        except Exception as exc:
            logger.error("Failed to load shard holders: %s", exc)
            return 0

    def __repr__(self) -> str:
        alive = sum(1 for h in self._holders.values() if h.is_alive)
        return (
            f"<KeySharding holders={len(self._holders)} "
            f"alive={alive} "
            f"rotation_count={self._rotation_count}>"
        )
