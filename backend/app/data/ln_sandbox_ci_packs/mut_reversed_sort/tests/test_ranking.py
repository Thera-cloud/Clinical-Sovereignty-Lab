from broken.ranking import top_n


def test_top_n():
    assert top_n([5, 1, 9, 3], 2) == [9, 5]
    assert top_n([1, 2, 3], 1) == [3]
