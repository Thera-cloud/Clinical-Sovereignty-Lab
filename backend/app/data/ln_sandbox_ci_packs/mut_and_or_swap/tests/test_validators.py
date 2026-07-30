from broken.validators import is_valid_age


def test_is_valid_age():
    assert is_valid_age(30) is True
    assert is_valid_age(-5) is False
    assert is_valid_age(200) is False
