"""Offline smoke — LN7 burst OpenAI URL join + provider allowlist.

Regresses the Branch A instrument artifact: burst handoff URL already ends in
/v1; naive join produced /v1/v1/chat/completions → provider=none →
vendor_rejected:none → mean 0.0 with zero diffs.
# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio

from app.services.nate_inference_router import (
    NateInferenceRouter,
    openai_compat_chat_url,
)
from app.websocket import ln7_harness as harness


def test_openai_compat_chat_url_no_double_v1():
    assert (
        openai_compat_chat_url("http://147.182.152.56:11436/v1")
        == "http://147.182.152.56:11436/v1/chat/completions"
    )
    assert (
        openai_compat_chat_url("http://147.182.152.56:11436/v1/")
        == "http://147.182.152.56:11436/v1/chat/completions"
    )


def test_openai_compat_chat_url_peft_host_gets_v1():
    assert (
        openai_compat_chat_url("http://10.13.13.5:11435")
        == "http://10.13.13.5:11435/v1/chat/completions"
    )


def test_provider_allowlist_rejects_cloud_vendors():
    assert "azure" not in harness._LN7_PROVIDER_ALLOWLIST
    assert "grok" not in harness._LN7_PROVIDER_ALLOWLIST
    assert "workers_ai" not in harness._LN7_PROVIDER_ALLOWLIST
    assert "sovereign" in harness._LN7_PROVIDER_ALLOWLIST
    assert "home_gpu" in harness._LN7_PROVIDER_ALLOWLIST


def test_provider_none_not_mislabeled_vendor_rejected():
    """provider=none is router exhaustion — must not say vendor_rejected."""
    assert "none" not in harness._LN7_PROVIDER_ALLOWLIST


def test_override_bypasses_stale_sovereign_unhealthy(monkeypatch):
    """base_url_override must still call sovereign when ORANGE health is false."""
    router = NateInferenceRouter()
    router._sovereign_healthy = False
    router._home_gpu_healthy = False
    called = {"n": 0}

    async def _fake_call(provider, *args, **kwargs):
        called["n"] += 1
        called["provider"] = provider
        called["override"] = kwargs.get("base_url_override")
        return {"text": "diff --git a/x b/x\n", "tokens_used": 1}

    monkeypatch.setattr(router, "_call_provider", _fake_call)

    async def _run():
        return await router.generate(
            prompt="fix",
            tier="coding",
            domain="coding",
            providers_override=["sovereign", "home_gpu"],
            model_override="LN7-2026-07-30T190327Z",
            base_url_override="http://147.182.152.56:11436/v1",
        )

    out = asyncio.run(_run())
    assert called["n"] == 1
    assert called["provider"] == "sovereign"
    assert called["override"] == "http://147.182.152.56:11436/v1"
    assert out["provider"] == "sovereign"
    assert out["text"].startswith("diff --git")


def test_no_override_still_skips_unhealthy_sovereign(monkeypatch):
    router = NateInferenceRouter()
    router._sovereign_healthy = False
    router._home_gpu_healthy = False
    called = {"n": 0}

    async def _fake_call(*args, **kwargs):
        called["n"] += 1
        return {"text": "ok", "tokens_used": 1}

    monkeypatch.setattr(router, "_call_provider", _fake_call)

    async def _run():
        return await router.generate(
            prompt="hi",
            tier="coding",
            domain="coding",
            providers_override=["sovereign", "home_gpu"],
        )

    out = asyncio.run(_run())
    assert called["n"] == 0
    assert out["provider"] == "none"
