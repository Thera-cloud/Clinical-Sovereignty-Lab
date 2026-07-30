from broken.stats import average


def test_average():
    assert average(3, 4) == 3.5
    assert average(10, 10) == 10
