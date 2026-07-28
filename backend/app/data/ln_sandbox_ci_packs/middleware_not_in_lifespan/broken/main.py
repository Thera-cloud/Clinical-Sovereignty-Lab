"""Broken — middleware registered inside lifespan."""

PHASE = "lifespan"

def add_middleware_phase() -> str:
    # BUG: Starlette forbids middleware after start
    return PHASE

def looks_fixed(phase: str) -> bool:
    return phase == "module"
