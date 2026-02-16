"""
HIVE DEFENSE v4.3 — Webhook Rate Limiting Middleware
Protects the Stripe webhook endpoint from DDoS and replay attacks.

- Per-IP sliding window rate limiting (in-memory, no Redis needed)
- Configurable window size and max requests
- Returns 429 on excess
"""

import logging
import time
from collections import defaultdict
from typing import Callable, Dict, List

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_logger = logging.getLogger("webhook_rate_limit")

# Protected paths
RATE_LIMITED_PATHS = {
    "/api/billing/stripe-webhook",
    "/api/stripe/webhook",
    "/api/webhooks/stripe",
}

# Rate limit: max requests per window per IP
MAX_REQUESTS_PER_WINDOW = 120
WINDOW_SECONDS = 60

# Cleanup old entries every N requests
CLEANUP_INTERVAL = 500


class WebhookRateLimitMiddleware(BaseHTTPMiddleware):
    """Rate-limits webhook endpoints by source IP using a sliding window."""

    def __init__(
        self,
        app,
        max_requests: int = MAX_REQUESTS_PER_WINDOW,
        window_seconds: int = WINDOW_SECONDS,
    ):
        super().__init__(app)
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._requests: Dict[str, List[float]] = defaultdict(list)
        self._total_requests = 0

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Only rate-limit webhook paths
        if path not in RATE_LIMITED_PATHS:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        cutoff = now - self._window_seconds

        # Prune old timestamps for this IP
        timestamps = self._requests[client_ip]
        self._requests[client_ip] = [t for t in timestamps if t > cutoff]

        # Check rate
        if len(self._requests[client_ip]) >= self._max_requests:
            _logger.warning(
                "Webhook rate limit exceeded: IP=%s, path=%s, count=%d/%d in %ds",
                client_ip, path, len(self._requests[client_ip]),
                self._max_requests, self._window_seconds,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded for webhook endpoint",
                    "retry_after_seconds": self._window_seconds,
                },
                headers={"Retry-After": str(self._window_seconds)},
            )

        # Record this request
        self._requests[client_ip].append(now)
        self._total_requests += 1

        # Periodic cleanup of stale IPs
        if self._total_requests % CLEANUP_INTERVAL == 0:
            self._cleanup(cutoff)

        return await call_next(request)

    def _cleanup(self, cutoff: float):
        """Remove IPs with no recent requests."""
        stale_ips = [
            ip for ip, timestamps in self._requests.items()
            if not timestamps or max(timestamps) < cutoff
        ]
        for ip in stale_ips:
            del self._requests[ip]

    def get_stats(self) -> Dict:
        """Return rate limiter statistics."""
        now = time.time()
        cutoff = now - self._window_seconds
        active_ips = sum(
            1 for timestamps in self._requests.values()
            if any(t > cutoff for t in timestamps)
        )
        return {
            "active_ips": active_ips,
            "total_requests_tracked": self._total_requests,
            "max_per_window": self._max_requests,
            "window_seconds": self._window_seconds,
        }
