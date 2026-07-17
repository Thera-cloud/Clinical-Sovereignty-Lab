"""
Dual-COO neuro-symbolic layer — CLI-Mac + CLI-Cloud as COOs; Nathan = CEO.

Risk classes (Nathan-approved policy):
  GREEN  — auto-act + digest note (ops, lint-pass reviews, non-clinical crystal apply,
           sandbox brief/matching, all patent claim tags + prior-art sweeps)
  YELLOW — morning CEO inbox batch (insight/coach labels, attribution/failover ops)
  RED    — synchronous CEO only (clinical/defense/therapeutic/sensitive)

# QUANTUM-CRYSTAL-ARCH — Dual-COO / Chief-of-Staff ceiling
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
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
    "insight_route",
    "coach_label",
    "second_order",
})

_GREEN_KINDS = frozenset({
    "review",
    "ops_fix",
    "lint_ok",
    "crystal_apply_nonclinical",
    "token_anomaly_fix",
    "bus_review",
    "compliance_redteam",
    "auditor_ops_fix",
    # QUANTUM-CRYSTAL-ARCH — CEO inbox de-noise (was YELLOW email spam)
    "matching_weight",
    "brief_refine",
    "patent_crystal_tag",
    "patent_tag_propose",  # all claim↔code maps auto-green (Nathan 2026-07-17)
    "prior_art_flag",
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

    # GREEN before patent substring — patent / prior-art / brief / matching stay digest-only
    if kind_l in _GREEN_KINDS or kind_l in ("", "work", "review"):
        return RISK_GREEN
    if "patent" in kind_l or "prior.art" in notes_l or "prior_art" in kind_l:
        return RISK_GREEN

    if kind_l in _YELLOW_KINDS:
        return RISK_YELLOW

    return RISK_YELLOW


def _ceo_dedup_key(title: str, origin: str, task_id: str = "") -> str:
    """Fingerprint for inbox dedup (title+origin+task_id)."""
    raw = f"{(origin or '')}|{(task_id or '')}|{(title or '')[:200]}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:24]
    return f"{_prefix()}:{_env()}:cli:ceo_dedup:{digest}"


def enqueue_ceo(
    *,
    risk: str,
    title: str,
    detail: str = "",
    origin: str = "cloud",
    task_id: str = "",
    payload: Optional[Dict[str, Any]] = None,
    dedup_ttl_s: int = 3600,
) -> Dict[str, Any]:
    """Push YELLOW/RED item to CEO-Nathan morning inbox (Redis list).

    Dedup: same title+origin+task_id within dedup_ttl_s is skipped (default 1h).
    Item ids are UUID-suffixed to avoid same-second ack collisions.
    """
    if risk not in (RISK_YELLOW, RISK_RED):
        return {"status": "skipped", "reason": "not_ceo_tier"}
    c = _redis()
    if not c:
        return {"status": "error", "error": "redis_unavailable"}
    dkey = _ceo_dedup_key(title or "", origin or "", task_id or "")
    try:
        if int(dedup_ttl_s or 0) > 0 and c.set(dkey, "1", nx=True, ex=int(dedup_ttl_s)) is None:
            return {"status": "skipped", "reason": "dedup"}
    except Exception as e:
        logger.debug("ceo dedup check: %s", e)
    item = {
        "id": f"{int(time.time())}-{origin[:4]}-{uuid.uuid4().hex[:8]}",
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
        # Email (YELLOW+RED) + SMS (RED) via ApprovalProtocol / SendGrid inbound
        try:
            from app.services.ceo_inbox_notify import schedule_ceo_inbox_notify

            schedule_ceo_inbox_notify(item)
        except Exception as notify_err:
            logger.debug("ceo inbox notify schedule: %s", notify_err)
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
        "failover": cloud_sole_failover_active(),
    }


def ack_ceo_inbox(*, item_id: str = "", ack_all: bool = False) -> Dict[str, Any]:
    """Remove one item (by id) or clear inbox after CEO review."""
    c = _redis()
    if not c:
        return {"status": "error", "error": "redis_unavailable"}
    try:
        key = ceo_inbox_key()
        if ack_all:
            n = int(c.llen(key) or 0)
            c.delete(key)
            return {"status": "ok", "acked": n}
        if not item_id:
            return {"status": "error", "error": "missing_item_id"}
        raws = c.lrange(key, 0, 199) or []
        kept: List[str] = []
        removed = 0
        for r in raws:
            try:
                data = json.loads(r)
            except Exception:
                kept.append(r)
                continue
            if str(data.get("id") or "") == str(item_id):
                removed += 1
                continue
            kept.append(r)
        c.delete(key)
        if kept:
            c.rpush(key, *kept)
            c.expire(key, 7 * 86400)
        return {"status": "ok", "acked": removed}
    except Exception as e:
        return {"status": "error", "error": str(e)[:300]}


def failover_key() -> str:
    return f"{_prefix()}:{_env()}:cli:coo_failover:cloud_sole"


def set_cloud_sole_failover(active: bool) -> bool:
    """When Mac Queen heartbeat is stale, Cloud runs sole-COO (no Mac execution)."""
    c = _redis()
    if not c:
        return False
    try:
        if active:
            c.setex(failover_key(), 600, json.dumps({"active": True, "ts": time.time()}))
        else:
            c.delete(failover_key())
        return True
    except Exception:
        return False


def cloud_sole_failover_active() -> bool:
    c = _redis()
    if not c:
        return False
    try:
        return bool(c.get(failover_key()))
    except Exception:
        return False


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
