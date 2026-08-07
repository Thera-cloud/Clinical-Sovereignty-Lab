#!/usr/bin/env python3
"""Bare-script self-test: mock veto miss → alert line (no pytest/package __init__).

Avoids `import app.services` (Mac numpy trap via services/__init__.py).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

SERVICES = Path(__file__).resolve().parents[1] / "app" / "services"


def _load(name: str, path: Path):
    mod_name = f"app.services.{name}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def _bootstrap_pkg():
    sys.modules.setdefault("app", types.ModuleType("app"))
    sys.modules.setdefault("app.services", types.ModuleType("app.services"))


async def _veto_inject_unit(engine) -> None:
    base = {
        "item_id": "#2",
        "tier": "CRANK",
        "title": "Safety veto misses = 0",
        "owner": "queens",
        "weight": 1.0,
        "pct": None,
        "display": "UNKNOWN",
        "evidence_uri": "evidence_id:11",
    }
    sc = await engine._h_veto(None, base, {}, {"force_veto_miss": True})
    assert sc.pct == 0.0, sc
    assert any("VETO MISS" in a for a in sc.alerts), sc.alerts
    print("PASS: veto inject → pct=0 + alert")


def _digest_format_unit(engine, sentinel) -> None:
    ItemScore = engine.ItemScore
    scores = [
        ItemScore("#9", "CLOSE", "Data budget", "queens", 1.0, 100.0, "100", "uri:9"),
        ItemScore("#10", "CLOSE", "Canary", "queens", 1.0, 50.0, "50(streak 1/2)", "uri:10"),
        ItemScore("#16", "CLOSE", "CI", "queens", 1.0, 100.0, "100", "uri:16"),
        ItemScore("#14a", "CLOSE", "Flags", "queens", 1.0, 100.0, "100", "uri:14a"),
        ItemScore("R4", "CLOSE", "R4", "queens", 0.5, 60.0, "60", "uri:r4"),
        ItemScore("W", "CLOSE", "W", "queens", 0.5, 60.0, "60", "uri:w"),
        ItemScore(
            "#1", "CRANK", "kappa", "clinician", 1.0, 30.0, "30", "uri:1",
            blocked_owner="clinician",
            blocked_hint="score sitting for +1 stems (#7 → unlocks #1)",
        ),
        ItemScore(
            "#2", "CRANK", "veto", "queens", 1.0, 0.0, "0*", "uri:2",
            alerts=["VETO MISS (injected self-test) — screener suspended"],
        ),
        ItemScore("#4", "CRANK", "rel", "ceo", 1.0, 40.0, "40", "uri:4"),
        ItemScore(
            "#5", "CRANK", "fn", "cursor", 2.0, 0.0, "0", "uri:5",
            blocked_owner="cursor", blocked_hint="address-gate commit (#5)",
        ),
        ItemScore(
            "#6", "CRANK", "fp", "ceo", 2.0, 0.0, "0", "uri:6",
            blocked_owner="ceo", blocked_hint="RED review verdict (#6 threshold)",
        ),
        ItemScore("#8", "CRANK", "obs", "ceo", 2.0, 0.0, "0", "uri:8"),
        ItemScore("#11", "CRANK", "pack", "queens", 1.0, 100.0, "100", "evidence_id:12"),
        ItemScore("#12", "CRANK", "inv", "clinician", 1.0, 40.0, "40", "uri:12"),
        ItemScore("#3", "HUMAN", "inter", "external", 1.0, 100.0, "N/A", "uri:3"),
        ItemScore("#7", "HUMAN", "crisis", "clinician", 2.0, 0.0, "0", "uri:7"),
        ItemScore("#13", "HUMAN", "memos", "ceo", 1.0, 0.0, "0/2", "uri:13"),
        ItemScore("#15", "HUMAN", "pre6", "ceo", 1.0, None, "UNKNOWN", "uri:15"),
        ItemScore("#17", "HUMAN", "pilot", "ceo", 2.0, 0.0, "0", "uri:17"),
    ]
    alerts = ["VETO MISS (injected self-test) — screener suspended"]
    body, _overall, blocked, out_alerts = sentinel.compose_digest(
        scores, day_index=1, prev_overall=None, alerts=alerts
    )
    assert "LN7 CLOSE — Day 1" in body
    assert "BLOCKED ON YOU:" in body
    assert "BLOCKED ON CURSOR:" in body
    assert "BLOCKED ON CEO:" in body
    assert "ALERTS:" in body and "VETO MISS" in body
    assert "VETO MISS" in ";".join(out_alerts)
    assert any(b["owner"] == "cursor" for b in blocked)
    print("PASS: digest format + veto alert line")
    print("--- sample ---")
    print(body)


def main() -> int:
    _bootstrap_pkg()
    engine = _load("ln7_close_percent_engine", SERVICES / "ln7_close_percent_engine.py")
    sentinel = _load("ln7_close_sentinel", SERVICES / "ln7_close_sentinel.py")
    _digest_format_unit(engine, sentinel)
    asyncio.run(_veto_inject_unit(engine))
    print("ALL SELF-TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
