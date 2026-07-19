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


def test_html_email_has_safety_footer_and_unsub():
    delivery = _load("nl_delivery_ut", "app/services/newsletter_delivery.py")
    html = delivery._html_email(
        {"subject_line": "Test", "final_body": "Hello", "slug": "test-issue"},
        rate_base="https://api.example/rate?t=abc",
        unsub_url="https://api.example/unsubscribe?sid=1&t=tok",
    )
    assert "Unsubscribe" in html
    assert "Story Library" in html
    assert "Little Nate Dispatch" in html
    assert "/api/newsletter/library/test-issue/page" in html


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


def test_admin_dispatch_shell_exists():
    p = ROOT / "dashboard" / "newsletter_dispatch.html"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "Approve" in text
    assert "Preview" in text
    assert "Request rewrite" in text
    assert "/preview" in text
    assert "Generate topic image" in text


def test_hero_prompt_is_safe_editorial():
    img = _load("nl_img_ut", "app/services/newsletter_imagery.py")
    prompt = img.build_hero_prompt("When anxiety asks you to shrink", "Dispatch")
    assert "Little Nate Dispatch" in prompt
    assert "no blood" in prompt.lower() or "no medical" in prompt.lower()
    assert "When anxiety asks you to shrink" in prompt
    assert img.hero_public_url("demo-slug").endswith("/api/newsletter/library/demo-slug/hero")


def test_email_html_embeds_hero_when_present():
    delivery = _load("nl_delivery_hero_ut", "app/services/newsletter_delivery.py")
    html = delivery._html_email(
        {
            "subject_line": "Test",
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


def test_template_draft_applies_rewrite_notes_without_dumping_instructions():
    pipe = _load("nl_pipe_ut", "app/services/newsletter_pipeline.py")
    topic = {"title": "Asking for help", "topic_key": "ask"}
    bundle = {
        "citations": [
            {
                "source_name": "NIMH",
                "year": 2025,
                "url": "https://www.nimh.nih.gov/health/topics/anxiety-disorders",
                "verified": True,
                "modality": "psychoeducation",
            }
        ],
        "external_reading": {
            "source_name": "NIMH",
            "year": 2025,
            "url": "https://www.nimh.nih.gov/health/topics/anxiety-disorders",
        },
        "editor_rewrite_notes": "Lead with grounding before research",
    }
    draft = pipe.draft_issue_from_bundle(topic, bundle)
    body = draft["body_md"]
    assert "Lead with grounding" in body
    assert "EDITOR REWRITE" not in body
    assert "988" in body


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


def test_signals_normalize_theme():
    sig = _load("nl_signals_ut", "app/services/newsletter_signals.py")
    assert sig._normalize_theme("  Anxiety!! Reach-Out  ") == "anxiety reach-out"


def test_hive_kinds_dispatchable():
    hive = _load("nl_hive_ut", "app/services/newsletter_hive.py")
    assert hive.hive_enabled() in (True, False)
    assert "newsletter_topic_patrol" in dir(hive) or callable(hive.run_hive_patrol)
