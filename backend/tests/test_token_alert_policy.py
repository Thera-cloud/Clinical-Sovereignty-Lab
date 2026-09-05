from app.services.token_alert_policy import (
    oauth_error_is_unresolvable,
    outage_already_alerted,
    social_token_outbound_alerts_allowed,
)
from datetime import datetime, timezone


def test_when_global_disabled_no_alerts_even_if_not_in_paused_list():
    assert not social_token_outbound_alerts_allowed(
        "linkedin",
        emails_enabled_globally=False,
        paused_platform_csv="",
    )


def test_when_paused_csv_contains_platform_alerts_blocked():
    assert not social_token_outbound_alerts_allowed(
        "x",
        emails_enabled_globally=True,
        paused_platform_csv="x,youtube",
    )
    assert not social_token_outbound_alerts_allowed(
        "linkedin",
        emails_enabled_globally=True,
        paused_platform_csv="LinkedIn ",
    )


def test_case_insensitive_pause_match():
    assert not social_token_outbound_alerts_allowed(
        "X",
        emails_enabled_globally=True,
        paused_platform_csv="x",
    )


def test_aliases_x_vs_x_twitter():
    assert not social_token_outbound_alerts_allowed(
        "x",
        emails_enabled_globally=True,
        paused_platform_csv="x_twitter",
    )
    assert not social_token_outbound_alerts_allowed(
        "x_twitter",
        emails_enabled_globally=True,
        paused_platform_csv="x",
    )


def test_unlisted_platform_allowed_when_csv_nonempty():
    assert social_token_outbound_alerts_allowed(
        "linkedin",
        emails_enabled_globally=True,
        paused_platform_csv="x",
    )


def test_global_enabled_empty_pause_allows_all():
    assert social_token_outbound_alerts_allowed(
        "x",
        emails_enabled_globally=True,
        paused_platform_csv="",
    )


def test_oauth_error_is_unresolvable():
    assert oauth_error_is_unresolvable(
        "Client application is not allowed for this operation."
    )
    assert oauth_error_is_unresolvable("not allowed for this operation")
    assert not oauth_error_is_unresolvable("invalid_grant")
    assert not oauth_error_is_unresolvable("")


def test_outage_already_alerted():
    earlier = datetime(2026, 9, 1, tzinfo=timezone.utc)
    later = datetime(2026, 9, 5, tzinfo=timezone.utc)
    assert outage_already_alerted(None, earlier) is False
    assert outage_already_alerted(later, None) is True
    assert outage_already_alerted(later, earlier) is True
    assert outage_already_alerted(earlier, later) is False

