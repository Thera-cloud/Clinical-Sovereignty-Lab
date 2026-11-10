"""Offline mint-governor tests for crystal_factory.py (no DB / network)."""
from pathlib import Path

import crystal_factory as cf

_SRC = (Path(__file__).resolve().parents[1] / "crystal_factory.py").read_text(encoding="utf-8")


def test_interval_default_is_design_envelope_not_ten_seconds():
    assert cf.DEFAULT_HARVEST_INTERVAL_SEC == 1800
    assert cf.MIN_HARVEST_INTERVAL_SEC == 1800
    assert 'getenv("HARVEST_INTERVAL_SEC", "10")' not in _SRC
    assert cf.resolve_harvest_interval_sec(None) == 1800
    assert cf.resolve_harvest_interval_sec("10") == 1800
    assert cf.resolve_harvest_interval_sec("10", allow_fast=True) == 10
    assert cf.resolve_harvest_interval_sec("1800") == 1800
    assert cf.resolve_harvest_interval_sec("bogus") == 1800


def test_daily_and_domain_caps_block_coding_defense_firehose():
    assert cf.DEFAULT_DAILY_STORE_CAP == 96
    assert cf.DEFAULT_MAX_STORE_PER_CYCLE == 2
    assert cf.FACTORY_DOMAIN_DAILY_CAP["coding"] == 4
    assert cf.FACTORY_DOMAIN_DAILY_CAP["defense"] == 4
    assert cf.domain_mint_allowed("coding", 3) is True
    assert cf.domain_mint_allowed("coding", 4) is False
    assert cf.domain_mint_allowed("clinical", 23) is True
    assert cf.domain_mint_allowed("clinical", 24) is False
    assert cf.domain_mint_allowed("unknown_domain", 5) is True
    assert cf.domain_mint_allowed("unknown_domain", 6) is False


def test_governor_wired_before_stage2_and_counts_archived():
    assert "factory_mint_counts_today" in _SRC
    assert "origin_surface = 'crystal_factory'" in _SRC
    assert "Daily store cap" in _SRC
    assert "Domain cap skip" in _SRC
    assert "max_per_cycle" in _SRC
    assert 'FULL_HARVEST_EVERY_CYCLES", "1"' in _SRC
    assert "FACTORY_ALLOW_FAST" in _SRC
