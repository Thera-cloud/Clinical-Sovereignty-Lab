"""
HIVE DEFENSE v4.3 — Upstream Canary Network (Section 13.10.8)
Detects provider-level breaches by monitoring canary accounts at each upstream service.

Canary signals maintained for:
1. Azure OpenAI — seeded canary prompt/response pair
2. Stripe — canary customer with known state
3. SendGrid — canary email delivery and webhook integrity
4. Anthropic — (reserved) canary prompt/response pair

Each canary is checked on a configurable interval. A failed check indicates
the upstream provider may have been compromised, tampered with, or is behaving
anomalously. Failed canaries trigger alerts and DEFCON escalation.
"""

import asyncio
import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.services.nate_ai_config import NATE_CHAT_URL, NATE_CHAT_KEY, NATE_CHAT_MODEL, nate_chat_headers, nate_chat_payload

_logger = logging.getLogger("upstream_canary")


# ─── Canary Definitions ─────────────────────────────────────────────────────

CANARY_PROVIDERS = ("azure", "stripe", "sendgrid", "anthropic")

# Interval between canary checks (seconds)
DEFAULT_CHECK_INTERVAL = 3600  # 1 hour
ALERT_COOLDOWN = 300  # 5 min between repeated alerts for the same provider


class CanaryStatus:
    """Status of a single upstream canary."""

    def __init__(self, provider: str):
        self.provider = provider
        self.alive = True
        self.last_check: Optional[datetime] = None
        self.last_success: Optional[datetime] = None
        self.consecutive_failures = 0
        self.total_checks = 0
        self.total_failures = 0
        self.last_error: Optional[str] = None
        self.last_alert_time: float = 0.0

    def record_success(self):
        now = datetime.now(timezone.utc)
        self.alive = True
        self.last_check = now
        self.last_success = now
        self.consecutive_failures = 0
        self.total_checks += 1
        self.last_error = None

    def record_failure(self, error: str):
        now = datetime.now(timezone.utc)
        self.last_check = now
        self.consecutive_failures += 1
        self.total_checks += 1
        self.total_failures += 1
        self.last_error = error
        if self.consecutive_failures >= 3:
            self.alive = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "alive": self.alive,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "consecutive_failures": self.consecutive_failures,
            "total_checks": self.total_checks,
            "total_failures": self.total_failures,
            "last_error": self.last_error,
        }


# ─── Individual Canary Checkers ──────────────────────────────────────────────

async def _check_azure_canary() -> bool:
    """
    Verify AI chat canary: send a deterministic prompt to the centralized
    Nate AI endpoint and verify the response is coherent.
    """
    try:
        if not NATE_CHAT_KEY:
            _logger.debug("AI canary skipped: no credentials configured")
            return True

        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                NATE_CHAT_URL,
                json=nate_chat_payload(
                    messages=[{"role": "user", "content": "Respond with only the word: CANARY"}],
                    max_tokens=5,
                ),
                headers=nate_chat_headers(),
            )
            resp.raise_for_status()
            body = resp.json()
            content = body["choices"][0]["message"]["content"].strip().upper()
            if "CANARY" not in content:
                _logger.warning("AI canary response drift (%s): got '%s'", NATE_CHAT_MODEL, content[:50])
                return False
        return True
    except Exception as exc:
        _logger.error("AI canary check failed (%s): %s", NATE_CHAT_MODEL, exc)
        raise


async def _check_stripe_canary() -> bool:
    """
    Verify Stripe canary: retrieve canary customer and verify expected fields
    have not been tampered with.
    """
    try:
        import stripe as stripe_lib
        secret_key = os.environ.get("STRIPE_SECRET_KEY", "")
        canary_customer_id = os.environ.get("STRIPE_CANARY_CUSTOMER_ID", "")

        if not secret_key or not canary_customer_id:
            _logger.debug("Stripe canary skipped: no credentials or canary customer configured")
            return True

        stripe_lib.api_key = secret_key
        customer = stripe_lib.Customer.retrieve(canary_customer_id)

        # Verify the canary customer's metadata contains our sentinel value
        sentinel = customer.get("metadata", {}).get("canary_sentinel", "")
        expected_hash = hashlib.sha256(
            f"sovereign-canary-{canary_customer_id}".encode()
        ).hexdigest()[:16]

        if sentinel != expected_hash:
            _logger.warning(
                "Stripe canary sentinel mismatch: expected=%s, got=%s",
                expected_hash, sentinel[:20],
            )
            return False
        return True
    except Exception as exc:
        _logger.error("Stripe canary check failed: %s", exc)
        raise


async def _check_sendgrid_canary() -> bool:
    """
    Verify SendGrid canary: call the API to verify key is valid and
    our sender identity exists.
    """
    try:
        api_key = os.environ.get("SENDGRID_API_KEY", "")
        if not api_key:
            _logger.debug("SendGrid canary skipped: no API key configured")
            return True

        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.sendgrid.com/v3/user/credits",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
        return True
    except Exception as exc:
        _logger.error("SendGrid canary check failed: %s", exc)
        raise


async def _check_anthropic_canary() -> bool:
    """
    Verify Anthropic canary: (reserved for future use).
    Currently a no-op that always returns True.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return True  # Not configured, skip

    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 5,
                    "messages": [{"role": "user", "content": "Respond with only: CANARY"}],
                },
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            body = resp.json()
            content = body["content"][0]["text"].strip().upper()
            if "CANARY" not in content:
                _logger.warning("Anthropic canary response drift: got '%s'", content[:50])
                return False
        return True
    except Exception as exc:
        _logger.error("Anthropic canary check failed: %s", exc)
        raise


CANARY_CHECKS: Dict[str, Callable] = {
    "azure": _check_azure_canary,
    "stripe": _check_stripe_canary,
    "sendgrid": _check_sendgrid_canary,
    "anthropic": _check_anthropic_canary,
}


# ─── Upstream Canary Network ────────────────────────────────────────────────

class UpstreamCanaryNetwork:
    """
    Monitors canary accounts across all upstream providers.
    Runs periodic checks and raises alerts on anomalies.
    """

    def __init__(
        self,
        db_pool=None,
        check_interval: int = DEFAULT_CHECK_INTERVAL,
        alert_callback: Optional[Callable] = None,
    ):
        self._db = db_pool
        self._check_interval = check_interval
        self._alert_callback = alert_callback
        self._canaries: Dict[str, CanaryStatus] = {
            provider: CanaryStatus(provider) for provider in CANARY_PROVIDERS
        }
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """Start the background canary monitoring loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        _logger.info(
            "Upstream Canary Network started (interval=%ds, providers=%d)",
            self._check_interval, len(CANARY_PROVIDERS),
        )

    def stop(self):
        """Stop the background canary monitoring loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _monitor_loop(self):
        """Main loop that checks all canaries periodically."""
        while self._running:
            try:
                await self.check_all()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _logger.error("Canary monitor loop error: %s", exc)
            await asyncio.sleep(self._check_interval)

    async def check_all(self) -> Dict[str, Dict[str, Any]]:
        """Run all canary checks and return combined status."""
        results = {}
        for provider, checker in CANARY_CHECKS.items():
            status = self._canaries[provider]
            try:
                ok = await checker()
                if ok:
                    status.record_success()
                else:
                    status.record_failure("canary_response_drift")
                    await self._handle_failure(provider, "canary_response_drift")
            except Exception as exc:
                status.record_failure(str(exc))
                await self._handle_failure(provider, str(exc))
            results[provider] = status.to_dict()

        # Persist check results to DB
        await self._persist_results(results)
        return results

    async def check_provider(self, provider: str) -> Dict[str, Any]:
        """Run a canary check for a single provider."""
        if provider not in CANARY_CHECKS:
            return {"error": f"Unknown provider: {provider}"}

        checker = CANARY_CHECKS[provider]
        status = self._canaries[provider]
        try:
            ok = await checker()
            if ok:
                status.record_success()
            else:
                status.record_failure("canary_response_drift")
                await self._handle_failure(provider, "canary_response_drift")
        except Exception as exc:
            status.record_failure(str(exc))
            await self._handle_failure(provider, str(exc))

        return status.to_dict()

    async def _handle_failure(self, provider: str, error: str):
        """Handle a canary failure — alert and escalate."""
        status = self._canaries[provider]
        now = time.time()

        # Rate-limit alerts
        if now - status.last_alert_time < ALERT_COOLDOWN:
            return
        status.last_alert_time = now

        _logger.critical(
            "UPSTREAM CANARY FAILURE: provider=%s, consecutive=%d, error=%s",
            provider, status.consecutive_failures, error[:200],
        )

        # Fire alert callback (e.g. DEFCON escalation)
        if self._alert_callback:
            try:
                await self._alert_callback(
                    "UPSTREAM_CANARY_FAILURE",
                    {
                        "provider": provider,
                        "consecutive_failures": status.consecutive_failures,
                        "error": error[:500],
                    },
                )
            except Exception as cb_err:
                _logger.error("Canary alert callback failed: %s", cb_err)

        # Persist alert to audit log
        if self._db:
            try:
                await self._db.execute(
                    """INSERT INTO audit_log (action_type, target_id, details)
                       VALUES ($1, $2, $3)""",
                    "UPSTREAM_CANARY_FAILURE",
                    provider,
                    f"Consecutive failures: {status.consecutive_failures}. Error: {error[:500]}",
                )
            except Exception:
                pass

    async def _persist_results(self, results: Dict[str, Dict]):
        """Persist canary check results to the database."""
        if not self._db:
            return
        try:
            import json
            await self._db.execute(
                """INSERT INTO audit_log (action_type, target_id, details)
                   VALUES ($1, $2, $3)""",
                "UPSTREAM_CANARY_CHECK",
                "all_providers",
                json.dumps({p: r.get("alive", True) for p, r in results.items()}),
            )
        except Exception:
            pass

    def get_status(self) -> Dict[str, Any]:
        """Get current canary network status."""
        all_alive = all(c.alive for c in self._canaries.values())
        return {
            "network_healthy": all_alive,
            "check_interval_seconds": self._check_interval,
            "providers": {
                name: status.to_dict()
                for name, status in self._canaries.items()
            },
        }

    def is_provider_healthy(self, provider: str) -> bool:
        """Check if a specific provider's canary is alive."""
        status = self._canaries.get(provider)
        return status.alive if status else True
