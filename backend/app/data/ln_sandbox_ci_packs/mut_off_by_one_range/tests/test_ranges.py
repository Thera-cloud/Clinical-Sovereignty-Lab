from broken.ranges import sum_first_n


def test_sum_first_n():
    assert sum_first_n(1) == 1
    assert sum_first_n(5) == 15
    assert sum_first_n(10) == 55
