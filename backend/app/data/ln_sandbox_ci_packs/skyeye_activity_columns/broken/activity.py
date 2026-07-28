"""Broken — wrong skyeye_activity column names."""

def insert_activity_sql() -> str:
    # BUG: columns are type, content, created_at
    return "INSERT INTO skyeye_activity (action, details, timestamp) VALUES ($1,$2,$3)"

def looks_fixed(s: str) -> bool:
    t = s.lower()
    return "type" in t and "content" in t and "created_at" in t and "action" not in t
