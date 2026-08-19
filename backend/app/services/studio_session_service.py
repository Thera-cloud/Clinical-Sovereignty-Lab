"""Studio sessions — show_mode forced true. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import logging
import secrets
from typing import Any, Dict

from app.services.studio_invariants import LN_COHOST_LABEL, guest_video_allowed

logger = logging.getLogger("studio_session")


async def create_session(db_pool, show_id: str, coach_id: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    admitted = await _preflight()
    if not admitted.get("ok"):
        return admitted
    async with db_pool.acquire() as conn:
        show = await conn.fetchrow(
            "SELECT id FROM studio_shows WHERE id = $1::uuid AND coach_id = $2",
            show_id,
            coach_id,
        )
        if not show:
            return {"ok": False, "reason": "not_found", "code": 404}
        sess = await conn.fetchrow(
            """
            INSERT INTO studio_sessions (show_id, show_mode, state, started_at)
            VALUES ($1::uuid, TRUE, 'active', NOW())
            RETURNING id, show_id, show_mode, state, started_at
            """,
            show_id,
        )
        host = await conn.fetchrow(
            """
            INSERT INTO session_legs (session_id, role, label, state)
            VALUES ($1::uuid, 'host', $2, 'live')
            RETURNING id, role, video_track_key
            """,
            sess["id"],
            "Host",
        )
        nate = await conn.fetchrow(
            """
            INSERT INTO session_legs (session_id, role, label, state)
            VALUES ($1::uuid, 'cohost_ai', $2, 'live')
            RETURNING id, role, video_track_key
            """,
            sess["id"],
            LN_COHOST_LABEL,
        )
    token = secrets.token_urlsafe(24)
    return {
        "ok": True,
        "session": {
            "id": str(sess["id"]),
            "show_id": str(sess["show_id"]),
            "show_mode": True,
            "state": sess["state"],
            "join_token": token,
            "legs": [
                {"id": str(host["id"]), "role": "host"},
                {"id": str(nate["id"]), "role": "cohost_ai", "label": LN_COHOST_LABEL},
            ],
        },
        "preflight": admitted,
    }


async def end_session(db_pool, session_id: str, coach_id: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE studio_sessions s
            SET state = 'ended', ended_at = NOW()
            FROM studio_shows sh
            WHERE s.id = $1::uuid AND s.show_id = sh.id AND sh.coach_id = $2
              AND s.state <> 'ended'
            RETURNING s.id, s.state
            """,
            session_id,
            coach_id,
        )
    if not row:
        return {"ok": False, "reason": "not_found", "code": 404}
    return {"ok": True, "session_id": str(row["id"]), "state": "ended"}


async def append_utterance(
    db_pool, session_id: str, coach_id: str, leg_id: str, text: str
) -> Dict[str, Any]:
    blob = (text or "").strip()
    if not blob:
        return {"ok": False, "reason": "text required", "code": 422}
    from app.services.studio_invariants import inv6_blocks

    if inv6_blocks(blob):
        return {"ok": False, "reason": "INV-6 blocked", "code": 422}
    if not db_pool:
        return {"ok": True, "dry": True, "text": blob}
    import json

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE session_legs l
            SET utterances_json = COALESCE(l.utterances_json, '[]'::jsonb) || $3::jsonb
            FROM studio_sessions s
            JOIN studio_shows sh ON sh.id = s.show_id
            WHERE l.id = $2::uuid AND l.session_id = s.id
              AND s.id = $1::uuid AND sh.coach_id = $4
            RETURNING l.id
            """,
            session_id,
            leg_id,
            json.dumps([{"text": blob}]),
            coach_id,
        )
    if not row:
        return {"ok": False, "reason": "not_found", "code": 404}
    return {"ok": True, "leg_id": str(row["id"])}


def reject_guest_video(role: str, video_track_key: str) -> Dict[str, Any]:
    if guest_video_allowed(role, video_track_key or None):
        return {"ok": True}
    return {"ok": False, "reason": "INV-2 guest video forbidden", "code": 422}


async def _preflight() -> Dict[str, Any]:
    try:
        from app.services.voice_admission import VoiceAdmission

        adm = VoiceAdmission()
        if hasattr(adm, "can_admit"):
            ok = await adm.can_admit("studio")
            if ok is False:
                return {"ok": False, "reason": "capacity", "code": 429}
    except Exception as exc:
        logger.warning("studio preflight admission skipped: %s", exc)
    return {"ok": True, "capacity": "reserved_or_open"}
