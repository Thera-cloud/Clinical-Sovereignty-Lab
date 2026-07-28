"""Broken — override=True clobbers Docker env."""

def load_settings_call() -> str:
    # BUG: override=True wipes REDIS_HOST from compose
    return "load_dotenv(override=True)"

def looks_fixed(s: str) -> bool:
    return "override=True" not in s.replace(" ", "") and "load_dotenv" in s
