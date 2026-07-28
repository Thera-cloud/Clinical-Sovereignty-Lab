"""Broken — registration missing coach_id."""

def new_client_profile(coach_hw: str, coach_user: str) -> dict:
    # BUG: need coach_id + assigned_coach_id + assigned_coach
    return {"assigned_coach": coach_user}

def looks_fixed(d: dict) -> bool:
    return all(k in d for k in ("coach_id", "assigned_coach_id", "assigned_coach"))
