"""
HIVE DEFENSE PROTOCOL v3.0 — Response Time Normalization (Phase 8C)
Timing window normalization for all API responses.

Timing attacks allow an attacker to infer server-side behavior from
response times.  For example:
    - A 5ms response might indicate "user not found" (fast lookup failure)
    - A 50ms response might indicate "user found, password checked"

This service normalizes response times so that all responses for the
same endpoint fall within a configured time window.  The attacker sees
only uniform timing, regardless of what happened server-side.

Example:
    Endpoint: /api/auth/login
    Window: 50ms–70ms

    - User not found (actual: 3ms) → padded to random value in [50, 70]ms
    - User found, wrong password (actual: 45ms) → padded to random in [50, 70]ms
    - User found, correct password (actual: 65ms) → no padding needed (already in window)
    - If actual > 70ms → response sent immediately (no artificial delay)

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hive.response_normalization")


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class EndpointWindow:
    """Time window configuration for a single endpoint."""

    endpoint: str = ""
    min_ms: float = 50.0
    max_ms: float = 70.0
    description: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class NormalizationMetrics:
    """Metrics for a single endpoint's response normalization."""

    endpoint: str = ""
    total_requests: int = 0
    padded_requests: int = 0            # Requests that needed padding
    overrun_requests: int = 0           # Requests that exceeded the window
    avg_actual_ms: float = 0.0
    avg_padding_ms: float = 0.0
    min_actual_ms: float = float("inf")
    max_actual_ms: float = 0.0


# =============================================================================
# DEFAULT ENDPOINT WINDOWS
# =============================================================================

DEFAULT_WINDOWS: Dict[str, EndpointWindow] = {
    "/api/auth/login": EndpointWindow(
        endpoint="/api/auth/login",
        min_ms=50.0,
        max_ms=70.0,
        description="Authentication endpoint — hide user existence",
    ),
    "/api/auth/verify": EndpointWindow(
        endpoint="/api/auth/verify",
        min_ms=30.0,
        max_ms=50.0,
        description="Token verification — hide token validity",
    ),
    "/api/sessions/lookup": EndpointWindow(
        endpoint="/api/sessions/lookup",
        min_ms=40.0,
        max_ms=60.0,
        description="Session lookup — hide existence of session data",
    ),
    "/api/users/profile": EndpointWindow(
        endpoint="/api/users/profile",
        min_ms=30.0,
        max_ms=50.0,
        description="User profile — hide data retrieval patterns",
    ),
    "/api/billing/status": EndpointWindow(
        endpoint="/api/billing/status",
        min_ms=40.0,
        max_ms=60.0,
        description="Billing status — hide subscription state",
    ),
    "/api/coherence/score": EndpointWindow(
        endpoint="/api/coherence/score",
        min_ms=50.0,
        max_ms=80.0,
        description="Coherence score — hide computation complexity",
    ),
}


# =============================================================================
# RESPONSE NORMALIZATION SERVICE
# =============================================================================

class ResponseNormalization:
    """
    API response time normalization service.

    Ensures all responses for the same endpoint are delivered within
    a configured time window, preventing timing-based information
    leakage about server-side operations.

    Parameters
    ----------
    windows : dict[str, EndpointWindow], optional
        Pre-configured endpoint windows.  If None, uses defaults.
    jitter_entropy : bytes, optional
        Additional entropy for the jitter random number generator.

    Usage
    -----
    ::

        normalizer = ResponseNormalization()

        # Configure per-endpoint
        normalizer.configure_window("/api/auth/login", min_ms=50, max_ms=70)

        # In request handler
        start_ms = time.monotonic() * 1000
        response = await handle_request()
        actual_ms = (time.monotonic() * 1000) - start_ms

        delay_ms = await normalizer.normalize_response_time(
            "/api/auth/login", actual_ms
        )
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)

        return response

    ASGI Middleware
    ---------------
    For automatic normalization, use :meth:`create_middleware` to get a
    FastAPI/Starlette middleware that wraps all configured endpoints.
    """

    def __init__(
        self,
        windows: Optional[Dict[str, EndpointWindow]] = None,
        jitter_entropy: Optional[bytes] = None,
    ) -> None:
        # Endpoint windows
        self._windows: Dict[str, EndpointWindow] = windows or dict(DEFAULT_WINDOWS)

        # Per-endpoint metrics
        self._metrics: Dict[str, NormalizationMetrics] = {}

        # Random state with additional entropy
        self._rng = random.Random()
        seed_material = os.urandom(32) + (jitter_entropy or b"")
        self._rng.seed(seed_material)

        # Global metrics
        self._total_normalized: int = 0
        self._total_padded: int = 0
        self._total_overruns: int = 0

        logger.info(
            "ResponseNormalization initialized — windows=%d",
            len(self._windows),
        )

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    async def normalize_response_time(
        self,
        endpoint: str,
        actual_ms: float,
    ) -> float:
        """
        Calculate the additional delay needed to normalize response time.

        If the actual response time is below the window minimum, returns
        a random delay that places the total response time within [min, max].
        If the actual time is already within the window, returns 0.
        If the actual time exceeds the window, returns 0 (no artificial delay).

        Parameters
        ----------
        endpoint : str
            The API endpoint path.
        actual_ms : float
            The actual processing time in milliseconds.

        Returns
        -------
        float
            Additional delay in milliseconds.  0.0 if no delay needed.
        """
        window = self._windows.get(endpoint)
        if window is None:
            # No window configured — no normalization
            return 0.0

        # Update metrics
        metrics = self._get_or_create_metrics(endpoint)
        metrics.total_requests += 1
        metrics.min_actual_ms = min(metrics.min_actual_ms, actual_ms)
        metrics.max_actual_ms = max(metrics.max_actual_ms, actual_ms)

        # Running average of actual times
        n = metrics.total_requests
        metrics.avg_actual_ms = (
            metrics.avg_actual_ms * (n - 1) + actual_ms
        ) / n

        self._total_normalized += 1

        if actual_ms >= window.max_ms:
            # Already exceeded the window — send immediately
            metrics.overrun_requests += 1
            self._total_overruns += 1
            logger.debug(
                "response_overrun endpoint=%s actual_ms=%.1f window=[%.1f, %.1f]",
                endpoint,
                actual_ms,
                window.min_ms,
                window.max_ms,
            )
            return 0.0

        if actual_ms >= window.min_ms:
            # Within the window — no padding needed
            return 0.0

        # Below the window — calculate padding
        # Target a random time within [min, max] for this response
        target_ms = self._rng.uniform(window.min_ms, window.max_ms)
        padding_ms = max(0.0, target_ms - actual_ms)

        metrics.padded_requests += 1
        self._total_padded += 1

        # Running average of padding
        metrics.avg_padding_ms = (
            metrics.avg_padding_ms * (metrics.padded_requests - 1) + padding_ms
        ) / metrics.padded_requests

        logger.debug(
            "response_padded endpoint=%s actual_ms=%.1f target_ms=%.1f padding_ms=%.1f",
            endpoint,
            actual_ms,
            target_ms,
            padding_ms,
        )

        return padding_ms

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure_window(
        self,
        endpoint: str,
        min_ms: float,
        max_ms: float,
        description: str = "",
    ) -> EndpointWindow:
        """
        Set the response time window for an endpoint.

        Parameters
        ----------
        endpoint : str
            The API endpoint path.
        min_ms : float
            Minimum response time in milliseconds.
        max_ms : float
            Maximum response time in milliseconds.
        description : str, optional
            Human-readable description.

        Returns
        -------
        EndpointWindow
            The configured window.

        Raises
        ------
        ValueError
            If min_ms >= max_ms or either value is negative.
        """
        if min_ms < 0 or max_ms < 0:
            raise ValueError("Window times must be non-negative")
        if min_ms >= max_ms:
            raise ValueError(
                f"min_ms ({min_ms}) must be less than max_ms ({max_ms})"
            )

        window = EndpointWindow(
            endpoint=endpoint,
            min_ms=min_ms,
            max_ms=max_ms,
            description=description,
        )
        self._windows[endpoint] = window

        logger.info(
            "response_window_configured endpoint=%s min=%.1fms max=%.1fms",
            endpoint,
            min_ms,
            max_ms,
        )
        return window

    def get_endpoint_windows(self) -> Dict[str, Dict[str, Any]]:
        """
        Return all configured endpoint windows.

        Returns
        -------
        dict[str, dict]
            Mapping of endpoint → window configuration.
        """
        return {
            endpoint: {
                "min_ms": window.min_ms,
                "max_ms": window.max_ms,
                "description": window.description,
                "created_at": window.created_at.isoformat(),
            }
            for endpoint, window in self._windows.items()
        }

    def remove_window(self, endpoint: str) -> bool:
        """Remove the response time window for an endpoint."""
        if endpoint in self._windows:
            del self._windows[endpoint]
            logger.info("response_window_removed endpoint=%s", endpoint)
            return True
        return False

    # ------------------------------------------------------------------
    # ASGI Middleware Factory
    # ------------------------------------------------------------------

    def create_middleware(self):
        """
        Create a FastAPI/Starlette middleware for automatic response normalization.

        Returns a middleware class that wraps configured endpoints with
        timing normalization.

        Returns
        -------
        type
            A Starlette middleware class.
        """
        normalizer = self

        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import Response

        class ResponseNormalizationMiddleware(BaseHTTPMiddleware):
            """ASGI middleware for response time normalization."""

            async def dispatch(self, request: Request, call_next) -> Response:
                endpoint = request.url.path

                # Only normalize configured endpoints
                if endpoint not in normalizer._windows:
                    return await call_next(request)

                start_ms = time.monotonic() * 1000
                response = await call_next(request)
                actual_ms = (time.monotonic() * 1000) - start_ms

                delay_ms = await normalizer.normalize_response_time(
                    endpoint, actual_ms
                )
                if delay_ms > 0:
                    await asyncio.sleep(delay_ms / 1000.0)

                return response

        return ResponseNormalizationMiddleware

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def _get_or_create_metrics(self, endpoint: str) -> NormalizationMetrics:
        """Get or create metrics for an endpoint."""
        if endpoint not in self._metrics:
            self._metrics[endpoint] = NormalizationMetrics(endpoint=endpoint)
        return self._metrics[endpoint]

    def get_metrics(self) -> Dict[str, Dict[str, Any]]:
        """
        Return per-endpoint normalization metrics.

        Returns
        -------
        dict[str, dict]
            Mapping of endpoint → metrics.
        """
        return {
            endpoint: {
                "total_requests": m.total_requests,
                "padded_requests": m.padded_requests,
                "overrun_requests": m.overrun_requests,
                "avg_actual_ms": round(m.avg_actual_ms, 2),
                "avg_padding_ms": round(m.avg_padding_ms, 2),
                "min_actual_ms": round(m.min_actual_ms, 2) if m.min_actual_ms != float("inf") else None,
                "max_actual_ms": round(m.max_actual_ms, 2),
            }
            for endpoint, m in self._metrics.items()
        }

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Global normalization statistics."""
        return {
            "configured_endpoints": len(self._windows),
            "total_normalized": self._total_normalized,
            "total_padded": self._total_padded,
            "total_overruns": self._total_overruns,
            "pad_rate": (
                round(self._total_padded / self._total_normalized, 4)
                if self._total_normalized > 0
                else 0.0
            ),
        }

    def __repr__(self) -> str:
        return (
            f"<ResponseNormalization "
            f"endpoints={len(self._windows)} "
            f"normalized={self._total_normalized} "
            f"padded={self._total_padded}>"
        )
