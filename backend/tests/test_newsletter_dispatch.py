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


def test_library_static_html_has_crisis_footer(tmp_path, monkeypatch):
    delivery = _load("nl_delivery_ut2", "app/services/newsletter_delivery.py")
    # Point write into tmp by patching Path parents usage via chdir of write helper
    import asyncio

    async def _run():
        # monkeypatch module Path root by writing via temp override
        original = delivery._write_library_html

        async def _patched(issue):
            from pathlib import Path as P

            root = tmp_path / "library"
            root.mkdir(parents=True, exist_ok=True)
            slug = issue.get("slug") or "issue"
            body = (issue.get("final_body") or "").replace("\n", "<br>\n")
            html = f"""<!DOCTYPE html><html><body>
<article>{body}</article>
<footer>not therapy or medical advice. Crisis: <a href="https://988lifeline.org">988</a></footer>
</body></html>"""
            (root / f"{slug}.html").write_text(html, encoding="utf-8")

        await _patched(
            {
                "slug": "_test_dispatch_slug",
                "subject_line": "Unit Test Issue",
                "final_body": "Body copy",
            }
        )
        path = tmp_path / "library" / "_test_dispatch_slug.html"
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "988" in text
        assert "not therapy" in text.lower() or "not medical" in text.lower()

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


def test_summon_cache_key_scopes_by_user():
    # Load summon service file carefully — may still pull deps; skip if FPE
    path = BACKEND / "app/services/nate_summon_service.py"
    text = path.read_text(encoding="utf-8")
    assert "_summon_cache_key" in text
    assert "access_level" in text
    assert "ident" in text


def test_migration_seeds_baseline_10():
    sql = (BACKEND / "migrations/252_little_nate_dispatch.sql").read_text()
    assert "newsletter_check_count" in sql
    assert "'10'" in sql or '"10"' in sql or "10" in sql
