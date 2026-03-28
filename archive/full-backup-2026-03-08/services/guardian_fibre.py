"""
HIVE DEFENSE v4.0 — Guardian Fibre
Per-user behavioral sentinel with 5-state Curiosity Engine.

States: DORMANT → CURIOUS → SUSPICIOUS → ALARMED → HOSTILE
Score bands: 0-15 | 15-40 | 40-65 | 65-85 | 85-100

The Guardian Fibre is imprinted at first authenticated login and enters a
7-day learning period. After learning, it actively monitors behavioral
divergence and escalates through curiosity states.
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from .guardian_imprint import DeviceImprint

_logger = logging.getLogger("guardian_fibre")

LEARNING_PERIOD_DAYS = 7


class GuardianState(str, Enum):
    """5-state curiosity engine for Guardian Fibre."""
    DORMANT = "DORMANT"       # 0-15: normal behavior
    CURIOUS = "CURIOUS"       # 15-40: mild anomaly, shadow session starts
    SUSPICIOUS = "SUSPICIOUS" # 40-65: notable anomaly, masked data
    ALARMED = "ALARMED"       # 65-85: significant anomaly, synthetic data
    HOSTILE = "HOSTILE"       # 85-100: confirmed threat, containment


# Threshold boundaries for state transitions
STATE_THRESHOLDS = {
    GuardianState.DORMANT: (0, 15),
    GuardianState.CURIOUS: (15, 40),
    GuardianState.SUSPICIOUS: (40, 65),
    GuardianState.ALARMED: (65, 85),
    GuardianState.HOSTILE: (85, 100),
}


def score_to_state(score: float) -> GuardianState:
    """Convert anomaly score to guardian state."""
    if score >= 85:
        return GuardianState.HOSTILE
    elif score >= 65:
        return GuardianState.ALARMED
    elif score >= 40:
        return GuardianState.SUSPICIOUS
    elif score >= 15:
        return GuardianState.CURIOUS
    return GuardianState.DORMANT


class GuardianFibre:
    """Per-user Guardian Fibre with 5-state Curiosity Engine."""

    def __init__(self, db_pool):
        self._db = db_pool
        self._device_imprint = DeviceImprint(db_pool)

    async def is_ready(self) -> bool:
        """Check if GuardianFibre is operational (DB pool alive)."""
        try:
            if not self._db:
                return False
            async with self._db.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    async def imprint_on_login(
        self,
        user_id: str,
        device_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Called at every authenticated login. Creates or updates the Guardian.
        Returns guardian state + whether this is a new/unrecognized device.
        """
        guardian = await self._get_or_create_guardian(user_id)

        # Find or create device imprint
        existing_imprint = await self._device_imprint.find_matching_imprint(
            user_id,
            user_agent=device_info.get("user_agent", ""),
            timezone_str=device_info.get("timezone", ""),
            ip_geo_region=device_info.get("ip_geo_region", ""),
            screen_resolution=device_info.get("screen_resolution", ""),
        )

        new_device = existing_imprint is None
        if new_device:
            imprint_id = await self._device_imprint.create_imprint(
                user_id,
                device_type=device_info.get("device_type", "unknown"),
                user_agent=device_info.get("user_agent", ""),
                timezone_str=device_info.get("timezone", ""),
                ip_geo_region=device_info.get("ip_geo_region", ""),
                screen_resolution=device_info.get("screen_resolution", ""),
                language=device_info.get("language", ""),
            )
        else:
            imprint_id = existing_imprint["imprint_id"]

        # Score anomaly
        now = datetime.now(timezone.utc)
        anomaly_score = await self._device_imprint.score_anomaly(
            user_id,
            user_agent=device_info.get("user_agent", ""),
            timezone_str=device_info.get("timezone", ""),
            ip_geo_region=device_info.get("ip_geo_region", ""),
            login_hour=now.hour,
        )

        # New device during non-learning mode raises score
        learning = guardian.get("learning_mode", True)
        if new_device and not learning:
            anomaly_score = min(anomaly_score + 25, 100)

        # Update guardian state
        new_state = score_to_state(anomaly_score)
        old_state = guardian.get("curiosity_state", "DORMANT")

        # Sentinel mode: 1.5x sensitivity
        if guardian.get("sentinel_mode"):
            sentinel_until = guardian.get("sentinel_until")
            if sentinel_until and now < sentinel_until:
                anomaly_score = min(anomaly_score * 1.5, 100)
                new_state = score_to_state(anomaly_score)

        # One-way ratchet: state can only escalate (not de-escalate without authority)
        state_order = [s.value for s in GuardianState]
        if state_order.index(new_state.value) < state_order.index(old_state):
            new_state = GuardianState(old_state)

        await self._update_guardian(user_id, new_state.value, anomaly_score, imprint_id)

        return {
            "user_id": user_id,
            "guardian_state": new_state.value,
            "anomaly_score": anomaly_score,
            "new_device": new_device,
            "device_imprint_id": imprint_id,
            "learning_mode": learning,
            "requires_verification": new_device and not learning and anomaly_score > 25,
        }

    async def on_login(
        self, user_id: str, user_agent: str = "", timezone_str: str = "",
        ip_geo: str = "", screen_resolution: str = "", login_hour: int = 12,
    ) -> Dict[str, Any]:
        """Convenience wrapper for bridge_server login integration."""
        return await self.imprint_on_login(user_id, {
            "user_agent": user_agent,
            "timezone": timezone_str,
            "ip_geo_region": ip_geo,
            "screen_resolution": screen_resolution,
        })

    async def observe_request(
        self, user_id: str, message_type: str, payload_size: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Called on EVERY subsequent WebSocket message after login.
        Updates the behavioral model and adjusts anomaly score in real-time.

        Returns current guardian state and whether any action is required.
        """
        guardian = await self._get_guardian(user_id)
        if not guardian:
            return {"state": "DORMANT", "score": 0, "action": None}

        learning = guardian.get("learning_mode", True)
        current_score = guardian.get("anomaly_score", 0)
        now = datetime.now(timezone.utc)

        # Behavioral signals that increase score
        score_delta = 0.0

        # Signal 1: Unusual message frequency (rapid-fire)
        meta = metadata or {}
        msg_interval_ms = meta.get("interval_since_last_ms", 1000)
        if msg_interval_ms < 50:
            score_delta += 3.0  # Bot-like speed

        # Signal 2: Accessing crown-jewel endpoints
        crown_jewel_types = {
            "export_data", "download_vault", "bulk_export", "admin_override",
            "delete_account", "get_all_users", "get_encryption_keys",
        }
        if message_type in crown_jewel_types:
            score_delta += 5.0

        # Signal 3: Unusual session hours
        hour = now.hour
        if hour < 5 or hour > 23:
            score_delta += 1.0

        # Signal 4: Large payloads (potential data exfil)
        if payload_size > 50000:
            score_delta += 2.0

        # Signal 5: Rapid endpoint breadth (scanning behavior)
        endpoints_key = f"_endpoints_{user_id}"
        session_endpoints = meta.get("session_endpoints_count", 0)
        if session_endpoints > 30:
            score_delta += 2.0

        # During learning period, only record, don't escalate
        if learning:
            # Record behavioral data for baseline building
            imprint_id = guardian.get("device_imprint_id")
            if imprint_id:
                await self._device_imprint.update_behavioral_data(
                    imprint_id, login_hour=hour,
                    session_duration_sec=0,
                    endpoints_accessed=[message_type],
                )
            return {"state": "DORMANT", "score": 0, "action": None, "learning": True}

        # Apply score delta with decay (scores naturally decay toward 0)
        decay = 0.1  # Decay per observation
        new_score = max(0, min(100, current_score + score_delta - decay))

        # Sentinel mode: 1.5x sensitivity
        if guardian.get("sentinel_mode"):
            sentinel_until = guardian.get("sentinel_until")
            if sentinel_until and now < sentinel_until:
                new_score = min(100, new_score * 1.5 if score_delta > 0 else new_score)

        new_state = score_to_state(new_score)
        old_state = guardian.get("curiosity_state", "DORMANT")

        # One-way ratchet within a session
        state_order = [s.value for s in GuardianState]
        if state_order.index(new_state.value) < state_order.index(old_state):
            new_state = GuardianState(old_state)

        # Only write to DB if state or score changed meaningfully
        if abs(new_score - current_score) > 0.5 or new_state.value != old_state:
            await self._update_guardian_score(user_id, new_state.value, new_score)

        # Determine action
        action = None
        if new_state == GuardianState.CURIOUS:
            action = "shadow_session"
        elif new_state == GuardianState.SUSPICIOUS:
            action = "mask_sensitive_data"
        elif new_state == GuardianState.ALARMED:
            action = "serve_synthetic_data"
        elif new_state == GuardianState.HOSTILE:
            action = "containment"

        return {
            "state": new_state.value,
            "score": new_score,
            "action": action,
            "delta": score_delta,
        }

    async def _update_guardian_score(self, user_id: str, state: str, score: float) -> None:
        """Lightweight score/state update (no imprint change)."""
        if not self._db:
            return
        try:
            await self._db.execute(
                "UPDATE guardian_fibres SET curiosity_state = $2, anomaly_score = $3, updated_at = NOW() WHERE user_id = $1",
                user_id, state, score,
            )
        except Exception as exc:
            _logger.error("Guardian score update error: %s", exc)

    async def check_session_behavior(
        self, user_id: str, endpoints_accessed: List[str],
        session_duration_sec: int = 0,
    ) -> Dict[str, Any]:
        """Called periodically during a session to update behavioral model."""
        guardian = await self._get_guardian(user_id)
        if not guardian:
            return {"state": "DORMANT", "anomaly_score": 0}

        imprint_id = guardian.get("device_imprint_id")
        if imprint_id:
            await self._device_imprint.update_behavioral_data(
                imprint_id,
                login_hour=datetime.now(timezone.utc).hour,
                session_duration_sec=session_duration_sec,
                endpoints_accessed=endpoints_accessed,
            )

        return {
            "state": guardian["curiosity_state"],
            "anomaly_score": guardian["anomaly_score"],
        }

    async def get_state(self, user_id: str) -> Dict[str, Any]:
        """Get current guardian state for a user."""
        guardian = await self._get_guardian(user_id)
        if not guardian:
            return {"state": "DORMANT", "anomaly_score": 0, "exists": False}
        return {
            "state": guardian["curiosity_state"],
            "anomaly_score": guardian["anomaly_score"],
            "learning_mode": guardian["learning_mode"],
            "sentinel_mode": guardian["sentinel_mode"],
            "exists": True,
        }

    async def enter_sentinel_mode(self, user_id: str, duration_days: int = 30) -> None:
        """Enter sentinel mode (1.5x sensitivity for 30 days)."""
        if not self._db:
            return
        until = datetime.now(timezone.utc) + timedelta(days=duration_days)
        try:
            await self._db.execute(
                "UPDATE guardian_fibres SET sentinel_mode = TRUE, sentinel_until = $2, updated_at = NOW() WHERE user_id = $1",
                user_id, until,
            )
            _logger.info("User %s entered sentinel mode until %s", user_id[:8], until.isoformat())
        except Exception as exc:
            _logger.error("Sentinel mode error: %s", exc)

    async def deescalate(self, user_id: str, new_state: str, authorized_by: str = "admin") -> None:
        """Manually de-escalate a guardian (requires authority)."""
        _logger.warning(
            "Guardian de-escalation for user %s to %s by %s",
            user_id[:8], new_state, authorized_by,
        )
        if not self._db:
            return
        try:
            await self._db.execute(
                "UPDATE guardian_fibres SET curiosity_state = $2, updated_at = NOW() WHERE user_id = $1",
                user_id, new_state,
            )
        except Exception as exc:
            _logger.error("De-escalation error: %s", exc)

    async def take_snapshot(self, user_id: str) -> Optional[str]:
        """Take a 24h signed snapshot of guardian state (for Sentinel Mesh)."""
        guardian = await self._get_guardian(user_id)
        if not guardian:
            return None

        snapshot_data = json.dumps({
            "user_id": user_id,
            "state": guardian["curiosity_state"],
            "score": guardian["anomaly_score"],
            "ts": datetime.now(timezone.utc).isoformat(),
        }, sort_keys=True)
        snapshot_hash = hashlib.sha256(snapshot_data.encode()).hexdigest()

        if self._db:
            try:
                await self._db.execute(
                    """INSERT INTO guardian_snapshots
                       (user_id, snapshot_hash, curiosity_state, anomaly_score, created_at)
                       VALUES ($1, $2, $3, $4, NOW())""",
                    user_id, snapshot_hash, guardian["curiosity_state"], guardian["anomaly_score"],
                )
            except Exception as exc:
                _logger.error("Snapshot save error: %s", exc)

        return snapshot_hash

    # ─── Internal ─────────────────────────────────────────────────────────────

    async def _get_or_create_guardian(self, user_id: str) -> Dict[str, Any]:
        """Get or create a guardian fibre for a user."""
        guardian = await self._get_guardian(user_id)
        if guardian:
            return guardian

        # Create new guardian in learning mode
        now = datetime.now(timezone.utc)
        learning_ends = now + timedelta(days=LEARNING_PERIOD_DAYS)

        if self._db:
            try:
                await self._db.execute(
                    """INSERT INTO guardian_fibres
                       (user_id, curiosity_state, anomaly_score, learning_mode,
                        learning_started_at, learning_ends_at, created_at, updated_at)
                       VALUES ($1, 'DORMANT', 0, TRUE, $2, $3, NOW(), NOW())
                       ON CONFLICT (user_id) DO NOTHING""",
                    user_id, now, learning_ends,
                )
            except Exception as exc:
                _logger.error("Guardian creation error: %s", exc)

        return {
            "user_id": user_id,
            "curiosity_state": "DORMANT",
            "anomaly_score": 0,
            "learning_mode": True,
            "sentinel_mode": False,
            "device_imprint_id": None,
        }

    async def _get_guardian(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Fetch guardian record from DB."""
        if not self._db:
            return None
        try:
            row = await self._db.fetchrow(
                "SELECT * FROM guardian_fibres WHERE user_id = $1", user_id,
            )
            if row:
                result = dict(row)
                # Check if learning period is over
                learning_ends = result.get("learning_ends_at")
                if learning_ends and datetime.now(timezone.utc) > learning_ends and result.get("learning_mode"):
                    await self._db.execute(
                        "UPDATE guardian_fibres SET learning_mode = FALSE, updated_at = NOW() WHERE user_id = $1",
                        user_id,
                    )
                    result["learning_mode"] = False
                return result
            return None
        except Exception as exc:
            _logger.error("Guardian fetch error: %s", exc)
            return None

    async def _update_guardian(
        self, user_id: str, state: str, score: float, imprint_id: str,
    ) -> None:
        """Update guardian state in DB."""
        if not self._db:
            return
        try:
            await self._db.execute(
                """UPDATE guardian_fibres
                   SET curiosity_state = $2, anomaly_score = $3, device_imprint_id = $4,
                       updated_at = NOW()
                   WHERE user_id = $1""",
                user_id, state, score, imprint_id,
            )
        except Exception as exc:
            _logger.error("Guardian update error: %s", exc)
