"""Studio show CRUD + host number store. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from app.services.broadcast_persona_resolver import validate_show_copy, validate_vertical
from app.services.studio_invariants import LIVE_TIER_CLEAN_EPISODES, filter_style_layer

logger = logging.getLogger("studio_show")


async def create_show(
    db_pool,
    coach_id: str,
    *,
    name: str,
    vertical: str,
    description: str = "",
    host_number: str = "",
) -> Dict[str, Any]:
    err = validate_show_copy(name, description)
    if err:
        return {"ok": False, "reason": err, "code": 422}
    err = validate_vertical(vertical)
    if err:
        return {"ok": False, "reason": err, "code": 422}
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO studio_shows (coach_id, name, description, vertical, host_number)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, coach_id, name, vertical, host_number, host_verified,
                      persona_style_layer, tier, live_unlocked, created_at
            """,
            coach_id,
            name.strip(),
            (description or "").strip() or None,
            vertical,
            (host_number or "").strip() or None,
        )
    return {"ok": True, "show": _show_row(row)}


async def get_show(db_pool, show_id: str, coach_id: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT s.*,
              (SELECT COUNT(*) FROM studio_episodes e
                WHERE e.show_id = s.id AND e.state = 'published') AS published_count,
              (SELECT COUNT(*) FROM studio_episodes e
                WHERE e.show_id = s.id AND e.state = 'published'
                  AND NOT EXISTS (
                    SELECT 1 FROM studio_compliance_flags f
                    WHERE f.episode_id = e.id AND f.severity = 'high'
                      AND f.status = 'overridden'
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM studio_compliance_flags f
                    WHERE f.episode_id = e.id AND f.status = 'open'
                  )
              ) AS clean_published
            FROM studio_shows s
            WHERE s.id = $1::uuid AND s.coach_id = $2
            """,
            show_id,
            coach_id,
        )
    if not row:
        return {"ok": False, "reason": "not_found", "code": 404}
    show = _show_row(row)
    clean = int(row["clean_published"] or 0)
    show["published_count"] = int(row["published_count"] or 0)
    show["clean_published"] = clean
    show["live_tier_needed"] = LIVE_TIER_CLEAN_EPISODES
    show["live_unlocked"] = clean >= LIVE_TIER_CLEAN_EPISODES
    return {"ok": True, "show": show}


async def ensure_coachn_show(db_pool) -> None:
    if not db_pool:
        return
    async with db_pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM studio_shows WHERE coach_id = $1 LIMIT 1",
            "COACH_COACHN_ID",
        )
        if exists:
            return
        await conn.execute(
            """
            INSERT INTO studio_shows (coach_id, name, description, vertical)
            VALUES (
              'COACH_COACHN_ID',
              'CoachN Studio',
              'Educational show with an AI co-host and knowledge companion.',
              'life_coaching'
            )
            """
        )


async def list_shows(db_pool, coach_id: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "shows": [], "code": 503}
    if coach_id == "COACH_COACHN_ID":
        await ensure_coachn_show(db_pool)
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.id, s.coach_id, s.name, s.vertical, s.host_number, s.host_verified,
                   s.persona_style_layer, s.tier, s.live_unlocked, s.created_at,
                   (SELECT COUNT(*) FROM studio_episodes e
                     WHERE e.show_id = s.id AND e.state = 'published'
                       AND NOT EXISTS (
                         SELECT 1 FROM studio_compliance_flags f
                         WHERE f.episode_id = e.id AND f.status = 'open'
                       )
                       AND NOT EXISTS (
                         SELECT 1 FROM studio_compliance_flags f
                         WHERE f.episode_id = e.id AND f.severity = 'high'
                           AND f.status = 'overridden'
                       )
                   ) AS clean_published
            FROM studio_shows s WHERE s.coach_id = $1
            ORDER BY s.created_at DESC
            """,
            coach_id,
        )
    shows = []
    for r in rows:
        item = _show_row(r)
        item["clean_published"] = int(r["clean_published"] or 0)
        shows.append(item)
    return {"ok": True, "shows": shows}


async def update_style(
    db_pool, show_id: str, coach_id: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    cleaned, rejected = filter_style_layer(payload or {})
    if rejected:
        return {
            "ok": False,
            "reason": "INV-5 locked keys rejected",
            "rejected": rejected,
            "code": 422,
        }
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE studio_shows
            SET persona_style_layer = $3::jsonb, updated_at = NOW()
            WHERE id = $1::uuid AND coach_id = $2
            RETURNING id, persona_style_layer
            """,
            show_id,
            coach_id,
            json.dumps(cleaned),
        )
    if not row:
        return {"ok": False, "reason": "not_found", "code": 404}
    return {"ok": True, "style": cleaned}


async def store_host_number(
    db_pool, show_id: str, coach_id: str, host_number: str
) -> Dict[str, Any]:
    number = (host_number or "").strip()
    if len(number) < 7:
        return {"ok": False, "reason": "host_number required", "code": 422}
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE studio_shows
            SET host_number = $3, host_verified = FALSE, updated_at = NOW()
            WHERE id = $1::uuid AND coach_id = $2
            RETURNING id, host_number, host_verified
            """,
            show_id,
            coach_id,
            number,
        )
    if not row:
        return {"ok": False, "reason": "not_found", "code": 404}
    return {
        "ok": True,
        "status": "queued",
        "host_number": row["host_number"],
        "host_verified": False,
        "dial_out": False,
        "note": "S1 stores the number. Twilio keypress verify ships with S2 DID provision.",
    }


def _show_row(row) -> Dict[str, Any]:
    style = row.get("persona_style_layer") if hasattr(row, "get") else None
    if isinstance(style, str):
        try:
            style = json.loads(style)
        except Exception:
            style = {}
    created = row.get("created_at")
    return {
        "id": str(row["id"]),
        "coach_id": row.get("coach_id"),
        "name": row.get("name"),
        "description": row.get("description"),
        "vertical": row.get("vertical"),
        "host_number": row.get("host_number"),
        "host_verified": bool(row.get("host_verified")),
        "persona_style_layer": style if isinstance(style, dict) else {},
        "tier": row.get("tier") or "tier1",
        "live_unlocked": bool(row.get("live_unlocked")),
        "created_at": created.isoformat() if created is not None and hasattr(created, "isoformat") else created,
    }
