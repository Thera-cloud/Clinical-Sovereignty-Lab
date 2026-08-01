"""hive_burst task worker body (W3 / Phase A).

Orchestrated only via task-bus. Scripts under scripts/ are invoked here.
Watchdog-blind: absent heartbeat → freeze, never re-dispatch paid GPU.
Economics: F1 bootstrap / CPAI gate before paid provision.
Resolves rev_a/rev_b from kwargs, notes JSON, intents, or env.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


def _parse_notes(notes: str) -> Dict[str, Any]:
    if not notes or not notes.strip().startswith("{"):
        return {}
    try:
        data = json.loads(notes)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def resolve_burst_arms(
    *,
    rev_a: str = "",
    rev_b: str = "",
    notes: str = "",
    intents: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, str]:
    """Pick two distinct revision_ids for the hive window."""
    meta = _parse_notes(notes)
    a = (
        (rev_a or "").strip()
        or str(meta.get("rev_a") or meta.get("revision_a") or "").strip()
        or os.getenv("LN7_BURST_REV_A", "").strip()
    )
    b = (
        (rev_b or "").strip()
        or str(meta.get("rev_b") or meta.get("revision_b") or "").strip()
        or os.getenv("LN7_BURST_REV_B", "").strip()
    )
    ids: List[str] = []
    for it in intents or []:
        aid = str((it or {}).get("adapter_id") or "").strip()
        if aid and aid not in ids:
            ids.append(aid)
    if not a and ids:
        a = ids[0]
    if not b and len(ids) > 1:
        b = ids[1]
    elif not b and len(ids) == 1 and a and ids[0] != a:
        b = ids[0]
    return a, b


async def _mirror_arms(rev_a: str, rev_b: str) -> Dict[str, Any]:
    root = Path(os.getenv("LN7_ADAPTER_ROOT", str(REPO_ROOT / ".ln7-adapters")))
    out: Dict[str, Any] = {}
    try:
        from app.services.ln7_r2_weight_mirror import mirror_adapter_dir
    except Exception as e:
        return {"skipped": True, "reason": str(e)}
    for rev in (rev_a, rev_b):
        if not rev:
            continue
        local = root / rev
        if not local.is_dir():
            out[rev] = {"ok": False, "error": "missing_local"}
            continue
        out[rev] = await mirror_adapter_dir(
            str(local), revision_id=rev, r2_key_prefix="ln7/adapters/"
        )
    return out


async def run_hive_burst(
    db_pool=None,
    *,
    notes: str = "",
    dry_run: bool = False,
    rev_a: str = "",
    rev_b: str = "",
    estimated_cost_usd: Optional[float] = None,
) -> Dict[str, Any]:
    """Provision → load intents → bakeoff/BoN → destroy. Returns result dict."""
    from app.services.flywheel_anomaly import notify_flywheel_anomaly
    from app.services.ln7_burst_economics import evaluate_burst_economics
    from app.services.ln7_change_lease import acquire_lease, release_lease
    from app.services.ln7_serve_endpoint import (
        clear_serve_endpoint,
        drain_adapter_intents,
        publish_serve_endpoint,
    )

    dry = dry_run or os.getenv("LN7_HIVE_DRY_RUN", "").strip() in (
        "1", "true", "yes",
    )
    est = estimated_cost_usd
    if est is None:
        est = float(os.getenv("LN7_HIVE_EST_COST_USD", "12") or "12")

    econ = await evaluate_burst_economics(
        db_pool, estimated_cost_usd=float(est), dry_run=dry
    )
    if not econ.get("ok"):
        anom = (
            "watchdog_blind"
            if econ.get("mode") == "observability_fail"
            else "bootstrap_cap"
        )
        await notify_flywheel_anomaly(anom, {"econ": econ}, db_pool=db_pool)
        return {"ok": False, "error": "economics_blocked", "economics": econ}

    lease = acquire_lease("hive_burst")
    if not lease:
        return {"ok": False, "error": "lease_held", "economics": econ}

    # Observability fail-safe: if prior state unreadable → freeze
    prior = read_watchdog()
    if prior is None and _watchdog_state_path().exists():
        await notify_flywheel_anomaly(
            "watchdog_blind",
            {"reason": "state_unreadable"},
            db_pool=db_pool,
        )
        release_lease("hive_burst", lease)
        return {"ok": False, "error": "watchdog_blind", "economics": econ}

    intents = drain_adapter_intents(32)
    arm_a, arm_b = resolve_burst_arms(
        rev_a=rev_a, rev_b=rev_b, notes=notes, intents=intents
    )
    burst_id = f"burst_{int(time.time())}"
    write_watchdog({
        "burst_id": burst_id,
        "phase": "start",
        "intents": len(intents),
        "rev_a": arm_a,
        "rev_b": arm_b,
    })

    script = REPO_ROOT / "scripts" / "ln7_hive_burst.sh"
    result: Dict[str, Any] = {
        "ok": True,
        "burst_id": burst_id,
        "intents": intents,
        "dry_run": dry,
        "rev_a": arm_a,
        "rev_b": arm_b,
        "economics": econ,
    }

    endpoint_url = os.getenv("LN7_HIVE_ENDPOINT", "").strip()
    ttl_s = int(os.getenv("LN7_HIVE_ENDPOINT_TTL_S", "3600") or "3600")
    try:
        if dry:
            stub = endpoint_url or os.getenv(
                "LN7_HIVE_STUB_URL", "http://127.0.0.1:11436"
            )
            published = publish_serve_endpoint(
                stub, engine="vllm_burst", ttl_s=min(300, ttl_s)
            )
            result["mode"] = "dry_run"
            result["endpoint"] = stub
            result["endpoint_published"] = published
            write_watchdog({
                "burst_id": burst_id, "phase": "dry_run", "endpoint": stub,
            })
            if os.getenv("LN7_HIVE_DRY_KEEP_ENDPOINT", "").strip() not in (
                "1", "true", "yes",
            ):
                clear_serve_endpoint()
        elif not arm_a or not arm_b or arm_a == arm_b:
            result["mode"] = "missing_arms"
            result["ok"] = False
            result["error"] = "rev_a/rev_b required and must differ"
        elif not script.is_file():
            result["mode"] = "missing_script"
            result["ok"] = False
            result["error"] = "ln7_hive_burst.sh missing"
        else:
            result["mirror"] = await _mirror_arms(arm_a, arm_b)
            env = os.environ.copy()
            env["LN7_BURST_ID"] = burst_id
            env["LN7_ADAPTER_INTENTS"] = json.dumps(intents)
            env["LN7_BURST_REV_A"] = arm_a
            env["LN7_BURST_REV_B"] = arm_b
            if endpoint_url:
                env["LN7_HIVE_ENDPOINT"] = endpoint_url
            proc = subprocess.run(
                ["bash", str(script), arm_a, arm_b],
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
            serve_url = endpoint_url
            for line in (proc.stdout or "").splitlines():
                if line.startswith("LN7_SERVE_URL="):
                    serve_url = line.split("=", 1)[1].strip()
            # Handoff often writes host:port without Redis publish — construct URL
            if not serve_url:
                for line in (proc.stdout or "").splitlines() + (proc.stderr or "").splitlines():
                    if "LN7_BURST_HOST=" in line or line.startswith("LN7_BURST_HOST="):
                        host = line.split("=", 1)[-1].strip()
                        port = os.getenv("LN7_BURST_PORT", "11436")
                        serve_url = f"http://{host}:{port}/v1"
            if result["ok"] and serve_url:
                result["endpoint_published"] = publish_serve_endpoint(
                    serve_url, engine="vllm_burst", ttl_s=ttl_s
                )
                result["endpoint"] = serve_url
                print(f"LN7_SERVE_URL={serve_url}", flush=True)
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
        result = {
            "ok": False,
            "error": str(e),
            "burst_id": burst_id,
            "economics": econ,
            "rev_a": arm_a,
            "rev_b": arm_b,
        }
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
            from app.services.ln7_outcome_envelope import (
                cross_loop_attribution,
                write_envelope,
            )

            cost = None if dry else float(est)
            await write_envelope(
                db_pool,
                loop_name="hive",
                event_kind="hive_burst",
                burst_id=burst_id,
                revision_id=arm_a or None,
                source_node="green",
                # E2: rev_b isn't a dedicated column — surface both arms in
                # attribution_json so a burst compare can be joined back to
                # either candidate's shadow_fork/canary_eval lineage.
                attribution={
                    **cross_loop_attribution(
                        None, revision_id=arm_a or None, burst_id=burst_id
                    ),
                    "rev_b": arm_b or None,
                },
                metrics={
                    **{k: v for k, v in result.items() if k != "intents"},
                    "intent_count": len(intents),
                    "accepted_improvement": int(
                        bool(result.get("ok") and result.get("mode") != "dry_run")
                        and os.getenv("LN7_BURST_MARK_ACCEPTED", "").strip() == "1"
                    ),
                },
                cost_usd=cost,
            )
        except Exception:
            pass
    return result
