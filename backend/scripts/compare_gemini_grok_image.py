#!/usr/bin/env python3
"""One-off: same prompt → Grok Imagine vs Gemini image. No production wiring."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

DEFAULT_PROMPT = (
    "Misty threshold pathway at dawn, painterly therapeutic fantasy illustration, "
    "muted warm palette, a single iridescent dragon scale on ancient stone, "
    "hopeful atmosphere, no text, no words, no lettering, no writing on image"
)

GROK_URL = "https://api.x.ai/v1/images/generations"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")


async def grok_bytes(session: aiohttp.ClientSession, prompt: str) -> tuple[bytes, str]:
    key = os.getenv("XAI_SSE_KEY", "").strip() or os.getenv("XAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("XAI_SSE_KEY / XAI_API_KEY not set")
    payload = {"model": "grok-imagine-image", "prompt": prompt, "n": 1}
    async with session.post(
        GROK_URL, json=payload, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    ) as resp:
        body = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"Grok {resp.status}: {body[:400]}")
        data = json.loads(body)
    url = (data.get("data") or [{}])[0].get("url")
    if not url:
        raise RuntimeError("Grok returned no image URL")
    async with session.get(url) as dl:
        if dl.status != 200:
            raise RuntimeError(f"Grok download {dl.status}")
        return await dl.read(), "grok-imagine-image"


def _extract_gemini_image(data: dict) -> bytes:
    """Parse Gemini interactions response (steps[].model_output.content[].image)."""
    for step in data.get("steps") or []:
        if step.get("type") != "model_output":
            continue
        for item in step.get("content") or []:
            if item.get("type") == "image":
                b64 = item.get("data")
                if b64:
                    return base64.b64decode(b64)
    if isinstance(data.get("output"), list):
        for item in data["output"]:
            if item.get("type") == "image":
                b64 = item.get("data") or item.get("image", {}).get("data")
                if b64:
                    return base64.b64decode(b64)
    for key in ("candidates", "outputs", "response"):
        block = data.get(key)
        if isinstance(block, list):
            for item in block:
                if isinstance(item, dict) and item.get("type") == "image":
                    b64 = item.get("data") or item.get("image", {}).get("data")
                    if b64:
                        return base64.b64decode(b64)
    # fallback: walk for inlineData / base64
    raw = json.dumps(data)
    if "inlineData" in raw or "inline_data" in raw:
        def walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in ("inlineData", "inline_data") and isinstance(v, dict):
                        b64 = v.get("data")
                        if b64:
                            return base64.b64decode(b64)
                    found = walk(v)
                    if found:
                        return found
            elif isinstance(obj, list):
                for x in obj:
                    found = walk(x)
                    if found:
                        return found
            return None
        img = walk(data)
        if img:
            return img
    raise RuntimeError(f"Gemini response had no image payload: {raw[:500]}")


async def gemini_bytes(session: aiohttp.ClientSession, prompt: str) -> tuple[bytes, str]:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    payload = {
        "model": GEMINI_MODEL,
        "input": [{"type": "text", "text": prompt}],
        "response_format": {"type": "image", "mime_type": "image/jpeg", "aspect_ratio": "1:1"},
    }
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    async with session.post(GEMINI_URL, json=payload, headers=headers) as resp:
        body = await resp.text()
        if resp.status != 200:
            raise RuntimeError(f"Gemini {resp.status}: {body[:400]}")
        data = json.loads(body)

    # Completed interactions may return steps inline or require fetch by id
    if not _has_image_steps(data) and data.get("id"):
        fetch_url = f"{GEMINI_URL}/{data['id']}"
        async with session.get(fetch_url, headers=headers) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"Gemini fetch {resp.status}: {body[:400]}")
            data = json.loads(body)

    return _extract_gemini_image(data), GEMINI_MODEL


def _has_image_steps(data: dict) -> bool:
    for step in data.get("steps") or []:
        if step.get("type") != "model_output":
            continue
        for item in step.get("content") or []:
            if item.get("type") == "image" and item.get("data"):
                return True
    return False


async def main() -> int:
    prompt = " ".join(sys.argv[1:]).strip() or DEFAULT_PROMPT
    out_dir = Path(os.getenv("COMPARE_OUT_DIR", "/tmp/sse_image_compare"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    meta = {"prompt": prompt, "stamp": stamp, "results": {}}

    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for name, coro in (("grok", grok_bytes(session, prompt)), ("gemini", gemini_bytes(session, prompt))):
            try:
                img, model = await coro
                path = out_dir / f"{stamp}_{name}.png"
                path.write_bytes(img)
                meta["results"][name] = {
                    "ok": True,
                    "model": model,
                    "path": str(path),
                    "bytes": len(img),
                }
                print(f"OK {name}: {path} ({len(img)} bytes, model={model})")
            except Exception as e:
                meta["results"][name] = {"ok": False, "error": str(e)[:500]}
                print(f"FAIL {name}: {e}", file=sys.stderr)

    meta_path = out_dir / f"{stamp}_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"META: {meta_path}")
    return 0 if all(r.get("ok") for r in meta["results"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
