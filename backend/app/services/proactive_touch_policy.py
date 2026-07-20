"""
QUANTUM-CRYSTAL-ARCH: Global proactive touch delivery gate (Agentic Phase 0).

Single entry point for every automated outbound touch producer.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("nate.proactive_touch_policy")


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str = ""
    channel_override: Optional[str] = None


def policy_enabled() -> bool:
    return os.getenv("ENABLE_PROACTIVE_TOUCH_POLICY", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _si_suppression_hours() -> int:
    raw = os.getenv("SI_TOUCH_SUPPRESSION_HOURS", os.getenv("SI_COACH_ALERT_DEDUP_HOURS", "24"))
    try:
        return max(1, int(str(raw).strip()))
    except ValueError:
        return 24


def _quiet_hours() -> tuple[time, time]:
    """Local quiet window; outside = deny (not queue). Default 08:00–20:00."""
    start_s = os.getenv("PROACTIVE_TOUCH_QUIET_START", "08:00").strip()
    end_s = os.getenv("PROACTIVE_TOUCH_QUIET_END", "20:00").strip()
    try:
        sh, sm = [int(x) for x in start_s.split(":")[:2]]
        eh, em = [int(x) for x in end_s.split(":")[:2]]
        return time(sh, sm), time(eh, em)
    except Exception:
        return time(8, 0), time(20, 0)


def _max_per_day() -> int:
    try:
        return max(0, int(os.getenv("PROACTIVE_TOUCH_MAX_PER_DAY", "1")))
    except ValueError:
        return 1


def _max_per_week() -> int:
    try:
        return max(0, int(os.getenv("PROACTIVE_TOUCH_MAX_PER_WEEK", "3")))
    except ValueError:
        return 3


def _profile_data(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


async def can_send_proactive_touch(
    db_pool: Any,
    identifier: str,
    *,
    source: str,
    channel_pref: str = "email",
    sensitivity: str = "routine",
    crystal_id: Optional[str] = None,
) -> PolicyDecision:
    """
    Fail-closed gate. ``identifier`` may be username or hardware_id.
    """
    if not policy_enabled():
        return PolicyDecision(allowed=True, reason="policy_disabled")

    if not db_pool or not identifier:
        return PolicyDecision(allowed=False, reason="skipped_gate_error")

    try:
        from app.services._identity_resolver import resolve_username

        username = await resolve_username(db_pool, identifier)
        if not username:
            return PolicyDecision(allowed=False, reason="skipped_trial")

        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT username, hardware_id, role, tier, profile_data
                FROM users
                WHERE username = $1 OR hardware_id = $1 OR id::text = $1
                LIMIT 1
                """,
                identifier,
            )
            if not row:
                return PolicyDecision(allowed=False, reason="skipped_trial")

            pd = _profile_data(row["profile_data"])
            tier = (row.get("tier") or pd.get("tier") or "").lower()
            if tier == "public_trial" or pd.get("public_trial") is True:
                return PolicyDecision(allowed=False, reason="skipped_trial")

            # SI suppression window
            hours = _si_suppression_hours()
            si_row = await conn.fetchrow(
                """
                SELECT 1 FROM sensitive_bridge_log
                WHERE user_id = $1
                  AND event_type = 'coach_alert_dispatched'
                  AND occurred_at >= NOW() - ($2::int * INTERVAL '1 hour')
                LIMIT 1
                """,
                username,
                hours,
            )
            if si_row:
                return PolicyDecision(allowed=False, reason="skipped_si_window")

            if not pd.get("proactive_presence_consent"):
                return PolicyDecision(allowed=False, reason="skipped_consent")

            if sensitivity == "sensitive":
                return PolicyDecision(allowed=False, reason="skipped_sensitive")

            if crystal_id:
                # id is SERIAL; also accept content_hash / uuid-looking strings
                cid = str(crystal_id).strip()
                crystal = None
                if cid.isdigit():
                    crystal = await conn.fetchrow(
                        """
                        SELECT scope FROM nate_intelligence_crystals
                        WHERE id = $1::int
                        LIMIT 1
                        """,
                        int(cid),
                    )
                else:
                    crystal = await conn.fetchrow(
                        """
                        SELECT scope FROM nate_intelligence_crystals
                        WHERE content_hash = $1
                           OR id::text = $1
                        LIMIT 1
                        """,
                        cid,
                    )
                if crystal and crystal["scope"] in ("admin_only", "archived"):
                    return PolicyDecision(allowed=False, reason="skipped_gate_error")

            # Timezone + quiet hours
            tz_name = (pd.get("timezone") or "UTC").strip() or "UTC"
            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                logger.warning("proactive_touch_policy: invalid timezone %r, using UTC", tz_name)
                tz = ZoneInfo("UTC")
            local_now = datetime.now(timezone.utc).astimezone(tz).time()
            q_start, q_end = _quiet_hours()
            if not (q_start <= local_now <= q_end):
                return PolicyDecision(allowed=False, reason="skipped_quiet_hours")

            adaptation = pd.get("proactive_touch_adaptation") or {}
            if isinstance(adaptation, str):
                try:
                    adaptation = json.loads(adaptation)
                except Exception:
                    adaptation = {}
            paused_until = adaptation.get("paused_until")
            if paused_until:
                try:
                    pu = datetime.fromisoformat(str(paused_until).replace("Z", "+00:00"))
                    if pu.tzinfo is None:
                        pu = pu.replace(tzinfo=timezone.utc)
                    if pu > datetime.now(timezone.utc):
                        return PolicyDecision(allowed=False, reason="skipped_paused")
                except Exception:
                    pass

            hw_key = row["hardware_id"] or username
            day_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM nate_proactive_touches
                WHERE user_id IN ($1, $2)
                  AND status IN ('sent', 'responded', 'ignored')
                  AND created_at > NOW() - INTERVAL '1 day'
                """,
                username,
                hw_key,
            )
            if day_count and int(day_count) >= _max_per_day():
                return PolicyDecision(allowed=False, reason="skipped_budget")

            week_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM nate_proactive_touches
                WHERE user_id IN ($1, $2)
                  AND status IN ('sent', 'responded', 'ignored')
                  AND created_at > NOW() - INTERVAL '7 days'
                """,
                username,
                hw_key,
            )
            if week_count and int(week_count) >= _max_per_week():
                return PolicyDecision(allowed=False, reason="skipped_budget")

            channel_override = None
            ceiling = adaptation.get("channel_ceiling")
            if ceiling == "in_app":
                channel_override = "in_app"
            elif channel_pref in ("sms", "email") and ceiling == "in_app":
                channel_override = "in_app"

            return PolicyDecision(allowed=True, reason="ok", channel_override=channel_override)

    except Exception as e:
        logger.warning("proactive_touch_policy: gate failed (fail-closed): %s", e)
        return PolicyDecision(allowed=False, reason="skipped_gate_error")


async def record_skipped_touch(
    db_pool: Any,
    identifier: str,
    *,
    source_agent: str,
    reason: str,
    touch_type: str = "proactive",
    content: str = "",
) -> None:
    """Audit row when gate denies a would-be touch."""
    if not db_pool:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO nate_proactive_touches
                    (user_id, source_agent, touch_type, channel, content, status)
                VALUES ($1, $2, $3, 'in_app', $4, $5)
                """,
                identifier,
                source_agent,
                touch_type,
                content[:2000] if content else "",
                reason if reason.startswith("skipped_") else f"skipped_{reason}",
            )
    except Exception as e:
        logger.warning("proactive_touch_policy: record_skipped_touch failed: %s", e)
