from broken.bridge import serve_kwargs, looks_fixed


def test_ping_timeout():
    assert looks_fixed(serve_kwargs())
