"""hive_burst task worker body (W3 / Phase A).

Orchestrated only via task-bus. Scripts under scripts/ are invoked here.
Watchdog-blind: absent heartbeat → freeze, never re-dispatch paid GPU.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("ln7_hive_burst")

REPO_ROOT = Path(__file__).resolve().parents[3]


def _watchdog_state_path() -> Path:
    return Path(os.getenv("LN7_HIVE_WATCHDOG_PATH", "/tmp/ln7_hive_watchdog.json"))


def write_watchdog(state: Dict[str, Any]) -> None:
    path = _watchdog_state_path()
    try:
        path.write_text(json.dumps({**state, "mtime": time.time()}), encoding="utf-8")
    except Exception as e:
        logger.error("WATCHDOG_BLIND_ALARM: cannot write state: %s", e)


def read_watchdog() -> Optional[Dict[str, Any]]:
    path = _watchdog_state_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("WATCHDOG_BLIND_ALARM: cannot read state: %s", e)
        return None


async def run_hive_burst(
    db_pool=None,
    *,
    notes: str = "",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Provision → load intents → bakeoff/BoN → destroy. Returns result dict."""
    from app.services.flywheel_anomaly import notify_flywheel_anomaly
    from app.services.ln7_change_lease import acquire_lease, release_lease
    from app.services.ln7_frozen_config import load_json
    from app.services.ln7_serve_endpoint import (
        clear_serve_endpoint,
        drain_adapter_intents,
        publish_serve_endpoint,
    )

    gov = load_json("governance.json", {}) or {}
    lease = acquire_lease("hive_burst")
    if not lease:
        return {"ok": False, "error": "lease_held"}

    # Observability fail-safe: if prior state unreadable → freeze
    prior = read_watchdog()
    if prior is None and _watchdog_state_path().exists():
        await notify_flywheel_anomaly(
            "watchdog_blind",
            {"reason": "state_unreadable"},
            db_pool=db_pool,
        )
        release_lease("hive_burst", lease)
        return {"ok": False, "error": "watchdog_blind"}

    intents = drain_adapter_intents(32)
    burst_id = f"burst_{int(time.time())}"
    write_watchdog({"burst_id": burst_id, "phase": "start", "intents": len(intents)})

    script = REPO_ROOT / "scripts" / "ln7_hive_burst.sh"
    result: Dict[str, Any] = {
        "ok": True,
        "burst_id": burst_id,
        "intents": intents,
        "dry_run": dry_run,
    }

    endpoint_url = os.getenv("LN7_HIVE_ENDPOINT", "").strip()
    ttl_s = int(os.getenv("LN7_HIVE_ENDPOINT_TTL_S", "3600") or "3600")
    try:
        if dry_run or os.getenv("LN7_HIVE_DRY_RUN", "").strip() in ("1", "true", "yes"):
            # Activate-ready dry path: publish Redis serve key for clients/tests
            stub = endpoint_url or os.getenv(
                "LN7_HIVE_STUB_URL", "http://127.0.0.1:11436"
            )
            published = publish_serve_endpoint(stub, engine="vllm_burst", ttl_s=min(300, ttl_s))
            result["mode"] = "dry_run"
            result["endpoint"] = stub
            result["endpoint_published"] = published
            write_watchdog({
                "burst_id": burst_id, "phase": "dry_run", "endpoint": stub,
            })
            # Dry-run still clears endpoint so miss → Ollama (unless keep flag)
            if os.getenv("LN7_HIVE_DRY_KEEP_ENDPOINT", "").strip() not in (
                "1", "true", "yes",
            ):
                clear_serve_endpoint()
        elif not script.is_file():
            result["mode"] = "missing_script"
            result["ok"] = False
            result["error"] = "ln7_hive_burst.sh missing"
        else:
            env = os.environ.copy()
            env["LN7_BURST_ID"] = burst_id
            env["LN7_ADAPTER_INTENTS"] = json.dumps(intents)
            if endpoint_url:
                env["LN7_HIVE_ENDPOINT"] = endpoint_url
            proc = subprocess.run(
                ["bash", str(script)],
                cwd=str(REPO_ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=int(os.getenv("LN7_HIVE_BURST_TIMEOUT_S", "7200")),
            )
            result["returncode"] = proc.returncode
            result["stdout_tail"] = (proc.stdout or "")[-2000:]
            result["stderr_tail"] = (proc.stderr or "")[-2000:]
            result["ok"] = proc.returncode == 0
            # Publish endpoint when script echoes LN7_SERVE_URL=...
            serve_url = endpoint_url
            for line in (proc.stdout or "").splitlines():
                if line.startswith("LN7_SERVE_URL="):
                    serve_url = line.split("=", 1)[1].strip()
            if result["ok"] and serve_url:
                result["endpoint_published"] = publish_serve_endpoint(
                    serve_url, engine="vllm_burst", ttl_s=ttl_s
                )
                result["endpoint"] = serve_url
            if not result["ok"]:
                await notify_flywheel_anomaly(
                    "burst_destroy_fail",
                    {"burst_id": burst_id, "rc": proc.returncode},
                    db_pool=db_pool,
                )
                clear_serve_endpoint()

        write_watchdog({"burst_id": burst_id, "phase": "done", "ok": result["ok"]})
    except Exception as e:
        logger.exception("hive_burst failed: %s", e)
        result = {"ok": False, "error": str(e), "burst_id": burst_id}
        await notify_flywheel_anomaly(
            "burst_destroy_fail",
            {"burst_id": burst_id, "error": str(e)},
            db_pool=db_pool,
        )
        clear_serve_endpoint()
    finally:
        release_lease("hive_burst", lease)

    if db_pool:
        try:
            from app.services.ln7_outcome_envelope import write_envelope

            await write_envelope(
                db_pool,
                loop_name="hive",
                event_kind="hive_burst",
                burst_id=burst_id,
                source_node="green",
                metrics=result,
                cost_usd=None,
            )
        except Exception:
            pass
    return result
