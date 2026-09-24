"""Working show thread — goal, constraints, evidence, citation trail. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import re
from typing import Any, Dict, List

_SHOWS: Dict[str, Dict[str, Any]] = {}

_CORRECTION = re.compile(
    r"\b(?:no[, ]+i mean|i mean|i meant|that'?s not|i don'?t mean|not a |not the )\b",
    re.I,
)
_RESET = re.compile(r"\b(?:start over|forget that|scratch that|reset(?: the topic)?)\b", re.I)
_BACK = re.compile(r"\b(?:back to|earlier|you said|go back|we were talking)\b", re.I)
_PIVOT = re.compile(r"\b(?:anyway|different question|switch gears|new topic|instead)\b", re.I)
_AMBIG = re.compile(r"^(?:that|it|this|he|she|they|those|the one|the other)\b", re.I)
_LOOKUP = re.compile(
    r"\b(?:look (?:that |it |this )?up|search|who is|what is|when did|where is)\b",
    re.I,
)


def _blank() -> Dict[str, Any]:
    return {
        "who": "host",
        "goal": "",
        "constraints": [],
        "topic": "",
        "move": "continue",
        "citations": [],
        "last_user": "",
        "last_reply": "",
    }


def read_show(session_id: str) -> Dict[str, Any]:
    row = _SHOWS.get((session_id or "").strip()) or _blank()
    return {
        "who": row.get("who") or "host",
        "goal": row.get("goal") or "",
        "constraints": list(row.get("constraints") or []),
        "topic": row.get("topic") or "",
        "move": row.get("move") or "continue",
        "citations": list(row.get("citations") or []),
    }


def interpret(session_id: str, speaker: str, text: str) -> str:
    """continue | pivot | reset | new_topic | backtrack."""
    blob = (text or "").strip()
    low = blob.lower()
    state = read_show(session_id)
    if _RESET.search(low):
        return "reset"
    if _CORRECTION.search(low):
        return "backtrack"
    if _BACK.search(low):
        return "continue"
    if _PIVOT.search(low):
        return "pivot" if state.get("goal") else "new_topic"
    if _AMBIG.search(low) and not state.get("goal"):
        return "backtrack"
    if state.get("goal") and _AMBIG.search(low):
        return "continue"
    if state.get("goal") and len(blob.split()) <= 4:
        return "continue"
    if state.get("topic") and state["topic"].lower() not in low and len(blob.split()) > 12:
        return "pivot" if state.get("goal") else "new_topic"
    if not state.get("goal"):
        return "new_topic"
    return "continue"


def _clip(text: str, n: int) -> str:
    line = " ".join((text or "").split())
    return line[:n].rstrip()


def apply_turn(session_id: str, speaker: str, text: str, move: str, reply: str) -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    blob = (text or "").strip()
    state = _SHOWS.setdefault(sid, _blank())
    if state.get("last_user") == blob and state.get("last_reply") == (reply or "").strip():
        return
    who = "caller" if (speaker or "").lower().startswith("caller") else "host"
    state["who"] = who
    state["move"] = move
    if move in ("reset", "new_topic"):
        state["goal"] = _clip(blob, 240)
        state["topic"] = _clip(blob, 80)
        if move == "reset":
            state["constraints"] = []
    elif move == "backtrack":
        cons = list(state.get("constraints") or [])
        cons.append(_clip(blob, 180))
        state["constraints"] = cons[-6:]
    elif move == "pivot":
        state["topic"] = _clip(blob, 80)
        if not state.get("goal"):
            state["goal"] = _clip(blob, 240)
    elif not state.get("goal"):
        state["goal"] = _clip(blob, 240)
        state["topic"] = _clip(blob, 80)
    state["last_user"] = blob
    state["last_reply"] = (reply or "").strip()


def note_citations(session_id: str, items: List[Dict[str, str]]) -> None:
    sid = (session_id or "").strip()
    if not sid or not items:
        return
    state = _SHOWS.setdefault(sid, _blank())
    trail = list(state.get("citations") or [])
    for item in items:
        title = _clip(str(item.get("title") or ""), 120)
        src = _clip(str(item.get("source") or ""), 80)
        if not title:
            continue
        trail.append({"title": title, "source": src})
    state["citations"] = trail[-8:]


def needs_lookup(speaker: str, text: str) -> bool:
    if (speaker or "").lower().startswith("caller"):
        return False
    return bool(_LOOKUP.search(text or ""))


def turn_block(
    session_id: str,
    move: str,
    *,
    host_seen: bool,
    host_note: str,
    share_seen: bool,
    share_note: str,
    fresh: str = "",
) -> str:
    state = read_show(session_id)
    cons = "; ".join(state["constraints"]) or "none yet"
    goal = state["goal"] or "not set — this line sets it"
    lines = [
        "WORKING SHOW",
        f"Speaking: {state['who']}. Goal: {goal}.",
        f"Constraints from earlier turns (keep these): {cons}.",
        f"Move this turn: {move}.",
    ]
    if move == "continue":
        lines.append("Stay on their goal. Use shorthand and pronouns as pointing at that goal.")
    elif move == "pivot":
        lines.append("Take the new angle. Keep the constraints. Do not drop what they already corrected.")
    elif move == "reset":
        lines.append("Drop the old topic. Answer this line as the new goal.")
    elif move == "new_topic":
        lines.append("This line is the goal. Answer it. Do not drag the backdrop in.")
    else:
        lines.append(
            "The reference is ambiguous or they are correcting you. "
            "Say the two readings in one breath, say which one you think they mean and why, "
            "then answer that reading."
        )
    lines.append(
        "Shape the reply around their question. No stock opener. No fixed essay. "
        "Match their length. If they asked for a choice, name the tradeoff and one next path. "
        "Do not invent a shared past. Do not interview them to end the turn."
    )
    if host_seen:
        note = _clip(host_note, 240) or "still attached"
        lines.append(f"HOST FRAME (real still): {note}. Say only what is in that frame.")
    else:
        lines.append("HOST FRAME: no still this turn. If they ask what you see, say you do not have the picture.")
    if share_seen:
        lines.append(f"ON SCREEN (read): {_clip(share_note, 400)}. Quote only that.")
    elif share_note:
        lines.append("ON SCREEN: a share is up and you have no read. Say you cannot see the page yet.")
    if fresh:
        lines.append(
            "FRESH NOTES for this question. Synthesize. Do not read titles or links unless they ask where it came from.\n"
            + fresh
        )
    if state["citations"]:
        titles = ", ".join(c["title"] for c in state["citations"][-3:])
        lines.append(f"Research trail already held (do not recite): {titles}.")
    return "\n".join(lines)


async def fresh_notes(query: str) -> List[Dict[str, str]]:
    q = _clip(query, 180)
    if not q:
        return []
    try:
        import asyncio

        from app.services.search_proxy import SecureSearchProxy

        out = await asyncio.wait_for(
            SecureSearchProxy().execute_search(q, coach_id="studio-cohost", num_results=3),
            timeout=3.5,
        )
    except Exception:
        return []
    rows = []
    for item in (out or {}).get("results") or []:
        if not isinstance(item, dict):
            continue
        title = _clip(str(item.get("title") or ""), 120)
        snippet = _clip(str(item.get("snippet") or item.get("body") or ""), 220)
        src = _clip(str(item.get("source") or item.get("domain") or ""), 80)
        if title or snippet:
            rows.append({"title": title, "source": src, "snippet": snippet})
    return rows[:3]
