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

_STT_RE = re.compile(
    r"whisper|tts|embedding|embed|realtime|audio|flux|rerank|dall-?e|"
    r"stable-diffusion|image-generation|codec",
    re.I,
)
_CHAT_KEEP_RE = re.compile(
    r"grok|gpt-|o[1-4]|claude|deepseek|llama|kimi|mistral|codestral|"
    r"phi-|qwen|gemini|command-r|jamba|mai-|sonar|devstral|ministral",
    re.I,
)
# Always-show xAI seeds when /v1/models is sparse or filtered
_XAI_SEED = (
    "grok-4",
    "grok-4-0709",
    "grok-4-1-fast-non-reasoning",
    "grok-3",
    "grok-3-mini",
    "grok-2-1212",
    "grok-2-vision-1212",
)
_FOUNDRY_PICKER_CAP = int(os.getenv("CLI_MODEL_FOUNDRY_PICKER_CAP", "80"))


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


def _foundry_picker_keep(model_id: str) -> bool:
    """Curate Foundry catalog for the IDE dropdown (chat agents only)."""
    if not _agent_eligible(model_id):
        return False
    mid = model_id or ""
    if _CHAT_KEEP_RE.search(mid):
        return True
    # Keep explicitly configured chat model even if name is unusual
    configured = os.getenv("NATE_CHAT_MODEL", "")
    return bool(configured and mid == configured)


def _curate_for_picker(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Shrink Foundry list for webview <select>; LN7 first, then contestants."""
    ln7 = [m for m in models if m.get("space") == "ln7"]
    cli = [m for m in models if m.get("space") == "cli"]
    contestant = [m for m in models if m.get("space") == "contestant"]
    xai = [
        m for m in models
        if m.get("space") == "xai" and m.get("agent_eligible", True)
    ]
    foundry_all = [
        m for m in models
        if m.get("space") == "foundry" and _foundry_picker_keep(str(m.get("id") or ""))
    ]
    # Prefer grok / gpt / claude first
    def _rank(m: Dict[str, Any]) -> tuple:
        mid = str(m.get("id") or "").lower()
        if "grok" in mid:
            return (0, mid)
        if mid.startswith("gpt-") or re.match(r"o[1-4]", mid):
            return (1, mid)
        if "claude" in mid:
            return (2, mid)
        if "deepseek" in mid:
            return (3, mid)
        return (4, mid)

    foundry_all.sort(key=_rank)
    foundry = foundry_all[: max(10, _FOUNDRY_PICKER_CAP)]
    return _merge([ln7, cli, contestant, foundry, xai])


def _cli_defaults() -> List[Dict[str, Any]]:
    """Always-present CLI / contestant space entries from env (nate_cli_chat defaults)."""
    items: List[Dict[str, Any]] = []
    seen = set()
    errors_local: List[str] = []

    def add(mid: str, label: str, *, space: str = "cli", provider: str = "grok") -> None:
        mid = (mid or "").strip()
        if not mid or mid in seen:
            return
        # QUANTUM-CRYSTAL-ARCH — never advertise broken Foundry alias grok-4.5
        try:
            from app.services.little_nate_7 import is_broken_foundry_alias
            if is_broken_foundry_alias(mid):
                errors_local.append(
                    f"skipped broken Foundry alias {mid!r} — use grok-4-1-fast-reasoning"
                )
                return
        except Exception:
            if mid.lower() in ("grok-4.5", "grok4.5"):
                errors_local.append(f"skipped broken Foundry alias {mid!r}")
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
    try:
        from app.services.little_nate_7 import contestant_reasoning_model
        reasoning = contestant_reasoning_model()
    except Exception:
        reasoning = (
            os.getenv("NATE_CLI_REASONING_MODEL")
            or os.getenv("NATE_CLI_CODE_MODEL")
            or "grok-4-1-fast-reasoning"
        )
    if reasoning:
        # Relabel as temporary contestant until LN7 is the default path
        add(reasoning, f"Contestant coding ({reasoning})", space="contestant", provider="grok")
    azure_deploy = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "")
    if azure_deploy:
        add(azure_deploy, f"Azure OpenAI ({azure_deploy})", space="cli", provider="azure")
    # Stash local catalog errors for refresh_catalog to merge
    if errors_local:
        _cache.setdefault("_cli_default_errors", [])
        _cache["_cli_default_errors"] = errors_local
    return items


async def _fetch_foundry() -> List[Dict[str, Any]]:
    key = os.getenv("NATE_CHAT_KEY") or os.getenv("AZURE_API_KEY") or ""
    out: List[Dict[str, Any]] = []
    if key:
        import aiohttp

        base = _foundry_base()
        ver = _foundry_api_version()
        urls = [
            f"{base}/models?api-version={ver}",
            f"{base}/openai/models?api-version={ver}",
        ]
        headers = {"api-key": key, "Content-Type": "application/json"}
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

    # Seed known chat models so the IDE picker is never empty for xAI when keyed
    have = {m["id"] for m in out}
    for mid in _XAI_SEED:
        if mid in have:
            continue
        out.append({
            "id": mid,
            "label": f"{mid} (xAI)",
            "space": "xai",
            "provider": "xai",
            "kind": "chat",
            "agent_eligible": _agent_eligible(mid),
            "source": "xai_seed",
        })
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
    # Prefer agent-eligible first, then space order ln7 → cli → contestant → foundry → xai
    space_rank = {"ln7": 0, "cli": 1, "contestant": 2, "foundry": 3, "xai": 4}
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
        ln7_rows: List[Dict[str, Any]] = []
        try:
            foundry = await _fetch_foundry()
        except Exception as exc:
            errors.append(f"foundry: {exc}")
        try:
            xai = await _fetch_xai()
        except Exception as exc:
            errors.append(f"xai: {exc}")
        try:
            from app.services.little_nate_7 import ln7_catalog_entries, ln7_enabled
            if ln7_enabled():
                ln7_rows = ln7_catalog_entries()
        except Exception as exc:
            errors.append(f"ln7: {exc}")

        cli_rows = _cli_defaults()
        errors.extend(list(_cache.pop("_cli_default_errors", []) or []))
        models = _merge([ln7_rows, cli_rows, foundry, xai])
        _cache["models"] = models
        _cache["refreshed_at"] = time.time()
        _cache["errors"] = errors
        _cache["counts"] = {
            "ln7": sum(1 for m in models if m.get("space") == "ln7"),
            "cli": sum(1 for m in models if m.get("space") == "cli"),
            "contestant": sum(1 for m in models if m.get("space") == "contestant"),
            "foundry": sum(1 for m in models if m.get("space") == "foundry"),
            "xai": sum(1 for m in models if m.get("space") == "xai"),
            "agent_eligible": sum(1 for m in models if m.get("agent_eligible")),
        }
        return snapshot()


def snapshot() -> Dict[str, Any]:
    full = list(_cache.get("models") or [])
    picker = _curate_for_picker(full)
    # QUANTUM-CRYSTAL-ARCH — default to LN7 when enabled
    try:
        from app.services.little_nate_7 import ln7_enabled, code_generator_mode
        use_ln7 = ln7_enabled() and code_generator_mode() == "ln7"
    except Exception:
        use_ln7 = False
    ln7_default = next((m for m in picker if m.get("space") == "ln7"), None)
    if use_ln7 and ln7_default:
        default_model = str(ln7_default.get("id") or "")
        default_space = "ln7"
    else:
        default_model = os.getenv("NATE_CHAT_MODEL", "grok-4-1-fast-non-reasoning")
        default_space = "foundry"
    return {
        "type": "nate_cli_models",
        "models": picker,
        "refreshed_at": _cache.get("refreshed_at") or 0,
        "ttl_s": _CACHE_TTL_S,
        "counts": dict(_cache.get("counts") or {}),
        "picker_counts": {
            "ln7": sum(1 for m in picker if m.get("space") == "ln7"),
            "cli": sum(1 for m in picker if m.get("space") == "cli"),
            "contestant": sum(1 for m in picker if m.get("space") == "contestant"),
            "foundry": sum(1 for m in picker if m.get("space") == "foundry"),
            "xai": sum(1 for m in picker if m.get("space") == "xai"),
        },
        "errors": list(_cache.get("errors") or []),
        "spaces": ["ln7", "cli", "contestant", "foundry", "xai"],
        "default_model": default_model,
        "default_space": default_space,
        "ln7_revised_at": (ln7_default or {}).get("revised_at"),
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

    # QUANTUM-CRYSTAL-ARCH — LN7 routes through local sovereign coder harness
    if space == "ln7" or mid.startswith("ln7:"):
        try:
            from app.services.little_nate_7 import coder_model, harness_enabled
            if not harness_enabled():
                return None
            mode = "max"
            if ":fast" in mid or mid.endswith(":fast"):
                mode = "fast"
            model = coder_model("fast" if mode == "fast" else "deep")
            # QUANTUM-CRYSTAL-ARCH — LN7_INFERENCE_URL preferred; never a vendor host
            sov_url = (
                (os.getenv("LN7_INFERENCE_URL") or "").rstrip("/")
                or (os.getenv("SOVEREIGN_INFERENCE_URL") or "").rstrip("/")
                or (os.getenv("HOME_GPU_URL") or "").rstrip("/")
            )
            if not sov_url:
                return {
                    "provider": "ln7",
                    "model": model,
                    "harness_mode": mode,
                    "url": "",
                    "headers": {},
                }
            chat_url = sov_url
            if not chat_url.endswith("/chat/completions"):
                chat_url = f"{sov_url}/v1/chat/completions"
            return {
                "provider": "ln7",
                "model": model,
                "harness_mode": mode,
                "url": chat_url,
                "headers": {"Content-Type": "application/json"},
            }
        except Exception as exc:
            logger.warning("LN7 stream target failed: %s", exc)
            return None

    if space == "contestant":
        space = "foundry"

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
