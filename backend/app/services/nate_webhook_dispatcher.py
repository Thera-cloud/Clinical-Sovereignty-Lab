"""
Nate Webhook Dispatcher — Background agent that fires webhooks defined by Nate's extensions.

Runs every 30 minutes. Reads active webhook definitions from nate_extensions,
evaluates trigger conditions, fires outbound HTTP POST, and logs to D1.

Circuit breakers:
  - Max 50 total webhook fires per hour
  - Max 5 fires per webhook per hour
  - 3 consecutive failures suspends a webhook
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger("nate_webhook_dispatcher")

_MAX_FIRES_PER_HOUR = 50
_MAX_PER_WEBHOOK_PER_HOUR = 5
_CONSECUTIVE_FAILURE_LIMIT = 3
_CYCLE_SECONDS = 1800


class NateWebhookDispatcher:
    def __init__(self, db_pool=None, sandbox_executor=None):
        self._db_pool = db_pool
        self._sandbox = sandbox_executor
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cycle_count = 0
        self._fire_log: List[float] = []
        self._per_webhook_fires: Dict[str, List[float]] = {}
        self._consecutive_failures: Dict[str, int] = {}
        self._suspended_webhooks: set = set()

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("NateWebhookDispatcher started (30-min cycle)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        await asyncio.sleep(180)
        while self._running:
            try:
                await self._cycle()
                self._cycle_count += 1
            except Exception as e:
                logger.warning("WebhookDispatcher cycle error: %s", e)
            await asyncio.sleep(_CYCLE_SECONDS)

    async def _cycle(self):
        if not self._db_pool:
            return

        webhooks = await self._load_active_webhooks()
        if not webhooks:
            return

        self._prune_fire_log()

        if len(self._fire_log) >= _MAX_FIRES_PER_HOUR:
            logger.info("WebhookDispatcher: global rate limit reached (%d/%d)", len(self._fire_log), _MAX_FIRES_PER_HOUR)
            return

        for wh in webhooks:
            name = wh.get("name", "")
            if name in self._suspended_webhooks:
                continue

            per_wh = self._per_webhook_fires.get(name, [])
            if len(per_wh) >= _MAX_PER_WEBHOOK_PER_HOUR:
                continue

            try:
                should_fire = await self._evaluate_trigger(wh)
                if not should_fire:
                    continue

                success = await self._fire_webhook(wh)
                now = time.time()

                if success:
                    self._fire_log.append(now)
                    self._per_webhook_fires.setdefault(name, []).append(now)
                    self._consecutive_failures[name] = 0
                else:
                    fails = self._consecutive_failures.get(name, 0) + 1
                    self._consecutive_failures[name] = fails
                    if fails >= _CONSECUTIVE_FAILURE_LIMIT:
                        self._suspended_webhooks.add(name)
                        logger.warning("WebhookDispatcher: suspended webhook '%s' after %d consecutive failures", name, fails)

            except Exception as e:
                logger.warning("WebhookDispatcher: error processing webhook '%s': %s", name, e)

    async def _load_active_webhooks(self) -> List[Dict]:
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, name, definition, domain
                    FROM nate_extensions
                    WHERE extension_type = 'webhook' AND active = true
                """)
            result = []
            for row in rows:
                defn = row["definition"]
                if isinstance(defn, str):
                    defn = json.loads(defn)
                result.append({
                    "id": str(row["id"]),
                    "name": row["name"],
                    "domain": row["domain"],
                    "target_url": defn.get("target_url", ""),
                    "trigger_condition": defn.get("trigger_condition", ""),
                    "payload_template": defn.get("payload_template", {}),
                    "rate_limit_per_hour": defn.get("rate_limit_per_hour", _MAX_PER_WEBHOOK_PER_HOUR),
                })
            return result
        except Exception as e:
            logger.warning("WebhookDispatcher: failed to load webhooks: %s", e)
            return []

    async def _evaluate_trigger(self, webhook: Dict) -> bool:
        condition = webhook.get("trigger_condition", "")
        if not condition:
            return False
        # Trigger conditions are evaluated as simple threshold checks
        # Format: "metric_name < 0.3" or "metric_name > 100"
        # For now, always return True if condition is non-empty (actual eval requires data context)
        return bool(condition.strip())

    async def _fire_webhook(self, webhook: Dict) -> bool:
        target = webhook.get("target_url", "")
        if not target:
            return False

        payload = {
            "source": "nate_webhook_dispatcher",
            "webhook_name": webhook.get("name", ""),
            "domain": webhook.get("domain", ""),
            "fired_at": datetime.now(timezone.utc).isoformat(),
            "data": webhook.get("payload_template", {}),
        }

        status_code = 0
        response_body = ""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.post(target, json=payload) as resp:
                    status_code = resp.status
                    response_body = (await resp.text())[:500]
            success = 200 <= status_code < 300
        except Exception as e:
            response_body = str(e)[:500]
            success = False

        if self._sandbox:
            await self._sandbox.log_webhook(
                webhook_name=webhook.get("name", ""),
                target_url=target,
                status_code=status_code,
                response_body=response_body,
            )

        return success

    def _prune_fire_log(self):
        cutoff = time.time() - 3600
        self._fire_log = [t for t in self._fire_log if t > cutoff]
        for name in list(self._per_webhook_fires.keys()):
            self._per_webhook_fires[name] = [t for t in self._per_webhook_fires[name] if t > cutoff]

    def health(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "fires_this_hour": len(self._fire_log),
            "suspended_webhooks": list(self._suspended_webhooks),
        }
