from broken.dashboard import embed_hive, looks_fixed


def test_native_tab():
    assert looks_fixed(embed_hive())
