"""Broken on purpose — ENVIRONMENT mismatch breaks REST auth."""
from typing import Optional

# BUG: local-dev default leaks into Docker "production" containers
DEFAULT_ENVIRONMENT = "development"


def redis_auth_key(token: str, environment: Optional[str] = None) -> str:
    env = environment or DEFAULT_ENVIRONMENT
    return f"nate:{env}:auth:{token}"


def production_ready() -> bool:
    return DEFAULT_ENVIRONMENT == "production"
