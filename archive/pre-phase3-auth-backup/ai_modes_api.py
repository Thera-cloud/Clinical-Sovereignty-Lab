"""
AI Modes API — Tri-Corder, Archivist, Guardian, Supervisor
Activate, deactivate, process data, and retrieve outputs for each AI mode.
"""

from fastapi import APIRouter, Depends, Request, HTTPException
from uuid import UUID
from typing import Dict, Any

from app.auth import get_current_user

router = APIRouter(
    prefix="/api/ai-modes",
    tags=["ai_modes"],
    dependencies=[Depends(get_current_user)],
)

# In-memory active mode sessions (session_id → mode instance)
_active_modes: Dict[str, Any] = {}


@router.get("/status")
async def ai_modes_status():
    """Return status of all active AI mode sessions."""
    return {
        "active_sessions": {
            sid: {"mode": m.MODE_NAME, "active": m._active}
            for sid, m in _active_modes.items()
        },
        "available_modes": ["tri_corder", "archivist", "guardian", "supervisor"],
    }


@router.post("/activate")
async def activate_mode(request: Request):
    """
    Activate an AI mode for a session.
    Body: {mode, session_id, user_id?, family_id?, minor_id?, guardian_id?, coach_id?}
    """
    body = await request.json()
    mode_name = body.get("mode")
    session_id = body.get("session_id")

    if not mode_name or not session_id:
        raise HTTPException(400, "mode and session_id are required")

    from app.services.ai_modes import get_ai_mode

    db = request.app.state.db_pool
    mode = get_ai_mode(mode_name, db_pool=db)

    kwargs = {}
    for key in ("user_id", "family_id", "minor_id", "guardian_id", "coach_id"):
        val = body.get(key)
        if val:
            kwargs[key] = UUID(val) if isinstance(val, str) else val

    result = await mode.activate(
        session_id=UUID(session_id) if isinstance(session_id, str) else session_id,
        **kwargs,
    )
    _active_modes[session_id] = mode
    return result


@router.post("/process/{session_id}")
async def process_mode_data(session_id: str, request: Request):
    """
    Send data to an active AI mode session.
    Body varies by mode (biometrics for tri_corder, text for archivist, etc.)
    """
    mode = _active_modes.get(session_id)
    if not mode or not mode._active:
        raise HTTPException(404, "No active AI mode for this session")

    body = await request.json()
    return await mode.process(body)


@router.post("/output/{session_id}")
async def get_mode_output(session_id: str):
    """Generate final output/report from an active AI mode session."""
    mode = _active_modes.get(session_id)
    if not mode:
        raise HTTPException(404, "No AI mode session found")

    result = await mode.generate_output()
    return result


@router.post("/deactivate/{session_id}")
async def deactivate_mode(session_id: str):
    """Deactivate an AI mode session."""
    mode = _active_modes.get(session_id)
    if not mode:
        raise HTTPException(404, "No AI mode session found")

    result = mode.deactivate()
    del _active_modes[session_id]
    return result
