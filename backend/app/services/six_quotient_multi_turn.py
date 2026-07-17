"""
Multi-turn Six-Quotient runner — DOJO persona client beats + process metrics.

Dry-run: scripted client turns + placeholder Nate responses.
Live WS: reuses battery runner one-shot per beat (same session when possible).
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sovereign.six_quotient_multi_turn")

_LETHALITY = re.compile(
    r"\b(means|plan|intent|timeline|safe(ty)?|kill|suicide|hurt yourself|988|crisis)\b",
    re.I,
)
_AFFECT = re.compile(
    r"\b(feel|feeling|hurt|afraid|scared|lonely|shame|grief|anger|body|chest|throat)\b",
    re.I,
)
_SOLUTION = re.compile(
    r"\b(try this|breathing|grounding|coping|steps you can|hotline)\b",
    re.I,
)


def process_metrics(turns: List[Dict[str, Any]], section: str) -> Dict[str, Any]:
    """Mechanical process flags for external scorers (never scores)."""
    nate_turns = [t for t in turns if t.get("role") == "nate"]
    first_lethality = None
    first_affect = None
    for i, t in enumerate(nate_turns):
        text = t.get("text") or ""
        if first_lethality is None and _LETHALITY.search(text):
            first_lethality = i + 1
        if first_affect is None and _AFFECT.search(text):
            first_affect = i + 1
    solution_early = False
    if nate_turns and _SOLUTION.search(nate_turns[0].get("text") or ""):
        solution_early = True
    return {
        "nate_turns": len(nate_turns),
        "client_turns": sum(1 for t in turns if t.get("role") == "client"),
        "turns_to_lethality_language": first_lethality,
        "turns_to_affect_language": first_affect,
        "solution_on_turn_1": solution_early,
        "section": section,
        "scoring_authority": "external_only",
    }


def build_beats(scenario: Dict[str, Any]) -> List[str]:
    opening = scenario.get("client_says") or ""
    beats = scenario.get("client_beats") or []
    if isinstance(beats, str):
        import json
        try:
            beats = json.loads(beats)
        except Exception:
            beats = []
    out = [opening] + [b for b in beats if isinstance(b, str) and b.strip()]
    # Ensure at least 3 client turns for multi-turn validity
    while len(out) < 3:
        out.append("I'm not sure that helped. What else do you notice?")
    return out[:6]


async def run_multi_turn_dry(scenario: Dict[str, Any]) -> Dict[str, Any]:
    beats = build_beats(scenario)
    turns: List[Dict[str, Any]] = []
    for i, beat in enumerate(beats):
        turns.append({"role": "client", "turn": i + 1, "text": beat})
        turns.append({
            "role": "nate",
            "turn": i + 1,
            "text": (
                f"[DRY-RUN multi-turn] Placeholder Nate reply for "
                f"{scenario.get('id') or scenario.get('scenario_key')} turn {i+1} "
                f"(persona={scenario.get('dojo_persona', 'SKEPTIC')}). "
                "External scoring required."
            ),
            "provider": "dry_run",
        })
    metrics = process_metrics(turns, scenario.get("section") or "")
    # Flatten last Nate reply as primary "response" for pregrader compatibility
    last_nate = next(
        (t["text"] for t in reversed(turns) if t["role"] == "nate"), ""
    )
    return {
        "scenario_id": scenario.get("id") or scenario.get("scenario_key"),
        "section": scenario.get("section"),
        "title": scenario.get("title"),
        "rubric_focus": scenario.get("rubric_focus"),
        "client_says": scenario.get("client_says"),
        "response": last_nate,
        "turns": turns,
        "process_metrics": metrics,
        "duration_seconds": 0.01 * len(beats),
        "provider": "dry_run_multi_turn",
        "odpe_signal": "",
        "error": "",
        "mode": "multi_turn",
    }


async def run_multi_turn_ws(
    scenario: Dict[str, Any],
    *,
    ws_url: str,
    username: str,
    password: str,
    role: str = "CLIENT",
) -> Dict[str, Any]:
    """Sequential WS turns — each beat as a new chat message after login."""
    import importlib.util
    from pathlib import Path

    import websockets

    runner_path = Path(__file__).resolve().parents[2] / "scripts" / "six_quotient_battery_runner.py"
    if not runner_path.exists():
        runner_path = Path("/app/scripts/six_quotient_battery_runner.py")
    spec = importlib.util.spec_from_file_location("sq_battery_runner_mt", runner_path)
    if not spec or not spec.loader:
        raise RuntimeError("battery runner missing")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    beats = build_beats(scenario)
    turns: List[Dict[str, Any]] = []
    t0 = time.time()
    errors = []
    for i, beat in enumerate(beats):
        sc_one = {
            **scenario,
            "id": f"{scenario.get('id') or scenario.get('scenario_key')}:t{i+1}",
            "client_says": beat,
        }
        turns.append({"role": "client", "turn": i + 1, "text": beat})
        try:
            one = await mod._one_scenario_ws(
                websockets,
                ws_url=ws_url,
                username=username,
                password=password,
                role=role,
                scenario=sc_one,
            )
            nate_text = one.get("response") or ""
            if one.get("error"):
                errors.append(one["error"])
            turns.append({
                "role": "nate",
                "turn": i + 1,
                "text": nate_text,
                "provider": one.get("provider") or "ws",
            })
        except Exception as e:
            errors.append(str(e)[:200])
            turns.append({
                "role": "nate",
                "turn": i + 1,
                "text": "",
                "provider": "error",
                "error": str(e)[:200],
            })
    metrics = process_metrics(turns, scenario.get("section") or "")
    last_nate = next(
        (t["text"] for t in reversed(turns) if t["role"] == "nate"), ""
    )
    return {
        "scenario_id": scenario.get("id") or scenario.get("scenario_key"),
        "section": scenario.get("section"),
        "title": scenario.get("title"),
        "rubric_focus": scenario.get("rubric_focus"),
        "client_says": scenario.get("client_says"),
        "response": last_nate,
        "turns": turns,
        "process_metrics": metrics,
        "duration_seconds": round(time.time() - t0, 2),
        "provider": "live_ws_multi_turn",
        "odpe_signal": "",
        "error": "; ".join(errors) if errors else "",
        "mode": "multi_turn",
    }


def multi_turn_enabled() -> bool:
    return os.getenv("ENABLE_SIX_QUOTIENT_MULTI_TURN", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )
