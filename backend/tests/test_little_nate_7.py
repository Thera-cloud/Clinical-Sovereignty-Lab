"""Offline unit tests for Little Nate 7 — identity, gates, bakeoff CI.

Loads via importlib to avoid app.services.__init__ → numpy crash on macOS.
# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"


def _ensure_pkg(name: str, path: Path) -> None:
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(path)]  # type: ignore[attr-defined]
        sys.modules[name] = pkg


def _load(name: str, path: Path):
    _ensure_pkg("app", APP)
    _ensure_pkg("app.services", APP / "services")
    _ensure_pkg("app.websocket", APP / "websocket")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    # Also register under app.* so cross-imports resolve without package __init__
    if name.startswith("app."):
        sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_ln7 = _load("app.services.little_nate_7", APP / "services" / "little_nate_7.py")
_ledger = _load("app.services.ln7_ledger", APP / "services" / "ln7_ledger.py")
_bakeoff = _load("app.services.ln7_bakeoff_engine", APP / "services" / "ln7_bakeoff_engine.py")
_harness = _load("app.websocket.ln7_harness", APP / "websocket" / "ln7_harness.py")
_revision = _load("app.services.ln7_revision", APP / "services" / "ln7_revision.py")
_catalog = _load("app.websocket.cli_model_catalog", APP / "websocket" / "cli_model_catalog.py")


def test_product_major_immutable():
    assert _ln7.PRODUCT_MAJOR == 7
    assert _ln7.PRODUCT_NAME == "Little Nate 7"


def test_broken_foundry_alias_rejected():
    assert _ln7.is_broken_foundry_alias("grok-4.5")
    assert _ln7.is_broken_foundry_alias("Grok-4.5")
    assert not _ln7.is_broken_foundry_alias("grok-4-1-fast-reasoning")


def test_contestant_reasoning_rewrites_broken_alias(monkeypatch):
    monkeypatch.setenv("NATE_CLI_REASONING_MODEL", "grok-4.5")
    monkeypatch.setenv("NATE_CHAT_MODEL", "grok-4-1-fast-reasoning")
    assert _ln7.contestant_reasoning_model() == "grok-4-1-fast-reasoning"


def test_catalog_entries_space_ln7(monkeypatch):
    monkeypatch.setenv("ENABLE_LN7", "true")
    rows = _ln7.ln7_catalog_entries({"revision_id": "LN7-baseline", "revised_at": "baseline"})
    assert len(rows) == 2
    assert all(r["space"] == "ln7" for r in rows)
    assert all(r["product_major"] == 7 for r in rows)


def test_static_gate_rejects_secrets_and_escapes():
    ok, _ = _harness.static_gate("diff --git a/x.py b/x.py\n+print(1)\n")
    assert ok
    bad, note = _harness.static_gate("api_key = 'sk-abcdefghijklmnopqrstuvwxyz'\n")
    assert not bad
    assert "secret" in note
    bad2, _note2 = _harness.static_gate("--- /etc/passwd\n+++ /etc/passwd\n")
    assert not bad2


def test_bootstrap_ci_and_gate():
    ci = _bakeoff.bootstrap_ci([True, True, True, False], n_boot=200)
    assert ci["n"] == 4
    assert 0.0 <= ci["lo"] <= ci["mean"] <= ci["hi"] <= 1.0
    assert _bakeoff.beats_incumbent({"lo": 0.8}, 0.5)
    assert not _bakeoff.beats_incumbent({"lo": 0.4}, 0.5)
    gate = _bakeoff.statistical_gate([True, True, True], [True, False, False], min_tasks=3)
    assert "ok" in gate


def test_license_gate():
    assert _ledger.license_allowed_for_training("MIT")
    assert not _ledger.license_allowed_for_training("GPL-3.0")
    assert not _ledger.license_allowed_for_training(None)


def test_resolve_stream_target_ln7(monkeypatch):
    monkeypatch.setenv("ENABLE_LN7", "true")
    monkeypatch.setenv("ENABLE_LN7_HARNESS", "true")
    monkeypatch.setenv("SOVEREIGN_INFERENCE_URL", "http://10.13.13.5:11434")
    monkeypatch.setenv("LN7_CODE_MODEL_DEEP", "qwen2.5-coder:32b-instruct-q5_K_M")
    t = _catalog.resolve_stream_target("ln7:LN7-baseline:max", "ln7")
    assert t is not None
    assert t["provider"] == "ln7"
    assert "coder" in (t["model"] or "")


def test_model_card_write():
    path = _revision.write_model_card(
        "LN7-test-unit",
        base_checkpoint="qwen2.5-coder:7b-instruct",
        quantization="q5_K_M",
        scorecard={"private": {"pass_rate": {"mean": 1.0, "lo": 0.9, "hi": 1.0, "n": 3}}},
        notes="unit test",
    )
    assert "LN7-test-unit" in path
    root = Path(__file__).resolve().parents[2]
    full = root / path
    assert full.is_file()
    text = full.read_text(encoding="utf-8")
    assert "Little Nate 7" in text
    assert "Non-clinical claim" in text
    full.unlink(missing_ok=True)


def test_cli_defaults_skip_grok45(monkeypatch):
    monkeypatch.setenv("NATE_CLI_REASONING_MODEL", "grok-4.5")
    monkeypatch.setenv("NATE_CHAT_MODEL", "grok-4-1-fast-non-reasoning")
    monkeypatch.setenv("NATE_CLI_CODE_MODEL", "")
    rows = _catalog._cli_defaults()
    ids = {r["id"] for r in rows}
    assert "grok-4.5" not in ids


def test_pack_task_detection():
    assert _harness.looks_like_pack_task("Please fix asyncpg_cast pack")
    assert _harness.infer_pack_name("env_redis_prefix is broken") == "env_redis_prefix"
    assert not _harness.looks_like_pack_task("what is the weather?")


def test_coding_tier_sovereign_only():
    import re

    # Avoid re-execing nate_inference_router after full-suite asyncio teardown (no event loop).
    src = (APP / "services" / "nate_inference_router.py").read_text(encoding="utf-8")
    m = re.search(
        r"TIER_CODING\s*:\s*\[([^\]]+)\]",
        src,
    )
    assert m, "TIER_CODING priority block missing"
    providers = [p.strip().strip("\"'") for p in m.group(1).split(",") if p.strip()]
    assert providers == ["sovereign", "home_gpu"]
