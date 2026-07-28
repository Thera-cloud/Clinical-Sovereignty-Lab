"""Broken — login_request missing expected_role."""

def login_payload(username: str, password: str, role: str) -> dict:
    # BUG: dual CLIENT/COACH accounts need expected_role
    return {"type": "login_request", "username": username, "password": password}

def looks_fixed(d: dict) -> bool:
    return d.get("expected_role") in ("CLIENT", "COACH", "ADMIN")
