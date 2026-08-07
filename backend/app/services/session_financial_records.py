"""Durable session financial records — approve obligations, default PM mirror,
Connect destination charges, and receipt audit events.

Used by: session_approval, bridge approve/auto-accept, billing PM endpoints,
SessionPaymentAgent.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.session_financial_records")


async def resolve_session_uuid(conn, session_id: str):
    """Return coaching_sessions.id (UUID) for a human session_id string."""
    if not session_id:
        return None
    row = await conn.fetchrow(
        "SELECT id FROM coaching_sessions WHERE session_id = $1 LIMIT 1",
        session_id,
    )
    return row["id"] if row else None


async def log_session_payment_event(
    db_pool,
    *,
    session_uuid=None,
    session_id: str = "",
    event_type: str,
    amount_cents: int = 0,
    stripe_payment_intent_id: Optional[str] = None,
    error_message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Append to session_payment_events (idempotent callers should dedupe)."""
    if not db_pool or not event_type:
        return False
    try:
        async with db_pool.acquire() as conn:
            sid = session_uuid
            if sid is None and session_id:
                sid = await resolve_session_uuid(conn, session_id)
            if sid is None:
                logger.warning(
                    "log_session_payment_event: no PG row for session_id=%s",
                    session_id,
                )
                return False
            await conn.execute(
                """INSERT INTO session_payment_events
                   (session_id, event_type, amount_cents, stripe_payment_intent_id,
                    error_message, metadata)
                   VALUES ($1, $2, $3, $4, $5, $6::jsonb)""",
                sid,
                event_type,
                int(amount_cents or 0),
                stripe_payment_intent_id,
                error_message,
                json.dumps(metadata or {}),
            )
        return True
    except Exception as e:
        logger.warning("log_session_payment_event(%s): %s", event_type, e)
        return False


async def record_approval_obligation(
    db_pool,
    session: Dict[str, Any],
    *,
    approved_by: str = "",
) -> bool:
    """Stamp approved_by into session_data and write obligation_created event.

    Call after upsert_session_pg so the coaching_sessions UUID exists.
    Dedupes: skips if obligation_created already logged for this session.
    """
    if not db_pool or not session.get("session_id"):
        return False
    sid_str = session["session_id"]
    approved_by = (
        approved_by
        or session.get("approved_by")
        or session.get("approved_via")
        or ""
    )
    try:
        coach_fee = float(session.get("coach_fee") or 0)
        platform_fee = float(session.get("platform_fee") or 0)
        coach_payout = float(session.get("coach_payout") or 0)
    except (TypeError, ValueError):
        coach_fee = platform_fee = coach_payout = 0.0
    try:
        price_cents = int(session.get("price_cents") or round(coach_fee * 100))
    except (TypeError, ValueError):
        price_cents = 0

    # Snapshot client's default PM for coach-facing audit
    client_hw = session.get("client_id") or ""
    default_pm = ""
    stripe_cust = ""
    try:
        async with db_pool.acquire() as conn:
            crow = await conn.fetchrow(
                """SELECT stripe_customer_id,
                          profile_data->>'stripe_customer_id' AS pd_cid,
                          profile_data->>'default_payment_method_id' AS default_pm
                   FROM users
                   WHERE hardware_id = $1 OR username = $1
                   LIMIT 1""",
                client_hw,
            )
            if crow:
                stripe_cust = (crow["stripe_customer_id"] or crow["pd_cid"] or "") or ""
                default_pm = (crow["default_pm"] or "") or ""
            if not default_pm and stripe_cust:
                default_pm = await _stripe_customer_default_pm(stripe_cust) or ""

            row = await conn.fetchrow(
                "SELECT id, session_data FROM coaching_sessions WHERE session_id = $1",
                sid_str,
            )
            if not row:
                return False
            already = await conn.fetchval(
                """SELECT 1 FROM session_payment_events
                   WHERE session_id = $1 AND event_type = 'obligation_created'
                   LIMIT 1""",
                row["id"],
            )
            patch = {
                "approved_by": approved_by,
                "approved_at": session.get("approved_at")
                or datetime.now(timezone.utc).isoformat(),
                "coach_fee": coach_fee,
                "platform_fee": platform_fee,
                "coach_payout": coach_payout,
                "client_default_pm_id": default_pm,
                "client_stripe_customer_id": stripe_cust,
                "billing_obligation": "pending_collection",
            }
            session["approved_by"] = approved_by
            if default_pm:
                session["client_default_pm_id"] = default_pm
            await conn.execute(
                """UPDATE coaching_sessions
                   SET session_data = COALESCE(session_data, '{}'::jsonb) || $2::jsonb,
                       updated_at = NOW()
                   WHERE id = $1""",
                row["id"],
                json.dumps(patch),
            )
            if already:
                return True
            meta = {
                "note": "Session accepted — fee obligation recorded for invoicing",
                "approved_by": approved_by,
                "coach_fee": coach_fee,
                "platform_fee": platform_fee,
                "coach_payout": coach_payout,
                "price_cents": price_cents,
                "client_default_pm_id": default_pm,
                "client_stripe_customer_id": stripe_cust,
                "coach_id": session.get("coach_id"),
                "client_id": session.get("client_id"),
                "client_name": session.get("client_name"),
            }
            await conn.execute(
                """INSERT INTO session_payment_events
                   (session_id, event_type, amount_cents, metadata)
                   VALUES ($1, 'obligation_created', $2, $3::jsonb)""",
                row["id"],
                price_cents,
                json.dumps(meta),
            )
        return True
    except Exception as e:
        logger.warning("record_approval_obligation(%s): %s", sid_str, e)
        return False


async def _stripe_customer_default_pm(customer_id: str) -> Optional[str]:
    try:
        import stripe

        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        if not stripe.api_key or not customer_id:
            return None
        cu = stripe.Customer.retrieve(customer_id)
        inv = getattr(cu, "invoice_settings", None) or {}
        if isinstance(inv, dict):
            pm = inv.get("default_payment_method")
        else:
            pm = getattr(inv, "default_payment_method", None)
        if pm:
            return pm if isinstance(pm, str) else getattr(pm, "id", None)
        pms = stripe.PaymentMethod.list(customer=customer_id, type="card", limit=1)
        if pms.data:
            return pms.data[0].id
    except Exception as e:
        logger.warning("_stripe_customer_default_pm: %s", e)
    return None


async def mirror_default_payment_method(
    db_pool,
    *,
    user_key: str,
    payment_method_id: str,
    stripe_customer_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Set Stripe customer default PM and mirror onto users.profile_data.

    user_key: hardware_id or username.
    """
    out: Dict[str, Any] = {
        "stripe_updated": False,
        "profile_updated": False,
        "payment_method_id": payment_method_id,
        "last4": None,
        "brand": None,
    }
    if not payment_method_id:
        return out

    brand = last4 = None
    try:
        import stripe

        stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        if stripe.api_key:
            pm = stripe.PaymentMethod.retrieve(payment_method_id)
            card = getattr(pm, "card", None)
            if card:
                brand = getattr(card, "brand", None)
                last4 = getattr(card, "last4", None)
            cust = stripe_customer_id or getattr(pm, "customer", None)
            if cust:
                stripe.Customer.modify(
                    cust,
                    invoice_settings={"default_payment_method": payment_method_id},
                )
                out["stripe_updated"] = True
                stripe_customer_id = cust
    except Exception as e:
        logger.warning("mirror_default_payment_method Stripe: %s", e)

    out["brand"] = brand
    out["last4"] = last4

    if not db_pool or not user_key:
        return out
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT username, hardware_id, role,
                          COALESCE(NULLIF(stripe_customer_id, ''),
                                   profile_data->>'stripe_customer_id') AS cid
                   FROM users
                   WHERE hardware_id = $1 OR username = $1
                   LIMIT 1""",
                user_key,
            )
            if not row:
                return out
            patch = {
                "default_payment_method_id": payment_method_id,
                "has_payment_method": True,
            }
            if last4:
                patch["payment_method_last4"] = str(last4)
            if brand:
                patch["payment_method_brand"] = str(brand)
            if stripe_customer_id or row["cid"]:
                patch["stripe_customer_id"] = stripe_customer_id or row["cid"]
            await conn.execute(
                """UPDATE users
                   SET profile_data = COALESCE(profile_data, '{}'::jsonb) || $2::jsonb,
                       stripe_customer_id = COALESCE(NULLIF($3, ''), stripe_customer_id),
                       updated_at = NOW()
                   WHERE username = $1""",
                row["username"],
                json.dumps(patch),
                stripe_customer_id or row["cid"] or "",
            )
            out["profile_updated"] = True
            # Mirror readiness onto assigned coach profile for portal billing view
            if (row["role"] or "").upper() == "CLIENT":
                await _mirror_client_pm_to_coach(
                    conn,
                    client_username=row["username"],
                    client_hw=row["hardware_id"] or "",
                    payment_method_id=payment_method_id,
                    last4=last4,
                    brand=brand,
                )
    except Exception as e:
        logger.warning("mirror_default_payment_method profile: %s", e)
    return out


async def _mirror_client_pm_to_coach(
    conn,
    *,
    client_username: str,
    client_hw: str,
    payment_method_id: str,
    last4: Optional[str],
    brand: Optional[str],
) -> None:
    """Store client default-PM readiness under coach profile billing_clients map."""
    try:
        crow = await conn.fetchrow(
            """SELECT profile_data->>'coach_id' AS coach_id,
                      profile_data->>'assigned_coach_id' AS assigned_coach_id,
                      profile_data->>'assigned_coach' AS assigned_coach
               FROM users WHERE username = $1""",
            client_username,
        )
        if not crow:
            return
        coach_key = crow["coach_id"] or crow["assigned_coach_id"] or crow["assigned_coach"]
        if not coach_key:
            return
        coach = await conn.fetchrow(
            """SELECT username, profile_data
               FROM users
               WHERE (hardware_id = $1 OR username = $1) AND role = 'COACH'
               LIMIT 1""",
            coach_key,
        )
        if not coach:
            return
        profile = coach["profile_data"] or {}
        if isinstance(profile, str):
            profile = json.loads(profile)
        billing_clients = profile.get("billing_clients") or {}
        if not isinstance(billing_clients, dict):
            billing_clients = {}
        billing_clients[client_username] = {
            "hardware_id": client_hw,
            "default_payment_method_id": payment_method_id,
            "has_payment_method": True,
            "payment_method_last4": last4,
            "payment_method_brand": brand,
            "mirrored_at": datetime.now(timezone.utc).isoformat(),
        }
        profile["billing_clients"] = billing_clients
        await conn.execute(
            "UPDATE users SET profile_data = $2::jsonb, updated_at = NOW() WHERE username = $1",
            coach["username"],
            json.dumps(profile),
        )
    except Exception as e:
        logger.warning("_mirror_client_pm_to_coach: %s", e)


async def resolve_charge_payment_method(customer_id: str) -> Optional[str]:
    """Prefer Stripe invoice default, then first card."""
    return await _stripe_customer_default_pm(customer_id)


async def mark_coach_ledger_collected(
    db_pool,
    *,
    coach_id: str,
    session_id: str,
    stripe_payment_intent_id: str,
    amount_cents: int,
    receipt_url: Optional[str] = None,
) -> bool:
    """Flip matching financial_ledger txn to collected; append charge audit fields."""
    if not db_pool or not coach_id or not session_id:
        return False
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT username, profile_data FROM users
                   WHERE (hardware_id = $1 OR username = $1) AND role = 'COACH'
                   LIMIT 1""",
                coach_id,
            )
            if not row:
                return False
            profile = row["profile_data"] or {}
            if isinstance(profile, str):
                profile = json.loads(profile)
            ledger = profile.get("financial_ledger") or []
            if not isinstance(ledger, list):
                ledger = []
            updated = False
            for txn in ledger:
                if txn.get("session_id") == session_id and txn.get("type") == "session_fee":
                    txn["status"] = "collected"
                    txn["stripe_payment_intent_id"] = stripe_payment_intent_id
                    txn["collected_at"] = datetime.now(timezone.utc).isoformat()
                    txn["amount_cents"] = amount_cents
                    if receipt_url:
                        txn["receipt_url"] = receipt_url
                    updated = True
                    break
            if not updated:
                ledger.append(
                    {
                        "txn_id": f"TXN_COLLECT_{session_id}",
                        "date": str(datetime.now(timezone.utc).date()),
                        "type": "session_fee",
                        "session_id": session_id,
                        "status": "collected",
                        "stripe_payment_intent_id": stripe_payment_intent_id,
                        "amount_cents": amount_cents,
                        "receipt_url": receipt_url,
                    }
                )
            profile["financial_ledger"] = ledger
            await conn.execute(
                "UPDATE users SET profile_data = $2::jsonb, updated_at = NOW() WHERE username = $1",
                row["username"],
                json.dumps(profile),
            )
        return True
    except Exception as e:
        logger.warning("mark_coach_ledger_collected: %s", e)
        return False


def platform_fee_cents_from_session(session_row: Any, amount_cents: int) -> int:
    """Derive application_fee_amount from session_data.platform_fee or 30%."""
    try:
        sd = session_row.get("session_data") if hasattr(session_row, "get") else None
        if sd is None and hasattr(session_row, "__getitem__"):
            try:
                sd = session_row["session_data"]
            except Exception:
                sd = None
        if isinstance(sd, str):
            sd = json.loads(sd)
        if isinstance(sd, dict) and sd.get("platform_fee") is not None:
            return max(0, int(round(float(sd["platform_fee"]) * 100)))
    except Exception:
        pass
    return max(0, int(round(amount_cents * 0.30)))
