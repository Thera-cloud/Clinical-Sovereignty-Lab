"""
HIVE DEFENSE v4.3 — Drum Tap Middleware
FastAPI middleware that taps all inbound/outbound pipelines for Pipeline Drum.
"""

import logging
import time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_logger = logging.getLogger("drum_tap")

EXEMPT_PATHS = {"/health", "/docs", "/openapi.json", "/favicon.ico"}


class DrumTapMiddleware(BaseHTTPMiddleware):
    """Middleware that feeds request/response data to Pipeline Drum."""

    def __init__(self, app, pipeline_drum=None):
        super().__init__(app)
        self._drum = pipeline_drum

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self._drum or request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        start_time = time.time()

        # Read payload for burn sensor (only small payloads)
        payload = b""
        content_length = int(request.headers.get("content-length", 0))
        if 0 < content_length < 32768:
            try:
                payload = await request.body()
            except Exception:
                pass

        response = await call_next(request)

        # Tap the completed request
        elapsed_ms = (time.time() - start_time) * 1000
        try:
            self._drum.tap_request(
                endpoint=request.url.path,
                method=request.method,
                status_code=response.status_code,
                response_time_ms=elapsed_ms,
                payload=payload,
            )
        except Exception as exc:
            _logger.error("DrumTap error: %s", type(exc).__name__)

        return response
