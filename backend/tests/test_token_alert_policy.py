from app.services.token_alert_policy import social_token_outbound_alerts_allowed


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

