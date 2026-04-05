"""Quick test: xAI Realtime WebSocket connectivity from inside Docker.

Run manually: python -m tests.test_xai_ws
NOT collected by pytest (no test_ function; guarded by __name__ check).
"""
import asyncio, json, os
import websockets


async def _run_xai_ws_probe():
    key = os.environ.get("XAI_API_KEY", "")
    url = "wss://api.x.ai/v1/realtime"
    print("Connecting to %s ..." % url)
    try:
        ws = await asyncio.wait_for(
            websockets.connect(url, extra_headers={"Authorization": "Bearer " + key}, max_size=None),
            timeout=10
        )
        print("Connected. Sending session.update ...")
        await ws.send(json.dumps({"type": "session.update", "session": {
            "instructions": "You are a test.",
            "voice": "Rex",
            "output_audio_format": "pcmu",
            "input_audio_format": "pcmu",
            "turn_detection": {"type": "server_vad", "silence_duration_ms": 700, "threshold": 0.5, "prefix_padding_ms": 300}
        }}))
        for i in range(5):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                ev = json.loads(raw)
                etype = ev.get("type", "unknown")
                print("Event %d: %s" % (i + 1, etype))
            except asyncio.TimeoutError:
                print("Event %d: TIMEOUT" % (i + 1,))
                break
        await ws.close()
        print("OK")
    except Exception as e:
        print("ERROR: %s: %s" % (type(e).__name__, e))


if __name__ == "__main__":
    asyncio.run(_run_xai_ws_probe())
