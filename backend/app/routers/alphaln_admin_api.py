"""AlphaLN admin twin chat API (Slice 2 of the AlphaLN shadow-twin plan).

Admin-only surface (``DrNevedal1``) for talking to AlphaLN, the shadow
research twin of Little Nate. AlphaLN NEVER speaks to clients and NEVER
writes to production memory. See cursor rule ``alphaln-twin-isolation.mdc``
for the full invariants.

Feature-flagged: ``ENABLE_ALPHALN_TWIN`` (default false). When off, every
endpoint returns 503 so this surface ships dark.

Endpoints
---------
- ``POST /api/admin/alphaln/session``                — start a new chat session.
- ``POST /api/admin/alphaln/message``                — send admin turn, get twin reply.
- ``GET  /api/admin/alphaln/session/{id}``           — read a transcript.
- ``POST /api/admin/alphaln/session/{id}/end``       — mark session ended.
- ``GET  /api/admin/alphaln/sessions``               — list recent sessions.

Guardrails
----------
- Router-level ``require_admin`` dependency.
- Body-level ``_require_dr_nevedal1`` — only ``DrNevedal1`` may talk to the twin.
- ``enforce_mfa_recent`` on all three mutating endpoints (session, message, end).
- Prompts passed through ``maybe_pseudonymize_prompt`` (same regex set used by
  ``process_private_coaching`` / ``process_sanctuary_message``); replies are
  restored before returning to the admin console.
- In-memory per-username rate limit on message send (20 turns / 60s).
- No writes to ``conversation_history``, ``nate_intelligence_crystals``, or
  ``nevedal_metrics``. All state lives in ``alphaln_conversations`` +
  ``alphaln_messages`` (migration 421).
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.api_server import require_admin
from app.services.mfa_gate import enforce_mfa_recent
from app.services.pii_pseudonymizer import maybe_pseudonymize_prompt, restore_text

logger = logging.getLogger("nate.alphaln_admin_api")

router = APIRouter(prefix="/api/admin/alphaln", tags=["alphaln"])

_ENV_FLAG = "ENABLE_ALPHALN_TWIN"
_ADMIN_USERNAME = "DrNevedal1"

# Twin system prompt. Kept short + explicit so the twin does not drift into
# client-facing therapist mode. Admins can layer their own context inside
# individual messages.
_TWIN_SYSTEM_PROMPT = (
    "You are AlphaLN, the shadow research twin of Little Nate. "
    "You are addressed only by the admin console. You never talk to clients. "
    "You may reason about clinical patterns, therapy strategy, coevolution "
    "loops, and system design. You do not diagnose, prescribe, or claim to be "
    "a licensed clinician. Be concise, technical, and candid with the admin."
)

# --------------------------------------------------------------------------- #
# Feature flag + gating helpers                                               #
# --------------------------------------------------------------------------- #


def _is_enabled() -> bool:
    """Return True iff the AlphaLN twin surface is enabled."""
    raw = (os.getenv(_ENV_FLAG) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _require_enabled() -> None:
    if not _is_enabled():
        raise HTTPException(503, "AlphaLN twin disabled")


def _require_dr_nevedal1(principal: Dict[str, Any]) -> str:
    """Only DrNevedal1 may talk to the twin. Return the confirmed username."""
    username = (principal or {}).get("username")
    if username != _ADMIN_USERNAME:
        raise HTTPException(
            403, f"AlphaLN twin is restricted to {_ADMIN_USERNAME}"
        )
    return username


def _require_db(request: Request):
    db = getattr(request.app.state, "db_pool", None)
    if db is None:
        raise HTTPException(503, "Database unavailable")
    return db


# --------------------------------------------------------------------------- #
# Rate limiting (in-memory, per-username)                                     #
# --------------------------------------------------------------------------- #

_msg_hits: Dict[str, List[float]] = {}
_MSG_RATE_WINDOW_S = 60
_MSG_RATE_MAX = 20  # message turns per window per username


def _msg_rate_limited(username: str) -> bool:
    now = time.time()
    hits = [t for t in _msg_hits.get(username, []) if now - t < _MSG_RATE_WINDOW_S]
    hits.append(now)
    _msg_hits[username] = hits
    return len(hits) > _MSG_RATE_MAX


def _msg_rate_reset_for_tests() -> None:
    """Test hook to clear the in-memory rate window between test runs."""
    _msg_hits.clear()


# --------------------------------------------------------------------------- #
# Request / response models                                                   #
# --------------------------------------------------------------------------- #


class SessionCreateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)


class SessionCreateResponse(BaseModel):
    conversation_id: str
    created_at: str


class MessageRequest(BaseModel):
    conversation_id: str = Field(..., min_length=1, max_length=64)
    content: str = Field(..., min_length=1, max_length=8000)
    max_tokens: Optional[int] = Field(default=800, ge=32, le=4000)


class MessageResponse(BaseModel):
    reply: str
    provider: str
    latency_ms: int
    tokens_used: int


# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #


@router.post("/session", response_model=SessionCreateResponse)
async def create_session(
    req: SessionCreateRequest,
    request: Request,
    principal: Dict[str, Any] = Depends(require_admin),
):
    _require_enabled()
    username = _require_dr_nevedal1(principal)
    db = _require_db(request)
    await enforce_mfa_recent(db, principal)

    conv_id = uuid.uuid4()
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO alphaln_conversations (id, admin_user, title)
                 VALUES ($1, $2, $3)
              RETURNING id, created_at""",
            conv_id, username, (req.title or None),
        )
    logger.info("alphaln: session created id=%s admin=%s", row["id"], username)
    return SessionCreateResponse(
        conversation_id=str(row["id"]),
        created_at=row["created_at"].isoformat(),
    )


@router.post("/message", response_model=MessageResponse)
async def send_message(
    req: MessageRequest,
    request: Request,
    principal: Dict[str, Any] = Depends(require_admin),
):
    _require_enabled()
    username = _require_dr_nevedal1(principal)
    db = _require_db(request)
    await enforce_mfa_recent(db, principal)

    if _msg_rate_limited(username):
        logger.warning("alphaln.message rate-limited username=%s", username)
        raise HTTPException(429, "Too many AlphaLN messages; slow down.")

    try:
        conv_uuid = uuid.UUID(req.conversation_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "invalid conversation_id")

    async with db.acquire() as conn:
        conv = await conn.fetchrow(
            """SELECT id, admin_user, ended_at
                 FROM alphaln_conversations WHERE id = $1""",
            conv_uuid,
        )
        if not conv:
            raise HTTPException(404, "conversation not found")
        if conv["admin_user"] != username:
            raise HTTPException(403, "not your conversation")
        if conv["ended_at"] is not None:
            raise HTTPException(409, "conversation has ended")

        # Store the admin turn BEFORE calling the provider so a provider
        # failure still leaves an audit trail.
        await conn.execute(
            """INSERT INTO alphaln_messages (conversation_id, role, content)
                 VALUES ($1, 'user', $2)""",
            conv_uuid, req.content,
        )

    # Pseudonymize both the system + user prompts (regex-only; no whole-name
    # substitution -- admin fluency > audio-token cost here; matches
    # process_private_coaching pattern).
    ps, pu, book = maybe_pseudonymize_prompt(
        _TWIN_SYSTEM_PROMPT, req.content, known_names=None
    )

    reply_text = ""
    provider = "unavailable"
    latency_ms = 0
    tokens_used = 0
    try:
        from app.services.nate_inference_router import NateInferenceRouter

        out = await NateInferenceRouter(app_state=request.app.state).generate(
            prompt=pu or "",
            system=ps or _TWIN_SYSTEM_PROMPT,
            domain="general",
            max_tokens=int(req.max_tokens or 800),
        )
        reply_text = (out.get("text") or "").strip()
        provider = str(out.get("provider") or "router")
        latency_ms = int(out.get("latency_ms") or 0)
        tokens_used = int(out.get("tokens_used") or 0)
    except Exception as exc:
        logger.warning("alphaln inference failed: %s", exc)
        reply_text = "[AlphaLN unavailable — inference router error]"
        provider = "error"

    if book:
        reply_text = restore_text(reply_text, book)

    async with db.acquire() as conn:
        await conn.execute(
            """INSERT INTO alphaln_messages
                   (conversation_id, role, content, provider, latency_ms, tokens_used)
                 VALUES ($1, 'assistant', $2, $3, $4, $5)""",
            conv_uuid, reply_text, provider, latency_ms, tokens_used,
        )

    return MessageResponse(
        reply=reply_text,
        provider=provider,
        latency_ms=latency_ms,
        tokens_used=tokens_used,
    )


@router.get("/session/{conversation_id}")
async def get_session(
    conversation_id: str,
    request: Request,
    principal: Dict[str, Any] = Depends(require_admin),
):
    _require_enabled()
    username = _require_dr_nevedal1(principal)
    db = _require_db(request)

    try:
        conv_uuid = uuid.UUID(conversation_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "invalid conversation_id")

    async with db.acquire() as conn:
        conv = await conn.fetchrow(
            """SELECT id, admin_user, title, created_at, ended_at
                 FROM alphaln_conversations WHERE id = $1""",
            conv_uuid,
        )
        if not conv:
            raise HTTPException(404, "conversation not found")
        if conv["admin_user"] != username:
            raise HTTPException(403, "not your conversation")

        messages = await conn.fetch(
            """SELECT role, content, provider, latency_ms, tokens_used, created_at
                 FROM alphaln_messages
                WHERE conversation_id = $1
                ORDER BY created_at ASC""",
            conv_uuid,
        )

    return {
        "conversation_id": str(conv["id"]),
        "title": conv["title"],
        "created_at": conv["created_at"].isoformat(),
        "ended_at": conv["ended_at"].isoformat() if conv["ended_at"] else None,
        "messages": [
            {
                "role": m["role"],
                "content": m["content"],
                "provider": m["provider"],
                "latency_ms": m["latency_ms"],
                "tokens_used": m["tokens_used"],
                "created_at": m["created_at"].isoformat(),
            }
            for m in messages
        ],
    }


@router.post("/session/{conversation_id}/end")
async def end_session(
    conversation_id: str,
    request: Request,
    principal: Dict[str, Any] = Depends(require_admin),
):
    _require_enabled()
    username = _require_dr_nevedal1(principal)
    db = _require_db(request)
    await enforce_mfa_recent(db, principal)

    try:
        conv_uuid = uuid.UUID(conversation_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "invalid conversation_id")

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE alphaln_conversations
                  SET ended_at = COALESCE(ended_at, NOW())
                WHERE id = $1 AND admin_user = $2
            RETURNING id, ended_at""",
            conv_uuid, username,
        )
        if not row:
            raise HTTPException(404, "conversation not found")

    return {"conversation_id": str(row["id"]), "ended_at": row["ended_at"].isoformat()}


@router.get("/sessions")
async def list_sessions(
    request: Request,
    principal: Dict[str, Any] = Depends(require_admin),
    limit: int = 25,
):
    _require_enabled()
    username = _require_dr_nevedal1(principal)
    db = _require_db(request)

    limit = max(1, min(int(limit or 25), 200))
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """SELECT c.id, c.title, c.created_at, c.ended_at,
                      COUNT(m.id) AS message_count
                 FROM alphaln_conversations c
            LEFT JOIN alphaln_messages m ON m.conversation_id = c.id
                WHERE c.admin_user = $1
             GROUP BY c.id
             ORDER BY c.created_at DESC
                LIMIT $2""",
            username, limit,
        )

    return {
        "sessions": [
            {
                "conversation_id": str(r["id"]),
                "title": r["title"],
                "created_at": r["created_at"].isoformat(),
                "ended_at": r["ended_at"].isoformat() if r["ended_at"] else None,
                "message_count": int(r["message_count"] or 0),
            }
            for r in rows
        ]
    }
