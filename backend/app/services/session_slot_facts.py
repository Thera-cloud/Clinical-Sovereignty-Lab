"""User-scoped session slot facts. Never write these as global crystals."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("nate.session_slot_facts")


def _pi_suffix(pi: str) -> str:
    raw = str(pi or "").strip()
    if len(raw) < 8:
        return raw
    return raw[-8:]


def fact_text(row: Dict[str, Any], event: str) -> str:
    sid = str(row.get("session_id") or "")
    when = str(row.get("scheduled_start") or row.get("scheduled_at") or "")
    cents = row.get("price_cents") or 0
    zoom = str(row.get("zoom_meeting_id") or "")
    pay = str(row.get("payment_status") or "")
    return (
        f"Operational session fact ({event}). "
        f"session_id={sid} slot={when} payment={pay} amount_cents={cents} "
        f"pi_suffix={_pi_suffix(row.get('stripe_payment_intent_id') or '')} "
        f"zoom_id={zoom}. Not clinical content."
    )


async def record_session_slot_fact(
    db_pool,
    row: Dict[str, Any],
    *,
    event: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    if not db_pool:
        return
    sid = str(row.get("session_id") or "")
    client_id = str(row.get("client_id") or "")
    coach_id = str(row.get("coach_id") or "")
    content = fact_text(row, event)
    payload = {
        "session_id": sid,
        "event": event,
        "payment_status": row.get("payment_status"),
        "price_cents": row.get("price_cents"),
        "pi_suffix": _pi_suffix(row.get("stripe_payment_intent_id") or ""),
        "zoom_meeting_id": row.get("zoom_meeting_id"),
        "scheduled_start": str(row.get("scheduled_start") or row.get("scheduled_at") or ""),
        "extra": extra or {},
    }
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO skyeye_activity (type, platform, content)
                VALUES ('session_slot_fact', $1, $2)
                """,
                (client_id or coach_id or "session")[:80],
                json.dumps(payload)[:8000],
            )
    except Exception as e:
        logger.warning("session_slot_facts: skyeye insert failed: %s", e)
    for hw in (client_id, coach_id):
        if not hw:
            continue
        try:
            from app.websocket.crystal_recall_bridge import crystallize_from_conversation
            await crystallize_from_conversation(
                db_pool,
                hw,
                content,
                "Session schedule fact recorded.",
                user_name="",
                domain="operational",
                min_score=1,
                origin_surface="session_ops",
            )
        except Exception as e:
            logger.warning("session_slot_facts: crystallize skipped %s: %s", hw, e)
