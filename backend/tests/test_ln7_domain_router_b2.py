"""Phase B2/B3 domain router offline fences (importlib — avoid numpy FPE).

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


def test_static_domain_python_and_flutter():
    dr = _load("app.services.ln7_domain_router", SERVICES / "ln7_domain_router.py")

    async def _run():
        assert await dr._static_domain("fix pytest asyncpg", ["foo.py"]) == "python"
        assert await dr._static_domain("build Widget", ["x.dart"]) == "flutter"
        assert await dr._static_domain("nginx compose", []) == "infra"

    import asyncio

    asyncio.run(_run())


def test_cosine_and_parse_embedding():
    dr = _load("app.services.ln7_domain_router", SERVICES / "ln7_domain_router.py")
    assert dr._cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert dr._parse_embedding({"vector": [0.1, 0.2]}) == [0.1, 0.2]
    assert dr._parse_embedding("not-json") is None


@pytest.mark.asyncio
async def test_route_disabled_skips():
    dr = _load("app.services.ln7_domain_router", SERVICES / "ln7_domain_router.py")
    with patch.object(dr, "router_enabled", new=AsyncMock(return_value=False)):
        out = await dr.route(None, prompt="x", file_paths=["a.py"])
    assert out.get("skipped") is True
    assert out.get("adapter_id") is None


@pytest.mark.asyncio
async def test_route_tier1_pushes_intent():
    dr = _load("app.services.ln7_domain_router", SERVICES / "ln7_domain_router.py")
    _load("app.services.ln7_serve_endpoint", SERVICES / "ln7_serve_endpoint.py")

    class _Conn:
        async def fetch(self, *a, **k):
            return [
                {
                    "revision_id": "LN7-DOM-1",
                    "domain_tag": "python",
                    "serve_weight": 1.0,
                    "embedding": None,
                    "win_rate": 0.6,
                }
            ]

    class _Pool:
        def acquire(self):
            return self

        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *a):
            return False

    with patch.object(dr, "router_enabled", new=AsyncMock(return_value=True)):
        with patch.object(
            dr, "_static_domain", new=AsyncMock(return_value="python")
        ):
            with patch(
                "app.services.ln7_serve_endpoint.push_adapter_intent",
                return_value=True,
            ) as push:
                with patch(
                    "app.services.ln7_serve_endpoint.get_serve_endpoint",
                    return_value=None,
                ):
                    out = await dr.route(
                        _Pool(),
                        prompt="pytest fix",
                        file_paths=["t.py"],
                        task_hash="abcd",
                    )
    assert out["tier"] == 1
    assert out["adapter_id"] == "LN7-DOM-1"
    assert push.called


def test_export_script_has_domain_flag():
    src = (BACKEND / "scripts" / "ln7_export_train_jsonl.py").read_text(
        encoding="utf-8"
    )
    assert "--domain" in src
    assert "domain_tag" in src


def test_backfill_script_exists():
    assert (BACKEND / "scripts" / "ln7_backfill_pack_domain_tags.py").is_file()
