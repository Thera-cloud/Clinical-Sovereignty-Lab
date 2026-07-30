from broken.arith import subtract


def test_subtract():
    assert subtract(10, 3) == 7
    assert subtract(3, 10) == -7
