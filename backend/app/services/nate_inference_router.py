"""
Nate Inference Router — ODPE-aware tiered routing.

6 providers, ODPE signal determines priority:
  1. Workers AI (Cloudflare, free) — LOCKED/PROMOTED routine queries
  2. Grok 4.1 Fast (Azure Foundry) — TENSION + DEEP_TENSION clinical depth
  3. Sovereign (Hetzner CAX41 Ollama) — batch processing
  4. Home GPU (local 70B) — clinical depth when available
  5. DigitalOcean (overflow node) — overflow
  6. Azure OpenAI — emergency fallback only (if Grok is down)

Provider-agnostic: any OpenAI-compatible API endpoint works as sovereign.
"""

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

TIER_CLINICAL = "clinical"
TIER_CREATIVE = "creative"
TIER_ANALYTICAL = "analytical"
TIER_UTILITY = "utility"
TIER_REALTIME = "realtime"
TIER_CODING = "coding"

_TIER_PRIORITY = {
    TIER_CLINICAL: ["grok", "home_gpu", "sovereign", "azure"],
    TIER_CREATIVE: ["workers_ai", "grok", "sovereign", "azure"],
    TIER_ANALYTICAL: ["workers_ai", "grok", "sovereign", "azure"],
    TIER_UTILITY: ["workers_ai", "grok", "azure"],
    TIER_REALTIME: ["azure"],
    TIER_CODING: ["sovereign", "grok", "workers_ai", "azure"],
}

# Domain -> temperature defaults
DOMAIN_TEMPERATURES = {
    "clinical": 0.3,
    "defense": 0.3,
    "coding": 0.3,
    "research": 0.6,
    "marketing": 0.8,
    "culture": 0.9,
    "coaching": 0.5,
    "general": 0.6,
}

_SOVEREIGN_URL = os.getenv("SOVEREIGN_INFERENCE_URL", "")
_SOVEREIGN_MODEL = os.getenv("SOVEREIGN_MODEL", "llama3.1:8b-instruct-q4_K_M")
_SOVEREIGN_MODEL_FAST = os.getenv("SOVEREIGN_MODEL_FAST", "llama3.1:8b-instruct-q4_K_M")
_SOVEREIGN_MODEL_MID = os.getenv("SOVEREIGN_MODEL_MID", "qwen2.5:14b-instruct-q4_K_M")
_SOVEREIGN_MODEL_DEEP = os.getenv("SOVEREIGN_MODEL_DEEP", "qwen2.5:32b-instruct-q4_K_M")
_WORKERS_AI_URL = os.getenv("WORKERS_AI_URL", "")
_WORKERS_AI_TOKEN = os.getenv("WORKERS_AI_TOKEN", "")
_WORKERS_AI_MODEL = os.getenv("WORKERS_AI_MODEL", "@cf/meta/llama-3.1-8b-instruct")

_HOME_GPU_URL = os.getenv("HOME_GPU_URL", "")
_HOME_GPU_MODEL = os.getenv("HOME_GPU_MODEL", "")
_DIGITAL_OCEAN_URL = os.getenv("DIGITAL_OCEAN_INFERENCE_URL", "")
_DIGITAL_OCEAN_MODEL = os.getenv("DIGITAL_OCEAN_MODEL", "llama3.1:8b-instruct-q4_K_M")

_GROK_URL = os.getenv("NATE_CHAT_URL", "")
_GROK_KEY = os.getenv("NATE_CHAT_KEY", os.getenv("AZURE_API_KEY", ""))
_GROK_MODEL = os.getenv("NATE_CHAT_MODEL", "grok-4-1-fast-non-reasoning")

_AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
_AZURE_KEY = os.getenv("AZURE_API_KEY", "")
_AZURE_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")

_stats = {
    "sovereign": {"calls": 0, "errors": 0, "total_ms": 0},
    "workers_ai": {"calls": 0, "errors": 0, "total_ms": 0},
    "grok": {"calls": 0, "errors": 0, "total_ms": 0},
    "azure": {"calls": 0, "errors": 0, "total_ms": 0},
    "home_gpu": {"calls": 0, "errors": 0, "total_ms": 0},
    "digitalocean": {"calls": 0, "errors": 0, "total_ms": 0},
}


class NateInferenceRouter:
    """Routes inference requests to the best available provider."""

    def __init__(self, app_state=None):
        self._app_state = app_state
        self._sovereign_healthy = bool(_SOVEREIGN_URL)
        self._workers_healthy = bool(_WORKERS_AI_URL)
        self._grok_healthy = bool(_GROK_URL and _GROK_KEY)
        self._azure_healthy = bool(_AZURE_ENDPOINT and _AZURE_KEY)
        self._home_gpu_healthy = bool(_HOME_GPU_URL)
        self._digitalocean_healthy = bool(_DIGITAL_OCEAN_URL)
        self._last_health_check = 0.0

    _PROVIDER_HOSTS = {
        "sovereign": _SOVEREIGN_URL,
        "workers_ai": _WORKERS_AI_URL,
        "grok": _GROK_URL,
        "azure": f"https://{_AZURE_ENDPOINT}" if _AZURE_ENDPOINT else "",
        "home_gpu": _HOME_GPU_URL,
        "digitalocean": _DIGITAL_OCEAN_URL,
    }

    def _sase_validate_outbound(self, provider: str):
        """SASE outbound validation before calling any external provider."""
        if not self._app_state:
            return
        hive_v4 = getattr(self._app_state, "hive_v4", {})
        sase = hive_v4.get("sase_controller") if isinstance(hive_v4, dict) else None
        if not sase:
            return
        url = self._PROVIDER_HOSTS.get(provider, "")
        if not url:
            return
        try:
            from urllib.parse import urlparse
            host = urlparse(url).hostname or ""
            if host:
                verdict = sase.validate_outbound(host, purpose=f"inference:{provider}")
                if not verdict.allowed:
                    logger.warning("SASE blocked outbound to %s (%s): %s", host, provider, verdict.reason)
                    raise RuntimeError(f"SASE outbound blocked: {host}")
        except RuntimeError:
            raise
        except Exception as e:
            logger.warning("SASE outbound check failed (allowing): %s", e)

    def _resolve_sovereign_model(self, odpe_signal: Optional[str], allow_deep: bool = False) -> str:
        """ODPE-driven three-tier model selection: 8B (fast) / 14B (mid) / 32B (deep)."""
        if odpe_signal in ("LOCKED", "PROMOTED"):
            return _SOVEREIGN_MODEL_FAST
        elif odpe_signal == "DEEP_TENSION" and allow_deep:
            return _SOVEREIGN_MODEL_DEEP
        elif odpe_signal in ("TENSION", "LIMINAL_RESOLVE", "PROVISIONAL", "DEEP_TENSION"):
            return _SOVEREIGN_MODEL_MID
        return _SOVEREIGN_MODEL_FAST

    async def generate(
        self,
        prompt: str,
        system: str = "",
        tier: str = TIER_ANALYTICAL,
        temperature: Optional[float] = None,
        max_tokens: int = 1000,
        domain: Optional[str] = None,
        odpe_signal: Optional[str] = None,
        allow_deep: bool = False,
        images: Optional[List[str]] = None,  # QUANTUM-CRYSTAL-ARCH — multimodal (Azure)
    ) -> Dict[str, Any]:
        """
        Route a generation request to the best available provider.
        Returns {"text": str, "provider": str, "tokens_used": int, "latency_ms": int}

        ODPE signal drives tier selection:
          LOCKED → TIER_UTILITY → Workers AI (free)
          PROMOTED → domain's natural tier → Workers AI (free)
          TENSION → TIER_CLINICAL → Grok 4.1 Fast via Foundry
          DEEP_TENSION → TIER_CLINICAL → Grok 4.1 Fast via Foundry
          NOISE → skip LLM call entirely
        """
        if odpe_signal == "NOISE" and not images:
            return {
                "text": "",
                "provider": "odpe_skip",
                "tokens_used": 0,
                "latency_ms": 0,
            }

        if odpe_signal == "LOCKED":
            tier = TIER_UTILITY
        elif odpe_signal in ("TENSION", "DEEP_TENSION", "LIMINAL_RESOLVE"):
            if domain == "coding":
                tier = TIER_CODING
            else:
                tier = TIER_CLINICAL

        sovereign_model = self._resolve_sovereign_model(odpe_signal, allow_deep)

        if temperature is None:
            temperature = DOMAIN_TEMPERATURES.get(domain or "general", 0.6)

        # Vision requires Azure multimodal; force azure when images present
        providers = ["azure"] if images else _TIER_PRIORITY.get(tier, ["azure"])

        for provider in providers:
            if provider == "sovereign" and not self._sovereign_healthy:
                continue
            if provider == "workers_ai" and not self._workers_healthy:
                continue
            if provider == "grok" and not self._grok_healthy:
                continue
            if provider == "azure" and not self._azure_healthy:
                continue
            if provider == "home_gpu" and not self._home_gpu_healthy:
                continue
            if provider == "digitalocean" and not self._digitalocean_healthy:
                continue

            try:
                start = time.time()
                result = await self._call_provider(
                    provider, prompt, system, temperature, max_tokens,
                    sovereign_model=sovereign_model,
                    images=images,
                )
                latency = int((time.time() - start) * 1000)

                _stats[provider]["calls"] += 1
                _stats[provider]["total_ms"] += latency

                result["provider"] = provider
                result["latency_ms"] = latency
                if provider == "sovereign":
                    result["model"] = sovereign_model
                return result

            except Exception as e:
                _stats[provider]["errors"] += 1
                logger.warning("Inference %s failed: %s", provider, e)
                continue

        # QUANTUM-CRYSTAL-ARCH — vision-only Azure failed: retry text path
        if images:
            logger.warning("Inference vision path failed — retrying text-only")
            return await self.generate(
                prompt=prompt,
                system=system,
                tier=tier,
                temperature=temperature,
                max_tokens=max_tokens,
                domain=domain,
                odpe_signal=odpe_signal,
                allow_deep=allow_deep,
                images=None,
            )

        return {
            "text": "I'm temporarily unable to process this request.",
            "provider": "none",
            "tokens_used": 0,
            "latency_ms": 0,
            "error": "All providers unavailable",
        }

    async def _call_provider(
        self,
        provider: str,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
        sovereign_model: str = "",
        images: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        self._sase_validate_outbound(provider)

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        # QUANTUM-CRYSTAL-ARCH — multimodal user content when images provided
        if images:
            content: List[Any] = []
            for b64 in images[:4]:
                if not b64:
                    continue
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                })
            content.append({"type": "text", "text": prompt})
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": prompt})

        if provider == "sovereign":
            return await self._call_sovereign(
                messages, temperature, max_tokens,
                model=sovereign_model or _SOVEREIGN_MODEL_FAST,
            )
        elif provider == "home_gpu":
            return await self._call_home_gpu(messages, temperature, max_tokens)
        elif provider == "digitalocean":
            return await self._call_digitalocean(messages, temperature, max_tokens)
        elif provider == "workers_ai":
            return await self._call_workers_ai(messages, temperature, max_tokens)
        elif provider == "grok":
            return await self._call_grok(messages, temperature, max_tokens)
        else:
            return await self._call_azure(messages, temperature, max_tokens)

    _SOVEREIGN_SEMAPHORE = asyncio.Semaphore(4)

    async def _call_sovereign(self, messages, temperature, max_tokens, model: str = "") -> Dict:
        selected_model = model or _SOVEREIGN_MODEL_FAST
        timeout_secs = 30 if selected_model == _SOVEREIGN_MODEL_FAST else 60
        if selected_model == _SOVEREIGN_MODEL_DEEP:
            timeout_secs = 120

        url = f"{_SOVEREIGN_URL}/v1/chat/completions"
        async with self._SOVEREIGN_SEMAPHORE, aiohttp.ClientSession() as sess:
            async with sess.post(url, json={
                "model": selected_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            }, timeout=aiohttp.ClientTimeout(total=timeout_secs)) as resp:
                if resp.status != 200:
                    self._sovereign_healthy = False
                    raise RuntimeError(f"Sovereign returned {resp.status}")
                data = await resp.json()
                choice = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                return {
                    "text": choice.strip(),
                    "tokens_used": usage.get("total_tokens", 0),
                }

    async def _call_home_gpu(self, messages, temperature, max_tokens) -> Dict:
        """Home GPU — local 70B model for clinical depth (Ollama-compatible)."""
        model = _HOME_GPU_MODEL or "llama3.1:70b-instruct-q4_K_M"
        url = f"{_HOME_GPU_URL}/v1/chat/completions"
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            }, timeout=aiohttp.ClientTimeout(total=180)) as resp:
                if resp.status != 200:
                    self._home_gpu_healthy = False
                    raise RuntimeError(f"Home GPU returned {resp.status}")
                data = await resp.json()
                choice = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                return {
                    "text": choice.strip(),
                    "tokens_used": usage.get("total_tokens", 0),
                }

    async def _call_digitalocean(self, messages, temperature, max_tokens) -> Dict:
        """DigitalOcean overflow node — 8B model (Ollama-compatible)."""
        url = f"{_DIGITAL_OCEAN_URL}/v1/chat/completions"
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json={
                "model": _DIGITAL_OCEAN_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            }, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    self._digitalocean_healthy = False
                    raise RuntimeError(f"DigitalOcean returned {resp.status}")
                data = await resp.json()
                choice = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                return {
                    "text": choice.strip(),
                    "tokens_used": usage.get("total_tokens", 0),
                }

    async def _call_workers_ai(self, messages, temperature, max_tokens) -> Dict:
        url = f"{_WORKERS_AI_URL}"
        headers = {}
        if _WORKERS_AI_TOKEN:
            headers["Authorization"] = f"Bearer {_WORKERS_AI_TOKEN}"

        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json={
                "model": _WORKERS_AI_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    self._workers_healthy = False
                    raise RuntimeError(f"Workers AI returned {resp.status}")
                data = await resp.json()
                result_data = data.get("result", data)
                text = result_data.get("response", "")
                if not text and "choices" in result_data:
                    text = result_data["choices"][0]["message"]["content"]
                return {
                    "text": text.strip(),
                    "tokens_used": result_data.get("usage", {}).get("total_tokens", 0),
                }

    async def _call_grok(self, messages, temperature, max_tokens) -> Dict:
        """Grok 4.1 Fast via Azure AI Foundry — TENSION/DEEP_TENSION queries."""
        headers = {
            "api-key": _GROK_KEY,
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession() as sess:
            async with sess.post(_GROK_URL, json={
                "model": _GROK_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_completion_tokens": max_tokens,
                "stream": False,
            }, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    self._grok_healthy = False
                    raise RuntimeError(f"Grok Foundry returned {resp.status}")
                data = await resp.json()
                choice = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                return {
                    "text": choice.strip(),
                    "tokens_used": usage.get("total_tokens", 0),
                }

    async def _call_azure(self, messages, temperature, max_tokens) -> Dict:
        url = (
            f"https://{_AZURE_ENDPOINT}/openai/deployments/"
            f"{_AZURE_DEPLOYMENT}/chat/completions?api-version=2024-06-01"
        )
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json={
                "messages": messages,
                "temperature": temperature,
                "max_completion_tokens": max_tokens,
            }, headers={"api-key": _AZURE_KEY},
                timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Azure returned {resp.status}")
                data = await resp.json()
                choice = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                return {
                    "text": choice.strip(),
                    "tokens_used": usage.get("total_tokens", 0),
                }

    async def health_check(self) -> Dict[str, Any]:
        """Quick availability probe for all providers."""
        now = time.time()
        if now - self._last_health_check < 300:
            return self.get_status()

        self._last_health_check = now

        async def _probe_ollama(url: str) -> bool:
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(
                        f"{url}/v1/models",
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        return resp.status == 200
            except Exception:
                return False

        if _SOVEREIGN_URL:
            self._sovereign_healthy = await _probe_ollama(_SOVEREIGN_URL)

        if _HOME_GPU_URL:
            self._home_gpu_healthy = await _probe_ollama(_HOME_GPU_URL)

        if _DIGITAL_OCEAN_URL:
            self._digitalocean_healthy = await _probe_ollama(_DIGITAL_OCEAN_URL)

        self._workers_healthy = bool(_WORKERS_AI_URL) and _stats["workers_ai"]["errors"] < _stats["workers_ai"]["calls"] + 1

        self._grok_healthy = bool(_GROK_URL and _GROK_KEY) and _stats["grok"]["errors"] < _stats["grok"]["calls"] + 1

        self._azure_healthy = bool(_AZURE_ENDPOINT and _AZURE_KEY)

        return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        total_calls = sum(s["calls"] for s in _stats.values())
        non_azure = sum(
            _stats[p]["calls"] for p in ("sovereign", "workers_ai", "grok",
                                          "home_gpu", "digitalocean")
        )
        return {
            "workers_ai": {
                "healthy": self._workers_healthy,
                "configured": bool(_WORKERS_AI_URL),
                **_stats["workers_ai"],
                "pct": round(_stats["workers_ai"]["calls"] / max(total_calls, 1) * 100, 1),
            },
            "grok": {
                "healthy": self._grok_healthy,
                "configured": bool(_GROK_URL and _GROK_KEY),
                **_stats["grok"],
                "pct": round(_stats["grok"]["calls"] / max(total_calls, 1) * 100, 1),
            },
            "sovereign": {
                "healthy": self._sovereign_healthy,
                "configured": bool(_SOVEREIGN_URL),
                **_stats["sovereign"],
                "pct": round(_stats["sovereign"]["calls"] / max(total_calls, 1) * 100, 1),
            },
            "home_gpu": {
                "healthy": self._home_gpu_healthy,
                "configured": bool(_HOME_GPU_URL),
                **_stats["home_gpu"],
                "pct": round(_stats["home_gpu"]["calls"] / max(total_calls, 1) * 100, 1),
            },
            "digitalocean": {
                "healthy": self._digitalocean_healthy,
                "configured": bool(_DIGITAL_OCEAN_URL),
                **_stats["digitalocean"],
                "pct": round(_stats["digitalocean"]["calls"] / max(total_calls, 1) * 100, 1),
            },
            "azure": {
                "healthy": self._azure_healthy,
                "configured": bool(_AZURE_ENDPOINT),
                **_stats["azure"],
                "pct": round(_stats["azure"]["calls"] / max(total_calls, 1) * 100, 1),
            },
            "total_calls": total_calls,
            "independence_pct": round(
                non_azure / max(total_calls, 1) * 100, 1
            ),
        }
