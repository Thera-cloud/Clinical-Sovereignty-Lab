from broken.checks import is_zero


def test_is_zero():
    assert is_zero(0) is True
    assert is_zero(0.0) is True
    assert is_zero(1000 - 1000) is True
