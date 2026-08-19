"""Load studio modules without app.services.__init__ (numpy SIGFPE on macOS)."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"


def _pkg(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[name] = mod


def ensure_stubs() -> None:
    _pkg("app", APP)
    _pkg("app.services", APP / "services")
    _pkg("app.routers", APP / "routers")


def load_svc(mod_name: str):
    ensure_stubs()
    key = f"app.services.{mod_name}"
    if key in sys.modules and getattr(sys.modules[key], "__file__", None):
        return sys.modules[key]
    path = APP / "services" / f"{mod_name}.py"
    spec = importlib.util.spec_from_file_location(key, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    setattr(sys.modules["app.services"], mod_name, mod)
    return mod
