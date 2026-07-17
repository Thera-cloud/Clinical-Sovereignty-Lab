"""
QUANTUM-CRYSTAL-ARCH: Nate-mediated coach↔client scheduling negotiation (option 1).

Coach still decides: approve | busy | propose alt time(s).
Nate narrates, suggests real slots from coach_slot_engine, and pushes WS updates.
Never invents times. Feature flag: ENABLE_NATE_SESSION_NEGOTIATION.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.session_negotiation")

ACTIVE_STATUSES = frozenset({"awaiting_coach", "alt_proposed", "awaiting_client"})
TERMINAL_STATUSES = frozenset({"approved", "declined", "busy", "expired", "cancelled"})

_APPROVE_RE = re.compile(
    r"\b(approve|accept|confirm|yes[,.]?\s*(i\s+can|that\s+works)|book\s+it)\b",
    re.I,
)
_BUSY_RE = re.compile(
    r"\b(busy|not\s+available|can'?t\s+make\s+it|unavailable|decline|reject)\b",
    re.I,
)
_ALT_RE = re.compile(
    r"\b(different\s+time|another\s+time|reschedule|propose|suggest|how\s+about|instead)\b",
    re.I,
)
_ACCEPT_ALT_RE = re.compile(
    r"\b(yes|yeah|yep|sure|ok(?:ay)?|that\s+works|i'?ll\s+take|book\s+(that|it)|accept)\b",
    re.I,
)
_REJECT_ALT_RE = re.compile(
    r"\b(no|nope|none\s+of\s+(those|them)|different|not\s+those)\b",
    re.I,
)


def negotiation_enabled() -> bool:
    return os.getenv("ENABLE_NATE_SESSION_NEGOTIATION", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _iso(dt: Any) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(dt)


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _row_to_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    d = dict(row)
    for k in ("alt_slots", "metadata"):
        v = d.get(k)
        if isinstance(v, str):
            try:
                d[k] = json.loads(v)
            except Exception:
                d[k] = [] if k == "alt_slots" else {}
    for k in ("proposed_start", "proposed_end", "created_at", "updated_at"):
        if d.get(k) is not None:
            d[k] = _iso(d[k])
    if d.get("id") is not None:
        d["id"] = str(d["id"])
    return d


async def suggest_alt_slots(
    db_pool: Any,
    coach_id: str,
    *,
    around: Optional[datetime] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Real availability only — never invented."""
    if not db_pool or not coach_id:
        return []
    try:
        from app.services.coach_slot_engine import compute_available_slots
    except Exception as e:
        logger.warning("session_negotiation: slot engine unavailable: %s", e)
        return []

    base = around or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    collected: List[Dict[str, Any]] = []
    for day_offset in range(0, 14):
        day = (base + timedelta(days=day_offset)).date().isoformat()
        try:
            result = await compute_available_slots(db_pool, coach_id, day)
        except Exception as e:
            logger.warning("session_negotiation: compute_available_slots failed: %s", e)
            continue
        slots = (result or {}).get("available_slots") or []
        for slot in slots:
            if isinstance(slot, dict):
                start = slot.get("start") or slot.get("scheduled_start") or slot.get("slot_start")
                end = slot.get("end") or slot.get("scheduled_end") or slot.get("slot_end")
            else:
                start, end = slot, None
            if not start:
                continue
            # Skip the originally requested moment if exact match
            if around and _parse_dt(start) and abs((_parse_dt(start) - around).total_seconds()) < 60:
                continue
            collected.append({"start": _iso(_parse_dt(start) or start), "end": _iso(_parse_dt(end)) if end else None})
            if len(collected) >= limit:
                return collected
    return collected


async def open_from_pending_session(
    db_pool: Any,
    session: Dict[str, Any],
) -> Dict[str, Any]:
    """Open negotiation when a pending_approval booking is created."""
    if not negotiation_enabled():
        return {"ok": False, "error": "flag_off"}
    if not db_pool:
        return {"ok": False, "error": "no_db"}
    session_id = (session.get("session_id") or "").strip()
    client_id = (session.get("client_id") or session.get("client_hw_id") or "").strip()
    coach_id = (session.get("coach_id") or "").strip()
    if not session_id or not client_id or not coach_id:
        return {"ok": False, "error": "missing_ids"}
    if (session.get("status") or "").lower() not in ("pending_approval",):
        return {"ok": False, "error": "not_pending"}

    start = _parse_dt(session.get("scheduled_start"))
    end = _parse_dt(session.get("scheduled_end"))
    client_name = session.get("client_name") or "your client"

    try:
        async with db_pool.acquire() as conn:
            # One active negotiation per session
            existing = await conn.fetchrow(
                """
                SELECT * FROM session_negotiations
                WHERE session_id = $1 AND status = ANY($2::text[])
                ORDER BY created_at DESC LIMIT 1
                """,
                session_id,
                list(ACTIVE_STATUSES),
            )
            if existing:
                neg = _row_to_dict(existing)
            else:
                row = await conn.fetchrow(
                    """
                    INSERT INTO session_negotiations (
                        session_id, client_id, coach_id, status,
                        proposed_start, proposed_end, client_note, metadata
                    ) VALUES ($1, $2, $3, 'awaiting_coach', $4, $5, $6, $7::jsonb)
                    RETURNING *
                    """,
                    session_id,
                    client_id,
                    coach_id,
                    start,
                    end,
                    (session.get("notes") or "")[:2000],
                    json.dumps({"source": "pending_booking", "client_name": client_name}),
                )
                neg = _row_to_dict(row)
    except Exception as e:
        logger.warning("session_negotiation: open failed: %s", e)
        return {"ok": False, "error": "db_error", "detail": str(e)[:200]}

    when = neg.get("proposed_start") or "the requested time"
    coach_msg = (
        f"{client_name} requested a session at {when}. "
        f"Reply approve, busy, or propose a different time — or use the negotiation actions."
    )
    client_msg = (
        f"I sent your session request to your coach for {when}. "
        f"I'll update you as soon as they approve, say they're busy, or suggest another time."
    )
    return {
        "ok": True,
        "negotiation": neg,
        "coach_notify": {
            "type": "session_negotiation_update",
            "negotiation": neg,
            "actions": ["approve", "busy", "alt"],
            "nate_message": coach_msg,
            "audience": "coach",
        },
        "client_notify": {
            "type": "session_negotiation_update",
            "negotiation": neg,
            "nate_message": client_msg,
            "audience": "client",
        },
        "coach_nate_text": coach_msg,
        "client_nate_text": client_msg,
    }


async def get_open_for_user(
    db_pool: Any, user_id: str, *, as_role: str
) -> Optional[Dict[str, Any]]:
    if not db_pool or not user_id:
        return None
    col = "coach_id" if as_role.upper() == "COACH" else "client_id"
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT * FROM session_negotiations
                WHERE {col} = $1 AND status = ANY($2::text[])
                ORDER BY updated_at DESC LIMIT 1
                """,
                user_id,
                list(ACTIVE_STATUSES),
            )
            return _row_to_dict(row) if row else None
    except Exception as e:
        logger.warning("session_negotiation: get_open failed: %s", e)
        return None


async def coach_decide(
    db_pool: Any,
    *,
    coach_id: str,
    session_id: Optional[str] = None,
    negotiation_id: Optional[str] = None,
    decision: str,
    alt_slots: Optional[List[Dict[str, Any]]] = None,
    note: str = "",
    force: bool = False,
) -> Dict[str, Any]:
    """
    decision: approve | busy | alt
    Returns bridge_action hints: approve_session | decline_session | none
    force=True: allow staging inbound fallback when prod flag is off.
    """
    if not force and not negotiation_enabled():
        return {"ok": False, "error": "flag_off"}
    if not db_pool or not coach_id:
        return {"ok": False, "error": "missing_args"}
    decision = (decision or "").strip().lower()
    if decision not in ("approve", "busy", "alt"):
        return {"ok": False, "error": "invalid_decision"}

    try:
        async with db_pool.acquire() as conn:
            if negotiation_id:
                row = await conn.fetchrow(
                    "SELECT * FROM session_negotiations WHERE id = $1::uuid AND coach_id = $2",
                    negotiation_id,
                    coach_id,
                )
            else:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM session_negotiations
                    WHERE session_id = $1 AND coach_id = $2
                      AND status = ANY($3::text[])
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    session_id or "",
                    coach_id,
                    list(ACTIVE_STATUSES),
                )
            if not row:
                return {"ok": False, "error": "negotiation_not_found"}
            neg = _row_to_dict(row)
            if neg.get("status") not in ACTIVE_STATUSES:
                return {"ok": False, "error": "not_active", "negotiation": neg}

            if decision == "approve":
                updated = await conn.fetchrow(
                    """
                    UPDATE session_negotiations
                    SET status = 'approved', coach_note = $2, updated_at = NOW()
                    WHERE id = $1::uuid RETURNING *
                    """,
                    neg["id"],
                    (note or "")[:2000],
                )
                neg = _row_to_dict(updated)
                client_text = (
                    f"Good news — your coach approved the session"
                    f"{' at ' + neg['proposed_start'] if neg.get('proposed_start') else ''}. "
                    f"It's on your schedule."
                )
                return {
                    "ok": True,
                    "negotiation": neg,
                    "bridge_action": "approve_session",
                    "session_id": neg["session_id"],
                    "client_notify": {
                        "type": "session_negotiation_update",
                        "negotiation": neg,
                        "nate_message": client_text,
                        "audience": "client",
                    },
                    "coach_nate_text": "Approved — I've confirmed with your client.",
                    "client_nate_text": client_text,
                }

            if decision == "busy":
                alts = alt_slots or await suggest_alt_slots(
                    db_pool, coach_id, around=_parse_dt(neg.get("proposed_start"))
                )
                new_status = "alt_proposed" if alts else "busy"
                updated = await conn.fetchrow(
                    """
                    UPDATE session_negotiations
                    SET status = $2, alt_slots = $3::jsonb, coach_note = $4,
                        round = LEAST(round + 1, max_rounds), updated_at = NOW()
                    WHERE id = $1::uuid RETURNING *
                    """,
                    neg["id"],
                    new_status,
                    json.dumps(alts),
                    (note or "Coach unavailable at requested time")[:2000],
                )
                neg = _row_to_dict(updated)
                if alts:
                    client_text = (
                        "Your coach isn't free at that time. Here are other open slots — "
                        "tell me which works, or say none of those."
                    )
                    bridge_action = "none"
                else:
                    client_text = (
                        "Your coach isn't available for that request right now. "
                        "We can try another day whenever you're ready."
                    )
                    bridge_action = "decline_session"
                return {
                    "ok": True,
                    "negotiation": neg,
                    "bridge_action": bridge_action,
                    "session_id": neg["session_id"],
                    "client_notify": {
                        "type": "session_negotiation_update",
                        "negotiation": neg,
                        "actions": ["accept_alt", "reject_alt"] if alts else [],
                        "alt_slots": alts,
                        "nate_message": client_text,
                        "audience": "client",
                    },
                    "coach_nate_text": (
                        "Noted — I offered your client alternate times."
                        if alts
                        else "Noted — I told your client you're unavailable."
                    ),
                    "client_nate_text": client_text,
                }

            # alt
            alts = alt_slots or await suggest_alt_slots(
                db_pool, coach_id, around=_parse_dt(neg.get("proposed_start"))
            )
            if not alts:
                return {"ok": False, "error": "no_alt_slots"}
            if int(neg.get("round") or 1) >= int(neg.get("max_rounds") or 3):
                return {"ok": False, "error": "max_rounds"}
            updated = await conn.fetchrow(
                """
                UPDATE session_negotiations
                SET status = 'alt_proposed', alt_slots = $2::jsonb, coach_note = $3,
                    round = round + 1, updated_at = NOW()
                WHERE id = $1::uuid RETURNING *
                """,
                neg["id"],
                json.dumps(alts),
                (note or "")[:2000],
            )
            neg = _row_to_dict(updated)
            client_text = (
                "Your coach suggested different times. Which of these works for you?"
            )
            return {
                "ok": True,
                "negotiation": neg,
                "bridge_action": "none",
                "session_id": neg["session_id"],
                "client_notify": {
                    "type": "session_negotiation_update",
                    "negotiation": neg,
                    "actions": ["accept_alt", "reject_alt"],
                    "alt_slots": alts,
                    "nate_message": client_text,
                    "audience": "client",
                },
                "coach_nate_text": "I sent those alternate times to your client.",
                "client_nate_text": client_text,
            }
    except Exception as e:
        logger.warning("session_negotiation: coach_decide failed: %s", e)
        return {"ok": False, "error": "db_error", "detail": str(e)[:200]}


async def client_respond(
    db_pool: Any,
    *,
    client_id: str,
    negotiation_id: Optional[str] = None,
    session_id: Optional[str] = None,
    decision: str,
    chosen_start: Optional[str] = None,
    note: str = "",
    force: bool = False,
) -> Dict[str, Any]:
    """
    decision: accept_alt | reject_alt
    On accept_alt with chosen_start → bridge_action reschedule_and_approve
    force=True: allow staging inbound fallback when prod flag is off.
    """
    if not force and not negotiation_enabled():
        return {"ok": False, "error": "flag_off"}
    if not db_pool or not client_id:
        return {"ok": False, "error": "missing_args"}
    decision = (decision or "").strip().lower()
    if decision not in ("accept_alt", "reject_alt"):
        return {"ok": False, "error": "invalid_decision"}

    try:
        async with db_pool.acquire() as conn:
            if negotiation_id:
                row = await conn.fetchrow(
                    "SELECT * FROM session_negotiations WHERE id = $1::uuid AND client_id = $2",
                    negotiation_id,
                    client_id,
                )
            else:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM session_negotiations
                    WHERE session_id = $1 AND client_id = $2
                      AND status = ANY($3::text[])
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    session_id or "",
                    client_id,
                    list(ACTIVE_STATUSES),
                )
            if not row:
                return {"ok": False, "error": "negotiation_not_found"}
            neg = _row_to_dict(row)
            if neg.get("status") != "alt_proposed":
                return {"ok": False, "error": "no_alts_pending", "negotiation": neg}

            if decision == "reject_alt":
                updated = await conn.fetchrow(
                    """
                    UPDATE session_negotiations
                    SET status = 'awaiting_coach', client_note = $2, updated_at = NOW()
                    WHERE id = $1::uuid RETURNING *
                    """,
                    neg["id"],
                    (note or "Client declined offered times")[:2000],
                )
                neg = _row_to_dict(updated)
                coach_text = (
                    "Your client couldn't take those alternate times. "
                    "Approve another slot, mark busy, or propose new times."
                )
                client_text = (
                    "Okay — I told your coach those times don't work. "
                    "They can suggest others or we can try a different day."
                )
                return {
                    "ok": True,
                    "negotiation": neg,
                    "bridge_action": "none",
                    "coach_notify": {
                        "type": "session_negotiation_update",
                        "negotiation": neg,
                        "actions": ["approve", "busy", "alt"],
                        "nate_message": coach_text,
                        "audience": "coach",
                    },
                    "client_nate_text": client_text,
                    "coach_nate_text": coach_text,
                }

            # accept_alt
            alts = neg.get("alt_slots") or []
            chosen = chosen_start
            if not chosen and alts:
                first = alts[0]
                chosen = first.get("start") if isinstance(first, dict) else str(first)
            chosen_dt = _parse_dt(chosen)
            if not chosen_dt:
                return {"ok": False, "error": "missing_chosen_start"}
            # Validate chosen is in offered alts (fuzzy within 2 min)
            ok_choice = False
            chosen_end = None
            for slot in alts:
                if not isinstance(slot, dict):
                    continue
                sdt = _parse_dt(slot.get("start"))
                if sdt and abs((sdt - chosen_dt).total_seconds()) < 120:
                    ok_choice = True
                    chosen_end = _parse_dt(slot.get("end"))
                    break
            if not ok_choice and alts:
                return {"ok": False, "error": "slot_not_offered"}
            if not chosen_end:
                chosen_end = chosen_dt + timedelta(minutes=50)

            updated = await conn.fetchrow(
                """
                UPDATE session_negotiations
                SET status = 'approved', proposed_start = $2, proposed_end = $3,
                    client_note = $4, updated_at = NOW()
                WHERE id = $1::uuid RETURNING *
                """,
                neg["id"],
                chosen_dt,
                chosen_end,
                (note or "Client accepted alternate")[:2000],
            )
            neg = _row_to_dict(updated)
            client_text = f"Booked — you're set for {neg.get('proposed_start')}."
            coach_text = (
                f"Your client accepted {neg.get('proposed_start')}. "
                f"I've confirmed the session."
            )
            return {
                "ok": True,
                "negotiation": neg,
                "bridge_action": "reschedule_and_approve",
                "session_id": neg["session_id"],
                "new_start": neg.get("proposed_start"),
                "new_end": neg.get("proposed_end"),
                "coach_notify": {
                    "type": "session_negotiation_update",
                    "negotiation": neg,
                    "nate_message": coach_text,
                    "audience": "coach",
                },
                "client_nate_text": client_text,
                "coach_nate_text": coach_text,
            }
    except Exception as e:
        logger.warning("session_negotiation: client_respond failed: %s", e)
        return {"ok": False, "error": "db_error", "detail": str(e)[:200]}


def parse_coach_chat(text: str) -> Optional[str]:
    """Return approve|busy|alt or None."""
    if not text or len(text) > 400:
        return None
    if _APPROVE_RE.search(text):
        return "approve"
    if _BUSY_RE.search(text):
        return "busy"
    if _ALT_RE.search(text):
        return "alt"
    return None


def parse_client_chat(text: str) -> Optional[str]:
    """Return accept_alt|reject_alt or None when alts are pending."""
    if not text or len(text) > 400:
        return None
    if _REJECT_ALT_RE.search(text) and not _ACCEPT_ALT_RE.search(text):
        return "reject_alt"
    if _ACCEPT_ALT_RE.search(text):
        return "accept_alt"
    return None


def parse_chosen_slot_index(text: str) -> Optional[int]:
    """1-based index from 'first', '1', 'option 2', etc."""
    if not text:
        return None
    t = text.lower()
    if re.search(r"\b(first|1st|option\s*1)\b", t) or re.search(r"^\s*1\b", t):
        return 0
    if re.search(r"\b(second|2nd|option\s*2)\b", t) or re.search(r"^\s*2\b", t):
        return 1
    if re.search(r"\b(third|3rd|option\s*3)\b", t) or re.search(r"^\s*3\b", t):
        return 2
    m = re.search(r"\b(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2})", text)
    if m:
        return -1  # signal ISO present; caller matches
    return None


async def handle_coach_chat_turn(
    db_pool: Any, coach_id: str, text: str
) -> Dict[str, Any]:
    decision = parse_coach_chat(text)
    if not decision:
        return {"handled": False}
    open_neg = await get_open_for_user(db_pool, coach_id, as_role="COACH")
    if not open_neg:
        return {"handled": False}
    result = await coach_decide(
        db_pool,
        coach_id=coach_id,
        negotiation_id=open_neg.get("id"),
        decision=decision,
        note=text[:500],
    )
    if not result.get("ok"):
        return {"handled": False, "error": result.get("error")}
    result["handled"] = True
    return result


async def expire_stale_negotiations(
    db_pool: Any,
    *,
    max_age_hours: int = 24,
) -> int:
    """
    QUANTUM-CRYSTAL-ARCH: Mark negotiations older than max_age_hours as expired
    and align coaching_sessions still pending_approval → cancelled.
    Fanouts Redis so bridge JSON/WS catch up.
    """
    if not db_pool or not negotiation_enabled():
        return 0
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                UPDATE session_negotiations
                SET status = 'expired', updated_at = NOW()
                WHERE status = ANY($1::text[])
                  AND created_at < NOW() - make_interval(hours => $2::int)
                RETURNING id, session_id, client_id, coach_id
                """,
                list(ACTIVE_STATUSES),
                int(max_age_hours),
            )
            n = 0
            expired_payloads = []
            for row in rows:
                sid = row["session_id"]
                sess = None
                if sid:
                    await conn.execute(
                        """
                        UPDATE coaching_sessions
                        SET status = 'cancelled'
                        WHERE session_id = $1
                          AND LOWER(status) = 'pending_approval'
                        """,
                        sid,
                    )
                    sess = {
                        "session_id": sid,
                        "status": "cancelled",
                        "client_id": row["client_id"],
                        "coach_id": row["coach_id"],
                        "cancelled_via": "negotiation_expired",
                    }
                expired_payloads.append(
                    {
                        "client_id": row["client_id"] or "",
                        "coach_id": row["coach_id"] or "",
                        "session": sess,
                        "session_negotiation_update": {
                            "type": "session_negotiation_update",
                            "negotiation": {
                                "id": str(row["id"]),
                                "session_id": sid,
                                "status": "expired",
                                "client_id": row["client_id"],
                                "coach_id": row["coach_id"],
                            },
                            "ok": True,
                        },
                        "booking_status_update": (
                            {
                                "type": "booking_status_update",
                                "session": sess,
                                "status": "cancelled",
                            }
                            if sess
                            else None
                        ),
                    }
                )
                n += 1
            if n:
                logger.info("session_negotiation: expired %d stale negotiations", n)
        try:
            from app.services.session_negotiation_notify import publish_negotiation_fanout

            for payload in expired_payloads:
                await publish_negotiation_fanout(payload)
        except Exception as fe:
            logger.warning("session_negotiation: expire fanout failed: %s", fe)
        return n
    except Exception as e:
        logger.warning("session_negotiation: expire_stale failed: %s", e)
        return 0


async def handle_client_chat_turn(
    db_pool: Any, client_id: str, text: str
) -> Dict[str, Any]:
    open_neg = await get_open_for_user(db_pool, client_id, as_role="CLIENT")
    if not open_neg or open_neg.get("status") != "alt_proposed":
        return {"handled": False}
    decision = parse_client_chat(text)
    if not decision:
        return {"handled": False}
    chosen_start = None
    if decision == "accept_alt":
        alts = open_neg.get("alt_slots") or []
        idx = parse_chosen_slot_index(text)
        if idx == -1:
            m = re.search(r"\b(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?)", text)
            if m:
                chosen_start = m.group(1).replace(" ", "T")
        elif idx is not None and 0 <= idx < len(alts):
            slot = alts[idx]
            chosen_start = slot.get("start") if isinstance(slot, dict) else None
        elif alts:
            chosen_start = alts[0].get("start") if isinstance(alts[0], dict) else None
    result = await client_respond(
        db_pool,
        client_id=client_id,
        negotiation_id=open_neg.get("id"),
        decision=decision,
        chosen_start=chosen_start,
        note=text[:500],
    )
    if not result.get("ok"):
        return {"handled": False, "error": result.get("error")}
    result["handled"] = True
    return result
