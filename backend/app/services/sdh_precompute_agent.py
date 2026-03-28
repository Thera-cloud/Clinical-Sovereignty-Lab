"""
SDH Pre-computation Agent — Background agent that speculatively pre-computes
SDH context blocks for active users during their idle time.

Runs every 5 seconds, identifies active users from bridge connection tracking
or app_state, and pre-computes helix + SDH context so that when the user sends
their next message, the context is already cached.

Max 10 pre-computations per cycle to avoid overloading the helix orchestrator.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_CYCLE_INTERVAL = 5.0
_MAX_PRECOMPUTE_PER_CYCLE = 10


class SDHPrecomputeAgent:
    """Background agent for speculative SDH pre-computation."""

    def __init__(self, app_state=None, db_pool=None):
        self._app_state = app_state
        self._db_pool = db_pool
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the background loop."""
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "SDHPrecomputeAgent started (cycle=%.0fs, max=%d/cycle)",
            _CYCLE_INTERVAL, _MAX_PRECOMPUTE_PER_CYCLE,
        )

    async def stop(self) -> None:
        """Stop the background loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("SDHPrecomputeAgent stopped")

    async def _run_loop(self) -> None:
        """Main loop: 5-second cycle."""
        while self._running:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("SDHPrecomputeAgent cycle error: %s", e)
            await asyncio.sleep(_CYCLE_INTERVAL)

    async def _cycle(self) -> None:
        """One cycle: get active users, precompute for up to 10."""
        helix = getattr(self._app_state, "helix_orchestrator", None)
        compressor = getattr(self._app_state, "sdh_context_compressor", None)
        cache = getattr(self._app_state, "sdh_precompute_cache", None)

        if not helix or not compressor or not cache:
            return

        active_users = await self._get_active_users()
        if not active_users:
            return

        processed = 0
        for user_id in active_users:
            if processed >= _MAX_PRECOMPUTE_PER_CYCLE:
                break

            # Skip if user already has a valid cache entry
            try:
                has_entry = await cache.has_any_entry(user_id)
                if has_entry:
                    continue
            except Exception as e:
                logger.debug("SDH cache check failed for %s: %s", user_id, e)
                continue

            try:
                session_context = {"user_id": user_id, "last_message": "[precompute]", "session_id": ""}
                await self._precompute_for_user(user_id, session_context)
                processed += 1
            except Exception as e:
                logger.warning("SDH precompute failed for %s: %s", user_id, e)

    async def _get_active_users(self) -> List[str]:
        """Discover active users from bridge connection tracking or app_state."""
        users: List[str] = []

        bridge_state = getattr(self._app_state, "bridge_connected_users", None)
        if bridge_state is not None:
            if isinstance(bridge_state, dict):
                users.extend(bridge_state.keys())
            elif isinstance(bridge_state, (list, set)):
                users.extend(bridge_state)

        if not users:
            cache = getattr(self._app_state, "sdh_precompute_cache", None)
            if cache and getattr(cache, "_redis", None):
                try:
                    cursor = 0
                    while True:
                        cursor, keys = await cache._redis.scan(
                            cursor, match="nate:*:auth:*", count=50
                        )
                        for key in keys:
                            try:
                                raw = await cache._redis.get(key)
                                if raw:
                                    import json
                                    data = json.loads(raw) if isinstance(raw, str) else {}
                                    uid = data.get("hardware_id", data.get("username", ""))
                                    if uid:
                                        users.append(uid)
                            except Exception:
                                pass
                        if cursor == 0:
                            break
                except Exception as e:
                    logger.debug("SDH agent: Redis scan for active users failed: %s", e)

        return list(dict.fromkeys(users))[:20]

    async def _precompute_for_user(
        self, user_id: str, session_context: Dict
    ) -> None:
        """Run helix + SDH for one user and store in cache."""
        helix = getattr(self._app_state, "helix_orchestrator", None)
        compressor = getattr(self._app_state, "sdh_context_compressor", None)
        cache = getattr(self._app_state, "sdh_precompute_cache", None)

        if not helix or not compressor or not cache:
            return

        helix_result = None
        try:
            helix_result = await helix.think(
                f"[SDH pre-compute for {user_id}]",
                crystals=[],
                user_id=user_id,
            )
        except Exception as e:
            logger.debug("Helix think failed for %s: %s", user_id, e)

        raw_context: Dict = {"precompute": f"Speculative context for user {user_id}"}
        target_model = "llama3.1:8b-instruct-q4_K_M"
        target_tokens = 500

        if helix_result:
            odpe = getattr(helix_result, "odpe_result", None)
            if odpe:
                sig = getattr(odpe, "signal", None)
                if sig is not None and hasattr(sig, "value"):
                    sig = sig.value
                if sig in ("TENSION", "DEEP_TENSION"):
                    target_model = "qwen2.5:14b-instruct-q4_K_M"
                    target_tokens = 700

        block = await compressor.compress(
            user_id=user_id,
            helix_result=helix_result,
            raw_context=raw_context,
            conversation_history=[],
            profile={},
            target_tokens=target_tokens,
            target_model=target_model,
        )

        last_message = session_context.get("last_message", "[precompute]")
        session_id = session_context.get("session_id", "")
        state_hash = cache.compute_state_hash(user_id, last_message, session_id)

        block_dict = block.to_dict() if hasattr(block, "to_dict") else block
        if not isinstance(block_dict, dict):
            block_dict = {"compressed_context": str(block)}

        await cache.put(user_id, state_hash, block_dict, ttl=60)
