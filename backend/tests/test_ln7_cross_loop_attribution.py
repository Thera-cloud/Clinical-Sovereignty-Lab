"""Phase E2 — cross-loop attribution keys offline fences (importlib — avoid numpy FPE).

Covers:
  - ln7_outcome_envelope.cross_loop_attribution(): normalizes join keys, drops
    empty values, lets explicit kwargs override the source dict.
  - dual_coo_checklist.dual_coo_checklist_review(): disagreement envelope
    carries revision_id/patch_hash + attribution_json so it can be joined
    against shadow_fork/hive_burst/canary_eval envelopes for the same lineage.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

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


def test_cross_loop_attribution_drops_empty_and_unknown_keys():
    env = _load("app.services.ln7_outcome_envelope", SERVICES / "ln7_outcome_envelope.py")
    out = env.cross_loop_attribution(
        {"revision_id": "LN7-1", "patch_hash": "", "unrelated": "x"}
    )
    assert out == {"revision_id": "LN7-1"}


def test_cross_loop_attribution_extra_kwargs_override_source():
    env = _load("app.services.ln7_outcome_envelope", SERVICES / "ln7_outcome_envelope.py")
    out = env.cross_loop_attribution(
        {"evidence_uri": "s3://old"}, evidence_uri="s3://new", patch_hash="abc123"
    )
    assert out == {"evidence_uri": "s3://new", "patch_hash": "abc123"}


def test_cross_loop_attribution_none_source_ok():
    env = _load("app.services.ln7_outcome_envelope", SERVICES / "ln7_outcome_envelope.py")
    assert env.cross_loop_attribution(None) == {}
    assert env.cross_loop_attribution(None, revision_id="LN7-1") == {"revision_id": "LN7-1"}


def test_checklist_disagree_envelope_carries_join_keys():
    _load("app.services.ln7_frozen_config", SERVICES / "ln7_frozen_config.py")
    _load("app.services.ln7_outcome_envelope", SERVICES / "ln7_outcome_envelope.py")
    _load("app.services.flywheel_anomaly", SERVICES / "flywheel_anomaly.py")
    checklist = _load("app.services.dual_coo_checklist", SERVICES / "dual_coo_checklist.py")

    write_envelope_mock = AsyncMock(return_value="env-1")

    async def _run():
        with patch.object(
            checklist, "evaluate_evidence", AsyncMock(return_value={"agree": False, "items": []})
        ), patch(
            "app.services.flywheel_anomaly.notify_flywheel_anomaly", AsyncMock()
        ), patch(
            "app.services.ln7_outcome_envelope.write_envelope", write_envelope_mock
        ):
            return await checklist.dual_coo_checklist_review(
                "s3://evidence/1",
                db_pool=object(),
                evidence={"revision_id": "LN7-2026-08-01", "patch_hash": "abc123"},
            )

    result = asyncio.run(_run())

    assert result["agree"] is False
    write_envelope_mock.assert_awaited_once()
    _, kwargs = write_envelope_mock.await_args
    assert kwargs["revision_id"] == "LN7-2026-08-01"
    assert kwargs["patch_hash"] == "abc123"
    assert kwargs["attribution"]["revision_id"] == "LN7-2026-08-01"
    assert kwargs["attribution"]["patch_hash"] == "abc123"
    assert kwargs["attribution"]["evidence_uri"] == "s3://evidence/1"
