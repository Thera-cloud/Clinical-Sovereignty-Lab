"""Charge-commit publish: PG paid is not done until calendar + Zoom exist.

JSON upsert mutates one session plus overlapping ghosts; id-set must match. Google Calendar
create is best-effort when OAuth is connected. Zoom is verified via GET.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.services.session_occupancy import as_utc, ranges_overlap

logger = logging.getLogger("nate.session_schedule_publish")

JSON_CANDIDATES = (
    Path(os.getenv("SESSIONS_JSON_PATH", "")),
    Path("/app/bridge_data/sessions.json"),
    Path("/app/data/sessions.json"),
    Path("/opt/clinical-sovereignty-lab/data/bridge/sessions.json"),
    Path("/opt/clinical-sovereignty-lab/data/backend/sessions.json"),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _session_id(row: Dict[str, Any]) -> str:
    return str(row.get("session_id") or row.get("id") or "").strip()


def _item_sid(item: Dict[str, Any]) -> str:
    return str(item.get("session_id") or item.get("id") or "").strip()


def _mark_json_cancelled(item: Dict[str, Any]) -> Dict[str, Any]:
    item["status"] = "cancelled"
    item["zoom_link"] = ""
    item["zoom_host_url"] = ""
    item["zoom_meeting_id"] = ""
    return item


def _json_times_overlap(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    a0 = as_utc(a.get("scheduled_start") or a.get("scheduled_at"))
    b0 = as_utc(b.get("scheduled_start") or b.get("scheduled_at"))
    if not a0 or not b0:
        return False
    a1 = as_utc(a.get("scheduled_end")) or (a0 + timedelta(minutes=50))
    b1 = as_utc(b.get("scheduled_end")) or (b0 + timedelta(minutes=50))
    return ranges_overlap(a0, a1, b0, b1)


def json_payload_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    sd = row.get("session_data") or {}
    if isinstance(sd, str):
        try:
            sd = json.loads(sd)
        except Exception:
            sd = {}
    if not isinstance(sd, dict):
        sd = {}
    start = _iso(row.get("scheduled_start") or row.get("scheduled_at"))
    end = _iso(row.get("scheduled_end"))
    return {
        "session_id": _session_id(row),
        "id": _session_id(row),
        "coach_id": row.get("coach_id") or "",
        "client_id": row.get("client_id") or "",
        "client_name": row.get("client_name") or "",
        "family_id": row.get("family_id") or "",
        "status": row.get("status") or "scheduled",
        "payment_status": row.get("payment_status") or "",
        "collect_later": bool(sd.get("collect_later") or row.get("collect_later")),
        "scheduled_start": start,
        "scheduled_end": end,
        "session_type": row.get("session_type") or "COACH",
        "zoom_link": row.get("zoom_link") or "",
        "zoom_host_url": row.get("zoom_host_url") or "",
        "zoom_meeting_id": row.get("zoom_meeting_id") or "",
        "google_event_id": row.get("google_event_id") or "",
        "price_cents": row.get("price_cents") or 0,
        "stripe_payment_intent_id": row.get("stripe_payment_intent_id") or "",
        "notes": row.get("notes") or "",
        "booked_by": row.get("booked_by") or sd.get("booked_by") or "",
        "schedule_published_at": sd.get("schedule_published_at") or _now_iso(),
    }


def _json_paths() -> List[Path]:
    seen = set()
    out: List[Path] = []
    for p in JSON_CANDIDATES:
        if not p or str(p) in ("", ".", "/"):
            continue
        try:
            key = str(p.resolve()) if p.exists() else str(p)
        except Exception:
            key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def upsert_sessions_json_row(
    payload: Dict[str, Any],
    *,
    cancel_ids: Optional[List[str]] = None,
    paths: Optional[List[Path]] = None,
) -> Dict[str, Any]:
    sid = _session_id(payload)
    cancel = {str(x) for x in (cancel_ids or []) if x}
    written: List[str] = []
    errors: List[str] = []
    coach = str(payload.get("coach_id") or "")
    blocking = {"scheduled", "active", "pending_approval"}
    for path in (paths if paths is not None else _json_paths()):
        if not path.exists():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, list):
                errors.append(f"{path}: not a list")
                continue
            old_ids = {_item_sid(x) for x in data if isinstance(x, dict) and _item_sid(x)}
            found = False
            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    continue
                iid = _item_sid(item)
                same_coach = coach and str(item.get("coach_id") or "") == coach
                live = str(item.get("status") or "").lower() in blocking
                if iid and iid != sid and (
                    iid in cancel
                    or (same_coach and live and _json_times_overlap(item, payload))
                ):
                    data[i] = _mark_json_cancelled(item)
                    continue
                if iid == sid:
                    merged = dict(item)
                    merged.update(payload)
                    data[i] = merged
                    found = True
            if sid and not found:
                data.append(payload)
            new_ids = {_item_sid(x) for x in data if isinstance(x, dict) and _item_sid(x)}
            expected = set(old_ids)
            if sid:
                expected.add(sid)
            if new_ids != expected:
                errors.append(f"{path}: id-set changed {sorted(old_ids ^ new_ids)[:8]}")
                logger.error(
                    "session_schedule_publish: refusing JSON rewrite %s (other sessions changed)",
                    path,
                )
                continue
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            check = json.loads(tmp.read_text(encoding="utf-8"))
            if not isinstance(check, list) or len(check) != len(data):
                tmp.unlink(missing_ok=True)
                errors.append(f"{path}: tmp validate failed")
                continue
            bak = path.with_suffix(path.suffix + ".bak")
            try:
                bak.write_text(raw, encoding="utf-8")
            except Exception:
                pass
            tmp.replace(path)
            written.append(str(path))
        except Exception as e:
            errors.append(f"{path}: {e}")
            logger.warning("session_schedule_publish: JSON upsert failed %s: %s", path, e)
    return {"written": written, "errors": errors}


async def verify_zoom_join(row: Dict[str, Any]) -> Tuple[bool, str]:
    mid = str(row.get("zoom_meeting_id") or "").strip()
    link = str(row.get("zoom_link") or "").strip()
    if not mid and "/j/" in link:
        try:
            mid = link.split("/j/", 1)[1].split("?", 1)[0].strip()
        except Exception:
            mid = ""
    if not mid:
        return False, "no_zoom_id"
    try:
        from app.services.zoom_client import ZoomClient
        client = ZoomClient.from_env()
        meeting = await client.get_meeting(meeting_id=mid)
        if meeting:
            join = meeting.get("join_url") or link
            return True, str(join or mid)
        return False, "zoom_get_empty"
    except Exception as e:
        logger.warning("session_schedule_publish: zoom GET failed: %s", e)
        return False, str(e)[:120]


async def ensure_google_event(row: Dict[str, Any], db_pool) -> str:
    existing = str(row.get("google_event_id") or "").strip()
    if existing:
        return existing
    if not db_pool:
        return ""
    try:
        from app.services.google_calendar_session_sync import sync_session_for_participants
        await sync_session_for_participants(db_pool, row, action="create")
        sid = _session_id(row)
        async with db_pool.acquire() as conn:
            eid = await conn.fetchval(
                "SELECT google_event_id FROM coaching_sessions WHERE session_id = $1",
                sid,
            )
        return str(eid or "")
    except Exception as e:
        logger.warning("session_schedule_publish: gcal create failed: %s", e)
        return ""


async def stamp_publish_state(
    db_pool,
    session_id: str,
    *,
    google_event_id: str = "",
    zoom_ok: bool = False,
    json_ok: bool = False,
    pending_reason: str = "",
) -> None:
    if not db_pool or not session_id:
        return
    pending = not (zoom_ok and json_ok)
    patch = {
        "schedule_published_at": _now_iso(),
        "schedule_publish_pending": pending,
        "schedule_publish_pending_reason": pending_reason if pending else "",
    }
    try:
        async with db_pool.acquire() as conn:
            if google_event_id:
                await conn.execute(
                    """
                    UPDATE coaching_sessions
                       SET google_event_id = COALESCE(NULLIF(google_event_id, ''), $2),
                           session_data = COALESCE(session_data, '{}'::jsonb) || $3::jsonb,
                           updated_at = NOW()
                     WHERE session_id = $1
                    """,
                    session_id, google_event_id, json.dumps(patch),
                )
            else:
                await conn.execute(
                    """
                    UPDATE coaching_sessions
                       SET session_data = COALESCE(session_data, '{}'::jsonb) || $2::jsonb,
                           updated_at = NOW()
                     WHERE session_id = $1
                    """,
                    session_id, json.dumps(patch),
                )
    except Exception as e:
        logger.warning("session_schedule_publish: stamp failed %s: %s", session_id, e)


async def _send_notices(row: Dict[str, Any], reason: str) -> None:
    try:
        from app.services.notifications_service import EmailService, outbound_email_blocked
        if outbound_email_blocked():
            logger.info("session_schedule_publish: notice skipped (test/ci) sid=%s", _session_id(row))
            return
        sid = _session_id(row)
        when = _iso(row.get("scheduled_start") or row.get("scheduled_at"))
        zoom = row.get("zoom_link") or ""
        pay = row.get("payment_status") or ""
        html = (
            f"<p>Session {sid} published ({reason}).</p>"
            f"<p>When: {when}<br>Payment: {pay}<br>Zoom: {zoom}</p>"
            "<p>Operational schedule confirmation — not a new charge.</p>"
        )
        dest = os.getenv("SESSION_OPS_EMAIL", "support@sovereignsanctuary.net")
        await EmailService().send_email(
            dest,
            "session_ops_digest",
            {
                "issue_count": 1,
                "issue_count_plural": "",
                "digest_html": html,
            },
        )
    except Exception as e:
        logger.warning("session_schedule_publish: notice failed: %s", e)


def _when_for_email(session: Dict[str, Any], tz_key: str) -> str:
    from app.utils.timezone_resolver import format_session_start_for_profile
    scheduled = session.get("scheduled_at") or session.get("scheduled_start")
    if not scheduled:
        return "your upcoming session"
    profile = {"timezone": session.get(tz_key) or session.get("client_timezone")}
    text, tz_name = format_session_start_for_profile(scheduled, profile)
    return f"{text} ({tz_name})"


async def _send_client_coach_confirmation(db_pool, row: Dict[str, Any], app_state) -> None:
    """Same confirmation subjects/bodies as SessionPaymentAgent._send_confirmation."""
    notify = getattr(app_state, "notification_system", None) if app_state else None
    if not db_pool or not notify or not hasattr(notify, "_send_email"):
        return
    sid = _session_id(row)
    if not sid:
        return
    try:
        async with db_pool.acquire() as conn:
            rec = await conn.fetchrow(
                """SELECT cs.id,
                          u.profile_data->>'email' AS client_email,
                          u.profile_data->>'name' AS client_name,
                          u.profile_data->>'timezone' AS client_timezone,
                          cu.profile_data->>'email' AS coach_email,
                          cu.profile_data->>'name' AS coach_name,
                          cu.profile_data->>'timezone' AS coach_timezone
                     FROM coaching_sessions cs
                     LEFT JOIN users u
                       ON u.hardware_id = cs.client_id
                       OR u.id::text = cs.client_id
                     LEFT JOIN users cu
                       ON cu.hardware_id = cs.coach_id
                       OR cu.id::text = cs.coach_id
                    WHERE cs.session_id = $1""",
                sid,
            )
            if not rec or not rec["id"]:
                return
            already = await conn.fetchval(
                """SELECT 1 FROM session_notifications
                    WHERE session_id = $1 AND notification_type = 'confirmation'
                    LIMIT 1""",
                rec["id"],
            )
            if already:
                return
            payload = dict(row)
            payload["scheduled_at"] = row.get("scheduled_at") or row.get("scheduled_start")
            payload["client_timezone"] = rec["client_timezone"]
            payload["coach_timezone"] = rec["coach_timezone"]
            client_email = (rec["client_email"] or "").strip()
            coach_email = (rec["coach_email"] or "").strip()
            client_name = rec["client_name"] or row.get("client_name") or "Client"
            coach_name = rec["coach_name"] or "Coach"
            if client_email:
                from app.services.calendar_invite import html_cta_fragment, invite_from_session
                invite = invite_from_session(payload, coach_name=coach_name)
                await notify._send_email(
                    client_email,
                    "Session Confirmed — Payment Received",
                    f"""<p>Hello {client_name},</p>
<p>Your payment has been received. Your session on <strong>{_when_for_email(payload, 'client_timezone')}</strong> is confirmed.</p>
{html_cta_fragment(invite, include_join=True)}
<p>Thank you,<br>Sovereign Sanctuary</p>""",
                )
            if coach_email:
                await notify._send_email(
                    coach_email,
                    f"Session Payment Confirmed — {client_name}",
                    f"""<p>Hello {coach_name},</p>
<p>Payment received for your session with <strong>{client_name}</strong> on <strong>{_when_for_email(payload, 'coach_timezone')}</strong>.</p>
<p>Sovereign Sanctuary</p>""",
                )
            if client_email or coach_email:
                await conn.execute(
                    """INSERT INTO session_notifications
                           (session_id, notification_type, channel, recipient_id)
                       VALUES ($1, 'confirmation', 'email', $2)
                       ON CONFLICT DO NOTHING""",
                    rec["id"], row.get("client_id") or "",
                )
    except Exception as e:
        logger.warning("session_schedule_publish: client/coach confirm failed: %s", e)


async def publish_scheduled_session(
    db_pool,
    row: Dict[str, Any],
    *,
    reason: str = "publish",
    cancel_json_ids: Optional[List[str]] = None,
    app_state=None,
) -> Dict[str, Any]:
    sid = _session_id(row)
    payload = json_payload_from_row(row)
    json_result = upsert_sessions_json_row(payload, cancel_ids=cancel_json_ids)
    json_ok = bool(json_result.get("written"))
    gcal_id = await ensure_google_event(row, db_pool)
    if gcal_id:
        payload["google_event_id"] = gcal_id
        row["google_event_id"] = gcal_id
        upsert_sessions_json_row(payload, cancel_ids=cancel_json_ids)
    zoom_ok, zoom_detail = await verify_zoom_join(row)
    pending_reason = ""
    if not json_ok:
        pending_reason = "json_write"
    elif not zoom_ok:
        pending_reason = f"zoom:{zoom_detail}"
    await stamp_publish_state(
        db_pool, sid,
        google_event_id=gcal_id,
        zoom_ok=zoom_ok,
        json_ok=json_ok,
        pending_reason=pending_reason,
    )
    try:
        from app.services.session_slot_facts import record_session_slot_fact
        await record_session_slot_fact(
            db_pool, row,
            event="schedule_published",
            extra={"reason": reason, "zoom_ok": zoom_ok, "json_ok": json_ok, "gcal": bool(gcal_id)},
        )
    except Exception as e:
        logger.warning("session_schedule_publish: fact failed: %s", e)
    await _send_notices(row, reason)
    pay = str(row.get("payment_status") or "").lower()
    if json_ok and pay in ("paid", "waived", "zero"):
        await _send_client_coach_confirmation(db_pool, row, app_state)
    return {
        "session_id": sid,
        "json_ok": json_ok,
        "json_paths": json_result.get("written") or [],
        "google_event_id": gcal_id,
        "zoom_ok": zoom_ok,
        "zoom_detail": zoom_detail,
        "pending": bool(pending_reason),
        "pending_reason": pending_reason,
    }
