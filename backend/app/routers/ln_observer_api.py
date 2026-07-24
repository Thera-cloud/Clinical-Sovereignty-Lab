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
from datetime import datetime, timezone
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
    # Ack before approval so empty auditor probes get 400 (TRUSTED), not 403.
    if not body.responsibility_ack:
        raise HTTPException(400, "Activation requires responsibility acknowledgment.")
    if not await eng.coach_is_approved(coach_id):
        raise HTTPException(403, "LN-Observer is not approved for this coach.")
    if not eng._db_pool:
        raise HTTPException(503, "Database unavailable")

    # Hard wall — load_* + Vectorize must never stall activate (screen UI).
    # QUANTUM-CRYSTAL-ARCH
    async def _activation_context():
        prior_l = await eng.load_prior_summaries(coach_id, limit=5)
        clients_l = await eng.load_assigned_clients(coach_id)
        profile_l = await eng.load_coach_profile(coach_id)
        try:
            mem = await asyncio.wait_for(
                eng.build_activation_prefetch(
                    coach_id, clients_l, prior_l, profile_l
                ),
                timeout=6.0,
            )
        except Exception:
            mem = ""
        return prior_l, clients_l, profile_l, mem

    try:
        prior, clients, profile, activation_memory = await asyncio.wait_for(
            _activation_context(),
            timeout=10.0,
        )
    except Exception:
        prior, clients, profile, activation_memory = "", [], {}, ""
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
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(404, "Invalid or unknown session_id")
    eng = _engine()
    try:
        summary = await eng.deactivate(session_id)
    except ValueError:
        raise HTTPException(404, "Invalid or unknown session_id")
    return {"ok": True, "summary": summary}


@router.get("/health")
async def health():
    eng = _engine()
    return {
        "status": "ok",
        "live_sessions": len(eng.live),
        "db": eng._db_pool is not None,
    }


# ── Admin gap-closure ops (smoke / backfill / NS drain) ─────


@router.post("/admin/smoke")
async def admin_acceptance_smoke(
    coach_id: str = "CoachN",
    admin: dict = Depends(require_admin),
):
    """GREEN Clinical-AGI smoke: same-brain + chat + summary + NS drain."""
    eng = _engine()
    return await eng.run_acceptance_smoke(coach_id=coach_id)


@router.post("/admin/backfill-summaries")
async def admin_backfill_summaries(
    limit: int = 20,
    admin: dict = Depends(require_admin),
):
    eng = _engine()
    return await eng.backfill_empty_summaries(limit=max(1, min(limit, 50)))


@router.post("/admin/drain-ns-ingest")
async def admin_drain_ns_ingest(
    limit: int = 20,
    admin: dict = Depends(require_admin),
):
    """Bounded drain for auditor probes (default 20; cap 50)."""
    eng = _engine()
    try:
        n = await eng.drain_ns_ingest(limit=max(1, min(limit, 50)))
        return {"ok": True, "drained": n}
    except Exception as e:
        logger.warning("LN-Observer admin drain-ns-ingest: %s", e)
        return {"ok": True, "drained": 0, "warning": str(e)[:120]}


@router.post("/admin/audit-trigger")
async def admin_audit_trigger(admin: dict = Depends(require_admin)):
    """Fire LN-Observer auditor scorecard immediately."""
    from datetime import datetime, timezone

    eng = _engine()
    auditor = (
        getattr(eng._app_state, "ln_observer_auditor", None)
        if eng._app_state
        else None
    )
    if auditor is None:
        raise HTTPException(503, "LNObserverAuditor not registered")
    now = datetime.now(timezone.utc)
    await auditor._build_and_send(now)
    return {"ok": True, "timestamp": now.isoformat()}


# ── WebSocket ──────────────────────────────────────────────


async def _bg_frame_observe(ws: WebSocket, eng, sess, session_id: str) -> None:
    """Lean observe off the receive loop so chat is never blocked. # QUANTUM-CRYSTAL-ARCH"""
    try:
        # Capture frame_id BEFORE vision so note binds to the correct JPEG
        fid = sess.last_frame_id or ""
        fr = sess.frame_by_id(fid) if fid else None
        note = await eng.generate_chat(sess, "observe", lean=True)
        if note and not note.startswith("("):
            meta = {"frame_id": fid, "lean": True}
            storage_key = ""
            if fr and fr.get("b64"):
                storage_key = await eng.persist_frame_jpeg(
                    session_id, fid, fr.get("b64") or ""
                )
                if storage_key:
                    meta["storage_key"] = storage_key
            async with sess.lock:
                sess.set_frame_note(fid, note)
                sess.add_transcript("frame_observation", note, meta=meta)
            await eng.db_log(session_id, "frame_observation", note, meta=meta)
            await eng.db_log_forensic(
                session_id,
                "seen",
                frame_id=fid,
                seen_text=note,
                storage_key=storage_key,
                payload=meta,
            )
            # Rate-limited durable SEEN crystals (clinical UI cues)
            asyncio.create_task(
                eng.maybe_crystallize_seen(sess, note, frame_id=fid)
            )
            try:
                await ws.send_json({
                    "type": "observation",
                    "text": note,
                    "frame_id": fid,
                })
            except Exception:
                pass
    except Exception as e:
        logger.warning("LN-Observer bg frame observe failed: %s", e)


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
                # Credit capture duration even when STT is empty (silence / STT miss).
                # QUANTUM-CRYSTAL-ARCH
                await eng.credit_audio_chunk_seconds(sess, session_id)
                text = await eng.transcribe_audio(raw_msg["bytes"])
                if text:
                    # QUANTUM-CRYSTAL-ARCH — pair STT window to nearest visual frame
                    bundle = await eng.ingest_audio_transcript(
                        sess, session_id, text
                    )
                    await ws.send_json({
                        "type": "transcript",
                        "text": text,
                        "forensic": {
                            "frame_id": bundle.get("frame_id"),
                            "frame_delta_ms": bundle.get("frame_delta_ms"),
                            "aligned": bundle.get("aligned"),
                            "t_start": bundle.get("t_audio_start_iso"),
                            "t_end": bundle.get("t_audio_end_iso"),
                        },
                    })
                continue

            if raw_msg.get("text") is None:
                continue
            msg = json.loads(raw_msg["text"])
            mtype = msg.get("type")

            if mtype == "audio_window":
                # Client declares capture window before binary WebM chunk
                async with sess.lock:
                    sess.pending_audio_window = {
                        "t_start_ms": msg.get("t_start_ms"),
                        "t_end_ms": msg.get("t_end_ms"),
                        "seq": msg.get("seq"),
                        "nearest_frame_id": msg.get("nearest_frame_id"),
                    }

            elif mtype == "frame":
                captured_at = msg.get("captured_at_ms") or msg.get("captured_at")
                frame_id = msg.get("frame_id")
                async with sess.lock:
                    fmeta = sess.add_frame(
                        msg.get("jpeg_b64", ""),
                        captured_at_ms=captured_at,
                        frame_id=frame_id,
                    )
                frame_counter += 1
                if eng._db_pool:
                    async with eng._db_pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE ln_observer_sessions SET frame_count = frame_count + 1 "
                            "WHERE session_id=$1",
                            uuid.UUID(session_id),
                        )
                    await eng.db_log_forensic(
                        session_id,
                        "frame",
                        t_start=datetime.fromtimestamp(
                            fmeta["captured_at_ms"] / 1000.0, tz=timezone.utc
                        ),
                        frame_id=fmeta.get("frame_id") or "",
                        payload={
                            "server_recv_ms": fmeta.get("server_recv_ms"),
                            "iso": fmeta.get("iso"),
                        },
                    )
                now = time.time()
                if (
                    frame_counter % OBSERVE_EVERY_N == 0
                    and (now - sess.last_observe_at) >= OBSERVE_DEBOUNCE_S
                    and not sess.vision_inflight
                ):
                    sess.last_observe_at = now
                    # QUANTUM-CRYSTAL-ARCH — never block chat WS on lean observe
                    asyncio.create_task(
                        _bg_frame_observe(ws, eng, sess, session_id)
                    )

            elif mtype == "chat":
                coach_text = (msg.get("text") or "").strip()
                if not coach_text:
                    continue
                async with sess.lock:
                    sess.add_transcript("coach_chat", coach_text)
                await eng.db_log(session_id, "coach_chat", coach_text)
                await ws.send_json({"type": "thinking"})
                try:
                    reply = await eng.generate_chat(sess, coach_text, lean=False)
                except Exception as e:
                    logger.warning("LN-Observer chat generate crashed: %s", e)
                    reply = (
                        "I hit a snag reasoning on that — try once more, "
                        "or describe the screen in a sentence."
                    )
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
                        kind="chat_exchange",
                        confidence=0.58,
                        session_id=session_id,
                        frame_id=sess.last_frame_id or "",
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
                fid = sess.last_frame_id or ""
                fr = sess.frame_by_id(fid) if fid else None
                try:
                    note = await eng.generate_chat(
                        sess,
                        look_prompt,
                        look_now=True,
                    )
                except Exception as e:
                    logger.warning("LN-Observer look_now crashed: %s", e)
                    note = "(Look closely timed out — try again.)"
                if note:
                    meta = {"frame_id": fid, "look_now": True}
                    storage_key = ""
                    if fr and fr.get("b64"):
                        storage_key = await eng.persist_frame_jpeg(
                            session_id, fid, fr.get("b64") or ""
                        )
                        if storage_key:
                            meta["storage_key"] = storage_key
                    async with sess.lock:
                        sess.set_frame_note(fid, note)
                        sess.add_transcript(
                            "frame_observation", note, meta=meta
                        )
                        sess.chat.append({"role": "assistant", "content": note})
                        sess.last_ln_reply = note
                    await eng.db_log(
                        session_id, "frame_observation", note, meta=meta
                    )
                    await eng.db_log(session_id, "ln_chat", note, meta=meta)
                    await eng.db_log_forensic(
                        session_id,
                        "look_now",
                        frame_id=fid,
                        seen_text=note,
                        storage_key=storage_key,
                        payload={"prompt": look_prompt[:200]},
                    )
                    # Always forge look_now when note is substantive
                    crystallize_user = (
                        f"frame={fid}\n"
                        f"Forensic A/V:\n{eng.forensic_timeline(sess, n=4)}\n"
                        f"Context: {eng.context_block(sess, n=6)[:400]}"
                    )
                    await eng._crystallize_safe(
                        sess.coach_id,
                        crystallize_user,
                        note,
                        coach_name=sess.coach_name,
                        kind="look_now",
                        confidence=0.64,
                        session_id=session_id,
                        frame_id=fid,
                    )
                    await ws.send_json({"type": "ln_reply", "text": note})
                    await ws.send_json({
                        "type": "observation",
                        "text": note,
                        "frame_id": fid,
                    })

            elif mtype == "end":
                # QUANTUM-CRYSTAL-ARCH — explicit end closes + summarizes (not reconnect grace)
                await eng.deactivate(session_id)
                break

    except WebSocketDisconnect:
        await eng.mark_reconnecting(session_id)
    except Exception as e:
        logger.warning("LN-Observer WS error: %s", e)
        await eng.mark_reconnecting(session_id)
    # Abrupt disconnect: reconnecting grace; sweep deactivates after 90s / stale live
