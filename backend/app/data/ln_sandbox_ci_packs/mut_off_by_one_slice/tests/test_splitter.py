from broken.splitter import first_half


def test_first_half():
    assert first_half([1, 2, 3, 4]) == [1, 2]
    assert first_half([1, 2, 3, 4, 5]) == [1, 2]
