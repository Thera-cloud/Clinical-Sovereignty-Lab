"""Broken — coach endpoint gated admin-only."""

def auth_dependency() -> str:
    # BUG: coaches get 403 with require_admin
    return "Depends(require_admin)"

def looks_fixed(s: str) -> bool:
    return "require_coach" in s and "require_admin" not in s
