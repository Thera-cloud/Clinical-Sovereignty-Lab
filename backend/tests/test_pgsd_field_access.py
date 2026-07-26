"""
PGSD Phase B/B2/C/D access + field services — offline-safe tests.  # QUANTUM-CRYSTAL-ARCH

Loads modules by file path. Avoids app.services.__init__ / numpy macOS FPE in CI sandboxes.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
_SERVICES = _BACKEND / "app" / "services"


def _load(name: str, filename: str):
    path = _SERVICES / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_triggers = _load("pgsd_triggers_ut", "pgsd_triggers.py")
_field = _load("pgsd_field_engine_ut", "pgsd_field_engine.py")
_pmb = _load("pgsd_pmb_bridge_ut", "pgsd_pmb_bridge.py")
_brief = _load("pgsd_briefing_ut", "pgsd_briefing.py")
_scorer_mod = _load("pgsd_discernment_scorer_ut", "pgsd_discernment_scorer.py")


class _NullPool:
    def acquire(self):
        raise RuntimeError("no db in offline test")


def test_triggers_quarantine_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGSD_ENABLED", "true")
    fake_router = MagicMock()
    fake_router.enabled = True
    fake_router.schedule_for_user.return_value = True

    def _q(raw_id: str, source: str = "") -> bool:
        return (raw_id or "").strip().lower().startswith("audit_")

    with patch.object(_triggers, "_resolve_router", return_value=fake_router), patch.object(
        _triggers, "_is_quarantined", side_effect=_q
    ):
        assert _triggers.notify_user("audit_client", source="crystallizer") is False
        fake_router.schedule_for_user.assert_not_called()
        assert _triggers.notify_user("CLIENT_REAL_ID", source="crystallizer") is True
        fake_router.schedule_for_user.assert_called_once()


def test_field_engine_pure_python_eig_2site() -> None:
    h = _field._build_site_hamiltonian(
        {"d1_valence": 0.1, "d5_integration": 0.2},
        j_coupling=0.5,
        h_drive=0.1,
    )
    assert len(h) == 2
    evals, _ = _field._eigh_symmetric_pure(h)
    assert len(evals) == 2
    assert evals[0] <= evals[1]
    local = h[0][0]
    j = abs(h[0][1])
    assert abs(evals[0] - (local - j)) < 1e-5 or abs(evals[0] - (local + j)) < 1e-5


@pytest.mark.asyncio
async def test_discernment_scorer_empty_db_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGSD_ENABLED", "true")
    monkeypatch.setenv("ENABLE_PGSD_ACCESS", "true")
    assert _scorer_mod.access_enabled() is True
    # Avoid PGSDEngine import (numpy) — disabled path returns empty
    monkeypatch.setenv("ENABLE_PGSD_ACCESS", "false")
    scorer = _scorer_mod.PGSDDiscernmentScorer(db_pool=_NullPool())
    result = await scorer.score_user("CLIENT_NOPE")
    assert result["score_composite"] == 0.5
    assert result["claim_count"] == 0


@pytest.mark.asyncio
async def test_briefing_returns_empty_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PGSD_ENABLED", raising=False)
    monkeypatch.delenv("ENABLE_PGSD_ACCESS", raising=False)
    monkeypatch.delenv("ENABLE_PGSD_FIELD", raising=False)
    text = await _brief.build_field_briefing(_NullPool(), "CLIENT_X")
    assert text == ""


def test_pmb_bridge_append_no_raise() -> None:
    pmb: Dict[str, Any] = {"crisis_precursors": [{"region_id": 1, "source": "legacy"}]}
    _pmb.merge_crisis_precursors(
        pmb,
        [
            {
                "id": 2,
                "d1_valence": 0.1,
                "d2_arousal": 0.2,
                "d3_relational": 0.0,
                "d4_temporal": -0.3,
                "d5_integration": 0.4,
                "radius": 0.25,
                "source_event_id": "t",
            }
        ],
    )
    assert len(pmb["crisis_precursors"]) >= 1
