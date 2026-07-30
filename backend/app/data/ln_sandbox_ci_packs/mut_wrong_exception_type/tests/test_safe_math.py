from broken.safe_math import safe_div


def test_safe_div_zero():
    assert safe_div(10, 2) == 5
    assert safe_div(10, 0) is None
