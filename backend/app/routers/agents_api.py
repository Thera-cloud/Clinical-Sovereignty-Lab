"""
Partner Agents API — OpenAI-style plug-in for full agentic coding runs.

Auth: same sk-sovereign-* proxy key as /api/v1/chat/completions
      (SOVEREIGN_PROXY_KEY) or bridge admin token.

Runs CLI-Cloud sandboxed agentic loops via run_agentic_loop so partners
never mutate the live tree without an explicit promote.

Security (production-true):
- Proxy-key callers get role PARTNER (no DATA_TOOLS / no sandbox_promote tool).
- Promote requires bridge ADMIN (not proxy key alone).
- Concurrent runs capped; run state mirrored to Redis when available.
"""
# SOVEREIGN-VOICE — Partner Agents API plug-in

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Sovereign Agents"])
_security = HTTPBearer(auto_error=False)
_PROXY_KEY = os.getenv("SOVEREIGN_PROXY_KEY", "")
_MAX_CONCURRENT_RUNS = int(os.getenv("CLI_AGENT_MAX_CONCURRENT", "3"))
_RUN_TTL_S = int(os.getenv("CLI_AGENT_RUN_TTL_S", "86400"))
_RUN_SEMAPHORE = asyncio.Semaphore(_MAX_CONCURRENT_RUNS)
_ACTIVE_RUNS = 0
_ACTIVE_GUARD = asyncio.Lock()


async def _verify_proxy_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> Dict[str, Any]:
    """Same sk-sovereign-* contract as sovereign_completions_api (duplicated to avoid import cycles)."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authorization header required")
    token = credentials.credentials
    if token.startswith("sk-sovereign-"):
        if not _PROXY_KEY:
            raise HTTPException(status_code=500, detail="SOVEREIGN_PROXY_KEY not configured on server")
        provided_secret = token[len("sk-sovereign-"):]
        if hmac.compare_digest(provided_secret, _PROXY_KEY):
            # PARTNER — not ADMIN: blocks DATA_TOOLS + sandbox_promote tool path
            return {
                "role": "PARTNER",
                "username": "cursor-proxy",
                "source": "sovereign_proxy_key",
            }
        raise HTTPException(status_code=401, detail="Invalid proxy key")
    from app.services.api_server import get_current_user as _bridge_auth
    try:
        return await _bridge_auth(credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid API key")

_AGENT_RUNS: Dict[str, Dict[str, Any]] = {}
_AGENT_RUNS_GUARD = asyncio.Lock()
_AGENT_RUNS_MAX = 200

AGENTIC_CAPABILITIES = {
    "agentic_tool_loop": True,
    "parallel_tools": True,
    "per_path_write_locks": True,
    "auto_lint": True,
    "auto_pytest": True,
    "retry_until_green": True,
    "spawn_subagent": True,
    "todo_task_state": True,
    "redis_session_history": True,
    "mode_aware_reasoning_models": True,
    "cloud_sandbox_isolation": True,
    "sandbox_diff_promote": True,
    "partner_agents_api": True,
    "openai_compatible_completions": True,
    "autonomy_budget": True,
    "partner_role_isolation": True,
    "promote_protected_denylist": True,
    "agent_run_concurrency_cap": True,
    "agent_run_redis_mirror": True,
}


class AgentRunBody(BaseModel):
    prompt: str = Field(..., min_length=1, description="Coding / complex request")
    mode: str = Field("ln_fab", description="ask | plan | debug | ln_fab")
    cli: str = Field("cloud", description="cloud (sandboxed) or mac")
    session_id: Optional[str] = None
    plan_id: Optional[str] = None
    max_turns: Optional[int] = Field(None, ge=1, le=60)


class AgentPromoteBody(BaseModel):
    paths: Optional[List[str]] = None


def _tier_from_user(user: Dict[str, Any]) -> str:
    if user.get("source") == "sovereign_proxy_key":
        return "ENTERPRISE"
    role = (user.get("role") or "").upper()
    if role == "ADMIN":
        return "ENTERPRISE"
    return "PRO"


def _role_for_loop(user: Dict[str, Any]) -> str:
    """Proxy keys always PARTNER; bridge sessions keep their role."""
    if user.get("source") == "sovereign_proxy_key":
        return "PARTNER"
    return (user.get("role") or "PARTNER").upper()


def _redis_client():
    """Best-effort sync Redis; None when REDIS_URL empty (unit tests)."""
    if os.getenv("REDIS_URL", "__unset__") == "":
        return None
    try:
        import redis as sync_redis
        url = os.getenv("REDIS_URL", "")
        if url:
            return sync_redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.5)
    except Exception:
        return None
    return None


def _run_redis_key(run_id: str) -> str:
    env = os.getenv("ENVIRONMENT", "production")
    return f"nate:{env}:agent_run:{run_id}"


def _mirror_run_to_redis(run_id: str, payload: Dict[str, Any]) -> None:
    client = _redis_client()
    if not client:
        return
    try:
        slim = {
            k: v for k, v in payload.items()
            if k not in ("result",) or v is None
        }
        # Keep a trimmed result for cross-worker GET
        result = payload.get("result")
        if isinstance(result, dict):
            slim["result"] = {
                "status": result.get("status"),
                "turn_count": result.get("turn_count"),
                "provider": result.get("provider"),
                "files": result.get("files"),
                "tool_calls": result.get("tool_calls"),
                "autonomy": result.get("autonomy"),
                "sandbox": result.get("sandbox"),
                "response_text": (result.get("response_text") or "")[:8000],
                "warning": result.get("warning"),
                "error": result.get("error"),
            }
        else:
            slim["result"] = result
        client.setex(_run_redis_key(run_id), _RUN_TTL_S, json.dumps(slim, default=str))
    except Exception as e:
        logger.debug("agent run redis mirror failed: %s", e)


def _load_run_from_redis(run_id: str) -> Optional[Dict[str, Any]]:
    client = _redis_client()
    if not client:
        return None
    try:
        raw = client.get(_run_redis_key(run_id))
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.debug("agent run redis load failed: %s", e)
        return None


async def _store_run(run_id: str, payload: Dict[str, Any]) -> None:
    async with _AGENT_RUNS_GUARD:
        _AGENT_RUNS[run_id] = payload
        while len(_AGENT_RUNS) > _AGENT_RUNS_MAX:
            oldest = next(iter(_AGENT_RUNS))
            _AGENT_RUNS.pop(oldest, None)
    await asyncio.to_thread(_mirror_run_to_redis, run_id, payload)


async def _update_run(run_id: str, **fields: Any) -> None:
    payload = None
    async with _AGENT_RUNS_GUARD:
        run = _AGENT_RUNS.get(run_id)
        if run is not None:
            run.update(fields)
            payload = dict(run)
    if payload is not None:
        await asyncio.to_thread(_mirror_run_to_redis, run_id, payload)


async def _get_run(run_id: str) -> Optional[Dict[str, Any]]:
    async with _AGENT_RUNS_GUARD:
        run = _AGENT_RUNS.get(run_id)
        if run is not None:
            return dict(run)
    return await asyncio.to_thread(_load_run_from_redis, run_id)


@router.get("/agents/capabilities")
async def agent_capabilities(user: Dict = Depends(_verify_proxy_auth)):
    """Feature matrix proving Full Agentic Reasoning & Coding Agent surface."""
    return {
        "object": "agent.capabilities",
        "status": "ok",
        "capabilities": AGENTIC_CAPABILITIES,
        "auth": {
            "source": user.get("source") or "bridge",
            "tier": _tier_from_user(user),
            "role": _role_for_loop(user),
        },
        "limits": {
            "max_concurrent_runs": _MAX_CONCURRENT_RUNS,
            "run_ttl_s": _RUN_TTL_S,
        },
        "endpoints": {
            "create": "POST /api/v1/agents",
            "get": "GET /api/v1/agents/{run_id}",
            "cancel": "DELETE /api/v1/agents/{run_id}",
            "promote": "POST /api/v1/agents/{run_id}/promote",
            "completions": "POST /api/v1/chat/completions",
        },
    }


@router.post("/agents")
async def create_agent_run(
    body: AgentRunBody,
    request: Request,
    user: Dict = Depends(_verify_proxy_auth),
):
    """Queue a sandboxed agentic coding run (partner plug-in)."""
    global _ACTIVE_RUNS
    mode = body.mode if body.mode in ("ask", "plan", "debug", "ln_fab") else "ln_fab"
    cli = body.cli if body.cli in ("mac", "cloud") else "cloud"
    # Partners default to cloud sandbox — mac only for ADMIN bridge sessions
    if cli == "mac" and _tier_from_user(user) != "ENTERPRISE":
        raise HTTPException(403, "CLI-Mac agent runs require ENTERPRISE / admin auth")
    if cli == "mac" and user.get("source") == "sovereign_proxy_key":
        # Proxy keys always sandboxed on cloud for safety
        cli = "cloud"

    async with _ACTIVE_GUARD:
        if _ACTIVE_RUNS >= _MAX_CONCURRENT_RUNS:
            raise HTTPException(
                429,
                f"Too many concurrent agent runs (max {_MAX_CONCURRENT_RUNS})",
            )
        _ACTIVE_RUNS += 1

    run_id = uuid.uuid4().hex[:16]
    plan_id = body.plan_id or f"partner-{run_id}"
    session_id = body.session_id or run_id
    username = user.get("username") or "partner-agent"
    loop_role = _role_for_loop(user)

    await _store_run(run_id, {
        "run_id": run_id,
        "status": "queued",
        "plan_id": plan_id,
        "session_id": session_id,
        "mode": mode,
        "cli": cli,
        "prompt": body.prompt[:2000],
        "username": username,
        "role": loop_role,
        "tier": _tier_from_user(user),
        "created_at": time.time(),
        "events": [],
        "result": None,
        "cancel_requested": False,
    })

    asyncio.create_task(
        _execute_agent_run(
            run_id=run_id,
            prompt=body.prompt,
            mode=mode,
            cli=cli,
            plan_id=plan_id,
            session_id=session_id,
            username=username,
            role=loop_role,
            db_pool=getattr(request.app.state, "db_pool", None),
            max_turns=body.max_turns,
        )
    )
    return {
        "object": "agent.run",
        "run_id": run_id,
        "plan_id": plan_id,
        "session_id": session_id,
        "status": "queued",
        "mode": mode,
        "cli": cli,
        "role": loop_role,
    }


async def _execute_agent_run(
    *,
    run_id: str,
    prompt: str,
    mode: str,
    cli: str,
    plan_id: str,
    session_id: str,
    username: str,
    role: str,
    db_pool,
    max_turns: Optional[int],
) -> None:
    global _ACTIVE_RUNS
    await _update_run(run_id, status="running", started_at=time.time())
    events: List[Dict[str, Any]] = []

    async def emit(msg: Dict[str, Any]) -> None:
        events.append({
            "type": msg.get("type"),
            "detail": msg.get("detail") or msg.get("tool_name"),
            "status": msg.get("status"),
            "ts": time.time(),
        })
        if len(events) > 200:
            del events[:50]
        await _update_run(run_id, events=list(events[-100:]))

    try:
        async with _RUN_SEMAPHORE:
            run = await _get_run(run_id)
            if run and run.get("cancel_requested"):
                await _update_run(
                    run_id,
                    status="cancelled",
                    completed_at=time.time(),
                    events=list(events[-100:]),
                )
                return
            from app.websocket.cli_chat_handler import run_agentic_loop
            result = await run_agentic_loop(
                user_message=prompt,
                mode=mode,
                cli_type=cli,
                plan_id=plan_id,
                session_id=session_id,
                admin_username=username,
                user_role=role,
                db_pool=db_pool,
                emit=emit,
                max_turns_override=max_turns,
                allow_subagents=True,
                is_subagent=False,
            )
            run = await _get_run(run_id)
            if run and run.get("cancel_requested"):
                status = "cancelled"
            else:
                status = "failed" if result.get("status") == "error" else "completed"
            await _update_run(
                run_id,
                status=status,
                result=result,
                completed_at=time.time(),
                events=list(events[-100:]),
            )
    except Exception as e:
        logger.exception("Agent run %s failed: %s", run_id, e)
        await _update_run(
            run_id,
            status="failed",
            error=str(e)[:800],
            completed_at=time.time(),
            events=list(events[-100:]),
        )
    finally:
        async with _ACTIVE_GUARD:
            _ACTIVE_RUNS = max(0, _ACTIVE_RUNS - 1)


@router.get("/agents/{run_id}")
async def get_agent_run(run_id: str, user: Dict = Depends(_verify_proxy_auth)):
    run = await _get_run(run_id)
    if not run:
        raise HTTPException(404, "Agent run not found")
    out = dict(run)
    # Trim large nested payloads for list-style GET
    result = out.get("result")
    if isinstance(result, dict):
        out["result"] = {
            "status": result.get("status"),
            "turn_count": result.get("turn_count"),
            "provider": result.get("provider"),
            "files": result.get("files"),
            "tool_calls": result.get("tool_calls"),
            "autonomy": result.get("autonomy"),
            "sandbox": result.get("sandbox"),
            "response_text": (result.get("response_text") or "")[:8000],
            "warning": result.get("warning"),
            "error": result.get("error"),
        }
    return {"object": "agent.run", **out}


@router.delete("/agents/{run_id}")
async def cancel_agent_run(run_id: str, user: Dict = Depends(_verify_proxy_auth)):
    """Request cancellation of a queued/running agent (soft cancel flag)."""
    run = await _get_run(run_id)
    if not run:
        raise HTTPException(404, "Agent run not found")
    if run.get("status") in ("completed", "failed", "cancelled"):
        return {"object": "agent.run", "run_id": run_id, "status": run.get("status")}
    await _update_run(run_id, cancel_requested=True, status="cancelling")
    return {"object": "agent.run", "run_id": run_id, "status": "cancelling"}


@router.post("/agents/{run_id}/promote")
async def promote_agent_run(
    run_id: str,
    body: AgentPromoteBody,
    user: Dict = Depends(_verify_proxy_auth),
):
    """Promote CLI-Cloud sandbox changes — bridge ADMIN only (not proxy key)."""
    # Proxy keys must not promote into the live tree
    if user.get("source") == "sovereign_proxy_key":
        raise HTTPException(
            403,
            "Promote requires bridge ADMIN auth (proxy key cannot promote)",
        )
    role = (user.get("role") or "").upper()
    if role != "ADMIN":
        raise HTTPException(403, "sandbox promote requires ADMIN role")
    run = await _get_run(run_id)
    if not run:
        raise HTTPException(404, "Agent run not found")
    if run.get("cli") != "cloud":
        raise HTTPException(400, "Only CLI-Cloud sandboxed runs can be promoted")
    plan_id = run.get("plan_id")
    if not plan_id:
        raise HTTPException(400, "Run has no plan_id")
    try:
        from app.websocket.cli_tools import _sandbox_promote_sync
        result = await asyncio.to_thread(_sandbox_promote_sync, plan_id, body.paths)
    except Exception as e:
        raise HTTPException(500, f"Promote failed: {e}") from e
    await _update_run(run_id, promoted=True, promote_result=result)
    return {"object": "agent.promote", "run_id": run_id, "plan_id": plan_id, **(result or {})}
