"""macOS numpy SIGFPE guard — stub app.services before nevedal import. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import sys
import types
from pathlib import Path

if sys.platform == "darwin" and "app.services" not in sys.modules:
    _app_dir = Path(__file__).resolve().parents[2] / "backend" / "app"
    _app = sys.modules.get("app")
    if _app is None:
        _app = types.ModuleType("app")
        _app.__path__ = [str(_app_dir)]  # type: ignore[attr-defined]
        sys.modules["app"] = _app
    _svc = types.ModuleType("app.services")
    _svc.__path__ = [str(_app_dir / "services")]  # type: ignore[attr-defined]
    sys.modules["app.services"] = _svc
    setattr(_app, "services", _svc)
