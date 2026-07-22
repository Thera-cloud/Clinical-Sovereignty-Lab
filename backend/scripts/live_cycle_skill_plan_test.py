#!/usr/bin/env python3
"""Live WS test: client1 / test123 — each cycle skill technique type.

Usage (from repo root, network required):
  python3 backend/scripts/live_cycle_skill_plan_test.py
"""

from __future__ import annotations

import asyncio
import json
import ssl
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import websockets
except ImportError:
    print("pip install websockets")
    sys.exit(1)

WS_URL = "wss://api.sovereignsanctuary.net/ws"
USER = "client1"
PASS = "test123"
SSH = ["ssh", "root@68.183.168.75"]

# (label, cycle_domain or None, force_template_id or None, modality)
TECHNIQUES: List[Tuple[str, Optional[str], Optional[str], str]] = [
    ("grounding", "emotional_state", None, "grounding"),
    ("mindfulness", "sexual_desire", None, "mindfulness"),
    ("CBT", "financial", None, "CBT"),
    ("DBT", None, "a1000001-0001-4000-8000-000000000001", "DBT"),
    ("ACT", None, "a1000001-0001-4000-8000-000000000003", "ACT"),
    ("DEAR MAN", None, "a1000001-0001-4000-8000-000000000004", "DBT"),
]

TRIGGER = (
    "I've been looping on the same hard feelings this week and keep getting stuck. "
    "I want something short I can practice between sessions."
)
ACCEPT = "Yes, let's try that practice — I'm in."
ADVANCE = "I practiced the step and finished the practice today."

# Optional local fidelity scorer (same heuristic as service)
try:
    sys.path.insert(0, str(__file__).rsplit("/scripts/", 1)[0])
    from app.services.cycle_skill_plan_service import score_skill_offer_fidelity
except Exception:
    score_skill_offer_fidelity = None  # type: ignore


def _psql(sql: str) -> str:
    # Pass SQL on stdin so quotes/newlines survive SSH.
    remote = (
        "docker exec -i nate_postgres "
        "psql -U nate_admin -d little_nate -v ON_ERROR_STOP=1 -tA"
    )
    r = subprocess.run(
        SSH + [remote],
        input=sql.strip() + "\n",
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip() or "psql failed")
    return (r.stdout or "").strip()


def reset_user_plans() -> None:
    _psql(
        """
        UPDATE nate_therapeutic_plans
        SET status = 'abandoned', updated_at = NOW() - INTERVAL '8 days'
        WHERE user_id IN ('client1', 'CLIENT_001')
          AND source = 'cycle_skill'
          AND status IN ('suggested', 'active', 'abandoned');
        """
    )
    _psql("DELETE FROM cycle_detections WHERE user_id IN ('client1', 'CLIENT_001');")


def seed_cycle(domain: str) -> None:
    _psql(
        f"""
        INSERT INTO cycle_detections
          (user_id, domain, detected_period_days, amplitude, confidence, method, detected_at)
        VALUES
          ('client1', '{domain}', 7.0, 0.8, 0.92, 'live_test', NOW()),
          ('CLIENT_001', '{domain}', 7.0, 0.8, 0.92, 'live_test', NOW());
        """
    )


def force_suggest(template_id: str, modality: str, domain: str = "live_test") -> str:
    out = _psql(
        f"""
        INSERT INTO nate_therapeutic_plans (
          user_id, template_id, title, total_steps, current_step, step_definitions,
          status, source, cycle_domain, modality
        )
        SELECT
          'client1',
          t.id,
          t.title,
          t.total_steps,
          1,
          t.step_definitions,
          'suggested',
          'cycle_skill',
          '{domain}',
          '{modality}'
        FROM plan_templates t
        WHERE t.id = '{template_id}'
        RETURNING id::text;
        """
    )
    return out.splitlines()[0] if out else ""


def plan_snapshot() -> str:
    return _psql(
        """
        SELECT COALESCE(string_agg(
          status || '|' || COALESCE(modality,'') || '|' || LEFT(title,40) || '|step' || current_step,
          '; '
        ), 'none')
        FROM nate_therapeutic_plans
        WHERE user_id IN ('client1', 'CLIENT_001')
          AND source = 'cycle_skill'
          AND status IN ('suggested', 'active', 'completed')
          AND started_at > NOW() - INTERVAL '2 hours';
        """
    )


async def _recv_until(
    ws, want_types: set, timeout: float = 90.0
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    deadline = time.monotonic() + timeout
    texts: List[str] = []
    last: Optional[Dict[str, Any]] = None
    while time.monotonic() < deadline:
        remaining = max(0.5, deadline - time.monotonic())
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except asyncio.TimeoutError:
            break
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        t = msg.get("type")
        if t in ("nate_response", "ai_response"):
            body = msg.get("text") or msg.get("response") or msg.get("message") or ""
            if body:
                texts.append(str(body))
            last = msg
            # keep draining briefly for stream end
            if t in want_types and len(texts) >= 1:
                # short grace for more chunks
                grace = time.monotonic() + 2.5
                while time.monotonic() < grace:
                    try:
                        raw2 = await asyncio.wait_for(ws.recv(), timeout=0.4)
                        m2 = json.loads(raw2)
                        if m2.get("type") in ("nate_response", "ai_response"):
                            b2 = m2.get("text") or m2.get("response") or ""
                            if b2:
                                texts.append(str(b2))
                            last = m2
                    except Exception:
                        break
                return last, texts
        if t in want_types and t not in ("nate_response", "ai_response"):
            return msg, texts
        if t in ("login_failed", "error"):
            return msg, texts
    return last, texts


async def login_session():
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    hw = f"live_cycle_skill_{int(time.time())}"
    ws = await websockets.connect(
        WS_URL, ssl=ssl_ctx, open_timeout=20, close_timeout=10, ping_interval=20, ping_timeout=60
    )
    raw = await asyncio.wait_for(ws.recv(), timeout=10)
    hello = json.loads(raw)
    if not (hello.get("type") == "connected" and hello.get("status") == "ready"):
        await ws.close()
        raise RuntimeError(f"bad handshake: {hello.get('type')}")
    await ws.send(
        json.dumps(
            {
                "type": "login_request",
                "username": USER,
                "password": PASS,
                "expected_role": "CLIENT",
                "hardware_id": hw,
            }
        )
    )
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        msg = json.loads(raw)
        if msg.get("type") == "login_success":
            return ws
        if msg.get("type") in ("login_failed", "error"):
            await ws.close()
            raise RuntimeError(f"login failed: {msg}")
    await ws.close()
    raise RuntimeError("login timeout")


async def chat(ws, text: str) -> str:
    await ws.send(
        json.dumps({"type": "nate_query", "text": text, "nate_query": text})
    )
    _, texts = await _recv_until(ws, {"nate_response", "ai_response"}, timeout=120)
    return " ".join(texts)[-1200:]


async def run_technique(
    label: str,
    domain: Optional[str],
    tpl_id: Optional[str],
    modality: str,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "technique": label,
        "modality": modality,
        "ok": False,
        "steps": {},
        "snippets": {},
        "db": {},
    }
    reset_user_plans()
    if domain:
        seed_cycle(domain)
        result["steps"]["seed"] = f"cycle:{domain}"
    elif tpl_id:
        pid = force_suggest(tpl_id, modality)
        result["steps"]["seed"] = f"force_suggest:{pid}"
        if not pid:
            result["error"] = "force_suggest failed"
            return result

    ws = await login_session()
    result["steps"]["login"] = "OK"
    try:
        # Turn 1: trigger suggest (cycle path) or load suggested context (force path)
        r1 = await chat(ws, TRIGGER)
        result["snippets"]["trigger"] = r1[:400]
        await asyncio.sleep(1.2)
        snap1 = plan_snapshot()
        result["db"]["after_trigger"] = snap1
        if modality.lower() not in snap1.lower() and label.lower() not in snap1.lower():
            if "suggested" not in snap1 and "active" not in snap1:
                result["error"] = f"no plan after trigger: {snap1}"
                return result

        r2 = await chat(ws, ACCEPT)
        result["snippets"]["accept"] = r2[:400]
        await asyncio.sleep(1.0)
        snap2 = plan_snapshot()
        result["db"]["after_accept"] = snap2
        if not snap2.startswith("active"):
            result["error"] = f"not active after accept: {snap2}"
            return result

        r3 = await chat(ws, ADVANCE)
        result["snippets"]["advance"] = r3[:400]
        await asyncio.sleep(1.0)
        snap3 = plan_snapshot()
        result["db"]["after_advance"] = snap3
        ok_advance = (
            "step2" in snap3
            or "step3" in snap3
            or "step4" in snap3
            or "completed" in snap3
            or "suggested|" in snap3
        )
        result["steps"]["advance"] = "OK" if ok_advance else f"weak:{snap3}"
        # Clinical quality: score offer turns (trigger + accept)
        if score_skill_offer_fidelity:
            s_trig = score_skill_offer_fidelity(r1, modality=modality)
            s_acc = score_skill_offer_fidelity(r2, modality=modality)
            result["scores"] = {
                "trigger": s_trig,
                "accept": s_acc,
                "mean": round((s_trig + s_acc) / 2, 2),
            }
            result["ok"] = ok_advance and result["scores"]["mean"] >= 4.0
            if result["scores"]["mean"] < 4.0:
                result["error"] = (
                    f"fidelity mean {result['scores']['mean']} < 4 "
                    f"(trigger={s_trig}, accept={s_acc})"
                )
        else:
            result["ok"] = bool(ok_advance)
    finally:
        try:
            await ws.close()
        except Exception:
            pass
    return result


async def main() -> int:
    print(f"Live cycle-skill test → {WS_URL} as {USER}")
    results = []
    for label, domain, tpl, modality in TECHNIQUES:
        print(f"\n=== {label} ({modality}) ===")
        try:
            r = await run_technique(label, domain, tpl, modality)
        except Exception as e:
            r = {"technique": label, "modality": modality, "ok": False, "error": str(e)}
        results.append(r)
        status = "PASS" if r.get("ok") else "FAIL"
        print(f"{status}: {json.dumps({k: r.get(k) for k in ('db', 'error', 'steps')}, default=str)}")
        await asyncio.sleep(1.5)

    passed = sum(1 for r in results if r.get("ok"))
    print(f"\nSUMMARY: {passed}/{len(results)} technique paths OK")
    print(json.dumps(results, indent=2, default=str)[:8000])
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
