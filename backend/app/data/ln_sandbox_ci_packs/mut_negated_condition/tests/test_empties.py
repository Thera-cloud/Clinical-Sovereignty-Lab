from broken.empties import is_empty


def test_is_empty():
    assert is_empty([]) is True
    assert is_empty([1]) is False
