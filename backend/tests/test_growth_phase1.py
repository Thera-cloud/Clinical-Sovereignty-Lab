"""Phase 1 / 1b Adaptive Growth Engine offline unit tests.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import time

from app.services.approval_protocol import ApprovalProtocolService
from app.services.growth.blog_publisher import body_to_html, _slugify, regenerate_sitemap
from app.services.growth.ceo_review_brief import format_metrics_lines
from app.services.growth.preview_links import sign_preview, verify_preview, build_preview_url
from app.services.growth.sender_guard import domain_is_blocked, validate_outreach_sender_domains


def test_sender_guard_blocks_product_domain():
    assert domain_is_blocked("sovereignsanctuary.net")
    assert domain_is_blocked("mail.sovereignsanctuary.net")
    assert not domain_is_blocked("outreach-example.com")


def test_sender_guard_ok_when_outreach_off(monkeypatch):
    monkeypatch.setenv("ENABLE_OUTREACH_ENGINE", "false")
    ok, msg = validate_outreach_sender_domains()
    assert ok
    assert "skipped" in msg


def test_sender_guard_fails_on_blocked_when_outreach_on(monkeypatch):
    monkeypatch.setenv("ENABLE_OUTREACH_ENGINE", "true")
    monkeypatch.setenv("OUTREACH_SENDER_DOMAINS", "hello.sovereignsanctuary.net")
    ok, msg = validate_outreach_sender_domains()
    assert not ok
    assert "blocked" in msg


def test_preview_hmac_roundtrip(monkeypatch):
    monkeypatch.setenv("GROWTH_PREVIEW_SECRET", "test-secret-phase1")
    exp = int(time.time()) + 3600
    sig = sign_preview(42, exp=exp)
    assert verify_preview(42, exp, sig)
    assert not verify_preview(42, exp - 10_000, sig)
    assert not verify_preview(99, exp, sig)
    url = build_preview_url(42)
    assert "/api/marketing/content/42/preview?" in url
    assert "sig=" in url


def test_parse_reply_rewrite_delay_retract():
    assert ApprovalProtocolService.parse_reply("REWRITE: soften claim") == {
        "decision": "REWRITE",
        "modifier_text": "soften claim",
    }
    assert ApprovalProtocolService.parse_reply("DELAY +3d")["decision"] == "DELAY"
    assert ApprovalProtocolService.parse_reply("DELAY +3d")["modifier_text"] == "+3d"
    assert ApprovalProtocolService.parse_reply("RETRACT")["decision"] == "RETRACT"
    assert ApprovalProtocolService.parse_reply("APPROVE")["decision"] == "APPROVE"


def test_metrics_lines_never_hallucinate():
    lines = format_metrics_lines(
        {
            "measured": {"source": "unavailable", "value": None},
            "cohort_median_28d": {"source": "insufficient_history", "value": None, "n": 2},
        }
    )
    joined = "\n".join(lines)
    assert "source=unavailable" in joined
    assert "insufficient_history" in joined
    assert "expected clicks" not in joined.lower()


def test_blog_helpers(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.growth.blog_publisher.PUBLIC_SITE_ROOT", tmp_path
    )
    assert _slugify("Hello World!!") == "hello-world"
    html = body_to_html("Para one.\n\nPara two.")
    assert "<p>" in html
    path = regenerate_sitemap([])
    assert path.endswith("sitemap.xml")
    assert (tmp_path / "robots.txt").exists()
