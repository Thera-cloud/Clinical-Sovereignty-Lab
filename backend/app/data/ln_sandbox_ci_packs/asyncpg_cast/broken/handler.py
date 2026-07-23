"""Broken on purpose — sandbox CI pack (asyncpg cast)."""


def build_token_balance_sql() -> str:
    # BUG: asyncpg cannot infer polymorphic type for to_jsonb($1)
    return (
        "UPDATE users SET profile_data = jsonb_set("
        "profile_data, '{token_balance}', to_jsonb($1))"
    )


def looks_fixed(sql: str) -> bool:
    """Judge helper used by pack tests (not production code)."""
    s = sql.lower().replace(" ", "")
    return "to_jsonb($1::int)" in s or "to_jsonb(($1)::int)" in s
