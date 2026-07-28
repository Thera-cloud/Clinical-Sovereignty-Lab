from broken.main import add_middleware_phase, looks_fixed


def test_module_level():
    assert looks_fixed(add_middleware_phase())
