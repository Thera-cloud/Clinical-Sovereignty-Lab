"""
SOVEREIGN SWARM — Nate Sentinel
AI intrusion protection for admin sessions.

Even if an attacker steals admin credentials, the Sentinel detects
anomalous behavior and freezes the session before damage is done.

Behavioral baseline (built over first 7 days, continuously updated):
    - known_ips, known_devices
    - typical_hours (local time)
    - typical_actions_per_minute
    - typical_action_types (frequency distribution)

Anomaly scoring per action:
    - Unknown IP: +40
    - Unknown device: +30
    - Unusual hour: +20
    - Rapid action rate (>3x typical): +25
    - Bulk destructive actions (>3 deletes/bans in 5min): +50
    - Attempting to modify admin credentials: +60

Thresholds:
    - Score >= 50: Log warning, send email alert
    - Score >= 80: FREEZE session — require full re-auth
"""

from __future__ import annotations

import json
import datetime
import hashlib
from collections import defaultdict
from typing import Any, Dict, List, Optional
from pathlib import Path


WARN_THRESHOLD = 50
FREEZE_THRESHOLD = 80
DESTRUCTIVE_ACTIONS = frozenset({
    "admin_delete_user", "admin_ban_user", "admin_delete_admin_account",
    "freeze_account",
})
CREDENTIAL_ACTIONS = frozenset({
    "admin_reset_password", "admin_setup_totp", "admin_webauthn_register_start",
})


class NateSentinel:
    """Session fingerprinting, anomaly scoring, and freeze logic for admin sessions."""

    def __init__(self, registry_path: str | Path, db_pool=None):
        self.registry_path = Path(registry_path)
        self.db_pool = db_pool
        # In-memory per-session tracking (keyed by hardware_id)
        self._session_scores: Dict[str, int] = defaultdict(int)
        self._session_actions: Dict[str, List[dict]] = defaultdict(list)
        self._frozen_sessions: set = set()

    def _load_registry(self) -> dict:
        try:
            with open(self.registry_path, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_registry(self, registry: dict):
        with open(self.registry_path, "w") as f:
            json.dump(registry, f, indent=2, default=str)

    def _get_profile(self, registry: dict, uid: str) -> Optional[dict]:
        for _, v in registry.items():
            if v.get("profile", {}).get("hardware_id") == uid:
                return v["profile"]
        return None

    @staticmethod
    def _device_hash(user_agent: str, ip: str) -> str:
        return hashlib.sha256(f"{user_agent}:{ip}".encode()).hexdigest()[:16]

    # ─── Baseline Management ──────────────────────────────────────────────

    def _ensure_baseline(self, profile: dict) -> dict:
        if "sentinel_baseline" not in profile:
            profile["sentinel_baseline"] = {
                "known_ips": [],
                "known_devices": [],
                "typical_hours": [],
                "typical_actions_per_minute": 2.5,
                "typical_action_types": {},
            }
        return profile["sentinel_baseline"]

    def update_baseline(self, uid: str, ip: str, device_hash: str, action_type: str):
        """Continuously update the admin's behavioral baseline."""
        registry = self._load_registry()
        profile = self._get_profile(registry, uid)
        if not profile or profile.get("role") != "ADMIN":
            return

        baseline = self._ensure_baseline(profile)

        # Update known IPs/devices (keep last 20)
        if ip and ip not in baseline["known_ips"]:
            baseline["known_ips"].append(ip)
            baseline["known_ips"] = baseline["known_ips"][-20:]

        if device_hash and device_hash not in baseline["known_devices"]:
            baseline["known_devices"].append(device_hash)
            baseline["known_devices"] = baseline["known_devices"][-20:]

        # Update typical hours
        hour = datetime.datetime.now().hour
        if hour not in baseline["typical_hours"]:
            baseline["typical_hours"].append(hour)
            baseline["typical_hours"] = sorted(set(baseline["typical_hours"]))

        # Update action type frequency
        atypes = baseline.get("typical_action_types", {})
        atypes[action_type] = atypes.get(action_type, 0) + 1
        baseline["typical_action_types"] = atypes

        self._save_registry(registry)

    # ─── Anomaly Scoring ──────────────────────────────────────────────────

    def score_action(self, uid: str, action_type: str, ip: str = "",
                     user_agent: str = "") -> Dict[str, Any]:
        """
        Score an admin action for anomaly.
        Returns: {"score": int, "total_session_score": int, "frozen": bool, "reasons": [...]}
        """
        registry = self._load_registry()
        profile = self._get_profile(registry, uid)
        if not profile or profile.get("role") != "ADMIN":
            return {"score": 0, "total_session_score": 0, "frozen": False, "reasons": []}

        baseline = self._ensure_baseline(profile)
        score = 0
        reasons = []
        now = datetime.datetime.now()
        device_hash = self._device_hash(user_agent, ip) if user_agent else ""

        # 1. Unknown IP
        if ip and ip not in baseline.get("known_ips", []):
            score += 40
            reasons.append(f"Unknown IP: {ip}")

        # 2. Unknown device
        if device_hash and device_hash not in baseline.get("known_devices", []):
            score += 30
            reasons.append("Unknown device fingerprint")

        # 3. Unusual hour
        if now.hour not in baseline.get("typical_hours", list(range(24))):
            score += 20
            reasons.append(f"Unusual hour: {now.hour}:00")

        # 4. Rapid action rate
        session_actions = self._session_actions[uid]
        session_actions.append({"action": action_type, "ts": now.timestamp()})
        # Keep only last 5 minutes
        cutoff = now.timestamp() - 300
        session_actions = [a for a in session_actions if a["ts"] > cutoff]
        self._session_actions[uid] = session_actions

        if len(session_actions) > 1:
            elapsed_min = (session_actions[-1]["ts"] - session_actions[0]["ts"]) / 60
            if elapsed_min > 0:
                rate = len(session_actions) / elapsed_min
                typical_rate = baseline.get("typical_actions_per_minute", 2.5)
                if rate > typical_rate * 3:
                    score += 25
                    reasons.append(f"Rapid rate: {rate:.1f}/min (typical: {typical_rate:.1f})")

        # 5. Bulk destructive actions
        recent_destructive = [
            a for a in session_actions
            if a["action"] in DESTRUCTIVE_ACTIONS and a["ts"] > cutoff
        ]
        if len(recent_destructive) > 3:
            score += 50
            reasons.append(f"Bulk destructive: {len(recent_destructive)} in 5 min")

        # 6. Credential modification attempt
        if action_type in CREDENTIAL_ACTIONS:
            score += 60
            reasons.append(f"Credential modification: {action_type}")

        # Accumulate session score
        self._session_scores[uid] += score
        total = self._session_scores[uid]

        # Check thresholds
        frozen = uid in self._frozen_sessions
        if total >= FREEZE_THRESHOLD and not frozen:
            self._frozen_sessions.add(uid)
            frozen = True

        return {
            "score": score,
            "total_session_score": total,
            "frozen": frozen,
            "reasons": reasons,
        }

    def is_frozen(self, uid: str) -> bool:
        return uid in self._frozen_sessions

    def unfreeze(self, uid: str):
        """Unfreeze a session (after re-auth)."""
        self._frozen_sessions.discard(uid)
        self._session_scores[uid] = 0
        self._session_actions[uid] = []

    def reset_session(self, uid: str):
        """Reset all session tracking (on logout or disconnect)."""
        self._session_scores.pop(uid, None)
        self._session_actions.pop(uid, None)
        self._frozen_sessions.discard(uid)

    # ─── Trusted Device Management ────────────────────────────────────────

    def is_trusted_device(self, uid: str, ip: str, user_agent: str) -> bool:
        """Check if this IP+device combination is trusted (known)."""
        registry = self._load_registry()
        profile = self._get_profile(registry, uid)
        if not profile:
            return False
        baseline = self._ensure_baseline(profile)
        device_hash = self._device_hash(user_agent, ip)
        return (
            ip in baseline.get("known_ips", [])
            and device_hash in baseline.get("known_devices", [])
        )

    def add_trusted_device(self, uid: str, ip: str, user_agent: str):
        """Add a device to trusted list after 2FA verification."""
        registry = self._load_registry()
        profile = self._get_profile(registry, uid)
        if not profile:
            return
        baseline = self._ensure_baseline(profile)
        device_hash = self._device_hash(user_agent, ip)
        if ip not in baseline["known_ips"]:
            baseline["known_ips"].append(ip)
        if device_hash not in baseline["known_devices"]:
            baseline["known_devices"].append(device_hash)
        self._save_registry(registry)

    # ─── Audit Log ────────────────────────────────────────────────────────

    async def log_action(self, uid: str, action: str, target: str = "",
                         ip: str = "", device_hash: str = "",
                         anomaly_score: int = 0, details: str = ""):
        """Log admin action to PostgreSQL audit_log."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO audit_log
                        (action_type, admin_id, target_id, description, ip_address)
                    VALUES ($1, $2, $3, $4, $5::inet)""",
                    action, uid, target or uid,
                    f"{details} [anomaly_score={anomaly_score}, device={device_hash[:8] if device_hash else 'n/a'}]",
                    ip or "0.0.0.0",
                )
        except Exception as e:
            print(f">>> [SENTINEL] Audit log failed: {e}")
