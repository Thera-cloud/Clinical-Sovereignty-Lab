"""
LN-Observer REST + WebSocket API — /api/ln-observer
# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel

from app.services.api_server import require_admin, require_coach
from app.services.ln_observer_engine import (
    ACK_TEXT_V1,
    OBSERVE_DEBOUNCE_S,
    ln_observer_engine,
    mint_ws_ticket,
    verify_ws_ticket,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ln-observer", tags=["ln-observer"])


def _engine():
    return ln_observer_engine


def _coach_id(user: dict) -> str:
    return (
        user.get("username")
        or user.get("hardware_id")
        or user.get("user_id")
        or ""
    )


def _coach_name(user: dict) -> str:
    return user.get("name") or user.get("username") or _coach_id(user)


# ── Approval gate ──────────────────────────────────────────


class AccessRequest(BaseModel):
    coach_id: Optional[str] = None
    coach_name: Optional[str] = None


@router.post("/request-access")
async def request_access(
    body: AccessRequest,
    user: dict = Depends(require_coach),
):
    eng = _engine()
    if not eng._db_pool:
        raise HTTPException(503, "Database unavailable")
    coach_id = body.coach_id or _coach_id(user)
    coach_name = body.coach_name or _coach_name(user)
    async with eng._db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO ln_observer_approvals (coach_id, coach_name, status)
               VALUES ($1,$2,'pending')
               ON CONFLICT (coach_id) DO UPDATE
                 SET status = CASE WHEN ln_observer_approvals.status='revoked'
                                   THEN 'pending' ELSE ln_observer_approvals.status END,
                     requested_at = now(),
                     coach_name = COALESCE(NULLIF($2,''), ln_observer_approvals.coach_name)""",
            coach_id,
            coach_name,
        )
    return {"ok": True, "status": "pending", "coach_id": coach_id}


@router.get("/status/{coach_id}")
async def feature_status(coach_id: str, user: dict = Depends(require_coach)):
    eng = _engine()
    if not eng._db_pool:
        return {"coach_id": coach_id, "status": "none"}
    async with eng._db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status FROM ln_observer_approvals WHERE coach_id=$1",
            coach_id,
        )
    return {"coach_id": coach_id, "status": row["status"] if row else "none"}


@router.get("/status")
async def feature_status_self(user: dict = Depends(require_coach)):
    return await feature_status(_coach_id(user), user)


class ApprovalDecision(BaseModel):
    coach_id: str
    coach_name: str = ""
    admin_id: str = ""
    decision: str
    notes: str = ""


@router.post("/admin/decide")
async def admin_decide(d: ApprovalDecision, admin: dict = Depends(require_admin)):
    if d.decision not in ("approved", "revoked"):
        raise HTTPException(400, "decision must be 'approved' or 'revoked'")
    eng = _engine()
    if not eng._db_pool:
        raise HTTPException(503, "Database unavailable")
    coach_name = d.coach_name
    if not coach_name.strip():
        async with eng._db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT profile_data->>'name' AS name FROM users
                   WHERE username=$1 OR hardware_id=$1 LIMIT 1""",
                d.coach_id,
            )
            if row and row["name"]:
                coach_name = row["name"]
            else:
                coach_name = d.coach_id
    admin_id = d.admin_id or admin.get("username") or "admin"
    async with eng._db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO ln_observer_approvals
               (coach_id, coach_name, status, decided_by, decided_at, notes)
               VALUES ($1,$2,$3,$4,now(),$5)
               ON CONFLICT (coach_id) DO UPDATE
                 SET status=$3, decided_by=$4, decided_at=now(), notes=$5,
                     coach_name=COALESCE(NULLIF($2,''), ln_observer_approvals.coach_name)""",
            d.coach_id,
            coach_name,
            d.decision,
            admin_id,
            d.notes,
        )
    return {"ok": True, "coach_id": d.coach_id, "status": d.decision}


@router.get("/admin/approvals")
async def list_approvals(admin: dict = Depends(require_admin)):
    eng = _engine()
    if not eng._db_pool:
        return []
    async with eng._db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT coach_id, coach_name, status, requested_at, decided_by, decided_at, notes "
            "FROM ln_observer_approvals ORDER BY requested_at DESC"
        )
    out = []
    for r in rows:
        d = dict(r)
        for k in ("requested_at", "decided_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        out.append(d)
    return out


@router.get("/admin/activation-log")
async def activation_log(limit: int = 200, admin: dict = Depends(require_admin)):
    eng = _engine()
    if not eng._db_pool:
        return []
    async with eng._db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, session_id, coach_id, coach_name, activated_at, deactivated_at, "
            "responsibility_ack, ack_text_version, client_ip, user_agent "
            "FROM ln_observer_activation_log ORDER BY activated_at DESC LIMIT $1",
            limit,
        )
    out = []
    for r in rows:
        d = dict(r)
        d["session_id"] = str(d["session_id"])
        for k in ("activated_at", "deactivated_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        out.append(d)
    return out


# ── Activate / deactivate ──────────────────────────────────


class ActivateRequest(BaseModel):
    coach_id: Optional[str] = None
    coach_name: Optional[str] = None
    responsibility_ack: bool = False


@router.post("/activate")
async def activate(
    body: ActivateRequest,
    request: Request,
    user: dict = Depends(require_coach),
):
    eng = _engine()
    coach_id = body.coach_id or _coach_id(user)
    coach_name = body.coach_name or _coach_name(user)
    if not await eng.coach_is_approved(coach_id):
        raise HTTPException(403, "LN-Observer is not approved for this coach.")
    if not body.responsibility_ack:
        raise HTTPException(400, "Activation requires responsibility acknowledgment.")
    if not eng._db_pool:
        raise HTTPException(503, "Database unavailable")

    prior = await eng.load_prior_summaries(coach_id, limit=5)
    clients = await eng.load_assigned_clients(coach_id)
    profile = await eng.load_coach_profile(coach_id)
    activation_memory = await eng.build_activation_prefetch(
        coach_id, clients, prior, profile,
    )
    session_id = str(uuid.uuid4())
    ticket = mint_ws_ticket(session_id, coach_id)

    async with eng._db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO ln_observer_sessions
               (session_id, coach_id, context_bundle, ws_ticket)
               VALUES ($1,$2,$3,$4)""",
            uuid.UUID(session_id),
            coach_id,
            prior,
            ticket,
        )
        await conn.execute(
            """INSERT INTO ln_observer_activation_log
               (session_id, coach_id, coach_name, responsibility_ack,
                ack_text_version, client_ip, user_agent)
               VALUES ($1,$2,$3,TRUE,'v1',$4,$5)""",
            uuid.UUID(session_id),
            coach_id,
            coach_name,
            request.client.host if request.client else None,
            request.headers.get("user-agent", ""),
        )

    from app.services.ln_observer_engine import LiveSession

    eng.live[session_id] = LiveSession(
        session_id,
        coach_id,
        coach_name,
        context_bundle=prior,
        assigned_clients=clients,
        coach_profile=profile,
        activation_memory=activation_memory,
    )
    await eng.db_log(
        session_id,
        "system",
        f"LN-Observer activated by {coach_name} ({coach_id}). Ack v1 accepted.",
    )
    return {
        "session_id": session_id,
        "ws_ticket": ticket,
        "ack_text": ACK_TEXT_V1,
    }


@router.post("/deactivate/{session_id}")
async def deactivate(session_id: str, user: dict = Depends(require_coach)):
    eng = _engine()
    summary = await eng.deactivate(session_id)
    return {"ok": True, "summary": summary}


@router.get("/health")
async def health():
    eng = _engine()
    return {
        "status": "ok",
        "live_sessions": len(eng.live),
        "db": eng._db_pool is not None,
    }


# ── WebSocket ──────────────────────────────────────────────


@router.websocket("/ws/{session_id}")
async def observer_ws(ws: WebSocket, session_id: str):
    eng = _engine()
    await ws.accept()

    # First message must be auth
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=15.0)
        auth = json.loads(raw)
    except Exception:
        await ws.close(code=4401)
        return

    if auth.get("type") != "auth" or not auth.get("token"):
        await ws.close(code=4401)
        return

    sess = eng.live.get(session_id) or await eng.hydrate_session(session_id)
    if not sess:
        await ws.close(code=4404)
        return

    ticket = auth.get("token") or ""
    if not verify_ws_ticket(session_id, sess.coach_id, ticket):
        # Also accept stored ticket from PG
        if eng._db_pool:
            async with eng._db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT ws_ticket FROM ln_observer_sessions WHERE session_id=$1",
                    uuid.UUID(session_id),
                )
            if not row or row["ws_ticket"] != ticket:
                await ws.close(code=4401)
                return
        else:
            await ws.close(code=4401)
            return

    if not await eng.coach_is_approved(sess.coach_id):
        await ws.close(code=4403)
        return

    await eng.mark_live_again(session_id)
    eng.live[session_id] = sess
    await ws.send_json({"type": "ready", "session_id": session_id})

    frame_counter = 0
    OBSERVE_EVERY_N = 10

    try:
        while True:
            warn = eng.session_time_warn(sess)
            if warn == "session_max":
                await ws.send_json({
                    "type": "session_warn",
                    "text": "LN-Observer 3-hour maximum reached. Ending session.",
                })
                await eng.deactivate(session_id)
                break
            if warn:
                await ws.send_json({"type": "session_warn", "text": warn})

            raw_msg = await ws.receive()

            if raw_msg.get("bytes") is not None:
                text = await eng.transcribe_audio(raw_msg["bytes"])
                if text:
                    async with sess.lock:
                        sess.add_transcript("audio_transcript", text)
                    await eng.db_log(session_id, "audio_transcript", text)
                    if eng._db_pool:
                        async with eng._db_pool.acquire() as conn:
                            await conn.execute(
                                "UPDATE ln_observer_sessions SET audio_seconds = audio_seconds + 8 "
                                "WHERE session_id=$1",
                                uuid.UUID(session_id),
                            )
                    await ws.send_json({"type": "transcript", "text": text})
                continue

            if raw_msg.get("text") is None:
                continue
            msg = json.loads(raw_msg["text"])
            mtype = msg.get("type")

            if mtype == "frame":
                async with sess.lock:
                    sess.add_frame(msg.get("jpeg_b64", ""))
                frame_counter += 1
                if eng._db_pool:
                    async with eng._db_pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE ln_observer_sessions SET frame_count = frame_count + 1 "
                            "WHERE session_id=$1",
                            uuid.UUID(session_id),
                        )
                now = time.time()
                if (
                    frame_counter % OBSERVE_EVERY_N == 0
                    and (now - sess.last_observe_at) >= OBSERVE_DEBOUNCE_S
                ):
                    sess.last_observe_at = now
                    note = await eng.generate_chat(
                        sess, "observe", lean=True
                    )
                    if note and not note.startswith("("):
                        async with sess.lock:
                            sess.add_transcript("frame_observation", note)
                        await eng.db_log(session_id, "frame_observation", note)
                        await ws.send_json({"type": "observation", "text": note})

            elif mtype == "chat":
                coach_text = (msg.get("text") or "").strip()
                if not coach_text:
                    continue
                async with sess.lock:
                    sess.add_transcript("coach_chat", coach_text)
                await eng.db_log(session_id, "coach_chat", coach_text)
                await ws.send_json({"type": "thinking"})
                reply = await eng.generate_chat(sess, coach_text, lean=False)
                async with sess.lock:
                    sess.add_transcript("ln_chat", reply)
                    sess.chat.append({"role": "user", "content": coach_text})
                    sess.chat.append({"role": "assistant", "content": reply})
                    eng.maybe_compact_chat(sess)
                    if len(sess.chat) > 12 and not sess.chat_compact:
                        sess.chat = sess.chat[-12:]
                    sess.last_ln_reply = reply
                await eng.db_log(session_id, "ln_chat", reply)
                await ws.send_json({"type": "ln_reply", "text": reply})

                # Gap 4 — substantive exchange crystallize
                if (
                    sess.pending_crystallize_coach
                    and (time.time() - sess.pending_crystallize_at) < 120
                    and len(reply) >= 200
                ):
                    await eng._crystallize_safe(
                        sess.coach_id,
                        sess.pending_crystallize_coach,
                        reply,
                        coach_name=sess.coach_name,
                    )
                    sess.pending_crystallize_coach = ""
                elif len(reply) >= 200:
                    sess.pending_crystallize_coach = coach_text
                    sess.pending_crystallize_at = time.time()

            elif mtype == "look_now":
                await ws.send_json({"type": "thinking"})
                look_prompt = (
                    msg.get("text")
                    or "Look closely at what is on screen right now and note "
                       "clinically relevant cues for the coach."
                )
                note = await eng.generate_chat(
                    sess,
                    look_prompt,
                    look_now=True,
                )
                if note:
                    async with sess.lock:
                        sess.add_transcript("frame_observation", note)
                    await eng.db_log(session_id, "frame_observation", note)
                    # Gap 4 — forge requires user_text >= 40 chars
                    crystallize_user = (
                        f"LN-Observer look_now: {look_prompt}\n"
                        f"Context: {eng.context_block(sess, n=6)[:400]}"
                    )
                    await eng._crystallize_safe(
                        sess.coach_id,
                        crystallize_user,
                        note,
                        coach_name=sess.coach_name,
                        min_score=2,
                    )
                    await ws.send_json({"type": "observation", "text": note})

            elif mtype == "end":
                break

    except WebSocketDisconnect:
        await eng.mark_reconnecting(session_id)
    except Exception as e:
        logger.warning("LN-Observer WS error: %s", e)
        await eng.mark_reconnecting(session_id)
    # Grace: do not deactivate immediately — sweep handles orphans after 90s
