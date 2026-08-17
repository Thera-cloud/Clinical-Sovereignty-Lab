"""T1 DAC gate — DAC1, DAC3, DAC6, DAC35, DAC45.

Runs against the renderer by default. Set DISCO_LIVE_DAC_URL to fetch a live
page with no JS execution (step 5). These are surface audits, not flag smokes.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request

from app.services.disco.engine import DiscoEngine
from app.services.disco.pipeline import CLINICAL_TERMS, register_lint
from app.services.disco.renderer import render_profile_html
from app.services.disco.surfaces import collect_surfaces, drift_pairs
from app.services.disco.workers_61_64 import InlineValueRenderer

LIVE_URL = os.getenv("DISCO_LIVE_DAC_URL", "").strip()

COACH = {
    "display_name": "Mara Chen",
    "credential_string": "ICF PCC",
    "bio": "Trauma-informed integration coaching for families in Detroit.",
    "slug": "mara-chen",
    "canonical_phrases": ["family systems coaching", "grief processing"],
    "same_as": ["https://www.linkedin.com/in/mara-chen-example"],
}


def _fetch_raw(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "SovereignSanctuary-DAC/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _extract_jsonld(html: str) -> dict:
    m = re.search(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.I | re.S,
    )
    assert m, "DAC6: no application/ld+json in raw HTML"
    return json.loads(m.group(1))


def _gate_html() -> str:
    if LIVE_URL:
        return _fetch_raw(LIVE_URL)
    out = render_profile_html(COACH, relationship_class="coaching")
    assert out["blocked"] is False
    return out["html"]


def test_dac1_canonical_propagates_zero_drift():
    """DAC1: one record → page, JSON-LD, sameAs, llms, hub, byline, footer; edit clears old phrases."""
    if LIVE_URL:
        html = _fetch_raw(LIVE_URL)
        ld = _extract_jsonld(html)
        assert ld.get("name")
        assert ld.get("@type") == "Person"
        assert ld.get("name") in html
        return
    first = collect_surfaces(COACH)
    assert first["blocked"] is False
    assert drift_pairs(COACH, first["surfaces"]) == []
    assert COACH["same_as"][0] in first["surfaces"]["sameAs"]
    edited = {**COACH, "canonical_phrases": ["somatic awareness coaching"]}
    second = collect_surfaces(edited)
    assert drift_pairs(edited, second["surfaces"]) == []
    leftover = drift_pairs(COACH, second["surfaces"])
    assert any("family systems coaching" in x for x in leftover)


def test_dac3_register_linter_blocks_clinical_on_coaching_profile():
    """DAC3: treatment-register terms on a coaching-class profile are blocked at publish."""
    for term in sorted(CLINICAL_TERMS):
        lint = register_lint(f"Welcome. This is {term} for families.", "coaching")
        assert lint["blocked"] is True, term
        assert lint["action"] == "BLOCK_PUBLISH+QUEENS_RED"
    out = render_profile_html(
        {**COACH, "bio": "Psychotherapy and diagnosis for the patient."},
        relationship_class="coaching",
    )
    assert out["blocked"] is True
    assert out["html"] == ""
    ok = register_lint(COACH["bio"], "coaching")
    assert ok["blocked"] is False


def test_dac6_raw_html_has_content_and_valid_jsonld():
    """DAC6: raw-HTML fetch (no JS) contains full content + valid JSON-LD."""
    html = _gate_html()
    eng = DiscoEngine()
    gate = eng.crawlability_gate(html)
    assert gate["has_body"] is True
    assert gate["has_jsonld"] is True
    assert gate["has_app_js"] is False
    ld = _extract_jsonld(html)
    assert eng.validate_jsonld(ld)["ok"] is True
    if not LIVE_URL:
        assert COACH["display_name"] in html
        assert COACH["display_name"] == ld["name"]
        assert "family systems coaching" in html


def test_dac45_usable_with_js_disabled():
    """DAC45: initial HTML is a complete value unit + crisis resources; no application JS."""
    html = _gate_html()
    eng = DiscoEngine()
    gate = eng.crawlability_gate(html)
    assert gate["has_app_js"] is False
    assert gate["has_crisis"] is True
    assert "ss-value" in html
    assert "988" in html or "ss-crisis" in html
    assert re.search(r"<script(?![^>]*application/ld\+json)", html, re.I) is None
    assert "<input type=\"checkbox\"" in html or "<details" in html


def test_dac35_crisis_resources_zero_conversion_red_on_inversion():
    """DAC35: distress HTML has resources, zero conversion prompts; inversion is Queens RED."""
    eng = DiscoEngine()
    unit = InlineValueRenderer().render_page("<p>A quiet practice.</p>", "grounding_60s", "US")
    clean = eng.crisis_session_gate(unit, distress=True, apply_conversion=False)
    assert clean["ok"] is True
    assert clean["queens"] == "GREEN"
    assert clean["resources"] is True
    assert clean["conversion_prompts"] == 0
    assert InlineValueRenderer.contains_conversion_ask(unit) is False
    inverted = eng.crisis_session_gate(
        unit + '<p>Sign up and start trial</p>',
        distress=True,
        apply_conversion=True,
    )
    assert inverted["ok"] is False
    assert inverted["queens"] == "RED"
    assert inverted["reason"] == "conversion_on_distress"
