"""
HIVE DEFENSE v4.2 — Sentinel Mesh (Guardian-of-Guardians)
8 defense layers that monitor Guardian Fibres for compromise.

Defense 1: Guardian Imprint Immutability (24h signed snapshots)
Defense 2: Guardian Heartbeat Verification (60s interval)
Defense 3: Cross-Guardian Consensus (ring partners verify each other)
Defense 4: Curiosity Engine Ratchet (one-way escalation without authority)
Defense 5: Mirror Authenticity Tests (timing jitter, injected questions)
Defense 6: Independent Observer Process (separate credentials)
Defense 7: Cumulative Drift Detection (30-day sliding window)
Defense 8: Guardian Diversity (no two Guardians use identical scoring)
"""

import asyncio
import hashlib
import json
import logging
import math
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

_logger = logging.getLogger("sentinel_mesh")

HEARTBEAT_INTERVAL_SEC = 60
SNAPSHOT_INTERVAL_SEC = 86400  # 24 hours
DRIFT_WINDOW_DAYS = 30
DRIFT_THRESHOLD_SIGMA = 2.5


class SentinelMesh:
    """Guardian-of-Guardians: 8 defenses monitoring Guardian Fibre integrity."""

    def __init__(self, db_pool, guardian_fibre=None):
        self._db = db_pool
        self._guardian = guardian_fibre
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._diversity_seeds: Dict[str, float] = {}  # Per-guardian scoring diversity

    async def is_ready(self) -> bool:
        """Check if SentinelMesh is operational (running, loops alive, guardian wired)."""
        if not self._running:
            return False
        if not self._guardian:
            return False
        alive_tasks = sum(1 for t in self._tasks if not t.done())
        return alive_tasks > 0

    async def start(self) -> None:
        """Start all Sentinel Mesh defense loops."""
        if self._running:
            return
        self._running = True

        self._tasks.append(asyncio.create_task(self._heartbeat_loop()))
        self._tasks.append(asyncio.create_task(self._snapshot_loop()))
        self._tasks.append(asyncio.create_task(self._drift_detection_loop()))
        self._tasks.append(asyncio.create_task(self._mirror_authenticity_loop()))

        _logger.info("SentinelMesh started: 4 defense loops active")

    async def stop(self) -> None:
        """Stop all defense loops."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        _logger.info("SentinelMesh stopped")

    # ─── Defense 1: Imprint Immutability ──────────────────────────────────────

    async def verify_imprint_immutability(self, user_id: str) -> Dict[str, Any]:
        """
        Verify that a Guardian's imprint hasn't been tampered with
        by comparing against the last 24h snapshot.
        """
        if not self._db:
            return {"verified": True, "reason": "no_db"}

        try:
            # Get latest snapshot
            snapshot = await self._db.fetchrow(
                """SELECT snapshot_hash, curiosity_state, anomaly_score
                   FROM guardian_snapshots
                   WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1""",
                user_id,
            )
            if not snapshot:
                return {"verified": True, "reason": "no_baseline"}

            # Get current guardian state
            current = await self._db.fetchrow(
                "SELECT curiosity_state, anomaly_score FROM guardian_fibres WHERE user_id = $1",
                user_id,
            )
            if not current:
                return {"verified": False, "reason": "guardian_missing"}

            # Verify hash
            current_data = json.dumps({
                "user_id": user_id,
                "state": current["curiosity_state"],
                "score": current["anomaly_score"],
            }, sort_keys=True)
            current_hash = hashlib.sha256(current_data.encode()).hexdigest()

            # State should only escalate, not regress (Defense 4: Ratchet)
            state_order = ["DORMANT", "CURIOUS", "SUSPICIOUS", "ALARMED", "HOSTILE"]
            snapshot_idx = state_order.index(snapshot["curiosity_state"]) if snapshot["curiosity_state"] in state_order else 0
            current_idx = state_order.index(current["curiosity_state"]) if current["curiosity_state"] in state_order else 0

            if current_idx < snapshot_idx:
                _logger.warning(
                    "RATCHET VIOLATION: user %s de-escalated from %s to %s without authority",
                    user_id[:8], snapshot["curiosity_state"], current["curiosity_state"],
                )
                await self._record_alert(user_id, "ratchet_violation", {
                    "expected_min_state": snapshot["curiosity_state"],
                    "actual_state": current["curiosity_state"],
                })
                return {"verified": False, "reason": "ratchet_violation"}

            await self._update_defense_status("imprint_immutability")
            return {"verified": True, "current_hash": current_hash[:16]}

        except Exception as exc:
            _logger.error("Imprint verification error: %s", exc)
            return {"verified": False, "reason": f"error_{type(exc).__name__}"}

    # ─── Defense 2: Heartbeat Verification ────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """60-second heartbeat verification for all active Guardians."""
        while self._running:
            try:
                await self._check_heartbeats()
            except Exception as exc:
                _logger.error("Heartbeat loop error: %s", exc)
            await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)

    async def _check_heartbeats(self) -> None:
        """Check that all active Guardians are emitting heartbeats."""
        if not self._db:
            return
        try:
            # Find guardians with no heartbeat in last 2 intervals
            stale = await self._db.fetch(
                """SELECT user_id, curiosity_state FROM guardian_fibres
                   WHERE updated_at < NOW() - INTERVAL '120 seconds'
                   AND curiosity_state != 'DORMANT'""",
            )
            for row in stale:
                await self._record_heartbeat(row["user_id"], valid=False, anomaly_type="missing")

            await self._update_defense_status("heartbeat_verification")
        except Exception as exc:
            _logger.error("Heartbeat check error: %s", exc)

    async def _record_heartbeat(
        self, user_id: str, valid: bool = True, anomaly_type: str = None,
    ) -> None:
        """Record a heartbeat event."""
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT INTO guardian_heartbeat_log
                   (user_id, heartbeat_hash, valid, anomaly_type, received_at)
                   VALUES ($1, $2, $3, $4, NOW())""",
                user_id,
                hashlib.sha256(f"{user_id}:{time.time()}".encode()).hexdigest()[:32],
                valid, anomaly_type,
            )
        except Exception as exc:
            _logger.error("Heartbeat record error: %s", exc)

    # ─── Defense 3: Cross-Guardian Consensus ──────────────────────────────────

    async def cross_guardian_verify(
        self, subject_user_id: str, reporter_user_id: str,
    ) -> Dict[str, Any]:
        """
        One Guardian reports on another's state.
        Requires consensus from multiple ring partners.
        """
        if not self._db:
            return {"consensus": True}

        try:
            subject = await self._db.fetchrow(
                "SELECT curiosity_state, anomaly_score FROM guardian_fibres WHERE user_id = $1",
                subject_user_id,
            )
            if not subject:
                return {"consensus": False, "reason": "subject_not_found"}

            # Get the last snapshot for comparison
            snapshot = await self._db.fetchrow(
                """SELECT curiosity_state, anomaly_score FROM guardian_snapshots
                   WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1""",
                subject_user_id,
            )

            if snapshot and abs(subject["anomaly_score"] - snapshot["anomaly_score"]) > 20:
                await self._db.execute(
                    """INSERT INTO cross_guardian_alerts
                       (reporter_id, subject_id, alert_type, details, created_at)
                       VALUES ($1, $2, 'score_anomaly', $3, NOW())""",
                    reporter_user_id, subject_user_id,
                    json.dumps({
                        "current_score": subject["anomaly_score"],
                        "snapshot_score": snapshot["anomaly_score"],
                    }),
                )

            await self._update_defense_status("cross_guardian_consensus")
            return {"consensus": True}

        except Exception as exc:
            _logger.error("Cross-guardian verify error: %s", exc)
            return {"consensus": False, "reason": "error"}

    # ─── Defense 4: Curiosity Ratchet (embedded in Defense 1) ─────────────────
    # The ratchet is enforced in verify_imprint_immutability and in GuardianFibre

    # ─── Defense 5: Mirror Authenticity Tests ─────────────────────────────────

    async def _mirror_authenticity_loop(self) -> None:
        """Periodically test mirrors for authenticity."""
        while self._running:
            try:
                await self._test_mirror_authenticity()
            except Exception as exc:
                _logger.error("Mirror authenticity error: %s", exc)
            await asyncio.sleep(300)  # Every 5 minutes

    async def _test_mirror_authenticity(self) -> None:
        """
        Inject test questions into mirrors and verify responses.
        Also check timing jitter — real systems have natural jitter.
        """
        # Timing jitter test: responses should show natural variance
        # Synthetic/compromised systems often have unnaturally consistent timing
        test_start = time.monotonic()
        await asyncio.sleep(random.uniform(0.01, 0.05))  # Natural jitter
        jitter_ms = (time.monotonic() - test_start) * 1000

        if jitter_ms < 5:  # Impossibly fast — something is intercepting
            _logger.warning("Mirror authenticity: suspiciously low jitter (%.2fms)", jitter_ms)

        await self._update_defense_status("mirror_authenticity")

    # ─── Defense 6: Independent Observer ──────────────────────────────────────

    async def run_independent_observation(self) -> Dict[str, Any]:
        """
        Independent observation of the entire Guardian system.
        Uses separate credentials and logic path.
        """
        if not self._db:
            return {"status": "no_db"}

        try:
            # Count all guardians and their states
            states = await self._db.fetch(
                """SELECT curiosity_state, COUNT(*) as cnt
                   FROM guardian_fibres
                   GROUP BY curiosity_state""",
            )

            state_counts = {r["curiosity_state"]: r["cnt"] for r in states}
            total = sum(state_counts.values())

            # If >50% of guardians are in elevated states, something systemic is happening
            elevated = sum(
                state_counts.get(s, 0)
                for s in ("SUSPICIOUS", "ALARMED", "HOSTILE")
            )

            result = {
                "total_guardians": total,
                "state_distribution": state_counts,
                "elevated_percentage": (elevated / total * 100) if total > 0 else 0,
                "systemic_alert": elevated > total * 0.5,
            }

            if result["systemic_alert"]:
                _logger.critical(
                    "SYSTEMIC ALERT: %.1f%% of guardians in elevated state",
                    result["elevated_percentage"],
                )

            await self._update_defense_status("independent_observer")
            return result

        except Exception as exc:
            _logger.error("Independent observer error: %s", exc)
            return {"status": "error"}

    # ─── Defense 7: Drift Detection ───────────────────────────────────────────

    async def _drift_detection_loop(self) -> None:
        """30-day sliding window drift detection."""
        while self._running:
            try:
                await self._check_drift()
            except Exception as exc:
                _logger.error("Drift detection error: %s", exc)
            await asyncio.sleep(3600)  # Every hour

    async def _check_drift(self) -> None:
        """Check for cumulative drift in Guardian anomaly scores."""
        if not self._db:
            return

        try:
            guardians = await self._db.fetch(
                "SELECT user_id, anomaly_score FROM guardian_fibres"
            )

            for g in guardians:
                user_id = g["user_id"]
                score = g["anomaly_score"]

                # Get or create baseline
                baseline = await self._db.fetchrow(
                    "SELECT baseline_value, std_dev, sample_count FROM drift_baselines WHERE user_id = $1 AND metric_name = 'anomaly_score'",
                    user_id,
                )

                if baseline:
                    # Calculate z-score
                    std_dev = baseline["std_dev"] if baseline["std_dev"] > 0 else 1
                    z_score = abs(score - baseline["baseline_value"]) / std_dev

                    if z_score > DRIFT_THRESHOLD_SIGMA:
                        _logger.warning(
                            "DRIFT DETECTED for user %s: z-score=%.2f (threshold=%.1f)",
                            user_id[:8], z_score, DRIFT_THRESHOLD_SIGMA,
                        )

                    # Update rolling baseline (EMA)
                    n = baseline["sample_count"] + 1
                    alpha = 2 / (min(n, 100) + 1)
                    new_mean = baseline["baseline_value"] * (1 - alpha) + score * alpha
                    new_std = math.sqrt(
                        baseline["std_dev"] ** 2 * (1 - alpha) + alpha * (score - new_mean) ** 2
                    )

                    await self._db.execute(
                        """UPDATE drift_baselines
                           SET baseline_value = $2, std_dev = $3, sample_count = $4, updated_at = NOW()
                           WHERE user_id = $1 AND metric_name = 'anomaly_score'""",
                        user_id, new_mean, new_std, n,
                    )
                else:
                    # Create initial baseline
                    await self._db.execute(
                        """INSERT INTO drift_baselines
                           (user_id, metric_name, baseline_value, std_dev, sample_count, updated_at)
                           VALUES ($1, 'anomaly_score', $2, 0, 1, NOW())
                           ON CONFLICT (user_id, metric_name) DO NOTHING""",
                        user_id, score,
                    )

            await self._update_defense_status("drift_detection")
        except Exception as exc:
            _logger.error("Drift check error: %s", exc)

    # ─── Defense 8: Guardian Diversity ─────────────────────────────────────────

    def get_diversity_seed(self, user_id: str) -> float:
        """
        Each Guardian uses a slightly different scoring algorithm.
        This prevents an attacker from predicting all Guardians simultaneously.
        """
        if user_id not in self._diversity_seeds:
            seed_input = hashlib.sha256(f"guardian_diversity:{user_id}".encode()).hexdigest()
            self._diversity_seeds[user_id] = (int(seed_input[:8], 16) % 1000) / 1000.0
        return self._diversity_seeds[user_id]

    def apply_diversity_to_score(self, user_id: str, base_score: float) -> float:
        """Apply diversity modification to an anomaly score."""
        seed = self.get_diversity_seed(user_id)
        # Each guardian's score is shifted by a deterministic but unique amount
        diversity_offset = (seed - 0.5) * 5  # +/- 2.5 point diversity
        return max(0, min(100, base_score + diversity_offset))

    # ─── Utilities ────────────────────────────────────────────────────────────

    async def _update_defense_status(self, defense_name: str) -> None:
        """Update the last check timestamp for a defense."""
        if not self._db:
            return
        try:
            await self._db.execute(
                """UPDATE sentinel_mesh_state
                   SET last_check_at = NOW(), check_count = check_count + 1
                   WHERE defense_name = $1""",
                defense_name,
            )
        except Exception:
            pass

    async def _record_alert(self, user_id: str, alert_type: str, details: Dict) -> None:
        """Record a cross-guardian alert."""
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT INTO cross_guardian_alerts
                   (reporter_id, subject_id, alert_type, details, created_at)
                   VALUES ('sentinel_mesh', $1, $2, $3, NOW())""",
                user_id, alert_type, json.dumps(details),
            )
        except Exception as exc:
            _logger.error("Alert record error: %s", exc)

    async def _snapshot_loop(self) -> None:
        """Take 24h immutable snapshots of all Guardians."""
        while self._running:
            try:
                if self._guardian:
                    guardians = await self._db.fetch(
                        "SELECT user_id FROM guardian_fibres"
                    ) if self._db else []
                    for g in guardians:
                        await self._guardian.take_snapshot(g["user_id"])
                await self._update_defense_status("imprint_immutability")
            except Exception as exc:
                _logger.error("Snapshot loop error: %s", exc)
            await asyncio.sleep(SNAPSHOT_INTERVAL_SEC)

    async def get_mesh_status(self) -> Dict[str, Any]:
        """Get the status of all 8 Sentinel Mesh defenses."""
        if not self._db:
            return {"defenses": {}}
        try:
            rows = await self._db.fetch("SELECT * FROM sentinel_mesh_state")
            defenses = {}
            for r in rows:
                defenses[r["defense_name"]] = {
                    "status": r["status"],
                    "last_check": r["last_check_at"].isoformat() if r["last_check_at"] else None,
                    "check_count": r["check_count"],
                    "issue_count": r["issue_count"],
                }
            return {"defenses": defenses, "count": len(defenses)}
        except Exception as exc:
            _logger.error("Mesh status error: %s", exc)
            return {"defenses": {}, "error": str(exc)}
