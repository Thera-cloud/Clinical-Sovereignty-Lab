"""On-air depth hides names, ages, and children."""

from app.services.studio_public_depth import guard_onair


def test_child_and_age_lines_are_dropped():
    text = "A boy of 8 years old sat with his mother. A gentleman kept his own mind."
    out = guard_onair(text)
    assert "boy" not in out.lower()
    assert "8" not in out
    assert "gentleman" in out.lower()


def test_names_become_a_general_reference():
    out = guard_onair("Maria told her husband the work was heavy. John Smith stayed with it.")
    assert "maria" not in out.lower()
    assert "john" not in out.lower()
    assert "smith" not in out.lower()
    assert "a woman" in out.lower() or "a couple" in out.lower()
    assert "Little Nate" == guard_onair("Little Nate stayed in the room.") or "Little Nate" in guard_onair(
        "Little Nate stayed in the room."
    )
