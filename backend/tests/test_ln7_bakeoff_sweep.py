"""Offline unit tests for LN7 bakeoff sweeper recommend logic (no router import)."""


def _bakeoff_recommend_refire(*, in_flight, n, expected_packs, outcomes_age_s, stale_outcomes_s):
    # Mirror app.routers.ln7_api._bakeoff_recommend_refire
    if in_flight or n >= expected_packs:
        return False
    if outcomes_age_s is None:
        return True
    return outcomes_age_s >= stale_outcomes_s


def test_recommend_refire_when_idle_and_short():
    assert _bakeoff_recommend_refire(
        in_flight=False, n=3, expected_packs=18, outcomes_age_s=900, stale_outcomes_s=600
    )


def test_no_recommend_while_in_flight():
    assert not _bakeoff_recommend_refire(
        in_flight=True, n=3, expected_packs=18, outcomes_age_s=900, stale_outcomes_s=600
    )


def test_no_recommend_when_complete():
    assert not _bakeoff_recommend_refire(
        in_flight=False, n=18, expected_packs=18, outcomes_age_s=900, stale_outcomes_s=600
    )


def test_recommend_when_no_outcomes_yet():
    assert _bakeoff_recommend_refire(
        in_flight=False, n=0, expected_packs=18, outcomes_age_s=None, stale_outcomes_s=600
    )


def test_no_recommend_when_outcomes_fresh():
    assert not _bakeoff_recommend_refire(
        in_flight=False, n=5, expected_packs=18, outcomes_age_s=30, stale_outcomes_s=600
    )
