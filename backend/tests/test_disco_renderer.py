"""Canonical renderer + authored copy gates."""

from app.services.disco.assets import BRAND_DEFENSE_COPY, PRICING_COPY, PRODUCT_COPY
from app.services.disco.renderer import person_jsonld, render_profile_html


def test_coaching_clinical_terms_blocked():
    out = render_profile_html(
        {"display_name": "Ada", "bio": "Trauma treatment and psychotherapy", "slug": "ada"},
        relationship_class="coaching",
    )
    assert out["blocked"] is True


def test_coaching_ok_has_crisis_and_jsonld():
    out = render_profile_html(
        {
            "display_name": "Ada Ruiz",
            "credential_string": "ICF PCC",
            "bio": "Trauma-informed integration coaching for families.",
            "slug": "ada-ruiz",
            "canonical_phrases": ["family systems coaching"],
        },
        relationship_class="coaching",
    )
    assert out["blocked"] is False
    assert "ss-crisis" in out["html"]
    assert "application/ld+json" in out["html"]
    assert out["jsonld"]["@type"] == "Person"
    assert "988" in out["html"]


def test_person_jsonld_shape():
    ld = person_jsonld({"display_name": "Ada", "slug": "ada", "canonical_phrases": ["grief"]})
    assert ld["@context"] == "https://schema.org"
    assert ld["name"] == "Ada"
    assert "grief" in ld["knowsAbout"]


def test_authored_copy_c4_c5():
    assert "about $5 a day for you and your partner" in PRODUCT_COPY
    assert "about $5 a day" in PRICING_COPY
    assert "primary-source" not in BRAND_DEFENSE_COPY.lower()
    assert "background checked" not in BRAND_DEFENSE_COPY.lower()
