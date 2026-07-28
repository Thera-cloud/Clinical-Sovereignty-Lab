from broken.config import load_settings_call, looks_fixed


def test_no_override_true():
    assert looks_fixed(load_settings_call())
