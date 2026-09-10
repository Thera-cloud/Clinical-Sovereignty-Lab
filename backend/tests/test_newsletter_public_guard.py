"""Offline guards for the public Story Library / Dispatch subscribe route."""
from __future__ import annotations

from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def _load_guard():
    if "app" not in sys.modules:
        import types

        pkg = types.ModuleType("app")
        pkg.__path__ = [str(BACKEND / "app")]  # type: ignore[attr-defined]
        sys.modules["app"] = pkg
    if "app.newsletter" not in sys.modules:
        import types

        nl = types.ModuleType("app.newsletter")
        nl.__path__ = [str(BACKEND / "app" / "newsletter")]  # type: ignore[attr-defined]
        sys.modules["app.newsletter"] = nl
        sys.modules["app"].newsletter = nl  # type: ignore[attr-defined]
    path = BACKEND / "app" / "newsletter" / "public_guard.py"
    spec = importlib.util.spec_from_file_location("app.newsletter.public_guard", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["app.newsletter.public_guard"] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_unsubscribe_html_rejects_xss_token():
    g = _load_guard()
    html = g.unsubscribe_confirm_html('"><script>alert(1)</script>', '"><script>')
    assert "<script>" not in html
    assert "alert(1)" not in html
    assert "&quot;" in g.html_attr('"><img')


def test_unsubscribe_html_drops_non_uuid_sid():
    g = _load_guard()
    html = g.unsubscribe_confirm_html("a" * 32, "not-a-uuid")
    assert 'name="sid"' not in html


def test_safe_http_url_rejects_javascript_and_unknown_hosts():
    g = _load_guard()
    assert g.safe_http_url("javascript:alert(1)") == ""
    assert g.safe_http_url('https://evil.example/"onerror=alert(1)') == ""
    assert (
        g.safe_http_url(
            "https://evil.example/x.png",
            require_known_host=True,
        )
        == ""
    )
    ok = "https://api.sovereignsanctuary.net/api/newsletter/library/demo/hero"
    assert g.safe_http_url(ok, require_known_host=True) == ok


def test_utm_source_and_slug_sanitizers():
    g = _load_guard()
    assert g.sanitize_utm("squarespace") == "squarespace"
    assert g.sanitize_utm("x<script>") is None
    assert g.sanitize_source("story_library") == "story_library"
    assert g.sanitize_source("admin") == "web"
    assert g.sanitize_ref("20260101-ok") == "20260101-ok"
    assert g.sanitize_ref("../etc/passwd") is None
    assert g.sanitize_share_channel("facebook") == "facebook"
    assert g.sanitize_share_channel("https://evil") == "link"


def test_honeypot_and_memory_rate_limit():
    g = _load_guard()
    assert g.honeypot_tripped("http://spam") is True
    assert g.honeypot_tripped("  ") is False
    key = "ut-mem-rl"
    g._mem_hits.pop(key, None)
    assert g.memory_over_limit(key, 2, 60) is False
    assert g.memory_over_limit(key, 2, 60) is False
    assert g.memory_over_limit(key, 2, 60) is True


def test_hero_img_tag_strips_javascript():
    path = BACKEND / "app" / "services" / "newsletter_delivery.py"
    spec = importlib.util.spec_from_file_location("nl_delivery_hero_xss", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nl_delivery_hero_xss"] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    bad = mod._hero_img_tag({"hero_image_url": "javascript:alert(1)", "slug": "x"})
    assert bad == ""
    good = mod._hero_img_tag(
        {
            "hero_image_url": "https://api.example/api/newsletter/library/demo/hero",
            "slug": "demo",
            "topic": "steadiness",
        }
    )
    assert "<img " in good
    assert "javascript:" not in good
