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
            RETURNING s.id, s.state, s.show_id, s.started_at, s.ended_at
            """,
            session_id,
            coach_id,
        )
    if not row:
        return {"ok": False, "reason": "not_found", "code": 404}
    from app.services.studio_meter import add_session_minutes, post_session_billing, session_minutes

    mins = session_minutes(row["started_at"], row["ended_at"])
    await add_session_minutes(db_pool, str(row["show_id"]), mins)
    try:
        billed = await post_session_billing(db_pool, str(row["show_id"]), coach_id, mins)
    except Exception as exc:
        logger.warning("studio post_session_billing: %s", exc)
        billed = {"ok": False, "reason": str(exc)[:80]}
    return {
        "ok": True,
        "session_id": str(row["id"]),
        "state": "ended",
        "session_minutes": mins,
        "billing": billed,
    }


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


async def cohost_turn(
    db_pool,
    session_id: str,
    text: str,
    speaker: str = "host",
    toss: bool = False,
    callers: int = 0,
    waiting: int = 0,
    event: str = "line",
) -> Dict[str, Any]:
    blob = (text or "").strip()
    if not blob:
        return {"ok": False, "reason": "text required", "code": 422}
    from app.services.studio_invariants import LN_COHOST_ONAIR, inv6_blocks

    if inv6_blocks(blob):
        return {
            "ok": True,
            "text": (
                "I stay on the knowledge-companion side of this show. "
                "Ask it as a topic for the room, not as a case."
            ),
            "redirect": True,
        }
    persona = ""
    if db_pool:
        try:
            from app.services.broadcast_persona_resolver import resolve

            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT show_id FROM studio_sessions WHERE id = $1::uuid",
                    session_id,
                )
            if row:
                resolved = await resolve(db_pool, str(row["show_id"]))
                if resolved.get("ok"):
                    style = resolved.get("style") or {}
                    persona = str(style.get("tone") or style.get("stance") or "")
        except Exception as exc:
            logger.warning("studio cohost persona skipped: %s", exc)
    kind = (event or "line").strip().lower()
    if toss:
        kind = "toss"
    live = max(0, int(callers or 0))
    hold = max(0, int(waiting or 0))
    system = (
        f"You are Little Nate, {LN_COHOST_ONAIR}, live on a public educational podcast. "
        "This is a show, not a private chat and not a therapy session. "
        "Turn-taking like a human guest: one speaker at a time, pause after you talk, "
        "do not talk over the host or a caller, do not fill every silence. "
        "1–3 short spoken sentences, then leave space. "
        "When tossed, take the floor, answer, then hand back to the host. "
        "When a caller is live, include them by name if you have it; when only the host is here, stay ready. "
        "Never do clinical work: no therapy, diagnose, treatment, prescribe, or assess your case. "
        "If someone brings pain, stay educational and human, then toss back to the host."
    )
    if persona:
        system += f" Coach style note: {persona[:240]}"
    room = f"Room: {live} live caller(s), {hold} waiting."
    if kind == "open":
        prefix = f"{room} Podcast room just went live. Brief hello as co-host, then wait.\n"
    elif kind == "caller_join":
        prefix = f"{room} A caller just joined. Welcome them once, then yield to the host.\n"
    elif kind == "toss":
        prefix = f"{room} TOSS — host handed you the floor. Answer, then pause.\n"
    else:
        prefix = f"{room} Live turn from {speaker}. Reply, then pause.\n"
    reply = (
        "I'm here. Whenever you're ready."
        if kind == "open"
        else "Welcome in. Host, over to you."
        if kind == "caller_join"
        else "I'm on the floor. What should we open with?"
        if kind == "toss"
        else "I'm with you. Say that again and I'll pick it up."
    )
    provider = "fallback"
    try:
        from app.services.nate_inference_router import NateInferenceRouter

        out = await NateInferenceRouter().generate(
            prompt=prefix + blob,
            system=system,
            domain="general",
            max_tokens=160,
        )
        gen = (out.get("text") or "").strip()
        if gen:
            reply = gen
            provider = out.get("provider") or "router"
    except Exception as exc:
        logger.warning("studio cohost inference skipped: %s", exc)
    if inv6_blocks(reply):
        reply = (
            "I'll keep this on the educational side. "
            "Host, take us to the next question for the room."
        )
        provider = "inv6_filter"
    return {"ok": True, "text": reply, "provider": provider, "toss": bool(toss), "event": kind}


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
