#!/usr/bin/env python3
"""Single-user WebSocket diagnostic: prints every message received."""
import asyncio, json, time, sys

async def probe():
    try:
        import aiohttp
    except ImportError:
        print("pip install aiohttp"); return

    target = "wss://api.sovereignsanctuary.net/ws"
    username = "loadtest_001"
    password = "LoadTest2026!Nate"

    async with aiohttp.ClientSession() as s:
        print(f"[*] Connecting to {target}")
        ws = await s.ws_connect(target, heartbeat=30, receive_timeout=180)
        print(f"[+] Connected")

        # Expect {type: connected}
        msg = await asyncio.wait_for(ws.receive(), timeout=10)
        data = json.loads(msg.data)
        print(f"[<] {data.get('type')}: {json.dumps(data)[:200]}")

        # Login
        print(f"[>] login_request for {username}")
        await ws.send_str(json.dumps({
            "type": "login_request",
            "username": username,
            "password": password,
            "expected_role": "CLIENT",
        }))

        # Drain until login_success (or 15s)
        deadline = time.monotonic() + 15
        logged_in = False
        while time.monotonic() < deadline:
            msg = await asyncio.wait_for(ws.receive(), timeout=10)
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                mt = data.get("type", "?")
                print(f"[<] {mt}: {json.dumps(data)[:300]}")
                if mt == "login_success":
                    logged_in = True
                    break
            elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                print(f"[!] WS closed/error during login: {msg}")
                return

        if not logged_in:
            print("[!] Never got login_success")
            await ws.close()
            return

        # Send nate_query
        query = "I feel anxious about an upcoming presentation at work."
        print(f"[>] nate_query: {query[:60]}")
        await ws.send_str(json.dumps({
            "type": "nate_query",
            "text": query,
            "nate_query": query,
        }))

        # Print EVERY message for 60 seconds
        t0 = time.monotonic()
        msg_count = 0
        while time.monotonic() - t0 < 60:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=10)
            except asyncio.TimeoutError:
                print(f"[.] 10s silence (total elapsed: {time.monotonic()-t0:.1f}s, msgs: {msg_count})")
                continue
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                mt = data.get("type", "?")
                text = data.get("text", data.get("response", data.get("message", "")))
                msg_count += 1
                elapsed = time.monotonic() - t0
                preview = (text[:120] + "...") if len(text) > 120 else text
                print(f"[<] #{msg_count} @{elapsed:.2f}s type={mt} len={len(text)} text={preview!r}")
            elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                print(f"[!] WS closed/error: {msg}")
                break
            else:
                print(f"[?] Non-text msg type={msg.type}")

        print(f"\n[=] Done. {msg_count} messages received in {time.monotonic()-t0:.1f}s")
        await ws.close()

asyncio.run(probe())
