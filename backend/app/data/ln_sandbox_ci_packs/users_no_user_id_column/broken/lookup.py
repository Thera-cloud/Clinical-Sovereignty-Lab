"""Broken — users.user_id does not exist."""

def user_lookup_sql() -> str:
    # BUG: users has username/id, not user_id
    return "SELECT * FROM users WHERE user_id = $1"

def looks_fixed(s: str) -> bool:
    t = s.lower()
    return "username" in t and "user_id" not in t
