#!/usr/bin/env python3
"""Probe Cloudflare Workers AI RPM ceiling (429 onset)."""
import asyncio
import os
import time
from collections import Counter

import aiohttp

ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID") or os.environ.get("CLOUDFLARE_ACCOUNT_ID") or os.environ.get("R2_ACCOUNT_ID")
API_TOKEN = os.environ.get("CF_API_TOKEN") or os.environ.get("WORKERS_AI_TOKEN")
MODEL = os.environ.get("WORKERS_AI_RPM_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")
TARGET_RPM = int(os.environ.get("TARGET_RPM", "450"))
DURATION_S = int(os.environ.get("DURATION_S", "60"))

if not ACCOUNT_ID or not API_TOKEN:
    raise SystemExit(f"missing creds account={bool(ACCOUNT_ID)} token={bool(API_TOKEN)}")

URL = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/{MODEL}"
HEADERS = {"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"}
if "bge" in MODEL.lower():
    PAYLOAD = {"text": "hi"}
else:
    PAYLOAD = {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
interval = 60.0 / TARGET_RPM
results: Counter = Counter()
rate_limited_times: list[float] = []


async def fire(session: aiohttp.ClientSession, start: float) -> None:
    try:
        async with session.post(URL, headers=HEADERS, json=PAYLOAD) as r:
            results[r.status] += 1
            if r.status == 429:
                rate_limited_times.append(round(time.time() - start, 1))
    except Exception as e:
        results[f"error:{type(e).__name__}"] += 1


async def main() -> None:
    start = time.time()
    tasks: list[asyncio.Task] = []
    async with aiohttp.ClientSession() as session:
        while time.time() - start < DURATION_S:
            tasks.append(asyncio.create_task(fire(session, start)))
            await asyncio.sleep(interval)
        await asyncio.gather(*tasks)

    elapsed = time.time() - start
    sent = sum(v for k, v in results.items() if not str(k).startswith("error:"))
    print(f"\n--- {MODEL} ---")
    print(f"target launch rate: {TARGET_RPM} RPM for {DURATION_S}s")
    print(f"sent {sent} requests in {elapsed:.1f}s  (~{sent / elapsed * 60:.0f} RPM launch rate)")
    for status, count in sorted(results.items(), key=str):
        print(f"  {status}: {count}")
    print(f"  429s: {results[429]}")
    ok = results[200] + results.get(201, 0)
    print(f"  successful (2xx): {ok}")
    if rate_limited_times:
        print(f"  first 429 at +{rate_limited_times[0]}s")
        print(f"  last 429 at +{rate_limited_times[-1]}s")
        sustained_ok_rpm = (ok / elapsed) * 60
        print(f"  sustained success rate: ~{sustained_ok_rpm:.0f} RPM")
    else:
        print("  no 429 rate limits observed — limit is above tested launch rate")


if __name__ == "__main__":
    asyncio.run(main())
