"""SSE Infrastructure — Replicate API client for LoRA training + Flux generation.

Available for future use. Not currently called by SSE delivery or group video
pipeline. All personalized content generation uses Grok Imagine with
archetype_ref_url (source_image_url) for character consistency.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_API_BASE = "https://api.replicate.com/v1"
_FLUX_MODEL = "black-forest-labs/flux-1.1-pro"
_LORA_TRAIN_MODEL = "ostris/flux-dev-lora-trainer"
_LORA_TRAIN_VERSION = "d995297071a44dcb72244e6c19462111649ec86a9646c96b64f20f894c8c2e94"


def _get_token() -> str:
    return os.getenv("REPLICATE_API_TOKEN", "").strip()


def _headers() -> dict[str, str]:
    token = _get_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "respond-async",
    }


def resolve_lora_destination(
    character_key: str | None = None,
    destination: str | None = None,
) -> str:
    """Resolve Replicate destination as owner/model-name (must exist, empty).

    Prefer explicit destination, else REPLICATE_LORA_DESTINATION, else
    REPLICATE_USERNAME + thera-{character_key}.
    """
    dest = (destination or os.getenv("REPLICATE_LORA_DESTINATION", "")).strip()
    if dest:
        return dest
    owner = os.getenv("REPLICATE_USERNAME", "").strip()
    if not owner:
        raise RuntimeError(
            "REPLICATE_USERNAME (or REPLICATE_LORA_DESTINATION) required — "
            "Replicate trainings need destination={owner}/{model}"
        )
    slug = (character_key or "character").strip().lower().replace("_", "-")
    slug = "".join(c for c in slug if c.isalnum() or c == "-") or "character"
    return f"{owner}/thera-{slug}"


async def ensure_destination_model(destination: str) -> None:
    """Create private empty destination model if missing (best-effort)."""
    if "/" not in destination:
        raise RuntimeError(f"Invalid Replicate destination: {destination}")
    owner, name = destination.split("/", 1)
    token = _get_token()
    if not token:
        raise RuntimeError("REPLICATE_API_TOKEN not set")

    get_url = f"{_API_BASE}/models/{owner}/{name}"
    create_url = f"{_API_BASE}/models"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as sess:
        async with sess.get(get_url, headers=_headers()) as resp:
            if resp.status == 200:
                return
        payload = {
            "owner": owner,
            "name": name,
            "description": f"SSE Thera-World LoRA destination ({name})",
            "visibility": "private",
            "hardware": "gpu-t4",
        }
        async with sess.post(create_url, json=payload, headers=_headers()) as resp:
            if resp.status in (200, 201):
                logger.info("[REPLICATE] Created destination model %s", destination)
                return
            body = await resp.text()
            # Already exists / race
            if resp.status in (409, 422) and "already" in body.lower():
                return
            raise RuntimeError(
                f"Replicate create model {resp.status}: {body[:300]}. "
                f"Create empty private model {destination} in the Replicate UI, then retry."
            )


async def train_lora(
    training_images_url: str,
    trigger_word: str = "THERACHAR",
    steps: int = 1000,
    lora_rank: int = 16,
    destination: str | None = None,
    character_key: str | None = None,
) -> dict:
    """Start a LoRA training job on Replicate.

    training_images_url: public URL to a .zip of training images.
    destination: owner/model — required by Replicate (empty model to push weights into).
    Returns dict with training id and status.
    """
    token = _get_token()
    if not token:
        raise RuntimeError("REPLICATE_API_TOKEN not set")

    dest = resolve_lora_destination(character_key=character_key, destination=destination)
    await ensure_destination_model(dest)

    url = f"{_API_BASE}/models/{_LORA_TRAIN_MODEL}/versions/{_LORA_TRAIN_VERSION}/trainings"
    payload = {
        "destination": dest,
        "input": {
            "input_images": training_images_url,
            "trigger_word": trigger_word,
            "steps": steps,
            "lora_rank": lora_rank,
            "learning_rate": 0.0004,
            "batch_size": 1,
            "resolution": "512,768,1024",
            "autocaption": True,
        },
    }

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as sess:
        async with sess.post(url, json=payload, headers=_headers()) as resp:
            if resp.status not in (200, 201, 202):
                body = await resp.text()
                raise RuntimeError(f"Replicate train {resp.status}: {body[:300]}")
            data = await resp.json()

    return {
        "training_id": data.get("id", ""),
        "status": data.get("status", "starting"),
        "destination": dest,
        "urls": data.get("urls", {}),
    }


async def poll_training(training_id: str) -> dict:
    """Poll a Replicate training job for status.

    Returns dict with status, logs snippet, and output (LoRA weights URL when done).
    """
    token = _get_token()
    if not token:
        raise RuntimeError("REPLICATE_API_TOKEN not set")

    url = f"{_API_BASE}/trainings/{training_id}"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as sess:
        async with sess.get(url, headers=_headers()) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Replicate poll {resp.status}: {body[:300]}")
            data = await resp.json()

    logs = data.get("logs", "")
    last_lines = "\n".join(logs.split("\n")[-5:]) if logs else ""

    return {
        "training_id": training_id,
        "status": data.get("status", "unknown"),
        "output": data.get("output"),
        "logs_tail": last_lines,
        "started_at": data.get("started_at"),
        "completed_at": data.get("completed_at"),
    }


async def generate_with_loras(
    prompt: str,
    lora_urls: list[str],
    lora_scales: list[float] | None = None,
    width: int = 1024,
    height: int = 576,
    num_outputs: int = 1,
) -> list[str]:
    """Generate images using Flux with LoRA weights applied.

    Returns list of generated image URLs.
    """
    token = _get_token()
    if not token:
        raise RuntimeError("REPLICATE_API_TOKEN not set")

    if not lora_scales:
        lora_scales = [0.8] * len(lora_urls)

    hf_loras = lora_urls[:4]
    scales = lora_scales[:4]

    url = f"{_API_BASE}/predictions"
    payload = {
        "version": "2389224e115448d9a77c07d7d45672b0f8e13b8f4c2710a1a857d5e7e2e649d3",
        "input": {
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_outputs": num_outputs,
            "guidance_scale": 3.5,
            "num_inference_steps": 28,
            "hf_loras": hf_loras,
            "lora_scales": scales,
        },
    }

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as sess:
        async with sess.post(url, json=payload, headers=_headers()) as resp:
            if resp.status not in (200, 201, 202):
                body = await resp.text()
                raise RuntimeError(f"Replicate predict {resp.status}: {body[:300]}")
            data = await resp.json()

        prediction_id = data.get("id", "")
        get_url = data.get("urls", {}).get("get", f"{_API_BASE}/predictions/{prediction_id}")

        for _ in range(60):
            import asyncio
            await asyncio.sleep(3)
            async with sess.get(get_url, headers=_headers()) as poll_resp:
                if poll_resp.status != 200:
                    continue
                poll_data = await poll_resp.json()
                status = poll_data.get("status", "")
                if status == "succeeded":
                    output = poll_data.get("output", [])
                    return output if isinstance(output, list) else [output]
                if status in ("failed", "canceled"):
                    raise RuntimeError(f"Replicate prediction {status}: {poll_data.get('error', '')}")

    raise RuntimeError("Replicate prediction timed out")
