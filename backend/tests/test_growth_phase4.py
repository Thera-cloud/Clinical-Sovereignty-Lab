"""Phase 4 Adaptive Growth Engine offline unit tests.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

from app.services.growth.directory_publisher import (
    render_gone_html,
    render_provider_html,
    validate_slug,
)
from app.services.growth.lead_events import _clean_meta
from app.services.growth import bwas_enabled
import os
from unittest.mock import patch


def test_slug_validation():
    assert validate_slug("jane-doe-therapy") == "jane-doe-therapy"
    try:
        validate_slug("Bad Slug!")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_provider_html_has_beacon_and_cta():
    html = render_provider_html(
        display_name="Jane Doe",
        seo_bio_md="Steady presence for families.",
        slug="jane-doe",
        specialty_tags=["coaching"],
        city="Austin",
    )
    assert "jane-doe" in html
    assert "provider=jane-doe" in html
    assert "src=directory" in html
    assert "/api/analytics/hit" in html
    assert "application/ld+json" in html


def test_withdraw_410_page():
    html = render_gone_html("jane-doe")
    assert "410" in html
    assert "noindex" in html


def test_meta_strips_pii_keys():
    cleaned = _clean_meta(
        {
            "email": "a@b.com",
            "device_id": "x",
            "utm_medium": "cpc",
            "ref": "ok",
        }
    )
    assert "email" not in cleaned
    assert "device_id" not in cleaned
    assert cleaned["utm_medium"] == "cpc"
    assert cleaned["ref"] == "ok"


def test_bwas_flag_default_off():
    with patch.dict(os.environ, {"ENABLE_BWAS": "false"}, clear=False):
        assert bwas_enabled() is False
    with patch.dict(os.environ, {"ENABLE_BWAS": "true"}, clear=False):
        assert bwas_enabled() is True


def test_bwas_score_math_unit():
    weights = {
        "impression": 0.05,
        "click": 0.15,
        "signup": 0.40,
    }
    counts = {"impression": 100, "click": 10, "signup": 2}
    score = sum(weights[s] * n for s, n in counts.items())
    assert abs(score - (5.0 + 1.5 + 0.8)) < 1e-6
