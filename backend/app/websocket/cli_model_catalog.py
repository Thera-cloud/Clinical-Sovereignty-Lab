"""CLI agent model catalog — Foundry + xAI + CLI defaults with TTL refresh.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

_CACHE_TTL_S = int(os.getenv("CLI_MODEL_CATALOG_TTL_S", "900"))
_cache: Dict[str, Any] = {"models": [], "refreshed_at": 0.0, "errors": []}
_lock = asyncio.Lock()

_STT_RE = re.compile(r"whisper|tts|embedding|embed|realtime|audio", re.I)


def _foundry_base() -> str:
    raw = (
        os.getenv("NATE_CHAT_URL")
        or "https://nathanlhr-0393-resource.services.ai.azure.com"
        "/models/chat/completions?api-version=2024-05-01-preview"
    )
    try:
        p = urlparse(raw)
        # strip path to resource root
        return urlunparse((p.scheme, p.netloc, "", "", "", "")).rstrip("/")
    except Exception:
        return "https://nathanlhr-0393-resource.services.ai.azure.com"


def _foundry_api_version() -> str:
    raw = os.getenv("NATE_CHAT_URL", "")
    m = re.search(r"api-version=([^&]+)", raw)
    return m.group(1) if m else "2024-05-01-preview"


def _agent_eligible(model_id: str, owned_by: str = "") -> bool:
    blob = f"{model_id} {owned_by}".lower()
    if _STT_RE.search(blob):
        return False
    return True


def _cli_defaults() -> List[Dict[str, Any]]:
    """Always-present CLI space entries from env (nate_cli_chat defaults)."""
    items: List[Dict[str, Any]] = []
    seen = set()

    def add(mid: str, label: str, *, space: str = "cli", provider: str = "grok") -> None:
        mid = (mid or "").strip()
        if not mid or mid in seen:
            return
        seen.add(mid)
        items.append({
            "id": mid,
            "label": label or mid,
            "space": space,
            "provider": provider,
            "kind": "chat" if _agent_eligible(mid) else "other",
            "agent_eligible": _agent_eligible(mid),
            "source": "cli_env",
        })

    add(os.getenv("NATE_CHAT_MODEL", "grok-4-1-fast-non-reasoning"), "CLI default (Foundry Grok)")
    reasoning = (
        os.getenv("NATE_CLI_REASONING_MODEL")
        or os.getenv("NATE_CLI_CODE_MODEL")
        or ""
    )
    if reasoning:
        add(reasoning, "CLI reasoning / code model", provider="grok")
    azure_deploy = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "")
    if azure_deploy:
        add(azure_deploy, f"Azure OpenAI ({azure_deploy})", space="cli", provider="azure")
    return items


async def _fetch_foundry() -> List[Dict[str, Any]]:
    key = os.getenv("NATE_CHAT_KEY") or os.getenv("AZURE_API_KEY") or ""
    if not key:
        return []
    import aiohttp

    base = _foundry_base()
    ver = _foundry_api_version()
    urls = [
        f"{base}/models?api-version={ver}",
        f"{base}/openai/models?api-version={ver}",
    ]
    headers = {"api-key": key, "Content-Type": "application/json"}
    out: List[Dict[str, Any]] = []
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for url in urls:
            try:
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.info("Foundry models %s → %s %s", url, resp.status, body[:120])
                        continue
                    data = await resp.json(content_type=None)
                    rows = data.get("data") or data.get("value") or data.get("models") or []
                    if isinstance(data, list):
                        rows = data
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        mid = (
                            row.get("id")
                            or row.get("name")
                            or row.get("model")
                            or row.get("deployment_name")
                            or ""
                        )
                        mid = str(mid).strip()
                        if not mid:
                            continue
                        eligible = _agent_eligible(mid, str(row.get("owned_by") or ""))
                        out.append({
                            "id": mid,
                            "label": mid,
                            "space": "foundry",
                            "provider": "grok" if "grok" in mid.lower() else "azure",
                            "kind": "chat" if eligible else "other",
                            "agent_eligible": eligible,
                            "source": "foundry_api",
                        })
                    if out:
                        break
            except Exception as exc:
                logger.warning("Foundry model list failed (%s): %s", url, exc)
    # Ensure configured Foundry chat model appears even if list API is locked down
    default = os.getenv("NATE_CHAT_MODEL", "grok-4-1-fast-non-reasoning")
    if default and not any(m["id"] == default for m in out):
        out.insert(0, {
            "id": default,
            "label": f"{default} (configured)",
            "space": "foundry",
            "provider": "grok",
            "kind": "chat",
            "agent_eligible": True,
            "source": "foundry_env",
        })
    return out


async def _fetch_xai() -> List[Dict[str, Any]]:
    key = (
        os.getenv("XAI_API_KEY")
        or os.getenv("NATE_CLI_CODE_KEY")
        or ""
    ).strip()
    if not key:
        return []
    import aiohttp

    url = os.getenv("XAI_MODELS_URL", "https://api.x.ai/v1/models").strip()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    out: List[Dict[str, Any]] = []
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.info("xAI models → %s %s", resp.status, body[:160])
                    return out
                data = await resp.json(content_type=None)
                rows = data.get("data") or []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    mid = str(row.get("id") or "").strip()
                    if not mid:
                        continue
                    eligible = _agent_eligible(mid)
                    out.append({
                        "id": mid,
                        "label": mid,
                        "space": "xai",
                        "provider": "xai",
                        "kind": "chat" if eligible else "other",
                        "agent_eligible": eligible,
                        "source": "xai_api",
                    })
    except Exception as exc:
        logger.warning("xAI model list failed: %s", exc)
    return out


def _merge(spaces: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    seen = set()
    merged: List[Dict[str, Any]] = []
    for group in spaces:
        for m in group:
            key = f"{m.get('space')}:{m.get('id')}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(m)
    # Prefer agent-eligible first, then space order cli → foundry → xai
    space_rank = {"cli": 0, "foundry": 1, "xai": 2}
    merged.sort(key=lambda m: (
        0 if m.get("agent_eligible") else 1,
        space_rank.get(str(m.get("space")), 9),
        str(m.get("id") or ""),
    ))
    return merged


async def refresh_catalog(force: bool = False) -> Dict[str, Any]:
    async with _lock:
        age = time.time() - float(_cache.get("refreshed_at") or 0)
        if not force and _cache.get("models") and age < _CACHE_TTL_S:
            return snapshot()

        errors: List[str] = []
        foundry: List[Dict[str, Any]] = []
        xai: List[Dict[str, Any]] = []
        try:
            foundry = await _fetch_foundry()
        except Exception as exc:
            errors.append(f"foundry: {exc}")
        try:
            xai = await _fetch_xai()
        except Exception as exc:
            errors.append(f"xai: {exc}")

        models = _merge([_cli_defaults(), foundry, xai])
        _cache["models"] = models
        _cache["refreshed_at"] = time.time()
        _cache["errors"] = errors
        _cache["counts"] = {
            "cli": sum(1 for m in models if m.get("space") == "cli"),
            "foundry": sum(1 for m in models if m.get("space") == "foundry"),
            "xai": sum(1 for m in models if m.get("space") == "xai"),
            "agent_eligible": sum(1 for m in models if m.get("agent_eligible")),
        }
        return snapshot()


def snapshot() -> Dict[str, Any]:
    return {
        "type": "nate_cli_models",
        "models": list(_cache.get("models") or []),
        "refreshed_at": _cache.get("refreshed_at") or 0,
        "ttl_s": _CACHE_TTL_S,
        "counts": dict(_cache.get("counts") or {}),
        "errors": list(_cache.get("errors") or []),
        "spaces": ["cli", "foundry", "xai"],
        "default_model": os.getenv("NATE_CHAT_MODEL", "grok-4-1-fast-non-reasoning"),
        "default_space": "foundry",
    }


async def handle_models_request(websocket, data: dict, force_refresh: bool = False) -> None:
    force = force_refresh or bool(data.get("force_refresh") or data.get("refresh"))
    try:
        payload = await refresh_catalog(force=force)
    except Exception as exc:
        payload = {
            "type": "nate_cli_models_error",
            "error": str(exc),
        }
    try:
        await websocket.send(json.dumps(payload))
    except Exception as exc:
        logger.debug("models reply failed: %s", exc)


def resolve_stream_target(
    model_id: Optional[str],
    model_space: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Map UI selection → stream url/headers/model/provider for _stream_with_tools."""
    mid = (model_id or "").strip()
    space = (model_space or "").strip().lower()
    if not mid and not space:
        return None

    if space == "xai":
        key = (
            os.getenv("XAI_API_KEY")
            or os.getenv("NATE_CLI_CODE_KEY")
            or ""
        ).strip()
        url = (
            os.getenv("XAI_CHAT_URL")
            or os.getenv("NATE_CLI_CODE_URL")
            or "https://api.x.ai/v1/chat/completions"
        ).strip()
        if key and url:
            return {
                "provider": "xai",
                "model": mid or "grok-4",
                "url": url,
                "headers": {
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            }
        return None

    if space == "azure" or (
        mid and mid == (os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT") or "")
    ):
        return {"provider": "azure", "model": mid or os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "")}

    if space in ("foundry", "cli", "") and mid:
        try:
            from app.services.nate_ai_config import NATE_CHAT_KEY, NATE_CHAT_URL
            url, key = NATE_CHAT_URL, NATE_CHAT_KEY
        except Exception:
            url = os.getenv("NATE_CHAT_URL", "")
            key = os.getenv("NATE_CHAT_KEY") or os.getenv("AZURE_API_KEY") or ""
        return {
            "provider": "grok",
            "model": mid,
            "url": url,
            "headers": {
                "api-key": key,
                "Content-Type": "application/json",
            },
        }

    return None
