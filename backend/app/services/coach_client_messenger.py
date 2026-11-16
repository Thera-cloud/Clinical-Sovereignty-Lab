"""Direct coach-to-client messaging (Coach Command VIEW BRIEF "Message Client").

A coach sends a free-text message to one of their assigned clients via email
and/or SMS. Assignment is verified against the same profile fields used by
coach_get_clients. Every send is audited in sensitive_bridge_log.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_MESSAGE_CHARS = 2000


async def _fetch_client_row(db_pool, client_username: str) -> Optional[Dict[str, Any]]:
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT username, role, profile_data
                  FROM users
                 WHERE username = $1 AND role = 'CLIENT'
                 LIMIT 1
                """,
                client_username,
            )
        if not row:
            return None
        pd = row["profile_data"] or {}
        if isinstance(pd, str):
            try:
                pd = json.loads(pd)
            except Exception:
                pd = {}
        return {"username": row["username"], "profile_data": pd}
    except Exception as e:
        logger.warning("coach_client_messenger: client lookup failed: %s", e)
        return None


def _client_assigned_to_coach(
    client_pd: Dict[str, Any], coach_profile: Dict[str, Any]
) -> bool:
    """Mirror coach_get_clients assignment fields: coach_id / assigned_coach_id / assigned_coach."""
    coach_role = (coach_profile.get("role") or "").upper()
    if coach_role == "ADMIN":
        return True
    coach_hw = (coach_profile.get("hardware_id") or "").strip()
    coach_un = (coach_profile.get("username") or "").strip().lower()
    for key in ("coach_id", "assigned_coach_id"):
        v = str(client_pd.get(key) or "").strip()
        if v and coach_hw and v == coach_hw:
            return True
    v = str(client_pd.get("assigned_coach") or "").strip().lower()
    if v and coach_un and v == coach_un:
        return True
    return False


def coach_can_see_client(coach_profile, client_profile, supervised_ids=None) -> bool:
    """Assigned coach, or a master viewing an assistant's assigned client.

    An assistant does not inherit the master's other clients.
    """
    role = (coach_profile.get("role") or "").upper()
    if role == "ADMIN":
        return True
    if role != "COACH":
        return False
    if _client_assigned_to_coach(client_profile, coach_profile):
        return True
    supervised = set()
    for raw in supervised_ids or ():
        text = str(raw or "").strip()
        if text:
            supervised.add(text)
            supervised.add(text.lower())
    if not supervised:
        return False
    for key in ("coach_id", "assigned_coach_id", "assigned_coach"):
        value = str((client_profile or {}).get(key) or "").strip()
        if value and (value in supervised or value.lower() in supervised):
            return True
    return False


async def load_supervised_assistant_ids(conn, coach_profile) -> set:
    """Hardware ids and usernames of this coach's active assistants."""
    ids = [
        x for x in (
            str(coach_profile.get("hardware_id") or "").strip(),
            str(coach_profile.get("username") or "").strip(),
        ) if x
    ]
    if not ids:
        return set()
    rows = await conn.fetch(
        """
        SELECT ch.assistant_id, u.username, u.hardware_id
        FROM coach_hierarchy ch
        LEFT JOIN users u
          ON u.hardware_id = ch.assistant_id OR u.username = ch.assistant_id
        WHERE ch.master_coach_id = ANY($1::text[])
          AND ch.status = 'active'
        """,
        ids,
    )
    out = set()
    for row in rows:
        for key in ("assistant_id", "username", "hardware_id"):
            value = row[key]
            if value:
                out.add(str(value).strip())
    return out


def _coach_with_username(coach_profile, coach_username: str = ""):
    if coach_username and not (coach_profile or {}).get("username"):
        merged = dict(coach_profile or {})
        merged["username"] = coach_username
        return merged
    return coach_profile or {}


async def coach_may_view_client_conn(conn, coach_profile, client_profile, coach_username: str = "") -> bool:
    coach = _coach_with_username(coach_profile, coach_username)
    if coach_can_see_client(coach, client_profile):
        return True
    if (coach.get("role") or "").upper() != "COACH":
        return False
    supervised = await load_supervised_assistant_ids(conn, coach)
    return coach_can_see_client(coach, client_profile, supervised)


async def coach_may_view_client(db_pool, coach_profile, client_profile, coach_username: str = "") -> bool:
    coach = _coach_with_username(coach_profile, coach_username)
    if coach_can_see_client(coach, client_profile):
        return True
    if not db_pool or (coach.get("role") or "").upper() != "COACH":
        return False
    async with db_pool.acquire() as conn:
        return await coach_may_view_client_conn(conn, coach, client_profile)


def _registry_client(registry, client_id: str):
    wanted = (client_id or "").strip()
    if not wanted or not registry:
        return None
    for entry in registry.values():
        profile = (entry or {}).get("profile") or {}
        if wanted in (
            profile.get("hardware_id"),
            profile.get("username"),
            (entry or {}).get("username"),
        ):
            return profile
    return None


async def coach_may_view_family(db_pool, coach_profile, family_id: str, registry, coach_username: str = "") -> bool:
    """A family folder is visible only when every member is assigned to this coach
    or to one of this coach's assistants."""
    family_id = (family_id or "").strip()
    if not family_id:
        return False
    members = []
    for entry in (registry or {}).values():
        profile = (entry or {}).get("profile") or {}
        if profile.get("role") != "CLIENT":
            continue
        if profile.get("account_status") == "DELETED":
            continue
        if str(profile.get("family_id") or "") == family_id:
            members.append(profile)
    if not members:
        return False
    for profile in members:
        if not await coach_may_view_client(db_pool, coach_profile, profile, coach_username):
            return False
    return True


async def coach_may_view_note_request(db_pool, coach_profile, data, registry, coach_username: str = "") -> bool:
    role = (coach_profile.get("role") or "").upper()
    if role == "ADMIN":
        return True
    if role != "COACH":
        return False
    data = data or {}
    folder = str(data.get("folder_id") or "").strip()
    client_id = str(data.get("client_id") or "").strip()
    family_id = str(data.get("family_id") or "").strip()
    if folder.startswith("client:"):
        client_id = client_id or folder.split(":", 1)[1].strip()
    elif folder.startswith("family:"):
        family_id = family_id or folder.split(":", 1)[1].strip()
    if family_id:
        return await coach_may_view_family(db_pool, coach_profile, family_id, registry, coach_username)
    if not client_id:
        return False
    profile = _registry_client(registry, client_id)
    if profile is None and db_pool:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT profile_data FROM users
                WHERE (hardware_id = $1 OR username = $1)
                  AND role = 'CLIENT' AND deleted_at IS NULL
                """,
                client_id,
            )
        if row:
            profile = row["profile_data"]
            if isinstance(profile, str):
                import json
                profile = json.loads(profile)
    return bool(profile) and await coach_may_view_client(
        db_pool, coach_profile, profile, coach_username
    )


async def _emit_message_audit(
    db_pool,
    *,
    client_username: str,
    coach_username: str,
    channels: List[str],
    results: Dict[str, bool],
    message_len: int,
) -> None:
    payload = {
        "coach_username": coach_username,
        "channels_requested": channels,
        "email_sent": bool(results.get("email_sent")),
        "sms_sent": bool(results.get("sms_sent")),
        "message_length": message_len,
    }
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sensitive_bridge_log
                    (user_id, session_id, event_type, event_severity,
                     payload_json, decision_summary, recorded_by,
                     access_classification, pii_screened_at)
                VALUES ($1, NULL, 'coach_direct_message_sent', 'low',
                        $2::jsonb, NULL, 'coach_client_messenger',
                        'clinician_and_admin', NOW())
                """,
                client_username,
                json.dumps(payload),
            )
    except Exception as e:
        logger.warning("coach_client_messenger: audit insert failed: %s", e)


async def send_direct_client_message(
    db_pool,
    coach_profile: Dict[str, Any],
    client_username: str,
    message: str,
    channels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Send a direct message from a coach to an assigned client.

    channels: subset of ["email", "sms"] (default both).
    Returns per-channel results so the UI can report honestly
    (SMS may fail while A2P is carrier-blocked).
    """
    client_username = (client_username or "").strip()
    message = (message or "").strip()[:_MAX_MESSAGE_CHARS]
    channels = [c for c in (channels or ["email", "sms"]) if c in ("email", "sms")]

    if not db_pool:
        return {"status": "error", "reason": "no_db_pool"}
    if not client_username or not message:
        return {"status": "error", "reason": "missing_client_or_message"}
    if not channels:
        return {"status": "error", "reason": "no_valid_channels"}

    coach_role = (coach_profile.get("role") or "").upper()
    if coach_role not in ("COACH", "ADMIN"):
        return {"status": "error", "reason": "not_authorized"}

    client = await _fetch_client_row(db_pool, client_username)
    if not client:
        return {"status": "error", "reason": "client_not_found"}
    client_pd = client["profile_data"]
    if not await coach_may_view_client(db_pool, coach_profile, client_pd):
        return {"status": "error", "reason": "client_not_assigned"}

    coach_name = (
        (coach_profile.get("name") or "").strip()
        or (coach_profile.get("username") or "").strip()
        or "Your coach"
    )
    client_email = (client_pd.get("email") or "").strip()
    client_phone = (client_pd.get("phone") or "").strip()

    results: Dict[str, Any] = {
        "status": "sent",
        "client_username": client_username,
        "email_sent": False,
        "sms_sent": False,
        "email_on_file": bool(client_email),
        "phone_on_file": bool(client_phone),
    }

    if "email" in channels and client_email:
        try:
            from app.services.notifications_service import EmailService

            ok = await EmailService().send_coach_direct_message(
                client_email, coach_name, message
            )
            results["email_sent"] = bool(ok)
        except Exception as e:
            logger.warning(
                "coach_client_messenger: email failed for %s: %s", client_username, e
            )

    if "sms" in channels and client_phone:
        try:
            from app.services.coach_notifications import _send_coach_sms

            body = f"Message from your coach {coach_name}: {message}"
            results["sms_sent"] = bool(_send_coach_sms(client_phone, body))
        except Exception as e:
            logger.warning(
                "coach_client_messenger: SMS failed for %s: %s", client_username, e
            )

    if not results["email_sent"] and not results["sms_sent"]:
        results["status"] = "no_channel_delivered"

    await _emit_message_audit(
        db_pool,
        client_username=client_username,
        coach_username=(coach_profile.get("username") or "").strip(),
        channels=channels,
        results=results,
        message_len=len(message),
    )
    return results
