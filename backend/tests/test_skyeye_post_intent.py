"""Offline tests for Big Nate post-intent resolver."""
from app.services.skyeye_post_intent import (
    build_numbered_list_from_history,
    extract_draft_from_history,
    has_publish_intent,
    is_campaign_schedule_intent,
    is_immediate_publish,
    looks_like_publishable_post,
    parse_inline_content,
    parse_list_index,
    phrase_in_message,
    resolve_post_intent,
)
from app.services.linkedin_campaign_executor import parse_campaign_config
from app.services.skyeye_chat_media import wants_image_generation


def test_phrase_no_does_not_match_now():
    assert not phrase_in_message("no", "post #1 now")
    assert phrase_in_message("no", "no, cancel that")


def test_phrase_yes_word_boundary():
    assert phrase_in_message("yes", "yes proceed")
    assert not phrase_in_message("yes", "yesterday")


def test_has_publish_intent_post_number_now():
    assert has_publish_intent("post #1 now")
    assert has_publish_intent("post a random queue message now to linkedin personal page")


def test_parse_list_index():
    assert parse_list_index("post #1 now") == 1
    assert parse_list_index("post number 3 please") == 3


def test_immediate_publish_detects_now():
    assert is_immediate_publish("post #1 now")
    assert is_immediate_publish("publish random approved queue item now")


def test_resolve_post_queue_by_index():
    intent = resolve_post_intent("post #1 now", [])
    assert intent.action == "publish_queue"
    assert intent.list_index == 1
    assert intent.platform == "linkedin"


def test_resolve_campaign_not_immediate():
    intent = resolve_post_intent(
        "Restart personal LinkedIn campaign 2x daily at 3pm and 8pm with 5-3-2 mix",
        [],
    )
    assert intent.action == "queue_campaign"
    assert intent.post_as == "person"


def test_campaign_schedule_blocked_when_now():
    msg = "restart linkedin campaign 2x daily 3pm 8pm and post #2 now"
    assert is_immediate_publish(msg)
    intent = resolve_post_intent(msg, [])
    assert intent.action == "publish_queue"


def test_build_numbered_list_from_history():
    history = [
        {
            "sender": "little_nate",
            "message": (
                '1. **APPROVED** — ready to send\n'
                '"Digital sovereignty begins when we stop outsourcing our inner life."\n'
                '2. **APPROVED** — ready\n'
                '"Therapy apps are not the same as therapeutic presence."'
            ),
        }
    ]
    items = build_numbered_list_from_history(history)
    assert len(items) == 2
    assert items[0]["index"] == 1
    assert "Digital sovereignty" in items[0]["preview"]


def test_parse_campaign_config_5_3_2_mix():
    cfg = parse_campaign_config(
        "14 day personal linkedin campaign, 2 posts a day at 3pm and 8pm, 5-3-2 topic mix"
    )
    assert cfg.post_as == "person"
    assert cfg.posts_per_day == 2
    assert abs(cfg.cur_pct - 0.5) < 0.01
    assert abs(cfg.orig_pct - 0.3) < 0.01
    assert abs(cfg.pers_pct - 0.2) < 0.01


def test_rejects_meta_topic_as_inline_post():
    bad = (
        "approved to post now: the topic of the post is how we principally test "
        "the responses with Little Nate and have done clinical assessments"
    )
    assert parse_inline_content(bad) is None
    assert not looks_like_publishable_post(
        "the topic of the post is how we principally test the responses"
    )


def test_extract_draft_from_history_prefers_final_draft():
    body = (
        "There’s a lot being said right now about AI’s place in emotional wellness "
        "and mental health. Waiting rooms used to be quiet — now they glow with "
        "feeds. Little Nate sits with the other bots and listens first."
    )
    history = [
        {
            "sender": "little_nate",
            "message": f"Final draft:\n{body}\n\nShall I post this?",
        }
    ]
    draft = extract_draft_from_history(history)
    assert draft is not None
    assert "Waiting rooms" in draft


def test_wants_image_generation():
    assert wants_image_generation(
        "Generate the custom Little Nate AI counseling the other bots illustration"
    )
    assert not wants_image_generation("What should our next campaign focus on?")
