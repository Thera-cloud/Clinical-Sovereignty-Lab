"""Live reply shape and length choice. QUANTUM-CRYSTAL-ARCH

Open on the tail of what they just said, then a take. A long question asks
whether they want the short version or the defined one, and both are already
forming in the background.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, Optional

LENGTH_ASK = (
    "Want the short version, or the more defined one? "
    "I am already working both."
)

_STOCK = re.compile(
    r"^(?:honestly|man|yeah[, ]+man|oh[, ]+man|"
    r"that(?:'s| is) a great question(?:[, ]+big nate)?)[,.]?\s+",
    re.I,
)
_SHORT = re.compile(
    r"\b(?:short version|the short one|keep it short|brief version|short one)\b"
    r"|^(?:short|brief)\.?$",
    re.I,
)
_LONG = re.compile(
    r"\b(?:more defined|defined one|the long one|fuller one|full version|"
    r"long version|go long|the defined one)\b"
    r"|^(?:long|full|defined|fuller)\.?$",
    re.I,
)
_PENDING: Dict[str, Dict[str, Any]] = {}


def strip_stock_open(text: str) -> str:
    line = (text or "").strip()
    for _ in range(2):
        nxt = _STOCK.sub("", line, count=1).strip()
        if nxt == line or not nxt:
            break
        line = nxt[:1].upper() + nxt[1:] if nxt[:1].islower() else nxt
    return line


def is_long_question(blob: str) -> bool:
    words = (blob or "").split()
    if len(words) < 40:
        return False
    low = blob.lower()
    return "?" in blob or bool(re.search(r"\b(?:what|how|why|would|should)\b", low))


def length_pick(text: str) -> Optional[str]:
    low = (text or "").strip().lower()
    if not low:
        return None
    if _SHORT.search(low) and not _LONG.search(low):
        return "short"
    if _LONG.search(low) and not _SHORT.search(low):
        return "long"
    return None


def arm_lengths(session_id: str, blob: str, short_task: asyncio.Task, long_task: asyncio.Task) -> None:
    sid = (session_id or "").strip()
    old = _PENDING.pop(sid, None)
    if old:
        for key in ("short", "long"):
            task = old.get(key)
            if task is not None and not task.done():
                task.cancel()
    _PENDING[sid] = {"blob": blob, "short": short_task, "long": long_task}


def drop_lengths(session_id: str) -> None:
    sid = (session_id or "").strip()
    old = _PENDING.pop(sid, None)
    if not old:
        return
    for key in ("short", "long"):
        task = old.get(key)
        if task is not None and not task.done():
            task.cancel()


async def take_length(session_id: str, blob: str) -> Optional[str]:
    sid = (session_id or "").strip()
    pending = _PENDING.get(sid)
    if not pending:
        return None
    pick = length_pick(blob)
    if not pick:
        if len((blob or "").split()) > 12:
            drop_lengths(sid)
        return None
    task = pending.get(pick)
    _PENDING.pop(sid, None)
    other = "long" if pick == "short" else "short"
    leftover = pending.get(other)
    if leftover is not None and not leftover.done():
        leftover.cancel()
    if task is None:
        return None
    try:
        text = await asyncio.wait_for(task, timeout=25.0)
    except Exception:
        return None
    return (text or "").strip() or None
