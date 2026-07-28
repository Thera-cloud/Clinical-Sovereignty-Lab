from broken.activity import insert_activity_sql, looks_fixed


def test_column_names():
    assert looks_fixed(insert_activity_sql())
