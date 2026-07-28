from broken.login import login_payload, looks_fixed


def test_expected_role():
    assert looks_fixed(login_payload("u", "p", "COACH"))
