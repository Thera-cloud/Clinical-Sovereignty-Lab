"""On-air depth hides names and ages. Family-table talk stays."""

from app.services.studio_public_depth import guard_onair


def test_child_and_age_lines_are_dropped():
    text = "A boy of 8 years old sat with his mother. A gentleman kept his own mind."
    out = guard_onair(text)
    assert "boy" not in out.lower()
    assert "8" not in out
    assert "gentleman" in out.lower()


def test_kid_without_age_stays_on_air():
    out = guard_onair("Yeah, the kid went quiet at the table. That's not disrespect.")
    low = out.lower()
    assert "quiet" in low
    assert "disrespect" in low
    assert "kid" in low
    assert "young person" not in low


def test_place_names_are_not_turned_into_a_gentleman():
    out = guard_onair("What's up Mike from Detroit, I got you loud and clear.")
    low = out.lower()
    assert "detroit" in low
    assert "caller" in low
    assert "mike" not in low
    assert "a gentleman" not in low


def test_instead_is_not_turned_into_a_gentleman():
    out = guard_onair(
        "I'd tell the dad to shift the vibe. Instead of pushing the kid to talk, ask something casual."
    )
    low = out.lower()
    assert "instead of pushing" in low
    assert "gentleman" not in low


def test_radio_openers_are_not_turned_into_a_gentleman():
    out = guard_onair("Man, hear me out, coaches on radio can talk family dinner.")
    low = out.lower()
    assert low.startswith("man,")
    assert "gentleman" not in low
    assert "coach" in guard_onair("Coach, hear me out on this one.").lower()
    assert "maybe" in guard_onair("Maybe the kid went quiet because he's scared.").lower()


def test_show_title_is_not_turned_into_a_gentleman():
    out = guard_onair(
        "What's up Mike from Detroit, you're calling in live on The Between Moments."
    )
    low = out.lower()
    assert "between moments" in low
    assert "detroit" in low
    assert "a gentleman" not in low


def test_names_become_a_general_reference():
    out = guard_onair("Maria told her husband the work was heavy. John Smith stayed with it.")
    assert "maria" not in out.lower()
    assert "john" not in out.lower()
    assert "smith" not in out.lower()
    assert "a woman" in out.lower() or "a couple" in out.lower()
    assert "Little Nate" == guard_onair("Little Nate stayed in the room.") or "Little Nate" in guard_onair(
        "Little Nate stayed in the room."
    )
