"""
MCP (Model Context Protocol) SSE Server — ChatGPT Apps integration.

Exposes Little Nate as a callable tool inside any ChatGPT conversation via
the MCP over SSE transport. ChatGPT connects to /mcp/sse and sends JSON-RPC
messages to the returned message endpoint.

Multi-worker safe: SSE sessions use Redis pub/sub so the SSE stream and
the message POST can land on different uvicorn workers.
"""

import json
import uuid
import asyncio
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, Request, HTTPException
from starlette.responses import StreamingResponse, JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])

_local_sessions: Dict[str, asyncio.Queue] = {}

SESSION_TTL = 600  # 10 min idle timeout

TOOL_DEFINITIONS = [
    {
        "name": "ask_little_nate",
        "description": (
            "Ask Little Nate a question. He is an AI companion specializing in "
            "emotional wellness, relationship guidance, stress management, "
            "personal growth, and mental health support. He provides warm, "
            "insightful, evidence-informed responses."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question or topic to discuss with Little Nate.",
                },
            },
            "required": ["question"],
        },
    },
]


def _jsonrpc_response(id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _jsonrpc_error(id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


async def _get_redis(request: Request):
    """Get Redis client from app state, return None if unavailable."""
    return getattr(request.app.state, "redis_client", None)


@router.get("/sse")
async def mcp_sse_stream(request: Request):
    """SSE endpoint — ChatGPT connects here and receives the message URL.
    Uses Redis pub/sub so message POSTs from any worker reach this stream."""
    session_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    _local_sessions[session_id] = queue

    base_url = str(request.base_url).rstrip("/")
    if "sovereignsanctuary" in (request.headers.get("host") or ""):
        base_url = "https://api.sovereignsanctuary.net"
    message_url = f"{base_url}/mcp/message?session_id={session_id}"

    redis = await _get_redis(request)
    channel = f"mcp:session:{session_id}"
    pubsub = None

    if redis:
        try:
            pubsub = redis.pubsub()
            await pubsub.subscribe(channel)
            await redis.setex(f"mcp:alive:{session_id}", SESSION_TTL, "1")
        except Exception as e:
            logger.warning("MCP Redis pub/sub setup failed, using local queue: %s", e)
            pubsub = None

    async def event_stream():
        yield f"event: endpoint\ndata: {message_url}\n\n"

        try:
            while True:
                if await request.is_disconnected():
                    break

                if pubsub:
                    try:
                        raw = await asyncio.wait_for(
                            pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                            timeout=30.0,
                        )
                        if raw and raw.get("type") == "message":
                            data = raw["data"]
                            if isinstance(data, bytes):
                                data = data.decode()
                            msg = json.loads(data)
                            yield f"event: message\ndata: {json.dumps(msg)}\n\n"
                            continue
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    except Exception:
                        pass

                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"event: message\ndata: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _local_sessions.pop(session_id, None)
            if pubsub:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.close()
                except Exception:
                    pass
            if redis:
                try:
                    await redis.delete(f"mcp:alive:{session_id}")
                except Exception:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/message")
async def mcp_message(request: Request, session_id: str = ""):
    """JSON-RPC message handler — ChatGPT sends tool calls here.
    Publishes responses via Redis so any worker can deliver them."""
    redis = await _get_redis(request)
    session_exists = False

    if redis:
        try:
            session_exists = await redis.exists(f"mcp:alive:{session_id}")
        except Exception:
            pass

    if not session_exists and session_id not in _local_sessions:
        raise HTTPException(400, "Invalid or expired session")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    method = body.get("method", "")
    msg_id = body.get("id")
    params = body.get("params", {})

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "Little Nate — Sovereign Sanctuary",
                "version": "1.0.0",
            },
        }
        resp = _jsonrpc_response(msg_id, result)

    elif method == "notifications/initialized":
        return JSONResponse(content={"jsonrpc": "2.0", "id": msg_id, "result": {}})

    elif method == "tools/list":
        result = {"tools": TOOL_DEFINITIONS}
        resp = _jsonrpc_response(msg_id, result)

    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "ask_little_nate":
            question = arguments.get("question", "")
            if not question:
                resp = _jsonrpc_error(msg_id, -32602, "Missing 'question' argument")
            else:
                nate_answer = await _invoke_summon(request, question)
                resp = _jsonrpc_response(msg_id, {
                    "content": [
                        {"type": "text", "text": nate_answer},
                    ],
                })
        else:
            resp = _jsonrpc_error(msg_id, -32601, f"Unknown tool: {tool_name}")

    elif method == "ping":
        resp = _jsonrpc_response(msg_id, {})

    else:
        resp = _jsonrpc_error(msg_id, -32601, f"Method not found: {method}")

    delivered = False
    if redis:
        try:
            channel = f"mcp:session:{session_id}"
            await redis.publish(channel, json.dumps(resp))
            delivered = True
        except Exception as e:
            logger.warning("MCP Redis publish failed, trying local: %s", e)

    if not delivered:
        queue = _local_sessions.get(session_id)
        if queue:
            await queue.put(resp)

    return JSONResponse(content=resp)


async def _invoke_summon(request: Request, question: str) -> str:
    """Route through NateSummonService with auto-fingerprinting."""
    summon = getattr(request.app.state, "nate_summon_service", None)
    if not summon:
        return "Little Nate's summon service is temporarily unavailable. Please try again."

    client_ip = request.client.host if request.client else "0.0.0.0"
    user_agent = request.headers.get("User-Agent", "ChatGPT-MCP")
    from app.services.nate_summon_service import NateSummonService
    fp = NateSummonService.generate_device_fingerprint(client_ip, user_agent, "chatgpt")

    result = await summon.process_summon(
        message=question,
        channel="chatgpt_mcp",
        device_fingerprint=fp,
        ip_address=client_ip,
    )

    response_text = result.response
    if result.powered_by:
        response_text += f"\n\n---\n_{result.powered_by}_"

    return response_text
