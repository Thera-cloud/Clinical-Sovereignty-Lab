from broken.config import get_setting


def test_get_setting_missing_key():
    assert get_setting({}, 'timeout', 30) == 30
    assert get_setting({'timeout': 5}, 'timeout', 30) == 5
