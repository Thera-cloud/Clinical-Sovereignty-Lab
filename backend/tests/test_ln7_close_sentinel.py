"""Offline unit tests for LN7 Close Sentinel (no DB / no numpy trap).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

SERVICES = Path(__file__).resolve().parents[1] / "app" / "services"


def _load(mod_name: str, path: Path):
    import sys

    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def engine():
    import sys
    import types

    sys.modules.setdefault("app", types.ModuleType("app"))
    sys.modules.setdefault("app.services", types.ModuleType("app.services"))
    return _load(
        "app.services.ln7_close_percent_engine",
        SERVICES / "ln7_close_percent_engine.py",
    )


@pytest.fixture(scope="module")
def sentinel(engine):
    return _load(
        "app.services.ln7_close_sentinel",
        SERVICES / "ln7_close_sentinel.py",
    )

def test_utc_day_key_is_utc_date(sentinel):
    from datetime import datetime, timezone

    assert sentinel.utc_day_key(datetime(2026, 8, 31, 23, 0, tzinfo=timezone.utc)) == "2026-08-31"


def test_already_sent_utc_day_true_and_false(sentinel):
    class _Conn:
        def __init__(self, hit):
            self.hit = hit
            self.query = None

        async def fetchval(self, query, *args):
            self.query = query
            return 1 if self.hit else None

    async def _run():
        yes = _Conn(True)
        no = _Conn(False)
        assert await sentinel.already_sent_utc_day(yes, "2026-08-31") is True
        assert await sentinel.already_sent_utc_day(no, "2026-08-31") is False
        assert "ln7_close_digest_snapshots" in (yes.query or "")

    asyncio.run(_run())


def test_run_close_digest_skips_when_already_sent_today(sentinel):
    class _Conn:
        async def fetchval(self, query, *args):
            return 1

    class _Pool:
        def acquire(self):
            return self

        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *a):
            return False

    async def _run():
        out = await sentinel.run_close_digest(_Pool())
        assert out == {"ok": True, "skipped": "already_sent_today"}

    asyncio.run(_run())


def test_compose_digest_fixed_sections(engine, sentinel):
    ItemScore = engine.ItemScore
    scores = [
        ItemScore("#9", "CLOSE", "d", "queens", 1.0, 100.0, "100", "e9"),
        ItemScore("#10", "CLOSE", "d", "queens", 1.0, 50.0, "50(streak 1/2)", "e10"),
        ItemScore("#16", "CLOSE", "d", "queens", 1.0, None, "UNKNOWN", "e16"),
        ItemScore("#14a", "CLOSE", "d", "queens", 1.0, 100.0, "100", "e14a"),
        ItemScore("R4", "CLOSE", "d", "queens", 0.5, None, "UNKNOWN", ""),
        ItemScore("W", "CLOSE", "d", "queens", 0.5, None, "UNKNOWN", ""),
        ItemScore("#1", "CRANK", "d", "clinician", 1.0, 30.0, "30", "e1",
                  blocked_owner="clinician", blocked_hint="score stems"),
        ItemScore("#2", "CRANK", "d", "queens", 1.0, 100.0, "100*", "e2"),
        ItemScore("#4", "CRANK", "d", "ceo", 1.0, 40.0, "40", "e4"),
        ItemScore("#5", "CRANK", "d", "cursor", 2.0, 0.0, "0", "e5",
                  blocked_owner="cursor", blocked_hint="address-gate"),
        ItemScore("#6", "CRANK", "d", "ceo", 2.0, 30.0, "30", "e6"),
        ItemScore("#8", "CRANK", "d", "ceo", 2.0, 0.0, "0", "e8"),
        ItemScore("#11", "CRANK", "d", "queens", 1.0, 100.0, "100", "evidence_id:12"),
        ItemScore("#12", "CRANK", "d", "clinician", 1.0, 40.0, "40", "e12"),
        ItemScore("#3", "HUMAN", "d", "external", 1.0, 100.0, "N/A", "e3"),
        ItemScore("#7", "HUMAN", "d", "clinician", 2.0, 20.0, "20", "e7"),
        ItemScore("#13", "HUMAN", "d", "ceo", 1.0, 0.0, "0/2", "e13"),
        ItemScore("#15", "HUMAN", "d", "ceo", 1.0, None, "UNKNOWN", "e15"),
        ItemScore("#17", "HUMAN", "d", "ceo", 2.0, 0.0, "0", "e17"),
    ]
    body, overall, blocked, alerts = sentinel.compose_digest(
        scores, day_index=2, prev_overall=69.0, alerts=[]
    )
    assert "LN7 CLOSE — Day 2" in body
    assert "CLOSE  " in body and "CRANK  " in body and "HUMAN  " in body
    assert "BLOCKED ON YOU:" in body
    assert "BLOCKED ON CURSOR: address-gate" in body
    assert "UNKNOWN" in body  # #16 or #15
    assert overall is not None
    assert any(b["owner"] == "clinician" for b in blocked)


def test_veto_miss_inject_alert(engine):
    async def _run():
        base = {
            "item_id": "#2",
            "tier": "CRANK",
            "title": "veto",
            "owner": "queens",
            "weight": 1.0,
            "pct": None,
            "display": "UNKNOWN",
            "evidence_uri": "evidence_id:11",
        }
        sc = await engine._h_veto(None, base, {}, {"force_veto_miss": True})
        assert sc.pct == 0.0
        assert sc.alerts and "VETO MISS" in sc.alerts[0]

    asyncio.run(_run())


def test_unknown_not_estimated_when_ci_absent(engine):
    async def _run():
        class _Conn:
            async def fetchrow(self, *a, **k):
                return None

        base = {
            "item_id": "#16",
            "tier": "CLOSE",
            "title": "CI",
            "owner": "queens",
            "weight": 1.0,
            "pct": None,
            "display": "UNKNOWN",
            "evidence_uri": "ci",
        }
        sc = await engine._h_ci(_Conn(), base, {}, {})
        assert sc.pct is None
        assert sc.display == "UNKNOWN"

    asyncio.run(_run())


def test_pilot_path_double_weight_in_overall(engine):
    ItemScore = engine.ItemScore
    # Two items: pilot-path at 0 weight 2, close at 100 weight 1 → overall 33.3
    scores = [
        ItemScore("#9", "CLOSE", "d", "queens", 1.0, 100.0, "100", "u"),
        ItemScore("#5", "CRANK", "d", "cursor", 2.0, 0.0, "0", "u"),
    ]
    o = engine.overall_weighted(scores)
    assert o == pytest.approx(33.3, abs=0.1)


def test_crisis_gt_uses_tally_n(engine):
    async def _run():
        base = {
            "item_id": "#7",
            "tier": "HUMAN",
            "title": "Crisis GT",
            "owner": "clinician",
            "weight": 2.0,
            "pct": None,
            "display": "UNKNOWN",
            "evidence_uri": "",
        }
        sc = await engine._h_crisis_gt(None, base, {"target_n": 30}, {"crisis_gt_n": 12})
        assert sc.pct == pytest.approx(40.0)
        assert sc.display == "12/30"

    asyncio.run(_run())


def test_inversion_census_pass_bar(engine, tmp_path, monkeypatch):
    marker = tmp_path / "inversion_census.json"
    marker.write_text(
        json.dumps(
            {
                "perspective_inversion_rate": 0.0087,
                "stall_family_pct": 0.0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(engine, "_resolve_path", lambda rel: marker if "inversion" in rel else None)
    async def _run():
        base = {
            "item_id": "#12",
            "tier": "CRANK",
            "title": "inversion",
            "owner": "clinician",
            "weight": 1.0,
            "pct": None,
            "display": "UNKNOWN",
            "evidence_uri": "",
        }
        sc = await engine._h_inversion(None, base, {"stall_max_pct": 10}, {})
        assert sc.pct == 100.0

    asyncio.run(_run())
