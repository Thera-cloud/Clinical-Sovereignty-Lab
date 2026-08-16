"""Offline DiscoEngine smoke — flags off, no DB."""

from app.services.disco.engine import DiscoEngine, WORKER_REGISTRY
from app.services.disco.pipeline import register_lint


def test_worker_registry_covers_required_ids():
    required = set(range(1, 17)) | set(range(29, 65))
    assert required <= set(WORKER_REGISTRY)


def test_engine_health_and_lint():
    eng = DiscoEngine()
    h = eng.health()
    assert h["status"] == "ok"
    assert h["workers"] == len(WORKER_REGISTRY)
    assert h["flags"]["DISCO_RENDER"] is False
    bad = eng.lint("Trauma treatment and psychotherapy for patients", "coaching")
    assert bad["blocked"] is True
    ok = eng.lint("Trauma-informed integration coaching", "coaching")
    assert ok["blocked"] is False


def test_jsonld_and_crawl_gate():
    eng = DiscoEngine()
    assert eng.validate_jsonld({"@context": "https://schema.org", "@type": "Person", "name": "Ada"})["ok"]
    html = (
        "<h1>Ada</h1><article>bio</article>"
        "<script type='application/ld+json'>{}</script>"
        "<aside class='ss-crisis'>988</aside>"
    )
    gate = eng.crawlability_gate(html)
    assert gate["has_body"] and gate["has_jsonld"] and gate["has_crisis"]
    assert gate["has_app_js"] is False


def test_a3_never_auto_publishes():
    eng = DiscoEngine()
    item = eng.queue_item("article_publish", {"slug": "x"})
    assert item["auto_approved"] is False
    assert item["publish_requires_human"] is True
    sched = eng.content_schedule("x")
    assert sched["published"] is False


def test_horizons_young_not_stable():
    eng = DiscoEngine()
    out = eng.horizons([50.0] * 60)
    y180 = next(r for r in out["rows"] if r["horizon_days"] == 180)
    assert y180["trend"] == "insufficient_history"


def test_ai_search_attribution():
    eng = DiscoEngine()
    assert eng.attribute_ai_search("https://chatgpt.com/") == "ai_search"
    assert eng.attribute_ai_search("https://example.com") is None


def test_ask_governor_and_crisis():
    eng = DiscoEngine()
    distress = eng.crisis_screen("I want to die")
    assert distress["distress"] is True
    ask = eng.ask_governor("<a href='/buy'>Buy now</a>", distress=True)
    assert ask["blocked"] is True


def test_hub_and_onboard():
    eng = DiscoEngine()
    assert eng.hub_gate(0)["allow"] is False
    assert eng.hub_gate(1)["allow"] is True
    pkt = eng.onboard_packet({"display_name": "Ada", "credential_string": "PCC", "canonical_phrases": ["grief"]})
    assert pkt["ready"] is True


def test_register_lint_matches_pipeline():
    assert register_lint("diagnose the patient", "coaching")["blocked"] is True
