from broken.billing import reset_usage_sql, looks_fixed


def test_jsonb_set():
    assert looks_fixed(reset_usage_sql())
