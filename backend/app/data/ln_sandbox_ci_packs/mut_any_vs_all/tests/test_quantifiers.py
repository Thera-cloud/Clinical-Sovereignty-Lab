from broken.quantifiers import all_positive


def test_all_positive():
    assert all_positive([1, 2, 3]) is True
    assert all_positive([1, -2, 3]) is False
