"""Offline unit tests — LN7 Milestone A fast vs deep routing helpers."""
from __future__ import annotations

import os

from app.services.little_nate_7 import (
    default_incumbent_id,
    revision_serving_tier,
    serve_target_from_revision,
)


def test_default_incumbent_fast_not_32b():
    assert default_incumbent_id("fast") == "LN7-fast-baseline"
    assert default_incumbent_id("deep") == "LN7-baseline"
    assert default_incumbent_id("max") == "LN7-baseline"


def test_revision_serving_tier_from_harness():
    assert revision_serving_tier({"harness_config": {"tier": "fast"}}) == "fast"
    assert revision_serving_tier({"harness_config_json": {"tier": "deep"}}) == "deep"
    assert revision_serving_tier({"revision_id": "LN7-fast-baseline"}) == "fast"
    assert revision_serving_tier({"revision_id": "LN7-baseline"}) == "deep"


def test_serve_target_fast_prefers_peft(monkeypatch):
    monkeypatch.setenv("LN7_PEFT_URL", "http://10.13.13.5:11435")
    monkeypatch.delenv("LN7_INFERENCE_URL", raising=False)
    t = serve_target_from_revision(
        {
            "quantization": "nf4_qlora",
            "harness_config": {
                "tier": "fast",
                "force_peft": True,
                "peft_url": "http://10.13.13.5:11435",
                "peft_model": "ln7-peft",
            },
        },
        tier="fast",
    )
    assert t["mode"] == "peft"
    assert "11435" in t["url"]


def test_serve_target_deep_uses_ollama_tag(monkeypatch):
    monkeypatch.setenv("LN7_INFERENCE_URL", "http://10.13.13.5:11434")
    t = serve_target_from_revision(
        {
            "serve_checkpoint": "qwen2.5-coder:32b-instruct-q5_K_M",
            "harness_config": {"tier": "deep", "ollama_tag": "qwen2.5-coder:32b-instruct-q5_K_M"},
        },
        tier="deep",
    )
    assert t["mode"] == "ollama"
    assert "32b" in t["model"]
