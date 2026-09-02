"""Host-only studio share: web lookup cards + SFX catalog. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

SOUND_CATALOG: Dict[str, Dict[str, str]] = {
    "sting": {"label": "Sting", "hint": "short brass hit"},
    "hit": {"label": "Sting hit", "hint": "harder button"},
    "whoosh": {"label": "Whoosh", "hint": "sweep in"},
    "chime": {"label": "Chime", "hint": "soft mark"},
    "bed": {"label": "Soft bed", "hint": "under-talk pad"},
}

_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def is_studio_host_identity(identity: str) -> bool:
    ident = (identity or "").strip().lower()
    if not ident:
        return False
    if ident in {"egress", "guest", "caller"}:
        return False
    if ident.startswith("guest") or ident.startswith("caller"):
        return False
    return True


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
