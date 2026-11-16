"""48-hour DOJO payment hold for coaches flagged at signup. Existing coaches are skipped."""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from app.services.coach_dojo_access import active_dojo_keys, patch_future_sessions

logger = logging.getLogger("nate.coach_payment_hold")


def hold_enabled() -> bool:
    return os.getenv("ENABLE_COACH_PAYMENT_HOLD", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def profile_dict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def eligible(profile: Any, username: str, role: str, subscription_status: str) -> bool:
    if not hold_enabled():
        return False
    if str(role or "").upper() != "COACH":
        return False
    if str(username or "").strip().lower() == "coachn":
        return False
    if str(subscription_status or "").upper() == "PENDING_VERIFICATION":
        return False
    return bool(profile_dict(profile).get("coach_payment_hold_eligible"))


def _parse_blocked(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [str(item) for item in raw if item]
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item]
    return []


async def _coachn(db) -> Optional[Dict[str, Any]]:
    return await db.fetchrow(
        """SELECT username, hardware_id,
                  COALESCE(NULLIF(email, ''), profile_data->>'email') AS email,
                  COALESCE(NULLIF(phone, ''), profile_data->>'phone') AS phone
             FROM users
            WHERE LOWER(username) = 'coachn' AND role = 'COACH'
            LIMIT 1"""
    )


async def open_hold_from_invoice(db, invoice: Dict[str, Any], user_id) -> None:
    """One hold per invoice. A retry of the same invoice does not move the clock."""
    if not hold_enabled() or db is None or not invoice:
        return
    from app.services.stripe_integration import _invoice_subscription_id

    subscription_id = _invoice_subscription_id(invoice)
    invoice_id = str(invoice.get("id") or "")
    if not subscription_id or not invoice_id:
        return
    row = await db.fetchrow(
        """SELECT username, role, hardware_id, subscription_status, profile_data,
                  COALESCE(NULLIF(email, ''), profile_data->>'email') AS email,
                  COALESCE(NULLIF(phone, ''), profile_data->>'phone') AS phone
             FROM users WHERE id = $1""",
        user_id,
    )
    if not row or not eligible(
        row["profile_data"], row["username"], row["role"], row["subscription_status"]
    ):
        return
    blocked = active_dojo_keys(profile_dict(row["profile_data"]))
    inserted = await db.fetchval(
        """INSERT INTO coach_payment_holds (
               invoice_id, coach_username, coach_hardware_id, stripe_subscription_id,
               deadline_at, blocked_dojos
           ) VALUES ($1, $2, $3, $4, NOW() + INTERVAL '48 hours', $5::jsonb)
           ON CONFLICT (invoice_id) DO NOTHING
           RETURNING invoice_id""",
        invoice_id,
        row["username"],
        row["hardware_id"],
        str(subscription_id),
        json.dumps(blocked),
    )
    if not inserted:
        return
    await _notify_opened(db, row, invoice_id)


async def mark_hold_paid(db, invoice_id: str) -> None:
    if not hold_enabled() or db is None or not invoice_id:
        return
    row = await db.fetchrow(
        """UPDATE coach_payment_holds
              SET status = 'paid',
                  session_sync = CASE WHEN transferred_at IS NULL THEN '' ELSE 'return' END
            WHERE invoice_id = $1 AND status IN ('open', 'expired')
            RETURNING coach_username, coach_hardware_id, transferred_at""",
        invoice_id,
    )
    if row and row["transferred_at"]:
        await _return_clients(db, row["coach_username"], row["coach_hardware_id"])


async def blocked_dojos_for(db, username: str) -> List[str]:
    if not hold_enabled() or db is None or not username:
        return []
    rows = await db.fetch(
        """SELECT blocked_dojos FROM coach_payment_holds
            WHERE LOWER(coach_username) = LOWER($1) AND status = 'open'""",
        username,
    )
    found: List[str] = []
    for row in rows:
        found.extend(_parse_blocked(row["blocked_dojos"]))
    return found


async def message_locked(db, profile: Any, message_type: str, sessions_file: str = "") -> bool:
    """True when a coach message must stop at the payment wall. Fail open."""
    try:
        if not hold_enabled() or db is None or not isinstance(profile, dict):
            return False
        if (profile.get("role") or "") != "COACH":
            return False
        if message_type in ("login_request", "logout", "ping", "pong"):
            return False
        return await coach_portal_locked(db, profile.get("username") or "", sessions_file)
    except Exception as exc:
        logger.warning("coach hold message check skipped: %s", exc)
        return False


async def fields_for_login(db, profile: Dict[str, Any], sessions_file: str = "") -> Dict[str, Any]:
    try:
        if not hold_enabled() or db is None or (profile.get("role") or "") != "COACH":
            return {}
        return await login_hold_fields(db, profile.get("username") or "", sessions_file)
    except Exception as exc:
        logger.warning("coach hold login view skipped: %s", exc)
        return {}


async def new_booking_paused(
    db, coach_id: str, sessions_file: str = "", client_name: str = "", when_text: str = "",
) -> bool:
    try:
        if not hold_enabled() or db is None or not coach_id:
            return False
        return await booking_blocked(db, coach_id, sessions_file, client_name, when_text)
    except Exception as exc:
        logger.warning("coach hold booking check skipped: %s", exc)
        return False


async def record_assistant_invite(db, master_id: str, assistant_id: str) -> str:
    """Keep a revoked pair revoked. Returns revoked or invited."""
    async with db.acquire() as conn:
        existing = await conn.fetchval(
            """SELECT status FROM coach_hierarchy
                WHERE master_coach_id = $1 AND assistant_id = $2""",
            master_id, assistant_id,
        )
        if existing == "revoked":
            return "revoked"
        await conn.execute(
            """INSERT INTO coach_hierarchy (master_coach_id, assistant_id, status)
               VALUES ($1, $2, 'pending_admin')
               ON CONFLICT (master_coach_id, assistant_id)
               DO UPDATE SET status = 'pending_admin', invited_at = NOW(), revoked_at = NULL""",
            master_id, assistant_id,
        )
    return "invited"


async def accept_pending_invite(db, master_id: str, assistant_id: str) -> bool:
    """Activate only a row that is already pending."""
    async with db.acquire() as conn:
        result = await conn.execute(
            """UPDATE coach_hierarchy SET status = 'active', accepted_at = NOW()
               WHERE master_coach_id = $1 AND assistant_id = $2 AND status = 'pending'""",
            master_id, assistant_id,
        )
    return str(result).rsplit(" ", 1)[-1] == "1"


async def coach_portal_locked(db, username: str, sessions_file: str = "") -> bool:
    if not hold_enabled() or db is None or not username:
        return False
    await _expire_due(db, username)
    await sync_hold_sessions(db, sessions_file)
    row = await db.fetchval(
        """SELECT 1 FROM coach_payment_holds
            WHERE LOWER(coach_username) = LOWER($1) AND status = 'expired'
            LIMIT 1""",
        username,
    )
    return bool(row)


async def login_hold_fields(db, username: str, sessions_file: str = "") -> Dict[str, Any]:
    if not hold_enabled() or db is None or not username:
        return {}
    await _expire_due(db, username)
    await sync_hold_sessions(db, sessions_file)
    locked = await db.fetchval(
        """SELECT 1 FROM coach_payment_holds
            WHERE LOWER(coach_username) = LOWER($1) AND status = 'expired' LIMIT 1""",
        username,
    )
    blocked = await blocked_dojos_for(db, username)
    if not locked and not blocked:
        return {}
    return {
        "coach_payment_required": bool(locked),
        "coach_hold_blocked_dojos": blocked,
    }


async def booking_blocked(
    db,
    coach_id: str,
    sessions_file: str = "",
    client_name: str = "",
    when_text: str = "",
) -> bool:
    """True when a new booking must not attach. Emails CoachN the request."""
    if not hold_enabled() or db is None or not coach_id:
        return False
    coach = await db.fetchrow(
        """SELECT username, hardware_id FROM users
            WHERE hardware_id = $1 OR username = $1
            LIMIT 1""",
        coach_id,
    )
    if not coach:
        return False
    await _expire_due(db, coach["username"])
    await sync_hold_sessions(db, sessions_file)
    row = await db.fetchrow(
        """SELECT status FROM coach_payment_holds
            WHERE LOWER(coach_username) = LOWER($1) AND status IN ('open', 'expired')
            ORDER BY failed_at DESC LIMIT 1""",
        coach["username"],
    )
    if not row:
        return False
    await _email_booking_request(db, client_name, when_text, coach["username"])
    return True


async def link_new_coach_to_coachn(db, assistant_hardware_id: str) -> None:
    """Active assistant link. Signup still succeeds when CoachN is missing."""
    if db is None or not assistant_hardware_id:
        return
    master = await _coachn(db)
    if not master or not master["hardware_id"]:
        logger.warning("CoachN link skipped: master row missing")
        return
    if master["hardware_id"] == assistant_hardware_id:
        return
    await db.execute(
        """INSERT INTO coach_hierarchy (master_coach_id, assistant_id, status, accepted_at)
           VALUES ($1, $2, 'active', NOW())
           ON CONFLICT (master_coach_id, assistant_id) DO NOTHING""",
        master["hardware_id"],
        assistant_hardware_id,
    )


async def _expire_due(db, username: str) -> None:
    rows = await db.fetch(
        """UPDATE coach_payment_holds
              SET status = 'expired', transferred_at = NOW(), session_sync = 'move'
            WHERE LOWER(coach_username) = LOWER($1)
              AND status = 'open'
              AND deadline_at <= NOW()
            RETURNING coach_username, coach_hardware_id""",
        username,
    )
    for row in rows:
        await _transfer_clients(db, row["coach_username"], row["coach_hardware_id"])


async def _transfer_clients(db, username: str, hardware_id: str) -> None:
    master = await _coachn(db)
    if not master:
        logger.warning("coach hold transfer skipped: CoachN missing")
        return
    old_ids = [item for item in (hardware_id, username) if item]
    await db.execute(
        """UPDATE users
              SET profile_data = jsonb_set(
                    jsonb_set(
                      jsonb_set(
                        jsonb_set(
                          COALESCE(profile_data, '{}'::jsonb),
                          '{coach_id}', to_jsonb($1::text)
                        ),
                        '{assigned_coach_id}', to_jsonb($1::text)
                      ),
                      '{assigned_coach}', to_jsonb($2::text)
                    ),
                    '{hold_original_coach}', to_jsonb($3::text)
                  ),
                  updated_at = NOW()
            WHERE role = 'CLIENT'
              AND (
                    profile_data->>'coach_id' = ANY($4::text[])
                 OR profile_data->>'assigned_coach_id' = ANY($4::text[])
                 OR profile_data->>'assigned_coach' = $3
              )""",
        master["hardware_id"],
        master["username"],
        username,
        old_ids,
    )
    await _move_pg_sessions(db, old_ids, master["hardware_id"], restore=False, tag=username)
    await _reload_user(username)
    await _reload_user(master["username"])
    await _email_clients_transferred(db, username)


async def _return_clients(db, username: str, hardware_id: str) -> None:
    master = await _coachn(db)
    if not master:
        return
    await db.execute(
        """UPDATE users
              SET profile_data = jsonb_set(
                    jsonb_set(
                      jsonb_set(
                        COALESCE(profile_data, '{}'::jsonb) - 'hold_original_coach',
                        '{coach_id}', to_jsonb($1::text)
                      ),
                      '{assigned_coach_id}', to_jsonb($1::text)
                    ),
                    '{assigned_coach}', to_jsonb($2::text)
                  ),
                  updated_at = NOW()
            WHERE role = 'CLIENT'
              AND profile_data->>'hold_original_coach' = $2
              AND profile_data->>'coach_id' = $3""",
        hardware_id,
        username,
        master["hardware_id"],
    )
    await _move_pg_sessions(
        db, [master["hardware_id"]], hardware_id, restore=True, tag=username,
    )
    await _reload_user(username)
    await _reload_user(master["username"])


async def _move_pg_sessions(db, old_ids: List[str], new_id: str, restore: bool, tag: str) -> None:
    if not new_id:
        return
    if restore:
        await db.execute(
            """UPDATE coaching_sessions
                  SET coach_id = $1,
                      session_data = COALESCE(session_data, '{}'::jsonb) - 'hold_from'
                WHERE coach_id = ANY($2::text[])
                  AND actual_start IS NULL
                  AND scheduled_start > NOW()
                  AND LOWER(COALESCE(status, '')) NOT IN
                      ('active', 'in_progress', 'completed', 'cancelled', 'canceled')
                  AND session_data->>'hold_from' = $3""",
            new_id,
            old_ids,
            tag,
        )
        return
    await db.execute(
        """UPDATE coaching_sessions
              SET coach_id = $1,
                  zoom_link = '',
                  zoom_meeting_id = '',
                  zoom_host_url = '',
                  session_data = jsonb_set(
                      COALESCE(session_data, '{}'::jsonb), '{hold_from}', to_jsonb($2::text)
                  )
            WHERE coach_id = ANY($3::text[])
              AND actual_start IS NULL
              AND scheduled_start > NOW()
              AND LOWER(COALESCE(status, '')) NOT IN
                  ('active', 'in_progress', 'completed', 'cancelled', 'canceled')""",
        new_id,
        tag,
        old_ids,
    )


async def sync_hold_sessions(db, sessions_file: str) -> None:
    if not sessions_file or db is None:
        return
    from pathlib import Path

    rows = await db.fetch(
        """SELECT id, session_sync, coach_username, coach_hardware_id
             FROM coach_payment_holds
            WHERE session_sync IN ('move', 'return')
            LIMIT 20"""
    )
    if not rows:
        return
    path = Path(sessions_file)
    if not path.exists():
        return
    try:
        sessions = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        logger.warning("coach hold session file unreadable")
        return
    if not isinstance(sessions, list):
        return
    master = await _coachn(db)
    if not master:
        return
    changed = False
    touched = []
    for row in rows:
        old_ids = [item for item in (row["coach_hardware_id"], row["coach_username"]) if item]
        if row["session_sync"] == "move":
            changed = patch_future_sessions(
                sessions, old_ids, master["hardware_id"], hold_tag=row["coach_username"],
            ) or changed
        else:
            changed = patch_future_sessions(
                sessions,
                [master["hardware_id"]],
                row["coach_hardware_id"] or "",
                restore_from=row["coach_username"],
            ) or changed
        touched.append(row["id"])
    if changed:
        path.write_text(json.dumps(sessions))
    if touched:
        await db.execute(
            "UPDATE coach_payment_holds SET session_sync = '' WHERE id = ANY($1::int[])",
            touched,
        )


async def _notify_opened(db, coach_row, invoice_id: str) -> None:
    master = await _coachn(db)
    schedule = await _docket_lines(db, coach_row["username"], coach_row["hardware_id"])
    body_coach = (
        "Your DOJO subscription payment was not captured. "
        "You have 48 hours to update payment. Booked sessions stay with you. "
        "New bookings are paused until the invoice is paid."
    )
    await _send_email(coach_row["email"], "Coach payment was not captured", body_coach)
    _sms(
        coach_row["phone"],
        "Your coach subscription payment was not captured. You have 48 hours to update it. Check your email.",
    )
    if master:
        await _send_email(master["email"], "Assistant coach payment was not captured", body_coach)
        _sms(master["phone"], "An assistant coach payment was not captured. Check email for the schedule.")
        docket = "Scheduled sessions:\n" + ("\n".join(schedule) if schedule else "None.")
        await _send_email(master["email"], "Assistant coach schedule", docket)
    await db.execute(
        """UPDATE coach_payment_holds
              SET docket_sent_at = NOW()
            WHERE invoice_id = $1 AND docket_sent_at IS NULL""",
        invoice_id,
    )


async def _docket_lines(db, username: str, hardware_id: str) -> List[str]:
    ids = [item for item in (hardware_id, username) if item]
    try:
        rows = await db.fetch(
            """SELECT client_name, scheduled_start
                 FROM coaching_sessions
                WHERE coach_id = ANY($1::text[])
                  AND actual_start IS NULL
                  AND scheduled_start > NOW()
                  AND LOWER(COALESCE(status, '')) IN ('scheduled', 'pending_approval', 'pending')
                ORDER BY scheduled_start
                LIMIT 40""",
            ids,
        )
    except Exception as exc:
        logger.warning("coach hold docket query skipped: %s", exc)
        return []
    lines = []
    for row in rows:
        who = row["client_name"] or "Client"
        lines.append(f"{who} — {row['scheduled_start']}")
    return lines


async def _email_booking_request(db, client_name: str, when_text: str, coach_username: str) -> None:
    master = await _coachn(db)
    if not master or not master["email"]:
        return
    who = client_name or "A client"
    text = (
        f"{who} asked to book {when_text or 'a session'} with {coach_username}. "
        "New bookings are paused until that coach's invoice is paid."
    )
    await _send_email(master["email"], "Booking request while a coach payment is open", text)


async def _email_clients_transferred(db, old_username: str) -> None:
    rows = await db.fetch(
        """SELECT COALESCE(NULLIF(email, ''), profile_data->>'email') AS email
             FROM users
            WHERE role = 'CLIENT' AND profile_data->>'hold_original_coach' = $1""",
        old_username,
    )
    text = (
        "Your coaching support may shift for a short time while your prior coach "
        "handles matters of their own. Your client portal is unchanged."
    )
    for row in rows:
        await _send_email(row["email"], "A note about your coach", text)


async def _send_email(to_email: str, subject: str, text: str) -> None:
    if not to_email:
        return
    try:
        from app.services.notifications_service import EmailService

        service = EmailService()
        await service.send_email(to_email, "coach_hold_notice", {
            "subject_line": subject,
            "body_text": text,
        })
    except Exception as exc:
        logger.warning("coach hold email skipped: %s", exc)


def _sms(phone: str, body: str) -> None:
    if not phone:
        return
    try:
        from app.services.voice_notifications import _send_sms
        _send_sms(phone, body)
    except Exception as exc:
        logger.warning("coach hold sms skipped: %s", exc)


async def _reload_user(username: str) -> None:
    if not username:
        return
    url = os.getenv("REDIS_URL")
    if not url:
        return
    try:
        import redis.asyncio as redis

        client = redis.from_url(url)
        await client.publish("nate:user_reload", json.dumps({"username": username}))
        await client.aclose()
    except Exception as exc:
        logger.warning("coach hold reload skipped: %s", exc)
