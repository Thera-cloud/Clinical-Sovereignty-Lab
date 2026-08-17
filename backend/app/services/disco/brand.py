"""T1.MIG brand SSR — T0.2 copy, zero application JS. DNS not flipped here."""

from __future__ import annotations

import json

from app.services.disco.surfaces import CANONICAL_POSITIONING

BRAND_ORIGIN = "https://www.sovereignsanctuary.net"
SIGNUP_URL = "https://app.sovereignsanctuary.net/signup.html"
SQUARESPACE_HOME = "https://www.sovereignsanctuary.net/"

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

PUBLIC_EMAIL = "support@sovereignsanctuary.net"
PUBLIC_PHONE = "+1-810-354-7770"
TEST_METRO = "Detroit, MI, USA"
TEST_HUB_PATH = "coaches/trauma-coaches/detroit-mi"
COACHING_PHRASES = ("family systems coaching", "presence-based coaching")
ORG_SAME_AS = (
    "https://mycounselor.online/christian-counselors/nathaniel-nevedal/",
    "https://mycounselor.online/author/nathaniel-nevedal/",
    "https://opennpi.com/provider/1790494144",
    "https://www.google.com/maps/place/Sovereign+Sanctuary/data=!4m2!3m1!1s0x8824bdf3fb8a0155:0xb66b2d67afaa7216",
)
ORG_DESCRIPTION = (
    "AI companion support paired with verified certified and licensed human "
    "professionals, for individuals and families."
)
SERVICE_DESCRIPTION = (
    "Family systems coaching and presence-based coaching in Detroit, MI, USA. "
    "Coaching-class Life coach. Virtual appointments."
)


def homepage_jsonld() -> dict:
    """Homepage graph. No empty strings. No LocalBusiness street. No clinical types."""
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": f"{BRAND_ORIGIN}/#website",
                "url": f"{BRAND_ORIGIN}/",
                "name": "Sovereign Sanctuary",
                "description": META,
                "publisher": {"@id": f"{BRAND_ORIGIN}/#org"},
            },
            {
                "@type": "Organization",
                "@id": f"{BRAND_ORIGIN}/#org",
                "name": "Sovereign Sanctuary",
                "url": BRAND_ORIGIN,
                "description": ORG_DESCRIPTION,
                "email": PUBLIC_EMAIL,
                "telephone": PUBLIC_PHONE,
                "founder": {"@type": "Person", "name": "Nathaniel Nevedal"},
                "sameAs": list(ORG_SAME_AS),
                "areaServed": TEST_METRO,
                "makesOffer": [
                    {"@type": "Offer", "name": "Trial-Threshold", "price": "0", "priceCurrency": "USD"},
                    {"@type": "Offer", "name": "Inner Chamber", "price": "49", "priceCurrency": "USD"},
                    {"@type": "Offer", "name": "Sovereign Circle", "price": "149", "priceCurrency": "USD"},
                    {"@type": "Offer", "name": "Coach-Only", "price": "0", "priceCurrency": "USD"},
                ],
            },
            {
                "@type": "ProfessionalService",
                "@id": f"{BRAND_ORIGIN}/#lifecoach",
                "name": "Sovereign Sanctuary",
                "url": BRAND_ORIGIN,
                "serviceType": "Life coach",
                "description": SERVICE_DESCRIPTION,
                "areaServed": TEST_METRO,
                "email": PUBLIC_EMAIL,
                "telephone": PUBLIC_PHONE,
                "sameAs": list(ORG_SAME_AS),
                "availableChannel": {
                    "@type": "ServiceChannel",
                    "serviceUrl": SIGNUP_URL,
                    "availableLanguage": "English",
                },
            },
        ],
    }


def homepage_seo_packet() -> dict:
    """Human paste for live Squarespace + GBP. Does not recut DNS."""
    ld = homepage_jsonld()
    script = (
        '<script type="application/ld+json">'
        + json.dumps(ld, separators=(",", ":"))
        + "</script>"
    )
    return {
        "live_host": "squarespace",
        "do_not_emit": ["LocalBusiness", "Counselor", "Therapist", "Psychotherapist"],
        "squarespace": {
            "h1_keep": "Revolutionizing the Path to Mental Wellness",
            "h1_demote_to_h2": "24 hours / 7 days a week!",
            "image_alt": "Sovereign Sanctuary — family systems coaching",
            "code_injection_header": script,
            "seo_description": META,
        },
        "gbp": {
            "primary_category": "Life coach",
            "additional_categories": [],
            "hide_address": True,
            "onsite_services": False,
            "service_area": "Detroit, MI",
            "website": SQUARESPACE_HOME,
            "signup": SIGNUP_URL,
            "human_step": "gbp_hide_address_keep_life_coach_only",
        },
        "bing": {"human_step": "request_indexing_after_squarespace_publish"},
        "jsonld": ld,
    }


ORG_JSONLD = homepage_jsonld()

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
        f"<meta property='og:title' content='{TITLE}'>"
        f"<meta property='og:description' content='{META}'>"
        f"<meta property='og:url' content='{SQUARESPACE_HOME}'>"
        f"<meta property='og:type' content='website'>"
        f"<meta property='og:site_name' content='Sovereign Sanctuary'>"
        f"<script type='application/ld+json'>{ld}</script>"
        "</head><body>"
        f"<h1>{spec['h1']}</h1>"
        f"<p class='positioning'>{CANONICAL_POSITIONING}</p>"
        f"<p>{spec['body']}</p>"
        "<p><a href='https://app.sovereignsanctuary.net/signup.html'>Sign up</a></p>"
        "<p><a href='/coaches/coachn'>Nathaniel Nevedal — coach profile</a></p>"
        "<aside class='ss-crisis' role='note'><strong>If you need support right now:</strong> "
        "<a href='tel:988'>988 Suicide &amp; Crisis Lifeline</a></aside>"
        "</body></html>"
    )


def sitemap_urls() -> list[str]:
    return [BRAND_ORIGIN + p if p != "/" else BRAND_ORIGIN + "/" for p in PAGES]


def sitemap_xml() -> str:
    locs = "".join(f"<url><loc>{u}</loc></url>" for u in sitemap_urls())
    extra = (
        f"<url><loc>{BRAND_ORIGIN}/coaches/coachn</loc></url>"
        f"<url><loc>{BRAND_ORIGIN}/coaches/trauma-coaches/detroit-mi</loc></url>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{locs}{extra}</urlset>\n"
    )


TEST_COACH = {
    "display_name": "Nathaniel Nevedal",
    "credential_string": "Coach",
    "bio": (
        "Coaching for households in Detroit, MI, USA. Presence-based coaching "
        "and family systems coaching — coaching-class, not a clinical practice."
    ),
    "slug": "coachn",
    "canonical_phrases": list(COACHING_PHRASES),
    "same_as": list(ORG_SAME_AS),
    "area_served": [TEST_METRO],
    "relationship_class": "coaching",
}


def render_metro_page(metro: str, slug: str) -> str:
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>Coaches in {metro} | Sovereign Sanctuary</title>"
        f"<meta name='description' content='{META}'>"
        "</head><body>"
        f"<h1>Coaches in {metro}</h1>"
        f"<p class='positioning'>{CANONICAL_POSITIONING}</p>"
        f"<p><a href='/coaches/{slug}'>Nathaniel Nevedal</a> — family systems coaching</p>"
        "<aside class='ss-crisis' role='note'><strong>If you need support right now:</strong> "
        "<a href='tel:988'>988 Suicide &amp; Crisis Lifeline</a></aside>"
        "</body></html>"
    )


def render_hub_page(hub: str, slug: str, metro: str = TEST_METRO) -> str:
    title = "Trauma coaches in Detroit, MI"
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{title} | Sovereign Sanctuary</title>"
        f"<meta name='description' content='{META}'>"
        "</head><body>"
        f"<h1>{title}</h1>"
        f"<p class='positioning'>{CANONICAL_POSITIONING}</p>"
        f"<p>Coaching-class hub for {metro}. Not a clinical directory.</p>"
        f"<p><a href='/coaches/{slug}'>Nathaniel Nevedal</a> — family systems coaching</p>"
        "<aside class='ss-crisis' role='note'><strong>If you need support right now:</strong> "
        "<a href='tel:988'>988 Suicide &amp; Crisis Lifeline</a></aside>"
        "</body></html>"
    )
