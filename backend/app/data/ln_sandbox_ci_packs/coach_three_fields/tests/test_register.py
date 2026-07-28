from broken.register import new_client_profile, looks_fixed


def test_three_fields():
    assert looks_fixed(new_client_profile("COACH_X", "CoachX"))
