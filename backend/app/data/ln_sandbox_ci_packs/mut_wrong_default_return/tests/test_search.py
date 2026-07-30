from broken.search import find_index


def test_find_index_not_found():
    assert find_index([1, 2, 3], 2) == 1
    assert find_index([1, 2, 3], 99) == -1
