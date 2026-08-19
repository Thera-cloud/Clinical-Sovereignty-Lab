"""
Shared pytest fixtures for the Sovereign Swarm test suite.

Also repairs dotted-path patches under ``app.services.*`` when submodules
live in ``sys.modules`` but are not bound as attributes on the parent
package (common with stub ``types.ModuleType("app.services")`` loaders that
avoid ``app.services.__init__`` / numpy on macOS).
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest import mock

# macOS: app.services.__init__ imports nevedal_engine → numpy SIGFPE.
# Namespace stub so submodule imports load files without package __init__.
# Collection-time skip for files that import numpy (Accelerate SIGFPE on
# macOS system Python). Linux CI still collects and runs the full tree.
import re as _re

_DARWIN_NPY_MARKERS = (
    "import numpy",
    "from numpy",
)


def _darwin_npy_service_stems() -> set[str]:
    svc = Path(__file__).resolve().parents[1] / "app" / "services"
    stems: set[str] = set()
    if not svc.is_dir():
        return stems
    texts: dict[str, str] = {}
    for py in svc.glob("*.py"):
        try:
            texts[py.stem] = py.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
    for stem, text in texts.items():
        if "import numpy" in text or "from numpy" in text or "nevedal_engine" in text:
            stems.add(stem)
    for _ in range(2):
        extra: set[str] = set()
        for stem, text in texts.items():
            if stem in stems:
                continue
            if any(
                f"from app.services.{s}" in text or f"import app.services.{s}" in text
                for s in stems
            ):
                extra.add(stem)
        stems.update(extra)
    return stems


_DARWIN_NPY_STEMS = _darwin_npy_service_stems() if sys.platform == "darwin" else set()


def pytest_ignore_collect(collection_path, config):
    if sys.platform != "darwin":
        return None
    path = Path(str(collection_path))
    if path.suffix != ".py" or not path.name.startswith("test_"):
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    # Subprocess re-imports app.services.__init__ → numpy SIGFPE on Xcode 3.9.
    if path.name == "test_ln7_clean_train_export.py":
        return True
    if any(m in text for m in _DARWIN_NPY_MARKERS):
        return True
    for stem in _DARWIN_NPY_STEMS:
        if _re.search(
            rf"(from\s+app\.services\s+import\s+[^\n]*\b{stem}\b|"
            rf"from\s+app\.services\.{stem}\b|"
            rf"import\s+app\.services\.{stem}\b)",
            text,
        ):
            return True
    return None


if sys.platform == "darwin" and "app.services" not in sys.modules:
    _app_dir = Path(__file__).resolve().parents[1] / "app"
    _app = sys.modules.get("app")
    if _app is None:
        _app = types.ModuleType("app")
        _app.__path__ = [str(_app_dir)]  # type: ignore[attr-defined]
        sys.modules["app"] = _app
    _svc = types.ModuleType("app.services")
    _svc.__path__ = [str(_app_dir / "services")]  # type: ignore[attr-defined]
    sys.modules["app.services"] = _svc
    setattr(_app, "services", _svc)

import pytest
try:
    from _pytest.monkeypatch import notset as _MP_NOTSET
except ImportError:
    from _pytest.monkeypatch import NOTSET as _MP_NOTSET


def _bind_module_ancestors(mod_path: str) -> None:
    """Ensure each ``app.services…`` segment is an attribute of its parent."""
    parts = mod_path.split(".")
    for i in range(1, len(parts)):
        parent = sys.modules.get(".".join(parts[:i]))
        child_name = parts[i]
        child = sys.modules.get(".".join(parts[: i + 1]))
        if parent is None or child is None:
            continue
        if getattr(parent, child_name, None) is not child:
            try:
                setattr(parent, child_name, child)
            except Exception:
                pass


def _resolve_app_services_target(dotted: str):
    """Return ``(owner, attr_name)`` for an ``app.services…`` dotted path."""
    if not isinstance(dotted, str) or not dotted.startswith("app.services."):
        return None
    parts = dotted.split(".")
    for i in range(len(parts), 1, -1):
        mod_path = ".".join(parts[:i])
        try:
            mod = importlib.import_module(mod_path)
        except ModuleNotFoundError:
            continue
        _bind_module_ancestors(mod_path)
        rest = parts[i:]
        if not rest:
            return None
        owner = mod
        try:
            for attr in rest[:-1]:
                owner = getattr(owner, attr)
        except AttributeError:
            continue
        return owner, rest[-1]
    return None


_ORIG_MP_SETATTR = pytest.MonkeyPatch.setattr


def _mp_setattr_pytest(self, target, name=_MP_NOTSET, value=_MP_NOTSET, raising=True):
    # Two-arg form: monkeypatch.setattr("a.b.c", new_value)
    if value is _MP_NOTSET and isinstance(target, str) and name is not _MP_NOTSET:
        resolved = _resolve_app_services_target(target)
        if resolved is not None:
            owner, attr = resolved
            return _ORIG_MP_SETATTR(self, owner, attr, name, raising=raising)
    return _ORIG_MP_SETATTR(self, target, name, value, raising=raising)


pytest.MonkeyPatch.setattr = _mp_setattr_pytest  # type: ignore[method-assign]

_ORIG_PATCH = mock.patch


def _patch_app_services(target, *args, **kwargs):
    if isinstance(target, str):
        resolved = _resolve_app_services_target(target)
        if resolved is not None:
            owner, attr = resolved
            return _ORIG_PATCH.object(owner, attr, *args, **kwargs)
    return _ORIG_PATCH(target, *args, **kwargs)


_patch_app_services.object = _ORIG_PATCH.object  # type: ignore[attr-defined]
_patch_app_services.dict = _ORIG_PATCH.dict  # type: ignore[attr-defined]
_patch_app_services.multiple = _ORIG_PATCH.multiple  # type: ignore[attr-defined]
_patch_app_services.stopall = _ORIG_PATCH.stopall  # type: ignore[attr-defined]
mock.patch = _patch_app_services  # type: ignore[assignment]


class FakeConnection:
    def __init__(self):
        self._executed = []
        self._fetch_results = []
        self._fetchrow_result = None
        self._fetchval_result = None

    async def fetch(self, query, *args):
        return self._fetch_results

    async def fetchrow(self, query, *args):
        return self._fetchrow_result

    async def fetchval(self, query, *args):
        return self._fetchval_result

    async def execute(self, query, *args):
        self._executed.append((query, args))
        return "INSERT 0 1"


class FakePool:
    def __init__(self):
        self._conn = FakeConnection()

    def acquire(self):
        return FakeAcquireContext(self._conn)


class FakeAcquireContext:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


class FakeRedis:
    def __init__(self):
        self._data = {}

    async def ping(self):
        return True

    async def xadd(self, name, fields, maxlen=None):
        if name not in self._data:
            self._data[name] = []
        self._data[name].append(fields)
        return b"1-0"

    async def info(self, section=None):
        return {}

    async def close(self):
        pass


@pytest.fixture
def fake_pool():
    return FakePool()


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def fake_conn(fake_pool):
    return fake_pool._conn
