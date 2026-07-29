"""Faster depth uses light TTC — not Extra deep-dive preflight."""
import asyncio
import inspect

from app.services.therapeutic_controller import prepare_therapeutic_context


def test_prepare_accepts_depth_mode():
    sig = inspect.signature(prepare_therapeutic_context)
    assert "depth_mode" in sig.parameters
    assert sig.parameters["depth_mode"].default is None


def test_faster_light_path_skips_deep_blocks():
    async def _run():
        pack = await prepare_therapeutic_context(
            user_text="Just checking in about my day with the kids.",
            user_id="CLIENT_001",
            db_pool=None,
            base_system_prompt="You are Nate.",
            default_max_tokens=1500,
            depth_mode="faster",
        )
        assert pack["audit_metadata"].get("faster_light_path") is True
        assert pack["max_tokens"] <= 450
        assert "FASTER" in pack["enriched_system_prompt"]
        assert "DNA — NEUROSCIENCE BEDROCK" not in pack["enriched_system_prompt"]
        assert pack["recent_narratives"] == []
        assert pack["audit_metadata"]["autonomic_state"] == "in_window"

    asyncio.run(_run())


def test_faster_light_path_crisis_still_detected():
    async def _run():
        pack = await prepare_therapeutic_context(
            user_text="I want to kill myself tonight.",
            user_id="CLIENT_001",
            db_pool=None,
            base_system_prompt="You are Nate.",
            default_max_tokens=600,
            depth_mode="faster",
        )
        assert pack["audit_metadata"]["crisis_class_fired"] is True
        assert pack["audit_metadata"]["autonomic_state"] == "activated"
        assert pack["audit_metadata"]["tmc_class"] == "CRISIS"

    asyncio.run(_run())


def test_extra_still_full_path_structure():
    async def _run():
        pack = await prepare_therapeutic_context(
            user_text="Just checking in about my day.",
            user_id="CLIENT_001",
            db_pool=None,
            base_system_prompt="You are Nate.",
            default_max_tokens=600,
            depth_mode="extra",
        )
        assert pack["audit_metadata"].get("faster_light_path") is not True
        assert "DNA — NEUROSCIENCE BEDROCK" in pack["enriched_system_prompt"]

    asyncio.run(_run())
