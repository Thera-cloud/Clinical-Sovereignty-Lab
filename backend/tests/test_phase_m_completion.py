"""Offline tests for the Phase M completion pass (TRUST_LEDGER.md Entry 19):
publisher-gate parity (SkyEye post path), M3 (therapeutic advisory), M4
(BWAS provenance weighting), M7 (marketing ingester privilege asymmetry).

Loaded via importlib file path — all three modified modules
(growth_claims.py, skyeye_content_generator.py, growth/bwas_worker.py)
were confirmed importable this way without triggering the local-Mac
numpy FPE (see .cursor/rules and prior LN7 test files for the same
workaround; these three specifically do NOT walk through
app.services.__init__ -> nevedal_engine).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _load(rel_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def growth_claims():
    return _load("app/services/growth_claims.py", "phase_m_growth_claims")


@pytest.fixture(scope="module")
def brand_checklist():
    # NOTE: skyeye_content_generator.py itself is NOT loaded directly in
    # this test file. It imports `from app.services.skyeye_expressions
    # import ...` at module level, which walks through app.services.__init__
    # -> nevedal_engine -> numpy -- a documented, environment-specific,
    # NON-DETERMINISTIC SIGFPE crash on this local Mac (confirmed flaky:
    # succeeded once, failed 3/3 on immediate retries with zero code
    # changes in between). growth.brand_checklist.py has no such
    # cross-import and loads reliably every time -- test the real blocking
    # logic through it directly, and verify skyeye_content_generator.py's
    # wiring to it via source-text checks (see the wired_into_* tests
    # below), matching this codebase's established workaround pattern for
    # numpy-adjacent modules (test_ln7_must_sequence_pack.py et al).
    return _load("app/services/growth/brand_checklist.py", "phase_m_brand_checklist")


# NOTE: BWAS provenance-weighting tests live in their own file,
# test_phase_m_bwas_provenance.py — loading bwas_worker.py in the SAME
# process as growth_claims.py/brand_checklist.py above was found to
# deterministically trigger the local-Mac numpy SIGFPE (5/5 repro), even
# though bwas_worker.py loads cleanly in total isolation. Splitting avoids
# fighting a documented, environment-specific, cross-import-order-
# dependent trap rather than a real code defect.


# --- Publisher gate parity: SkyEye post path -----------------------------


def test_skyeye_post_phase_calls_claim_gate():
    """The SkyEye social post path (skyeye_session_engine._post_phase) must
    call the same growth_claims.assert_claims_publishable gate that
    outreach_publisher.py has enforced since W11 — the plan spec names
    both paths explicitly, but only outreach had it wired."""
    src = (_ROOT / "app" / "services" / "skyeye_session_engine.py").read_text(
        encoding="utf-8"
    )
    assert "from app.services.growth_claims import assert_claims_publishable" in src
    assert 'channel="social"' in src
    # Must actually skip posting on gate failure, not just log it.
    idx = src.index("_claim_ids = _meta.get")
    window = src[idx : idx + 1500]
    assert "continue" in window
    assert "'failed'" in window or '"failed"' in window


def test_social_channel_is_unretractable(growth_claims):
    """Once a social post is live it isn't auto-rewritten (retract_surfaces
    only cancels PENDING/scheduled rows) — short_horizon claims must be
    refused pre-publish the same as on email."""
    src = (_ROOT / "app" / "services" / "growth_claims.py").read_text(encoding="utf-8")
    assert '"social"' in src
    assert "unretractable = channel in" in src


def test_retract_surfaces_no_longer_references_nonexistent_metadata_column():
    """skyeye_content_queue has no `metadata` column (verified against the
    live GREEN schema) — the original query would have raised
    UndefinedColumnError the first time this branch actually executed.
    Must reference content_text (verified real column) and emotion_context
    (the actual per-item JSON-blob column) instead. Checks the actual SQL
    string, not the whole file, since the fix's own explanatory comment
    legitimately mentions the old (now-dead) reference by name."""
    src = (_ROOT / "app" / "services" / "growth_claims.py").read_text(encoding="utf-8")
    idx = src.index("UPDATE skyeye_content_queue")
    sql_window = src[idx : idx + 400]
    assert "metadata->>'claim_ids'" not in sql_window
    assert "content_text ILIKE" in sql_window
    assert "emotion_context" in sql_window


# --- M3: therapeutic advisory sensitivity path ---------------------------


def test_brand_checklist_blocks_diagnosis_and_cure_claims(brand_checklist):
    """This is the real blocking logic _check_therapeutic_advisory() wraps
    (see wiring tests below) — exercised directly since the wrapper's own
    module cannot be reliably loaded standalone on this host (see fixture
    docstring)."""
    result = brand_checklist.run_brand_checklist(
        "Our program", "We diagnose anxiety and guarantee results in 30 days."
    )
    assert result["passed"] is False
    assert "diagnosis_claim" in result["fails"]
    assert "outcome_claim" in result["fails"]


def test_brand_checklist_blocks_fabricated_stats_and_agi(brand_checklist):
    result = brand_checklist.run_brand_checklist(
        "", "73% of patients feel better and our AGI companion never forgets."
    )
    assert result["passed"] is False
    assert "fabricated_stat" in result["fails"]
    assert "agi_claim" in result["fails"]


def test_brand_checklist_passes_clean_engagement_post(brand_checklist):
    result = brand_checklist.run_brand_checklist(
        "", "What's one small thing that helped you feel steadier this week?"
    )
    assert result["passed"] is True
    assert result["fails"] == []


def test_therapeutic_advisory_wrapper_present_and_wired_into_all_five_generation_paths():
    src = (_ROOT / "app" / "services" / "skyeye_content_generator.py").read_text(
        encoding="utf-8"
    )
    assert "def _check_therapeutic_advisory(" in src
    assert "from app.services.growth.brand_checklist import run_brand_checklist" in src
    assert src.count("_check_therapeutic_advisory(") >= 6  # def + >=5 call sites


def test_therapeutic_advisory_wrapper_fails_closed_on_exception():
    src = (_ROOT / "app" / "services" / "skyeye_content_generator.py").read_text(
        encoding="utf-8"
    )
    idx = src.index("def _check_therapeutic_advisory(")
    window = src[idx : idx + 2000]
    assert '"ok": False, "fails": ["advisory_check_unavailable"]' in window
    assert "except Exception as e:" in window


def test_lead_events_meta_still_strips_pii_no_regression():
    """M4's design explicitly does NOT reintroduce device/IP tracking into
    lead_events -- confirm the existing PII-stripping allowlist in
    lead_events.py is untouched by this pass."""
    src = (_ROOT / "app" / "services" / "growth" / "lead_events.py").read_text(
        encoding="utf-8"
    )
    for pii_key in ("device_id", "hardware_id", "ip", "email", "phone"):
        assert f'"{pii_key}"' in src


# --- M7: marketing ingester privilege asymmetry --------------------------


def test_generate_reply_sanitizes_comment_text_and_handle():
    src = (_ROOT / "app" / "services" / "skyeye_content_generator.py").read_text(
        encoding="utf-8"
    )
    idx = src.index("async def generate_reply")
    window = src[idx : idx + 2200]
    assert "from app.services.ln7_injection_firewall import sanitize_notes" in window
    assert 'sanitize_notes(comment_text or "")["notes"]' in window
    assert 'sanitize_notes(user_handle or "")["notes"]' in window


def test_generate_reply_fails_closed_on_firewall_import_error():
    src = (_ROOT / "app" / "services" / "skyeye_content_generator.py").read_text(
        encoding="utf-8"
    )
    idx = src.index("async def generate_reply")
    window = src[idx : idx + 2200]
    assert "injection_firewall_unavailable" in window


def test_try_theme_classifier_already_closed_allowlist_no_regression():
    """Confirmed during the M7 audit: this module was ALREADY correctly
    hardened via output-domain restriction (closed slug enum + utterance
    discard), not sanitization -- a stronger guarantee. No code change was
    made here; this test guards that property against future drift."""
    src = (_ROOT / "app" / "services" / "growth" / "try_theme_classifier.py").read_text(
        encoding="utf-8"
    )
    assert "Never logs the utterance" in src
    assert "no LLM" in src.lower() or "keyword-only" in src.lower()


def test_reply_classifier_still_rule_based_no_regression():
    """Confirmed during the M7 audit: rule-based, never auto-sends, no LLM
    call -- already privilege-minimal. Guard against future drift toward
    an LLM-driven auto-reply on raw inbound email text."""
    src = (_ROOT / "app" / "services" / "growth" / "reply_classifier.py").read_text(
        encoding="utf-8"
    )
    assert "never auto-sends" in src.lower()
    for banned in ("chat_completion_with_fallback", "_call_azure_openai", "generate_complete"):
        assert banned not in src
