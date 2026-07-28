"""Broken — empty dict fails auditor L2."""

def list_response() -> object:
    # BUG: {} is WARNING for auditors; use []
    return {}

def looks_fixed(v) -> bool:
    return isinstance(v, list)
