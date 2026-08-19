"""Offline gates: API + Flutter-web robots stay closed to crawlers."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_api_robots_disallow_all():
    text = (ROOT / "backend/app/routers/seo_public.py").read_text()
    assert "Disallow: /" in text
    assert "X-Robots-Tag" in text
    assert "noindex" in text


def test_app_web_robots_disallow():
    text = (ROOT / "mobile/web/robots.txt").read_text()
    assert "User-agent: *" in text
    assert "Disallow: /" in text
    assert "Sitemap:" not in text


def test_main_root_noindex():
    text = (ROOT / "backend/app/main.py").read_text()
    assert "seo_public" in text
    assert 'X-Robots-Tag": "noindex, nofollow"' in text or "X-Robots-Tag" in text
