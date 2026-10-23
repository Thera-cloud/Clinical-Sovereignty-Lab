"""Stop Stripe charges on cancel/delete; notify client + coach; 30-day hold history."""

from __future__ import annotations

import html
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("account_lifecycle")

_LIVE_STRIPE_STATUSES = frozenset(
    {"active", "past_due", "unpaid", "trialing", "incomplete", "paused"}
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def should_cancel_stripe_status(status: str) -> bool:
    return _as_text(status).lower() in _LIVE_STRIPE_STATUSES


def _stripe_cancel_now(stripe_mod: Any, sub_id: str) -> None:
    cancel = getattr(stripe_mod.Subscription, "cancel", None)
    if callable(cancel):
        cancel(sub_id)
        return
    stripe_mod.Subscription.delete(sub_id)


def _init_stripe(stripe_mod: Any = None) -> Optional[Any]:
    if stripe_mod is not None:
        return stripe_mod
    key = os.getenv("STRIPE_SECRET_KEY") or ""
    if not key:
        logger.warning("stop_charges: STRIPE_SECRET_KEY missing")
        return None
    try:
        import stripe as stripe_lib
    except ImportError:
        logger.warning("stop_charges: stripe package missing")
        return None
    stripe_lib.api_key = key
    return stripe_lib


async def _user_row(conn: Any, identity: str) -> Optional[Dict[str, Any]]:
    return await conn.fetchrow(
        """
        SELECT username, role, hardware_id,
               COALESCE(profile_data->>'name', name, username) AS name,
               COALESCE(profile_data->>'email', email, '') AS email,
               COALESCE(profile_data->>'phone', '') AS phone,
               COALESCE(profile_data->>'coach_id', '') AS coach_id,
               COALESCE(profile_data->>'assigned_coach', '') AS assigned_coach,
               COALESCE(profile_data->>'assigned_coach_id', '') AS assigned_coach_id,
               COALESCE(profile_data->>'stripe_customer_id', '') AS profile_cust,
               COALESCE(profile_data->>'stripe_subscription_id', '') AS profile_sub,
               subscription_status, tier
        FROM users
        WHERE hardware_id = $1 OR username = $1
        LIMIT 1
        """,
        identity,
    )


async def _coach_row(conn: Any, user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    coach_key = (
        _as_text(user.get("assigned_coach"))
        or _as_text(user.get("assigned_coach_id"))
        or _as_text(user.get("coach_id"))
    )
    if not coach_key:
        return None
    return await conn.fetchrow(
        """
        SELECT username, role,
               COALESCE(profile_data->>'name', name, username) AS name,
               COALESCE(profile_data->>'email', email, '') AS email
        FROM users
        WHERE username = $1 OR hardware_id = $1
        LIMIT 1
        """,
        coach_key,
    )


async def collect_subscription_ids(conn: Any, user: Dict[str, Any]) -> Dict[str, Any]:
    uid = await conn.fetchval(
        "SELECT id FROM users WHERE username = $1",
        user["username"],
    )
    rows = []
    if uid is not None:
        rows = await conn.fetch(
            """
            SELECT stripe_subscription_id, stripe_customer_id, status
            FROM subscriptions
            WHERE user_id = $1 AND stripe_subscription_id IS NOT NULL
            """,
            uid,
        )
    sub_ids: List[str] = []
    cust_ids: List[str] = []
    for row in rows:
        sid = _as_text(row["stripe_subscription_id"])
        cid = _as_text(row["stripe_customer_id"])
        if sid and sid not in sub_ids:
            sub_ids.append(sid)
        if cid and cid not in cust_ids:
            cust_ids.append(cid)
    profile_sub = _as_text(user.get("profile_sub"))
    profile_cust = _as_text(user.get("profile_cust"))
    if profile_sub and profile_sub not in sub_ids:
        sub_ids.append(profile_sub)
    if profile_cust and profile_cust not in cust_ids:
        cust_ids.append(profile_cust)
    return {"sub_ids": sub_ids, "cust_ids": cust_ids, "user_uuid": uid}


def _cancel_via_stripe(
    stripe_mod: Any,
    sub_ids: Sequence[str],
    cust_ids: Sequence[str],
    immediate: bool,
) -> Dict[str, Any]:
    cancelled: List[str] = []
    errors: List[str] = []
    seen = set()

    def _one(sub_id: str) -> None:
        if not sub_id or sub_id in seen or sub_id.startswith("sub_local"):
            return
        seen.add(sub_id)
        try:
            if immediate:
                _stripe_cancel_now(stripe_mod, sub_id)
            else:
                stripe_mod.Subscription.modify(sub_id, cancel_at_period_end=True)
            cancelled.append(sub_id)
        except Exception as exc:
            msg = str(exc)
            if "No such subscription" in msg or "already been canceled" in msg.lower() or "canceled" in msg.lower():
                cancelled.append(sub_id)
                return
            errors.append(f"{sub_id}:{type(exc).__name__}")
            logger.warning("stop_charges stripe cancel failed sub=%s err=%s", sub_id, type(exc).__name__)

    for sid in sub_ids:
        _one(sid)

    for cid in cust_ids:
        try:
            listed = stripe_mod.Subscription.list(customer=cid, status="all", limit=20)
            data = listed.get("data") if isinstance(listed, dict) else getattr(listed, "data", [])
            for item in data or []:
                st = item.get("status") if isinstance(item, dict) else getattr(item, "status", "")
                sid = item.get("id") if isinstance(item, dict) else getattr(item, "id", "")
                if should_cancel_stripe_status(st):
                    _one(_as_text(sid))
        except Exception as exc:
            errors.append(f"list:{cid}:{type(exc).__name__}")
            logger.warning("stop_charges stripe list failed cust=%s err=%s", cid[:12], type(exc).__name__)

    return {"cancelled": cancelled, "errors": errors}


async def _mark_pg_cancelled(conn: Any, user: Dict[str, Any], ids: Dict[str, Any], immediate: bool) -> None:
    uid = ids.get("user_uuid")
    if uid is not None:
        if immediate:
            await conn.execute(
                """
                UPDATE subscriptions
                   SET status = 'CANCELLED',
                       canceled_at = COALESCE(canceled_at, NOW()),
                       cancel_at_period_end = FALSE,
                       updated_at = NOW()
                 WHERE user_id = $1
                   AND status NOT IN ('CANCELLED', 'canceled')
                """,
                uid,
            )
        else:
            await conn.execute(
                """
                UPDATE subscriptions
                   SET cancel_at_period_end = TRUE, updated_at = NOW()
                 WHERE user_id = $1
                   AND status NOT IN ('CANCELLED', 'canceled')
                """,
                uid,
            )
    await conn.execute(
        """
        UPDATE users
           SET subscription_status = 'CANCELLED',
               profile_data = jsonb_set(
                   jsonb_set(
                       COALESCE(profile_data, '{}'::jsonb),
                       '{subscription_status}',
                       '"CANCELLED"'
                   ),
                   '{stripe_cancel_requested_at}',
                   to_jsonb($2::text)
               )
         WHERE username = $1
        """,
        user["username"],
        _utc_now_iso(),
    )


async def _record_event(
    conn: Any,
    user: Dict[str, Any],
    event_type: str,
    stripe_result: str,
    sub_ids: Sequence[str],
    cust_id: str,
    coach_username: str,
    client_notified: bool,
    coach_notified: bool,
    reason: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        await conn.execute(
            """
            INSERT INTO account_cancellation_events
                (username, hardware_id, event_type, stripe_customer_id,
                 stripe_subscription_ids, stripe_result, coach_username,
                 client_notified, coach_notified, reason, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
            """,
            user["username"],
            _as_text(user.get("hardware_id")),
            event_type,
            cust_id or None,
            list(sub_ids),
            stripe_result[:500],
            coach_username or None,
            client_notified,
            coach_notified,
            reason or None,
            json.dumps(metadata or {}),
        )
    except Exception as exc:
        logger.warning("stop_charges history insert failed: %s", type(exc).__name__)
    try:
        await conn.execute(
            """
            INSERT INTO audit_log (action_type, target_id, description, ip_address)
            VALUES ($1, $2, $3, '0.0.0.0'::inet)
            """,
            event_type.upper()[:64],
            _as_text(user.get("hardware_id")) or user["username"],
            f"{event_type}: stripe={stripe_result[:180]}",
        )
    except Exception:
        pass


async def _ensure_staged_deletion(conn: Any, hardware_id: str, hours: int = 30 * 24) -> bool:
    existing = await conn.fetchval(
        """
        SELECT id FROM staged_deletions
         WHERE user_id = $1 AND data_type = 'account'
           AND NOT executed AND NOT cancelled
         LIMIT 1
        """,
        hardware_id,
    )
    if existing:
        return False
    await conn.execute(
        """
        INSERT INTO staged_deletions
            (user_id, data_type, data_id, cooling_period_hours, executes_at)
        VALUES ($1, 'account', $1, $2, NOW() + make_interval(hours => $2::int))
        """,
        hardware_id,
        hours,
    )
    return True


async def _notify(
    notifier: Any,
    user: Dict[str, Any],
    coach: Optional[Dict[str, Any]],
    source: str,
    stripe_ok: bool,
) -> Dict[str, bool]:
    out = {"client": False, "coach": False}
    if notifier is None:
        return out
    name = _as_text(user.get("name")) or user["username"]
    email = _as_text(user.get("email"))
    phone = _as_text(user.get("phone")) or None
    try:
        if source == "account_deletion" and hasattr(notifier, "send_account_deletion_scheduled"):
            if email:
                out["client"] = bool(
                    await notifier.send_account_deletion_scheduled(
                        email, name, phone, charges_stopped=stripe_ok
                    )
                )
        elif hasattr(notifier, "send_stop_payment_confirmation") and email:
            out["client"] = bool(
                await notifier.send_stop_payment_confirmation(email, name, phone)
            )
    except Exception as exc:
        logger.warning("stop_charges client email failed: %s", type(exc).__name__)
    if coach and _as_text(coach.get("email")) and hasattr(notifier, "send_coach_client_charges_stopped"):
        try:
            out["coach"] = bool(
                await notifier.send_coach_client_charges_stopped(
                    coach["email"],
                    _as_text(coach.get("name")) or coach["username"],
                    name,
                    user["username"],
                    source,
                )
            )
        except Exception as exc:
            logger.warning("stop_charges coach email failed: %s", type(exc).__name__)
    return out


async def stop_charges_for_user(
    db_pool: Any,
    identity: str,
    *,
    source: str = "stop_payment",
    reason: str = "",
    immediate: bool = True,
    schedule_purge: bool = False,
    notifier: Any = None,
    stripe_mod: Any = None,
    emails: bool = True,
) -> Dict[str, Any]:
    """Cancel live Stripe subscriptions for a user and record history.

    Does not create or delete the users row. schedule_purge only inserts staged_deletions.
    """
    result: Dict[str, Any] = {
        "ok": False,
        "already_cancelled": False,
        "cancelled_ids": [],
        "errors": [],
        "message": "",
        "client_notified": False,
        "coach_notified": False,
    }
    if db_pool is None:
        result["message"] = "Database unavailable"
        return result

    stripe_lib = _init_stripe(stripe_mod)
    async with db_pool.acquire() as conn:
        user = await _user_row(conn, identity)
        if not user:
            result["message"] = "Account not found"
            return result
        user = dict(user)
        ids = await collect_subscription_ids(conn, user)
        stripe_out = {"cancelled": [], "errors": []}
        if stripe_lib is not None:
            stripe_out = _cancel_via_stripe(
                stripe_lib, ids["sub_ids"], ids["cust_ids"], immediate
            )
        elif ids["sub_ids"] or ids["cust_ids"]:
            stripe_out["errors"].append("stripe_unconfigured")

        await _mark_pg_cancelled(conn, user, ids, immediate)

        if schedule_purge and _as_text(user.get("hardware_id")):
            try:
                await _ensure_staged_deletion(conn, _as_text(user.get("hardware_id")))
            except Exception as exc:
                logger.warning("stop_charges staged_deletions failed: %s", type(exc).__name__)
                result["errors"].append("staged_deletions")

        coach = await _coach_row(conn, user)
        notify = {"client": False, "coach": False}
        if emails:
            notify = await _notify(
                notifier, user, coach, source, stripe_ok=not stripe_out["errors"]
            )

        stripe_result = "cancelled:" + ",".join(stripe_out["cancelled"][:8])
        if stripe_out["errors"]:
            stripe_result = "partial:" + ",".join(stripe_out["errors"][:6])
        if not stripe_out["cancelled"] and not ids["sub_ids"] and not ids["cust_ids"]:
            stripe_result = "no_stripe_ids"
            result["already_cancelled"] = True

        await _record_event(
            conn,
            user,
            source,
            stripe_result,
            stripe_out["cancelled"] or ids["sub_ids"],
            (ids["cust_ids"][0] if ids["cust_ids"] else ""),
            _as_text((coach or {}).get("username")),
            notify["client"],
            notify["coach"],
            reason,
            {"immediate": immediate, "errors": stripe_out["errors"]},
        )

        result["ok"] = not stripe_out["errors"] or bool(stripe_out["cancelled"]) or result["already_cancelled"]
        result["cancelled_ids"] = stripe_out["cancelled"]
        result["errors"] = stripe_out["errors"]
        result["client_notified"] = notify["client"]
        result["coach_notified"] = notify["coach"]
        if result["already_cancelled"] and not stripe_out["cancelled"]:
            result["message"] = "No live Stripe subscription. Confirmation emails sent."
        elif stripe_out["cancelled"]:
            result["message"] = "Stripe cancelled. No further charges will apply."
        elif stripe_out["errors"]:
            result["message"] = "Could not reach Stripe. Support will complete the stop-payment."
            result["ok"] = False
        else:
            result["ok"] = True
            result["message"] = "Billing marked cancelled. No further charges will apply."
        return result


async def cancel_leftover_stripe(conn: Any, hardware_id: str, stripe_mod: Any = None) -> None:
    """Best-effort Stripe cancel during 30-day purge. Uses an open connection."""
    user = await _user_row(conn, hardware_id)
    if not user:
        return
    ids = await collect_subscription_ids(conn, dict(user))
    stripe_lib = _init_stripe(stripe_mod)
    if stripe_lib is None:
        return
    _cancel_via_stripe(stripe_lib, ids["sub_ids"], ids["cust_ids"], immediate=True)


async def send_due_cooling_checkins(db_pool: Any, notifier: Any) -> int:
    """Email 24h / 15-day / 27-day deletion reminders and set checkin flags."""
    if db_pool is None or notifier is None:
        return 0
    sent = 0
    stages = (
        ("checkin_24h", "24 hours", 29, "24h"),
        ("checkin_midpoint", "15 days", 15, "midpoint"),
        ("checkin_final", "27 days", 3, "final"),
    )
    async with db_pool.acquire() as conn:
        for col, _label, remaining, kind in stages:
            interval = {
                "checkin_24h": "24 hours",
                "checkin_midpoint": "15 days",
                "checkin_final": "27 days",
            }[col]
            rows = await conn.fetch(
                f"""
                SELECT sd.id, sd.user_id
                  FROM staged_deletions sd
                 WHERE NOT sd.executed AND NOT sd.cancelled
                   AND NOT sd.{col}
                   AND sd.requested_at <= NOW() - INTERVAL '{interval}'
                """
            )
            for row in rows:
                await conn.execute(
                    f"UPDATE staged_deletions SET {col} = TRUE WHERE id = $1",
                    row["id"],
                )
                user = await _user_row(conn, row["user_id"])
                email = _as_text((user or {}).get("email"))
                name = _as_text((user or {}).get("name"))
                if email and hasattr(notifier, "send_cooling_checkin"):
                    try:
                        await notifier.send_cooling_checkin(
                            email, name, kind, remaining, _as_text((user or {}).get("phone")) or None
                        )
                        sent += 1
                    except Exception as exc:
                        logger.warning("cooling checkin email failed: %s", type(exc).__name__)
    return sent


def client_email_mentions_no_charges(html_body: str) -> bool:
    return "no further charges" in html.unescape(html_body or "").lower()
