"""
Sovereign Chat Client — ODPE-aware inference routing for the bridge.

Three-provider architecture with automatic fallback + Grok 429 retry:
  LOCKED/PROMOTED/PROVISIONAL → Workers AI (free, instant)
  TENSION/DEEP_TENSION → Grok 4.1 Fast via Foundry ($0.00025/query)
  Sovereign Ollama (Hetzner CAX41) → batch/background processing

The ODPE signal determines which provider handles each therapy query.
~75-80% of queries are LOCKED/PROMOTED (Workers AI = $0).
~20-25% are TENSION/DEEP_TENSION (Grok = pennies).
On Grok 429, backs off the requested wait and retries once before fallback.

Used by bridge_server.py for all therapy chat interactions.
"""

import asyncio
import json
import logging
import os
import time
from typing import AsyncIterator, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)

try:
    from app.services.provider_tracker import log_call as _track
except ImportError:
    async def _track(**kw):  # noqa: E303
        pass

# --- Provider config (captured at import, re-read lazily if empty) ---
_SOVEREIGN_URL = os.getenv("SOVEREIGN_INFERENCE_URL", "")
_SOVEREIGN_MODEL_FAST = os.getenv("SOVEREIGN_MODEL_FAST", "llama3.1:8b-instruct-q4_K_M")
_SOVEREIGN_MODEL_MID = os.getenv("SOVEREIGN_MODEL_MID", "qwen2.5:14b-instruct-q4_K_M")
_SOVEREIGN_MODEL_DEEP = os.getenv("SOVEREIGN_MODEL_DEEP", "qwen2.5:32b-instruct-q4_K_M")

_GROK_URL = os.getenv("NATE_CHAT_URL", "")
_GROK_KEY = os.getenv("NATE_CHAT_KEY", "")
_GROK_MODEL = os.getenv("NATE_CHAT_MODEL", "grok-4-1-fast-non-reasoning")

_WORKERS_AI_URL = os.getenv("WORKERS_AI_URL", "")
_WORKERS_AI_TOKEN = os.getenv("WORKERS_AI_TOKEN", "")
_WORKERS_AI_MODEL = os.getenv("WORKERS_AI_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")

# Azure OpenAI (fast fallback when Workers AI is down and Grok is slow)
_AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
_AZURE_KEY = os.getenv("AZURE_API_KEY", "")
_AZURE_CHAT_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4.1")

_inference_banner_printed = False

# Secrets left as .env.template placeholders behave as UNSET (common misconfig).
_PLACEHOLDER_TOKEN_MARKERS = (
    "your_nate_chat_key_here",
    "your_azure_api_key_here",
    "your_cloudflare_api_token_here",
    "changeme",
    "replace_me",
    "sk-placeholder",
)


def _strip_env(val: Optional[str]) -> str:
    return (val or "").strip()


def _is_placeholder_secret(val: str) -> bool:
    if not val:
        return True
    low = val.strip().lower()
    if low in ("", "none", "null", "xxx", "changeme"):
        return True
    for marker in _PLACEHOLDER_TOKEN_MARKERS:
        if marker in low:
            return True
    return False


def _reload_inference_env():
    """Always sync globals from os.environ (fixes Docker/import-order races; pick up new .env)."""
    global _SOVEREIGN_URL, _GROK_URL, _GROK_KEY, _GROK_MODEL
    global _WORKERS_AI_URL, _WORKERS_AI_TOKEN, _WORKERS_AI_MODEL
    global _AZURE_ENDPOINT, _AZURE_KEY, _AZURE_CHAT_DEPLOYMENT

    _SOVEREIGN_URL = _strip_env(os.getenv("SOVEREIGN_INFERENCE_URL", ""))
    _GROK_URL = _strip_env(os.getenv("NATE_CHAT_URL", ""))
    _GROK_KEY = _strip_env(os.getenv("NATE_CHAT_KEY", ""))
    _GROK_MODEL = _strip_env(os.getenv("NATE_CHAT_MODEL", "")) or "grok-4-1-fast-non-reasoning"
    _WORKERS_AI_URL = _strip_env(os.getenv("WORKERS_AI_URL", ""))
    _WORKERS_AI_TOKEN = _strip_env(os.getenv("WORKERS_AI_TOKEN", ""))
    _WORKERS_AI_MODEL = _strip_env(os.getenv("WORKERS_AI_MODEL", "")) or "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    _AZURE_ENDPOINT = _strip_env(os.getenv("AZURE_OPENAI_ENDPOINT", ""))
    _AZURE_KEY = _strip_env(os.getenv("AZURE_API_KEY", ""))
    _AZURE_CHAT_DEPLOYMENT = _strip_env(os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "")) or "gpt-4.1"

    if _is_placeholder_secret(_GROK_KEY):
        _GROK_KEY = ""
    if _is_placeholder_secret(_WORKERS_AI_TOKEN):
        _WORKERS_AI_TOKEN = ""
    if _is_placeholder_secret(_AZURE_KEY):
        _AZURE_KEY = ""


def inference_configuration_gaps() -> List[str]:
    """Human-readable misconfiguration lines (empty if at least one provider is viable)."""
    _reload_inference_env()
    gaps: List[str] = []
    grok_ok = bool(_GROK_URL and _GROK_KEY)
    workers_ok = bool(_WORKERS_AI_URL and _WORKERS_AI_TOKEN)
    ollama_ok = bool(_SOVEREIGN_URL)
    azure_ok = bool(_AZURE_ENDPOINT and _AZURE_KEY)

    if not grok_ok:
        if not _GROK_URL:
            gaps.append("Grok: NATE_CHAT_URL is empty — set full Foundry/chat completions URL (see .env.template).")
        elif not _GROK_KEY:
            gaps.append("Grok: NATE_CHAT_KEY is empty or still a placeholder — set the real API key (paired with NATE_CHAT_URL).")
        else:
            gaps.append("Grok: NATE_CHAT_KEY looks like a template placeholder — replace with a real key.")
    if not workers_ok:
        if not _WORKERS_AI_URL:
            gaps.append("Workers AI: WORKERS_AI_URL is empty — set Cloudflare AI URL (see .env.template).")
        elif not _WORKERS_AI_TOKEN:
            gaps.append(
                "Workers AI: WORKERS_AI_TOKEN is empty or placeholder — set CLOUDFLARE_API_TOKEN (Bearer); pair with WORKERS_AI_URL."
            )
        else:
            gaps.append("Workers AI: WORKERS_AI_TOKEN looks like a template placeholder.")
    if not ollama_ok:
        gaps.append(
            "Sovereign Ollama: SOVEREIGN_INFERENCE_URL is empty — e.g. http://127.0.0.1:11434 "
            "or http://host.docker.internal:11434 from Docker Desktop."
        )

    if grok_ok or workers_ok or ollama_ok or azure_ok:
        return []
    return gaps


def format_inference_setup_help() -> str:
    """Multi-line remediation for RuntimeError and admin logs."""
    gaps = inference_configuration_gaps()
    lines = [
        "No inference provider is usable. Rules — always set credentials as PAIRS where applicable:",
        "  • Grok (Foundry): NATE_CHAT_URL + NATE_CHAT_KEY (HTTP api-key header; no separate username).",
        "  • Workers AI: WORKERS_AI_URL + WORKERS_AI_TOKEN (Bearer token from Cloudflare).",
        "  • Ollama: SOVEREIGN_INFERENCE_URL only (no password; bind reachable from the bridge container).",
        "  • PostgreSQL (separate): POSTGRES_USER + POSTGRES_PASSWORD — required for DB, not for LLM routing.",
        "",
        "Other paths (not used by sovereign_chat_client streaming — wire via router/NateInferenceRouter):",
        "  HOME_GPU_URL, DIGITAL_OCEAN_INFERENCE_URL, AZURE_OPENAI_* for chat/realtime elsewhere.",
        "",
        "Docker: after editing .env, use `docker compose up -d` (not only restart) so the backend container receives vars.",
        "",
    ]
    if gaps:
        lines.append("Detected issues:")
        lines.extend(f"  - {g}" for g in gaps)
    else:
        lines.append(
            "Env looks set but every request failed — check network/firewall, model names, "
            "and bridge logs for TTFT timeouts or 401/403 from Grok/Workers/Ollama."
        )
    return "\n".join(lines)


def inference_providers_configured() -> bool:
    """True if at least one sovereign_chat_client provider can be called."""
    _reload_inference_env()
    return bool(
        (_GROK_URL and _GROK_KEY)
        or (_WORKERS_AI_URL and _WORKERS_AI_TOKEN)
        or _SOVEREIGN_URL
        or (_AZURE_ENDPOINT and _AZURE_KEY)
    )


def _ensure_config():
    """Reload env from OS and print one-time banner."""
    global _inference_banner_printed
    _reload_inference_env()

    configured = []
    if _GROK_URL and _GROK_KEY:
        configured.append("Grok")
    if _WORKERS_AI_URL and _WORKERS_AI_TOKEN:
        configured.append("Workers AI")
    if _SOVEREIGN_URL:
        configured.append("Sovereign")
    if _AZURE_ENDPOINT and _AZURE_KEY:
        configured.append("Azure")

    if not _inference_banner_printed:
        _inference_banner_printed = True
        print(f"[INFERENCE] Configured providers: {', '.join(configured) or 'NONE'}")
        if not configured:
            logger.warning("[INFERENCE] No providers configured at startup:\n%s", format_inference_setup_help())

OLLAMA_PARALLEL_SLOTS = int(os.getenv("OLLAMA_NUM_PARALLEL", "4"))
OVERFLOW_THRESHOLD = int(os.getenv("SOVEREIGN_OVERFLOW_THRESHOLD", str(OLLAMA_PARALLEL_SLOTS)))

_inflight_sovereign = 0
_inflight_lock = asyncio.Lock()
_sovereign_stats = {
    "total_sovereign": 0,
    "total_grok": 0,
    "total_workers_ai": 0,
    "total_overflow": 0,
    "total_azure_fallback": 0,
    "peak_inflight": 0,
}

_ollama_session: Optional[aiohttp.ClientSession] = None
_grok_session: Optional[aiohttp.ClientSession] = None
_workers_session: Optional[aiohttp.ClientSession] = None


def _get_ollama_session(timeout_secs: int = 180) -> aiohttp.ClientSession:
    global _ollama_session
    if _ollama_session is None or _ollama_session.closed:
        timeout = aiohttp.ClientTimeout(total=timeout_secs, sock_read=timeout_secs)
        connector = aiohttp.TCPConnector(limit=OLLAMA_PARALLEL_SLOTS + 2, keepalive_timeout=300)
        _ollama_session = aiohttp.ClientSession(timeout=timeout, connector=connector)
    return _ollama_session


def _get_grok_session() -> aiohttp.ClientSession:
    global _grok_session
    if _grok_session is None or _grok_session.closed:
        timeout = aiohttp.ClientTimeout(total=60, sock_read=60)
        connector = aiohttp.TCPConnector(limit=20, keepalive_timeout=120)
        _grok_session = aiohttp.ClientSession(timeout=timeout, connector=connector)
    return _grok_session


def _get_workers_session() -> aiohttp.ClientSession:
    global _workers_session
    if _workers_session is None or _workers_session.closed:
        timeout = aiohttp.ClientTimeout(total=120, sock_connect=5, sock_read=30)
        connector = aiohttp.TCPConnector(limit=20, keepalive_timeout=120)
        _workers_session = aiohttp.ClientSession(timeout=timeout, connector=connector)
    return _workers_session


def get_routing_stats() -> Dict:
    total = sum(_sovereign_stats[k] for k in (
        "total_sovereign", "total_grok", "total_workers_ai",
        "total_overflow", "total_azure_fallback",
    ))
    zero_cost = _sovereign_stats["total_sovereign"] + _sovereign_stats["total_workers_ai"]
    sov_pct = ((zero_cost / total * 100) if total > 0 else 0)
    return {
        **_sovereign_stats,
        "current_inflight": _inflight_sovereign,
        "overflow_threshold": OVERFLOW_THRESHOLD,
        "parallel_slots": OLLAMA_PARALLEL_SLOTS,
        "sovereignty_pct": round(sov_pct, 1),
        "grok_configured": bool(_GROK_URL and _GROK_KEY),
        "workers_ai_configured": bool(_WORKERS_AI_URL and _WORKERS_AI_TOKEN),
        "sovereign_configured": bool(_SOVEREIGN_URL),
        "azure_configured": bool(_AZURE_ENDPOINT and _AZURE_KEY),
        "any_provider_configured": inference_providers_configured(),
    }


def log_inference_config() -> None:
    """Log which inference providers are configured at startup (masks secrets)."""
    _ensure_config()
    grok = bool(_GROK_URL and _GROK_KEY)
    workers = bool(_WORKERS_AI_URL and _WORKERS_AI_TOKEN)
    sovereign = bool(_SOVEREIGN_URL)
    azure = bool(_AZURE_ENDPOINT and _AZURE_KEY)
    lines = [
        "[INFERENCE] Providers:",
        f"  Grok (NATE_CHAT_*): {'✓' if grok else '✗'}",
        f"  Workers AI:         {'✓' if workers else '✗'}",
        f"  Sovereign Ollama:   {'✓' if sovereign else '✗'}",
        f"  Azure OpenAI:       {'✓' if azure else '✗'}",
    ]
    if not (grok or workers or sovereign or azure):
        lines.append("[INFERENCE] ⚠️ No provider configured — see full checklist in logs (inference setup help).")
        logger.warning("%s", format_inference_setup_help())
    for line in lines:
        print(line)
        logger.info(line)


_FORCE_FAST = os.getenv("SOVEREIGN_FORCE_FAST", "false").lower() in ("true", "1", "yes")
_HAS_GPU = os.getenv("SOVEREIGN_HAS_GPU", "false").lower() in ("true", "1", "yes")


def _first_configured_provider(*preference: str) -> str:
    """Pick the first provider in preference order that has env configured."""
    _reload_inference_env()
    for p in preference:
        if p == "sovereign" and _SOVEREIGN_URL:
            return p
        if p == "grok" and _GROK_URL and _GROK_KEY:
            return p
        if p == "workers_ai" and _WORKERS_AI_URL and _WORKERS_AI_TOKEN:
            return p
        if p == "azure" and _AZURE_ENDPOINT and _AZURE_KEY:
            return p
    return preference[0] if preference else "grok"


def _resolve_provider_for_signal(odpe_signal: Optional[str] = None, domain: str = "general") -> str:
    """ODPE-aware routing decision for interactive therapy/coding chat.

    LOCKED/PROMOTED/PROVISIONAL/None → workers_ai (free) → grok → sovereign → azure
    TENSION/DEEP_TENSION (clinical)  → grok (clinical depth) → workers_ai → sovereign → azure
    TENSION/DEEP_TENSION (coding)    → sovereign 14B (zero cost) → grok → workers_ai → azure
    NOISE → skip (handled before this is called)

    Azure is emergency-only fallback. Zero-cost providers first.
    """
    if domain == "coding" and odpe_signal in ("TENSION", "DEEP_TENSION"):
        return _first_configured_provider("sovereign", "grok", "workers_ai", "azure")

    if odpe_signal in ("LOCKED", "PROMOTED", None, "PROVISIONAL"):
        return _first_configured_provider("workers_ai", "grok", "sovereign", "azure")

    if odpe_signal in ("TENSION", "DEEP_TENSION", "LIMINAL_RESOLVE"):
        return _first_configured_provider("grok", "workers_ai", "sovereign", "azure")

    return _first_configured_provider("workers_ai", "grok", "sovereign", "azure")


_FALLBACK_CHAIN = {
    "workers_ai": ["grok", "sovereign", "azure"],
    "grok": ["workers_ai", "sovereign", "azure"],
    "sovereign": ["workers_ai", "grok", "azure"],
    "azure": ["grok", "workers_ai", "sovereign"],
}

# TTFT ceilings (seconds) — reroute to next provider if first token exceeds this
_TTFT_CEILING = {
    "sovereign": 30.0,
    "grok": 15.0,
    "workers_ai": 8.0,
    "azure": 10.0,
}


class TTFTTimeoutError(Exception):
    """First token took too long — triggers fallback to next provider."""
    pass


class RateLimitError(Exception):
    """Provider returned 429 — retry after backoff."""
    def __init__(self, wait_seconds: float, message: str = ""):
        self.wait_seconds = wait_seconds
        super().__init__(message or f"Rate limited, retry after {wait_seconds}s")


def _parse_429_wait(error_text: str) -> float:
    """Extract wait seconds from a 429 error body. Falls back to 15s."""
    import re
    m = re.search(r"wait\s+(\d+)\s+seconds", error_text, re.IGNORECASE)
    if m:
        return float(m.group(1)) + 1.0
    m = re.search(r"retry.after.*?(\d+)", error_text, re.IGNORECASE)
    if m:
        return float(m.group(1)) + 1.0
    return 15.0


async def _with_ttft_ceiling(stream, provider_name: str):
    """Wrap an async generator with a TTFT ceiling.

    If the first token doesn't arrive within the provider's ceiling,
    raises TTFTTimeoutError to trigger fallback. After the first token
    arrives, streams normally with no additional timeout overhead.

    Catches both asyncio.TimeoutError (from wait_for) and aiohttp socket
    timeouts (ServerTimeoutError) which race when a provider is slow.
    """
    ttft_limit = _TTFT_CEILING.get(provider_name, 10.0)
    aiter = stream.__aiter__()
    try:
        first_token = await asyncio.wait_for(aiter.__anext__(), timeout=ttft_limit)
    except (asyncio.TimeoutError, aiohttp.ServerTimeoutError) as e:
        logger.warning("%s TTFT exceeded %.1fs ceiling — rerouting to next provider (err: %s)",
                       provider_name, ttft_limit, type(e).__name__)
        raise TTFTTimeoutError(
            f"{provider_name} TTFT exceeded {ttft_limit}s ceiling")
    except StopAsyncIteration:
        return
    yield first_token
    async for token in aiter:
        yield token


def _select_sovereign_model(odpe_signal: Optional[str] = None, allow_deep: bool = False) -> str:
    if _FORCE_FAST:
        return _SOVEREIGN_MODEL_FAST
    if _HAS_GPU:
        if odpe_signal == "DEEP_TENSION" and allow_deep:
            return _SOVEREIGN_MODEL_DEEP
        elif odpe_signal in ("TENSION", "LIMINAL_RESOLVE", "PROVISIONAL", "DEEP_TENSION"):
            return _SOVEREIGN_MODEL_MID
    return _SOVEREIGN_MODEL_FAST


def _timeout_for_model(model: str) -> int:
    if model == _SOVEREIGN_MODEL_DEEP:
        return 240
    elif model == _SOVEREIGN_MODEL_MID:
        return 180
    return 180


async def _acquire_sovereign_slot() -> bool:
    global _inflight_sovereign
    async with _inflight_lock:
        if _inflight_sovereign >= OVERFLOW_THRESHOLD:
            return False
        _inflight_sovereign += 1
        if _inflight_sovereign > _sovereign_stats["peak_inflight"]:
            _sovereign_stats["peak_inflight"] = _inflight_sovereign
        return True


async def _release_sovereign_slot():
    global _inflight_sovereign
    async with _inflight_lock:
        _inflight_sovereign = max(0, _inflight_sovereign - 1)


def _stat_key(provider: str) -> str:
    """Map provider name to stats dict key."""
    if provider == "workers_ai":
        return "total_workers_ai"
    if provider == "grok":
        return "total_grok"
    if provider == "sovereign":
        return "total_sovereign"
    return "total_overflow"


async def _try_stream(provider: str, messages: List[Dict],
                      temperature: float, max_tokens: int,
                      odpe_signal: Optional[str], allow_deep: bool) -> Optional[AsyncIterator]:
    """Attempt to stream from a single provider. Returns None on failure."""
    if provider == "workers_ai" and _WORKERS_AI_URL and _WORKERS_AI_TOKEN:
        return _stream_workers_ai(messages, temperature, max_tokens)
    if provider == "azure" and _AZURE_ENDPOINT and _AZURE_KEY:
        return _stream_azure(messages, temperature, max_tokens)
    if provider == "grok" and _GROK_URL and _GROK_KEY:
        return _stream_grok(messages, temperature, max_tokens)
    if provider == "sovereign" and _SOVEREIGN_URL:
        if await _acquire_sovereign_slot():
            model = _select_sovereign_model(odpe_signal, allow_deep)
            return _stream_ollama(messages, model, temperature, max_tokens,
                                 _timeout_for_model(model))
    return None


async def generate_streaming(
    system_prompt: str,
    user_message: str,
    *,
    odpe_signal: Optional[str] = None,
    allow_deep: bool = False,
    temperature: float = 0.7,
    max_tokens: int = 1500,
    domain: str = "general",
    image_data_url: Optional[str] = None,
) -> AsyncIterator[Tuple[str, str]]:
    """
    Stream tokens from the ODPE-selected provider with automatic fallback.

    Yields (delta_text, provider) tuples as tokens arrive.

    Routing:
      LOCKED/PROMOTED → Workers AI (free)
      TENSION/DEEP_TENSION → Grok 4.1 Fast via Foundry (~$0.00025/query)
      domain="coding" + TENSION → sovereign (Ollama) first

    On Grok 429 (rate limit), waits the requested backoff and retries once
    before falling back to the next provider in the chain.
    """
    _ensure_config()

    primary = _resolve_provider_for_signal(odpe_signal, domain=domain)
    providers_to_try = [primary] + _FALLBACK_CHAIN.get(primary, [])
    seen = set()

    _t0 = time.monotonic()
    _chars_out = 0

    from app.websocket.cli_prompt_budget import trim_prompt_to_ceiling

    # SOVEREIGN-VOICE: if image present, prefer vision-capable providers
    if image_data_url:
        _vision_providers = [p for p in providers_to_try if p in ("azure", "grok")]
        if _vision_providers:
            providers_to_try = _vision_providers + [p for p in providers_to_try if p not in _vision_providers]

    for provider in providers_to_try:
        if provider in seen:
            continue
        seen.add(provider)

        try:
            _sp, _um = trim_prompt_to_ceiling(
                system_prompt, user_message, provider, max_tokens
            )
            if image_data_url and provider in ("azure", "grok"):
                messages = [
                    {"role": "system", "content": _sp},
                    {"role": "user", "content": [
                        {"type": "text", "text": _um},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ]},
                ]
            else:
                messages = [
                    {"role": "system", "content": _sp},
                    {"role": "user", "content": _um},
                ]
            _chars_in = len(_sp) + len(_um)

            if provider == "sovereign":
                slot_acquired = await _acquire_sovereign_slot()
                if not slot_acquired:
                    logger.info("Overflow: %d in-flight >= threshold %d — skipping sovereign",
                                _inflight_sovereign, OVERFLOW_THRESHOLD)
                    _sovereign_stats["total_overflow"] += 1
                    continue
                model = _select_sovereign_model(odpe_signal, allow_deep)
                timeout_secs = _timeout_for_model(model)
                logger.info("Sovereign slot acquired (inflight=%d/%d) model=%s odpe=%s",
                            _inflight_sovereign, OVERFLOW_THRESHOLD, model, odpe_signal)
                try:
                    _provider_chars = 0
                    async for delta in _with_ttft_ceiling(
                        _stream_ollama(messages, model, temperature, max_tokens, timeout_secs), "sovereign"
                    ):
                        _provider_chars += len(delta)
                        _chars_out += len(delta)
                        yield (delta, "sovereign")
                    if _provider_chars == 0:
                        logger.warning("Sovereign returned 0 chunks — falling back to next provider")
                        continue
                    _sovereign_stats["total_sovereign"] += 1
                    asyncio.ensure_future(_track(provider="sovereign", chars_in=_chars_in, chars_out=_chars_out, duration_ms=int((time.monotonic() - _t0) * 1000), domain=domain, odpe_signal=odpe_signal or "PROVISIONAL"))
                    return
                finally:
                    await _release_sovereign_slot()

            elif provider == "workers_ai" and _WORKERS_AI_URL and _WORKERS_AI_TOKEN:
                logger.info("ODPE→Workers AI (odpe=%s, free tier)", odpe_signal)
                _provider_chars = 0
                async for delta in _with_ttft_ceiling(
                    _stream_workers_ai(messages, temperature, max_tokens), "workers_ai"
                ):
                    _provider_chars += len(delta)
                    _chars_out += len(delta)
                    yield (delta, "workers_ai")
                if _provider_chars == 0:
                    logger.warning("Workers AI returned 0 chunks — falling back to next provider")
                    continue
                _sovereign_stats["total_workers_ai"] += 1
                asyncio.ensure_future(_track(provider="workers_ai", chars_in=_chars_in, chars_out=_chars_out, duration_ms=int((time.monotonic() - _t0) * 1000), domain=domain, odpe_signal=odpe_signal or "PROVISIONAL"))
                return

            elif provider == "azure" and _AZURE_ENDPOINT and _AZURE_KEY:
                logger.info("ODPE→Azure OpenAI (odpe=%s, deployment=%s)", odpe_signal, _AZURE_CHAT_DEPLOYMENT)
                _provider_chars = 0
                async for delta in _with_ttft_ceiling(
                    _stream_azure(messages, temperature, max_tokens), "azure"
                ):
                    _provider_chars += len(delta)
                    _chars_out += len(delta)
                    yield (delta, "azure")
                if _provider_chars == 0:
                    logger.warning("Azure OpenAI returned 0 chunks — falling back to next provider")
                    continue
                _sovereign_stats["total_azure_fallback"] += 1
                asyncio.ensure_future(_track(provider="azure", chars_in=_chars_in, chars_out=_chars_out, duration_ms=int((time.monotonic() - _t0) * 1000), domain=domain, odpe_signal=odpe_signal or "PROVISIONAL"))
                return

            elif provider == "grok" and _GROK_URL and _GROK_KEY:
                for attempt in range(2):
                    try:
                        logger.info("ODPE→Grok Foundry (odpe=%s, model=%s, attempt=%d)",
                                    odpe_signal, _GROK_MODEL, attempt + 1)
                        _provider_chars = 0
                        async for delta in _with_ttft_ceiling(
                            _stream_grok(messages, temperature, max_tokens), "grok"
                        ):
                            _provider_chars += len(delta)
                            _chars_out += len(delta)
                            yield (delta, "grok")
                        if _provider_chars == 0:
                            logger.warning("Grok returned 0 chunks — falling back to next provider")
                            continue
                        _sovereign_stats["total_grok"] += 1
                        asyncio.ensure_future(_track(provider="grok", chars_in=_chars_in, chars_out=_chars_out, duration_ms=int((time.monotonic() - _t0) * 1000), domain=domain, odpe_signal=odpe_signal or "PROVISIONAL"))
                        return
                    except RateLimitError as rl:
                        if attempt == 0:
                            wait = min(rl.wait_seconds, 65.0)
                            logger.warning("Grok 429 rate-limited — backing off %.1fs before retry", wait)
                            await asyncio.sleep(wait)
                        else:
                            raise

        except Exception as e:
            logger.warning("%s streaming failed (odpe=%s): %s — trying next provider",
                           provider, odpe_signal, e)
            continue

    raise RuntimeError(
        "No inference providers configured or all failed.\n" + format_inference_setup_help()
    )


async def generate_complete(
    system_prompt: str,
    user_message: str,
    *,
    odpe_signal: Optional[str] = None,
    allow_deep: bool = False,
    temperature: float = 0.7,
    max_tokens: int = 1500,
    domain: str = "general",
) -> Tuple[str, str]:
    """
    Non-streaming generation with ODPE routing. Returns (full_text, provider).

    On Grok 429 (rate limit), waits the requested backoff and retries once
    before falling back to the next provider in the chain.
    """
    _ensure_config()

    primary = _resolve_provider_for_signal(odpe_signal, domain=domain)
    providers_to_try = [primary] + _FALLBACK_CHAIN.get(primary, [])
    seen = set()
    _t0 = time.monotonic()

    from app.websocket.cli_prompt_budget import trim_prompt_to_ceiling

    for provider in providers_to_try:
        if provider in seen:
            continue
        seen.add(provider)

        try:
            _sp, _um = trim_prompt_to_ceiling(
                system_prompt, user_message, provider, max_tokens
            )
            messages = [
                {"role": "system", "content": _sp},
                {"role": "user", "content": _um},
            ]
            _chars_in = len(_sp) + len(_um)

            if provider == "sovereign" and _SOVEREIGN_URL:
                slot_acquired = await _acquire_sovereign_slot()
                if not slot_acquired:
                    _sovereign_stats["total_overflow"] += 1
                    continue
                model = _select_sovereign_model(odpe_signal, allow_deep)
                try:
                    text = await _complete_ollama(messages, model, temperature, max_tokens,
                                                 _timeout_for_model(model))
                    _sovereign_stats["total_sovereign"] += 1
                    asyncio.ensure_future(_track(provider="sovereign", chars_in=_chars_in, chars_out=len(text), duration_ms=int((time.monotonic() - _t0) * 1000), domain=domain, odpe_signal=odpe_signal or "PROVISIONAL"))
                    return (text, "sovereign")
                finally:
                    await _release_sovereign_slot()

            elif provider == "workers_ai" and _WORKERS_AI_URL and _WORKERS_AI_TOKEN:
                text = await _complete_workers_ai(messages, temperature, max_tokens)
                _sovereign_stats["total_workers_ai"] += 1
                asyncio.ensure_future(_track(provider="workers_ai", chars_in=_chars_in, chars_out=len(text), duration_ms=int((time.monotonic() - _t0) * 1000), domain=domain, odpe_signal=odpe_signal or "PROVISIONAL"))
                return (text, "workers_ai")

            elif provider == "azure" and _AZURE_ENDPOINT and _AZURE_KEY:
                text = await _complete_azure(messages, temperature, max_tokens)
                _sovereign_stats["total_azure_fallback"] += 1
                asyncio.ensure_future(_track(provider="azure", chars_in=_chars_in, chars_out=len(text), duration_ms=int((time.monotonic() - _t0) * 1000), domain=domain, odpe_signal=odpe_signal or "PROVISIONAL"))
                return (text, "azure")

            elif provider == "grok" and _GROK_URL and _GROK_KEY:
                for attempt in range(2):
                    try:
                        text = await _complete_grok(messages, temperature, max_tokens)
                        _sovereign_stats["total_grok"] += 1
                        asyncio.ensure_future(_track(provider="grok", chars_in=_chars_in, chars_out=len(text), duration_ms=int((time.monotonic() - _t0) * 1000), domain=domain, odpe_signal=odpe_signal or "PROVISIONAL"))
                        return (text, "grok")
                    except RateLimitError as rl:
                        if attempt == 0:
                            wait = min(rl.wait_seconds, 65.0)
                            logger.warning("Grok 429 rate-limited — backing off %.1fs before retry", wait)
                            await asyncio.sleep(wait)
                        else:
                            raise

        except Exception as e:
            logger.warning("%s complete failed (odpe=%s): %s", provider, odpe_signal, e)
            continue

    raise RuntimeError(
        "No inference providers configured or all failed.\n" + format_inference_setup_help()
    )


async def summarize_turns_async(turns: List[Dict]) -> Optional[str]:
    """
    Emergency compression: summarize older turns via Grok or Workers AI (not Azure).
    Used when >8 turns to condense context. Background, not user-facing.
    Returns None if no provider available or on failure.
    """
    if not turns:
        return None
    conversation = "\n".join(
        f"User: {t.get('user_text', '')}\nNate: {t.get('ai_text', '')}"
        for t in turns
    )
    if not conversation.strip():
        return None
    messages = [
        {"role": "system", "content": "Summarize this therapy conversation into 3-5 sentences. Preserve themes, emotions, and key points. Output only the summary, no preamble."},
        {"role": "user", "content": conversation},
    ]
    for provider, fn, configured in [
        ("grok", _complete_grok, bool(_GROK_URL and _GROK_KEY)),
        ("workers_ai", _complete_workers_ai, bool(_WORKERS_AI_URL and _WORKERS_AI_TOKEN)),
    ]:
        if not configured:
            continue
        try:
            text = await fn(messages, temperature=0.3, max_tokens=300)
            if text and text.strip():
                return text.strip()
        except Exception as e:
            logger.warning("Emergency compression %s failed: %s", provider, e)
            continue
    return None


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

_OLLAMA_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
_MAX_SYSTEM_CHARS = int(os.getenv("SOVEREIGN_MAX_SYSTEM_CHARS", "6000"))


def _trim_messages_for_ollama(messages: List[Dict], max_system_chars: int) -> List[Dict]:
    """Aggressively trim the system prompt so Ollama has headroom for generation."""
    trimmed = []
    for m in messages:
        content = m.get("content", "")
        if m["role"] == "system" and len(content) > max_system_chars:
            original_len = len(content)
            content = content[:max_system_chars]
            last_period = content.rfind(".")
            if last_period > max_system_chars * 0.8:
                content = content[: last_period + 1]
            logger.debug("Trimmed system prompt %d -> %d chars (~%d -> ~%d tokens)",
                        original_len, len(content), original_len // 4, len(content) // 4)
        trimmed.append({**m, "content": content})
    return trimmed


# --- Ollama (Sovereign Hetzner) ---

async def _stream_ollama(
    messages: List[Dict], model: str, temperature: float, max_tokens: int, timeout_secs: int
) -> AsyncIterator[str]:
    url = f"{_SOVEREIGN_URL.rstrip('/')}/api/chat"
    _sys_cap = min(_MAX_SYSTEM_CHARS * 2, 12000) if max_tokens > 1500 else _MAX_SYSTEM_CHARS
    messages = _trim_messages_for_ollama(messages, _sys_cap)
    total_chars = sum(len(m.get("content", "")) for m in messages)
    _ollama_hard_cap = 2000 if max_tokens > 1500 else 800
    capped_tokens = min(max_tokens, _ollama_hard_cap)
    print(f">>> [SOVEREIGN] Ollama request: model={model} total_prompt_chars={total_chars} "
          f"(~{total_chars // 4} tokens) max_tokens={capped_tokens} timeout={timeout_secs}s ctx={_OLLAMA_CTX}")
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {
            "num_ctx": _OLLAMA_CTX,
            "temperature": temperature,
            "num_predict": capped_tokens,
        },
    }
    t0 = time.time()
    session = _get_ollama_session(timeout_secs)
    async with session.post(url, json=payload) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(f"Ollama {resp.status}: {body[:200]}")
        first_token_time = None
        token_count = 0
        async for line in resp.content:
            decoded = line.decode("utf-8", errors="ignore").strip()
            if not decoded:
                continue
            try:
                chunk = json.loads(decoded)
                if chunk.get("done"):
                    break
                delta = chunk.get("message", {}).get("content", "")
                if delta:
                    if first_token_time is None:
                        first_token_time = time.time()
                        print(f">>> [SOVEREIGN] First token in {first_token_time - t0:.1f}s")
                    token_count += 1
                    yield delta
            except (json.JSONDecodeError, IndexError, KeyError):
                continue
        elapsed = time.time() - t0
        print(f">>> [SOVEREIGN] Ollama stream complete: {token_count} chunks in {elapsed:.1f}s")


async def _complete_ollama(
    messages: List[Dict], model: str, temperature: float, max_tokens: int, timeout_secs: int
) -> str:
    url = f"{_SOVEREIGN_URL.rstrip('/')}/api/chat"
    _sys_cap = min(_MAX_SYSTEM_CHARS * 2, 12000) if max_tokens > 1500 else _MAX_SYSTEM_CHARS
    messages = _trim_messages_for_ollama(messages, _sys_cap)
    total_chars = sum(len(m.get("content", "")) for m in messages)
    _ollama_hard_cap = 2000 if max_tokens > 1500 else 800
    capped_tokens = min(max_tokens, _ollama_hard_cap)
    print(f">>> [SOVEREIGN] Ollama complete: model={model} prompt_chars={total_chars} "
          f"max_tokens={capped_tokens} timeout={timeout_secs}s")
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "num_ctx": _OLLAMA_CTX,
            "temperature": temperature,
            "num_predict": capped_tokens,
        },
    }
    t0 = time.time()
    session = _get_ollama_session(timeout_secs)
    async with session.post(url, json=payload) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(f"Ollama {resp.status}: {body[:200]}")
        data = await resp.json()
        text = data.get("message", {}).get("content", "")
        print(f">>> [SOVEREIGN] Ollama complete done in {time.time() - t0:.1f}s ({len(text)} chars)")
        return text


# --- Grok via Azure AI Foundry (TENSION queries) ---

async def _stream_grok(
    messages: List[Dict], temperature: float, max_tokens: int
) -> AsyncIterator[str]:
    """Stream from Grok 4.1 Fast via Azure AI Foundry — OpenAI-compatible SSE."""
    headers = {
        "api-key": _GROK_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "model": _GROK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
        "stream": True,
    }
    t0 = time.time()
    session = _get_grok_session()
    async with session.post(_GROK_URL, json=payload, headers=headers) as resp:
        if resp.status == 429:
            body = await resp.text()
            wait = _parse_429_wait(body)
            raise RateLimitError(wait, f"Grok 429: {body[:200]}")
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(f"Grok Foundry {resp.status}: {body[:300]}")
        first_token_time = None
        token_count = 0
        async for line in resp.content:
            decoded = line.decode("utf-8", errors="ignore").strip()
            if not decoded.startswith("data: "):
                continue
            data_str = decoded[6:]
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
                choices = chunk.get("choices", [])
                if not choices:
                    continue
                d = choices[0].get("delta", {})
                delta = d.get("content") or ""
                # When Grok returns tool_calls instead of content, content is empty
                if not delta and d.get("tool_calls") and token_count == 0:
                    print(f">>> [GROK] Chunk has tool_calls but no content (model may use native FC) — add tools param or use XML in prompt")
                if delta:
                    if first_token_time is None:
                        first_token_time = time.time()
                        print(f">>> [GROK] First token in {first_token_time - t0:.1f}s")
                    token_count += 1
                    yield delta
            except (json.JSONDecodeError, IndexError, KeyError):
                continue
        elapsed = time.time() - t0
        print(f">>> [GROK] Stream complete: {token_count} chunks in {elapsed:.1f}s (model={_GROK_MODEL})")


async def _complete_grok(
    messages: List[Dict], temperature: float, max_tokens: int
) -> str:
    """Non-streaming Grok via Azure AI Foundry."""
    headers = {
        "api-key": _GROK_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "model": _GROK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
        "stream": False,
    }
    t0 = time.time()
    session = _get_grok_session()
    async with session.post(_GROK_URL, json=payload, headers=headers) as resp:
        if resp.status == 429:
            body = await resp.text()
            wait = _parse_429_wait(body)
            raise RateLimitError(wait, f"Grok 429: {body[:200]}")
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(f"Grok Foundry {resp.status}: {body[:300]}")
        data = await resp.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f">>> [GROK] Complete done in {time.time() - t0:.1f}s ({len(text)} chars)")
        return text


# --- Azure OpenAI (fast fallback — uses existing Azure resource) ---

_azure_session: Optional[aiohttp.ClientSession] = None


def _get_azure_session() -> aiohttp.ClientSession:
    global _azure_session
    if _azure_session is None or _azure_session.closed:
        timeout = aiohttp.ClientTimeout(total=30, sock_read=25)
        connector = aiohttp.TCPConnector(limit=20, keepalive_timeout=120)
        _azure_session = aiohttp.ClientSession(timeout=timeout, connector=connector)
    return _azure_session


def _azure_chat_url() -> str:
    endpoint = _AZURE_ENDPOINT.rstrip("/")
    if not endpoint.startswith("https://"):
        endpoint = f"https://{endpoint}"
    return f"{endpoint}/openai/deployments/{_AZURE_CHAT_DEPLOYMENT}/chat/completions?api-version=2024-06-01"


async def _stream_azure(
    messages: List[Dict], temperature: float, max_tokens: int
) -> AsyncIterator[str]:
    """Stream from Azure OpenAI Chat Completions — fast fallback."""
    url = _azure_chat_url()
    headers = {
        "api-key": _AZURE_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    t0 = time.time()
    session = _get_azure_session()
    async with session.post(url, json=payload, headers=headers) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(f"Azure OpenAI {resp.status}: {body[:300]}")
        first_token_time = None
        token_count = 0
        async for line in resp.content:
            decoded = line.decode("utf-8", errors="ignore").strip()
            if not decoded.startswith("data: "):
                continue
            data_str = decoded[6:]
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
                choices = chunk.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {}).get("content") or ""
                if delta:
                    if first_token_time is None:
                        first_token_time = time.time()
                        print(f">>> [AZURE] First token in {first_token_time - t0:.1f}s")
                    token_count += 1
                    yield delta
            except (json.JSONDecodeError, IndexError, KeyError):
                continue
        elapsed = time.time() - t0
        print(f">>> [AZURE] Stream complete: {token_count} chunks in {elapsed:.1f}s (deployment={_AZURE_CHAT_DEPLOYMENT})")


async def _complete_azure(
    messages: List[Dict], temperature: float, max_tokens: int
) -> str:
    """Non-streaming Azure OpenAI for fallback."""
    url = _azure_chat_url()
    headers = {
        "api-key": _AZURE_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    t0 = time.time()
    session = _get_azure_session()
    async with session.post(url, json=payload, headers=headers) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(f"Azure OpenAI {resp.status}: {body[:300]}")
        data = await resp.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f">>> [AZURE] Complete done in {time.time() - t0:.1f}s ({len(text)} chars)")
        return text


# --- Workers AI (LOCKED/PROMOTED — zero cost) ---

async def _stream_workers_ai(
    messages: List[Dict], temperature: float, max_tokens: int
) -> AsyncIterator[str]:
    """Stream from Cloudflare Workers AI — free tier for routine queries."""
    headers = {}
    if _WORKERS_AI_TOKEN:
        headers["Authorization"] = f"Bearer {_WORKERS_AI_TOKEN}"
    headers["Content-Type"] = "application/json"
    payload = {
        "model": _WORKERS_AI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    t0 = time.time()
    session = _get_workers_session()
    async with session.post(_WORKERS_AI_URL, json=payload, headers=headers) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(f"Workers AI {resp.status}: {body[:300]}")
        first_token_time = None
        token_count = 0
        async for line in resp.content:
            decoded = line.decode("utf-8", errors="ignore").strip()
            if not decoded.startswith("data: "):
                if decoded.startswith("{"):
                    try:
                        result = json.loads(decoded)
                        text = result.get("result", {}).get("response", "")
                        if text:
                            yield text
                            token_count += 1
                    except (json.JSONDecodeError, KeyError):
                        pass
                continue
            data_str = decoded[6:]
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
                delta = chunk.get("response", "")
                if not isinstance(delta, str):
                    delta = ""
                if not delta and "choices" in chunk:
                    delta = chunk["choices"][0].get("delta", {}).get("content", "")
                if delta:
                    if first_token_time is None:
                        first_token_time = time.time()
                        print(f">>> [WORKERS] First token in {first_token_time - t0:.1f}s")
                    token_count += 1
                    yield delta
            except (json.JSONDecodeError, IndexError, KeyError):
                continue
        elapsed = time.time() - t0
        print(f">>> [WORKERS] Stream complete: {token_count} chunks in {elapsed:.1f}s")


async def _complete_workers_ai(
    messages: List[Dict], temperature: float, max_tokens: int
) -> str:
    """Non-streaming Workers AI for routine queries."""
    headers = {}
    if _WORKERS_AI_TOKEN:
        headers["Authorization"] = f"Bearer {_WORKERS_AI_TOKEN}"
    headers["Content-Type"] = "application/json"
    payload = {
        "model": _WORKERS_AI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    session = _get_workers_session()
    async with session.post(_WORKERS_AI_URL, json=payload, headers=headers) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(f"Workers AI {resp.status}: {body[:300]}")
        data = await resp.json()
        result = data.get("result", data)
        text = result.get("response", "")
        if not text and "choices" in result:
            text = result["choices"][0]["message"]["content"]
        return text.strip()
