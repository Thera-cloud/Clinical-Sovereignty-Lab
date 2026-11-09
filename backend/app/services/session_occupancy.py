"""PG occupancy lock for live coaching slots.

JSON calendars are not occupancy. A paid or pending row in coaching_sessions
blocks the coach, the client, and the family for that tstzrange.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.session_occupancy")

BLOCKING_STATUSES = ("scheduled", "active", "pending_approval")
PAID_STATUSES = ("paid", "waived", "zero")

OVERLAP_SQL = """
SELECT cs.session_id, cs.coach_id, cs.client_id, cs.family_id, cs.status,
       cs.payment_status, cs.stripe_payment_intent_id, cs.zoom_link,
       cs.zoom_meeting_id, cs.price_cents, cs.client_name,
       COALESCE(cs.scheduled_start, cs.scheduled_at) AS scheduled_start,
       COALESCE(
           cs.scheduled_end,
           COALESCE(cs.scheduled_start, cs.scheduled_at) + INTERVAL '50 minutes'
       ) AS scheduled_end
  FROM coaching_sessions cs
 WHERE LOWER(COALESCE(cs.status, '')) = ANY($1::text[])
   AND COALESCE(cs.scheduled_start, cs.scheduled_at) IS NOT NULL
   AND tstzrange(
         COALESCE(cs.scheduled_start, cs.scheduled_at),
         COALESCE(
             cs.scheduled_end,
             COALESCE(cs.scheduled_start, cs.scheduled_at) + INTERVAL '50 minutes'
         ),
         '[)'
       ) && tstzrange($2::timestamptz, $3::timestamptz, '[)')
   AND (
         cs.coach_id = $4
      OR ($5 <> '' AND cs.client_id = $5)
      OR ($6 <> '' AND COALESCE(cs.family_id, '') = $6)
   )
   AND ($7 = '' OR cs.session_id <> $7)
 LIMIT 25
"""

OCCUPANCY_PAIR_COUNT_SQL = """
SELECT COUNT(*) FROM coaching_sessions a
  JOIN coaching_sessions b
    ON a.session_id < b.session_id
   AND a.coach_id = b.coach_id
   AND LOWER(COALESCE(a.status, '')) = ANY($1::text[])
   AND LOWER(COALESCE(b.status, '')) = ANY($1::text[])
   AND tstzrange(
         COALESCE(a.scheduled_start, a.scheduled_at),
         COALESCE(a.scheduled_end, COALESCE(a.scheduled_start, a.scheduled_at)
                  + INTERVAL '50 minutes'), '[)'
       ) && tstzrange(
         COALESCE(b.scheduled_start, b.scheduled_at),
         COALESCE(b.scheduled_end, COALESCE(b.scheduled_start, b.scheduled_at)
                  + INTERVAL '50 minutes'), '[)'
       )
"""


def as_utc(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raw = str(value).strip().replace("Z", "+00:00")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def ranges_overlap(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    return a0 < b1 and a1 > b0


def _end_or_default(start: datetime, end: Optional[datetime]) -> datetime:
    if end and end > start:
        return end
    return start + timedelta(minutes=50)


async def fetch_blocking_overlaps(
    conn,
    *,
    coach_id: str,
    start: Any,
    end: Any = None,
    client_id: str = "",
    family_id: str = "",
    exclude_session_id: str = "",
) -> List[Dict[str, Any]]:
    st = as_utc(start)
    if not st or not conn:
        return []
    en = _end_or_default(st, as_utc(end))
    rows = await conn.fetch(
        OVERLAP_SQL,
        list(BLOCKING_STATUSES),
        st,
        en,
        str(coach_id or ""),
        str(client_id or ""),
        str(family_id or ""),
        str(exclude_session_id or ""),
    )
    return [dict(r) for r in rows]


async def occupancy_blocks_booking(
    db_pool,
    *,
    coach_id: str,
    start: Any,
    end: Any = None,
    client_id: str = "",
    family_id: str = "",
    exclude_session_id: str = "",
) -> Optional[str]:
    """Return a conflict message when the slot is taken, else None."""
    if not db_pool:
        return None
    try:
        async with db_pool.acquire() as conn:
            rows = await fetch_blocking_overlaps(
                conn,
                coach_id=coach_id,
                start=start,
                end=end,
                client_id=client_id,
                family_id=family_id,
                exclude_session_id=exclude_session_id,
            )
    except Exception as e:
        logger.warning("session_occupancy: overlap query failed: %s", e)
        return None
    if not rows:
        return None
    sid = rows[0].get("session_id") or ""
    pay = str(rows[0].get("payment_status") or "").lower()
    if pay in PAID_STATUSES:
        return f"Time slot conflict (paid session {sid})"
    return "Time slot conflict"


async def find_paid_slot_credit(
    conn,
    *,
    coach_id: str,
    start: Any,
    end: Any = None,
    client_id: str = "",
    family_id: str = "",
    exclude_session_id: str = "",
) -> Optional[Dict[str, Any]]:
    """Succeeded collection already sits on an overlapping live row."""
    rows = await fetch_blocking_overlaps(
        conn,
        coach_id=coach_id,
        start=start,
        end=end,
        client_id=client_id,
        family_id=family_id,
        exclude_session_id=exclude_session_id,
    )
    for row in rows:
        pay = str(row.get("payment_status") or "").lower()
        pi = str(row.get("stripe_payment_intent_id") or "").strip()
        if pay in PAID_STATUSES and (pi or pay in ("waived", "zero")):
            return row
    return None
