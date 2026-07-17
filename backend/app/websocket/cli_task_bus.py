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


def ensure_bus_meta(client=None) -> bool:
    """Create meta marker so live probes can see the bus. Returns True if ready."""
    if not task_bus_enabled():
        return False
    c = client or _redis()
    if not c:
        return False
    try:
        meta = {
            "features": ["shared_task_bus", "cross_cli_review"],
            "max_review_rounds": MAX_REVIEW_ROUNDS,
            "updated_at": time.time(),
        }
        c.setex(bus_meta_key(), TASK_TTL_S, json.dumps(meta))
        # Ensure list key exists (empty list still "exists" after LPUSH+LPOP of sentinel — use SET marker too)
        if not c.exists(bus_list_key()):
            c.rpush(bus_list_key(), "__init__")
            c.lrem(bus_list_key(), 1, "__init__")
            # Redis list may not exist after LREM emptied it — keep a dedicated exists key
            c.setex(f"{bus_list_key()}:ready", TASK_TTL_S, "1")
        else:
            c.setex(f"{bus_list_key()}:ready", TASK_TTL_S, "1")
        return True
    except Exception as e:
        logger.debug("cli_task_bus ensure_meta: %s", e)
        return False


def probe_shared_task_bus() -> bool:
    """Live probe: meta/ready key present (never claim partnership without Redis proof)."""
    if not task_bus_enabled():
        return False
    c = _redis()
    if not c:
        return False
    try:
        ensure_bus_meta(c)
        return bool(
            c.exists(bus_meta_key())
            or c.exists(f"{bus_list_key()}:ready")
            or c.exists(bus_list_key())
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
    """Claim next task not originated by consumer (cross-CLI)."""
    if not task_bus_enabled():
        return {"status": "error", "error": "CLI_TASK_BUS_ENABLED is off"}
    c = _redis()
    if not c:
        return {"status": "error", "error": "redis_unavailable"}
    ensure_bus_meta(c)
    consumer = consumer if consumer in ("mac", "cloud") else "cloud"
    try:
        # Scan up to N items without starving the queue
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
            if rec.get("origin") == consumer:
                # Own task — put back for the other CLI
                c.rpush(bus_list_key(), task_id)
                continue
            if prefer_kind and rec.get("kind") != prefer_kind:
                c.rpush(bus_list_key(), task_id)
                continue
            if rec.get("status") not in ("queued", "review_pending"):
                continue
            rec["status"] = "claimed"
            rec["claimed_by"] = consumer
            _save_task(c, rec)
            return {"status": "ok", "task": rec}
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
