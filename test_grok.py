import asyncio, json, os, websockets

async def test():
    key = os.getenv("XAI_API_KEY","").strip()
    url = "wss://api.x.ai/v1/realtime"
    ws = await asyncio.wait_for(
        websockets.connect(url, extra_headers={"Authorization": f"Bearer {key}"}, max_size=None),
        timeout=10
    )
    await ws.send(json.dumps({
        "type": "session.update",
        "session": {
            "instructions": "Say hello. Keep it very brief.",
            "voice": "Rex",
            "turn_detection": {
                "type": "server_vad",
                "silence_duration_ms": 700,
                "threshold": 0.5,
                "prefix_padding_ms": 300,
            },
            "audio": {
                "input": {"format": {"type": "audio/pcmu"}},
                "output": {"format": {"type": "audio/pcmu"}},
            },
        }
    }))
    for _ in range(5):
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        ev = json.loads(raw)
        et = ev.get("type","")
        print("setup:", et)
        if et == "session.updated":
            s = ev.get("session",{})
            print("  modalities:", s.get("modalities"))
            print("  voice:", s.get("voice"))
            break

    await ws.send(json.dumps({
        "type": "conversation.item.create",
        "item": {"type": "message", "role": "user",
                 "content": [{"type": "input_text", "text": "Hello, are you there?"}]}
    }))
    await ws.send(json.dumps({
        "type": "response.create",
        "response": {"modalities": ["audio"]}
    }))
    events = []
    try:
        while len(events) < 60:
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            ev = json.loads(raw)
            et = ev.get("type","")
            events.append(et)
            if "delta" not in et:
                print("event:", et)
            if et == "error":
                print("  error:", ev.get("error",{}))
            if et == "response.done":
                break
    except Exception as e2:
        print("Read err:", e2)
    await ws.close()
    audio_ct = len([e for e in events if "audio.delta" in e])
    print("Total:", len(events), "audio_deltas:", audio_ct)

asyncio.run(asyncio.wait_for(test(), timeout=30))
