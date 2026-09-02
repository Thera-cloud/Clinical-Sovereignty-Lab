"""Studio sessions — show_mode forced true. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Any, Dict

from app.services.studio_invariants import LN_COHOST_LABEL, guest_video_allowed

logger = logging.getLogger("studio_session")

_THREAD: Dict[str, list] = {}
_THREAD_MAX = 40


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
    remember_line(session_id, "HOST", blob)
    return {"ok": True, "leg_id": str(row["id"])}


def remember_line(session_id: str, speaker: str, text: str) -> None:
    line = f"{(speaker or 'HOST').strip()}: {(text or '').strip()}"
    sid = (session_id or "").strip()
    if not sid or len(line) < 8:
        return
    buf = _THREAD.setdefault(sid, [])
    if buf and buf[-1] == line[:500]:
        return
    buf.append(line[:500])
    _THREAD[sid] = buf[-_THREAD_MAX:]


def thread_text(session_id: str) -> str:
    return "\n".join(_THREAD.get(session_id or "", []) or [])


def _last_nate_line(session_id: str) -> str:
    for line in reversed(_THREAD.get(session_id or "", []) or []):
        if line.startswith("NATE: "):
            return line[6:]
    return ""


async def _hydrate_thread(db_pool, session_id: str) -> None:
    if not db_pool or thread_text(session_id):
        return
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT role, utterances_json
                FROM session_legs
                WHERE session_id = $1::uuid
                """,
                session_id,
            )
        for row in rows:
            role = "NATE" if (row["role"] or "") == "cohost_ai" else "HOST"
            raw = row["utterances_json"] or []
            if isinstance(raw, str):
                import json

                raw = json.loads(raw)
            for item in raw[-_THREAD_MAX:]:
                if isinstance(item, dict):
                    remember_line(session_id, str(item.get("t") or role), str(item.get("text") or ""))
                elif item:
                    remember_line(session_id, role, str(item))
    except Exception as exc:
        logger.warning("studio thread hydrate skipped: %s", exc)


async def _persist_line(db_pool, session_id: str, role: str, speaker: str, text: str) -> None:
    if not db_pool or not session_id or not (text or "").strip():
        return
    import json

    blob = json.dumps([{"t": speaker, "text": (text or "").strip()[:500]}])
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE session_legs
                SET utterances_json = COALESCE(utterances_json, '[]'::jsonb) || $2::jsonb
                WHERE session_id = $1::uuid AND role = $3
                """,
                session_id,
                blob,
                role,
            )
    except Exception as exc:
        logger.warning("studio thread persist skipped: %s", exc)


async def cohost_turn(
    db_pool,
    session_id: str,
    text: str,
    speaker: str = "host",
    toss: bool = False,
    callers: int = 0,
    waiting: int = 0,
    event: str = "line",
    realm: str = "",
    realm_blurb: str = "",
    realm_shift: bool = False,
    share_kind: str = "",
    share_note: str = "",
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
    kind = (event or "line").strip().lower()
    if toss:
        kind = "toss"
    from app.services.studio_listen_hold import prime_clear, prime_store, prime_take
    from app.services.studio_cohost_share import (
        merge_share_note,
        note_has_seen_content,
        share_seen,
    )

    sid = str(session_id)
    share_k = (share_kind or "").strip()[:40]
    share_n = (share_note or "").strip()[:800]
    seen = share_seen(sid)
    share_n = merge_share_note(share_n, seen.get("note") or "")
    jpeg = seen.get("jpeg") or ""
    needs_eyes = share_k.lower() in {"screen", "image", "file", "window"}
    can_see = note_has_seen_content(share_n) or bool(jpeg)
    if kind in ("toss", "open", "caller_join"):
        prime_clear(sid)
    # Screen shares change every second. A primed line without the still is fiction.
    cached_reply = None if kind == "prime" or needs_eyes else prime_take(sid, blob)
    if cached_reply:
        remember_line(session_id, speaker or "HOST", blob)
        remember_line(session_id, "NATE", cached_reply)
        await _persist_line(db_pool, session_id, "host", speaker or "HOST", blob)
        await _persist_line(db_pool, session_id, "cohost_ai", "NATE", cached_reply)
        return {
            "ok": True,
            "text": cached_reply,
            "provider": "prime",
            "toss": bool(toss),
            "event": kind,
            "primed": True,
        }
    live = max(0, int(callers or 0))
    hold = max(0, int(waiting or 0))
    await _hydrate_thread(db_pool, session_id)
    from app.services.studio_product_brief import (
        PRODUCT_BRIEF,
        SHOW_VOICE,
        asks_app_howto,
        drop_trailing_question,
        ends_with_question,
        sanitize_onair,
    )

    howto = asks_app_howto(blob)
    system = (
        f"You are Little Nate, {LN_COHOST_ONAIR}, live with Big Nate the host. "
        "Radio co-host energy, not therapy. "
        "Track THIS_SHOW moment to moment and answer the latest line. "
        "Finish the thought — do not stop mid-idea. "
        "4–8 spoken sentences when the topic is live; shorter only for a one-liner toss. "
        "Land on a take more often than a question. "
        "No mirroring their words back, no interviewing.\n\n"
        + SHOW_VOICE
    )
    if howto:
        system += (
            "\n\nThis turn asked how the app works. Use the product notes. "
            "Then return to conversation.\n"
            + PRODUCT_BRIEF
        )
    # The backdrop behind Nate rotates through Thera-world realms during the
    # show. He always knows where he is standing; he only says it out loud when
    # the moment actually wants it.
    realm_name = (realm or "").strip()
    if realm_name:
        where = f"You are broadcasting from {realm_name}"
        if (realm_blurb or "").strip():
            where += f" — {realm_blurb.strip()}"
        system += (
            f"\n\nWHERE YOU ARE: {where}. "
            "The realm behind you shifts on its own during the show. "
            "Know it, let it color your mood, and only name it out loud when it "
            "genuinely fits the moment. Never announce it as a status update."
        )
    room = f"Room: {live} live caller(s), {hold} waiting."
    if realm_name:
        room += f" Realm: {realm_name}."
        if realm_shift:
            room += " The realm just shifted in behind you this second."
    if share_k:
        room += f" On screen: {share_k}."
        if can_see:
            system += (
                f"\n\nON SCREEN ({share_k}): {share_n or 'current screenshot attached'}\n"
                "A still of the share is attached. Quote only text that is actually on screen. "
                "If a label is blurry, say you cannot read that part. "
                "Do not invent titles, quotes, code, or layout. "
                "You look things up and bring stings only when the host asks — "
                "never when a caller asks.\n"
            )
        else:
            system += (
                "\n\nON SCREEN: a share is up, but you have no read on the page yet. "
                "Say you cannot see the page yet. Do not invent titles, quotes, code, or layout. "
                "You look things up and bring stings only when the host asks — "
                "never when a caller asks.\n"
            )
    prior = thread_text(session_id)
    prior_block = f"THIS_SHOW so far:\n{prior}\n\n" if prior else ""
    if kind == "open":
        prefix = (
            f"{room} Show just went live. Warm hello, then a small joke or take of your own. "
            "Land it on a statement. No app pitch.\n"
        )
    elif kind == "caller_join":
        prefix = f"{room} A caller just joined. Welcome them like a person, once. No product pitch.\n"
    elif kind == "toss":
        prefix = (
            f"{room} TOSS — host handed you the floor. Follow THIS_SHOW. "
            "React, then say what you actually think. Do not default to the app.\n"
        )
    elif kind == "caption" or (
        kind == "prime"
        and ("caller:" in blob.lower() or blob.lower().lstrip().startswith("host:"))
    ):
        prefix = (
            f"{room} Live captions. If this is aimed at you, finish a take in 4–8 sentences. "
            "If they are mid-thought, one short reaction is fine. Never trail off mid-idea. "
            "No product pitch unless they asked.\n"
        )
    else:
        prefix = (
            f"{room} Live turn from {speaker}. Follow their topic. "
            "React and add your take. Do not pitch unless they asked.\n"
        )
    if howto:
        prefix += (
            "They asked how Little Nate / the app works. One clear breath for clients and coaches. "
            "Land on a statement.\n"
        )
    prefix = prior_block + prefix
    reply = (
        "Hey — Little Nate with you. Let's see where this one goes."
        if kind == "open"
        else "Hey, welcome in."
        if kind == "caller_join"
        else "Alright, I'm in."
        if kind == "toss"
        else "Yeah, man — that tracks."
    )
    provider = "fallback"
    try:
        from app.services.nate_inference_router import NateInferenceRouter

        out = await NateInferenceRouter().generate(
            prompt=prefix + blob,
            system=system,
            domain="culture",
            max_tokens=400 if howto else 280,
            images=[jpeg] if jpeg else None,
        )
        gen = (out.get("text") or "").strip()
        if gen:
            reply = gen
            provider = out.get("provider") or "router"
    except Exception as exc:
        logger.warning("studio cohost inference skipped: %s", exc)
    if inv6_blocks(reply):
        reply = "I'll keep this on the educational side and stay with the room."
        provider = "inv6_filter"
    cleaned = sanitize_onair(reply)
    if cleaned != reply:
        reply = cleaned
        provider = "onair_guard"
    # A question is fine. Two Nate turns in a row ending in one is an interview.
    if ends_with_question(reply) and ends_with_question(_last_nate_line(session_id)):
        trimmed = drop_trailing_question(reply)
        if trimmed:
            reply = trimmed
            provider = "onair_guard"
    if not (reply or "").strip():
        reply = "Yeah, man — that tracks."
    if kind == "prime":
        prime_store(sid, blob, reply)
        return {
            "ok": True,
            "text": reply,
            "provider": provider,
            "toss": False,
            "event": "prime",
            "primed": True,
        }
    remember_line(session_id, speaker or "HOST", blob)
    remember_line(session_id, "NATE", reply)
    await _persist_line(db_pool, session_id, "host", speaker or "HOST", blob)
    await _persist_line(db_pool, session_id, "cohost_ai", "NATE", reply)
    return {"ok": True, "text": reply, "provider": provider, "toss": bool(toss), "event": kind}


async def synthesize_cohost_line(text: str, voice_router=None) -> bytes:
    line = (text or "").strip()
    if not line:
        return b""
    try:
        from app.services.studio_phone_voice import synthesize_studio_voice

        audio = await synthesize_studio_voice(line)
        if audio:
            return audio
    except Exception as exc:
        logger.warning("studio speak phone voice skipped: %s", exc)
    if voice_router is None:
        return b""
    try:
        audio = await asyncio.wait_for(
            voice_router.process_text_to_speech(
                line, tts_provider="azure_premium", voice="onyx"
            ),
            timeout=24.0,
        )
        if audio:
            return audio
    except Exception as exc:
        logger.warning("studio speak azure skipped: %s", exc)
    return b""


def caption_should_ask(blob: str) -> bool:
    text = (blob or "").strip()
    if len(text) < 12:
        return False
    low = text.lower()
    if "caller:" in low:
        return True
    if "?" in text:
        return True
    if "nate" in low or "co-host" in low or "cohost" in low:
        return True
    # Drop STT crumbs ("late.") — wait for a real host/caller utterance.
    if len(text) < 24:
        return False
    return len(text) >= 80


async def ingest_live_caption(
    audio: bytes,
    speaker: str = "host",
    identity: str = "",
    content_type: str = "audio/webm",
    session_id: str = "",
    db_pool=None,
) -> Dict[str, Any]:
    role = "caller" if (speaker or "").strip().lower() == "caller" else "host"
    ctype = (content_type or "audio/webm").split(";")[0].strip() or "audio/webm"
    if not audio or len(audio) < 400:
        return {"ok": False, "reason": "no_speech", "speaker": role}
    text = ""
    try:
        from app.services.whisper_stt import transcribe

        text = (await transcribe(audio, content_type=ctype, fail_fast=True)) or ""
    except Exception as exc:
        logger.warning("studio caption stt skipped: %s", exc)
    text = text.strip()
    if not text:
        return {"ok": False, "reason": "no_speech", "speaker": role}
    who = "CALLER" if role == "caller" else "HOST"
    if session_id:
        remember_line(session_id, who, text)
        await _persist_line(db_pool, session_id, "host", who, text)
    return {"ok": True, "text": text, "speaker": role, "identity": (identity or "").strip()}


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
