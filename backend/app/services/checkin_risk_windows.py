"""Post-crisis / anniversary check-in risk windows — QUANTUM-CRYSTAL-ARCH.

Separate from NateCheckInAgent outcome backoff (which only stretches thresholds).
Active windows SHORTEN silence thresholds for a time-boxed period, then expire.
Snooze / safe_silence still win.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.population_profile import risk_windows_enabled

logger = logging.getLogger(__name__)

REASON_POST_P0 = "post_p0"
REASON_POST_P1 = "post_p1"
REASON_TRIGGER_DATE = "trigger_date"
REASON_FAMILY_CONCERN = "family_concern"
REASON_CRITICAL_INCIDENT = "critical_incident"

DEFAULT_CADENCE_HOURS = {
    REASON_POST_P0: 24,
    REASON_POST_P1: 24,
    REASON_TRIGGER_DATE: 24,
    REASON_FAMILY_CONCERN: 36,
    REASON_CRITICAL_INCIDENT: 24,
}

DEFAULT_TTL_DAYS = {
    REASON_POST_P0: 7,
    REASON_POST_P1: 5,
    REASON_TRIGGER_DATE: 7,
    REASON_FAMILY_CONCERN: 5,
    REASON_CRITICAL_INCIDENT: 7,
}


def _ttl_days(reason: str) -> int:
    raw = os.getenv(f"CHECKIN_RISK_WINDOW_TTL_{reason.upper()}_DAYS", "")
    if raw.strip().isdigit():
        return max(1, int(raw.strip()))
    return DEFAULT_TTL_DAYS.get(reason, 7)


def _cadence(reason: str) -> int:
    raw = os.getenv(f"CHECKIN_RISK_WINDOW_CADENCE_{reason.upper()}_HOURS", "")
    if raw.strip().isdigit():
        return max(6, int(raw.strip()))
    return DEFAULT_CADENCE_HOURS.get(reason, 24)


async def open_risk_window(
    db_pool,
    *,
    username: str,
    reason: str,
    opened_by: str = "system",
    metadata: Optional[Dict[str, Any]] = None,
    cadence_hours: Optional[int] = None,
    ttl_days: Optional[int] = None,
) -> Optional[int]:
    """Open or refresh an active risk window. Returns row id or None."""
    if not risk_windows_enabled() or not db_pool or not username:
        return None
    reason = (reason or "").strip().lower()
    if reason not in DEFAULT_CADENCE_HOURS:
        logger.warning("checkin_risk_windows: unknown reason %s", reason)
        return None
    cadence = cadence_hours or _cadence(reason)
    days = ttl_days or _ttl_days(reason)
    import json

    meta_json = json.dumps(metadata or {})
    try:
        async with db_pool.acquire() as conn:
            # Close overlapping same-reason windows first (refresh)
            await conn.execute(
                """
                UPDATE checkin_risk_windows
                   SET expires_at = NOW(), closed_at = NOW(), close_reason = 'superseded'
                 WHERE username = $1 AND reason = $2
                   AND expires_at > NOW() AND closed_at IS NULL
                """,
                username,
                reason,
            )
            row = await conn.fetchrow(
                """
                INSERT INTO checkin_risk_windows
                    (username, reason, cadence_hours, expires_at, opened_by, metadata)
                VALUES (
                    $1, $2, $3,
                    NOW() + ($4::int * INTERVAL '1 day'),
                    $5, $6::jsonb
                )
                RETURNING id
                """,
                username,
                reason,
                cadence,
                days,
                opened_by,
                meta_json,
            )
            wid = int(row["id"]) if row else None
            try:
                await conn.execute(
                    """
                    INSERT INTO skyeye_activity (type, content, platform, created_at)
                    VALUES (
                        'checkin_risk_window_opened',
                        $1, 'system', NOW()
                    )
                    """,
                    f"username={username} reason={reason} cadence_h={cadence} ttl_d={days} id={wid}",
                )
            except Exception:
                pass
            return wid
    except Exception as e:
        logger.warning("checkin_risk_windows: open failed for %s: %s", username, e)
        return None


async def get_active_window(
    db_pool,
    username: str,
) -> Optional[Dict[str, Any]]:
    """Return the tightest (lowest cadence_hours) active window, or None."""
    if not risk_windows_enabled() or not db_pool or not username:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, username, reason, cadence_hours, opened_at, expires_at,
                       opened_by, metadata
                  FROM checkin_risk_windows
                 WHERE username = $1
                   AND expires_at > NOW()
                   AND closed_at IS NULL
                 ORDER BY cadence_hours ASC, opened_at DESC
                 LIMIT 1
                """,
                username,
            )
        if not row:
            return None
        return dict(row)
    except Exception as e:
        logger.warning("checkin_risk_windows: get_active failed for %s: %s", username, e)
        return None


async def list_active_windows_for_coach(
    db_pool,
    *,
    client_usernames: List[str],
) -> List[Dict[str, Any]]:
    if not db_pool or not client_usernames:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, username, reason, cadence_hours, opened_at, expires_at, opened_by
                  FROM checkin_risk_windows
                 WHERE username = ANY($1::text[])
                   AND expires_at > NOW()
                   AND closed_at IS NULL
                 ORDER BY expires_at ASC
                """,
                client_usernames,
            )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("checkin_risk_windows: coach list failed: %s", e)
        return []


async def apply_risk_window_thresholds(
    db_pool,
    username: str,
    *,
    default_alert_hours: float,
    default_outreach_hours: float,
) -> Dict[str, Any]:
    """
    If an active window exists, return shortened thresholds.
    Does NOT modify backoff multipliers — parallel exception path.
    """
    win = await get_active_window(db_pool, username)
    if not win:
        return {
            "active": False,
            "alert_hours": default_alert_hours,
            "outreach_hours": default_outreach_hours,
            "window": None,
        }
    cadence = float(win.get("cadence_hours") or 24)
    # Coach alert slightly before client outreach
    alert_h = max(6.0, cadence * 0.75)
    outreach_h = max(8.0, cadence)
    return {
        "active": True,
        "alert_hours": alert_h,
        "outreach_hours": outreach_h,
        "window": win,
        "reason": win.get("reason"),
    }


async def open_post_crisis_window(
    db_pool,
    username: str,
    *,
    alert_type: str = "",
) -> Optional[int]:
    reason = REASON_POST_P0
    if "violence" in (alert_type or "").lower():
        reason = REASON_POST_P0
    return await open_risk_window(
        db_pool,
        username=username,
        reason=reason,
        opened_by="si_coach_alert",
        metadata={"alert_type": alert_type},
    )


async def sweep_trigger_date_windows(db_pool) -> int:
    """Open trigger_date windows for dates within ±7 days. Returns count opened."""
    if not risk_windows_enabled() or not db_pool:
        return 0
    opened = 0
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_id, date_type, trigger_date, recurring_annually
                  FROM user_trigger_dates
                 WHERE active = TRUE
                   AND (
                     (recurring_annually = FALSE
                      AND trigger_date BETWEEN (CURRENT_DATE - 3)
                                           AND (CURRENT_DATE + 7))
                     OR
                     (recurring_annually = TRUE
                      AND make_date(
                            EXTRACT(YEAR FROM CURRENT_DATE)::int,
                            EXTRACT(MONTH FROM trigger_date)::int,
                            LEAST(EXTRACT(DAY FROM trigger_date)::int, 28)
                          ) BETWEEN (CURRENT_DATE - 3) AND (CURRENT_DATE + 7))
                   )
                """
            )
        for row in rows:
            uid = row["user_id"]
            wid = await open_risk_window(
                db_pool,
                username=uid,
                reason=REASON_TRIGGER_DATE,
                opened_by="trigger_date_sweep",
                metadata={
                    "date_type": row.get("date_type"),
                    "trigger_date": str(row.get("trigger_date")),
                },
            )
            if wid:
                opened += 1
    except Exception as e:
        logger.warning("checkin_risk_windows: trigger sweep failed: %s", e)
    return opened


async def flag_family_concern(
    db_pool,
    *,
    target_username: str,
    flagger_username: str,
    relationship: str = "family",
    note_redacted: str = "",
) -> Dict[str, Any]:
    """
    Family member flags concern. Stores WHO/WHEN only — never conversation content.
    Opens a family_concern risk window.
    """
    if not db_pool:
        return {"status": "error", "reason": "no_db"}
    import json

    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO family_concern_flags
                    (target_username, flagger_username, relationship, metadata)
                VALUES ($1, $2, $3, $4::jsonb)
                RETURNING id, created_at
                """,
                target_username,
                flagger_username,
                (relationship or "family")[:64],
                json.dumps({"note_present": bool(note_redacted)}),
            )
        wid = await open_risk_window(
            db_pool,
            username=target_username,
            reason=REASON_FAMILY_CONCERN,
            opened_by=f"family:{flagger_username}",
            metadata={"flag_id": int(row["id"]) if row else None},
        )
        return {
            "status": "ok",
            "flag_id": int(row["id"]) if row else None,
            "window_id": wid,
            # Nate must never mention that a family flag occurred
            "nate_disclosure": False,
        }
    except Exception as e:
        logger.warning("family_concern_flag failed: %s", e)
        return {"status": "error", "reason": str(e)}
