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
                SELECT id, username, reason, cadence_hours, opened_at, expires_at, opened_by, metadata
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


def _p0_sla_minutes() -> int:
    raw = os.getenv("P0_COACH_SLA_MINUTES", "5").strip()
    if raw.isdigit():
        return max(1, min(60, int(raw)))
    return 5


async def mark_windows_coach_reviewed(
    db_pool,
    window_ids: List[int],
    *,
    coach_username: str = "",
) -> None:
    """Stamp coach review on active windows (clears P0 SLA clock). QUANTUM-CRYSTAL-ARCH."""
    if not db_pool or not window_ids:
        return
    import json

    ids = [int(i) for i in window_ids if i is not None]
    if not ids:
        return
    patch = json.dumps(
        {
            "coach_reviewed_at": datetime.now(timezone.utc).isoformat(),
            "coach_reviewed_by": (coach_username or "")[:64],
        }
    )
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE checkin_risk_windows
                   SET metadata = COALESCE(metadata, '{}'::jsonb) || $1::jsonb
                 WHERE id = ANY($2::bigint[])
                   AND closed_at IS NULL
                """,
                patch,
                ids,
            )
    except Exception as e:
        logger.warning("checkin_risk_windows: mark reviewed failed: %s", e)


async def sweep_p0_coach_sla(db_pool) -> int:
    """Re-alert coach (+ admin activity) when post_p0 window exceeds SLA without review.

    Returns number of windows escalated. QUANTUM-CRYSTAL-ARCH.
    """
    if not risk_windows_enabled() or not db_pool:
        return 0
    minutes = _p0_sla_minutes()
    escalated = 0
    import json

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, username, reason, opened_at, metadata, opened_by
                  FROM checkin_risk_windows
                 WHERE reason = $1
                   AND expires_at > NOW()
                   AND closed_at IS NULL
                   AND opened_at <= NOW() - ($2::int * INTERVAL '1 minute')
                   AND COALESCE(metadata->>'sla_escalated', 'false') NOT IN ('true', '1')
                   AND COALESCE(metadata->>'coach_reviewed_at', '') = ''
                 LIMIT 25
                """,
                REASON_POST_P0,
                minutes,
            )
        for row in rows:
            username = row["username"]
            wid = int(row["id"])
            try:
                async with db_pool.acquire() as conn:
                    tprof = await conn.fetchrow(
                        """
                        SELECT username, profile_data, role, hardware_id
                          FROM users WHERE username = $1 AND deleted_at IS NULL
                        """,
                        username,
                    )
                if not tprof:
                    continue
                from app.services.coach_handoff import _resolve_assigned_coach_username
                from app.services.sensitive_alert_dispatcher import dispatch_sensitive_alert

                coach_uname = await _resolve_assigned_coach_username(
                    db_pool,
                    {
                        "username": tprof["username"],
                        "role": tprof["role"],
                        "profile_data": tprof["profile_data"],
                        "hardware_id": tprof.get("hardware_id"),
                    },
                )
                if coach_uname:
                    await dispatch_sensitive_alert(
                        db_pool=db_pool,
                        client_username=username,
                        coach_username=coach_uname,
                        risk_level="critical",
                        reason=(
                            f"P0 coach SLA breach ({minutes}m) — "
                            "active post-crisis risk window needs review."
                        ),
                        keywords=["p0_sla", "risk_window"],
                        session_id=None,
                        family_id=None,
                        raw_context=(
                            "Automated SLA escalation. No new client content. "
                            "Open Risk windows in Coach portal."
                        ),
                        alert_type="p0_sla_breach",
                    )
                patch = json.dumps(
                    {
                        "sla_escalated": True,
                        "sla_escalated_at": datetime.now(timezone.utc).isoformat(),
                        "sla_minutes": minutes,
                    }
                )
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE checkin_risk_windows
                           SET metadata = COALESCE(metadata, '{}'::jsonb) || $1::jsonb
                         WHERE id = $2
                        """,
                        patch,
                        wid,
                    )
                    await conn.execute(
                        """
                        INSERT INTO skyeye_activity (type, content, platform, created_at)
                        VALUES (
                            'p0_sla_breach',
                            $1, 'system', NOW()
                        )
                        """,
                        f"username={username} window_id={wid} minutes={minutes} "
                        f"coach={coach_uname or 'none'}",
                    )
                escalated += 1
            except Exception as one_e:
                logger.warning("p0_sla escalate failed user=%s: %s", username, one_e)
    except Exception as e:
        logger.warning("checkin_risk_windows: p0 sla sweep failed: %s", e)
    if escalated:
        logger.info("checkin_risk_windows: p0 sla escalated=%s", escalated)
    return escalated


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
    # QUANTUM-CRYSTAL-ARCH — SI → post_p0; other-harm → post_p1
    reason = REASON_POST_P0
    if "violence" in (alert_type or "").lower():
        reason = REASON_POST_P1
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
                      AND trigger_date BETWEEN (CURRENT_DATE - 1)
                                           AND (CURRENT_DATE + 1))
                     OR
                     (recurring_annually = TRUE
                      AND make_date(
                            EXTRACT(YEAR FROM CURRENT_DATE)::int,
                            EXTRACT(MONTH FROM trigger_date)::int,
                            LEAST(EXTRACT(DAY FROM trigger_date)::int, 28)
                          ) BETWEEN (CURRENT_DATE - 1) AND (CURRENT_DATE + 1))
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
    import os

    cooldown_h = 12
    raw_cd = os.getenv("FAMILY_CONCERN_FLAG_COOLDOWN_HOURS", "12").strip()
    if raw_cd.isdigit():
        cooldown_h = max(1, int(raw_cd))

    try:
        async with db_pool.acquire() as conn:
            recent = await conn.fetchrow(
                """
                SELECT id FROM family_concern_flags
                 WHERE target_username = $1 AND flagger_username = $2
                   AND created_at >= NOW() - ($3::int * INTERVAL '1 hour')
                 LIMIT 1
                """,
                target_username,
                flagger_username,
                cooldown_h,
            )
            if recent:
                return {
                    "status": "error",
                    "reason": "cooldown",
                    "cooldown_hours": cooldown_h,
                }
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
        # QUANTUM-CRYSTAL-ARCH — notify assigned coach (no message content)
        try:
            async with db_pool.acquire() as conn:
                tprof = await conn.fetchrow(
                    "SELECT username, profile_data, role FROM users WHERE username = $1",
                    target_username,
                )
            if tprof:
                from app.services.coach_handoff import _resolve_assigned_coach_username
                from app.services.sensitive_alert_dispatcher import dispatch_sensitive_alert

                coach_uname = await _resolve_assigned_coach_username(
                    db_pool,
                    {
                        "username": tprof["username"],
                        "role": tprof["role"],
                        "profile_data": tprof["profile_data"],
                    },
                )
                if coach_uname:
                    await dispatch_sensitive_alert(
                        db_pool=db_pool,
                        client_username=target_username,
                        coach_username=coach_uname,
                        risk_level="elevated",
                        reason="Family concern flag raised (no content shared).",
                        keywords=["family_concern"],
                        session_id=None,
                        family_id=None,
                        raw_context="Family member flagged concern. Content withheld by design.",
                        alert_type="family_concern_flag",
                    )
        except Exception as _cn_e:
            logger.warning("family_concern coach notify failed: %s", _cn_e)
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
