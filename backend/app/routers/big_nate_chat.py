"""
SOVEREIGN SWARM — Big Nate Chat Router
Human–AI command interface implementing 5 conversation modes (Patent Claim 11).

Modes:
    1. Briefing — Synthesized intelligence briefings
    2. Strategy — Collaborative strategy development and proposal creation
    3. Command — Direct command issuance to the swarm
    4. Inquiry — Question-answer about swarm state, client progress, patterns
    5. Swarm — Real-time swarm oversight and fleet management
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.api_server import require_admin
from app.services.sovereign_mind import SovereignMind

router = APIRouter(
    prefix="/api/big-nate",
    tags=["Big Nate Chat"],
    dependencies=[Depends(require_admin)],
)

logger = structlog.get_logger(__name__)


# =============================================================================
# REQUEST / RESPONSE MODELS
# =============================================================================


class ChatMessage(BaseModel):
    """Input message for the main chat endpoint."""

    mode: str = Field(
        ...,
        description="Conversation mode: briefing | strategy | command | inquiry | swarm",
    )
    content: str = Field(..., description="Message content")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Optional context")


class ChatResponse(BaseModel):
    """Structured response from the Big Nate Chat."""

    mode: str = Field(..., description="Mode that produced this response")
    response_type: str = Field(..., description="Type of response (e.g. briefing, proposal)")
    content: Dict[str, Any] = Field(..., description="Response payload")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    follow_up_suggestions: List[str] = Field(default_factory=list)


class BriefingRequest(BaseModel):
    """Request for a focused intelligence briefing."""

    focus_areas: Optional[List[str]] = Field(
        default=None,
        description="Optional list of domains to emphasize",
    )


class ProposalRequest(BaseModel):
    """Request to create a strategy proposal."""

    objective: str = Field(..., min_length=1, description="Strategic objective")
    rationale: str = Field(..., min_length=1, description="Justification and reasoning")
    domain_tags: Optional[List[str]] = Field(
        default=None,
        description="Optional tags for categorization",
    )


class DirectiveRequest(BaseModel):
    """Request to issue a directive to the swarm."""

    target_fibre_ids: List[str] = Field(default_factory=list)
    target_fibre_types: List[str] = Field(default_factory=list)
    directive_type: str = Field(..., min_length=1)
    content: Dict[str, Any] = Field(default_factory=dict)
    priority: str = Field(default="normal", description="normal | high | critical")


class SpawnRequest(BaseModel):
    """Request to evaluate and spawn a new Fibre."""

    fibre_type: str = Field(..., min_length=1)
    justification: str = Field(..., min_length=1)
    domain: Optional[str] = None


# =============================================================================
# DEPENDENCY INJECTION
# =============================================================================


def get_sovereign_mind(request: Request) -> SovereignMind:
    """
    Return the globally-initialized SovereignMind from app state.

    Falls back to a minimal instance if the global one is unavailable
    (e.g. ENABLE_SOVEREIGN_SWARM is False).
    """
    mind = getattr(request.app.state, "sovereign_mind", None)
    if mind is not None:
        return mind
    # Fallback: create a minimal instance (stub behavior)
    db_pool = getattr(request.app.state, "db_pool", None)
    return SovereignMind(db_pool=db_pool, redis=None)


# =============================================================================
# MODE HANDLERS (used by /chat endpoint)
# =============================================================================


def _to_dict(value: Any) -> Dict[str, Any]:
    """Normalize SovereignMind returns (Pydantic models, dataclasses, dicts)
    into a plain ``Dict[str, Any]`` so they fit ``ChatResponse.content``."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    # Pydantic v2
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except TypeError:
            return dump()
    # Pydantic v1
    dump_v1 = getattr(value, "dict", None)
    if callable(dump_v1):
        try:
            return dump_v1()
        except Exception:
            pass
    # Dataclass / generic object
    try:
        from dataclasses import asdict, is_dataclass
        if is_dataclass(value):
            return asdict(value)
    except Exception:
        pass
    return {"value": str(value)}


async def _handle_briefing(
    sovereign_mind: SovereignMind,
    content: str,
    context: Optional[Dict[str, Any]],
) -> ChatResponse:
    """Route to Briefing Mode: synthesized intelligence briefings."""
    focus_areas = None
    if context and "focus_areas" in context:
        focus_areas = context.get("focus_areas")
    elif content and content.strip():
        # Parse focus areas from content if comma-separated
        focus_areas = [s.strip() for s in content.split(",") if s.strip()]
    result = await sovereign_mind.generate_briefing(focus_areas=focus_areas)
    return ChatResponse(
        mode="briefing",
        response_type="briefing",
        content=_to_dict(result),
        follow_up_suggestions=[
            "Expand on client risk signals",
            "Deep dive into coherence trends",
            "Review family patterns",
        ],
    )


async def _handle_strategy(
    sovereign_mind: SovereignMind,
    content: str,
    context: Optional[Dict[str, Any]],
) -> ChatResponse:
    """Route to Strategy Mode: proposals or synthesis."""
    # Check if content/context suggests a proposal
    proposal_hint = (
        context
        and isinstance(context.get("create_proposal"), dict)
    ) or (
        content.lower().startswith("create proposal")
        or "propose" in content.lower()
        or "strategy for" in content.lower()
    )
    if proposal_hint and context and context.get("create_proposal"):
        payload = context["create_proposal"]
        result = await sovereign_mind.generate_proposal(
            objective=payload.get("objective", content),
            rationale=payload.get("rationale", ""),
            domain_tags=payload.get("domain_tags"),
        )
    else:
        result = await sovereign_mind.generate_proposal(
            objective=content or "General strategy synthesis",
            rationale="Operator-initiated strategy discussion",
            domain_tags=context.get("domain_tags") if context else None,
        )
    return ChatResponse(
        mode="strategy",
        response_type="proposal",
        content=_to_dict(result),
        follow_up_suggestions=[
            "Refine the objective",
            "Add domain tags",
            "Request approval workflow",
        ],
    )


async def _handle_command(
    sovereign_mind: SovereignMind,
    content: str,
    context: Optional[Dict[str, Any]],
) -> ChatResponse:
    """Route to Command Mode: direct swarm directives."""
    result = await sovereign_mind.process_command(
        command=content or "",
        context=context or {},
    )
    return ChatResponse(
        mode="command",
        response_type="command_ack",
        content=_to_dict(result),
        follow_up_suggestions=[
            "Check command status",
            "View swarm overview",
            "Issue follow-up directive",
        ],
    )


async def _handle_inquiry(
    sovereign_mind: SovereignMind,
    content: str,
    context: Optional[Dict[str, Any]],
) -> ChatResponse:
    """Route to Inquiry Mode: question-answer about swarm/client/patterns."""
    inquiry_context = {
        "question": content,
        "intent": "inquiry",
        **(context or {}),
    }
    result = await sovereign_mind.process_command(
        command=content or "",
        context=inquiry_context,
    )
    return ChatResponse(
        mode="inquiry",
        response_type="inquiry_response",
        content=_to_dict(result),
        follow_up_suggestions=[
            "Ask a related question",
            "Request briefing",
            "View swarm overview",
        ],
    )


async def _handle_swarm(
    sovereign_mind: SovereignMind,
    content: str,
    context: Optional[Dict[str, Any]],
) -> ChatResponse:
    """Route to Swarm Mode: real-time fleet oversight."""
    result = await sovereign_mind.get_swarm_overview()
    return ChatResponse(
        mode="swarm",
        response_type="swarm_overview",
        content=_to_dict(result),
        follow_up_suggestions=[
            "Drill into specific Fibre",
            "Issue directive",
            "Request briefing",
        ],
    )


MODE_HANDLERS = {
    "briefing": _handle_briefing,
    "strategy": _handle_strategy,
    "command": _handle_command,
    "inquiry": _handle_inquiry,
    "swarm": _handle_swarm,
}


# =============================================================================
# REST ENDPOINTS
# =============================================================================


@router.post("/chat", response_model=ChatResponse)
async def chat(
    message: ChatMessage,
    sovereign_mind: SovereignMind = Depends(get_sovereign_mind),
) -> ChatResponse:
    """
    Main chat endpoint. Routes the message to the appropriate mode handler.

    Mode is parsed from ChatMessage.mode. Each mode formats the response
    differently via SovereignMind methods.
    """
    mode = (message.mode or "").lower().strip()
    if mode not in MODE_HANDLERS:
        logger.warning("big_nate_chat.unknown_mode", mode=mode, available=list(MODE_HANDLERS))
        raise HTTPException(
            status_code=400,
            detail=f"Unknown mode '{mode}'. Valid modes: {', '.join(MODE_HANDLERS)}",
        )
    try:
        handler = MODE_HANDLERS[mode]
        return await handler(
            sovereign_mind,
            message.content,
            message.context,
        )
    except Exception as e:
        logger.exception("big_nate_chat.handler_error", mode=mode)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/briefing")
async def get_briefing(
    focus_areas: Optional[str] = None,
    sovereign_mind: SovereignMind = Depends(get_sovereign_mind),
) -> Dict[str, Any]:
    """
    Get current intelligence briefing. Optional focus_areas as comma-separated query param.
    """
    areas = [s.strip() for s in focus_areas.split(",")] if focus_areas else None
    try:
        return await sovereign_mind.generate_briefing(focus_areas=areas)
    except Exception as e:
        logger.exception("big_nate_chat.briefing_error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/proposal")
async def create_proposal(
    request: ProposalRequest,
    sovereign_mind: SovereignMind = Depends(get_sovereign_mind),
) -> Dict[str, Any]:
    """Create a strategy proposal for operator review."""
    try:
        return await sovereign_mind.generate_proposal(
            objective=request.objective,
            rationale=request.rationale,
            domain_tags=request.domain_tags,
        )
    except Exception as e:
        logger.exception("big_nate_chat.proposal_error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/directive")
async def issue_directive(
    request: DirectiveRequest,
    sovereign_mind: SovereignMind = Depends(get_sovereign_mind),
) -> Dict[str, Any]:
    """Issue a directive to the swarm (target fibres or fibre types)."""
    cmd_content = {
        "target_fibre_ids": request.target_fibre_ids,
        "target_fibre_types": request.target_fibre_types,
        "directive_type": request.directive_type,
        "content": request.content,
        "priority": request.priority,
    }
    try:
        return await sovereign_mind.process_command(content=cmd_content)
    except Exception as e:
        logger.exception("big_nate_chat.directive_error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/swarm-overview")
async def get_swarm_overview(
    sovereign_mind: SovereignMind = Depends(get_sovereign_mind),
) -> Dict[str, Any]:
    """Get fleet overview for real-time swarm oversight."""
    try:
        return await sovereign_mind.get_swarm_overview()
    except Exception as e:
        logger.exception("big_nate_chat.swarm_overview_error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/spawn")
async def spawn_fibre(
    request: SpawnRequest,
    sovereign_mind: SovereignMind = Depends(get_sovereign_mind),
) -> Dict[str, Any]:
    """Evaluate and spawn a new Fibre. Returns approval status (stub may not actually spawn)."""
    try:
        return await sovereign_mind.evaluate_spawn(
            fibre_type=request.fibre_type,
            justification=request.justification,
            domain=request.domain,
        )
    except Exception as e:
        logger.exception("big_nate_chat.spawn_error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/modes")
async def list_modes() -> Dict[str, Any]:
    """
    List available conversation modes with descriptions for UI discovery.
    """
    return {
        "modes": [
            {
                "id": "briefing",
                "name": "Briefing Mode",
                "description": "Nate presents synthesized intelligence briefings.",
            },
            {
                "id": "strategy",
                "name": "Strategy Mode",
                "description": "Collaborative strategy development and proposal creation.",
            },
            {
                "id": "command",
                "name": "Command Mode",
                "description": "Direct command issuance to the swarm.",
            },
            {
                "id": "inquiry",
                "name": "Inquiry Mode",
                "description": "Question-answer about swarm state, client progress, patterns.",
            },
            {
                "id": "swarm",
                "name": "Swarm Mode",
                "description": "Real-time swarm oversight and fleet management.",
            },
        ],
    }
