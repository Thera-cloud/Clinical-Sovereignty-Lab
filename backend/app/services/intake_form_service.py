"""Clinical intake service layer (DB + policy + audit)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.constants.intake_questions import (
    ALL_QUESTION_FIELDS,
    QUESTION_LABELS,
    SECTION1_ENUM_FIELDS,
    SECTION1_FIELDS,
    SECTION2_FIELDS,
)

logger = logging.getLogger("intake_form_service")

_STYLE_BLOCK_PATTERNS = (
    r"\bdiagnos(?:is|e|ed|ing)\b",
    r"\bptsd\b",
    r"\bbipolar\b",
    r"\bschizo\w*\b",
    r"\bborderline\b",
    r"\bself[- ]harm\b",
    r"\bsuicid\w*\b",
    r"\bhomicid\w*\b",
    r"\bmedicat(?:ion|e|ed|ing)\b",
)

_WALKTHROUGH_REWARD = 1000


def _coerce_profile_data(profile_data: Any) -> Dict[str, Any]:
    if isinstance(profile_data, dict):
        return profile_data
    if isinstance(profile_data, str):
        try:
            parsed = json.loads(profile_data)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _section_completion_percent(payload: Dict[str, Any], fields: List[str]) -> int:
    if not fields:
        return 0
    complete = sum(0 if _is_blank(payload.get(field)) else 1 for field in fields)
    return int(round((complete / len(fields)) * 100))


def validate_style_guidance_text(text: str) -> Tuple[bool, Optional[str]]:
    text = (text or "").strip()
    if not text:
        return True, None
    lowered = text.lower()
    for pattern in _STYLE_BLOCK_PATTERNS:
        if re.search(pattern, lowered):
            return False, "Style guidance must stay behavioral/relational and avoid clinical diagnosis language."
    return True, None


async def _resolve_username(conn, actor: Dict[str, Any]) -> Optional[str]:
    username = (actor.get("username") or "").strip()
    if username:
        return username
    hardware_id = (actor.get("hardware_id") or actor.get("user_id") or "").strip()
    if not hardware_id:
        return None
    return await conn.fetchval(
        "SELECT username FROM users WHERE hardware_id = $1 LIMIT 1",
        hardware_id,
    )


async def ensure_intake_row(conn, username: str, user_hardware_id: Optional[str]) -> None:
    await conn.execute(
        """
        INSERT INTO intake_form (user_id, user_hardware_id)
        VALUES ($1, $2)
        ON CONFLICT (user_id) DO NOTHING
        """,
        username,
        user_hardware_id,
    )


async def _recompute_statuses(conn, username: str) -> None:
    row = await conn.fetchrow(
        "SELECT * FROM intake_form WHERE user_id = $1",
        username,
    )
    if not row:
        return
    data = dict(row)
    s1_complete = all(not _is_blank(data.get(f)) for f in SECTION1_FIELDS)
    s2_complete = all(not _is_blank(data.get(f)) for f in SECTION2_FIELDS)
    s1_started = any(not _is_blank(data.get(f)) for f in SECTION1_FIELDS)
    s2_started = any(not _is_blank(data.get(f)) for f in SECTION2_FIELDS)
    s1_status = "complete" if s1_complete else "in_progress" if s1_started else "not_started"
    s2_status = "complete" if s2_complete else "in_progress" if s2_started else "not_started"

    await conn.execute(
        """
        UPDATE intake_form
        SET section_1_status = $2,
            section_1_completed_at = CASE
                WHEN $2 = 'complete' THEN COALESCE(section_1_completed_at, NOW())
                ELSE NULL
            END,
            section_2_status = $3,
            section_2_completed_at = CASE
                WHEN $3 = 'complete' THEN COALESCE(section_2_completed_at, NOW())
                ELSE NULL
            END,
            updated_at = NOW()
        WHERE user_id = $1
        """,
        username,
        s1_status,
        s2_status,
    )


async def _audit_write(
    conn,
    *,
    username: str,
    question_id: str,
    old_value: Any,
    new_value: Any,
    actor: str,
    actor_id: str,
    method: str,
    override_reason: Optional[str] = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO intake_form_audit (
            user_id, question_id, old_value, new_value, actor, actor_id, method, override_reason
        ) VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6, $7, $8)
        """,
        username,
        question_id,
        json.dumps(old_value),
        json.dumps(new_value),
        actor,
        actor_id,
        method,
        override_reason,
    )


async def get_client_intake(conn, username: str, hardware_id: Optional[str]) -> Dict[str, Any]:
    await ensure_intake_row(conn, username, hardware_id)
    row = await conn.fetchrow("SELECT * FROM intake_form WHERE user_id = $1", username)
    data = dict(row or {})
    data["section_1_completion_pct"] = _section_completion_percent(data, SECTION1_FIELDS)
    data["section_2_completion_pct"] = _section_completion_percent(data, SECTION2_FIELDS)
    return data


async def update_client_answer(
    conn,
    *,
    username: str,
    hardware_id: Optional[str],
    question_id: str,
    value: Any,
    actor_id: str,
    method: str = "self_service",
) -> Dict[str, Any]:
    if question_id not in ALL_QUESTION_FIELDS:
        raise ValueError("Unknown question_id")
    if question_id in SECTION1_ENUM_FIELDS and value not in SECTION1_ENUM_FIELDS[question_id]:
        raise ValueError(f"Invalid enum value for {question_id}")

    await ensure_intake_row(conn, username, hardware_id)
    old_value = await conn.fetchval(
        f"SELECT {question_id} FROM intake_form WHERE user_id = $1",
        username,
    )
    await conn.execute(
        f"UPDATE intake_form SET {question_id} = $2, updated_at = NOW() WHERE user_id = $1",
        username,
        value,
    )
    await _recompute_statuses(conn, username)
    await _audit_write(
        conn,
        username=username,
        question_id=question_id,
        old_value=old_value,
        new_value=value,
        actor="client",
        actor_id=actor_id,
        method=method,
    )
    return await get_client_intake(conn, username, hardware_id)


async def update_coach_section2_answer(
    conn,
    *,
    username: str,
    question_id: str,
    value: Any,
    coach_username: str,
) -> Dict[str, Any]:
    if question_id not in SECTION2_FIELDS:
        raise PermissionError("Coaches may edit section 2 only")
    old_value = await conn.fetchval(
        f"SELECT {question_id} FROM intake_form WHERE user_id = $1",
        username,
    )
    await conn.execute(
        f"UPDATE intake_form SET {question_id} = $2, updated_at = NOW() WHERE user_id = $1",
        username,
        value,
    )
    await _recompute_statuses(conn, username)
    await _audit_write(
        conn,
        username=username,
        question_id=question_id,
        old_value=old_value,
        new_value=value,
        actor="coach",
        actor_id=coach_username,
        method="coach_entry",
    )
    return dict(await conn.fetchrow("SELECT * FROM intake_form WHERE user_id = $1", username))


async def update_coach_style_guidance(
    conn,
    *,
    username: str,
    guidance: str,
    coach_username: str,
) -> Dict[str, Any]:
    ok, err = validate_style_guidance_text(guidance)
    if not ok:
        raise ValueError(err or "Invalid style guidance")
    old_value = await conn.fetchval(
        "SELECT coach_nate_style_guidance FROM intake_form WHERE user_id = $1",
        username,
    )
    await conn.execute(
        """
        UPDATE intake_form
        SET coach_nate_style_guidance = $2,
            updated_at = NOW()
        WHERE user_id = $1
        """,
        username,
        guidance.strip(),
    )
    await _audit_write(
        conn,
        username=username,
        question_id="coach_nate_style_guidance",
        old_value=old_value,
        new_value=guidance.strip(),
        actor="coach",
        actor_id=coach_username,
        method="coach_entry",
    )
    return dict(await conn.fetchrow("SELECT * FROM intake_form WHERE user_id = $1", username))


async def get_intake_summary(conn, username: str) -> Dict[str, Any]:
    row = await conn.fetchrow("SELECT * FROM intake_form WHERE user_id = $1", username)
    if not row:
        return {
            "section_1_completion_pct": 0,
            "section_1_status": "not_started",
            "section_2_status": "not_started",
            "has_any_answers": False,
        }
    data = dict(row)
    return {
        "section_1_completion_pct": _section_completion_percent(data, SECTION1_FIELDS),
        "section_1_status": data.get("section_1_status") or "not_started",
        "section_2_status": data.get("section_2_status") or "not_started",
        "has_any_answers": any(not _is_blank(data.get(field)) for field in ALL_QUESTION_FIELDS),
    }


async def get_section1_for_nate(conn, username: str) -> str:
    row = await conn.fetchrow(
        """
        SELECT user_id, coach_nate_style_guidance, {}
        FROM intake_form
        WHERE user_id = $1
        """.format(", ".join(SECTION1_FIELDS)),
        username,
    )
    if not row:
        return ""
    data = dict(row)
    lines: List[str] = []
    for field in SECTION1_FIELDS:
        value = data.get(field)
        if _is_blank(value):
            continue
        lines.append(f"- {QUESTION_LABELS.get(field, field)}: {str(value).strip()}")

    style = (data.get("coach_nate_style_guidance") or "").strip()
    if style:
        lines.append(f"- Coach rapport guidance: {style}")

    if not lines:
        return ""
    return "CLIENT INTAKE (SECTION 1)\n" + "\n".join(lines)


async def credit_walkthrough_question(
    conn,
    *,
    username: str,
    question_id: str,
) -> Dict[str, Any]:
    if question_id not in SECTION1_FIELDS:
        return {"credited": False, "amount": 0, "reason": "not_section_1"}

    row = await conn.fetchrow(
        "SELECT tokens_credited FROM intake_form WHERE user_id = $1",
        username,
    )
    token_map = dict((row["tokens_credited"] or {}) if row else {})
    if token_map.get(question_id) is True:
        return {"credited": False, "amount": 0, "reason": "already_credited"}

    bal_row = await conn.fetchrow(
        """
        SELECT username, COALESCE(token_balance, 0) AS token_balance
        FROM users
        WHERE LOWER(username) = LOWER($1)
        LIMIT 1
        """,
        username,
    )
    if not bal_row:
        return {"credited": False, "amount": 0, "reason": "user_not_found"}

    clean_username = bal_row["username"]
    before = int(bal_row["token_balance"] or 0)
    after = before + _WALKTHROUGH_REWARD

    batch_id = f"intake_{question_id}_{clean_username}".replace("-", "_")
    existing = await conn.fetchval(
        "SELECT 1 FROM token_transactions WHERE source = 'intake_walkthrough' AND reason = $1 LIMIT 1",
        batch_id,
    )
    if existing:
        return {"credited": False, "amount": 0, "reason": "duplicate_transaction"}

    await conn.execute(
        """
        UPDATE users
        SET token_balance = $2,
            profile_data = jsonb_set(
                COALESCE(profile_data, '{}'::jsonb),
                '{token_balance}',
                to_jsonb($2::int)
            )
        WHERE LOWER(username) = LOWER($1)
        """,
        clean_username,
        after,
    )
    await conn.execute(
        """
        INSERT INTO token_transactions (
            username, action, amount, balance_before, balance_after,
            source, reason, initiated_by, target_scope
        ) VALUES ($1, 'reward', $2, $3, $4, 'intake_walkthrough', $5, 'system', 'individual')
        """,
        clean_username,
        _WALKTHROUGH_REWARD,
        before,
        after,
        batch_id,
    )
    await conn.execute(
        """
        UPDATE intake_form
        SET tokens_credited = jsonb_set(
                COALESCE(tokens_credited, '{}'::jsonb),
                ARRAY[$2],
                'true'::jsonb,
                true
            ),
            updated_at = NOW()
        WHERE user_id = $1
        """,
        username,
        question_id,
    )
    logger.info("[INTAKE_TOKEN] uid=%s question=%s credited=%s", username, question_id, _WALKTHROUGH_REWARD)
    return {"credited": True, "amount": _WALKTHROUGH_REWARD}


async def is_client_assigned_to_coach(conn, *, client_username: str, coach: Dict[str, Any]) -> bool:
    if (coach.get("role") or "").upper() == "ADMIN":
        return True
    coach_hw = (coach.get("hardware_id") or coach.get("user_id") or "").strip()
    coach_username = (coach.get("username") or "").strip()
    if not coach_username:
        coach_username = await _resolve_username(conn, coach) or ""
    row = await conn.fetchrow(
        """
        SELECT profile_data
        FROM users
        WHERE LOWER(username) = LOWER($1)
          AND role = 'CLIENT'
          AND deleted_at IS NULL
        LIMIT 1
        """,
        client_username,
    )
    if not row:
        return False
    profile_data = _coerce_profile_data(row["profile_data"])
    assigned_ids = {
        str(profile_data.get("assigned_coach_id") or "").strip(),
        str(profile_data.get("coach_id") or "").strip(),
    }
    assigned_names = {
        str(profile_data.get("assigned_coach") or "").strip(),
        str(profile_data.get("coach_username") or "").strip(),
    }
    return (coach_hw and coach_hw in assigned_ids) or (coach_username and coach_username in assigned_names)


async def mark_section2_complete(
    conn,
    *,
    username: str,
    completed_by: str,
) -> Dict[str, Any]:
    await conn.execute(
        """
        UPDATE intake_form
        SET section_2_status = 'complete',
            section_2_completed_at = NOW(),
            section_2_completed_by = $2,
            updated_at = NOW()
        WHERE user_id = $1
        """,
        username,
        completed_by,
    )
    return dict(await conn.fetchrow("SELECT * FROM intake_form WHERE user_id = $1", username))


async def get_reminder_status(conn, username: str) -> Dict[str, Any]:
    last_sent = await conn.fetchval(
        "SELECT MAX(sent_at) FROM intake_reminders WHERE user_id = $1",
        username,
    )
    now = datetime.now(timezone.utc)
    available_at = None
    if last_sent:
        available_at = last_sent + timedelta(days=7)
    can_send = (not available_at) or (available_at <= now)
    days_until = 0 if can_send else max(1, int((available_at - now).total_seconds() // 86400))
    return {
        "last_sent_at": last_sent.isoformat() if last_sent else None,
        "available_at": available_at.isoformat() if available_at else None,
        "can_send_now": can_send,
        "days_until_available": days_until,
    }


async def send_intake_reminder(
    conn,
    *,
    username: str,
    coach_username: str,
    sections: List[str],
    methods: List[str],
    personal_note: str,
    override_rate_limit: bool,
    override_reason: Optional[str],
    notification_system,
) -> Dict[str, Any]:
    status = await get_reminder_status(conn, username)
    if not status["can_send_now"] and not override_rate_limit:
        raise PermissionError("Reminder rate-limited")
    if override_rate_limit and (_is_blank(override_reason) or len((override_reason or "").strip()) < 10):
        raise ValueError("override_reason must be at least 10 characters when overriding rate limit")

    user_row = await conn.fetchrow(
        """
        SELECT username, hardware_id, profile_data
        FROM users
        WHERE LOWER(username) = LOWER($1) AND role = 'CLIENT' AND deleted_at IS NULL
        LIMIT 1
        """,
        username,
    )
    if not user_row:
        raise ValueError("Client not found")

    profile_data = _coerce_profile_data(user_row["profile_data"])
    hardware_id = (user_row["hardware_id"] or "").strip()
    note = (personal_note or "").strip()
    reminder_payload = {
        "sections": sections,
        "methods": methods,
        "personal_note": note,
        "override_reason": (override_reason or "").strip() if override_rate_limit else None,
    }
    await conn.execute(
        """
        INSERT INTO intake_reminders (
            user_id, coach_username, sections, methods, personal_note,
            override_rate_limit, override_reason
        ) VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6, $7)
        """,
        username,
        coach_username,
        json.dumps(sections),
        json.dumps(methods),
        note,
        override_rate_limit,
        (override_reason or "").strip() if override_rate_limit else None,
    )
    await _audit_write(
        conn,
        username=username,
        question_id="reminder",
        old_value=None,
        new_value=reminder_payload,
        actor="coach",
        actor_id=coach_username,
        method="coach_reminder_override" if override_rate_limit else "coach_reminder",
        override_reason=(override_reason or "").strip() if override_rate_limit else None,
    )

    # notification_system.py only
    if notification_system and hardware_id:
        title = "Clinical intake reminder"
        msg = "Your coach asked you to complete your clinical intake form in Settings."
        if note:
            msg = f"{msg}\n\nCoach note: {note}"
        send_email = "email" in methods and bool(profile_data.get("email"))
        await notification_system.send(
            recipient_id=hardware_id,
            notification_type="intake_reminder",
            title=title,
            message=msg,
            priority="NORMAL",
            data={"route": "settings_intake", "sections": sections},
            send_email=send_email,
            email_address=profile_data.get("email"),
        )
        if "sms" in methods and profile_data.get("phone"):
            try:
                await notification_system.send_sms(
                    to_phone=profile_data.get("phone"),
                    body="Little Nate: Your coach sent a reminder to complete your intake form in Settings.",
                )
            except Exception as sms_err:
                logger.warning("Intake reminder SMS failed for %s: %s", username, sms_err)

    return await get_reminder_status(conn, username)
