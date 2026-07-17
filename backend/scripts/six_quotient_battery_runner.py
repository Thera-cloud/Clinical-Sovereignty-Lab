#!/usr/bin/env python3
"""
Six-Quotient Battery Runner — WS capture for external scoring.

Usage:
  # Dry-run (no WS) — validates scenario pack + pregrade plumbing
  python backend/scripts/six_quotient_battery_runner.py --dry-run

  # Live against staging bridge
  BRIDGE_WS_URL=ws://127.0.0.1:8766/ws \\
  TEST_USERNAME=audit_client TEST_PASSWORD=... \\
  python backend/scripts/six_quotient_battery_runner.py --env staging

  # Persist run row (requires DATABASE_URL)
  python backend/scripts/six_quotient_battery_runner.py --dry-run --persist

Scoring is NEVER performed here. Output is for external evaluators.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow `python backend/scripts/...` from repo root
_REPO = Path(__file__).resolve().parents[2]
_BACKEND = _REPO / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

DEFAULT_SCENARIOS = (
    _BACKEND / "app" / "data" / "six_quotient_scenarios_v4.json"
    if (_BACKEND / "app" / "data" / "six_quotient_scenarios_v4.json").exists()
    else _BACKEND / "tests" / "six_quotient_scenarios_v4.json"
)


def load_scenarios(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def _run_ws_battery(
    scenarios: List[Dict[str, Any]],
    *,
    ws_url: str,
    username: str,
    password: str,
    role: str,
    section_filter: Optional[str],
    scenario_filter: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    # Import local test client pattern without pulling tests package
    import websockets

    results: List[Dict[str, Any]] = []
    selected = scenarios
    if section_filter:
        selected = [s for s in selected if s["section"].upper() == section_filter.upper()]
    if scenario_filter:
        selected = [s for s in selected if s["id"].upper() == scenario_filter.upper()]
    if limit > 0:
        selected = selected[:limit]

    for sc in selected:
        result = await _one_scenario_ws(
            websockets,
            ws_url=ws_url,
            username=username,
            password=password,
            role=role,
            scenario=sc,
        )
        results.append(result)
        await asyncio.sleep(float(os.getenv("INTER_SESSION_DELAY", "6")))
    return results


async def _one_scenario_ws(
    websockets,
    *,
    ws_url: str,
    username: str,
    password: str,
    role: str,
    scenario: Dict[str, Any],
) -> Dict[str, Any]:
    origin = {"Origin": "https://app.sovereignsanctuary.net"}
    kwargs = dict(ping_interval=30, ping_timeout=60, close_timeout=10, max_size=2**20)
    t0 = time.time()
    response = ""
    err = ""
    try:
        try:
            ws = await websockets.connect(ws_url, additional_headers=origin, **kwargs)
        except TypeError:
            ws = await websockets.connect(ws_url, extra_headers=origin, **kwargs)
        async with ws:
            hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if hello.get("type") != "connected":
                err = f"bad_handshake:{hello.get('type')}"
            else:
                await ws.send(json.dumps({
                    "type": "login_request",
                    "username": username,
                    "password": password,
                    "expected_role": role,
                }))
                login = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                if login.get("type") != "login_success":
                    err = f"login_failed:{login.get('message') or login.get('type')}"
                else:
                    await ws.send(json.dumps({
                        "type": "nate_query",
                        "text": scenario["client_says"],
                        "nate_query": scenario["client_says"],
                    }))
                    full = ""
                    got = False
                    deadline = time.time() + float(os.getenv("RESPONSE_TIMEOUT", "90"))
                    while time.time() < deadline:
                        try:
                            timeout = 8.0 if got else min(30.0, deadline - time.time())
                            if timeout <= 0:
                                break
                            msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
                            data = json.loads(msg) if isinstance(msg, str) else {}
                            if data.get("type") == "nate_response" and data.get("text"):
                                full = data["text"]
                                got = True
                            elif data.get("type") == "error":
                                err = data.get("message", "error")
                                break
                        except asyncio.TimeoutError:
                            if got:
                                break
                    response = (full or "").strip()
    except Exception as e:
        err = str(e)

    duration = time.time() - t0
    return {
        "scenario_id": scenario["id"],
        "section": scenario["section"],
        "title": scenario["title"],
        "rubric_focus": scenario["rubric_focus"],
        "client_says": scenario["client_says"],
        "response": response,
        "duration_seconds": round(duration, 2),
        "provider": "",
        "odpe_signal": "",
        "error": err,
    }


def _dry_run_results(scenarios: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    selected = scenarios[: limit or len(scenarios)]
    out = []
    for sc in selected:
        out.append({
            "scenario_id": sc["id"],
            "section": sc["section"],
            "title": sc["title"],
            "rubric_focus": sc["rubric_focus"],
            "client_says": sc["client_says"],
            "response": (
                f"[DRY-RUN] Placeholder response for {sc['id']}. "
                "External scoring required; this text is not a clinical answer."
            ),
            "duration_seconds": 0.01,
            "provider": "dry_run",
            "odpe_signal": "",
            "error": "",
        })
    return out


async def persist_run(
    *,
    pack: Dict[str, Any],
    results: List[Dict[str, Any]],
    environment: str,
    git_hash: str,
    status: str,
    error_message: str = "",
) -> Optional[str]:
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        print("[persist] DATABASE_URL unset — skip")
        return None
    try:
        import asyncpg
    except ImportError:
        print("[persist] asyncpg missing — skip")
        return None

    run_id = str(uuid.uuid4())
    payload = {
        "battery_version": pack.get("battery_version", "v4"),
        "rubric": pack.get("rubric"),
        "results": results,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            """INSERT INTO six_quotient_runs
               (id, battery_version, environment, git_hash, status,
                results_json, finished_at, error_message)
               VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb, NOW(), $7)""",
            run_id,
            pack.get("battery_version", "v4"),
            environment,
            git_hash,
            status,
            json.dumps(payload),
            error_message or "",
        )
    finally:
        await conn.close()
    print(f"[persist] run_id={run_id} status={status}")
    return run_id


def _load_pregrade_battery():
    """Avoid app.services.__init__ (numpy) when running as a CLI script."""
    import importlib.util
    import types

    if "app" not in sys.modules:
        sys.modules["app"] = types.ModuleType("app")
    if "app.services" not in sys.modules:
        svc = types.ModuleType("app.services")
        svc.__path__ = [str(_BACKEND / "app" / "services")]  # type: ignore[attr-defined]
        sys.modules["app.services"] = svc
    path = _BACKEND / "app" / "services" / "six_quotient_pregrader.py"
    name = "app.services.six_quotient_pregrader"
    if name in sys.modules:
        return sys.modules[name].pregrade_battery
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod.pregrade_battery


async def main_async(args: argparse.Namespace) -> int:
    pregrade_battery = _load_pregrade_battery()

    pack = load_scenarios(Path(args.scenarios))
    scenarios = pack["scenarios"]
    git_hash = args.git_hash or os.getenv("GIT_HASH", "") or _git_hash()

    if args.dry_run:
        raw = _dry_run_results(scenarios, args.limit)
    else:
        ws_url = args.ws_url or os.getenv("BRIDGE_WS_URL", "ws://127.0.0.1:8766/ws")
        raw = await _run_ws_battery(
            scenarios,
            ws_url=ws_url,
            username=args.username or os.getenv("TEST_USERNAME", "audit_client"),
            password=args.password or os.getenv("TEST_PASSWORD", os.getenv("AUDIT_CLIENT_PASSWORD", "")),
            role=args.role or os.getenv("TEST_ROLE", "CLIENT"),
            section_filter=args.section,
            scenario_filter=args.scenario,
            limit=args.limit,
        )

    graded = pregrade_battery(raw)
    out_dir = Path(args.out_dir or (_REPO / "tests" / f"six_quotient_{datetime.now().strftime('%Y%m%d_%H%M%S')}"))
    out_dir.mkdir(parents=True, exist_ok=True)
    master = {
        "assessment": "Little Nate Six-Quotient Intelligence Assessment",
        "battery_version": pack.get("battery_version", "v4"),
        "environment": args.env,
        "git_hash": git_hash,
        "scoring": "EXTERNAL — no automated scoring",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": graded,
        "pregrade_note": "flags only; scores must be submitted via /api/admin/six-quotient/scores",
    }
    out_path = out_dir / "master_results.json"
    out_path.write_text(json.dumps(master, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path} ({len(graded)} scenarios)")

    status = "awaiting_scores"
    errs = [r for r in graded if r.get("error") or r.get("pregrade", {}).get("empty_response")]
    if not args.dry_run and len(errs) == len(graded):
        status = "failed"

    if args.persist:
        await persist_run(
            pack=pack,
            results=graded,
            environment=args.env,
            git_hash=git_hash,
            status=status if status != "failed" else "failed",
            error_message="; ".join(e.get("error", "") for e in errs if e.get("error"))[:500],
        )
    return 0


def _git_hash() -> str:
    try:
        import subprocess
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(_REPO), text=True
        ).strip()
    except Exception:
        return ""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Six-Quotient battery runner")
    p.add_argument("--scenarios", default=str(DEFAULT_SCENARIOS))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--persist", action="store_true")
    p.add_argument("--env", default="staging")
    p.add_argument("--ws-url", default="")
    p.add_argument("--username", default="")
    p.add_argument("--password", default="")
    p.add_argument("--role", default="")
    p.add_argument("--section", default="")
    p.add_argument("--scenario", default="")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--out-dir", default="")
    p.add_argument("--git-hash", default="")
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(main_async(args)))
