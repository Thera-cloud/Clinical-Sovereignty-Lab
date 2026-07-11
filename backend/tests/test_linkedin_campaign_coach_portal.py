"""Offline tests — Coach Portal Acquisition verbatim LinkedIn campaign."""
from datetime import date

from app.services.linkedin_campaign_coach_portal import (
    POSTS,
    POST1_MAX_CHARS,
    POST2_MAX_CHARS,
    WEEKS,
    build_verbatim_slots,
    campaign_week_dates,
    first_tuesday_on_or_after,
    is_coach_portal_campaign_message,
    validate_post_text,
)


def test_detection_phrases():
    assert is_coach_portal_campaign_message("SKYEYE CAMPAIGN BRIEF — Coach Portal Acquisition")
    assert is_coach_portal_campaign_message("execute coach portal acquisition verbatim starting today")
    assert not is_coach_portal_campaign_message("random linkedin post idea")


def test_first_tuesday_from_friday():
    assert first_tuesday_on_or_after(date(2026, 7, 10)) == date(2026, 7, 14)


def test_five_week_tue_thu_rotation():
    dates = campaign_week_dates(date(2026, 7, 10))
    assert len(dates) == WEEKS
    assert dates[0] == date(2026, 7, 14)  # Tue
    assert dates[1] == date(2026, 7, 22)  # Wed
    assert dates[2] == date(2026, 7, 30)  # Thu
    assert dates[3].weekday() in (1, 2, 3)
    assert dates[4].weekday() in (1, 2, 3)


def test_ten_verbatim_slots_3pm_8pm():
    slots = build_verbatim_slots(date(2026, 7, 10))
    assert len(slots) == 10
    hours = [s["hour"] for s in slots]
    assert hours.count(15) == 5
    assert hours.count(20) == 5
    for s in slots:
        assert "EDT" in s["local_label"] or "EST" in s["local_label"]


def test_all_posts_pass_validation():
    for post in POSTS:
        errs = validate_post_text(
            post.text,
            max_chars=post.max_chars,
            extra_compliance=post.extra_compliance,
        )
        assert not errs, f"week {post.week} {post.slot}: {errs}"


def test_post_char_limits():
    for post in POSTS:
        limit = POST1_MAX_CHARS if post.slot == "post1" else POST2_MAX_CHARS
        assert len(post.text.strip()) <= limit, f"week {post.week} {post.slot} too long"


def test_post2_has_image_prompts():
    post2s = [p for p in POSTS if p.slot == "post2"]
    assert len(post2s) == 5
    for p in post2s:
        assert p.needs_image
        assert "#0A0A0A" in p.image_prompt
        assert "6 words" in p.image_prompt.lower()
