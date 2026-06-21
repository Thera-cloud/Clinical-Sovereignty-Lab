"""
Optional Zoom Docs / Hub API client (user OAuth token).

Server-to-Server OAuth cannot export Hub docs — set ZOOM_DOCS_ACCESS_TOKEN
(from a General OAuth app with docs:read:export) for Hub note retrieval.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

_DOCS_BASE = "https://api.zoom.us/v2"


class ZoomDocsClient:
    def __init__(self, access_token: str) -> None:
        self._token = (access_token or "").strip()

    @staticmethod
    def from_env() -> "ZoomDocsClient":
        return ZoomDocsClient(os.getenv("ZOOM_DOCS_ACCESS_TOKEN", ""))

    def is_configured(self) -> bool:
        return bool(self._token)

    async def get_file_markdown(self, file_id: str) -> Optional[str]:
        fid = (file_id or "").strip()
        if not fid or not self._token:
            return None
        url = f"{_DOCS_BASE}/docs/files/{fid}/content"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
            if resp.status_code != 200:
                logger.debug("Zoom Docs content %s for %s", resp.status_code, fid)
                return None
            data = resp.json()
            for key in ("content", "markdown", "body", "text"):
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
            if isinstance(data, str) and data.strip():
                return data.strip()
            return None
        except Exception as e:
            logger.debug("Zoom Docs get_file_markdown %s: %s", fid, e)
            return None

    async def list_recent_docs(self, page_size: int = 30) -> List[Dict[str, Any]]:
        if not self._token:
            return []
        url = f"{_DOCS_BASE}/docs/files"
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.get(
                    url,
                    params={"page_size": page_size},
                    headers={"Authorization": f"Bearer {self._token}"},
                )
            if resp.status_code != 200:
                return []
            data = resp.json()
            files = data.get("files") or data.get("items") or []
            return files if isinstance(files, list) else []
        except Exception as e:
            logger.debug("Zoom Docs list_recent_docs: %s", e)
            return []

    async def find_doc_by_session_id(self, session_id: str) -> Optional[Dict[str, str]]:
        sid = (session_id or "").strip()
        if not sid or not self._token:
            return None
        files = await self.list_recent_docs()
        needle = sid.upper()
        for f in files:
            title = (f.get("name") or f.get("title") or "").upper()
            if needle in title:
                fid = (f.get("id") or f.get("file_id") or "").strip()
                if fid:
                    return {
                        "file_id": fid,
                        "doc_url": f"https://docs.zoom.us/doc/{fid}",
                        "title": f.get("name") or f.get("title") or "",
                    }
        return None
