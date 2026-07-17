"""
Dual-COO neuro-symbolic layer — CLI-Mac + CLI-Cloud as COOs; Nathan = CEO.

Risk classes (Nathan-approved policy):
  GREEN  — auto-act + digest note (ops, lint-pass reviews, non-clinical crystal apply)
  YELLOW — morning CEO inbox batch (matching/brief/patent tag proposals)
  RED    — synchronous CEO only (clinical/defense/therapeutic/sensitive)

# QUANTUM-CRYSTAL-ARCH — Dual-COO / Chief-of-Staff ceiling
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.cli_dual_coo")

RISK_GREEN = "GREEN"
RISK_YELLOW = "YELLOW"
RISK_RED = "RED"

# Paths / keywords that force RED (CEO-Nathan)
_RED_PATH_MARKERS = (
    "nevedal_engine",
    "sensitive_clinical",
    "sensitive_bridge",
    "therapeutic_controller",
    "crisis",
    "voice_billing",
    "twilio_grok",
    "bridge_server.py",
    "littlenate_inference",
    "nate_memory_crystallizer",
)

_RED_DOMAINS = frozenset({"clinical", "defense"})

_YELLOW_KINDS = frozenset({
    "patent_tag_propose",
    "matching_weight",
    "brief_refine",
    "prior_art_flag",
    "insight_route",
})

_GREEN_KINDS = frozenset({
    "review",
    "ops_fix",
    "lint_ok",
    "crystal_apply_nonclinical",
    "token_anomaly_fix",
    "bus_review",
})


def dual_coo_enabled() -> bool:
    return os.getenv("CLI_DUAL_COO_ENABLED", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _env() -> str:
    return os.getenv("ENVIRONMENT", "production")


def _prefix() -> str:
    return os.getenv("REDIS_KEY_PREFIX", "nate")


def ceo_inbox_key() -> str:
    return f"{_prefix()}:{_env()}:cli:ceo_inbox"


def queen_beat_key(role: str) -> str:
    """role: mac | cloud"""
    r = role if role in ("mac", "cloud") else "cloud"
    return f"{_prefix()}:{_env()}:cli:coo_beat:{r}"


def _redis():
    if os.getenv("REDIS_URL", "__unset__") == "":
        return None
    try:
        import redis as sync_redis

        url = os.getenv("REDIS_URL", "")
        if not url:
            return None
        return sync_redis.Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=0.5,
        )
    except Exception:
        return None


def beat_queen(role: str, *, meta: Optional[Dict[str, Any]] = None) -> bool:
    """COO heartbeat so the peer Queen can detect peer liveness."""
    c = _redis()
    if not c:
        return False
    payload = {
        "role": role,
        "ts": time.time(),
        "meta": meta or {},
    }
    try:
        c.setex(queen_beat_key(role), 180, json.dumps(payload))
        return True
    except Exception as e:
        logger.debug("beat_queen failed: %s", e)
        return False


def peer_queen_alive(role: str, *, max_age_s: float = 180.0) -> Dict[str, Any]:
    """Check the *other* Queen's heartbeat."""
    peer = "mac" if role == "cloud" else "cloud"
    c = _redis()
    if not c:
        return {"alive": False, "peer": peer, "error": "redis_unavailable"}
    try:
        raw = c.get(queen_beat_key(peer))
        if not raw:
            return {"alive": False, "peer": peer, "detail": "no_beat"}
        data = json.loads(raw)
        age = time.time() - float(data.get("ts") or 0)
        return {
            "alive": age <= max_age_s,
            "peer": peer,
            "age_s": round(age, 1),
            "meta": data.get("meta") or {},
        }
    except Exception as e:
        return {"alive": False, "peer": peer, "error": str(e)[:200]}


def classify_risk(
    *,
    kind: str = "",
    files: Optional[List[str]] = None,
    domain: str = "",
    notes: str = "",
) -> str:
    """Symbolic risk classifier — RED wins over YELLOW over GREEN."""
    kind_l = (kind or "").strip().lower()
    domain_l = (domain or "").strip().lower()
    notes_l = (notes or "").lower()
    files = list(files or [])

    if domain_l in _RED_DOMAINS:
        return RISK_RED
    for p in files:
        pl = (p or "").lower()
        if any(m in pl for m in _RED_PATH_MARKERS):
            return RISK_RED
    if any(m in notes_l for m in ("therapeutic", "crisis", "r-floor", "sensitive bridge")):
        return RISK_RED

    if kind_l in _YELLOW_KINDS or "patent" in kind_l or "prior.art" in notes_l:
        return RISK_YELLOW

    if kind_l in _GREEN_KINDS or kind_l in ("", "work", "review"):
        # Review of non-RED files stays GREEN
        return RISK_GREEN

    return RISK_YELLOW


def enqueue_ceo(
    *,
    risk: str,
    title: str,
    detail: str = "",
    origin: str = "cloud",
    task_id: str = "",
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Push YELLOW/RED item to CEO-Nathan morning inbox (Redis list)."""
    if risk not in (RISK_YELLOW, RISK_RED):
        return {"status": "skipped", "reason": "not_ceo_tier"}
    c = _redis()
    if not c:
        return {"status": "error", "error": "redis_unavailable"}
    item = {
        "id": f"{int(time.time())}-{origin[:4]}",
        "risk": risk,
        "title": (title or "")[:300],
        "detail": (detail or "")[:2000],
        "origin": origin,
        "task_id": task_id or "",
        "payload": payload or {},
        "created_at": time.time(),
        "status": "pending_ceo",
    }
    try:
        c.lpush(ceo_inbox_key(), json.dumps(item, default=str))
        c.ltrim(ceo_inbox_key(), 0, 199)
        c.expire(ceo_inbox_key(), 7 * 86400)
        return {"status": "ok", "item": item}
    except Exception as e:
        return {"status": "error", "error": str(e)[:300]}


def peek_ceo_inbox(limit: int = 25) -> List[Dict[str, Any]]:
    c = _redis()
    if not c:
        return []
    try:
        raws = c.lrange(ceo_inbox_key(), 0, max(0, limit - 1)) or []
        out: List[Dict[str, Any]] = []
        for r in raws:
            try:
                out.append(json.loads(r))
            except Exception:
                continue
        return out
    except Exception:
        return []


def ceo_inbox_summary() -> Dict[str, Any]:
    items = peek_ceo_inbox(100)
    yellow = sum(1 for i in items if i.get("risk") == RISK_YELLOW)
    red = sum(1 for i in items if i.get("risk") == RISK_RED)
    return {
        "pending": len(items),
        "yellow": yellow,
        "red": red,
        "top": items[:8],
    }


def dual_coo_system_addon() -> str:
    return (
        "\nDUAL-COO (Nathan = CEO): You are one Queen COO (CLI-Mac or CLI-Cloud). "
        "Your peer Queen is the other COO — monitor via shared task bus, path locks, "
        "and cross-CLI review. Classify work GREEN (auto + digest), YELLOW (CEO morning "
        "inbox), RED (CEO-Nathan only: clinical/defense/therapeutic/sensitive). "
        "Never auto-apply clinical crystal confidence or ship RED without CEO. "
        "Reflect against your peer: enqueue_review after promotes; treat peer findings "
        "as backup verification of one mind.\n"
    )


def probe_dual_coo() -> bool:
    if not dual_coo_enabled():
        return False
    try:
        from app.websocket.cli_task_bus import probe_shared_task_bus

        return probe_shared_task_bus()
    except Exception:
        return False
