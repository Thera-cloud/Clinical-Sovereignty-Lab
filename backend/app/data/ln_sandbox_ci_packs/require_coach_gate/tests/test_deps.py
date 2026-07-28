from broken.deps import auth_dependency, looks_fixed


def test_coach_dep():
    assert looks_fixed(auth_dependency())
