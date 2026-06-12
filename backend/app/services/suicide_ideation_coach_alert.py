"""Universal suicidal/self-harm language → assigned coach alert (feature-flagged)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from app.services.coach_handoff import _resolve_assigned_coach_username
from app.services.suicide_ideation_lexicon import match_user_text

logger = logging.getLogger(__name__)

_EVENT_TYPE = "coach_alert_dispatched"
_ALERT_TYPE = "suicidal_ideation_escalation"


def _flag_enabled() -> bool:
    return os.getenv("ENABLE_UNIVERSAL_SI_COACH_ALERT", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _dedup_hours() -> int:
    raw = os.getenv("SI_COACH_ALERT_DEDUP_HOURS", "24").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 24


async def _resolve_client_username(db_pool, profile: Dict[str, Any]) -> Optional[str]:
    username = (profile.get("username") or "").strip()
    if username:
        return username
    hardware_id = (profile.get("hardware_id") or "").strip()
    if not hardware_id:
        return None
    try:
        from app.services._identity_resolver import resolve_username

        return await resolve_username(db_pool, hardware_id)
    except Exception as e:
        logger.warning("[SI_COACH_ALERT] identity resolve failed: %s", e)
        return None


async def _recent_escalation_in_window(db_pool, client_username: str) -> bool:
    hours = _dedup_hours()
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT 1
                  FROM sensitive_bridge_log
                 WHERE user_id = $1
                   AND event_type = 'coach_alert_dispatched'
                   AND occurred_at >= NOW() - ($2::int * INTERVAL '1 hour')
                 LIMIT 1
                """,
                client_username,
                hours,
            )
        return row is not None
    except Exception as e:
        logger.warning("[SI_COACH_ALERT] dedup check failed: %s", e)
        return False


async def _build_recent_context(
    db_pool,
    *,
    client_username: str,
    hardware_id: Optional[str],
    user_text: str,
) -> str:
    user_ids: List[str] = []
    for uid in (client_username, hardware_id):
        if uid and uid not in user_ids:
            user_ids.append(uid)
    lines: List[str] = [f'Current message: "{(user_text or "")[:500]}"']
    if db_pool and user_ids:
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT user_text, ai_text, created_at
                      FROM conversation_history
                     WHERE user_id = ANY($1::text[])
                     ORDER BY created_at DESC
                     LIMIT 4
                    """,
                    user_ids,
                )
            if rows:
                lines.append("Recent conversation excerpts:")
                for row in reversed(rows):
                    ut = (row["user_text"] or "").strip()
                    at = (row["ai_text"] or "").strip()
                    if ut:
                        lines.append(f'Client: "{ut[:240]}"')
                    if at:
                        lines.append(f'Little Nate: "{at[:240]}"')
        except Exception as e:
            logger.warning("[SI_COACH_ALERT] context fetch failed: %s", e)
    return "\n".join(lines)[:7500]


async def _emit_audit(
    db_pool,
    *,
    client_username: str,
    coach_username: str,
    turn_id: str,
    matched: List[str],
    notification_id: int,
) -> None:
    payload = {
        "alert_type": _ALERT_TYPE,
        "turn_id": turn_id,
        "coach_username": coach_username,
        "notification_id": notification_id,
        "matched_phrases": matched,
        # QUANTUM-CRYSTAL-ARCH: redaction contract — alert content lives in the
        # coach_notifications row; the audit log carries only a reference.
        "payload_ref": f"coach_notifications:{notification_id}",
    }
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sensitive_bridge_log
                    (user_id, session_id, event_type, event_severity,
                     payload_json, decision_summary, recorded_by,
                     access_classification, pii_screened_at, redaction_pass_count)
                VALUES ($1, NULL, $2, 'critical',
                        $3::jsonb, NULL, 'si_coach_alert', 'clinician_and_admin', NOW(), 1)
                """,
                client_username,
                _EVENT_TYPE,
                json.dumps(payload),
            )
    except Exception as e:
        logger.error("[SI_COACH_ALERT] audit insert failed: %s", e)


async def maybe_dispatch_si_coach_alert(
    db_pool,
    profile: Dict[str, Any],
    user_text: str,
    *,
    turn_id: str = "",
) -> Dict[str, Any]:
    """Detect SI language in client chat and notify assigned coach when enabled."""
    if not _flag_enabled():
        return {"status": "disabled"}
    if not db_pool:
        return {"status": "skipped", "reason": "no_db_pool"}
    if (profile.get("role") or "").upper() != "CLIENT":
        return {"status": "skipped", "reason": "not_client"}
    text = user_text or ""
    if text.startswith("[DOJO SIMULATION") or text.startswith("[SEARCH SYNTHESIS]"):
        return {"status": "skipped", "reason": "simulation_or_synthesis"}

    matched = match_user_text(text)
    if not matched:
        return {"status": "no_match"}

    client_username = await _resolve_client_username(db_pool, profile)
    if not client_username:
        logger.warning("[SI_COACH_ALERT] no canonical username for profile")
        return {"status": "error", "reason": "identity_unresolved"}

    if await _recent_escalation_in_window(db_pool, client_username):
        logger.info("[SI_COACH_ALERT] dedup skip user=%s", client_username)
        return {"status": "duplicate", "matched": matched}

    coach_username = await _resolve_assigned_coach_username(db_pool, profile)
    if not coach_username:
        logger.warning("[SI_COACH_ALERT] no assigned coach for user=%s", client_username)
        return {"status": "error", "reason": "no_assigned_coach", "matched": matched}

    hardware_id = (profile.get("hardware_id") or "").strip() or None
    raw_context = await _build_recent_context(
        db_pool,
        client_username=client_username,
        hardware_id=hardware_id,
        user_text=text,
    )
    reason = "Suicidal/self-harm language detected in client message."

    receipt: Dict[str, Any] = {}
    try:
        from app.services.sensitive_alert_dispatcher import dispatch_sensitive_alert

        receipt = await dispatch_sensitive_alert(
            db_pool=db_pool,
            client_username=client_username,
            coach_username=coach_username,
            risk_level="critical",
            reason=reason,
            keywords=matched,
            session_id=None,
            family_id=None,
            raw_context=raw_context,
            alert_type=_ALERT_TYPE,
        )
    except Exception as e:
        logger.error("[SI_COACH_ALERT] dispatch failed user=%s: %s", client_username, e)
        return {"status": "error", "reason": "dispatch_failed", "matched": matched}

    notification_id = int(receipt.get("notification_id") or 0)
    await _emit_audit(
        db_pool,
        client_username=client_username,
        coach_username=coach_username,
        turn_id=turn_id or "",
        matched=matched,
        notification_id=notification_id,
    )
    logger.info(
        "[SI_COACH_ALERT] dispatched user=%s coach=%s phrases=%s nid=%s",
        client_username,
        coach_username,
        matched,
        notification_id,
    )
    return {
        "status": "dispatched",
        "matched": matched,
        "coach_username": coach_username,
        "notification_id": notification_id,
        "coach_notified": bool(receipt.get("coach_notified")),
    }
