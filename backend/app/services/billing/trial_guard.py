"""
HIVE DEFENSE v4.0 — Trial Guard
Multi-signal fingerprinting to prevent trial abuse.

5-field fingerprint matching:
1. Email hash
2. Phone hash
3. Device ID hash
4. IP geolocation hash
5. Payment method hash (last4 + exp)
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("trial_guard")

# Minimum matches to flag as probable abuse
MATCH_THRESHOLD = 2
# Hard block threshold
BLOCK_THRESHOLD = 3


class TrialGuard:
    """Multi-signal fingerprinting to detect trial abuse."""

    def __init__(self, db_pool):
        self._db = db_pool

    @staticmethod
    def _hash_field(value: str) -> str:
        """SHA-256 hash a field for comparison (one-way)."""
        return hashlib.sha256(value.strip().lower().encode()).hexdigest()

    async def can_start_trial(
        self,
        email: str,
        phone: Optional[str] = None,
        device_id: Optional[str] = None,
        ip_geo: Optional[str] = None,
        payment_method_fingerprint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Check whether this user should be allowed to start a trial.
        Returns {"allowed": bool, "match_count": int, "matches": [...], "reason": str}.
        """
        fields = {}
        if email:
            fields["email_hash"] = self._hash_field(email)
        if phone:
            fields["phone_hash"] = self._hash_field(phone)
        if device_id:
            fields["device_id_hash"] = self._hash_field(device_id)
        if ip_geo:
            fields["ip_geo_hash"] = self._hash_field(ip_geo)
        if payment_method_fingerprint:
            fields["payment_method_hash"] = self._hash_field(payment_method_fingerprint)

        matches = []
        for field_type, field_hash in fields.items():
            row = await self._lookup_fingerprint(field_type, field_hash)
            if row:
                matches.append({
                    "field": field_type,
                    "previous_user_id": row["user_id"],
                    "created_at": str(row["created_at"]),
                })

        match_count = len(matches)
        if match_count >= BLOCK_THRESHOLD:
            _logger.warning(
                "Trial BLOCKED: %d fingerprint matches (threshold=%d)",
                match_count, BLOCK_THRESHOLD,
            )
            return {
                "allowed": False,
                "match_count": match_count,
                "matches": matches,
                "reason": "trial_abuse_detected",
            }
        elif match_count >= MATCH_THRESHOLD:
            _logger.warning(
                "Trial FLAGGED: %d fingerprint matches (flag threshold=%d)",
                match_count, MATCH_THRESHOLD,
            )
            return {
                "allowed": True,
                "match_count": match_count,
                "matches": matches,
                "reason": "flagged_for_review",
            }

        return {
            "allowed": True,
            "match_count": 0,
            "matches": [],
            "reason": "clean",
        }

    async def record_trial_start(
        self,
        user_id: str,
        email: str,
        phone: Optional[str] = None,
        device_id: Optional[str] = None,
        ip_geo: Optional[str] = None,
        payment_method_fingerprint: Optional[str] = None,
    ) -> None:
        """Record fingerprints when a user starts a trial."""
        fields = {}
        if email:
            fields["email_hash"] = self._hash_field(email)
        if phone:
            fields["phone_hash"] = self._hash_field(phone)
        if device_id:
            fields["device_id_hash"] = self._hash_field(device_id)
        if ip_geo:
            fields["ip_geo_hash"] = self._hash_field(ip_geo)
        if payment_method_fingerprint:
            fields["payment_method_hash"] = self._hash_field(payment_method_fingerprint)

        for field_type, field_hash in fields.items():
            await self._store_fingerprint(field_type, field_hash, user_id)

    async def _lookup_fingerprint(self, field_type: str, field_hash: str) -> Optional[Dict]:
        """Look up a fingerprint in the database."""
        if not self._db:
            return None
        try:
            return await self._db.fetchrow(
                "SELECT user_id, created_at FROM trial_fingerprints WHERE field_type=$1 AND field_hash=$2",
                field_type, field_hash,
            )
        except Exception as exc:
            _logger.error("Fingerprint lookup error: %s", exc)
            return None

    # ─── Gated Trial Enforcement (Days 8-14) ─────────────────────────────────

    async def enforce_gated_trial(self, user_id: str, trial_start_date: str) -> Dict[str, Any]:
        """
        Enforce gated trial restrictions during days 8-14.

        During week 1 (days 1-7): full trial access.
        During week 2 (days 8-14): reduced access (30 min/day AI, coherence prompts).
        After day 14: trial expired, must convert.

        Returns {"phase": str, "restrictions": dict, "days_remaining": int}
        """
        from datetime import datetime, timezone

        try:
            start = datetime.fromisoformat(trial_start_date.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return {"phase": "unknown", "restrictions": {}, "days_remaining": 0}

        now = datetime.now(timezone.utc)
        elapsed_days = (now - start).days

        if elapsed_days < 0:
            return {"phase": "not_started", "restrictions": {}, "days_remaining": 14}

        if elapsed_days <= 7:
            # Week 1: full trial
            return {
                "phase": "week_1_full",
                "restrictions": {
                    "ai_minutes": 300,
                    "tokens": 50000,
                    "daily_limit": False,
                    "coherence_prompt": False,
                },
                "days_remaining": 14 - elapsed_days,
            }

        if elapsed_days <= 14:
            # Week 2: gated — reduced daily AI, coherence prompt on entry
            return {
                "phase": "week_2_gated",
                "restrictions": {
                    "ai_minutes_per_day": 30,
                    "tokens": 50000,
                    "daily_limit": True,
                    "coherence_prompt": True,
                    "message": "Your trial is in gated phase. Upgrade for full access.",
                },
                "days_remaining": 14 - elapsed_days,
            }

        # Expired
        _logger.info("Trial expired for user %s (day %d)", user_id[:8], elapsed_days)
        return {
            "phase": "expired",
            "restrictions": {
                "ai_minutes": 0,
                "tokens": 0,
                "daily_limit": True,
                "coherence_prompt": True,
                "blocked": True,
                "message": "Your trial has expired. Please subscribe to continue.",
            },
            "days_remaining": 0,
        }

    async def _store_fingerprint(self, field_type: str, field_hash: str, user_id: str) -> None:
        """Store a fingerprint in the database."""
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT INTO trial_fingerprints (field_type, field_hash, user_id, created_at)
                   VALUES ($1, $2, $3, NOW())
                   ON CONFLICT (field_type, field_hash) DO NOTHING""",
                field_type, field_hash, user_id,
            )
        except Exception as exc:
            _logger.error("Fingerprint store error: %s", exc)
