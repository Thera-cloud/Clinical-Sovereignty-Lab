from broken.auditor import is_trusted, looks_fixed


def test_trusted_codes():
    assert looks_fixed(is_trusted)
