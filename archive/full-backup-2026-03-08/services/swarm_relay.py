"""
Swarm Relay — Redis pub/sub bridge between the WebSocket bridge process
and the FastAPI process where swarm services (FibreManager, WisdomMesh,
SovereignImmunity, ForesightEngine, CoherenceEngine) are initialized.

Architecture:
  Bridge → publishes to Redis channel "swarm:request"
  FastAPI → subscribes to "swarm:request", dispatches to app.state services,
            publishes results to "swarm:response:{request_id}"

This allows the bridge to trigger swarm operations without sharing process memory.
"""

import asyncio
import json
import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("swarm_relay")

REDIS_CHANNEL_REQUEST = "swarm:request"
REDIS_CHANNEL_RESPONSE_PREFIX = "swarm:response:"
REQUEST_TIMEOUT_SECONDS = 15


# =============================================================================
# CLIENT (used by bridge_server.py)
# =============================================================================

class SwarmRelayClient:
    """
    Lightweight client used by the bridge process to send swarm requests
    to the FastAPI process via Redis pub/sub.

    Uses synchronous redis.Redis in a thread pool executor to avoid
    redis-py 5.x async connection pool timeouts inside the bridge's
    websockets event loop.
    """

    def __init__(self, redis_url: str = None):
        self._redis_host = os.environ.get("REDIS_HOST", "redis")
        self._redis_port = int(os.environ.get("REDIS_PORT", "6379"))
        self._redis_password = os.environ.get("REDIS_PASSWORD", None)
        if self._redis_host not in ("redis", "localhost", "127.0.0.1"):
            self._redis_host = "redis"
        self._redis = None

    async def connect(self, retries: int = 5, delay: float = 5.0):
        """Establish Redis connection with retry. Uses sync client in thread pool."""
        import redis as sync_redis
        loop = asyncio.get_event_loop()
        for attempt in range(1, retries + 1):
            try:
                client = sync_redis.Redis(
                    host=self._redis_host,
                    port=self._redis_port,
                    password=self._redis_password,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=10,
                )
                await loop.run_in_executor(None, client.ping)
                self._redis = client
                logger.info("[SWARM RELAY CLIENT] Connected to Redis")
                return
            except Exception as e:
                logger.warning(
                    f"[SWARM RELAY CLIENT] Redis attempt {attempt}/{retries} failed: {type(e).__name__}: {e}"
                )
                self._redis = None
                if attempt < retries:
                    await asyncio.sleep(delay)
        logger.warning("[SWARM RELAY CLIENT] All Redis connection attempts exhausted — relay disabled")

    def _sync_request(self, message: str, response_channel: str, timeout: float) -> Optional[str]:
        """Synchronous pub/sub request-response cycle (runs in thread pool)."""
        import time
        pubsub = self._redis.pubsub()
        try:
            pubsub.subscribe(response_channel)
            self._redis.publish(REDIS_CHANNEL_REQUEST, message)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                raw_msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if raw_msg and raw_msg["type"] == "message":
                    return raw_msg["data"]
            return None
        finally:
            try:
                pubsub.unsubscribe(response_channel)
                pubsub.close()
            except Exception:
                pass

    async def request(self, action: str, payload: Dict[str, Any],
                      timeout: float = REQUEST_TIMEOUT_SECONDS) -> Optional[Dict[str, Any]]:
        """
        Send a swarm request and wait for a response.

        Args:
            action: The swarm action (e.g., "coherence_pulse", "fibre_spawn",
                    "immunity_check", "foresight_forecast", "mesh_publish")
            payload: Action-specific data
            timeout: Seconds to wait for response

        Returns:
            Response dict from the FastAPI-side handler, or None on timeout/error.
        """
        if not self._redis:
            return None

        request_id = str(uuid.uuid4())
        response_channel = f"{REDIS_CHANNEL_RESPONSE_PREFIX}{request_id}"

        message = json.dumps({
            "request_id": request_id,
            "action": action,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        try:
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(
                None, self._sync_request, message, response_channel, timeout
            )
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.warning(f"[SWARM RELAY CLIENT] Request failed ({action}): {e}")
            return None

    async def fire_and_forget(self, action: str, payload: Dict[str, Any]):
        """Send a swarm request without waiting for a response."""
        if not self._redis:
            return

        message = json.dumps({
            "request_id": str(uuid.uuid4()),
            "action": action,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fire_and_forget": True,
        })

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, self._redis.publish, REDIS_CHANNEL_REQUEST, message
            )
        except Exception as e:
            logger.warning(f"[SWARM RELAY CLIENT] Fire-and-forget failed ({action}): {e}")

    async def disconnect(self):
        if self._redis:
            try:
                self._redis.close()
            except Exception:
                pass
            self._redis = None


# =============================================================================
# SERVER (used by main.py / FastAPI lifespan)
# =============================================================================

class SwarmRelayServer:
    """
    Server-side relay that runs in the FastAPI process, listening for swarm
    requests from the bridge and dispatching them to the appropriate app.state
    services.
    """

    def __init__(self, app_state, redis_url: str = None):
        self._app_state = app_state
        self._redis_host = os.environ.get("REDIS_HOST", "redis")
        self._redis_port = int(os.environ.get("REDIS_PORT", "6379"))
        self._redis_password = os.environ.get("REDIS_PASSWORD", None)
        self._redis = None
        self._pubsub = None
        self._listener_task = None

    async def start(self):
        """Connect to Redis and start listening for swarm requests."""
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.Redis(
                host=self._redis_host,
                port=self._redis_port,
                password=self._redis_password,
                decode_responses=True,
            )
            await self._redis.ping()

            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(REDIS_CHANNEL_REQUEST)

            self._listener_task = asyncio.create_task(self._listen())
            logger.info("[SWARM RELAY SERVER] Listening for bridge requests")
        except Exception as e:
            logger.warning(f"[SWARM RELAY SERVER] Failed to start: {e}")

    async def _listen(self):
        """Main listener loop — dispatch incoming requests to handlers."""
        _last_ping = asyncio.get_event_loop().time()
        _PING_INTERVAL = 60  # seconds
        try:
            async for raw_msg in self._pubsub.listen():
                if raw_msg["type"] != "message":
                    # ── HIVE DEFENSE v4.3: Periodic Redis health ping (GAP I4) ──
                    now = asyncio.get_event_loop().time()
                    if now - _last_ping > _PING_INTERVAL:
                        try:
                            await self._redis.ping()
                            _last_ping = now
                        except Exception as ping_err:
                            logger.warning("[SWARM RELAY SERVER] Redis ping failed, reconnecting: %s", ping_err)
                            try:
                                await self._reconnect()
                                _last_ping = asyncio.get_event_loop().time()
                            except Exception as rc_err:
                                logger.error("[SWARM RELAY SERVER] Reconnect failed: %s", rc_err)
                    continue
                try:
                    request = json.loads(raw_msg["data"])
                    asyncio.create_task(self._handle_request(request))
                except json.JSONDecodeError:
                    pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("[SWARM RELAY SERVER] Listener error: %s", e)

    async def _reconnect(self):
        """Reconnect Redis pub/sub after a stale connection."""
        import redis.asyncio as aioredis
        try:
            if self._pubsub:
                await self._pubsub.close()
        except Exception:
            pass
        try:
            if self._redis:
                await self._redis.close()
        except Exception:
            pass
        self._redis = aioredis.Redis(
            host=self._redis_host,
            port=self._redis_port,
            password=self._redis_password,
            decode_responses=True,
        )
        await self._redis.ping()
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(REDIS_CHANNEL_REQUEST)
        logger.info("[SWARM RELAY SERVER] Reconnected to Redis")

    async def _handle_request(self, request: Dict[str, Any]):
        """Route a request to the appropriate swarm service handler."""
        action = request.get("action", "")
        payload = request.get("payload", {})
        request_id = request.get("request_id", "")
        fire_and_forget = request.get("fire_and_forget", False)

        result = {"status": "error", "message": f"Unknown action: {action}"}

        try:
            if action == "coherence_pulse":
                result = await self._handle_coherence_pulse(payload)
            elif action == "fibre_spawn":
                result = await self._handle_fibre_spawn(payload)
            elif action == "fibre_list":
                result = await self._handle_fibre_list(payload)
            elif action == "immunity_check":
                result = await self._handle_immunity_check(payload)
            elif action == "foresight_forecast":
                result = await self._handle_foresight_forecast(payload)
            elif action == "mesh_health":
                result = await self._handle_mesh_health(payload)
            elif action == "mesh_publish":
                result = await self._handle_mesh_publish(payload)
            else:
                result = {"status": "error", "message": f"Unknown action: {action}"}
        except Exception as e:
            result = {"status": "error", "message": str(e)}

        # Publish response (unless fire-and-forget)
        if not fire_and_forget and request_id and self._redis:
            response_channel = f"{REDIS_CHANNEL_RESPONSE_PREFIX}{request_id}"
            try:
                await self._redis.publish(response_channel, json.dumps(result))
            except Exception as e:
                logger.warning(f"[SWARM RELAY SERVER] Response publish failed: {e}")

    # ── Handlers ──

    async def _handle_coherence_pulse(self, payload: Dict) -> Dict:
        engine = getattr(self._app_state, "coherence_engine", None)
        if not engine:
            return {"status": "unavailable", "message": "Coherence Engine not initialized"}
        pulse = await engine.compute_pulse()
        return {"status": "ok", "pulse": pulse}

    async def _handle_fibre_spawn(self, payload: Dict) -> Dict:
        manager = getattr(self._app_state, "fibre_manager", None)
        if not manager:
            return {"status": "unavailable", "message": "Fibre Manager not initialized"}
        fibre_type = payload.get("fibre_type", "")
        config = payload.get("config", {})
        fibre = await manager.spawn_fibre(fibre_type, config)
        return {"status": "ok", "fibre_id": str(fibre.fibre_id) if fibre else None}

    async def _handle_fibre_list(self, payload: Dict) -> Dict:
        manager = getattr(self._app_state, "fibre_manager", None)
        if not manager:
            return {"status": "unavailable", "message": "Fibre Manager not initialized"}
        fibres = manager.list_fibres()
        return {"status": "ok", "fibres": fibres}

    async def _handle_immunity_check(self, payload: Dict) -> Dict:
        immunity = getattr(self._app_state, "sovereign_immunity", None)
        if not immunity:
            return {"status": "unavailable", "message": "Sovereign Immunity not initialized"}
        message = payload.get("message", "")
        fibre_id = payload.get("fibre_id")
        result = await immunity.guard_message(message, fibre_id=fibre_id)
        return {"status": "ok", "allowed": result.get("allowed", True), "details": result}

    async def _handle_foresight_forecast(self, payload: Dict) -> Dict:
        engine = getattr(self._app_state, "foresight_engine", None)
        if not engine:
            return {"status": "unavailable", "message": "Foresight Engine not initialized"}
        alerts = await engine.generate_alerts()
        return {"status": "ok", "alerts": alerts}

    async def _handle_mesh_health(self, payload: Dict) -> Dict:
        mesh = getattr(self._app_state, "wisdom_mesh", None)
        if not mesh:
            return {"status": "unavailable", "message": "Wisdom Mesh not initialized"}
        health = await mesh.get_mesh_health()
        # MeshHealth is a dataclass, convert to dict
        return {"status": "ok", "health": health.__dict__ if hasattr(health, "__dict__") else str(health)}

    async def _handle_mesh_publish(self, payload: Dict) -> Dict:
        mesh = getattr(self._app_state, "wisdom_mesh", None)
        if not mesh:
            return {"status": "unavailable", "message": "Wisdom Mesh not initialized"}
        # Rebuild a MeshMessage-like object from payload
        from app.services.wisdom_mesh import MeshMessage
        msg = MeshMessage(**payload.get("message", {}))
        await mesh.publish(msg)
        return {"status": "ok"}

    async def stop(self):
        """Clean up Redis connections."""
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self._pubsub:
            await self._pubsub.unsubscribe(REDIS_CHANNEL_REQUEST)
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()
        logger.info("[SWARM RELAY SERVER] Stopped")
