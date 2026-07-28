from broken.auth_keys import token_key, looks_fixed


def test_env_prefix():
    assert looks_fixed(token_key("production", "abc"))
