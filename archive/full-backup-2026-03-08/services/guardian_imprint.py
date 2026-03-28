"""
HIVE DEFENSE v4.0 — Device Imprint & Behavioral Learning
Device fingerprinting and behavioral baseline tracking for Guardian Fibre.

- Collects device characteristics at login
- Builds behavioral model over 7-day learning period
- Scores anomalies against learned baseline
"""

import hashlib
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

_logger = logging.getLogger("guardian_imprint")

LEARNING_PERIOD_DAYS = 7


class DeviceImprint:
    """Device fingerprint and behavioral baseline."""

    def __init__(self, db_pool):
        self._db = db_pool

    async def create_imprint(
        self,
        user_id: str,
        device_type: str = "unknown",
        user_agent: str = "",
        timezone_str: str = "",
        ip_geo_region: str = "",
        screen_resolution: str = "",
        language: str = "",
    ) -> str:
        """Create a new device imprint and return its ID."""
        imprint_id = str(uuid4())
        ua_hash = hashlib.sha256(user_agent.encode()).hexdigest()[:32]

        if self._db:
            try:
                await self._db.execute(
                    """INSERT INTO device_imprints
                       (imprint_id, user_id, device_type, user_agent_hash, timezone,
                        ip_geo_region, screen_resolution, language, last_seen_at, created_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), NOW())""",
                    imprint_id, user_id, device_type, ua_hash, timezone_str,
                    ip_geo_region, screen_resolution, language,
                )
            except Exception as exc:
                _logger.error("Failed to create imprint: %s", exc)

        return imprint_id

    async def find_matching_imprint(
        self, user_id: str, user_agent: str = "", timezone_str: str = "",
        ip_geo_region: str = "", screen_resolution: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Find an existing device imprint matching the current device signals."""
        if not self._db:
            return None
        ua_hash = hashlib.sha256(user_agent.encode()).hexdigest()[:32]

        try:
            row = await self._db.fetchrow(
                """SELECT * FROM device_imprints
                   WHERE user_id = $1 AND user_agent_hash = $2
                   ORDER BY last_seen_at DESC NULLS LAST LIMIT 1""",
                user_id, ua_hash,
            )
            if row:
                return dict(row)

            # Fuzzy match: same user, same timezone and geo
            row = await self._db.fetchrow(
                """SELECT * FROM device_imprints
                   WHERE user_id = $1 AND timezone = $2 AND ip_geo_region = $3
                   ORDER BY last_seen_at DESC NULLS LAST LIMIT 1""",
                user_id, timezone_str, ip_geo_region,
            )
            return dict(row) if row else None
        except Exception as exc:
            _logger.error("Imprint lookup error: %s", exc)
            return None

    async def update_behavioral_data(
        self, imprint_id: str, login_hour: int, session_duration_sec: int,
        endpoints_accessed: List[str],
    ) -> None:
        """Update behavioral baseline from session activity."""
        if not self._db:
            return
        try:
            row = await self._db.fetchrow(
                "SELECT typical_login_hours, avg_session_duration_sec, endpoint_patterns FROM device_imprints WHERE imprint_id = $1",
                imprint_id,
            )
            if not row:
                return

            import json
            hours = json.loads(row["typical_login_hours"]) if row["typical_login_hours"] else []
            if login_hour not in hours:
                hours.append(login_hour)
                hours = sorted(hours)[-24:]  # keep last 24 unique hours

            # Running average for session duration
            old_avg = row["avg_session_duration_sec"] or 0
            new_avg = int((old_avg * 0.8) + (session_duration_sec * 0.2)) if old_avg else session_duration_sec

            patterns = json.loads(row["endpoint_patterns"]) if row["endpoint_patterns"] else {}
            for ep in endpoints_accessed:
                patterns[ep] = patterns.get(ep, 0) + 1

            await self._db.execute(
                """UPDATE device_imprints
                   SET typical_login_hours = $2,
                       avg_session_duration_sec = $3,
                       endpoint_patterns = $4,
                       last_seen_at = NOW()
                   WHERE imprint_id = $1""",
                imprint_id, json.dumps(hours), new_avg, json.dumps(patterns),
            )
        except Exception as exc:
            _logger.error("Behavioral update error: %s", exc)

    async def score_anomaly(
        self, user_id: str, user_agent: str = "", timezone_str: str = "",
        ip_geo_region: str = "", login_hour: int = 12,
    ) -> float:
        """Score how anomalous the current login is (0-100)."""
        if not self._db:
            return 0.0

        ua_hash = hashlib.sha256(user_agent.encode()).hexdigest()[:32]
        score = 0.0

        try:
            imprints = await self._db.fetch(
                "SELECT * FROM device_imprints WHERE user_id = $1 ORDER BY last_seen_at DESC NULLS LAST",
                user_id,
            )
            if not imprints:
                return 0.0  # No baseline yet

            # Check if user_agent matches any known device
            known_ua = {r["user_agent_hash"] for r in imprints}
            if ua_hash not in known_ua:
                score += 25  # Unknown device

            # Check timezone
            known_tz = {r["timezone"] for r in imprints if r["timezone"]}
            if timezone_str and known_tz and timezone_str not in known_tz:
                score += 15  # Unusual timezone

            # Check geo region
            known_geo = {r["ip_geo_region"] for r in imprints if r["ip_geo_region"]}
            if ip_geo_region and known_geo and ip_geo_region not in known_geo:
                score += 20  # New geographic region

            # Check login hour against typical hours
            import json
            all_hours = set()
            for r in imprints:
                hours = json.loads(r["typical_login_hours"]) if r["typical_login_hours"] else []
                all_hours.update(hours)

            if all_hours and login_hour not in all_hours:
                # How far from nearest typical hour?
                min_dist = min(abs(login_hour - h) for h in all_hours)
                min_dist = min(min_dist, 24 - min_dist)  # wrap around
                if min_dist > 4:
                    score += 15  # Very unusual hour
                elif min_dist > 2:
                    score += 8   # Somewhat unusual hour

            return min(score, 100.0)
        except Exception as exc:
            _logger.error("Anomaly scoring error: %s", exc)
            return 0.0

    async def mark_verified(self, imprint_id: str) -> None:
        """Mark a device imprint as verified (email verification completed)."""
        if not self._db:
            return
        try:
            await self._db.execute(
                "UPDATE device_imprints SET verified = TRUE WHERE imprint_id = $1",
                imprint_id,
            )
        except Exception as exc:
            _logger.error("Failed to verify imprint: %s", exc)
