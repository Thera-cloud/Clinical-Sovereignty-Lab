"""T1.MIG — 301 map covers live Squarespace URLs; SSR has T0.2 + JSON-LD."""

import json
from pathlib import Path

from app.services.disco.brand import (
    PAGES,
    REDIRECTS,
    SQUARESPACE_PATHS,
    TITLE,
    homepage_jsonld,
    homepage_seo_packet,
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


def _empty_strings(obj, path="$"):
    found = []
    if obj == "":
        found.append(path)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            found.extend(_empty_strings(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found.extend(_empty_strings(v, f"{path}[{i}]"))
    return found


def test_homepage_jsonld_fills_bing_gaps_without_clinical_types():
    ld = homepage_jsonld()
    assert _empty_strings(ld) == []
    types = {n["@type"] for n in ld["@graph"]}
    assert types == {"WebSite", "Organization", "ProfessionalService"}
    assert "LocalBusiness" not in types
    for banned in ("Counselor", "Therapist", "Psychotherapist", "LocalBusiness"):
        assert banned not in types
    site = next(n for n in ld["@graph"] if n["@type"] == "WebSite")
    svc = next(n for n in ld["@graph"] if n["@type"] == "ProfessionalService")
    assert site["description"]
    assert svc["serviceType"] == "Life coach"
    assert svc["areaServed"] == "Detroit, MI, USA"
    assert DiscoEngine().org_schema() == ld
    assert DiscoEngine().validate_jsonld(ld)["ok"] is True


def test_homepage_seo_packet_squarespace_and_gbp():
    pkt = homepage_seo_packet()
    assert pkt["gbp"]["hide_address"] is True
    assert pkt["gbp"]["onsite_services"] is False
    assert pkt["gbp"]["primary_category"] == "Life coach"
    assert "LocalBusiness" in pkt["do_not_emit"]
    assert "application/ld+json" in pkt["squarespace"]["code_injection_header"]
    html = render_brand_page("/")
    assert html.count("<h1>") == 1
    assert "og:description" in html


def test_sitemap_lists_ssr_pages_only():
    xml = sitemap_xml()
    assert "/new-page" not in xml
    assert "/cart" not in xml
    assert "/safety" in xml
    assert "/pricing" in xml
