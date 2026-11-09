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
OCCUPANCY_UNAVAILABLE = "Time slot conflict (occupancy unavailable)"

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
      OR (CARDINALITY($5::text[]) > 0 AND cs.client_id = ANY($5::text[]))
      OR ($6 <> '' AND COALESCE(cs.family_id, '') = $6)
   )
   AND ($7 = '' OR cs.session_id <> $7)
 LIMIT 25
"""

SIBLING_CLIENT_SQL = """
SELECT DISTINCT u2.hardware_id::text AS hardware_id
  FROM users u1
  JOIN users u2
    ON u2.role = 'CLIENT'
   AND u2.hardware_id IS DISTINCT FROM u1.hardware_id
 WHERE u1.role = 'CLIENT'
   AND (
        u1.hardware_id = $1
     OR u1.id::text = $1
     OR LOWER(u1.username) = LOWER($1)
   )
   AND (
        (
          LOWER(TRIM(COALESCE(u1.profile_data->>'name', ''))) <> ''
          AND LOWER(TRIM(u1.profile_data->>'name'))
            = LOWER(TRIM(COALESCE(u2.profile_data->>'name', '')))
        )
     OR (
          NULLIF(COALESCE(u1.stripe_customer_id,
                          u1.profile_data->>'stripe_customer_id'), '') IS NOT NULL
          AND COALESCE(u1.stripe_customer_id, u1.profile_data->>'stripe_customer_id', '')
            = COALESCE(u2.stripe_customer_id, u2.profile_data->>'stripe_customer_id', '')
        )
     OR (
          NULLIF(COALESCE(u1.family_id::text, u1.profile_data->>'family_id'), '')
            IS NOT NULL
          AND COALESCE(u1.family_id::text, u1.profile_data->>'family_id', '')
            = COALESCE(u2.family_id::text, u2.profile_data->>'family_id', '')
        )
   )
 LIMIT 12
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


async def expand_client_ids(conn, client_id: str) -> List[str]:
    """Same person, second CLIENT row (hardware_id). Does not merge accounts."""
    cid = str(client_id or "").strip()
    ids = [cid] if cid else []
    if not conn or not cid:
        return ids
    try:
        rows = await conn.fetch(SIBLING_CLIENT_SQL, cid)
    except Exception as e:
        logger.warning("session_occupancy: sibling lookup failed: %s", e)
        return ids
    for row in rows:
        hid = str(row.get("hardware_id") or "").strip()
        if hid and hid not in ids:
            ids.append(hid)
    return ids


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
    client_ids = await expand_client_ids(conn, client_id)
    rows = await conn.fetch(
        OVERLAP_SQL,
        list(BLOCKING_STATUSES),
        st,
        en,
        str(coach_id or ""),
        client_ids,
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
        return OCCUPANCY_UNAVAILABLE
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
        return OCCUPANCY_UNAVAILABLE
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
