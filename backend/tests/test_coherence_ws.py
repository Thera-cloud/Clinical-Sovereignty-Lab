"""End-to-end WebSocket test: auth → get_coherence_report → verify response.
Mimics exact Flutter NevedalReportsScreen flow."""
import asyncio
import json
import os
import sys

async def test():
    import websockets
    import redis as _redis

    pw = os.environ.get("REDIS_PASSWORD", "")
    r = _redis.Redis(host="redis", port=6379, password=pw, decode_responses=True)

    token = hw = None
    env = os.environ.get("ENVIRONMENT", "development")
    prefix = f"nate:{env}:auth:"
    for key in r.scan_iter(f"{prefix}*", count=200):
        val = r.get(key)
        if val and "CLIENT_001" in val:
            profile = json.loads(val)
            hw = profile["hardware_id"]
            token = key.replace(prefix, "")
            break

    if not token:
        print("NO TOKEN FOUND")
        sys.exit(1)

    print(f"Token: {token[:8]}... HW: {hw}")

    async with websockets.connect("ws://bridge:8765") as ws:
        msg = await asyncio.wait_for(ws.recv(), timeout=5)
        d = json.loads(msg)
        tp = d.get("type")
        st = d.get("status")
        print(f"1. type={tp} status={st}")

        await ws.send(json.dumps({"type": "auth", "hardware_id": hw, "token": token}))

        auth_ok = False
        for _ in range(15):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                d2 = json.loads(raw)
                t = d2.get("type", "")
                if t in ("auth_success", "login_success"):
                    print(f"2. AUTH OK (type={t})")
                    auth_ok = True
                elif t == "auth_failed":
                    reason = d2.get("message", "?")
                    print(f"2. AUTH FAILED: {reason}")
                    sys.exit(1)
                elif t == "metrics_data":
                    m = d2.get("metrics", {})
                    cemo = m.get("C_emo")
                    gap = m.get("GAP")
                    sess = m.get("session_count")
                    print(f"3. metrics_data: C_emo={cemo}, GAP={gap}, sessions={sess}")
                    if auth_ok:
                        break
                elif t == "metrics_update":
                    m = d2.get("metrics", {})
                    cemo = m.get("C_emo")
                    print(f"3. metrics_update: C_emo={cemo}")
                    if auth_ok:
                        break
                else:
                    print(f"   (other: {t})")
            except asyncio.TimeoutError:
                break

        if not auth_ok:
            print("AUTH NEVER SUCCEEDED")
            sys.exit(1)

        await ws.send(json.dumps({"type": "get_coherence_report"}))

        for _ in range(10):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                d3 = json.loads(raw)
                t3 = d3.get("type", "")
                if t3 == "coherence_report":
                    cur = d3.get("current", {})
                    hist = d3.get("history", [])
                    cee = d3.get("cee_experiences", [])
                    trends = d3.get("trends", {})
                    cvals = trends.get("C_emo", {}).get("values", [])
                    mood_h = d3.get("mood_history", [])
                    print("4. COHERENCE REPORT OK")
                    c = cur.get("C_emo")
                    g = cur.get("GAP")
                    q = cur.get("Quantum")
                    s = cur.get("session_count")
                    print(f"   C_emo={c}, GAP={g}, Quantum={q}")
                    print(f"   Sessions={s}, History={len(hist)}, CEE_exp={len(cee)}, Trend_pts={len(cvals)}, Moods={len(mood_h)}")
                    sys.exit(0)
                elif t3 == "coherence_report_error":
                    err = d3.get("error", "?")
                    print(f"4. COHERENCE ERROR: {err}")
                    sys.exit(1)
                else:
                    print(f"   (other: {t3})")
            except asyncio.TimeoutError:
                print("4. TIMEOUT waiting for coherence_report")
                sys.exit(1)

        print("4. NO coherence_report received after 10 messages")
        sys.exit(1)

asyncio.run(test())
