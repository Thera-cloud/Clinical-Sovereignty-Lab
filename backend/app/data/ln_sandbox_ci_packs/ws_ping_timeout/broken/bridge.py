"""Broken — WebSocket ping_timeout too short under load."""

def serve_kwargs() -> dict:
    # BUG: 10s kills connections mid-inference
    return {"ping_interval": 20, "ping_timeout": 10, "close_timeout": 30}

def looks_fixed(d: dict) -> bool:
    return int(d.get("ping_timeout") or 0) >= 60
