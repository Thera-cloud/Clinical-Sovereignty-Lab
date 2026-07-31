"""Phase A hive_burst economics + arm resolve (importlib — avoid numpy FPE).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
SERVICES = APP / "services"
FROZEN = BACKEND.parent / "frozen-config"


def _ensure_pkg(name: str, path: Path) -> None:
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(path)]  # type: ignore[attr-defined]
        sys.modules[name] = pkg


def _load(name: str, path: Path):
    _ensure_pkg("app", APP)
    _ensure_pkg("app.services", SERVICES)
    if name in sys.modules and getattr(sys.modules[name], "__file__", None) == str(path):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.asyncio
async def test_burst_economics_dry_run_exempt():
    econ = _load(
        "app.services.ln7_burst_economics", SERVICES / "ln7_burst_economics.py"
    )
    out = await econ.evaluate_burst_economics(
        None, estimated_cost_usd=99.0, dry_run=True
    )
    assert out["ok"] is True
    assert out["mode"] == "dry_run_exempt"


@pytest.mark.asyncio
async def test_burst_economics_bootstrap_cap():
    econ = _load(
        "app.services.ln7_burst_economics", SERVICES / "ln7_burst_economics.py"
    )
    with patch.object(
        econ,
        "burst_spend_stats",
        new=AsyncMock(
            return_value={
                "windows": 1,
                "spend_usd": 70.0,
                "accepted_improvements": 0,
            }
        ),
    ):
        with patch.object(
            econ,
            "_gov",
            return_value={
                "bootstrap_burst_windows": 5,
                "bootstrap_spend_cap_usd": 75.0,
                "cpai_baseline_usd": 25.0,
                "cpai_yellow_multiplier": 1.5,
            },
        ):
            blocked = await econ.evaluate_burst_economics(
                object(), estimated_cost_usd=20.0, dry_run=False
            )
            ok = await econ.evaluate_burst_economics(
                object(), estimated_cost_usd=4.0, dry_run=False
            )
    assert blocked["ok"] is False
    assert blocked["mode"] == "bootstrap_cap"
    assert ok["ok"] is True
    assert ok["mode"] == "bootstrap"


def test_resolve_burst_arms_from_intents():
    hb = _load("app.services.ln7_hive_burst", SERVICES / "ln7_hive_burst.py")
    a, b = hb.resolve_burst_arms(
        intents=[
            {"adapter_id": "LN7-A"},
            {"adapter_id": "LN7-B"},
            {"adapter_id": "LN7-A"},
        ]
    )
    assert a == "LN7-A"
    assert b == "LN7-B"


@pytest.mark.asyncio
async def test_hive_burst_dry_path_publishes_and_clears():
    _load("app.services.ln7_burst_economics", SERVICES / "ln7_burst_economics.py")
    _load("app.services.ln7_serve_endpoint", SERVICES / "ln7_serve_endpoint.py")
    _load("app.services.ln7_change_lease", SERVICES / "ln7_change_lease.py")
    _load("app.services.flywheel_anomaly", SERVICES / "flywheel_anomaly.py")
    hb = _load("app.services.ln7_hive_burst", SERVICES / "ln7_hive_burst.py")

    with patch(
        "app.services.ln7_change_lease.acquire_lease", return_value="lease1"
    ):
        with patch("app.services.ln7_change_lease.release_lease", return_value=True):
            with patch(
                "app.services.ln7_burst_economics.evaluate_burst_economics",
                new=AsyncMock(return_value={"ok": True, "mode": "dry_run_exempt"}),
            ):
                with patch(
                    "app.services.ln7_serve_endpoint.drain_adapter_intents",
                    return_value=[],
                ):
                    with patch(
                        "app.services.ln7_serve_endpoint.publish_serve_endpoint",
                        return_value=True,
                    ) as pub:
                        with patch(
                            "app.services.ln7_serve_endpoint.clear_serve_endpoint",
                            return_value=True,
                        ) as clr:
                            out = await hb.run_hive_burst(
                                None, dry_run=True, notes="{}"
                            )
    assert out.get("ok") is True
    assert out.get("mode") == "dry_run"
    assert pub.called
    assert clr.called


def test_governance_cpai_baseline_in_frozen():
    import json

    data = json.loads((FROZEN / "governance.json").read_text(encoding="utf-8"))
    assert "cpai_baseline_usd" in data
