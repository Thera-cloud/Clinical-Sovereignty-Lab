"""
Workspace R2 Cache Client — Phase 8a
Sovereign Sanctuary · Little Nate Infrastructure

Python client for the Cloudflare Worker-backed R2 workspace cache.
Pushes workspace files on save, reads from cache when workspace routing
fails, and provides stats for the autonomous controller.

Env vars:
    R2_WORKSPACE_WORKER_URL  — Worker base URL (e.g. https://sovereign-workspace-cache.xxx.workers.dev)
    R2_WORKSPACE_AUTH_TOKEN  — Bearer token matching the Worker's AUTH_TOKEN secret

File: backend/app/websocket/workspace_r2_cache.py
Dependencies: aiohttp (already in requirements)
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, Optional

try:
    import aiohttp
except ImportError:
    aiohttp = None  # type: ignore


class WorkspaceR2Cache:
    """
    HTTP client for the R2 workspace cache Cloudflare Worker.

    The worker exposes:
        PUT    /workspace/<path>  — store file content
        GET    /workspace/<path>  — retrieve file content
        DELETE /workspace/<path>  — remove cached file
        GET    /workspace/_list   — list cached files
    """

    def __init__(
        self,
        worker_url: Optional[str] = None,
        auth_token: Optional[str] = None,
        timeout_seconds: int = 10,
    ):
        self._url = (worker_url or os.environ.get("R2_WORKSPACE_WORKER_URL", "")).rstrip("/")
        self._token = auth_token or os.environ.get("R2_WORKSPACE_AUTH_TOKEN", "")
        self._timeout = timeout_seconds
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def configured(self) -> bool:
        return bool(self._url and self._token and aiohttp)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._timeout),
                headers={
                    "Authorization": f"Bearer {self._token}",
                },
            )
        return self._session

    async def push_file(self, relative_path: str, content: str) -> Dict[str, Any]:
        """
        Push a workspace file to R2 cache.

        Args:
            relative_path: Path relative to workspace root (e.g. "src/main.ts")
            content: File content as string

        Returns:
            {"ok": True, "path": ..., "size": ...} on success
            {"ok": False, "error": ...} on failure
        """
        if not self.configured:
            return {"ok": False, "error": "R2 cache not configured"}
        try:
            session = await self._get_session()
            safe_path = relative_path.lstrip("/")
            url = f"{self._url}/workspace/{safe_path}"
            async with session.put(url, data=content.encode("utf-8")) as resp:
                if resp.status in (200, 201):
                    return {"ok": True, "path": safe_path, "size": len(content)}
                body = await resp.text()
                return {"ok": False, "error": f"HTTP {resp.status}: {body[:200]}"}
        except asyncio.TimeoutError:
            return {"ok": False, "error": "Timeout pushing to R2 cache"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def get_file(self, relative_path: str) -> Optional[str]:
        """
        Retrieve a file from R2 cache.

        Returns file content as string, or None if not found / error.
        """
        if not self.configured:
            return None
        try:
            session = await self._get_session()
            safe_path = relative_path.lstrip("/")
            url = f"{self._url}/workspace/{safe_path}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.text()
                return None
        except Exception:
            return None

    async def delete_file(self, relative_path: str) -> bool:
        """Delete a file from R2 cache. Returns True on success."""
        if not self.configured:
            return False
        try:
            session = await self._get_session()
            safe_path = relative_path.lstrip("/")
            url = f"{self._url}/workspace/{safe_path}"
            async with session.delete(url) as resp:
                return resp.status in (200, 204)
        except Exception:
            return False

    async def stats(self) -> Dict[str, Any]:
        """
        Get cache statistics via the Worker's _list endpoint.

        Returns:
            {"files_cached": N, "files": [...], ...} on success
            {"files_cached": 0, "error": ...} on failure
        """
        if not self.configured:
            return {"files_cached": 0, "error": "R2 cache not configured"}
        try:
            session = await self._get_session()
            url = f"{self._url}/workspace/_list"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    files = data.get("files", [])
                    return {
                        "files_cached": data.get("count", len(files)),
                        "files": files,
                    }
                return {"files_cached": 0, "error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"files_cached": 0, "error": str(e)}

    async def list_keys(self, prefix: str = "") -> list:
        """List cached file keys with optional prefix filter."""
        if not self.configured:
            return []
        try:
            session = await self._get_session()
            query = f"?prefix=workspace/{prefix}" if prefix else ""
            url = f"{self._url}/workspace/_list{query}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("files", [])
                return []
        except Exception:
            return []

    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
