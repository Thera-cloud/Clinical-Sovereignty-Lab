"""
HIVE DEFENSE v4.0 — Transit Inspection Middleware
FastAPI middleware that intercepts requests and classifies data-in-motion.

Integrates with TransitGuardian for payload classification and
ALLOWED_SENSITIVE_DESTINATIONS enforcement.
"""

import json
import logging
import time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_logger = logging.getLogger("transit_inspection")

# Endpoints exempt from transit inspection (health checks, static assets)
EXEMPT_PATHS = {
    "/health",
    "/docs",
    "/openapi.json",
    "/favicon.ico",
}

# Limit body reading to prevent memory issues
MAX_BODY_INSPECT_BYTES = 65536  # 64KB


class TransitInspectionMiddleware(BaseHTTPMiddleware):
    """Middleware that feeds request metadata to TransitGuardian."""

    def __init__(self, app, transit_guardian=None, app_state=None):
        super().__init__(app)
        self._guardian = transit_guardian
        self._app_state = app_state

    def _get_guardian(self):
        if self._guardian:
            return self._guardian
        if self._app_state:
            return getattr(self._app_state, "hive_v4", {}).get("transit_guardian")
        return None

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        if path in EXEMPT_PATHS or path.startswith("/static"):
            return await call_next(request)

        guardian = self._get_guardian()
        if not guardian:
            return await call_next(request)

        start_time = time.time()
        user_id = ""

        # Extract basic request metadata
        try:
            # Get user_id from auth header if present
            auth_header = request.headers.get("authorization", "")
            if auth_header:
                user_id = "authenticated_user"

            # Classify inbound request
            content_length = int(request.headers.get("content-length", 0))
            payload_keys = []

            # For JSON requests, extract top-level keys for classification
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type and content_length > 0 and content_length < MAX_BODY_INSPECT_BYTES:
                try:
                    body = await request.body()
                    body_data = json.loads(body)
                    if isinstance(body_data, dict):
                        payload_keys = list(body_data.keys())
                except Exception:
                    pass

            result = await guardian.inspect_transit(
                direction="inbound",
                source=request.client.host if request.client else "unknown",
                destination="internal_api",
                endpoint=path,
                payload_keys=payload_keys,
                payload_size_bytes=content_length,
                user_id=user_id,
            )

            # Block if transit guardian says so
            if result.get("verdict") == "block":
                _logger.warning(
                    "Transit BLOCKED: %s %s from %s — %s",
                    request.method, path,
                    request.client.host if request.client else "?",
                    result.get("reason", ""),
                )
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Request blocked by security policy"},
                )

        except Exception as exc:
            _logger.error("Transit inspection error: %s", type(exc).__name__)

        # Continue with the request
        response = await call_next(request)

        # Log timing for crown jewel endpoints
        elapsed_ms = (time.time() - start_time) * 1000
        if elapsed_ms > 5000:
            _logger.warning("Slow request: %s %s took %.0fms", request.method, path, elapsed_ms)

        return response
