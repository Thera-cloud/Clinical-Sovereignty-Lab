from broken.auth_keys import DEFAULT_ENVIRONMENT, production_ready, redis_auth_key


def test_default_environment_is_production():
    assert DEFAULT_ENVIRONMENT == "production"
    assert production_ready()
    assert redis_auth_key("abc").startswith("nate:production:auth:")
