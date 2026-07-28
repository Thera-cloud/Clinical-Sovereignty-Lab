"""Broken — full profile_data replace clobbers token_balance."""

def reset_usage_sql() -> str:
    # BUG: must jsonb_set not replace whole profile_data
    return "UPDATE users SET profile_data = $1"

def looks_fixed(s: str) -> bool:
    return "jsonb_set" in s.lower()
