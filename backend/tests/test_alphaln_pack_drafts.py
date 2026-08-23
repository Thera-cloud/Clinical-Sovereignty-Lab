"""Offline guards for AlphaLN pack drafts (no inference, no DB)."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
SVC = APP / "services"


def _ensure_pkg(name: str, path: Path) -> None:
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(path)]  # type: ignore[attr-defined]
        sys.modules[name] = pkg


def _load():
    _ensure_pkg("app", APP)
    _ensure_pkg("app.services", SVC)
    name = "app.services.alphaln_pack_drafts"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SVC / "alphaln_pack_drafts.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_GOOD_BROKEN = '''
def run() -> str:
    return "rsync -avz --delete ./a/ /b/"

def looks_fixed(cmd: str) -> bool:
    return "--delete" not in cmd and "rsync" in cmd
'''

_GOOD_FIXED = '''
def run() -> str:
    return "rsync -avz ./a/ /b/"

def looks_fixed(cmd: str) -> bool:
    return "--delete" not in cmd and "rsync" in cmd
'''


def test_validate_spec_accepts_exclusive_needle():
    m = _load()
    spec, err = m.validate_spec(
        {
            "slug": "rsync_aln_demo",
            "title": "Ban rsync delete in demo pack",
            "rel": "broken/deploy.py",
            "broken": _GOOD_BROKEN,
            "fixed": _GOOD_FIXED,
            "looks_needle": "rsync -avz ./a/",
        },
        reserved=set(),
    )
    assert err == ""
    assert spec and spec["slug"] == "rsync_aln_demo"


def test_validate_spec_rejects_import_and_taken_slug():
    m = _load()
    spec, err = m.validate_spec(
        {
            "slug": "x",
            "title": "too short",
            "rel": "broken/x.py",
            "broken": "import os\n",
            "fixed": "import os\n",
            "looks_needle": "x",
        },
        reserved=set(),
    )
    assert spec is None
    spec, err = m.validate_spec(
        {
            "slug": "taken_slug",
            "title": "Taken slug should fail validation",
            "rel": "broken/deploy.py",
            "broken": _GOOD_BROKEN,
            "fixed": _GOOD_FIXED,
            "looks_needle": "rsync -avz ./a/",
        },
        reserved={"taken_slug"},
    )
    assert spec is None
    assert err == "slug_taken"


def test_review_and_generate_never_call_burst():
    src = (SVC / "alphaln_pack_drafts.py").read_text(encoding="utf-8")
    assert "run_fuel_volume_burst(" not in src
    assert "run_fuel_organic_drip(" not in src
    assert "INSERT INTO outcome_envelope" not in src
    assert "nate_intelligence_crystals" not in src


def test_materialize_writes_catalog_aln_prefix(tmp_path):
    m = _load()
    spec, err = m.validate_spec(
        {
            "slug": "rsync_aln_demo",
            "title": "Ban rsync delete in demo pack",
            "rel": "broken/deploy.py",
            "broken": _GOOD_BROKEN,
            "fixed": _GOOD_FIXED,
            "looks_needle": "rsync -avz ./a/",
        },
        reserved=set(),
    )
    assert spec and err == ""
    out = m.materialize_aln_pack(tmp_path, spec)
    assert out["pack_name"] == "catalog_aln_rsync_aln_demo"
    assert (tmp_path / out["pack_name"] / "task.json").is_file()
    assert (tmp_path / out["pack_name"] / "golden.patch").is_file()
