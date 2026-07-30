from broken.grader import passed_threshold


def test_passed_threshold_inclusive():
    assert passed_threshold(70, 70) is True
    assert passed_threshold(69, 70) is False
    assert passed_threshold(90, 70) is True
