"""Night School drills. The paid map decides the tab. The session kind decides the exercise."""

from typing import Any, Dict, List, Optional

from app.services.coach_dojo_access import active_dojo_keys
from app.services.dojo_mentor_engine import MASTER_PERSONA

NIGHT_SCHOOL_MODES = (
    "therapist",
    "project_pm",
    "business",
    "cnc",
    "mcat",
    "teacher",
    "judge",
)
_PRACTICE_RULES = (
    "This is coach practice, not a live client session. "
    "Train the coach in this DOJO only. Do not switch to another DOJO. "
    "Do not treat the drill as a real crisis event. "
    "If you cannot answer, say the model is unavailable and stop."
)
_SIMULATION_RULES = (
    "This is a Night School simulation. The coach is playing the scenario. "
    "Stay in this DOJO. Do not treat the scenario as a real crisis event. "
    "If you cannot answer, say the model is unavailable and stop."
)


def stamp_active_dojos(profile: Dict[str, Any], blocked: Optional[List[str]] = None) -> None:
    """Attach the server list the page is allowed to show. Does not rewrite subscriptions."""
    if not isinstance(profile, dict):
        return
    role = str(profile.get("role") or "").upper()
    if role == "ADMIN":
        profile["active_dojos"] = list(NIGHT_SCHOOL_MODES) + ["coach_nate"]
        return
    if role != "COACH":
        return
    profile["active_dojos"] = active_dojo_keys(profile, blocked or [])


async def attach_active_dojos(profile: Dict[str, Any], db) -> None:
    blocked: List[str] = []
    if db is not None and str((profile or {}).get("role") or "").upper() == "COACH":
        try:
            from app.services.coach_payment_hold import blocked_dojos_for
            blocked = await blocked_dojos_for(db, profile.get("username") or "")
        except Exception:
            blocked = list(profile.get("coach_hold_blocked_dojos") or [])
    stamp_active_dojos(profile, blocked)


def drill_preface(user_text: str) -> str:
    """Pull the SYSTEM block out of a drill message. Empty when the message is ordinary chat."""
    text = user_text or ""
    if not (text.startswith("[DOJO PRACTICE]") or text.startswith("[DOJO SIMULATION")):
        return ""
    marker = "\nSYSTEM:"
    end = "\nCOACH:"
    start = text.find(marker)
    stop = text.find(end)
    if start < 0 or stop <= start:
        return ""
    return text[start + len(marker):stop].strip()


def prepare_turn(
    profile: Any,
    blocked: Optional[List[str]],
    dojo_type: Any,
    session_kind: Any,
    text: Any,
    persona: Any = "",
) -> Dict[str, str]:
    """Build one drill. An unpaid DOJO is an error, not a different DOJO."""
    data = profile if isinstance(profile, dict) else {}
    role = str(data.get("role") or "").upper()
    dojo = str(dojo_type or "").strip().lower()
    kind = str(session_kind or "").strip().lower()
    body = str(text or "").strip()
    if kind not in ("practice", "simulation"):
        return {"error": "DOJO_SESSION_KIND", "user_text": "", "dojo_type": dojo}
    if not body:
        return {"error": "DOJO_EMPTY", "user_text": "", "dojo_type": dojo}
    if role == "ADMIN":
        allowed = set(NIGHT_SCHOOL_MODES) | {"coach_nate"}
    elif role == "CLIENT":
        allowed = {"judge"} if data.get("judge_dojo_access") else set()
    else:
        allowed = set(active_dojo_keys(data, blocked or []))
    if dojo not in allowed or dojo not in MASTER_PERSONA:
        return {"error": "DOJO_NOT_SUBSCRIBED", "user_text": "", "dojo_type": dojo}
    if dojo == "coach_nate" and kind == "simulation":
        return {"error": "DOJO_NOT_SUBSCRIBED", "user_text": "", "dojo_type": dojo}
    who = str(persona or "").strip()
    rules = _PRACTICE_RULES if kind == "practice" else _SIMULATION_RULES
    prefix = "[DOJO PRACTICE]" if kind == "practice" else "[DOJO SIMULATION]"
    system = f"{MASTER_PERSONA[dojo]}\n{rules}"
    if who:
        system = f"{system}\nScenario: {who}."
    user_text = f"{prefix}\nSYSTEM:{system}\nCOACH:{body}"
    return {"error": "", "user_text": user_text, "dojo_type": dojo}
