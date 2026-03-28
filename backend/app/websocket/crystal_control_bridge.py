"""
Crystal Control Bridge — Redis pub/sub IPC for crystal system control.

The backend publishes control commands to Redis channel `crystal_control`.
This module subscribes inside the bridge process and dispatches actions to
the Autonomous Controller and Subconscious Engine (bridge-local objects).

Also periodically reports AC/SE status to Redis for the backend to read.

NOTE: The bridge uses a SYNCHRONOUS redis.Redis client (via SwarmRelayClient).
All Redis calls must be wrapped in asyncio.to_thread() to avoid blocking.
"""
# QUANTUM-CRYSTAL-ARCH

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("nate.crystal_control")

_autonomous_controller = None
_subconscious_runtime = None
_bridge_crystallizer = None
_db_pool = None
_redis = None


def register_systems(
    autonomous_controller=None,
    subconscious_runtime=None,
    bridge_crystallizer=None,
    db_pool=None,
):
    """Called from bridge main() to register live references."""
    global _autonomous_controller, _subconscious_runtime, _bridge_crystallizer, _db_pool
    _autonomous_controller = autonomous_controller
    _subconscious_runtime = subconscious_runtime
    _bridge_crystallizer = bridge_crystallizer
    _db_pool = db_pool


async def start_listener(redis_client):
    """Start the Redis subscriber + periodic status reporter."""
    global _redis
    _redis = redis_client
    if not _redis:
        logger.warning("[CRYSTAL CONTROL] No Redis client — listener disabled")
        return

    asyncio.create_task(_subscribe_loop())
    asyncio.create_task(_status_reporter_loop())
    print(">>> [CRYSTAL CONTROL] Listener started")


def _sync_subscribe_and_listen():
    """Blocking sync function: subscribe to channel and yield messages.

    Runs inside asyncio.to_thread() so it doesn't block the event loop.
    """
    pubsub = _redis.pubsub()
    pubsub.subscribe("crystal_control")
    logger.info("[CRYSTAL CONTROL] Subscribed to crystal_control channel")
    for message in pubsub.listen():
        if message["type"] == "message":
            yield message["data"]


async def _subscribe_loop():
    """Subscribe to `crystal_control` Redis channel and dispatch actions."""
    try:
        pubsub = _redis.pubsub()
        await asyncio.to_thread(pubsub.subscribe, "crystal_control")
        logger.info("[CRYSTAL CONTROL] Subscribed to crystal_control channel")

        while True:
            raw = await asyncio.to_thread(pubsub.get_message, True, 1.0)
            if raw is None:
                continue
            if raw.get("type") != "message":
                continue
            try:
                data_str = raw.get("data", "")
                if isinstance(data_str, bytes):
                    data_str = data_str.decode("utf-8")
                data = json.loads(data_str)
                request_id = data.get("request_id", "unknown")
                system = data.get("system", "")
                action = data.get("action", "")
                logger.info(
                    "[CRYSTAL CONTROL] Received: system=%s action=%s id=%s",
                    system, action, request_id,
                )

                result = await _dispatch(system, action)
                result["request_id"] = request_id
                result["system"] = system
                result["action"] = action

                result_key = f"crystal_control_result:{request_id}"
                result_json = json.dumps(result)
                await asyncio.to_thread(
                    lambda: _redis.set(result_key, result_json, ex=30),
                )
            except Exception as e:
                logger.warning("[CRYSTAL CONTROL] Failed to process message: %s", e)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error("[CRYSTAL CONTROL] Subscribe loop crashed: %s", e)


async def _dispatch(system: str, action: str) -> dict:
    """Execute a control action on the named system."""
    global _autonomous_controller, _subconscious_runtime

    if system == "autonomous_controller":
        return await _control_autonomous(action)
    elif system == "subconscious_engine":
        return await _control_subconscious(action)
    else:
        return {"status": "error", "detail": f"Unknown system: {system}"}


async def _control_autonomous(action: str) -> dict:
    """Control the Autonomous Controller."""
    global _autonomous_controller

    if action == "stop":
        if _autonomous_controller and getattr(_autonomous_controller, "_running", False):
            _autonomous_controller._running = False
            return {"status": "ok", "detail": "Autonomous Controller stopped."}
        return {"status": "ok", "detail": "Controller was not running."}

    if action in ("start", "restart"):
        if _autonomous_controller and getattr(_autonomous_controller, "_running", False):
            _autonomous_controller._running = False
            await asyncio.sleep(1)

        try:
            from .autonomous_controller import AutonomousController
            from .autonomous_health import AutonomousHealthGates
            from pathlib import Path

            crystallizer = _bridge_crystallizer
            if not crystallizer:
                try:
                    from app.services.nate_memory_crystallizer import NateMemoryCrystallizer
                    crystallizer = NateMemoryCrystallizer(db_pool=_db_pool)
                except Exception:
                    pass

            health_gates = AutonomousHealthGates(
                db_pool=_db_pool,
                redis_client=_redis,
                crystallizer=crystallizer,
                project_root=Path(os.environ.get("CLI_PROJECT_ROOT", ".")),
                use_redis=bool(_redis),
            )
            _autonomous_controller = AutonomousController(
                health_gates=health_gates,
                project_root=Path(os.environ.get("CLI_PROJECT_ROOT", ".")),
                crystallizer=crystallizer,
                broadcast_fn=None,
                health_interval=int(os.environ.get("AUTONOMOUS_HEALTH_INTERVAL", "60")),
                learn_budget=int(os.environ.get("AUTONOMOUS_LEARN_BUDGET", "600")),
                db_pool=_db_pool,
            )
            asyncio.create_task(_autonomous_controller.run())
            return {"status": "ok", "detail": f"Autonomous Controller {action}ed successfully."}
        except Exception as e:
            return {"status": "error", "detail": f"Failed to {action} controller: {e}"}

    return {"status": "error", "detail": f"Unknown action for autonomous_controller: {action}"}


async def _control_subconscious(action: str) -> dict:
    """Control the Subconscious Engine."""
    global _subconscious_runtime

    if action in ("stop", "disable"):
        if _subconscious_runtime:
            try:
                await _subconscious_runtime.shutdown()
            except Exception as e:
                return {"status": "error", "detail": f"Shutdown failed: {e}"}
            _subconscious_runtime = None
            return {"status": "ok", "detail": "Subconscious Engine stopped."}
        return {"status": "ok", "detail": "Engine was not running."}

    if action in ("start", "enable", "restart"):
        if _subconscious_runtime:
            try:
                await _subconscious_runtime.shutdown()
            except Exception:
                pass
            _subconscious_runtime = None
            await asyncio.sleep(1)

        try:
            from app.services.subconscious_bootstrap import boot_subconscious, SubconsciousConfig
            _subconscious_runtime = await boot_subconscious(
                redis_client=_redis,
                config=SubconsciousConfig.from_env(),
            )
            return {"status": "ok", "detail": f"Subconscious Engine {action}d successfully."}
        except Exception as e:
            return {"status": "error", "detail": f"Failed to {action} engine: {e}"}

    return {"status": "error", "detail": f"Unknown action for subconscious_engine: {action}"}


async def _status_reporter_loop():
    """Every 60s, write AC/SE status to Redis for the backend to read."""
    while True:
        try:
            await asyncio.sleep(60)
            if not _redis:
                continue

            ac_data = {
                "running": False,
                "crystals_forged": 0,
                "buffer_size": 0,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
            if _autonomous_controller:
                ac_data["running"] = getattr(_autonomous_controller, "_running", False)
                ac_data["crystals_forged"] = getattr(_autonomous_controller, "_total_crystals", 0)
                if _bridge_crystallizer:
                    ac_data["buffer_size"] = len(getattr(_bridge_crystallizer, "_harvest_buffer", []))
                ac_data["cycles"] = getattr(_autonomous_controller, "_cycles", 0)

            ac_json = json.dumps(ac_data)
            await asyncio.to_thread(
                lambda: _redis.set("crystal_system_status:autonomous_controller", ac_json, ex=120),
            )

            se_data = {
                "enabled": os.environ.get("ENABLE_SUBCONSCIOUS", "false").lower() == "true",
                "running": False,
                "jobs_completed": 0,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
            if _subconscious_runtime:
                se_data["running"] = getattr(_subconscious_runtime, "_running", False)
                try:
                    status = _subconscious_runtime.status()
                    orch = status.get("orchestrator", {})
                    se_data["jobs_completed"] = orch.get("total_crystallizations", 0)
                    se_data["idle_score"] = status.get("monitor", {}).get("idle_score", 0)
                except Exception:
                    pass

            se_json = json.dumps(se_data)
            await asyncio.to_thread(
                lambda: _redis.set("crystal_system_status:subconscious_engine", se_json, ex=120),
            )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("[CRYSTAL CONTROL] Status reporter error: %s", e)
