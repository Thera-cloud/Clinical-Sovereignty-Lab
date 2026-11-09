"""Offline tests for the panel-of-the-day resolver (pure chooser + fake-db path)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.sse.panel_of_the_day import (
    SOURCE_DELIVERY,
    SOURCE_JOURNEY,
    STALE_AFTER_DAYS,
    choose_panel_of_the_day,
    fetch_panel_row_by_id,
    resolve_panel_of_the_day,
)

NOW = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)


def _journey(days_ago: float, **extra):
    row = {
        "panel_id": "11111111-1111-1111-1111-111111111111",
        "panel_type": "journey",
        "r2_url": "https://r2/j.png",
        "narrative_text": "journey scene",
        "biome": "drift_valley",
        "character_manifest": "Scribe",
        "panel_tone": "calm",
        "crystal_domains_used": None,
        "generated_at": NOW - timedelta(days=days_ago),
        "panel_metadata": None,
        "region": "origin",
    }
    row.update(extra)
    return row


def _delivery(days_ago: float, **extra):
    row = {
        "panel_id": "22222222-2222-2222-2222-222222222222",
        "generation_type": "daily_panel",
        "r2_url": "https://r2/d.png",
        "client_narrative_text": "daily panel scene",
        "storyboard_id": "the_father_and_broken_sons",
        "generated_at": NOW - timedelta(days=days_ago),
    }
    row.update(extra)
    return row


def test_none_when_nothing():
    assert choose_panel_of_the_day(None, None, now=NOW) is None


def test_journey_today_wins_over_delivery_today():
    p = choose_panel_of_the_day(_journey(0.1), _delivery(0.05), now=NOW)
    assert p["source_type"] == SOURCE_JOURNEY
    assert p["is_today"] is True and p["is_stale"] is False


def test_delivery_today_beats_old_journey():
    """The Lisa case: journey still frozen for months, daily panel minted today."""
    p = choose_panel_of_the_day(_journey(97), _delivery(0.2), now=NOW)
    assert p["source_type"] == SOURCE_DELIVERY
    assert p["is_today"] is True
    assert p["is_stale"] is False
    assert p["biome"] == "the_father_and_broken_sons"
    assert p["storyboard_id"] == "the_father_and_broken_sons"
    assert p["narrative_text"] == "daily panel scene"
    assert p["panel_type"] == "daily_panel"
    assert p["panel_id"] == "22222222-2222-2222-2222-222222222222"


def test_newest_wins_when_neither_is_today_and_stale_flagged():
    p = choose_panel_of_the_day(_journey(5), _delivery(3), now=NOW)
    assert p["source_type"] == SOURCE_DELIVERY
    assert p["is_today"] is False
    assert p["is_stale"] is True
    assert p["age_days"] > STALE_AFTER_DAYS


def test_yesterday_is_not_stale():
    p = choose_panel_of_the_day(_journey(1.2), None, now=NOW)
    assert p["is_today"] is False
    assert p["is_stale"] is False


def test_rows_without_url_are_ignored():
    p = choose_panel_of_the_day(_journey(0.1, r2_url=""), _delivery(0.5), now=NOW)
    assert p["source_type"] == SOURCE_DELIVERY
    assert choose_panel_of_the_day(_journey(0.1, r2_url=None), _delivery(0.5, r2_url=""), now=NOW) is None


def test_naive_timestamps_are_treated_as_utc():
    j = _journey(0.1)
    j["generated_at"] = j["generated_at"].replace(tzinfo=None)
    p = choose_panel_of_the_day(j, None, now=NOW)
    assert p["is_today"] is True
    assert p["generated_at"].tzinfo is not None


def test_utc_day_boundary():
    late_yesterday = datetime(2026, 11, 8, 23, 50, tzinfo=timezone.utc)
    j = _journey(0)
    j["generated_at"] = late_yesterday
    p = choose_panel_of_the_day(j, None, now=NOW)
    assert p["is_today"] is False and p["is_stale"] is False


class _FakeDB:
    def __init__(self, journey=None, delivery=None, by_id=None):
        self.journey, self.delivery = journey, delivery
        self.by_id = by_id or {}
        self.calls = []

    async def fetchrow(self, sql, *args):
        self.calls.append(sql)
        if "FROM sse_panel_log" in sql and "panel_id = $1::uuid" in sql:
            return self.by_id.get(("journey", args[0]))
        if "FROM sse_delivery_generation_log" in sql and "log_id = $1::uuid" in sql:
            return self.by_id.get(("delivery", args[0]))
        if "FROM sse_panel_log" in sql:
            return self.journey
        if "FROM sse_delivery_generation_log" in sql:
            return self.delivery
        return None


@pytest.mark.asyncio
async def test_resolver_queries_both_tables_and_picks_delivery_today():
    db = _FakeDB(journey=_journey(97), delivery=_delivery(0.1))
    p = await resolve_panel_of_the_day(db, ["LetsGoLisa", "CLIENT_X_ID"], now=NOW)
    assert p["source_type"] == SOURCE_DELIVERY and p["is_today"]
    assert any("FROM sse_panel_log" in c for c in db.calls)
    assert any("FROM sse_delivery_generation_log" in c for c in db.calls)


@pytest.mark.asyncio
async def test_resolver_handles_empty_ids_and_none_db():
    assert await resolve_panel_of_the_day(None, ["x"]) is None
    assert await resolve_panel_of_the_day(_FakeDB(), []) is None


@pytest.mark.asyncio
async def test_fetch_by_id_falls_through_to_delivery_log():
    did = "22222222-2222-2222-2222-222222222222"
    db = _FakeDB(by_id={("delivery", did): _delivery(0.3)})
    p = await fetch_panel_row_by_id(db, did, ["u"])
    assert p and p["source_type"] == SOURCE_DELIVERY and p["panel_id"] == did
    assert await fetch_panel_row_by_id(db, "33333333-3333-3333-3333-333333333333", ["u"]) is None
