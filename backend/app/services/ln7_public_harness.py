"""LN7 public benchmark harness orchestration (ORANGE/BLUE — never GREEN exec).

Modes:
  smoke — tiny in-repo tasks (CI / wiring proof); schema matches full runs
  full  — invoke official container runners when LN7_PUBLIC_HARNESS_ROOT is set
  ingest — load precomputed JSON from LN7_PUBLIC_RESULTS_DIR (ORANGE/BLUE upload)

Scores are report-only; private held-out remains the promotion gate.
# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ln7_public_harness")

PUBLIC_BENCHMARKS = (
    "swe_bench_verified",
    "livecodebench",
    "aider_polyglot",
    "terminal_bench",
)

# Minimal smoke tasks — prove harness I/O; not competitive scores.
_SMOKE_TASKS: Dict[str, List[Dict[str, Any]]] = {
    "swe_bench_verified": [
        {
            "task_id": "smoke_swe_001",
            "prompt": "Return a one-line Python function add(a,b) that returns a+b.",
            "oracle": "def add(a, b):\n    return a + b\n",
        },
    ],
    "livecodebench": [
        {
            "task_id": "smoke_lcb_001",
            "prompt": "Write fib(n) iterative returning the nth Fibonacci number (n>=0).",
            "oracle": "def fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n",
        },
    ],
    "aider_polyglot": [
        {
            "task_id": "smoke_aider_001",
            "prompt": "Edit: rename function foo to bar in: def foo():\n    return 1\n",
            "oracle": "def bar():\n    return 1\n",
        },
    ],
    "terminal_bench": [
        {
            "task_id": "smoke_term_001",
            "prompt": "Shell: echo hello world (expected stdout contains hello).",
            "oracle": "hello",
        },
    ],
}


def harness_mode() -> str:
    m = (os.getenv("LN7_PUBLIC_HARNESS_MODE", "smoke") or "smoke").strip().lower()
    if m in ("full", "official", "container"):
        return "full"
    if m in ("ingest", "results"):
        return "ingest"
    return "smoke"


def results_dir() -> Path:
    raw = os.getenv("LN7_PUBLIC_RESULTS_DIR", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[3] / "docs" / "ln7" / "public_results"


def harness_root() -> Optional[Path]:
    raw = os.getenv("LN7_PUBLIC_HARNESS_ROOT", "").strip()
    return Path(raw) if raw else None


def _bootstrap_ci(passes: List[bool]) -> Dict[str, float]:
    from app.services.ln7_bakeoff_engine import bootstrap_ci
    return bootstrap_ci(passes)


def _score_smoke_task(bench: str, task: Dict[str, Any], response: str) -> bool:
    oracle = (task.get("oracle") or "").strip()
    text = (response or "").strip()
    if not text:
        return False
    if bench == "terminal_bench":
        return oracle.lower() in text.lower()
    # Code-ish: require oracle keywords / normalized containment
    norm_o = "".join(oracle.split())
    norm_t = "".join(text.split())
    if norm_o and norm_o in norm_t:
        return True
    # Soft: key tokens present
    keys = [t for t in oracle.replace("(", " ").replace(")", " ").split() if len(t) > 2]
    hits = sum(1 for k in keys if k in text)
    return hits >= max(1, len(keys) // 2)


async def _propose_ln7(prompt: str) -> str:
    """Sovereign-only propose for smoke (no vendor)."""
    try:
        from app.websocket.ln7_harness import generate_sovereign_reply
        out = await generate_sovereign_reply(
            [
                {"role": "system", "content": "Return only code or shell output."},
                {"role": "user", "content": prompt},
            ],
            mode="fast",
        )
        return (out or {}).get("text") or ""
    except Exception as exc:
        logger.warning("public smoke propose: %s", exc)
        return ""


async def run_smoke_benchmark(name: str) -> Dict[str, Any]:
    tasks = _SMOKE_TASKS.get(name) or []
    if not tasks:
        return {"benchmark": name, "status": "unknown_benchmark", "report_only": True}
    offline = os.getenv("LN7_PUBLIC_SMOKE_OFFLINE", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    passes: List[bool] = []
    details: List[Dict[str, Any]] = []
    t0 = time.time()
    for task in tasks:
        if offline:
            # Schema / wiring proof without Ollama (CI)
            text = task.get("oracle") or ""
        else:
            text = await _propose_ln7(task["prompt"])
        ok = _score_smoke_task(name, task, text)
        passes.append(ok)
        details.append({
            "task_id": task["task_id"],
            "passed": ok,
            "response_chars": len(text),
            "offline": offline,
        })
    ci = _bootstrap_ci(passes)
    return {
        "benchmark": name,
        "status": "ok",
        "mode": "smoke_offline" if offline else "smoke",
        "report_only": True,
        "pass_rate": ci,
        "latency_ms": int((time.time() - t0) * 1000),
        "details": details,
        "note": "Smoke subset only — not a competitive SWE-bench / LCB score.",
    }


def load_ingested_result(name: str) -> Optional[Dict[str, Any]]:
    path = results_dir() / f"{name}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("benchmark", name)
        data.setdefault("report_only", True)
        data.setdefault("mode", "ingest")
        data.setdefault("status", "ok")
        return data
    except Exception as exc:
        logger.warning("ingest %s: %s", name, exc)
        return None


def run_full_container(name: str, *, timeout_s: int = 7200) -> Dict[str, Any]:
    """Invoke official runner script under LN7_PUBLIC_HARNESS_ROOT/<name>/run.sh."""
    root = harness_root()
    if not root:
        return {
            "benchmark": name,
            "status": "harness_root_unset",
            "report_only": True,
            "note": "Set LN7_PUBLIC_HARNESS_ROOT on ORANGE/BLUE to official clone roots.",
        }
    script = root / name / "run.sh"
    if not script.is_file():
        # Fallback: docker compose in repo scripts
        compose = (
            Path(__file__).resolve().parents[2]
            / "scripts"
            / "ln7_public_harness"
            / name
            / "docker-compose.yml"
        )
        if compose.is_file():
            try:
                subprocess.run(
                    ["docker", "compose", "-f", str(compose), "run", "--rm", "harness"],
                    check=False,
                    timeout=timeout_s,
                    capture_output=True,
                    text=True,
                )
            except Exception as exc:
                return {
                    "benchmark": name,
                    "status": "container_error",
                    "report_only": True,
                    "error": str(exc)[:300],
                }
            ingested = load_ingested_result(name)
            if ingested:
                ingested["mode"] = "full"
                return ingested
        return {
            "benchmark": name,
            "status": "runner_missing",
            "report_only": True,
            "note": f"Expected {script} or compose under scripts/ln7_public_harness/{name}/",
        }
    try:
        proc = subprocess.run(
            ["bash", str(script)],
            cwd=str(script.parent),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        out_path = results_dir() / f"{name}.json"
        if out_path.is_file():
            data = load_ingested_result(name) or {}
            data["mode"] = "full"
            data["exit_code"] = proc.returncode
            return data
        return {
            "benchmark": name,
            "status": "no_results_file",
            "report_only": True,
            "exit_code": proc.returncode,
            "stderr": (proc.stderr or "")[:500],
        }
    except Exception as exc:
        return {
            "benchmark": name,
            "status": "runner_error",
            "report_only": True,
            "error": str(exc)[:300],
        }


async def run_public_benchmark(name: str) -> Dict[str, Any]:
    mode = harness_mode()
    if name not in PUBLIC_BENCHMARKS:
        return {"benchmark": name, "status": "unknown", "report_only": True}
    if mode == "ingest":
        data = load_ingested_result(name)
        return data or {
            "benchmark": name,
            "status": "results_missing",
            "report_only": True,
            "note": f"Place {name}.json under {results_dir()}",
        }
    if mode == "full":
        # Prefer ingested if fresh; else container
        data = load_ingested_result(name)
        if data and data.get("pass_rate"):
            data["mode"] = "full_cached"
            return data
        return run_full_container(name)
    return await run_smoke_benchmark(name)


async def run_all_public() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for name in PUBLIC_BENCHMARKS:
        try:
            out.append(await run_public_benchmark(name))
        except Exception as exc:
            out.append({
                "benchmark": name,
                "status": "error",
                "report_only": True,
                "error": str(exc)[:200],
            })
    return out


def write_result(name: str, payload: Dict[str, Any]) -> str:
    results_dir().mkdir(parents=True, exist_ok=True)
    path = results_dir() / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return str(path)
