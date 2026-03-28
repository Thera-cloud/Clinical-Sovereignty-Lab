"""
Cache-Control middleware for Cloudflare Tiered Cache + Cache Reserve.

Adds appropriate caching headers to responses based on endpoint patterns.
Cloudflare respects these headers to determine what to cache at the edge
and how long to keep it in Cache Reserve (persistent R2-backed CDN cache).

Rules:
  - File downloads (immutable once created): public, max-age=3600
  - Classroom videos: public, max-age=7200 (large files, rarely change)
  - Static templates / exports: public, max-age=86400
  - User-specific data (search, vault metadata): private, max-age=60
  - Auth-sensitive endpoints: no-store (default for authenticated routes)
  - Health / status endpoints: no-cache
"""

from __future__ import annotations

import re
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_IMMUTABLE_FILE_PATTERNS = [
    re.compile(r"^/api/coach/folders/files/.+/download$"),
    re.compile(r"^/api/dojo/download-assessment/.+$"),
    re.compile(r"^/api/dojo/download-export/.+$"),
    re.compile(r"^/api/hive-defense/v4/threat-dropbox/detonation/.+/screenshot/.+$"),
]

_LONG_CACHE_PATTERNS = [
    re.compile(r"^/api/sessions/classroom/video/.+$"),
]

_STATIC_PATTERNS = [
    re.compile(r"^/api/corp/template/download$"),
]

_SHORT_CACHE_PATTERNS = [
    re.compile(r"^/api/client/memory/search/.+$"),
    re.compile(r"^/api/client/memory/sessions/.+$"),
    re.compile(r"^/api/sessions/classroom/session/.+$"),
    re.compile(r"^/api/v1/vault/search$"),
    re.compile(r"^/api/v1/vault/stats$"),
    re.compile(r"^/api/v1/vault/folders$"),
    re.compile(r"^/api/skyeye/platforms$"),
    re.compile(r"^/api/skyeye/platform-health$"),
]

_DASHBOARD_CACHE_PATTERNS = [
    re.compile(r"^/api/skyeye/overview$"),
    re.compile(r"^/api/skyeye/engine-status$"),
    re.compile(r"^/api/skyeye/sessions$"),
    re.compile(r"^/api/skyeye/activity$"),
    re.compile(r"^/api/marketing/results$"),
    re.compile(r"^/api/marketing/funnel-stats$"),
    re.compile(r"^/api/marketing/post-analytics$"),
    re.compile(r"^/api/marketing/notifications$"),
    re.compile(r"^/api/skyeye/history$"),
    re.compile(r"^/api/skyeye/compliance$"),
]

_NO_CACHE_PATTERNS = [
    re.compile(r"^/health$"),
    re.compile(r"^/api/skyeye/pulse$"),
]


class CacheControlMiddleware(BaseHTTPMiddleware):
    """
    Sets Cache-Control headers based on URL patterns.
    Only applies to successful GET responses (200-299).
    Never overrides an already-set Cache-Control header.
    """

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        if request.method != "GET":
            return response

        if not (200 <= response.status_code < 300):
            return response

        if "cache-control" in response.headers:
            return response

        path = request.url.path

        for pattern in _IMMUTABLE_FILE_PATTERNS:
            if pattern.match(path):
                response.headers["Cache-Control"] = "public, max-age=3600, s-maxage=86400"
                response.headers["CDN-Cache-Control"] = "max-age=86400"
                return response

        for pattern in _LONG_CACHE_PATTERNS:
            if pattern.match(path):
                response.headers["Cache-Control"] = "public, max-age=7200, s-maxage=86400"
                response.headers["CDN-Cache-Control"] = "max-age=86400"
                return response

        for pattern in _STATIC_PATTERNS:
            if pattern.match(path):
                response.headers["Cache-Control"] = "public, max-age=86400"
                response.headers["CDN-Cache-Control"] = "max-age=604800"
                return response

        for pattern in _SHORT_CACHE_PATTERNS:
            if pattern.match(path):
                response.headers["Cache-Control"] = "private, max-age=60"
                return response

        for pattern in _DASHBOARD_CACHE_PATTERNS:
            if pattern.match(path):
                response.headers["Cache-Control"] = "public, max-age=30, s-maxage=30"
                return response

        for pattern in _NO_CACHE_PATTERNS:
            if pattern.match(path):
                response.headers["Cache-Control"] = "no-cache"
                return response

        return response
