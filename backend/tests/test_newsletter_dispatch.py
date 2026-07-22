"""Offline unit tests — Little Nate Dispatch (no DB/network).

Avoid `from app.services.X` when that pulls services/__init__ → numpy (sandbox FPE).
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def _load(mod_name: str, rel: str):
    path = BACKEND / rel
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def _ensure_lite_services_pkg():
    """Register newsletter modules under app.services.* without importing services/__init__ (numpy FPE)."""
    import types

    if "app" not in sys.modules:
        app_pkg = types.ModuleType("app")
        app_pkg.__path__ = [str(BACKEND / "app")]  # type: ignore[attr-defined]
        sys.modules["app"] = app_pkg

    existing = sys.modules.get("app.services")
    if existing is None or not getattr(existing, "_nl_lite", False):
        # Blank package shell so `from app.services.X` does not exec __init__.py
        svc = types.ModuleType("app.services")
        svc.__path__ = [str(BACKEND / "app" / "services")]  # type: ignore[attr-defined]
        svc._nl_lite = True  # type: ignore[attr-defined]
        sys.modules["app.services"] = svc
        sys.modules["app"].services = svc  # type: ignore[attr-defined]

    deps = (
        ("app.services.newsletter_clinical_curriculum", "app/services/newsletter_clinical_curriculum.py"),
        ("app.services.newsletter_clinical_gate", "app/services/newsletter_clinical_gate.py"),
        ("app.services.newsletter_topic_engine", "app/services/newsletter_topic_engine.py"),
    )
    for name, rel in deps:
        if name not in sys.modules:
            _load(name, rel)


def _load_pipeline(alias: str):
    _ensure_lite_services_pkg()
    return _load(alias, "app/services/newsletter_pipeline.py")


def test_html_email_has_safety_footer_and_unsub():
    delivery = _load("nl_delivery_ut", "app/services/newsletter_delivery.py")
    html = delivery._html_email(
        {
            "subject_line": "Test",
            "final_body": "Hello [NIMH](https://www.nimh.nih.gov/health)\n\n## Techniques\nStep one",
            "slug": "test-issue",
            "citations": [
                {
                    "source_name": "NIMH",
                    "year": 2025,
                    "url": "https://www.nimh.nih.gov/health",
                }
            ],
        },
        rate_base="https://api.example/rate?t=abc",
        unsub_url="https://api.example/unsubscribe?sid=1&t=tok",
    )
    assert "Unsubscribe" in html
    assert "Story Library" in html
    assert "Little Nate Dispatch" in html
    assert "/api/newsletter/library/test-issue/page" in html
    assert 'href="https://www.nimh.nih.gov/health"' in html
    assert "<h2" in html
    assert "Share this Dispatch" in html
    assert "channel=x" in html
    assert "channel=facebook" in html
    assert "channel=linkedin" in html
    assert "channel=whatsapp" in html


def test_md_body_to_html_links_and_headers():
    delivery = _load("nl_delivery_md_ut", "app/services/newsletter_delivery.py")
    html = delivery.md_body_to_html("## Go deeper\nSee [988](https://988lifeline.org)")
    assert "<h2" in html
    assert 'href="https://988lifeline.org"' in html
    escaped = delivery.md_body_to_html("<script>x</script>")
    assert "<script>" not in escaped
    assert "&lt;script&gt;" in escaped


def test_rate_token_uses_canonical_salt(monkeypatch):
    monkeypatch.setenv("NEWSLETTER_TOKEN_SALT", "nate-dispatch")
    delivery = _load("nl_delivery_tok_ut", "app/services/newsletter_delivery.py")
    tok = delivery.rate_token_for_subscriber(
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    )
    expect = hashlib.sha256(
        b"11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222:rate:nate-dispatch"
    ).hexdigest()[:32]
    assert tok == expect
    assert len(delivery.library_rate_token("11111111-1111-1111-1111-111111111111")) == 32


def test_render_library_html_crisis_footer():
    delivery = _load("nl_delivery_ut2", "app/services/newsletter_delivery.py")
    html = delivery.render_library_html(
        {
            "slug": "_test_dispatch_slug",
            "subject_line": "Unit Test Issue",
            "final_body": "Body copy",
            "topic": "steadiness",
        }
    )
    assert "988" in html
    assert "not therapy" in html.lower() or "not medical" in html.lower()
    assert delivery.library_page_url("_test_dispatch_slug").endswith(
        "/api/newsletter/library/_test_dispatch_slug/page"
    )


def test_library_write_uses_data_dir(tmp_path, monkeypatch):
    delivery = _load("nl_delivery_ut3", "app/services/newsletter_delivery.py")
    import asyncio

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEWSLETTER_SKIP_CLOUD_ARCHIVE", "true")

    async def _run():
        meta = await delivery._write_library_html(
            {
                "slug": "_test_dispatch_slug",
                "subject_line": "Unit Test Issue",
                "final_body": "Body copy long enough",
            }
        )
        path = tmp_path / "newsletter_library" / "_test_dispatch_slug.html"
        assert path.exists()
        assert "988" in path.read_text(encoding="utf-8")
        assert meta.get("library_html_path")

    asyncio.run(_run())


def test_deterministic_unsub_token():
    salt = "nate-dispatch"
    sid = "11111111-1111-1111-1111-111111111111"
    tok = hashlib.sha256(f"{salt}:unsub:{sid}".encode()).hexdigest()[:40]
    assert len(tok) == 40
    assert re.fullmatch(r"[0-9a-f]+", tok)


def test_library_recall_empty_without_db():
    recall = _load("nl_recall_ut", "app/services/newsletter_library_recall.py")
    import asyncio

    async def _run():
        ctx = await recall.recall_newsletter_library_context(None, "anxiety and sleep")
        assert ctx == ""

    asyncio.run(_run())


def test_newsletter_task_kinds_registered():
    bus = _load("cli_task_bus_ut", "app/websocket/cli_task_bus.py")
    assert "newsletter_topic_patrol" in bus.NEWSLETTER_TASK_KINDS
    assert "newsletter_symbolic_promote" in bus.NEWSLETTER_TASK_KINDS


def test_story_library_shell_exists():
    p = ROOT / "dashboard" / "nate_story_library.html"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "Story Library" in text
    assert "988" in text
    assert "/api/newsletter/library/" in text
    assert "Subscribe" in text
    assert "shareBase" in text
    assert "channel=" in text


def test_admin_dispatch_shell_exists():
    p = ROOT / "dashboard" / "newsletter_dispatch.html"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "Approve" in text
    assert "Preview" in text
    assert "Request rewrite" in text
    assert "/preview" in text
    assert "Generate topic image" in text
    assert "Refresh topic pool" in text
    assert "growthBody" in text


def test_topic_engine_novelty_and_score():
    _ensure_lite_services_pkg()
    eng = _load("nl_topic_eng_ut", "app/services/newsletter_topic_engine.py")
    assert eng.novelty_penalty("Anxiety reach out", ["Anxiety reach out"]) == 1.0
    assert eng.novelty_penalty("Brand new theme", ["Anxiety reach out"]) < 0.3
    assert eng.infer_domain("ADHD and masking at work") == "neurodivergence"
    assert eng.infer_domain("CBT thought record practice") == "cbt"
    assert eng.infer_domain("DEAR MAN ask for space") == "dbt"
    # Clinical editorial (default): curriculum beat beats news_velocity
    s_clinical = eng.score_candidate(clinical_boost=1.0, news_velocity=0.0, novelty=0.0, domain="cbt")
    s_trend = eng.score_candidate(clinical_boost=0.0, news_velocity=0.9, foresight=0.8, novelty=0.0, domain="arts")
    assert s_clinical > s_trend
    s_fresh = eng.score_candidate(clinical_boost=1.0, novelty=0.0, domain="cbt")
    s_stale = eng.score_candidate(clinical_boost=1.0, novelty=0.9, domain="cbt")
    assert s_fresh > s_stale


def test_share_intent_urls():
    delivery = _load("nl_delivery_share_ut", "app/services/newsletter_delivery.py")
    lib = "https://api.example/library/foo/page?utm_source=share&utm_medium=x&ref=foo"
    x = delivery.share_intent_url("x", lib, "Hello")
    assert "twitter.com/intent" in x
    assert "facebook.com/sharer" in delivery.share_intent_url("facebook", lib, "Hello")
    assert "linkedin.com/sharing" in delivery.share_intent_url("linkedin", lib, "Hello")
    assert "whatsapp.com" in delivery.share_intent_url("whatsapp", lib, "Hello")
    assert delivery.share_tracker_url("my-slug", "x").endswith("channel=x")


def test_trend_heuristic_pair_politics_is_coping():
    trend = _load("nl_trend_ut", "app/services/newsletter_trend_pairing.py")
    p = trend._heuristic_pair("Election headlines spike", "politics")
    assert "nervous" in p["title"].lower() or "headline" in p["title"].lower()
    assert "vote for" not in p["title"].lower()


def test_citation_allowlist_has_neuro_military_arts():
    pipe = _load_pipeline("nl_pipe_cite_ut")
    domains = set()
    for c in pipe.CITATION_ALLOWLIST:
        domains.update(c.get("domains") or ())
        domains.update(c.get("topic_tags") or ())
    assert "neurodivergence" in domains
    assert "military" in domains
    assert "arts" in domains
    assert "cbt" in domains
    assert "dbt" in domains
    assert "act" in domains
    assert "988 then press 1" in pipe.safety_footer_for_domain("military")
    # No mislabeled Physical Activity → caring-for-your-mental-health
    for c in pipe.CITATION_ALLOWLIST:
        if "physical activity" in (c.get("source_name") or "").lower():
            assert "caring-for-your-mental-health" not in c["url"]
        if "caring for your mental health" in (c.get("source_name") or "").lower():
            assert "caring-for-your-mental-health" in c["url"]


def test_clinical_gate_topic_match_universal_modalities():
    _ensure_lite_services_pkg()
    gate = sys.modules["app.services.newsletter_clinical_gate"]
    pipe = _load_pipeline("nl_pipe_gate_ut")

    cbt_topic = {
        "title": "CBT thought records: catching the story before it runs you",
        "topic_key": "cbt_thought_records",
        "domain": "cbt",
        "modalities": ["CBT"],
    }
    dbt_topic = {
        "title": "DBT distress tolerance when the wave hits",
        "topic_key": "dbt_distress_tolerance",
        "domain": "dbt",
        "modalities": ["DBT"],
    }
    cbt_cites = gate.select_relevant_citations(pipe.CITATION_ALLOWLIST, cbt_topic, limit=5)
    dbt_cites = gate.select_relevant_citations(pipe.CITATION_ALLOWLIST, dbt_topic, limit=5)
    assert cbt_cites
    assert dbt_cites
    assert all("autism" not in (c.get("url") or "").lower() for c in cbt_cites)
    assert any(c.get("supports_technique") for c in cbt_cites)
    assert any("dbt" in (c.get("topic_tags") or c.get("domains") or ()) for c in dbt_cites)

    # Autism allowlist entry only for neurodivergence topics
    neuro = {
        "title": "Autism and sensory load",
        "topic_key": "neuro_autism",
        "domain": "neurodivergence",
        "modalities": ["neurodivergence"],
    }
    neuro_cites = gate.select_relevant_citations(pipe.CITATION_ALLOWLIST, neuro, limit=5)
    assert any("autism" in (c.get("url") or "").lower() for c in neuro_cites)

    # Label mismatch fails gate
    bad = {
        "citations": [
            {
                "source_name": "NIH — Physical Activity",
                "page_title": "Caring for Your Mental Health",
                "year": 2025,
                "url": "https://www.nimh.nih.gov/health/topics/caring-for-your-mental-health",
                "verified": True,
                "topic_tags": ["cbt"],
                "technique_tags": ["cbt"],
                "supports_technique": True,
            }
        ]
    }
    errs = gate.validate_clinical_citations(bad, bad, topic=cbt_topic)
    assert any("cite_label_mismatch" in e for e in errs)

    good_cite = {
        "source_name": "APA — Cognitive Behavioral Therapy",
        "page_title": "Cognitive Behavioral Therapy",
        "year": 2025,
        "url": "https://www.apa.org/ptsd-guideline/patients-and-families/cognitive-behavioral",
        "verified": True,
        "topic_tags": ["cbt"],
        "technique_tags": ["cbt"],
        "supports_technique": True,
        "modality": "psychoeducation",
    }
    ok_errs = gate.validate_clinical_citations(
        {"citations": [good_cite]}, {"citations": [good_cite], "topic": cbt_topic}, topic=cbt_topic
    )
    assert ok_errs == []


def test_hero_prompt_is_safe_editorial():
    img = _load("nl_img_ut", "app/services/newsletter_imagery.py")
    prompt = img.build_hero_prompt("When anxiety asks you to shrink", "Dispatch")
    assert "Little Nate Dispatch" in prompt
    assert "no blood" in prompt.lower() or "no medical" in prompt.lower()
    assert "When anxiety asks you to shrink" in prompt
    assert img.hero_public_url("demo-slug").endswith("/api/newsletter/library/demo-slug/hero")


def test_hero_sniff_png_and_jpeg():
    img = _load("nl_img_sniff_ut", "app/services/newsletter_imagery.py")
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    jpg = b"\xff\xd8\xff" + b"\x00" * 20
    assert img.sniff_image_meta(png) == (".png", "image/png")
    assert img.sniff_image_meta(jpg) == (".jpg", "image/jpeg")


def test_hero_enabled_accepts_gemini_without_xai(monkeypatch):
    img = _load("nl_img_en_ut", "app/services/newsletter_imagery.py")
    monkeypatch.setenv("ENABLE_NEWSLETTER_HERO_IMAGE", "true")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_SSE_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini")
    assert img.hero_enabled() is True
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert img.hero_enabled() is False


def test_resolve_hero_prompt_prefers_override_then_stored():
    img = _load("nl_img_resolve_ut", "app/services/newsletter_imagery.py")
    stored = "[provider:gemini]\nCustom lantern in fog"
    assert img.strip_provider_prefix(stored) == "Custom lantern in fog"
    assert (
        img.resolve_hero_prompt("topic", stored_prompt=stored, override="Editor override")
        == "Editor override"
    )
    assert img.resolve_hero_prompt("topic", stored_prompt=stored) == "Custom lantern in fog"
    assert "Little Nate Dispatch" in img.resolve_hero_prompt("Quiet check-ins")


def test_admin_preview_shows_hero_placeholder_when_missing():
    delivery = _load("nl_delivery_placeholder_ut", "app/services/newsletter_delivery.py")
    html = delivery.render_library_html(
        {"slug": "demo", "subject_line": "Test", "final_body": "Body", "topic": "steadiness"},
        admin_preview=True,
    )
    assert "Topic image not generated yet" in html
    public = delivery.render_library_html(
        {"slug": "demo", "subject_line": "Test", "final_body": "Body", "topic": "steadiness"},
        admin_preview=False,
    )
    assert "Topic image not generated yet" not in public


def test_email_html_embeds_hero_when_present():
    delivery = _load("nl_delivery_hero_ut", "app/services/newsletter_delivery.py")
    html = delivery._html_email(
        {
            "subject_line": "Little Nate Dispatch: steadiness",
            "preheader": "You do not have to earn rest or connection.",
            "opener": "You do not have to earn rest or connection. Strength includes asking.",
            "final_body": "Hello",
            "slug": "demo-slug",
            "hero_image_url": "https://api.example/api/newsletter/library/demo-slug/hero",
            "topic": "steadiness",
        },
        rate_base="https://api.example/rate?t=abc",
        unsub_url="https://api.example/unsubscribe?sid=1&t=tok",
    )
    assert "<img " in html
    assert "demo-slug/hero" in html
    assert "display:none" in html
    assert "You do not have to earn rest" in html
    # Subject must not be the first visible preview line
    assert html.index("display:none") < html.index("Little Nate Dispatch")


def test_template_draft_applies_rewrite_notes_without_dumping_instructions():
    pipe = _load_pipeline("nl_pipe_ut")
    topic = {"title": "Asking for help", "topic_key": "ask", "domain": "somatic"}
    bundle = {
        "citations": [
            {
                "source_name": "NIMH — Caring for Your Mental Health",
                "page_title": "Caring for Your Mental Health",
                "year": 2025,
                "url": "https://www.nimh.nih.gov/health/topics/caring-for-your-mental-health",
                "verified": True,
                "modality": "psychoeducation",
                "topic_tags": ["somatic"],
                "technique_tags": ["somatic"],
                "supports_technique": True,
            }
        ],
        "external_reading": {
            "source_name": "NIMH — Caring for Your Mental Health",
            "year": 2025,
            "url": "https://www.nimh.nih.gov/health/topics/caring-for-your-mental-health",
        },
        "editor_rewrite_notes": "Lead with grounding before research",
        "topic": topic,
        "domain": "somatic",
    }
    draft = pipe.draft_issue_from_bundle(topic, bundle)
    body = draft["body_md"]
    assert "Lead with grounding" in body
    assert "EDITOR REWRITE" not in body
    assert "988" in body
    assert "This week's Dispatch is clinical psychoeducation on" not in body


def test_template_draft_clinical_psychoeducation_and_nate_prompts():
    pipe = _load_pipeline("nl_pipe_clinical_ut")
    topic = {
        "title": "CBT thought records: catching the story before it runs you",
        "topic_key": "cbt_thought_records",
        "domain": "cbt",
        "headline": "SHOULD NOT APPEAR IN CLINICAL MODE",
        "angle": "SHOULD NOT APPEAR",
        "symbolic_hints": [
            "GROWTH_7D: warm_lead: +7 subs / 7 conv",
            "Issue 20260719-x topic=Building: avg_helpful=5.00",
        ],
    }
    bundle = {
        "citations": [
            {
                "source_name": "APA — Cognitive Behavioral Therapy",
                "page_title": "Cognitive Behavioral Therapy",
                "year": 2025,
                "url": "https://www.apa.org/ptsd-guideline/patients-and-families/cognitive-behavioral",
                "verified": True,
                "modality": "psychoeducation",
                "topic_tags": ["cbt"],
                "technique_tags": ["cbt"],
                "supports_technique": True,
            }
        ],
        "external_reading": {
            "source_name": "APA — Cognitive Behavioral Therapy",
            "year": 2025,
            "url": "https://www.apa.org/ptsd-guideline/patients-and-families/cognitive-behavioral",
        },
        "topic": topic,
        "domain": "cbt",
    }
    draft = pipe.draft_issue_from_bundle(topic, bundle)
    body = draft["body_md"]
    assert "Voice notes" not in body
    assert "GROWTH_7D" not in body
    assert "avg_helpful" not in body
    assert "SHOULD NOT APPEAR" not in body
    assert "Cognitive Behavioral" in body or "thought record" in body.lower()
    assert "**CBT:**" in body or "CBT" in body
    assert "Practice with Little Nate" in body
    assert "thought record" in body.lower()
    assert "This week's Dispatch is clinical psychoeducation on" not in body
    assert "(CBT)" not in body.split("\n")[0]  # no redundant modality tag on intro line
    assert draft.get("preheader")
    assert draft["preheader"].lower() != (draft.get("subject_line") or "").lower()
    ok, errs = pipe.critique_issue(draft, bundle)
    assert ok, errs


def test_clinical_curriculum_bank_loaded():
    cur = _load("nl_clin_cur_ut", "app/services/newsletter_clinical_curriculum.py")
    assert cur.clinical_editorial_mode() is True
    assert len(cur.CLINICAL_CURRICULUM) >= 12
    hit = cur.curriculum_by_key("dbt_interpersonal_effectiveness")
    assert hit
    assert "DEAR MAN" in hit["title"] or any("DEAR MAN" in p for p in hit["nate_prompts"])
    assert any("Assert" in t["text"] for t in hit["techniques"])
    assert len(hit["nate_prompts"]) >= 2


def test_summon_cache_key_scopes_by_user():
    path = BACKEND / "app/services/nate_summon_service.py"
    text = path.read_text(encoding="utf-8")
    assert "_summon_cache_key" in text
    assert "access_level" in text
    assert "ident" in text


def test_migration_seeds_baseline_and_gap_fix():
    sql = (BACKEND / "migrations/252_little_nate_dispatch.sql").read_text()
    assert "newsletter_check_count" in sql
    gap = (BACKEND / "migrations/253_newsletter_gap_fixes.sql").read_text()
    assert "learned_at" in gap
    assert "library_html_path" in gap
    gap255 = (BACKEND / "migrations/255_newsletter_wiring_gaps.sql").read_text()
    assert "uq_newsletter_feedback_issue_sub" in gap255
    gap256 = (BACKEND / "migrations/256_newsletter_growth_engine.sql").read_text()
    assert "newsletter_trend_candidates" in gap256
    assert "ref_slug" in gap256


def test_library_recall_gate_ignores_short_unrelated():
    recall = _load("nl_recall_gate_ut", "app/services/newsletter_library_recall.py")
    assert recall._query_wants_library("hi") is False
    assert recall._query_wants_library("anxiety sleep stress tonight") is True
    assert recall._query_wants_library("story library") is True


def test_admin_dispatch_has_insights_tab():
    text = (ROOT / "dashboard" / "newsletter_dispatch.html").read_text(encoding="utf-8")
    assert "Insights" in text
    assert "/metrics" in text
    assert "reject-replicates" in text


def test_signals_normalize_theme():
    sig = _load("nl_signals_ut", "app/services/newsletter_signals.py")
    assert sig._normalize_theme("  Anxiety!! Reach-Out  ") == "anxiety reach-out"


def test_hive_kinds_dispatchable():
    hive = _load("nl_hive_ut", "app/services/newsletter_hive.py")
    assert hive.hive_enabled() in (True, False)
    assert "newsletter_topic_patrol" in dir(hive) or callable(hive.run_hive_patrol)
    assert callable(hive.execute_newsletter_kind)
    assert callable(hive.enqueue_hive_tasks)


def test_newsletter_task_kinds_include_growth_loop():
    bus = _load("nl_bus_kinds_ut", "app/websocket/cli_task_bus.py")
    kinds = bus.NEWSLETTER_TASK_KINDS
    for k in (
        "newsletter_topic_patrol",
        "newsletter_trend_pairing",
        "newsletter_growth_attribution",
        "newsletter_chat_learn",
        "newsletter_symbolic_promote",
    ):
        assert k in kinds


def test_hive_defaults_on_when_agent_on(monkeypatch):
    hive = _load("nl_hive_default_ut", "app/services/newsletter_hive.py")
    monkeypatch.setenv("ENABLE_NEWSLETTER_HIVE", "")
    monkeypatch.setenv("ENABLE_NEWSLETTER_AGENT", "true")
    assert hive.hive_enabled() is True
    monkeypatch.setenv("ENABLE_NEWSLETTER_HIVE", "false")
    assert hive.hive_enabled() is False


def test_consumer_has_newsletter_dispatch():
    text = (BACKEND / "app/services/cli_task_bus_consumer.py").read_text(encoding="utf-8")
    assert "_dispatch_newsletter_kind" in text
    assert "newsletter_chat_learn" in text


def test_learning_reinforces_crystal_sql():
    text = (BACKEND / "app/services/newsletter_learning.py").read_text(encoding="utf-8")
    assert "nate_intelligence_crystals" in text
    assert "learning_outcome" in text
    assert "24 hours" in text


def test_library_recall_records_chat_theme():
    text = (BACKEND / "app/services/newsletter_library_recall.py").read_text(encoding="utf-8")
    assert "library_chat" in text
    assert "DISPATCH LEARNING" in text
    assert "_load_editorial_learning_block" in text
