"""S5 Tier-2 live — 1 clean episode gate, dump, RTMP. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

from typing import Any, Dict

from app.services.studio_invariants import LIVE_TIER_CLEAN_EPISODES, live_tier_unlocked

DELAY_S = 45


def dump_allowed(clean_published: int) -> bool:
    return live_tier_unlocked(clean_published)


def delay_status(live_unlocked: bool) -> Dict[str, Any]:
    return {
        "ok": True,
        "delay_s": DELAY_S,
        "live_unlocked": bool(live_unlocked),
        "dump": "armed" if live_unlocked else "locked",
    }


async def booth_status(db_pool, session_id: str, coach_id: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT s.id, sh.id AS show_id, sh.rtmp_url,
              (SELECT COUNT(*) FROM studio_episodes e
                WHERE e.show_id = sh.id AND e.state = 'published'
                  AND NOT EXISTS (
                    SELECT 1 FROM studio_compliance_flags f
                    WHERE f.episode_id = e.id AND f.status = 'open'
                  )
              ) AS clean_published
            FROM studio_sessions s
            JOIN studio_shows sh ON sh.id = s.show_id
            WHERE s.id = $1::uuid AND sh.coach_id = $2
            """,
            session_id,
            coach_id,
        )
    if not row:
        return {"ok": False, "reason": "not_found", "code": 404}
    unlocked = dump_allowed(int(row["clean_published"] or 0))
    rtmp = (row.get("rtmp_url") or "").strip()
    out = delay_status(unlocked)
    out["session_id"] = session_id
    out["show_id"] = str(row["show_id"])
    out["rtmp_url_set"] = bool(rtmp)
    out["rtmp"] = "set" if rtmp else "pending"
    return out


async def store_rtmp(db_pool, show_id: str, coach_id: str, rtmp_url: str) -> Dict[str, Any]:
    url = (rtmp_url or "").strip()
    if not url.startswith("rtmp"):
        return {"ok": False, "reason": "rtmp url required", "code": 422}
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE studio_shows SET rtmp_url = $3, updated_at = NOW()
            WHERE id = $1::uuid AND coach_id = $2
            RETURNING id
            """,
            show_id,
            coach_id,
            url,
        )
    if not row:
        return {"ok": False, "reason": "not_found", "code": 404}
    return {"ok": True, "rtmp_set": True}


async def dump_session(db_pool, session_id: str, coach_id: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT s.id, sh.coach_id, sh.id AS show_id,
              (SELECT COUNT(*) FROM studio_episodes e
                WHERE e.show_id = sh.id AND e.state = 'published'
                  AND NOT EXISTS (
                    SELECT 1 FROM studio_compliance_flags f
                    WHERE f.episode_id = e.id AND f.status = 'open'
                  )
              ) AS clean_published
            FROM studio_sessions s
            JOIN studio_shows sh ON sh.id = s.show_id
            WHERE s.id = $1::uuid AND sh.coach_id = $2
            """,
            session_id,
            coach_id,
        )
    if not row:
        return {"ok": False, "reason": "not_found", "code": 404}
    if not dump_allowed(int(row["clean_published"] or 0)):
        return {"ok": False, "reason": "tier2_locked", "code": 409}
    span_id = None
    try:
        async with db_pool.acquire() as conn:
            rec = await conn.fetchrow(
                """
                INSERT INTO studio_dump_spans (session_id, show_id, delay_s, irreversible)
                VALUES ($1::uuid, $2::uuid, $3, TRUE)
                RETURNING id
                """,
                session_id,
                str(row["show_id"]),
                DELAY_S,
            )
            span_id = str(rec["id"]) if rec else None
    except Exception:
        span_id = None
    return {
        "ok": True,
        "dumped": True,
        "delay_s": DELAY_S,
        "irreversible": True,
        "gate": LIVE_TIER_CLEAN_EPISODES,
        "span_id": span_id,
    }
