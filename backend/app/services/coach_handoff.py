"""Client-initiated coach handoff acceptance (adaptive mode UI)."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_HANDOFF_SOURCE = "client_accepted"


async def _handoff_already_accepted(db_pool, client_username: str, turn_id: str) -> bool:
    if not db_pool or not client_username or not turn_id:
        return False
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT 1
                  FROM sensitive_bridge_log
                 WHERE user_id = $1
                   AND event_type = 'coach_handoff_emitted'
                   AND payload_json->>'handoff_source' = $2
                   AND payload_json->>'turn_id' = $3
                 LIMIT 1
                """,
                client_username,
                _HANDOFF_SOURCE,
                turn_id,
            )
        return row is not None
    except Exception as e:
        logger.warning("coach_handoff: idempotency check failed: %s", e)
        return False


async def _resolve_assigned_coach_username(
    db_pool, client_profile: Dict[str, Any]
) -> Optional[str]:
    username = (client_profile.get("username") or "").strip()
    if not username:
        return None
    for key in ("assigned_coach", "coach_username"):
        v = client_profile.get(key)
        if v and str(v).strip():
            return str(v).strip()
    cid = client_profile.get("coach_id") or client_profile.get("assigned_coach_id")
    if cid and str(cid).strip() and db_pool:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT username FROM users
                     WHERE hardware_id = $1 AND role = 'COACH'
                     LIMIT 1
                    """,
                    str(cid).strip(),
                )
            if row and row["username"]:
                return str(row["username"]).strip()
        except Exception:
            pass
    if not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT profile_data FROM users WHERE username = $1",
                username,
            )
    except Exception:
        return None
    if not row:
        return None
    pd = row["profile_data"] or {}
    if isinstance(pd, str):
        try:
            pd = json.loads(pd)
        except Exception:
            pd = {}
    for key in ("assigned_coach", "coach_username"):
        v = pd.get(key)
        if v and str(v).strip():
            return str(v).strip()
    return None


def _first_name(client_profile: Dict[str, Any]) -> str:
    pd = client_profile.get("profile_data")
    if isinstance(pd, str):
        try:
            pd = json.loads(pd)
        except Exception:
            pd = {}
    if not isinstance(pd, dict):
        pd = {}
    raw = client_profile.get("name") or pd.get("name") or client_profile.get("username") or "Client"
    if isinstance(raw, str):
        part = raw.strip().split()[0] if raw.strip() else "Client"
        return part[:40]
    return "Client"


def _trim_words(text: str, max_words: int = 300) -> str:
    words = (text or "").split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words])


async def generate_handoff_summary(
    db_pool,
    username: str,
    turn_id: str,
    *,
    hardware_id: Optional[str] = None,
    client_profile: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a 200–300 word factual handoff summary from conversation_history."""
    first = _first_name(client_profile or {"username": username})
    user_ids: List[str] = []
    for uid in (username, hardware_id):
        if uid and uid not in user_ids:
            user_ids.append(uid)

    rows: List[Any] = []
    if db_pool and user_ids:
        try:
            async with db_pool.acquire() as conn:
                anchor = await conn.fetchrow(
                    """
                    SELECT id, created_at
                      FROM conversation_history
                     WHERE user_id = ANY($1::text[])
                       AND metadata->>'turn_id' = $2
                     ORDER BY created_at DESC
                     LIMIT 1
                    """,
                    user_ids,
                    turn_id,
                )
                if anchor:
                    rows = await conn.fetch(
                        """
                        SELECT user_text, ai_text, created_at
                          FROM conversation_history
                         WHERE user_id = ANY($1::text[])
                           AND created_at >= $2 - INTERVAL '45 minutes'
                           AND created_at <= $2 + INTERVAL '10 minutes'
                         ORDER BY created_at ASC
                        """,
                        user_ids,
                        anchor["created_at"],
                    )
                if not rows:
                    rows = await conn.fetch(
                        """
                        SELECT user_text, ai_text, created_at
                          FROM conversation_history
                         WHERE user_id = ANY($1::text[])
                         ORDER BY created_at DESC
                         LIMIT 6
                        """,
                        user_ids,
                    )
                    rows = list(reversed(rows))
        except Exception as e:
            logger.warning("coach_handoff: summary history fetch failed: %s", e)

    parts: List[str] = [
        f"{first} accepted a coach handoff from Little Nate and asked to reach their assigned coach.",
    ]
    if rows:
        parts.append("Recent conversation excerpts (factual):")
        for r in rows:
            ut = (r["user_text"] or "").strip()
            at = (r["ai_text"] or "").strip()
            if ut:
                parts.append(f'{first} said: "{_trim_words(ut, 80)}"')
            if at:
                parts.append(f'Little Nate replied: "{_trim_words(at, 80)}"')
    else:
        parts.append(
            f"No stored transcript was found for turn {turn_id}; "
            f"{first} still requested coach contact from the in-app handoff prompt."
        )

    parts.append(
        "This is a client-initiated, non-crisis handoff. "
        "No clinical conclusions are included in this summary."
    )

    summary = " ".join(parts)
    words = summary.split()
    if len(words) < 200:
        pad = (
            "The client was using the Sanctuary chat when the handoff offer appeared. "
            "They tapped Reach out to notify their coach with this conversation context. "
            "Please follow up when you are available to continue the thread they raised. "
            "This summary is limited to factual excerpts from the recent chat transcript "
            "and does not include diagnostic labels or treatment recommendations. "
        )
        while len(words) < 200 and len(words) < 400:
            summary = summary + " " + pad
            words = summary.split()
    return _trim_words(summary, 300)


async def _emit_handoff_audit(
    db_pool,
    *,
    client_username: str,
    turn_id: str,
    coach_username: str,
    notification_id: int,
    summary_excerpt: str,
) -> Optional[int]:
    payload = {
        "handoff_source": _HANDOFF_SOURCE,
        "turn_id": turn_id,
        "coach_username": coach_username,
        "notification_id": notification_id,
        "alert_type": "client_initiated_handoff",
        "summary_word_count": len((summary_excerpt or "").split()),
    }
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO sensitive_bridge_log
                    (user_id, session_id, event_type, event_severity,
                     payload_json, decision_summary, recorded_by,
                     access_classification, pii_screened_at)
                VALUES ($1, NULL, 'coach_handoff_emitted', 'moderate',
                        $2::jsonb, NULL, 'coach_handoff', 'clinician_and_admin', NOW())
                RETURNING id
                """,
                client_username,
                json.dumps(payload),
            )
            return int(row["id"]) if row else None
    except Exception as e:
        logger.error("coach_handoff: audit insert failed: %s", e)
        return None


async def process_coach_handoff_accepted(
    db_pool,
    client_profile: Dict[str, Any],
    turn_id: str,
    *,
    adaptive_state=None,
) -> Dict[str, Any]:
    """Handle explicit client acceptance of offer_coach_handoff."""
    turn_id = (turn_id or "").strip()
    client_username = (client_profile.get("username") or "").strip()
    if not turn_id or not client_username:
        return {"status": "error", "reason": "missing_turn_or_user", "turn_id": turn_id}

    if await _handoff_already_accepted(db_pool, client_username, turn_id):
        return {"status": "duplicate", "turn_id": turn_id}

    if adaptive_state is not None:
        try:
            from app.services.little_nate_adaptive import handle_coach_offer_response

            outcome = handle_coach_offer_response(adaptive_state, "yes")
            if outcome != "accepted":
                logger.info(
                    "coach_handoff: handle_coach_offer_response returned %s for %s",
                    outcome,
                    client_username,
                )
        except Exception as e:
            logger.warning("coach_handoff: adaptive acceptance hook failed: %s", e)

    coach_username = await _resolve_assigned_coach_username(db_pool, client_profile)
    if not coach_username:
        return {"status": "error", "reason": "no_assigned_coach", "turn_id": turn_id}

    hardware_id = (client_profile.get("hardware_id") or "").strip() or None
    summary = await generate_handoff_summary(
        db_pool,
        client_username,
        turn_id,
        hardware_id=hardware_id,
        client_profile=client_profile,
    )

    reason = (
        f"{_first_name(client_profile)} accepted a coach handoff from Little Nate "
        f"(turn_id={turn_id})."
    )

    receipt: Dict[str, Any] = {
        "event_id": 0,
        "coach_notified": False,
        "notification_id": 0,
        "email_sent": False,
        "redacted": False,
    }
    try:
        from app.services.sensitive_alert_dispatcher import dispatch_sensitive_alert

        receipt = await dispatch_sensitive_alert(
            db_pool=db_pool,
            client_username=client_username,
            coach_username=coach_username,
            risk_level="high",
            reason=reason,
            keywords=["client_initiated_handoff", turn_id],
            session_id=None,
            family_id=None,
            raw_context=summary,
            alert_type="client_initiated_handoff",
        )
    except Exception as e:
        logger.error("coach_handoff: dispatch_sensitive_alert failed: %s", e)
        return {"status": "error", "reason": "dispatch_failed", "turn_id": turn_id}

    notification_id = int(receipt.get("notification_id") or 0)
    audit_id = await _emit_handoff_audit(
        db_pool,
        client_username=client_username,
        turn_id=turn_id,
        coach_username=coach_username,
        notification_id=notification_id,
        summary_excerpt=summary[:500],
    )

    return {
        "status": "accepted",
        "turn_id": turn_id,
        "coach_username": coach_username,
        "notification_id": notification_id,
        "audit_id": audit_id or 0,
        "email_sent": bool(receipt.get("email_sent")),
        "coach_notified": bool(receipt.get("coach_notified")),
    }
