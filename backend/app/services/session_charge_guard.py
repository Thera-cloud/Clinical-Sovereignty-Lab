"""Session charge guard — one coaching session, one collection.

Root cause of the 2026-11-05 Blake Barnes incident: a Zoom-repair write
(`upsert_session_pg`) flipped `coaching_sessions.payment_status` from `paid`
back to `pending`, and the payment agent's only "already paid" check was that
single mutable column. Four 30-minute cycles → four new $90 PaymentIntents.

This module gives every charge path four independent checks before money moves:

1. DB truth    — payment_status / stripe_payment_intent_id / billing_obligation /
                 `charge_succeeded` ledger rows (any one of them says "collected" → stop).
2. Atomic claim — a conditional UPDATE that only one caller can win per session
                 (protects against overlapping cycles or two processes).
3. Stripe truth — PaymentIntent.search on our session metadata (independent of
                 our DB; catches the case where the DB lost state). Fails CLOSED.
4. Idempotency  — a stable Stripe idempotency key, so a retried create cannot
                 mint a second PaymentIntent for the same session/amount/card.

Plus a never-downgrade SQL guard for `payment_status` used by the shared upsert.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.session_charge_guard")

# Money has moved (or been returned) in these states — a generic upsert must
# never regress them to pending/cancelled. Only a money-state → money-state
# transition (paid → refunded) is allowed through.
MONEY_STATES = ("paid", "refunded", "partially_refunded")

# A claim older than this is considered abandoned (process died mid-charge).
# Re-claim is still only allowed after the Stripe-side check finds nothing.
CLAIM_STALE_MINUTES = 120

# Sanity ceiling — a corrupted price (e.g. dollars*100*100) must never reach Stripe.
MAX_SESSION_CHARGE_CENTS = int(os.getenv("SESSION_MAX_CHARGE_CENTS", "100000"))

_MONEY_STATES_SQL = "('" + "','".join(MONEY_STATES) + "')"

# For `INSERT ... ON CONFLICT (session_id) DO UPDATE SET payment_status = <this>`.
PAYMENT_STATUS_GUARD_SQL = f"""CASE
    WHEN LOWER(COALESCE(coaching_sessions.payment_status, '')) IN {_MONEY_STATES_SQL}
     AND LOWER(COALESCE(EXCLUDED.payment_status, '')) NOT IN {_MONEY_STATES_SQL}
    THEN coaching_sessions.payment_status
    ELSE EXCLUDED.payment_status END"""

# Re-assert collected markers inside session_data after a JSON merge so a stale
# caller copy cannot erase them.
SESSION_DATA_GUARD_SQL = """CASE
    WHEN COALESCE(coaching_sessions.session_data->>'billing_obligation', '') = 'collected'
    THEN jsonb_strip_nulls(jsonb_build_object(
            'billing_obligation', 'collected',
            'stripe_payment_intent_id', coaching_sessions.session_data->'stripe_payment_intent_id'))
    ELSE '{}'::jsonb END"""

# Reusable WHERE fragment for "this session has never been collected".
# `cs` must alias coaching_sessions in the calling query.
NOT_COLLECTED_SQL = """COALESCE(cs.stripe_payment_intent_id, '') = ''
                   AND COALESCE(cs.session_data->>'billing_obligation', '') <> 'collected'
                   AND NOT EXISTS (
                       SELECT 1 FROM session_payment_events spe
                       WHERE spe.session_id = cs.id AND spe.event_type = 'charge_succeeded'
                   )"""


def flatten_session_data_extra(extra: Dict[str, Any]) -> Dict[str, Any]:
    """Callers sometimes pass the row's own `session_data` dict back as a key.

    Merging that unchanged produces `session_data.session_data.session_data…`
    (Blake's row was nested 4 deep). Lift the nested keys to the top level,
    letting explicit top-level keys win, and drop the nested container.
    """
    if not isinstance(extra, dict):
        return {}
    out = dict(extra)
    nested = out.pop("session_data", None)
    if isinstance(nested, str):
        try:
            nested = json.loads(nested) if nested else {}
        except Exception:
            nested = {}
    if isinstance(nested, dict):
        nested = flatten_session_data_extra(nested)
        merged = dict(nested)
        merged.update(out)
        out = merged
    return out


def collected_reason(state: Optional[Dict[str, Any]]) -> Optional[str]:
    """Return why this session must not be charged, or None when it is chargeable."""
    if not state:
        return "session row not found"
    ps = str(state.get("payment_status") or "").lower()
    if ps in MONEY_STATES:
        return f"payment_status={ps}"
    if ps != "pending":
        return f"payment_status={ps or 'empty'} is not pending"
    if str(state.get("stripe_payment_intent_id") or "").strip():
        return f"stripe_payment_intent_id already set ({state['stripe_payment_intent_id']})"
    if str(state.get("billing_obligation") or "") == "collected":
        return "billing_obligation=collected"
    try:
        if int(state.get("charges") or 0) > 0:
            return f"{int(state['charges'])} charge_succeeded event(s) already recorded"
    except (TypeError, ValueError):
        pass
    return None


async def collection_state(conn, session_uuid) -> Optional[Dict[str, Any]]:
    """Fresh read of every DB signal that says 'already collected'."""
    row = await conn.fetchrow(
        """SELECT cs.payment_status,
                  cs.stripe_payment_intent_id,
                  cs.session_data->>'billing_obligation' AS billing_obligation,
                  cs.session_data->>'charge_claim_at' AS charge_claim_at,
                  (SELECT COUNT(*) FROM session_payment_events e
                    WHERE e.session_id = cs.id AND e.event_type = 'charge_succeeded') AS charges
             FROM coaching_sessions cs
            WHERE cs.id = $1""",
        session_uuid,
    )
    return dict(row) if row else None


async def claim_charge(conn, session_uuid, *, now: Optional[datetime] = None) -> bool:
    """Atomically mark this session as 'being charged'. Only one caller wins.

    The WHERE clause re-checks every collected signal, so a stale in-memory
    view can never win the claim.
    """
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    status = await conn.execute(
        f"""UPDATE coaching_sessions cs
               SET session_data = COALESCE(cs.session_data, '{{}}'::jsonb)
                                  || jsonb_build_object('charge_claim_at', $2::text),
                   updated_at = NOW()
             WHERE cs.id = $1
               AND LOWER(COALESCE(cs.payment_status, '')) = 'pending'
               AND {NOT_COLLECTED_SQL}
               AND (COALESCE(cs.session_data->>'charge_claim_at', '') = ''
                    OR (cs.session_data->>'charge_claim_at')::timestamptz
                       < NOW() - make_interval(mins => $3))""",
        session_uuid,
        stamp,
        CLAIM_STALE_MINUTES,
    )
    return str(status or "").strip().upper() == "UPDATE 1"


async def release_claim(conn, session_uuid) -> None:
    try:
        await conn.execute(
            """UPDATE coaching_sessions
                  SET session_data = COALESCE(session_data, '{}'::jsonb) - 'charge_claim_at',
                      updated_at = NOW()
                WHERE id = $1""",
            session_uuid,
        )
    except Exception as e:
        logger.warning("release_claim %s: %s", session_uuid, e)


def stripe_search_queries(session_uuid, session_id_str: str = "") -> list:
    """Stripe Search rejects a query that mixes AND and OR.

    Each clause is AND-only. Callers search them separately.
    """
    queries = [f"metadata['session_uuid']:'{session_uuid}' AND status:'succeeded'"]
    sid = str(session_id_str or "").strip()
    if sid and sid != str(session_uuid):
        queries.append(f"metadata['session_id']:'{sid}' AND status:'succeeded'")
    return queries


def stripe_search_query(session_uuid, session_id_str: str = "") -> str:
    """First AND-only search. Kept for callers that expect one string."""
    return stripe_search_queries(session_uuid, session_id_str)[0]


def _pi_succeeded(pi) -> bool:
    status = getattr(pi, "status", None)
    if status is None and isinstance(pi, dict):
        status = pi.get("status")
    return str(status or "") == "succeeded"


def stripe_existing_charge(stripe_mod, session_uuid, session_id_str: str = ""):
    """Ask Stripe whether a succeeded PaymentIntent already exists for this session.

    Raises on API failure — callers must treat that as "cannot verify" and skip
    the charge for this cycle (fail closed). Returns the PaymentIntent or None.
    """
    for query in stripe_search_queries(session_uuid, session_id_str):
        res = stripe_mod.PaymentIntent.search(query=query, limit=5)
        data = getattr(res, "data", None) or (res.get("data") if isinstance(res, dict) else None) or []
        for pi in data:
            if _pi_succeeded(pi):
                return pi
    return None


def idempotency_key(session_uuid, amount_cents: int, pm_id: str) -> str:
    """Same session + amount + card within Stripe's 24h window → same PaymentIntent."""
    return f"sess-{session_uuid}-{int(amount_cents)}-{pm_id or 'nopm'}"[:255]


def amount_within_ceiling(amount_cents: int) -> bool:
    try:
        return 0 < int(amount_cents) <= MAX_SESSION_CHARGE_CENTS
    except (TypeError, ValueError):
        return False


async def record_payment_history(
    conn,
    *,
    client_key: str,
    intent_id: str,
    charge_id: Optional[str],
    amount_cents: int,
    receipt_url: Optional[str],
    metadata: Dict[str, Any],
) -> bool:
    """Mirror a successful session charge into payment_history (Billing → History).

    Idempotent on stripe_payment_intent_id. Never raises.
    """
    try:
        status = await conn.execute(
            """INSERT INTO payment_history
                   (user_id, stripe_charge_id, stripe_payment_intent_id, event_type,
                    amount_cents, currency, status, receipt_url, metadata)
               SELECT u.id, $2::text, $3::text, 'charge.succeeded', $4::int, 'usd', 'succeeded',
                      $5::text, $6::jsonb
                 FROM users u
                WHERE (u.hardware_id = $1::text OR u.id::text = $1::text OR u.username = $1::text)
                  AND NOT EXISTS (SELECT 1 FROM payment_history ph
                                   WHERE ph.stripe_payment_intent_id = $3::text)
                LIMIT 1""",
            str(client_key or ""),
            charge_id or None,
            intent_id,
            int(amount_cents),
            receipt_url or None,
            json.dumps(metadata or {}),
        )
        return str(status or "").strip().upper().startswith("INSERT 0 1")
    except Exception as e:
        logger.warning("record_payment_history %s: %s", intent_id, e)
        return False


async def session_collected_elsewhere(conn, session_id_str: str, this_payment_intent: str = "") -> Optional[str]:
    """For invoice auto-pay: is the invoice's session already paid by a different PaymentIntent?"""
    sid = str(session_id_str or "").strip()
    if not sid:
        return None
    row = await conn.fetchrow(
        """SELECT payment_status, stripe_payment_intent_id,
                  session_data->>'billing_obligation' AS billing_obligation
             FROM coaching_sessions WHERE session_id = $1 LIMIT 1""",
        sid,
    )
    if not row:
        return None
    ps = str(row["payment_status"] or "").lower()
    pi = str(row["stripe_payment_intent_id"] or "").strip()
    mine = str(this_payment_intent or "").strip()
    if ps in MONEY_STATES and pi and pi != mine:
        return f"session {sid} already {ps} via {pi}"
    if str(row["billing_obligation"] or "") == "collected" and pi and pi != mine:
        return f"session {sid} already collected via {pi}"
    return None
