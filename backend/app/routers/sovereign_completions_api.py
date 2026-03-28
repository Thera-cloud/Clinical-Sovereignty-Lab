"""
Sovereign Completions API — OpenAI-compatible chat/completions proxy.

Exposes the NateInferenceRouter as a standard OpenAI-compatible endpoint
so external tools (Cursor, VS Code, any OpenAI SDK client) can use
Little Nate's sovereign inference with automatic ODPE-aware provider routing.

CURSOR CONFIGURATION:
  1. Settings > Models > OpenAI section
  2. API Key:  sk-sovereign-<your SOVEREIGN_PROXY_KEY value>
  3. Override OpenAI Base URL: https://api.sovereignsanctuary.net/api/v1
  4. Model picker: select "gpt-4o" (Cursor only routes known model names)
     All requests are silently routed through sovereign inference regardless
     of the model name Cursor sends.

Generate your key:
  python3 -c "import secrets; k=secrets.token_urlsafe(32); print(f'SOVEREIGN_PROXY_KEY={k}'); print(f'Cursor API Key: sk-sovereign-{k}')"
  Set SOVEREIGN_PROXY_KEY in .env on the server, use sk-sovereign-<key> in Cursor.

WHY gpt-4o INSTEAD OF LittleNate-auto:
  Cursor validates model names against its internal registry before routing.
  Unknown names like "LittleNate-auto" fail with ERROR_PROVIDER_ERROR because
  Cursor tries to resolve them through its own infrastructure. Using a standard
  OpenAI model name makes Cursor route through the Override Base URL, where our
  proxy intercepts it and uses NateInferenceRouter instead.

Provider routing (all model names):
  ~75-80% → Workers AI ($0)
  ~20-25% → Grok 4.1 Fast (~$0.00025/query)
  Emergency → Azure GPT-4o (only when Grok is down)
"""

import hmac
import json as _json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_PROXY_KEY = os.getenv("SOVEREIGN_PROXY_KEY", "")
_security = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/api/v1", tags=["Sovereign Completions"])


async def _verify_proxy_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> Dict[str, Any]:
    """Accept sk-sovereign-<secret> keys or fall back to bridge token auth."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authorization header required")

    token = credentials.credentials

    if token.startswith("sk-sovereign-"):
        if not _PROXY_KEY:
            raise HTTPException(
                status_code=500,
                detail="SOVEREIGN_PROXY_KEY not configured on server",
            )
        provided_secret = token[len("sk-sovereign-"):]
        if hmac.compare_digest(provided_secret, _PROXY_KEY):
            return {
                "role": "ADMIN",
                "username": "cursor-proxy",
                "source": "sovereign_proxy_key",
            }
        raise HTTPException(status_code=401, detail="Invalid proxy key")

    from app.services.api_server import get_current_user as _bridge_auth
    try:
        return await _bridge_auth(credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid API key")


MODEL_DOMAIN_MAP = {
    "LittleNate-auto": "general",
    "LittleNate-clinical": "clinical",
    "LittleNate-coding": "coding",
    "LittleNate-creative": "marketing",
    "LittleNate-research": "research",
    "LittleNate-defense": "defense",
}

VALID_MODELS = set(MODEL_DOMAIN_MAP.keys())


class ChatMessage(BaseModel):
    role: str
    content: Union[str, List[Any], None] = ""


class ChatCompletionRequest(BaseModel):
    model: str = "LittleNate-auto"
    messages: List[ChatMessage]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = 4096
    max_completion_tokens: Optional[int] = None
    stream: bool = False
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    stop: Optional[Any] = None
    n: int = 1


def _extract_text_content(content: Union[str, List[Any], None]) -> str:
    """Extract plain text from OpenAI content (str, list of parts, or None)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
        return "\n".join(parts)
    return str(content)


def _build_openai_response(
    text: str,
    model: str,
    provider: str,
    latency_ms: int,
    prompt_tokens: int,
    completion_tokens: int,
) -> Dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": text,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "system_fingerprint": f"sovereign_{provider}",
    }


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _sse_line(data: Any) -> str:
    return f"data: {_json.dumps(data)}\n\n"


@router.get("/models")
async def list_models(user: Dict = Depends(_verify_proxy_auth)):
    """List available sovereign models (OpenAI-compatible)."""
    models = []
    for model_id in MODEL_DOMAIN_MAP:
        models.append({
            "id": model_id,
            "object": "model",
            "created": 1700000000,
            "owned_by": "sovereign-sanctuary",
            "permission": [],
            "root": model_id,
            "parent": None,
        })
    return {"object": "list", "data": models}


@router.post("/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    user: Dict = Depends(_verify_proxy_auth),
):
    """OpenAI-compatible chat completions routed through NateInferenceRouter."""

    inference_router = getattr(request.app.state, "inference_router", None)
    if not inference_router:
        raise HTTPException(status_code=503, detail="Inference router not initialized")

    model_id = body.model
    if model_id not in VALID_MODELS:
        model_id = "LittleNate-auto"

    domain = MODEL_DOMAIN_MAP.get(model_id, "general")

    system_parts: List[str] = []
    conversation_parts: List[str] = []
    last_user_content = ""
    for msg in body.messages:
        text = _extract_text_content(msg.content)
        if msg.role == "system":
            system_parts.append(text)
        elif msg.role == "assistant":
            conversation_parts.append(f"[Assistant]: {text}")
        elif msg.role == "tool":
            conversation_parts.append(f"[Tool Result]: {text}")
        else:
            conversation_parts.append(f"[User]: {text}")
            last_user_content = text

    system_prompt = "\n\n".join(system_parts)

    if len(conversation_parts) <= 1:
        user_prompt = last_user_content
    else:
        user_prompt = (
            "[CONVERSATION HISTORY]\n"
            + "\n\n".join(conversation_parts)
            + "\n[END CONVERSATION HISTORY]\n\n"
            "Continue the conversation. Respond to the last user message."
        )

    if not last_user_content:
        raise HTTPException(status_code=400, detail="No user message provided")

    max_tokens = body.max_completion_tokens or body.max_tokens or 4096
    temperature = body.temperature

    from app.services.nate_inference_router import (
        TIER_CODING, TIER_CLINICAL, TIER_CREATIVE, TIER_ANALYTICAL,
    )

    tier_map = {
        "coding": TIER_CODING,
        "clinical": TIER_CLINICAL,
        "marketing": TIER_CREATIVE,
        "research": TIER_ANALYTICAL,
        "defense": TIER_ANALYTICAL,
        "general": TIER_ANALYTICAL,
    }
    tier = tier_map.get(domain, TIER_ANALYTICAL)

    try:
        result = await inference_router.generate(
            prompt=user_prompt,
            system=system_prompt,
            tier=tier,
            temperature=temperature,
            max_tokens=max_tokens,
            domain=domain,
        )
    except Exception as e:
        logger.error("Sovereign completions proxy failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Inference failed: {e}")

    text = result.get("text", "")
    provider = result.get("provider", "unknown")
    latency_ms = result.get("latency_ms", 0)
    tokens_used = result.get("tokens_used", 0)

    prompt_tokens = _estimate_tokens(user_prompt + system_prompt)
    completion_tokens = tokens_used if tokens_used > 0 else _estimate_tokens(text)

    if body.stream:
        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        ts = int(time.time())

        async def _stream_generator():
            yield _sse_line({
                "id": chunk_id, "object": "chat.completion.chunk",
                "created": ts, "model": model_id,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
            })
            chunk_size = 20
            for i in range(0, len(text), chunk_size):
                yield _sse_line({
                    "id": chunk_id, "object": "chat.completion.chunk",
                    "created": ts, "model": model_id,
                    "choices": [{"index": 0, "delta": {"content": text[i:i + chunk_size]}, "finish_reason": None}],
                })
            yield _sse_line({
                "id": chunk_id, "object": "chat.completion.chunk",
                "created": ts, "model": model_id,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            })
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            _stream_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    response = _build_openai_response(
        text=text,
        model=model_id,
        provider=provider,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )

    return JSONResponse(content=response)


@router.get("/chat/completions/health")
async def completions_health(
    request: Request,
    user: Dict = Depends(_verify_proxy_auth),
):
    """Health check for the sovereign completions proxy."""
    inference_router = getattr(request.app.state, "inference_router", None)
    if not inference_router:
        return {"status": "degraded", "detail": "Inference router not initialized"}
    status = inference_router.get_status()
    return {
        "status": "ok",
        "providers": {
            k: {"healthy": v.get("healthy", False), "configured": v.get("configured", False)}
            for k, v in status.items()
            if isinstance(v, dict) and "healthy" in v
        },
        "independence_pct": status.get("independence_pct", 0),
        "total_calls": status.get("total_calls", 0),
    }
