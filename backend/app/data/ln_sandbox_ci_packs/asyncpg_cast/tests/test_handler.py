from broken.handler import build_token_balance_sql, looks_fixed


def test_sql_has_explicit_int_cast():
    sql = build_token_balance_sql()
    assert looks_fixed(sql), f"expected ::int cast in SQL, got: {sql}"
