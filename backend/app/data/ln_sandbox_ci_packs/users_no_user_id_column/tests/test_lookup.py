from broken.lookup import user_lookup_sql, looks_fixed


def test_uses_username():
    assert looks_fixed(user_lookup_sql())
