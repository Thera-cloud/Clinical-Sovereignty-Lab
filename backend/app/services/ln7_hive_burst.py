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

    try:
        if dry_run or not script.is_file():
            # Skeleton path: publish stub endpoint marker only in dry_run
            if dry_run:
                publish_serve_endpoint(
                    os.getenv("LN7_HIVE_STUB_URL", "http://127.0.0.1:11436"),
                    ttl_s=120,
                )
            result["mode"] = "dry_run_or_missing_script"
        else:
            env = os.environ.copy()
            env["LN7_BURST_ID"] = burst_id
            env["LN7_ADAPTER_INTENTS"] = json.dumps(intents)
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
            if not result["ok"]:
                await notify_flywheel_anomaly(
                    "burst_destroy_fail",
                    {"burst_id": burst_id, "rc": proc.returncode},
                    db_pool=db_pool,
                )

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
