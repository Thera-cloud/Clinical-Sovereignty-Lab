"""Offline tests for LinkedIn 14-post campaign executor."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.services.linkedin_campaign_executor import (
    CAMPAIGN_SIGNATURE,
    ORIG_THEME_POOL,
    PERS_THEME_POOL,
    TZ,
    build_slot_schedule,
    ensure_signature,
    in_post_window,
    message_looks_like_restart,
    parse_campaign_config,
    parse_cur_sources,
    parse_start_date,
    pick_theme,
    slot_key,
)


def pick_orig_theme(slot_index: int, batch_number: int) -> str:
    return pick_theme(ORIG_THEME_POOL, slot_index, batch_number, [])


def pick_pers_theme(slot_index: int, batch_number: int) -> str:
    return pick_theme(PERS_THEME_POOL, slot_index, batch_number, [])


def test_fourteen_slots_50_30_20_mix():
    slots = build_slot_schedule(date(2026, 6, 25))
    assert len(slots) == 14
    lanes = [s["lane"] for s in slots]
    assert lanes.count("CUR") == 7
    assert lanes.count("ORIG") == 4
    assert lanes.count("PERS") == 3


def test_slot_times_3pm_and_8pm_eastern():
    slots = build_slot_schedule(date(2026, 6, 25))
    local_hours = set()
    for s in slots:
        assert "EDT" in s["local_label"] or "EST" in s["local_label"]
        if s["lane"] == "CUR":
            assert s["slot_key"].endswith("_1500")
        if s["lane"] in ("ORIG", "PERS"):
            assert s["slot_key"].endswith("_2000")
        local_hours.add(s["slot_key"].split("_")[1])
    assert local_hours == {"1500", "2000"}


def test_ensure_signature_appends_once():
    text = "Hello world."
    out = ensure_signature(text)
    assert CAMPAIGN_SIGNATURE in out
    assert out.count(CAMPAIGN_SIGNATURE) == 1
    assert "Nathaniel Nevedal" in out


def test_ensure_signature_legacy_not_duplicated():
    legacy = "Post body.\n\nNathaniel reviewed + approved — Little Nate, your AI companion"
    out = ensure_signature(legacy)
    assert out == legacy
    assert out.count("reviewed + approved") == 1


def test_parse_cur_sources_url_and_search():
    msg = """
    Day 1 3pm CUR: https://www.apa.org/monitor/example
    Day 2 3pm: search up digital mental health guidelines 2024
    """
    sources = parse_cur_sources(msg)
    assert sources[slot_key(1, 15, 0)] == "https://www.apa.org/monitor/example"
    assert "digital mental health" in sources[slot_key(2, 15, 0)]


def test_parse_start_date_iso():
    assert parse_start_date("start date: 2026-07-01") == date(2026, 7, 1)


def test_batch_two_orig_themes_differ_from_batch_one():
    batch_one = [pick_orig_theme(i, 1) for i in range(4)]
    batch_two = [pick_orig_theme(i, 2) for i in range(4)]
    assert batch_one != batch_two
    assert len(set(batch_one)) == 4


def test_batch_two_pers_themes_differ_from_batch_one():
    batch_one = [pick_pers_theme(i, 1) for i in range(3)]
    batch_two = [pick_pers_theme(i, 2) for i in range(3)]
    assert batch_one != batch_two
    assert len(set(batch_one)) == 3


def test_theme_pools_large_enough_for_multiple_campaigns():
    assert len(ORIG_THEME_POOL) >= 8
    assert len(PERS_THEME_POOL) >= 6


def test_parse_personal_not_company_destination():
    cfg = parse_campaign_config(
        "Restart the LinkedIn campaign on my personal page, not the company page, "
        "2 posts a day at 3pm and 8pm."
    )

    assert cfg.post_as == "person"
    assert cfg.posts_per_day == 2
    assert cfg.post_times == [15, 20]


def test_parse_both_destinations_when_explicit():
    cfg = parse_campaign_config(
        "Queue this LinkedIn campaign to both my personal profile and the company page."
    )

    assert cfg.post_as == "both"


def test_message_looks_like_restart():
    assert message_looks_like_restart("restart the LinkedIn campaign")
    assert message_looks_like_restart("Restart campaign with 2 posts per day")
    assert not message_looks_like_restart("approve campaign and proceed")
    assert not message_looks_like_restart("post #1 now")


def test_parse_start_date_today():
    today = date.today()
    assert parse_start_date("starting today") == today


def test_in_post_window_first_fifteen_minutes_eastern():
    inside = datetime(2026, 6, 30, 15, 10, tzinfo=TZ)
    outside_hour = datetime(2026, 6, 30, 20, 5, tzinfo=TZ)
    outside_minute = datetime(2026, 6, 30, 15, 20, tzinfo=TZ)

    assert in_post_window(inside, 15) is True
    assert in_post_window(outside_hour, 15) is False
    assert in_post_window(outside_minute, 15) is False
    assert in_post_window(datetime(2026, 6, 30, 20, 0, tzinfo=TZ), 20) is True


def test_publish_scheduled_slots_catchup_outside_window():
    """Overdue slots publish on scheduler ticks outside the 15-minute ET window."""
    assert in_post_window(datetime(2026, 6, 30, 20, 16, tzinfo=TZ), 20) is False
    assert in_post_window(datetime(2026, 6, 30, 15, 16, tzinfo=TZ), 15) is False
