"""
CLI Mac↔Cloud shared task bus (Redis).

Keys (ENVIRONMENT-scoped):
  nate:{env}:cli:taskbus          — Redis list of task_id (queue)
  nate:{env}:cli:taskbus:meta     — marker + feature flags (probe target)
  nate:{env}:cli:task:{task_id}   — JSON task record
  nate:{env}:cli:pathlock:{path}  — SETNX distributed path claims

Loop guard: max 2 review round-trips per task (review_round counter).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_REVIEW_ROUNDS = 2
TASK_TTL_S = int(os.getenv("CLI_TASK_BUS_TTL", "86400"))
PATH_LOCK_TTL_S = int(os.getenv("CLI_PATH_LOCK_TTL", "600"))

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch hive task kinds (patrol / promote / learn)
NEWSLETTER_TASK_KINDS = frozenset({
    "newsletter_topic_patrol",
    "newsletter_research_verify",
    "newsletter_draft_critique",
    "newsletter_growth_signal",
    "newsletter_symbolic_promote",
    "newsletter_trend_pairing",
    "newsletter_growth_attribution",
    "newsletter_chat_learn",
})

# QUANTUM-CRYSTAL-ARCH — Adaptive Growth Engine Dual-COO bus kinds (Phase 5)
GROWTH_TASK_KINDS = frozenset({
    "growth_policy_cross_review",
    "growth_weekly_digest",
    "growth_segment_propose",
    "growth_experiment_conclude",
})

# QUANTUM-CRYSTAL-ARCH — Multi-LoRA flywheel (W3 / W1)
FLYWHEEL_TASK_KINDS = frozenset({
    "hive_burst",
    "ln7_shadow_fork",
    "sandbox_pack_sync",
    "ln7_bakeoff",  # QUANTUM-CRYSTAL-ARCH — Attempt 6 Phase A/B via Queens bus
})


def _env() -> str:
    return os.getenv("ENVIRONMENT", "production")


def _prefix() -> str:
    return os.getenv("REDIS_KEY_PREFIX", "nate")


def bus_list_key() -> str:
    return f"{_prefix()}:{_env()}:cli:taskbus"


def bus_meta_key() -> str:
    return f"{_prefix()}:{_env()}:cli:taskbus:meta"


def task_key(task_id: str) -> str:
    return f"{_prefix()}:{_env()}:cli:task:{task_id}"


def path_lock_key(path: str) -> str:
    norm = (path or "").strip().lstrip("./").lower()
    return f"{_prefix()}:{_env()}:cli:pathlock:{norm}"


def task_bus_enabled() -> bool:
    return os.getenv("CLI_TASK_BUS_ENABLED", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


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


def _consumer_flag_on() -> bool:
    return os.getenv("CLI_TASK_BUS_CONSUMER_ENABLED", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def ensure_bus_meta(client=None, *, consumer_active: bool = False) -> bool:
    """Create meta marker after real bus activity. Returns True if ready."""
    if not task_bus_enabled():
        return False
    c = client or _redis()
    if not c:
        return False
    try:
        features = ["shared_task_bus", "cross_cli_review"]
        if consumer_active or _consumer_flag_on():
            features.append("autonomous_consumer")
        # QUANTUM-CRYSTAL-ARCH — Dual-COO / CEO-Nathan
        if os.getenv("CLI_DUAL_COO_ENABLED", "true").strip().lower() in (
            "1", "true", "yes", "on",
        ):
            features.append("dual_coo")
            features.append("ceo_inbox")
        # QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch (hive_enabled mirrors agent default)
        _hive_on = False
        try:
            from app.services.newsletter_hive import hive_enabled as _hive_enabled

            _hive_on = _hive_enabled()
        except Exception:
            _hive_on = os.getenv("ENABLE_NEWSLETTER_HIVE", "").strip().lower() in (
                "1", "true", "yes", "on",
            ) or os.getenv("ENABLE_NEWSLETTER_AGENT", "false").strip().lower() in (
                "1", "true", "yes", "on",
            )
        if _hive_on:
            features.append("newsletter_hive")
            features.extend(sorted(NEWSLETTER_TASK_KINDS))
        # QUANTUM-CRYSTAL-ARCH — Phase 5 growth Dual-COO kinds when growth engine on
        _growth_on = os.getenv("ENABLE_GROWTH_ENGINE", "false").strip().lower() in (
            "1", "true", "yes", "on",
        )
        if _growth_on:
            features.append("adaptive_growth")
            features.extend(sorted(GROWTH_TASK_KINDS))
        # QUANTUM-CRYSTAL-ARCH — flywheel hive_burst + ln7_shadow_fork
        features.append("ln7_flywheel")
        features.extend(sorted(FLYWHEEL_TASK_KINDS))
        meta = {
            "features": features,
            "max_review_rounds": MAX_REVIEW_ROUNDS,
            "updated_at": time.time(),
            "governance": "Nathan=CEO; CLI-Mac+CLI-Cloud=Dual-COO",
        }
        c.setex(bus_meta_key(), TASK_TTL_S, json.dumps(meta))
        if not c.exists(bus_list_key()):
            c.rpush(bus_list_key(), "__init__")
            c.lrem(bus_list_key(), 1, "__init__")
        c.setex(f"{bus_list_key()}:ready", TASK_TTL_S, "1")
        return True
    except Exception as e:
        logger.debug("cli_task_bus ensure_meta: %s", e)
        return False


def beat_consumer(client=None) -> bool:
    """Heartbeat proving the autonomous consumer process is alive."""
    c = client or _redis()
    if not c:
        return False
    try:
        c.setex(f"{bus_list_key()}:consumer_beat", 120, str(time.time()))
        return True
    except Exception:
        return False


def probe_shared_task_bus() -> bool:
    """Live probe: meta/ready already present — never create keys just to pass."""
    if not task_bus_enabled():
        return False
    c = _redis()
    if not c:
        return False
    try:
        return bool(
            c.exists(bus_meta_key())
            or c.exists(f"{bus_list_key()}:ready")
        )
    except Exception:
        return False


def probe_cross_cli_review_loop() -> bool:
    if not probe_shared_task_bus():
        return False
    c = _redis()
    if not c:
        return False
    try:
        raw = c.get(bus_meta_key())
        if not raw:
            return False
        meta = json.loads(raw)
        feats = meta.get("features") or []
        return "cross_cli_review" in feats
    except Exception:
        return False


def probe_autonomous_consumer() -> bool:
    """True when consumer heartbeat is fresh OR meta advertises autonomous_consumer."""
    if not task_bus_enabled() or not _consumer_flag_on():
        return False
    c = _redis()
    if not c:
        return False
    try:
        if c.exists(f"{bus_list_key()}:consumer_beat"):
            return True
        raw = c.get(bus_meta_key())
        if not raw:
            return False
        meta = json.loads(raw)
        return "autonomous_consumer" in (meta.get("features") or [])
    except Exception:
        return False


def claim_paths(paths: List[str], owner: str, *, ttl: int = PATH_LOCK_TTL_S) -> Dict[str, Any]:
    """Distributed SETNX path locks. Returns {ok, locked, blocked}."""
    c = _redis()
    if not c:
        return {"ok": False, "error": "redis_unavailable", "locked": [], "blocked": list(paths)}
    locked: List[str] = []
    blocked: List[str] = []
    for p in paths or []:
        if not p:
            continue
        key = path_lock_key(p)
        try:
            got = c.set(key, owner, nx=True, ex=ttl)
            if got:
                locked.append(p)
            else:
                cur = c.get(key)
                if cur == owner:
                    c.expire(key, ttl)
                    locked.append(p)
                else:
                    blocked.append(p)
        except Exception:
            blocked.append(p)
    return {
        "ok": len(blocked) == 0,
        "locked": locked,
        "blocked": blocked,
        "owner": owner,
    }


def release_paths(paths: List[str], owner: str) -> int:
    c = _redis()
    if not c:
        return 0
    n = 0
    for p in paths or []:
        key = path_lock_key(p)
        try:
            if c.get(key) == owner:
                c.delete(key)
                n += 1
        except Exception:
            pass
    return n


def publish_task(
    *,
    origin: str,
    files: Optional[List[str]] = None,
    status: str = "queued",
    branch: str = "",
    kind: str = "work",
    run_id: str = "",
    plan_id: str = "",
    notes: str = "",
) -> Dict[str, Any]:
    """Publish a task onto the shared bus. origin is 'mac' or 'cloud'."""
    if not task_bus_enabled():
        return {"status": "error", "error": "CLI_TASK_BUS_ENABLED is off"}
    c = _redis()
    if not c:
        return {"status": "error", "error": "redis_unavailable"}
    ensure_bus_meta(c)
    origin = origin if origin in ("mac", "cloud") else "cloud"
    files = list(files or [])
    owner = f"{origin}:{uuid.uuid4().hex[:8]}"
    lock = claim_paths(files, owner) if files else {"ok": True, "locked": [], "blocked": []}
    if files and not lock.get("ok"):
        return {
            "status": "error",
            "error": "path_lock_conflict",
            "blocked": lock.get("blocked"),
        }
    task_id = uuid.uuid4().hex[:16]
    try:
        from app.websocket.cli_dual_coo import classify_risk

        risk_tier = classify_risk(kind=kind, files=files, notes=notes or "")
    except Exception:
        risk_tier = "GREEN"
    record = {
        "task_id": task_id,
        "origin": origin,
        "files": files,
        "status": status,
        "branch": branch or "",
        "kind": kind,
        "run_id": run_id or "",
        "plan_id": plan_id or "",
        "notes": (notes or "")[:2000],
        "risk_tier": risk_tier,
        "review_round": 0,
        "max_review_rounds": MAX_REVIEW_ROUNDS,
        "findings": [],
        "claimed_by": "",
        "path_lock_owner": owner if files else "",
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    try:
        c.setex(task_key(task_id), TASK_TTL_S, json.dumps(record, default=str))
        c.rpush(bus_list_key(), task_id)
        c.setex(f"{bus_list_key()}:ready", TASK_TTL_S, "1")
        return {"status": "ok", "task": record}
    except Exception as e:
        if files:
            release_paths(files, owner)
        return {"status": "error", "error": str(e)[:400]}


def _load_task(c, task_id: str) -> Optional[Dict[str, Any]]:
    raw = c.get(task_key(task_id))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save_task(c, record: Dict[str, Any]) -> None:
    record["updated_at"] = time.time()
    c.setex(task_key(record["task_id"]), TASK_TTL_S, json.dumps(record, default=str))


def claim_task(*, consumer: str, prefer_kind: str = "") -> Dict[str, Any]:
    """Claim next task not originated by consumer (cross-CLI).

    consumer='agent' may claim any review_pending/queued review (autonomous loop).

    Cloud-sole failover (Mac heartbeat stale): Mac must not claim; cloud/agent
    may claim Mac-originated tasks so work continues without the Mac Queen.
    """
    if not task_bus_enabled():
        return {"status": "error", "error": "CLI_TASK_BUS_ENABLED is off"}
    c = _redis()
    if not c:
        return {"status": "error", "error": "redis_unavailable"}
    ensure_bus_meta(c)
    is_agent = consumer == "agent"
    if not is_agent:
        consumer = consumer if consumer in ("mac", "cloud") else "cloud"
    sole = False
    try:
        from app.websocket.cli_dual_coo import cloud_sole_failover_active

        sole = bool(cloud_sole_failover_active())
    except Exception:
        sole = False
    # QUANTUM-CRYSTAL-ARCH — Mac blocked during cloud_sole failover
    if sole and consumer == "mac":
        return {
            "status": "ok",
            "task": None,
            "detail": "cloud_sole_failover_mac_blocked",
        }
    try:
        n = int(c.llen(bus_list_key()) or 0)
        scanned = 0
        while scanned < min(n, 50):
            task_id = c.lpop(bus_list_key())
            scanned += 1
            if not task_id or task_id == "__init__":
                continue
            rec = _load_task(c, task_id)
            if not rec:
                continue
            # During sole failover, cloud/agent may claim Mac-origin work
            if not is_agent and not (sole and consumer == "cloud"):
                if rec.get("origin") == consumer:
                    c.rpush(bus_list_key(), task_id)
                    continue
            elif not is_agent and sole and consumer == "cloud":
                # Prefer Mac-origin first: skip cloud-origin when Mac tasks wait
                pass
            if prefer_kind and rec.get("kind") != prefer_kind:
                c.rpush(bus_list_key(), task_id)
                continue
            if rec.get("status") not in ("queued", "review_pending"):
                continue
            # Agent prefers review_pending; still allows queued review kinds
            if is_agent and prefer_kind == "review" and rec.get("kind") != "review":
                c.rpush(bus_list_key(), task_id)
                continue
            # Failover preference: skip non-mac when looking for mac takeover
            if sole and (is_agent or consumer == "cloud") and prefer_kind == "":
                # Allow any; mark takeover in record
                pass
            rec["status"] = "claimed"
            rec["claimed_by"] = "agent" if is_agent else consumer
            if sole and rec.get("origin") == "mac":
                rec["failover_takeover"] = True
            _save_task(c, rec)
            return {"status": "ok", "task": rec, "failover": sole}
        return {"status": "ok", "task": None, "detail": "queue_empty"}
    except Exception as e:
        return {"status": "error", "error": str(e)[:400]}


def enqueue_review(
    *,
    origin: str,
    files: Optional[List[str]] = None,
    run_id: str = "",
    plan_id: str = "",
    branch: str = "",
    notes: str = "",
) -> Dict[str, Any]:
    """After promote/commit — ask the other CLI for a read-only review pass."""
    return publish_task(
        origin=origin,
        files=files,
        status="review_pending",
        branch=branch,
        kind="review",
        run_id=run_id,
        plan_id=plan_id,
        notes=notes or "cross-CLI review: grep/read_lints/pytest",
    )


def post_findings(
    task_id: str,
    *,
    reviewer: str,
    findings: List[Dict[str, Any]],
    pass_review: bool = False,
) -> Dict[str, Any]:
    """Reviewer posts findings; bumps review_round; re-queues for originator if failing."""
    if not task_bus_enabled():
        return {"status": "error", "error": "CLI_TASK_BUS_ENABLED is off"}
    c = _redis()
    if not c:
        return {"status": "error", "error": "redis_unavailable"}
    rec = _load_task(c, task_id)
    if not rec:
        return {"status": "error", "error": "task_not_found"}
    round_n = int(rec.get("review_round") or 0) + 1
    rec["review_round"] = round_n
    rec.setdefault("findings", [])
    entry = {
        "reviewer": reviewer,
        "round": round_n,
        "pass": pass_review,
        "items": (findings or [])[:40],
        "at": time.time(),
    }
    rec["findings"].append(entry)
    if pass_review or round_n >= MAX_REVIEW_ROUNDS:
        rec["status"] = "review_done" if pass_review else "review_budget_exhausted"
        # release path locks
        owner = rec.get("path_lock_owner") or ""
        if owner and rec.get("files"):
            release_paths(list(rec["files"]), owner)
    else:
        # Hand back to originator for fixes (retry-until-green)
        rec["status"] = "fix_pending"
        rec["claimed_by"] = ""
        c.rpush(bus_list_key(), task_id)
    _save_task(c, rec)
    return {"status": "ok", "task": rec}


def get_task(task_id: str) -> Dict[str, Any]:
    c = _redis()
    if not c:
        return {"status": "error", "error": "redis_unavailable"}
    rec = _load_task(c, task_id)
    if not rec:
        return {"status": "error", "error": "task_not_found"}
    return {"status": "ok", "task": rec}
