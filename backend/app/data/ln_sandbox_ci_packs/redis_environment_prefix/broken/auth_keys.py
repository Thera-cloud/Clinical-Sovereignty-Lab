"""Broken — ENVIRONMENT mismatch breaks REST auth."""

def token_key(env: str, token: str) -> str:
    # BUG: hardcodes development while bridge uses production
    return f"nate:development:auth:{token}"

def looks_fixed(key: str) -> bool:
    return key.startswith("nate:") and ":development:" not in key
