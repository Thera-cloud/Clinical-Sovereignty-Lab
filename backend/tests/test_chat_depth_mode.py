"""Offline unit tests for Faster/Extra chat depth mode."""
from app.websocket.chat_depth_mode import (
    DEPTH_EXTRA,
    DEPTH_FASTER,
    allow_deep_memory_search,
    allow_enrichment,
    allow_plan_heavy,
    build_depth_richness_directive,
    build_extra_quotient_directive,
    build_faster_richness_directive,
    crystal_max_results,
    normalize_depth_mode,
    pg_history_limit,
)


def test_normalize_aliases():
    assert normalize_depth_mode("fast") == DEPTH_FASTER
    assert normalize_depth_mode("FASTER") == DEPTH_FASTER
    assert normalize_depth_mode("deep") == DEPTH_EXTRA
    assert normalize_depth_mode(None) == DEPTH_EXTRA
    assert normalize_depth_mode("weird") == DEPTH_EXTRA


def test_faster_budgets():
    assert crystal_max_results("faster") == 6
    assert pg_history_limit("faster") == 8
    assert allow_enrichment("faster") is False
    assert allow_plan_heavy("faster") is False
    assert allow_deep_memory_search("faster") is False


def test_extra_budgets():
    assert crystal_max_results("extra") == 8
    assert pg_history_limit("extra") == 15
    assert allow_enrichment("extra") is True
    assert allow_plan_heavy("extra") is True
    assert allow_deep_memory_search("extra") is True


def test_extra_quotient_directive_mentions_levels():
    block = build_extra_quotient_directive(
        "I feel sad talking with my son about which church denomination is true"
    )
    assert "SIX QUOTIENT" in block
    assert "EQ" in block
    assert "SQ" in block or "CQ" in block


def test_faster_richness_hybrid():
    text = "I feel sad talking with my son about church"
    fast = build_faster_richness_directive(text)
    assert "FASTER" in fast
    assert "RICH CLINICAL" in fast
    assert "EQ" in fast
    # Router picks compact vs full by mode
    assert "FASTER" in build_depth_richness_directive("faster", text)
    assert "EXTRA" in build_depth_richness_directive("extra", text)
    # Faster directive stays shorter than Extra
    assert len(fast) < len(build_extra_quotient_directive(text))
