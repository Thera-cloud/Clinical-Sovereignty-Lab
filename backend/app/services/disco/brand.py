"""T1.MIG brand SSR — T0.2 copy, zero application JS. DNS not flipped here."""

from __future__ import annotations

import json

from app.services.disco.surfaces import CANONICAL_POSITIONING

BRAND_ORIGIN = "https://www.sovereignsanctuary.net"

# Live Squarespace sitemap 2026-08-16 + nav extras (cart, root, clinical-safety alias).
SQUARESPACE_PATHS = (
    "/",
    "/home",
    "/about",
    "/our-team",
    "/new-page",
    "/clinical-safety",
    "/contact",
    "/thera-world",
    "/pricing",
    "/videos",
    "/cart",
)

# 1:1 map. Same-path stays; aliases 301 to canonical SSR paths.
REDIRECTS = {
    "/": "/",
    "/home": "/",
    "/about": "/about",
    "/our-team": "/our-team",
    "/new-page": "/safety",
    "/clinical-safety": "/safety",
    "/contact": "/contact",
    "/thera-world": "/thera-world",
    "/pricing": "/pricing",
    "/videos": "/videos",
    "/cart": "/pricing",
}

TITLE = "Sovereign Sanctuary | AI Companion + Verified Licensed Professionals"
META = (
    "AI companion support paired with verified certified and licensed "
    "professionals. 24/7 care for individuals and families — about $5 a day for you "
    "and your partner."
)
HERO = (
    "Support that knows your history — and professionals who are verified before "
    "they meet you."
)

ORG_JSONLD = {
    "@context": "https://schema.org",
    "@type": "Organization",
    "name": "Sovereign Sanctuary",
    "url": BRAND_ORIGIN,
    "description": (
        "AI companion support paired with verified certified and licensed human "
        "professionals, for individuals and families."
    ),
    "founder": {"@type": "Person", "name": "Nathaniel Nevedal"},
    "makesOffer": [
        {"@type": "Offer", "name": "Trial-Threshold", "price": "0", "priceCurrency": "USD"},
        {"@type": "Offer", "name": "Inner Chamber", "price": "49", "priceCurrency": "USD"},
        {"@type": "Offer", "name": "Sovereign Circle", "price": "149", "priceCurrency": "USD"},
        {"@type": "Offer", "name": "Coach-Only", "price": "0", "priceCurrency": "USD"},
    ],
}

PAGES = {
    "/": {"h1": HERO, "body": CANONICAL_POSITIONING},
    "/about": {"h1": "About", "body": CANONICAL_POSITIONING},
    "/our-team": {"h1": "Our team", "body": CANONICAL_POSITIONING},
    "/safety": {"h1": "Clinical safety", "body": CANONICAL_POSITIONING},
    "/contact": {"h1": "Contact", "body": "support@sovereignsanctuary.net"},
    "/thera-world": {"h1": "Thera-world", "body": CANONICAL_POSITIONING},
    "/pricing": {
        "h1": "Pricing",
        "body": "about $5 a day for you and your partner. Inner Chamber $49. Sovereign Circle $149.",
    },
    "/videos": {"h1": "Videos", "body": CANONICAL_POSITIONING},
}


def render_brand_page(path: str) -> str:
    spec = PAGES[path]
    ld = json.dumps(ORG_JSONLD, separators=(",", ":"))
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{TITLE}</title>"
        f"<meta name='description' content='{META}'>"
        f"<script type='application/ld+json'>{ld}</script>"
        "</head><body>"
        f"<h1>{spec['h1']}</h1>"
        f"<p class='positioning'>{CANONICAL_POSITIONING}</p>"
        f"<p>{spec['body']}</p>"
        "<aside class='ss-crisis' role='note'><strong>If you need support right now:</strong> "
        "<a href='tel:988'>988 Suicide &amp; Crisis Lifeline</a></aside>"
        "</body></html>"
    )


def sitemap_urls() -> list[str]:
    return [BRAND_ORIGIN + p if p != "/" else BRAND_ORIGIN + "/" for p in PAGES]


def sitemap_xml() -> str:
    locs = "".join(f"<url><loc>{u}</loc></url>" for u in sitemap_urls())
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{locs}</urlset>\n"
    )
