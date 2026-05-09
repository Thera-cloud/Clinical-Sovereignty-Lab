"""CI version-lock test for linguistic_arousal_load.

Mirrors the pattern in test_specialized_resources_version_lock.py.

Why this test exists
--------------------
The clinical_arousal_lexicon and somatic_resource_prebuffers JSON files in
backend/data/lexicons/ are clinician-authored content under Gap D review
workflow. Every edit to those files must:

  1. Bump REGISTRY_VERSION (so audit logs can correlate "which version of the
     arousal lexicon was active when this disclosure was scored")
  2. Recompute REGISTRY_CONTENT_HASH (so the content<->version pairing is
     verified at CI time, not by hope)

Without this enforcement, a clinician could edit the lexicon without bumping
the version string, and 7-year audit retention would lose the ability to
forensically reconstruct what scoring policy was in effect on a given date.

If this test fails:
  - You edited backend/data/lexicons/clinical_arousal_lexicon_*.json or
    backend/data/lexicons/somatic_resource_prebuffers_*.json
  - Recompute the hash:
      python -c "from backend.app.services.linguistic_arousal_load import \
                 compute_content_hash; print(compute_content_hash())"
  - Update REGISTRY_VERSION (semver bump or date suffix change)
  - Update REGISTRY_CONTENT_HASH to the new value
  - Commit both in the same PR
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "backend" / "app" / "services" / "linguistic_arousal_load.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "linguistic_arousal_load_under_test", str(MODULE_PATH)
    )
    assert spec is not None and spec.loader is not None, "spec load failed"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["linguistic_arousal_load_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_registry_version_format():
    mod = _load_module()
    assert isinstance(mod.REGISTRY_VERSION, str)
    assert mod.REGISTRY_VERSION, "REGISTRY_VERSION must not be empty"
    # Same shape as specialized_resources / detector modules
    parts = mod.REGISTRY_VERSION.split("-", 1)
    assert len(parts) >= 1
    semver = parts[0]
    components = semver.split(".")
    assert len(components) == 3, f"semver part must be MAJOR.MINOR.PATCH, got {semver}"
    for c in components:
        assert c.isdigit(), f"semver component '{c}' must be numeric"


def test_registry_content_hash_format():
    mod = _load_module()
    assert isinstance(mod.REGISTRY_CONTENT_HASH, str)
    assert len(mod.REGISTRY_CONTENT_HASH) == 64, "must be sha256 hex (64 chars)"
    int(mod.REGISTRY_CONTENT_HASH, 16)  # must be valid hex


def test_content_hash_is_aligned():
    """The recorded REGISTRY_CONTENT_HASH must match the live computation.

    Failure means: someone edited a hashed lexicon file (or this module's seed)
    without bumping the recorded hash. CI fails the PR until both are updated
    together.
    """
    mod = _load_module()
    actual = mod.compute_content_hash()
    assert actual == mod.REGISTRY_CONTENT_HASH, (
        f"content hash drift detected.\n"
        f"  REGISTRY_VERSION       = {mod.REGISTRY_VERSION}\n"
        f"  REGISTRY_CONTENT_HASH  = {mod.REGISTRY_CONTENT_HASH}\n"
        f"  actual_hash            = {actual}\n"
        "If you edited backend/data/lexicons/*.json or the module seed, "
        "bump REGISTRY_VERSION + REGISTRY_CONTENT_HASH together in the same PR."
    )


def test_assert_version_aligned_does_not_raise():
    mod = _load_module()
    mod.assert_version_aligned()  # raises AssertionError if drifted


def test_production_stubs_present():
    """The en-US production stubs must ship with the repo.

    Catches the deploy-bundle exclusion bug class (someone forgot to add
    backend/data/lexicons/ to the Docker image). The module's import-time
    invariant also catches this; this test catches it at CI before the merge.
    """
    arousal = REPO_ROOT / "backend" / "data" / "lexicons" / "clinical_arousal_lexicon_en-US.json"
    prebuffer = REPO_ROOT / "backend" / "data" / "lexicons" / "somatic_resource_prebuffers_en-US.json"
    assert arousal.exists(), f"missing production stub: {arousal}"
    assert prebuffer.exists(), f"missing production stub: {prebuffer}"


def test_production_stubs_are_schema_valid():
    """Production stubs must parse and have the expected _meta + container shape."""
    import json

    arousal = REPO_ROOT / "backend" / "data" / "lexicons" / "clinical_arousal_lexicon_en-US.json"
    prebuffer = REPO_ROOT / "backend" / "data" / "lexicons" / "somatic_resource_prebuffers_en-US.json"

    arousal_data = json.loads(arousal.read_text(encoding="utf-8"))
    assert "_meta" in arousal_data
    assert "patterns" in arousal_data
    assert isinstance(arousal_data["patterns"], list)
    assert "version" in arousal_data["_meta"]
    assert "locale" in arousal_data["_meta"]
    assert "status" in arousal_data["_meta"]

    prebuffer_data = json.loads(prebuffer.read_text(encoding="utf-8"))
    assert "_meta" in prebuffer_data
    assert "buffers" in prebuffer_data
    assert isinstance(prebuffer_data["buffers"], list)


def test_auditor_self_check_passes():
    mod = _load_module()
    report = mod._auditor_self_check()
    if report["status"] == "fail":
        failed = {k: v for k, v in report["checks"].items() if v.get("status") == "fail"}
        pytest.fail(f"linguistic_arousal_load auditor failed: {failed}")
    assert report["status"] in ("ok", "warn")
