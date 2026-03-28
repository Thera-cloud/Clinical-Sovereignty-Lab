"""
LittleNate-1.X API Router — OpenAI-compatible endpoints.

Phase 1 (internal): Admin-only, no OAuth required.
Phase 2 (public): OAuth 2.0 client_credentials with scopes.

Endpoints:
  POST /v1/chat/completions   — text generation (Helix + LLM)
  POST /v1/audio/speech        — text-to-speech
  POST /v1/audio/transcriptions — speech-to-text
  WS   /v1/realtime            — bidirectional audio streaming
  POST /v1/coherence/score     — Nevedal coherence scoring
  GET  /v1/models              — available models
  POST /v1/oauth/token         — OAuth 2.0 token grant
  GET  /v1/health              — API health check
  WS   /ws/nate-media-stream   — Twilio Media Stream bridge (via twilio_ws_router)
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["LittleNate-1.X API"])


class ChatMessage(BaseModel):
    role: str = "user"
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "littlenate-1.0-chat"
    messages: List[ChatMessage]
    temperature: Optional[float] = None
    max_tokens: int = 1000
    stream: bool = False


class SpeechRequest(BaseModel):
    model: str = "littlenate-1.0-tts"
    input: str
    voice: str = "nate_warm"


class TranscriptionRequest(BaseModel):
    model: str = "littlenate-1.0-stt"


class CoherenceRequest(BaseModel):
    text: str
    domain: str = "general"
    user_id: str = "anonymous"


class OAuthTokenRequest(BaseModel):
    grant_type: str = "client_credentials"
    client_id: str
    client_secret: str


@router.get("/health")
async def health(request: Request):
    inference = getattr(request.app.state, "littlenate_inference", None)
    realtime = getattr(request.app.state, "littlenate_realtime", None)
    reward = getattr(request.app.state, "littlenate_reward", None)
    audit = getattr(request.app.state, "littlenate_audit", None)

    return {
        "status": "ok",
        "model": "littlenate-1.0",
        "services": {
            "inference": inference.get_status() if inference else {"ready": False},
            "realtime": realtime.get_status() if realtime else {"active_sessions": 0},
            "reward": reward.get_status() if reward else {"total_scored": 0},
            "audit": audit.get_status() if audit else {"total_logged": 0},
        },
    }


@router.get("/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "littlenate-1.0-chat",
                "object": "model",
                "created": 1741478400,
                "owned_by": "sovereign-sanctuary",
                "capabilities": ["chat", "coherence"],
            },
            {
                "id": "littlenate-1.0-realtime",
                "object": "model",
                "created": 1741478400,
                "owned_by": "sovereign-sanctuary",
                "capabilities": ["realtime", "voice", "chat", "coherence"],
            },
            {
                "id": "littlenate-1.0-tts",
                "object": "model",
                "created": 1741478400,
                "owned_by": "sovereign-sanctuary",
                "capabilities": ["tts"],
            },
            {
                "id": "littlenate-1.0-stt",
                "object": "model",
                "created": 1741478400,
                "owned_by": "sovereign-sanctuary",
                "capabilities": ["stt"],
            },
        ],
    }


@router.post("/chat/completions")
async def chat_completions(body: ChatCompletionRequest, request: Request):
    start = time.time()
    inference = getattr(request.app.state, "littlenate_inference", None)
    if not inference:
        raise HTTPException(503, "Inference service not available")

    system_parts = []
    user_prompt = ""
    for msg in body.messages:
        if msg.role == "system":
            system_parts.append(msg.content)
        elif msg.role == "user":
            user_prompt = msg.content

    if not user_prompt:
        raise HTTPException(400, "No user message provided")

    result = await inference.generate(
        prompt=user_prompt,
        system="\n".join(system_parts),
        temperature=body.temperature,
        max_tokens=body.max_tokens,
    )

    reward = getattr(request.app.state, "littlenate_reward", None)
    if reward:
        await reward.score_and_store(
            prompt=user_prompt,
            response=result.text,
            c_knowledge=result.c_knowledge,
            c_quantum_self=result.c_quantum_self,
            felt_sense=result.felt_sense,
            domain=result.domain,
            provider=result.provider,
            tokens_used=result.tokens_used,
            latency_ms=result.latency_ms,
        )

    audit = getattr(request.app.state, "littlenate_audit", None)
    if audit:
        await audit.log_request(
            endpoint="/v1/chat/completions",
            c_knowledge=result.c_knowledge,
            c_quantum_self=result.c_quantum_self,
            felt_sense=result.felt_sense,
            latency_ms=result.latency_ms,
            tokens_used=result.tokens_used,
            provider=result.provider,
        )

    return {
        "id": f"chatcmpl-{int(time.time()*1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": result.text},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": len(user_prompt.split()),
            "completion_tokens": result.tokens_used,
            "total_tokens": result.tokens_used + len(user_prompt.split()),
        },
        "coherence": {
            "c_knowledge": result.c_knowledge,
            "c_quantum_self": result.c_quantum_self,
            "felt_sense": result.felt_sense,
            "provider": result.provider,
            "crystals_retrieved": result.crystals_retrieved,
            "helix_nodes": result.helix_nodes,
        },
    }


@router.post("/audio/speech")
async def text_to_speech(body: SpeechRequest, request: Request):
    from fastapi.responses import Response
    from app.services import edge_tts_service

    audio = await edge_tts_service.synthesize(
        body.input,
        voice=body.voice,
    )

    if not audio:
        raise HTTPException(500, "TTS synthesis failed")

    audit = getattr(request.app.state, "littlenate_audit", None)
    if audit:
        await audit.log_request(endpoint="/v1/audio/speech", latency_ms=0)

    return Response(content=audio, media_type="audio/mpeg")


@router.post("/audio/transcriptions")
async def speech_to_text(request: Request):
    from app.services.sovereign_whisper import transcribe

    form = await request.form()
    file = form.get("file")
    if not file:
        raise HTTPException(400, "No audio file provided")

    audio_data = await file.read()
    result = await transcribe(audio_data)

    audit = getattr(request.app.state, "littlenate_audit", None)
    if audit:
        await audit.log_request(
            endpoint="/v1/audio/transcriptions",
            latency_ms=result.get("latency_ms", 0),
        )

    return {
        "text": result.get("text", ""),
        "provider": result.get("provider", "none"),
        "language": result.get("language", "en"),
    }


@router.websocket("/realtime")
async def realtime_websocket(websocket: WebSocket):
    await websocket.accept()

    realtime = getattr(websocket.app.state, "littlenate_realtime", None)
    if not realtime:
        await websocket.close(1011, "Realtime service not available")
        return

    session = await realtime.create_session(websocket)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                await session.handle_message(msg)
            except json.JSONDecodeError:
                await session._send({"type": "error", "error": {"message": "Invalid JSON"}})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("Realtime WS error: %s", e)
    finally:
        realtime.remove_session(session.session_id)


# ── Twilio Media Stream WebSocket ──────────────────────────────────────────

_twilio_ws_router = APIRouter(tags=["Twilio Media Stream"])


@_twilio_ws_router.websocket("/ws/nate-media-stream")
async def twilio_media_stream(websocket: WebSocket, call_id: str = "", user_id: str = ""):
    """
    Twilio Media Stream WebSocket endpoint.

    Twilio connects here after a <Stream> TwiML verb. This bridges
    Twilio's mulaw audio stream with Little Nate's full cognitive
    pipeline (STT -> Attunement -> Inference -> RISSC TTS).
    """
    await websocket.accept()
    print(f"[TWILIO-WS] WebSocket accepted, query call_id={call_id!r}, user_id={user_id!r}")

    call_context: Dict[str, Any] = {}

    async def _load_context_from_redis(cid: str) -> dict:
        """Load call context from Redis by call_id."""
        try:
            from app.services.api_server import _get_auth_redis
            redis = await _get_auth_redis()
            if redis:
                ctx_json = await redis.get(f"nate:call_context:{cid}")
                if ctx_json:
                    if isinstance(ctx_json, bytes):
                        ctx_json = ctx_json.decode()
                    ctx = json.loads(ctx_json)
                    print(f"[TWILIO-WS] Loaded call context: opening_line={ctx.get('opening_line', '')[:60]}")
                    return ctx
                else:
                    print(f"[TWILIO-WS] No call context found in Redis for call_id={cid}")
        except Exception as e:
            print(f"[TWILIO-WS] Failed to load call context from Redis: {e}")
        return {}

    if call_id:
        call_context = await _load_context_from_redis(call_id)

    if not call_context and user_id:
        call_context = {"username": user_id, "is_nate_initiated": False}
        pool = getattr(websocket.app.state, "db_pool", None)
        if pool:
            try:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        """
                        SELECT profile_data->>'tier' AS tier, id::text AS user_uuid
                        FROM users WHERE username = $1
                        """,
                        user_id,
                    )
                if row:
                    from app.services.voice_metering import max_single_call_seconds

                    if row.get("tier"):
                        call_context["tier"] = row["tier"]
                        call_context["max_call_seconds"] = max_single_call_seconds(
                            row["tier"]
                        )
                    if row.get("user_uuid"):
                        call_context["user_uuid"] = row["user_uuid"]
            except Exception as e:
                logger.warning("twilio_media_stream tier lookup failed: %s", e)

    realtime = getattr(websocket.app.state, "littlenate_realtime", None)

    # ── Grok Realtime (xAI) + Hetzner XTTS (see twilio_grok_xtts_pipeline.py) ──
    # 1) TWILIO_VOICE_PIPELINE=grok_xtts (or 1/true/yes) → always try Grok+XTTS first.
    # 2) If littlenate_realtime is missing → Grok+XTTS fallback when configured.
    # 3) Otherwise → legacy TwilioMediaSession when realtime exists.
    try:
        from app.services.twilio_grok_xtts_pipeline import (
            grok_xtts_configured,
            run_twilio_grok_xtts_bridge,
            use_grok_xtts_pipeline,
        )

        force_grok_xtts = os.getenv("TWILIO_VOICE_PIPELINE", "").strip().lower() == "grok_xtts"
        force_grok_xtts = force_grok_xtts or use_grok_xtts_pipeline()
        configured = grok_xtts_configured()

        if force_grok_xtts:
            if configured:
                print("[TWILIO-WS] Using Grok+XTTS pipeline (TWILIO_VOICE_PIPELINE)")
                _pool = getattr(websocket.app.state, "db_pool", None)
                if _pool and isinstance(call_context, dict):
                    call_context["db_pool"] = _pool
                    call_context["app_state"] = websocket.app.state
                try:
                    await run_twilio_grok_xtts_bridge(websocket, call_context)
                except WebSocketDisconnect:
                    print("[TWILIO-WS] Grok+XTTS pipeline WebSocket disconnected")
                except Exception as e:
                    logger.warning("Twilio Grok+XTTS pipeline error: %s", e)
                return
            print(
                "[TWILIO-WS] TWILIO_VOICE_PIPELINE=grok_xtts but Grok+XTTS not configured "
                "(set XAI_API_KEY and XTTS_URL on backend, then recreate container)"
            )

        if not realtime:
            if configured:
                print(
                    "[TWILIO-WS] littlenate_realtime not available — Using Grok+XTTS pipeline"
                )
                _pool = getattr(websocket.app.state, "db_pool", None)
                if _pool and isinstance(call_context, dict):
                    call_context["db_pool"] = _pool
                    call_context["app_state"] = websocket.app.state
                try:
                    await run_twilio_grok_xtts_bridge(websocket, call_context)
                except WebSocketDisconnect:
                    print("[TWILIO-WS] Grok+XTTS pipeline WebSocket disconnected")
                except Exception as e:
                    logger.warning("Twilio Grok+XTTS pipeline error: %s", e)
                return
            print(
                "[TWILIO-WS] Grok+XTTS not configured — set XAI_API_KEY and XTTS_URL "
                "on the backend container, then recreate (not restart) so env loads."
            )
            print("[TWILIO-WS] No voice pipeline available, closing")
            try:
                await websocket.close(
                    code=1011, reason="No voice service available"
                )
            except Exception:
                pass
            return

    except Exception as e:
        logger.warning("Twilio Grok+XTTS import or gate failed: %s", e)
        if not realtime:
            print("[TWILIO-WS] No voice pipeline available, closing")
            try:
                await websocket.close(
                    code=1011, reason="No voice service available"
                )
            except Exception:
                pass
            return

    session = await realtime.create_twilio_session(websocket, call_context=call_context)

    async def _on_start_event(start_data: dict):
        """Called when the Twilio 'start' event arrives with customParameters."""
        from app.services.littlenate_realtime import _twilio_stream_custom_parameters

        nonlocal call_context
        params = _twilio_stream_custom_parameters(start_data)
        param_call_id = params.get("call_id", "")
        print(f"[TWILIO-WS] start event customParameters: {params}")
        if param_call_id and not call_context:
            call_context = await _load_context_from_redis(param_call_id)
            if call_context:
                session._call_context = call_context
                session._instructions = call_context.get("system_prompt", session._instructions)
                print(f"[TWILIO-WS] Injected context from start params, opening={call_context.get('opening_line', '')[:60]}")

    session._on_start_callback = _on_start_event

    try:
        await session.handle_twilio_messages()
    except WebSocketDisconnect:
        print(f"[TWILIO-WS] Disconnected: {session.session_id}")
    except Exception as e:
        print(f"[TWILIO-WS] Error: {e}")
    finally:
        realtime.remove_session(session.session_id)


@router.post("/coherence/score")
async def coherence_score(body: CoherenceRequest, request: Request):
    inference = getattr(request.app.state, "littlenate_inference", None)
    if not inference:
        raise HTTPException(503, "Inference service not available")

    quantum = getattr(request.app.state, "quantum_cognition_engine", None)
    if not quantum:
        raise HTTPException(503, "Quantum cognition engine not available")

    try:
        from app.services.vectorize_service import semantic_search_all
        crystals_raw = await semantic_search_all(body.text, body.user_id, top_k=10)
        crystals = []
        for matches in crystals_raw.values():
            crystals.extend(matches)
    except Exception:
        crystals = []

    eval_result = await quantum.evaluate(body.text, relevant_crystals=crystals or None)

    qs = eval_result.get("quantum_self", {})

    from app.services.nevedal_engine import compute_knowledge_coherence
    c_know = compute_knowledge_coherence(
        p_relevance=max((c.get("score", 0) for c in crystals), default=0.0),
        t_transfer=0.8,
        gamma_loss=0.05,
        e_complexity=0.3,
        t_elapsed_days=0.0,
    )

    return {
        "text": body.text[:200],
        "domain": body.domain,
        "c_knowledge": round(c_know, 4),
        "c_quantum_self": round(qs.get("c_quantum_self", 0.0), 4),
        "felt_sense": qs.get("felt_sense", "grounded"),
        "confidence_band": qs.get("confidence_band", "medium"),
        "metacognition": eval_result.get("metacognition", {}),
        "generative_wisdom": eval_result.get("generative_wisdom", {}),
    }


@router.post("/oauth/token")
async def oauth_token(body: OAuthTokenRequest, request: Request):
    if body.grant_type != "client_credentials":
        raise HTTPException(400, "Only client_credentials grant type is supported")

    oauth = getattr(request.app.state, "oauth_server", None)
    if not oauth:
        raise HTTPException(503, "OAuth server not available")

    result = await oauth.issue_token(body.client_id, body.client_secret)
    if "error" in result:
        raise HTTPException(401, result)

    return result


# Public alias for main.py to import
twilio_ws_router = _twilio_ws_router
