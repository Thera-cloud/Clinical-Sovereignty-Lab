"""
SOVEREIGN SWARM — Abuse Manager
Progressive discipline system for account violations.

Discipline flow:
    Strike 1 → Warning (logged)
    Strike 2 (within 7 days) → 24-hour hold (account blocked)
    Strike 3 (within 7 days of hold end) → 30-day ban
    Admin reviews → Delete or Reinstate (reset strikes)

Violation types:
    - THREAT: Explicit threats or harmful language
    - RATE_ABUSE: >120 messages/min or >20 reconnects/5min
    - JAILBREAK: Prompt injection / manipulation attempts
    - CREDENTIAL_SHARING: Multiple simultaneous device logins beyond 2
    - HARASSMENT: Flagged by coach or family member in Sanctuary

Family Succession:
    When the abuser is the HEAD of household:
    - 24hr hold → temp successor (HEAD_TEMP), restore on hold expiry
    - 30-day ban or delete → permanent successor (HEAD), transfer billing
"""

from __future__ import annotations

import json
import datetime
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path


# ─── Constants ────────────────────────────────────────────────────────────────

VIOLATION_TYPES = [
    "THREAT",
    "RATE_ABUSE",
    "JAILBREAK",
    "CREDENTIAL_SHARING",
    "HARASSMENT",
]

STRIKE_DECAY_DAYS = 7          # Strikes decay if no new violations within this window
MAX_STRIKES_BEFORE_BAN = 3
HOLD_DURATION_HOURS = 24
BAN_DURATION_DAYS = 30


class AbuseManager:
    """Manages violation recording, progressive discipline, and family succession."""

    def __init__(self, registry_path: str | Path, db_pool=None):
        self.registry_path = Path(registry_path)
        self.db_pool = db_pool

    # ─── Registry Helpers ─────────────────────────────────────────────────

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

    # ─── Discipline State ─────────────────────────────────────────────────

    def _ensure_discipline(self, profile: dict) -> dict:
        """Ensure profile has a discipline block."""
        if "discipline" not in profile:
            profile["discipline"] = {
                "strikes": 0,
                "warnings": [],
                "hold_until": None,
                "ban_until": None,
                "ban_reasons": [],
                "last_violation": None,
            }
        return profile["discipline"]

    def check_status(self, uid: str) -> Dict[str, Any]:
        """
        Check if a user is currently held or banned.
        Returns: {"status": "ok"|"held"|"banned", "until": iso_str|None, "reason": str|None}
        """
        registry = self._load_registry()
        profile = self._get_profile(registry, uid)
        if not profile:
            return {"status": "ok", "until": None, "reason": None}

        disc = self._ensure_discipline(profile)
        now = datetime.datetime.now()

        # Check ban
        if disc.get("ban_until"):
            try:
                ban_dt = datetime.datetime.fromisoformat(disc["ban_until"])
                if now < ban_dt:
                    return {
                        "status": "banned",
                        "until": disc["ban_until"],
                        "reason": disc.get("ban_reasons", ["Policy violation"])[-1] if disc.get("ban_reasons") else "Policy violation",
                    }
                else:
                    # Ban expired — don't auto-clear, admin must review
                    return {
                        "status": "banned",
                        "until": disc["ban_until"],
                        "reason": "Ban expired — awaiting admin review",
                    }
            except Exception:
                pass

        # Check hold
        if disc.get("hold_until"):
            try:
                hold_dt = datetime.datetime.fromisoformat(disc["hold_until"])
                if now < hold_dt:
                    return {
                        "status": "held",
                        "until": disc["hold_until"],
                        "reason": "24-hour hold due to repeated violations",
                    }
                else:
                    # Hold expired — clear it
                    disc["hold_until"] = None
                    self._save_registry(registry)
            except Exception:
                pass

        return {"status": "ok", "until": None, "reason": None}

    def record_violation(self, uid: str, violation_type: str, reason: str = "") -> Dict[str, Any]:
        """
        Record a violation and apply progressive discipline.
        Returns action taken: {"action": "warning"|"hold"|"ban", "strikes": N, ...}
        """
        registry = self._load_registry()
        profile = self._get_profile(registry, uid)
        if not profile:
            return {"action": "none", "reason": "User not found"}

        disc = self._ensure_discipline(profile)
        now = datetime.datetime.now()

        # Check strike decay: if last violation was > STRIKE_DECAY_DAYS ago, reset
        if disc.get("last_violation"):
            try:
                last = datetime.datetime.fromisoformat(disc["last_violation"])
                if (now - last).days > STRIKE_DECAY_DAYS:
                    disc["strikes"] = 0
            except Exception:
                pass

        disc["strikes"] = disc.get("strikes", 0) + 1
        disc["last_violation"] = now.isoformat()
        disc["warnings"].append({
            "type": violation_type,
            "reason": reason,
            "timestamp": now.isoformat(),
            "strike_number": disc["strikes"],
        })

        # Keep only last 50 warnings
        disc["warnings"] = disc["warnings"][-50:]

        action_taken = "warning"

        if disc["strikes"] >= MAX_STRIKES_BEFORE_BAN:
            # Strike 3+: 30-day ban
            ban_until = now + datetime.timedelta(days=BAN_DURATION_DAYS)
            disc["ban_until"] = ban_until.isoformat()
            disc["ban_reasons"].append(f"{violation_type}: {reason}" if reason else violation_type)
            profile["account_status"] = "BANNED"
            action_taken = "ban"
        elif disc["strikes"] == 2:
            # Strike 2: 24-hour hold
            hold_until = now + datetime.timedelta(hours=HOLD_DURATION_HOURS)
            disc["hold_until"] = hold_until.isoformat()
            profile["account_status"] = "HELD"
            action_taken = "hold"

        profile["updated_at"] = now.isoformat()
        self._save_registry(registry)

        result = {
            "action": action_taken,
            "strikes": disc["strikes"],
            "violation_type": violation_type,
            "user_id": uid,
        }

        if action_taken == "ban":
            result["ban_until"] = disc["ban_until"]
            # Family succession needed?
            if profile.get("family_role", "").upper() == "HEAD":
                succession = self.find_family_successor(
                    profile.get("family_id", ""), uid
                )
                if succession:
                    self._apply_succession(registry, profile, succession, permanent=True)
                    self._save_registry(registry)
                    result["succession"] = succession

        elif action_taken == "hold":
            result["hold_until"] = disc["hold_until"]
            if profile.get("family_role", "").upper() == "HEAD":
                succession = self.find_family_successor(
                    profile.get("family_id", ""), uid
                )
                if succession:
                    self._apply_succession(registry, profile, succession, permanent=False)
                    self._save_registry(registry)
                    result["succession"] = succession

        return result

    def lift_hold(self, uid: str) -> bool:
        """Manually lift a hold (admin action)."""
        registry = self._load_registry()
        profile = self._get_profile(registry, uid)
        if not profile:
            return False
        disc = self._ensure_discipline(profile)
        disc["hold_until"] = None
        if profile.get("account_status") == "HELD":
            profile["account_status"] = "ACTIVE"
        profile["updated_at"] = datetime.datetime.now().isoformat()
        self._save_registry(registry)
        return True

    def lift_ban(self, uid: str, reset_strikes: bool = True) -> bool:
        """Lift a ban and optionally reset strikes (admin action)."""
        registry = self._load_registry()
        profile = self._get_profile(registry, uid)
        if not profile:
            return False
        disc = self._ensure_discipline(profile)
        disc["ban_until"] = None
        if reset_strikes:
            disc["strikes"] = 0
        if profile.get("account_status") == "BANNED":
            profile["account_status"] = "ACTIVE"
        profile["updated_at"] = datetime.datetime.now().isoformat()
        self._save_registry(registry)
        return True

    def get_user_discipline(self, uid: str) -> Dict[str, Any]:
        """Get full discipline record for a user (for dashboard)."""
        registry = self._load_registry()
        profile = self._get_profile(registry, uid)
        if not profile:
            return {}
        return dict(self._ensure_discipline(profile))

    # ─── Family Succession ────────────────────────────────────────────────

    def find_family_successor(self, family_id: str, excluded_uid: str) -> Optional[Dict[str, Any]]:
        """
        Find a successor for HEAD of household.
        Priority: (1) SPOUSE, (2) oldest member 18+.
        Returns: {"uid": str, "name": str, "role": str} or None.
        """
        if not family_id:
            return None

        registry = self._load_registry()
        candidates = []

        for _, v in registry.items():
            p = v.get("profile", {})
            if (p.get("family_id") == family_id
                    and p.get("hardware_id") != excluded_uid
                    and p.get("account_status", "ACTIVE") not in ("BANNED", "PENDING_DELETION")):
                candidates.append(p)

        if not candidates:
            return None

        # Priority 1: Spouse
        for c in candidates:
            if (c.get("family_role") or "").upper() == "SPOUSE":
                return {
                    "uid": c["hardware_id"],
                    "name": c.get("name", ""),
                    "role": "SPOUSE",
                }

        # Priority 2: Oldest member (by account creation, proxy for age)
        candidates.sort(key=lambda x: x.get("created_at", ""), reverse=False)
        best = candidates[0]
        return {
            "uid": best["hardware_id"],
            "name": best.get("name", ""),
            "role": best.get("family_role", "MEMBER"),
        }

    def _apply_succession(self, registry: dict, head_profile: dict,
                          successor: dict, permanent: bool):
        """Apply family succession: transfer HEAD to successor."""
        successor_profile = self._get_profile(registry, successor["uid"])
        if not successor_profile:
            return

        if permanent:
            # Permanent transfer: ban or delete
            head_profile["family_role"] = "FORMER_HEAD"
            successor_profile["family_role"] = "HEAD"
            # Transfer subscription plan
            if head_profile.get("subscription_plan"):
                successor_profile["subscription_plan"] = head_profile["subscription_plan"]
        else:
            # Temporary: 24hr hold
            head_profile["family_role"] = "HEAD_SUSPENDED"
            successor_profile["family_role"] = "HEAD_TEMP"

        successor_profile["updated_at"] = datetime.datetime.now().isoformat()

    # ─── Rate Limiting Check ──────────────────────────────────────────────

    def check_rate_abuse(self, uid: str, message_timestamps: List[float]) -> bool:
        """
        Check if a user is sending messages too fast (>120/min).
        message_timestamps: list of unix timestamps of recent messages.
        Returns True if rate abuse detected.
        """
        if len(message_timestamps) < 120:
            return False

        now = datetime.datetime.now().timestamp()
        one_min_ago = now - 60
        recent = [t for t in message_timestamps if t > one_min_ago]

        if len(recent) > 120:
            self.record_violation(uid, "RATE_ABUSE",
                                  f"{len(recent)} messages in 60 seconds")
            return True
        return False
