"""
HIVE DEFENSE PROTOCOL v3.1 — Trinity Helix (Phase 8D)
The rotating 3×3×3 verification cube at the core of the Hive's identity
verification architecture.

The Trinity Helix is a nine-sub-cord verification matrix organised into
three tiers of three:

    TIER 1 — INTUITIVE
        1a  pattern_recognition     → Curiosity Protocol
        1b  contextual_assessment   → Mirror Reflection
        1c  anomaly_intuition       → Cumulative Drift Scorer

    TIER 2 — MATHEMATICAL
        2a  mathematical_verification → Heartbeat + Coherence Gate
        2b  statistical_verification  → Payload Entropy Analyzer
        2c  structural_verification   → Content Sentinel + Conservation Ledger

    TIER 3 — TEMPORAL-SPATIAL-BEHAVIORAL
        3a  temporal_verification   → Temporal Jitter + Response Normalization
        3b  spatial_verification    → Network Topology Fingerprint
        3c  behavioral_verification → Behavioral Snapshot

The sub-cords are continuously rotated into a new sequence derived from
three entropy sources:
    1. Coherence state hash (Nevedal engine C_emo output)
    2. HSM random bytes (os.urandom(32))
    3. Nanosecond-precision monotonic time

Legitimate traffic passes in ~5ms because it possesses all nine
credentials; the rotation interval (50–500ms, itself entropy-derived)
is never a constraint for valid signals.

If the sequence rotates mid-verification → RESTART.
If any gate fails → INVERT_TO_TRIANGLE (triangular mirror space).
All 9 gates pass → PASS_TO_REAL.

Patent-Pending — Claims 48-49
    Claim 48: "A verification method employing a rotating 3×3×3 cube of
               nine sub-cord gates whose sequence is derived from combined
               entropy of coherence state, hardware random, and nanosecond
               time."
    Claim 49: "The method of Claim 48 wherein legitimate traffic passes
               all nine gates within a single rotation window (~5ms) and
               failed signals are inverted into a triangular mirror space
               rather than rejected outward."

© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from app.models.hive_defense import (
    HelixState,
    HelixVerdict,
    InvertedSpace,
)

logger = logging.getLogger("hive.trinity_helix")


# =============================================================================
# SUB-CORD DEFINITIONS
# =============================================================================

# Canonical names in tier order — indices 0-8 map to permutation slots
SUB_CORDS: List[str] = [
    "pattern_recognition",       # 1a — Curiosity Protocol
    "contextual_assessment",     # 1b — Mirror Reflection
    "anomaly_intuition",         # 1c — Cumulative Drift Scorer
    "mathematical_verification", # 2a — Heartbeat + Coherence Gate
    "statistical_verification",  # 2b — Payload Entropy Analyzer
    "structural_verification",   # 2c — Content Sentinel + Conservation Ledger
    "temporal_verification",     # 3a — Temporal Jitter + Response Normalization
    "spatial_verification",      # 3b — Network Topology Fingerprint
    "behavioral_verification",   # 3c — Behavioral Snapshot
]

# Convenience mapping from index to sub-cord name
INDEX_TO_SUB_CORD: Dict[int, str] = {i: name for i, name in enumerate(SUB_CORDS)}
SUB_CORD_TO_INDEX: Dict[str, int] = {name: i for i, name in enumerate(SUB_CORDS)}

# Rotation interval bounds (milliseconds)
MIN_ROTATION_INTERVAL_MS: float = 50.0
MAX_ROTATION_INTERVAL_MS: float = 500.0


# =============================================================================
# VERIFICATION CONTEXT
# =============================================================================

@dataclass
class VerificationContext:
    """
    Context object passed through the nine-gate verification pipeline.

    Carries the signal under test and accumulates per-gate results
    so that the TrinityHelix can make a single atomic verdict.
    """
    signal: Dict[str, Any]
    sequence_snapshot: List[int] = field(default_factory=list)
    gate_results: List[Tuple[str, bool]] = field(default_factory=list)
    started_at_ns: int = 0
    verdict: Optional[HelixVerdict] = None
    failed_gate: Optional[str] = None


# =============================================================================
# TRINITY HELIX
# =============================================================================

class TrinityHelix:
    """
    Rotating 3×3×3 verification cube — the core of Phase 8D.

    The helix maintains a continuously rotating permutation of nine
    sub-cord gates.  Each incoming signal must pass all nine gates in
    the current sequence order.  If the sequence rotates while a
    verification is in progress, the verification restarts.  If any
    gate fails, the signal is *inverted* into a triangular mirror space
    (not rejected outward) to contain and study the attacker.

    Parameters
    ----------
    rotation_engine : object
        ``HelixRotationEngine`` responsible for entropy gathering,
        Fisher-Yates permutation, and interval derivation.
    sub_cord_router : object
        ``HelixSubCordRouter`` that maps sub-cord names to their
        actual verification functions.
    triangular_inversion : object, optional
        ``TriangularMirrorInversion`` service that handles failed-signal
        containment.  If *None*, failed signals are logged but not
        actively contained.
    forensic_logger : object, optional
        Shared ``ForensicLogger`` instance for immutable evidence chain.
    db_pool : object, optional
        asyncpg connection pool for state persistence.

    Patent Ref: Claims 48-49.
    """

    def __init__(
        self,
        rotation_engine=None,
        sub_cord_router=None,
        triangular_inversion=None,
        forensic_logger=None,
        db_pool=None,
    ) -> None:
        self._rotation_engine = rotation_engine
        self._sub_cord_router = sub_cord_router
        self._triangular_inversion = triangular_inversion
        self._forensic_logger = forensic_logger
        self._db_pool = db_pool

        # Current helix state — sequence + interval + metadata
        self._state: HelixState = HelixState(
            current_sequence=list(range(9)),
            rotation_interval_ms=200.0,
            rotation_count=0,
            last_rotation_ns=time.monotonic_ns(),
            entropy_sources_healthy=True,
        )

        # Metrics
        self._total_verifications: int = 0
        self._total_passes: int = 0
        self._total_inversions: int = 0
        self._total_restarts: int = 0

        logger.info(
            ">>> [TRINITY_HELIX] Initialized — 9 sub-cords, "
            "initial interval=%.0fms",
            self._state.rotation_interval_ms,
        )

    # ─── Properties ──────────────────────────────────────────────────────

    @property
    def state(self) -> HelixState:
        """Access the current HelixState (read-only snapshot)."""
        return self._state

    @property
    def metrics(self) -> Dict[str, Any]:
        """Return verification metrics for admin dashboard."""
        return {
            "total_verifications": self._total_verifications,
            "total_passes": self._total_passes,
            "total_inversions": self._total_inversions,
            "total_restarts": self._total_restarts,
            "pass_rate": round(
                self._total_passes / max(self._total_verifications, 1), 4
            ),
            "rotation_count": self._state.rotation_count,
            "rotation_interval_ms": self._state.rotation_interval_ms,
            "entropy_healthy": self._state.entropy_sources_healthy,
            "current_sequence": self._state.current_sequence,
        }

    # ─── Core Verification ───────────────────────────────────────────────

    async def verify_signal(self, signal: Dict[str, Any]) -> HelixVerdict:
        """
        Verify an incoming signal through the nine-gate helix.

        Algorithm:
            1. Snapshot the current sequence (and rotation deadline).
            2. Iterate all 9 sub-cords in the snapshot order.
            3. Before each gate check whether the sequence has rotated
               since the snapshot — if so, return RESTART_ROTATION.
            4. If any gate fails, return INVERT_TO_TRIANGLE and hand
               the signal to TriangularMirrorInversion.
            5. If all 9 pass, return PASS_TO_REAL.

        Parameters
        ----------
        signal : dict
            The signal payload to verify.  The sub-cord router
            interprets its contents.

        Returns
        -------
        HelixVerdict
            One of PASS_TO_REAL, INVERT_TO_TRIANGLE, or RESTART_ROTATION.
        """
        start_ns = time.monotonic_ns()
        self._total_verifications += 1

        # 1. Snapshot current state
        sequence = await self.get_current_sequence()
        snapshot = list(sequence)

        ctx = VerificationContext(
            signal=signal,
            sequence_snapshot=snapshot,
            started_at_ns=start_ns,
        )

        # 2. Iterate gates in sequence order
        for idx in snapshot:
            sub_cord_name = INDEX_TO_SUB_CORD[idx]

            # 3. Check rotation hasn't occurred since snapshot
            if self._state.current_sequence != snapshot:
                ctx.verdict = HelixVerdict.RESTART_ROTATION
                self._total_restarts += 1
                elapsed_us = (time.monotonic_ns() - start_ns) / 1_000
                logger.info(
                    ">>> [TRINITY_HELIX] RESTART — sequence rotated mid-"
                    "verification at gate '%s' (%.1fμs)",
                    sub_cord_name,
                    elapsed_us,
                )
                await self._log_verdict(ctx)
                return HelixVerdict.RESTART_ROTATION

            # 4. Run the sub-cord gate
            passed = await self._run_gate(sub_cord_name, signal)
            ctx.gate_results.append((sub_cord_name, passed))

            if not passed:
                ctx.verdict = HelixVerdict.INVERT_TO_TRIANGLE
                ctx.failed_gate = sub_cord_name
                self._total_inversions += 1

                elapsed_us = (time.monotonic_ns() - start_ns) / 1_000
                logger.warning(
                    ">>> [TRINITY_HELIX] INVERT — gate '%s' failed "
                    "(%.1fμs elapsed)",
                    sub_cord_name,
                    elapsed_us,
                )

                # Hand off to triangular inversion
                await self._invert_signal(signal, sub_cord_name)
                await self._log_verdict(ctx)
                return HelixVerdict.INVERT_TO_TRIANGLE

        # 5. All 9 gates passed
        ctx.verdict = HelixVerdict.PASS_TO_REAL
        self._total_passes += 1

        elapsed_us = (time.monotonic_ns() - start_ns) / 1_000
        logger.debug(
            ">>> [TRINITY_HELIX] PASS — all 9 gates cleared (%.1fμs)",
            elapsed_us,
        )
        await self._log_verdict(ctx)
        return HelixVerdict.PASS_TO_REAL

    # ─── Sequence Management ─────────────────────────────────────────────

    async def get_current_sequence(self) -> List[int]:
        """
        Return the current sub-cord permutation, rotating first if the
        interval has elapsed.

        The method checks whether enough time has passed since the last
        rotation (based on ``rotation_interval_ms``).  If so, it calls
        ``_rotate()`` to produce a new permutation and interval before
        returning the updated sequence.

        Returns
        -------
        list[int]
            Current ordered list of sub-cord indices (0-8).
        """
        now_ns = time.monotonic_ns()
        elapsed_ms = (now_ns - self._state.last_rotation_ns) / 1_000_000

        if elapsed_ms >= self._state.rotation_interval_ms:
            await self._rotate()

        return list(self._state.current_sequence)

    async def _rotate(self) -> None:
        """
        Rotate the helix — produce a new permutation and interval.

        Uses the HelixRotationEngine to:
            1. Gather combined entropy (coherence hash + HSM random +
               nanosecond time).
            2. Generate a Fisher-Yates permutation of 0-8.
            3. Derive a new rotation interval (50-500ms).

        If no rotation engine is available, falls back to a local
        entropy-based rotation.
        """
        if self._rotation_engine:
            try:
                result = await self._rotation_engine.rotate()
                self._state.current_sequence = result["new_sequence"]
                self._state.rotation_interval_ms = result["new_interval_ms"]
                self._state.rotation_count += 1
                self._state.last_rotation_ns = time.monotonic_ns()
                self._state.entropy_sources_healthy = result.get(
                    "entropy_healthy", True
                )

                logger.debug(
                    ">>> [TRINITY_HELIX] Rotated (#%d) — new interval=%.0fms "
                    "sequence=%s",
                    self._state.rotation_count,
                    self._state.rotation_interval_ms,
                    self._state.current_sequence,
                )
                return
            except Exception as exc:
                logger.error(
                    ">>> [TRINITY_HELIX] Rotation engine failed: %s — "
                    "falling back to local entropy",
                    exc,
                )

        # Fallback: local Fisher-Yates using os.urandom
        await self._rotate_local()

    async def _rotate_local(self) -> None:
        """
        Local fallback rotation using os.urandom + nanosecond time.

        Produces a Fisher-Yates shuffle of 0-8 using SHA-256 of combined
        entropy as the random source.
        """
        import hashlib

        entropy = (
            os.urandom(32)
            + time.monotonic_ns().to_bytes(8, "big")
        )
        digest = hashlib.sha256(entropy).digest()

        # Fisher-Yates shuffle using entropy bytes
        perm = list(range(9))
        for i in range(8, 0, -1):
            j = digest[i % len(digest)] % (i + 1)
            perm[i], perm[j] = perm[j], perm[i]

        # Derive interval from bytes 24-28
        interval_raw = int.from_bytes(digest[24:28], "big")
        interval_ms = (
            MIN_ROTATION_INTERVAL_MS
            + (interval_raw % int(MAX_ROTATION_INTERVAL_MS - MIN_ROTATION_INTERVAL_MS + 1))
        )

        self._state.current_sequence = perm
        self._state.rotation_interval_ms = interval_ms
        self._state.rotation_count += 1
        self._state.last_rotation_ns = time.monotonic_ns()

        logger.debug(
            ">>> [TRINITY_HELIX] Local rotation (#%d) — interval=%.0fms "
            "sequence=%s",
            self._state.rotation_count,
            interval_ms,
            perm,
        )

    # ─── Gate Execution ──────────────────────────────────────────────────

    async def _run_gate(self, sub_cord_name: str, signal: Dict[str, Any]) -> bool:
        """
        Execute a single sub-cord gate verification.

        Delegates to the ``HelixSubCordRouter`` if available; otherwise
        returns True (fail-open for development environments).

        Parameters
        ----------
        sub_cord_name : str
            One of the 9 canonical sub-cord names.
        signal : dict
            The signal payload under test.

        Returns
        -------
        bool
            True if the gate passes, False otherwise.
        """
        if self._sub_cord_router:
            try:
                return await self._sub_cord_router.run_sub_cord(
                    sub_cord_name, signal
                )
            except Exception as exc:
                logger.error(
                    ">>> [TRINITY_HELIX] Gate '%s' raised exception: %s",
                    sub_cord_name,
                    exc,
                )
                return False

        # No router — fail-open (development only)
        return True

    # ─── Triangular Inversion ────────────────────────────────────────────

    async def _invert_signal(
        self,
        signal: Dict[str, Any],
        failed_gate: str,
    ) -> Optional[InvertedSpace]:
        """
        Invert a failed signal into a triangular mirror space.

        Parameters
        ----------
        signal : dict
            The signal that failed verification.
        failed_gate : str
            The sub-cord gate name that the signal failed.

        Returns
        -------
        InvertedSpace or None
            The created inversion space, or None if no inversion engine
            is available.
        """
        if not self._triangular_inversion:
            logger.warning(
                ">>> [TRINITY_HELIX] No triangular inversion engine — "
                "failed signal at gate '%s' dropped",
                failed_gate,
            )
            return None

        try:
            space = await self._triangular_inversion.invert(
                failed_signal=signal,
                failed_gate=failed_gate,
                helix_state=self._state,
            )
            logger.info(
                ">>> [TRINITY_HELIX] Signal inverted into space %s "
                "(failed gate: %s)",
                space.space_id,
                failed_gate,
            )
            return space
        except Exception as exc:
            logger.error(
                ">>> [TRINITY_HELIX] Triangular inversion failed: %s", exc
            )
            return None

    # ─── Forensic Logging ────────────────────────────────────────────────

    async def _log_verdict(self, ctx: VerificationContext) -> None:
        """
        Log a verification verdict to the forensic chain.

        Only non-PASS verdicts are logged to avoid write amplification.
        PASS verdicts are recorded in metrics only.
        """
        if ctx.verdict == HelixVerdict.PASS_TO_REAL:
            return  # Metrics only

        if not self._forensic_logger:
            return

        try:
            elapsed_ns = time.monotonic_ns() - ctx.started_at_ns
            await self._forensic_logger.log_event(
                event_type=f"hive.helix.{ctx.verdict.value}",
                source_entity="trinity_helix",
                evidence={
                    "verdict": ctx.verdict.value,
                    "failed_gate": ctx.failed_gate,
                    "gate_results": [
                        {"gate": name, "passed": passed}
                        for name, passed in ctx.gate_results
                    ],
                    "sequence_snapshot": ctx.sequence_snapshot,
                    "rotation_count": self._state.rotation_count,
                    "elapsed_ns": elapsed_ns,
                },
            )
        except Exception as exc:
            logger.error(
                ">>> [TRINITY_HELIX] Forensic log failed: %s", exc
            )

    # ─── Persistence ─────────────────────────────────────────────────────

    async def persist_state(self) -> None:
        """
        Persist the current HelixState to the database for crash recovery.
        """
        if not self._db_pool:
            return
        try:
            import json
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_helix_state
                        (state_key, current_sequence, rotation_interval_ms,
                         rotation_count, entropy_healthy, updated_at)
                    VALUES ('primary', $1, $2, $3, $4, NOW())
                    ON CONFLICT (state_key)
                    DO UPDATE SET
                        current_sequence = EXCLUDED.current_sequence,
                        rotation_interval_ms = EXCLUDED.rotation_interval_ms,
                        rotation_count = EXCLUDED.rotation_count,
                        entropy_healthy = EXCLUDED.entropy_healthy,
                        updated_at = NOW()
                    """,
                    json.dumps(self._state.current_sequence),
                    self._state.rotation_interval_ms,
                    self._state.rotation_count,
                    self._state.entropy_sources_healthy,
                )
        except Exception as exc:
            logger.error(
                ">>> [TRINITY_HELIX] State persistence failed: %s", exc
            )

    async def load_state(self) -> bool:
        """
        Load persisted HelixState from the database on startup.

        Returns
        -------
        bool
            True if state was successfully restored.
        """
        if not self._db_pool:
            return False
        try:
            import json
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM hive_helix_state WHERE state_key = 'primary'"
                )
            if row:
                self._state.current_sequence = json.loads(
                    row["current_sequence"]
                )
                self._state.rotation_interval_ms = row["rotation_interval_ms"]
                self._state.rotation_count = row["rotation_count"]
                self._state.entropy_sources_healthy = row["entropy_healthy"]
                self._state.last_rotation_ns = time.monotonic_ns()
                logger.info(
                    ">>> [TRINITY_HELIX] State restored — rotation #%d",
                    self._state.rotation_count,
                )
                return True
        except Exception as exc:
            logger.error(
                ">>> [TRINITY_HELIX] State load failed: %s", exc
            )
        return False

    # ─── Admin ───────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """
        Full diagnostic summary for the admin dashboard.
        """
        return {
            "helix_state": {
                "current_sequence": self._state.current_sequence,
                "rotation_interval_ms": self._state.rotation_interval_ms,
                "rotation_count": self._state.rotation_count,
                "entropy_healthy": self._state.entropy_sources_healthy,
            },
            "metrics": self.metrics,
            "sub_cords": SUB_CORDS,
        }

    def __repr__(self) -> str:
        return (
            f"<TrinityHelix rotations={self._state.rotation_count} "
            f"verified={self._total_verifications} "
            f"passes={self._total_passes} "
            f"inversions={self._total_inversions}>"
        )
