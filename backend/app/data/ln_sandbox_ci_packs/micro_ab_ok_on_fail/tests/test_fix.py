from broken.fix import value, looks_fixed


def test_fixed():
    assert looks_fixed(value())
