"""Parallel chat directories — one active thread, the rest parked.

QUANTUM-CRYSTAL-ARCH — clinical. SOVEREIGN-STANDARD.
A client can hold marriage, panel, faith, and body threads at once.
Nate answers the directory this turn belongs to and does not drag the others in.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, Optional

from app.services.attunement import store

_TTL = 14 * 24 * 60 * 60

_CUT = re.compile(
    r"\b("
    r"glitch(?:ing|ed)?|eras(?:e|ing|ed)|disconnect(?:ed|ing|ion)?|"
    r"not working|didn'?t respond|loop(?:ing|ed)|mental spasms?|"
    r"incongruent|you avoided|did not actually answer"
    r")\b",
    re.I,
)
_PRESENCE = re.compile(
    r"^\s*(are you there|still there|can you hear me|hello)\s*\??\s*$",
    re.I,
)
_MARRIAGE = re.compile(
    r"\b(bill|husband|marriage|our relationship|with him)\b",
    re.I,
)
_PANEL = re.compile(
    r"\b("
    r"theraworld|sovereign journey|story panel|panel|"
    r"dawnsinger|archivist|firekeeper|roottender"
    r")\b",
    re.I,
)
_FAITH = re.compile(
    r"\b(lord|scripture|church|prayer|holy spirit|sermon|leadership)\b",
    re.I,
)
_BODY = re.compile(
    r"\b(in my car|numb|chest|shame|can'?t sleep|exhausted)\b",
    re.I,
)

_ORDER = (
    ("marriage", _MARRIAGE),
    ("panel", _PANEL),
    ("faith", _FAITH),
    ("body", _BODY),
)


def _clip(text: str, n: int = 220) -> str:
    return " ".join((text or "").split())[:n].rstrip()


def _key(uid: str) -> str:
    return store.key("threads", uid)


def _blank() -> Dict[str, Any]:
    return {"active": "general", "threads": {}, "cut": False}


def load(uid: str) -> Dict[str, Any]:
    row = store.get_json(_key(uid)) if uid else None
    if not isinstance(row, dict):
        return _blank()
    threads = row.get("threads") if isinstance(row.get("threads"), dict) else {}
    return {
        "active": str(row.get("active") or "general"),
        "threads": threads,
        "cut": bool(row.get("cut")),
    }


def classify(text: str) -> Optional[str]:
    blob = text or ""
    if len(blob.strip()) < 12:
        return None
    for name, rx in _ORDER:
        if rx.search(blob):
            return name
    return "general"


def is_cut(text: str) -> bool:
    return bool(_CUT.search(text or ""))


def is_presence(text: str) -> bool:
    return bool(_PRESENCE.match(text or ""))


def commit_turn(uid: str, user_text: str) -> None:
    if not uid or not (user_text or "").strip():
        return
    state = load(uid)
    if is_cut(user_text) or is_presence(user_text):
        state["cut"] = is_cut(user_text)
        store.set_json(_key(uid), state, _TTL)
        return
    tid = classify(user_text) or state.get("active") or "general"
    threads = dict(state.get("threads") or {})
    prev = threads.get(tid) if isinstance(threads.get(tid), dict) else {}
    threads[tid] = {
        "beat": _clip(user_text),
        "n": int(prev.get("n") or 0) + 1,
        "at": int(time.time()),
    }
    state["active"] = tid
    state["threads"] = threads
    state["cut"] = False
    store.set_json(_key(uid), state, _TTL)


def cut_repair_line(uid: str) -> str:
    state = load(uid)
    tid = state.get("active") or "general"
    beat = ""
    row = (state.get("threads") or {}).get(tid) or {}
    if isinstance(row, dict):
        beat = (row.get("beat") or "").strip()
    if beat:
        return (
            "That cut was on my side — the reply dropped instead of landing. "
            f"Staying with this: {beat}"
        )
    return (
        "That cut was on my side — the reply dropped instead of landing. "
        "Say the last line again and I will answer that, not the room around it."
    )


def block_for_turn(uid: str, user_text: str) -> str:
    state = load(uid)
    cut = is_cut(user_text)
    presence = is_presence(user_text)
    tid = state.get("active") or "general"
    if not cut and not presence:
        guessed = classify(user_text)
        if guessed:
            tid = guessed
    threads = state.get("threads") or {}
    lines = [
        "THREAD DIRECTORY — separate conversations. Answer only the active one.",
        f"Active: {tid}.",
    ]
    parked = []
    for name, row in threads.items():
        if name == tid or not isinstance(row, dict):
            continue
        beat = _clip(str(row.get("beat") or ""), 120)
        if beat:
            parked.append(f"{name}: {beat}")
    if parked:
        lines.append("Parked (do not bring these in unless she names them):")
        lines.extend(f"- {p}" for p in parked[:4])
    else:
        lines.append("No other open directories.")
    if cut:
        lines.append(
            "CUT REPAIR: She named a glitch, erase, or a reply that missed her. "
            "Sentence 1 owns the cut. Then answer the active directory's last beat. "
            "Do not ask which part matters. Do not use a stock heavy-line."
        )
    elif presence:
        lines.append(
            "PRESENCE CHECK: One short yes, then the active beat. "
            "No welcome-back. No new topic."
        )
    else:
        lines.append(
            "Open on what she just said in this directory. "
            "If she switches directories, name the switch in one clause, then stay there."
        )
    return "\n".join(lines)
