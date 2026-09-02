"""Host-only studio share: web lookup cards + SFX catalog. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger("studio_cohost_share")

SOUND_CATALOG: Dict[str, Dict[str, str]] = {
    "sting": {"label": "Sting", "hint": "short brass hit"},
    "hit": {"label": "Sting hit", "hint": "harder button"},
    "whoosh": {"label": "Whoosh", "hint": "sweep in"},
    "chime": {"label": "Chime", "hint": "soft mark"},
    "bed": {"label": "Soft bed", "hint": "under-talk pad"},
}

_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_SEEN: Dict[str, Dict[str, Any]] = {}
_SEEN_TTL = 90.0


def is_studio_host_identity(identity: str) -> bool:
    ident = (identity or "").strip().lower()
    if not ident:
        return False
    if ident in {"egress", "guest", "caller"}:
        return False
    if ident.startswith("guest") or ident.startswith("caller"):
        return False
    return True


def note_has_seen_content(note: str) -> bool:
    """True when the share note is a real page read, not a generic picker line."""
    n = (note or "").strip()
    if len(n) < 28:
        return False
    low = n.lower()
    if low.startswith("host is sharing"):
        return False
    if low.startswith("host opened "):
        return False
    return True


def remember_share_frame(session_id: str, note: str, jpeg_b64: str = "") -> None:
    sid = (session_id or "").strip()
    if not sid:
        return
    _SEEN[sid] = {
        "note": (note or "")[:800],
        "jpeg": (jpeg_b64 or "")[:900_000],
        "at": time.time(),
    }


def forget_share_frame(session_id: str) -> None:
    sid = (session_id or "").strip()
    if sid:
        _SEEN.pop(sid, None)


def share_seen(session_id: str) -> Dict[str, str]:
    sid = (session_id or "").strip()
    row = _SEEN.get(sid) or {}
    if not row:
        return {}
    if time.time() - float(row.get("at") or 0) > _SEEN_TTL:
        _SEEN.pop(sid, None)
        return {}
    return {"note": str(row.get("note") or ""), "jpeg": str(row.get("jpeg") or "")}


def merge_share_note(posted: str, seen_note: str) -> str:
    if note_has_seen_content(posted):
        return (posted or "").strip()
    return ((seen_note or posted) or "").strip()


async def describe_share_frame(image_bytes: bytes) -> Dict[str, Any]:
    raw = image_bytes or b""
    if len(raw) < 80:
        return {"ok": False, "reason": "empty_frame", "code": 422}
    if len(raw) > 500_000:
        return {"ok": False, "reason": "frame_too_large", "code": 413}
    jpeg = base64.b64encode(raw).decode("ascii")
    note = ""
    try:
        from app.services.nate_inference_router import NateInferenceRouter

        out = await NateInferenceRouter().generate(
            prompt=(
                "Read this live screenshare. List only visible titles, headings, "
                "quotes, and UI labels. If you cannot read it, reply exactly: unread"
            ),
            system="OCR only. No guesses. No invented page titles.",
            domain="culture",
            max_tokens=220,
            images=[jpeg],
        )
        note = (out.get("text") or "").strip()
        if note.lower() in {"unread", "unable to process images"}:
            note = ""
        if "temporarily unable" in note.lower():
            note = ""
    except Exception as exc:
        logger.warning("studio share-frame describe skipped: %s", exc)
        note = ""
    return {"ok": True, "note": note[:800], "seen": bool(note), "jpeg": jpeg}


def resolve_sound(sound_id: str) -> Dict[str, Any]:
    key = (sound_id or "").strip().lower().replace(" ", "_")
    aliases = {
        "sting_hit": "hit",
        "sting-hit": "hit",
        "sound": "sting",
        "sfx": "sting",
        "pad": "bed",
    }
    key = aliases.get(key, key)
    meta = SOUND_CATALOG.get(key)
    if not meta:
        return {"ok": False, "reason": "unknown_sound", "code": 422}
    return {"ok": True, "sound_id": key, **meta}


def sound_catalog() -> List[Dict[str, str]]:
    return [{"id": k, **v} for k, v in SOUND_CATALOG.items()]


def safe_https_url(url: str) -> Optional[str]:
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        return None
    host = (parsed.hostname or "").lower()
    if not host or host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        return None
    if all(part.isdigit() for part in host.split(".")):
        return None
    return raw[:500]


def is_image_url(url: str) -> bool:
    path = urlparse(url or "").path.lower()
    return any(path.endswith(ext) for ext in _IMAGE_EXT)


def host_url_card(url: str) -> Dict[str, Any]:
    safe = safe_https_url(url)
    if not safe:
        return {"ok": False, "reason": "https_url_required", "code": 422}
    return {
        "ok": True,
        "kind": "url",
        "url": safe,
        "image": is_image_url(safe),
        "note": f"Host opened {safe}",
    }


def _cards_from_search(results: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    cards: List[Dict[str, str]] = []
    for row in results or []:
        if row.get("injection_detected") or not row.get("safe", True):
            continue
        title = (row.get("title") or "").strip()[:200]
        snippet = (row.get("snippet") or "").strip()[:400]
        href = (row.get("url") or "").strip()
        if not title and not href:
            continue
        cards.append(
            {
                "title": title or "Result",
                "snippet": snippet,
                "url": href[:500],
                "domain": (row.get("domain") or "")[:120],
                "image": "1" if is_image_url(href) else "",
            }
        )
        if len(cards) >= 3:
            break
    return cards


def share_note(kind: str, query: str = "", cards: Optional[List[Dict[str, str]]] = None) -> str:
    label = (kind or "share").strip() or "share"
    q = (query or "").strip()
    titles = [c.get("title") or "" for c in (cards or []) if c.get("title")]
    if label == "search" and titles:
        head = f"Lookup: {q}. " if q else ""
        return (head + "On screen: " + "; ".join(titles[:3]))[:800]
    if q:
        return f"{label}: {q}"[:800]
    return f"Host is sharing {label}."[:800]


async def host_search(proxy: Any, query: str, identity: str) -> Dict[str, Any]:
    q = (query or "").strip()[:240]
    if not q:
        return {"ok": False, "reason": "query required", "code": 422}
    if proxy is None or not hasattr(proxy, "execute_search"):
        return {"ok": False, "reason": "search_unavailable", "code": 503}
    out = await proxy.execute_search(q, coach_id=identity or "studio_host", num_results=3)
    if not out or not out.get("success"):
        return {
            "ok": False,
            "reason": (out or {}).get("error") or "search_failed",
            "code": 502,
            "query": q,
            "results": [],
        }
    cards = _cards_from_search(list(out.get("results") or []))
    return {
        "ok": True,
        "kind": "search",
        "query": q,
        "results": cards,
        "note": share_note("search", q, cards),
    }
