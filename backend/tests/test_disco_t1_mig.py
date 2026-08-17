"""T1.MIG — 301 map covers live Squarespace URLs; SSR has T0.2 + JSON-LD."""

import json
from pathlib import Path

from app.services.disco.brand import (
    PAGES,
    REDIRECTS,
    SQUARESPACE_PATHS,
    TITLE,
    render_brand_page,
    sitemap_xml,
)
from app.services.disco.engine import DiscoEngine
from app.services.disco.surfaces import CANONICAL_POSITIONING

REDIRECTS_FILE = Path(__file__).resolve().parents[2] / "public" / "disco" / "brand" / "redirects.json"


def test_every_squarespace_path_has_a_301_or_200_target():
    on_disk = json.loads(REDIRECTS_FILE.read_text())
    assert on_disk == REDIRECTS
    missing = [p for p in SQUARESPACE_PATHS if p not in REDIRECTS]
    assert missing == []
    for src, dest in REDIRECTS.items():
        assert dest in PAGES, f"{src} → {dest} has no SSR page"


def test_cart_retired_to_pricing():
    assert REDIRECTS["/cart"] == "/pricing"
    assert REDIRECTS["/new-page"] == "/safety"


def test_ssr_home_has_t02_and_valid_jsonld():
    html = render_brand_page("/")
    assert TITLE in html
    assert CANONICAL_POSITIONING in html
    assert "Sentient IP Quantum AI" not in html
    assert "healing, finally made possible" not in html
    eng = DiscoEngine()
    ld_ok = eng.validate_jsonld(
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "Sovereign Sanctuary",
        }
    )
    assert ld_ok["ok"]
    gate = eng.crawlability_gate(html)
    assert gate["has_jsonld"] and gate["has_body"] and gate["has_app_js"] is False
    assert "ss-crisis" in html


def test_sitemap_lists_ssr_pages_only():
    xml = sitemap_xml()
    assert "/new-page" not in xml
    assert "/cart" not in xml
    assert "/safety" in xml
    assert "/pricing" in xml
