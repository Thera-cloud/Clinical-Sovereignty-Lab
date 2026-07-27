"""
Relay Redis nate:voice_avatar → bridge WebSocket clients (SOVEREIGN-VOICE).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Dict, Optional, Set

logger = logging.getLogger("nate.voice_avatar_relay")

REDIS_CHANNEL = "nate:voice_avatar"


async def start_voice_avatar_relay(
    get_sockets: Callable[[], Dict[str, Set[Any]]],
    redis_client,
) -> Optional[asyncio.Task]:
    if redis_client is None:
        return None

    async def _loop():
        pubsub = None
        while True:
            try:
                pubsub = redis_client.pubsub()
                await asyncio.to_thread(pubsub.subscribe, REDIS_CHANNEL)
                logger.info("voice_avatar_relay subscribed to %s", REDIS_CHANNEL)
                while True:
                    msg = await asyncio.to_thread(
                        pubsub.get_message,
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )
                    if not msg or msg.get("type") != "message":
                        await asyncio.sleep(0.05)
                        continue
                    await _fanout(get_sockets, msg.get("data"))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("voice_avatar_relay loop: %s", e)
                await asyncio.sleep(2)
            finally:
                try:
                    if pubsub is not None:
                        await asyncio.to_thread(pubsub.close)
                except Exception:
                    pass

    return asyncio.create_task(_loop())


async def _fanout(get_sockets, raw) -> None:
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        data = json.loads(raw)
        username = (data.get("username") or "").strip()
        hw = (data.get("hardware_id") or "").strip()
        sockets = get_sockets() or {}
        targets: Set[Any] = set()
        for key in (hw, username):
            if key and key in sockets:
                targets |= set(sockets[key])
        if not targets:
            return
        payload = json.dumps(
            {
                "type": "voice_avatar_expression",
                "avatar_state": data.get("avatar_state") or {},
                "call_sid": (data.get("avatar_state") or {}).get("call_sid", ""),
                "source": "voice_call",
            }
        )
        for ws in list(targets):
            try:
                result = ws.send(payload)
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                pass
    except Exception as e:
        logger.debug("voice_avatar fanout: %s", e)
