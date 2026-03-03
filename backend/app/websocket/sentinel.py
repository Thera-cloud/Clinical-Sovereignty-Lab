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

Score decay: 10% per minute of inactivity prevents slow-drip false positives.

On freeze, fires on_freeze_callback (if set) to activate House of Mirrors
(Patent Claims 30-56) — SASE ban, DEFCON escalation, Mirror Shell containment,
Ghost Swarm deployment, and forensic logging.
"""

from __future__ import annotations

import json
import datetime
import hashlib
import time
from collections import defaultdict
from typing import Any, Callable, Coroutine, Dict, List, Optional
from pathlib import Path


WARN_THRESHOLD = 50
FREEZE_THRESHOLD = 80
SCORE_DECAY_RATE = 0.10
SCORE_DECAY_INTERVAL_SEC = 60
DESTRUCTIVE_ACTIONS = frozenset({
    "admin_delete_user", "admin_ban_user", "admin_delete_admin_account",
    "freeze_account",
})
CREDENTIAL_ACTIONS = frozenset({
    "admin_reset_password", "admin_setup_totp", "admin_webauthn_register_start",
})

AUTH_METHOD_MULTIPLIERS = {
    "yubikey": 0.3,
    "totp": 0.5,
    "password": 1.0,
}
AUTH_METHOD_WARN_THRESHOLD = {
    "yubikey": 100,
    "totp": 75,
    "password": WARN_THRESHOLD,
}
AUTH_METHOD_FREEZE_THRESHOLD = {
    "yubikey": 150,
    "totp": 120,
    "password": FREEZE_THRESHOLD,
}


class NateSentinel:
    """Session fingerprinting, anomaly scoring, and freeze logic for admin sessions."""

    def __init__(self, registry_path: str | Path, db_pool=None,
                 on_freeze_callback: Optional[Callable[..., Coroutine]] = None):
        self.registry_path = Path(registry_path)
        self.db_pool = db_pool
        self._on_freeze_callback = on_freeze_callback
        # In-memory per-session tracking (keyed by hardware_id)
        self._session_scores: Dict[str, int] = defaultdict(int)
        self._session_actions: Dict[str, List[dict]] = defaultdict(list)
        self._frozen_sessions: set = set()
        self._session_auth_method: Dict[str, str] = {}
        self._last_action_ts: Dict[str, float] = {}
        self._frozen_at: Dict[str, datetime.datetime] = {}

    def set_auth_method(self, uid: str, method: str):
        """Record auth method for a session (password, yubikey, totp)."""
        self._session_auth_method[uid] = method

    def get_auth_method(self, uid: str) -> str:
        return self._session_auth_method.get(uid, "password")

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
                "typical_hours": list(range(24)) if profile.get("role") == "ADMIN" else [],
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
                     user_agent: str = "", pg_profile: dict = None) -> Dict[str, Any]:
        """
        Score an admin action for anomaly.
        pg_profile: optional profile_data dict from PostgreSQL (overrides JSON baseline).
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

        pg = pg_profile or {}
        all_known_ips = set(baseline.get("known_ips", []))
        all_known_ips.update(pg.get("typical_ips", []))
        all_typical_hours = set(baseline.get("typical_hours", list(range(24))))
        all_typical_hours.update(pg.get("typical_hours", []))

        ip_trusted = ip and ip in all_known_ips

        # 1. Unknown IP
        if ip and not ip_trusted:
            score += 40
            reasons.append(f"Unknown IP: {ip}")

        # 2. Unknown device — skip if IP is already trusted via PG typical_ips
        if device_hash and not ip_trusted and device_hash not in baseline.get("known_devices", []):
            score += 30
            reasons.append("Unknown device fingerprint")

        # 3. Unusual hour
        if now.hour not in all_typical_hours:
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

        # Apply auth-method multiplier
        auth_method = self._session_auth_method.get(uid, "password")
        multiplier = AUTH_METHOD_MULTIPLIERS.get(auth_method, 1.0)
        adjusted_score = int(score * multiplier)

        if multiplier < 1.0 and score > 0:
            reasons.append(f"Auth-method '{auth_method}' multiplier: {multiplier}x ({score} -> {adjusted_score})")

        # Score decay: reduce cumulative score by 10% per minute of inactivity
        now_ts = time.monotonic()
        last_ts = self._last_action_ts.get(uid, now_ts)
        elapsed_sec = now_ts - last_ts
        if elapsed_sec > SCORE_DECAY_INTERVAL_SEC and self._session_scores[uid] > 0:
            decay_periods = int(elapsed_sec / SCORE_DECAY_INTERVAL_SEC)
            decay_factor = (1.0 - SCORE_DECAY_RATE) ** decay_periods
            self._session_scores[uid] = int(self._session_scores[uid] * decay_factor)
        self._last_action_ts[uid] = now_ts

        # Accumulate session score
        self._session_scores[uid] += adjusted_score
        total = self._session_scores[uid]

        # Check thresholds (adjusted per auth method)
        warn_thresh = AUTH_METHOD_WARN_THRESHOLD.get(auth_method, WARN_THRESHOLD)
        freeze_thresh = AUTH_METHOD_FREEZE_THRESHOLD.get(auth_method, FREEZE_THRESHOLD)

        was_frozen = uid in self._frozen_sessions
        frozen = was_frozen
        if total >= freeze_thresh and not was_frozen:
            self._frozen_sessions.add(uid)
            self._frozen_at[uid] = now
            frozen = True

        result = {
            "score": adjusted_score,
            "raw_score": score,
            "total_session_score": total,
            "frozen": frozen,
            "freeze_transition": frozen and not was_frozen,
            "frozen_at": self._frozen_at.get(uid, now).isoformat() if frozen else None,
            "reasons": reasons,
            "auth_method": auth_method,
            "multiplier": multiplier,
            "warn_threshold": warn_thresh,
            "freeze_threshold": freeze_thresh,
        }

        # Fire freeze callback on transition to frozen (House of Mirrors activation)
        if frozen and not was_frozen and self._on_freeze_callback:
            try:
                import asyncio
                asyncio.ensure_future(self._on_freeze_callback(
                    uid=uid, ip=ip, user_agent=user_agent,
                    score=total, reasons=reasons, auth_method=auth_method,
                    frozen_at=self._frozen_at[uid],
                ))
            except Exception as e:
                print(f">>> [SENTINEL] Freeze callback failed: {e}")

        return result

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
        self._session_auth_method.pop(uid, None)
        self._last_action_ts.pop(uid, None)
        self._frozen_at.pop(uid, None)

    def get_frozen_at(self, uid: str) -> Optional[datetime.datetime]:
        """Return the datetime when a session was frozen, or None."""
        return self._frozen_at.get(uid)

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
                pg_uid = await conn.fetchval(
                    "SELECT id FROM users WHERE hardware_id = $1 LIMIT 1", uid
                )
                if not pg_uid:
                    return
                await conn.execute(
                    """INSERT INTO audit_log
                        (action_type, admin_id, target_id, description, ip_address)
                    VALUES ($1, $2, $3, $4, $5::inet)""",
                    action, pg_uid, target or str(pg_uid),
                    f"{details} [anomaly_score={anomaly_score}, device={device_hash[:8] if device_hash else 'n/a'}]",
                    ip or "0.0.0.0",
                )
        except Exception as e:
            print(f">>> [SENTINEL] Audit log failed: {e}")
