"""
Offline unit tests for LN Enrichment Tiers (backend/app/websocket/bridge_enrichment.py).

No DB, Redis, or network required. All heavy Tier 2 paths (FederatedSearch,
Helix) are lazy and never triggered here.
"""
import importlib
import os

import pytest

import app.websocket.bridge_enrichment as enr


@pytest.fixture(autouse=True)
def _enable_enrichment(monkeypatch):
    monkeypatch.setenv("LN_ENRICHMENT", "1")
    for i in range(1, 6):
        monkeypatch.delenv(f"LN_T{i}_ENRICH", raising=False)
    # Reset per-test mutable state
    enr._pending_corrections.clear()
    yield
    enr._pending_corrections.clear()


# ─── Flags ────────────────────────────────────────────────────────────────

def test_master_flag_off_disables_everything(monkeypatch):
    monkeypatch.setenv("LN_ENRICHMENT", "0")
    assert not enr.enrichment_enabled()
    for i in range(1, 6):
        assert not enr.tier_enabled(i)


def test_per_tier_override(monkeypatch):
    monkeypatch.setenv("LN_ENRICHMENT", "1")
    monkeypatch.setenv("LN_T3_ENRICH", "0")
    assert enr.tier_enabled(2)
    assert not enr.tier_enabled(3)


def test_per_tier_can_enable_when_master_off(monkeypatch):
    monkeypatch.setenv("LN_ENRICHMENT", "0")
    monkeypatch.setenv("LN_T5_ENRICH", "1")
    assert enr.tier_enabled(5)


# ─── Tier 1: memory turns + rerank ───────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Do you remember what I told you about my dad?",
    "Last session we talked about the divorce.",
    "like I said before, mornings are the worst",
])
def test_memory_turn_detection(text):
    assert enr.is_memory_turn(text)


@pytest.mark.parametrize("text", ["", "I feel anxious today.", "ok thanks"])
def test_non_memory_turns(text):
    assert not enr.is_memory_turn(text)


def test_lexical_rerank_prefers_topical_overlap():
    rows = [
        {"id": 1, "crystal_text": "Client fears abandonment after divorce", "confidence": 0.55},
        {"id": 2, "crystal_text": "Spring marketing cadence for campaigns", "confidence": 0.95},
        {"id": 3, "crystal_text": "Divorce grief resurfaces at night, abandonment wound", "confidence": 0.50},
    ]
    seen = set()
    picked = enr.lexical_rerank_globals(rows, "my divorce and the abandonment I feel", 2, seen)
    ids = [r["id"] for r in picked]
    assert ids[0] in (1, 3)
    assert seen == set(ids)


def test_lexical_rerank_thin_query_falls_back_to_order():
    rows = [{"id": i, "crystal_text": f"text {i}", "confidence": 0.5} for i in range(4)]
    seen = {0}
    picked = enr.lexical_rerank_globals(rows, "ok", 2, seen)
    assert [r["id"] for r in picked] == [1, 2]


def test_lexical_rerank_respects_seen_ids():
    rows = [{"id": 1, "crystal_text": "divorce abandonment", "confidence": 0.9}]
    seen = {1}
    assert enr.lexical_rerank_globals(rows, "divorce abandonment pain", 3, seen) == []


# ─── Tier 2: high-signal gating ──────────────────────────────────────────

def test_high_signal_emotional_disclosure():
    text = ("I feel so ashamed and hurt about what happened with my mother "
            "when I was a child, it still makes me cry.")
    assert enr.is_high_signal_turn(text)


def test_memory_turn_is_always_high_signal():
    assert enr.is_high_signal_turn("Do you remember my dad?")


@pytest.mark.parametrize("text", ["", "ok thanks", "what time is my session tomorrow please"])
def test_low_signal_turns(text):
    assert not enr.is_high_signal_turn(text)


@pytest.mark.asyncio
async def test_addendum_returns_empty_on_low_signal():
    assert await enr.build_enrichment_addendum(None, "u1", "ok thanks") == ""


@pytest.mark.asyncio
async def test_addendum_disabled_when_tier2_off(monkeypatch):
    monkeypatch.setenv("LN_T2_ENRICH", "0")
    text = "I feel so ashamed and hurt about my mother, I was so scared as a child."
    assert await enr.build_enrichment_addendum(None, "u1", text) == ""


@pytest.mark.asyncio
async def test_addendum_priority_fires_when_tier2_off(monkeypatch):
    monkeypatch.setenv("LN_T2_ENRICH", "0")
    text = "Just give me actionable strategies, stop asking about feelings."
    block = await enr.build_enrichment_addendum(None, "u1", text)
    assert "PARALLEL PROCESS" in block


def test_detect_priority_overrides():
    assert "parallel_process" in enr.detect_priority_overrides(
        "I need you to tell me what to do, stop asking about feelings.")
    assert "witnessing" in enr.detect_priority_overrides(
        "Sometimes I think about suicide.")
    assert not enr.detect_priority_overrides("The weather was nice.")
    # Literal tech/image — must not fire parallel_process / somatic
    assert "parallel_process" not in enr.detect_priority_overrides(
        "That's not helpful — the picture of me looks like a female and sad."
    )
    assert "parallel_process" not in enr.detect_priority_overrides(
        "I think you are glitching. Can we focus on the image?"
    )
    somatic = enr.build_priority_override_addendum(
        "From a research perspective this is textbook depersonalization with cortisol spikes."
    )
    assert "SOMATIC INTERRUPT" in somatic
    assert "grounding script" in somatic.lower() or "felt-sense" in somatic.lower()
    assert "clipboard" not in somatic.lower()


# ─── Tier 3: language guard ──────────────────────────────────────────────

def test_guard_replaces_banned_phrases():
    cleaned, hits = enr.apply_language_guard(
        "I want to hold space for you in this liminal moment.", uid="u1")
    assert "hold space" not in cleaned.lower()
    assert "liminal" not in cleaned.lower()
    assert len(hits) >= 2


def test_guard_leaves_clean_text_untouched():
    text = "You said the mornings are the hardest part."
    cleaned, hits = enr.apply_language_guard(text, uid="u2")
    assert cleaned == text
    assert hits == []


def test_guard_flags_threshold_without_replacing():
    text = "Your pain threshold has shifted since we started."
    cleaned, hits = enr.apply_language_guard(text, uid="u3")
    assert cleaned == text  # flag-only, no substitution
    assert any("threshold" in h for h in hits)


def test_correction_directive_one_shot():
    enr.apply_language_guard("Let me hold space for that.", uid="u4")
    assert enr.pop_correction_directive("u4")
    assert enr.pop_correction_directive("u4") == ""


def test_guard_disabled_when_tier3_off(monkeypatch):
    monkeypatch.setenv("LN_T3_ENRICH", "0")
    text = "I will hold space in this liminal moment."
    cleaned, hits = enr.apply_language_guard(text, uid="u5")
    assert cleaned == text
    assert hits == []


# ─── Tier 4: IFS part hints ──────────────────────────────────────────────

def test_ifs_firefighter():
    assert "Firefighter" in enr.ifs_part_hints("I went numb and scrolled for hours")


def test_ifs_exile():
    assert "Exile" in enr.ifs_part_hints("deep down I feel worthless and unlovable")


def test_ifs_manager():
    assert "Manager" in enr.ifs_part_hints("I have to keep it together and stay in control")


def test_ifs_neutral_text():
    assert enr.ifs_part_hints("The weather was nice this weekend.") == []
    assert enr.ifs_part_hints("") == []


# ─── Tier 5: audit log ───────────────────────────────────────────────────

def test_audit_noop_when_tier5_off(monkeypatch, tmp_path):
    monkeypatch.setenv("LN_ENRICHMENT", "0")
    # Must not raise even with no event loop running
    enr.log_turn_audit(uid="u", provider="grok", latency_ms=100)


def test_audit_hash_is_stable_and_short():
    h1 = enr._hash_uid("client_alice")
    h2 = enr._hash_uid("client_alice")
    assert h1 == h2
    assert len(h1) == 12
    assert h1 != enr._hash_uid("client_bob")
