"""Studio caller board — Redis queue + LiveKit data sync. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_LOCAL: Dict[str, Dict[str, Any]] = {}
_TTL_S = 86400


def _env() -> str:
    return os.getenv("ENVIRONMENT", "development")


def _redis_key(session_id: str) -> str:
    return f"nate:{_env()}:studio:queue:{session_id}"


def caller_identity(caller_uuid: str) -> str:
    raw = (caller_uuid or "").replace("-", "")[:8]
    return f"caller-{raw}" if raw else "caller-unknown"


def empty_queue() -> Dict[str, Any]:
    return {"active": None, "waiting": [], "labels": {}}


def move_waiting(waiting: List[str], caller_id: str, delta: int) -> List[str]:
    if not caller_id or caller_id not in waiting:
        return list(waiting)
    w = list(waiting)
    i = w.index(caller_id)
    j = max(0, min(len(w) - 1, i + delta))
    if i == j:
        return w
    w.pop(i)
    w.insert(j, caller_id)
    return w


async def _load_queue(redis, session_id: str) -> Dict[str, Any]:
    key = _redis_key(session_id)
    if redis:
        try:
            raw = await redis.get(key)
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return {
                        "active": data.get("active"),
                        "waiting": list(data.get("waiting") or []),
                        "labels": dict(data.get("labels") or {}),
                    }
        except Exception as exc:
            logger.warning("studio queue redis read failed: %s", exc)
    return dict(_LOCAL.get(session_id) or empty_queue())


async def _save_queue(redis, session_id: str, q: Dict[str, Any]) -> None:
    payload = {
        "active": q.get("active"),
        "waiting": list(q.get("waiting") or []),
        "labels": dict(q.get("labels") or {}),
    }
    key = _redis_key(session_id)
    if redis:
        try:
            await redis.setex(key, _TTL_S, json.dumps(payload))
            return
        except Exception as exc:
            logger.warning("studio queue redis write failed: %s", exc)
    _LOCAL[session_id] = payload


async def _owns_session(db_pool, session_id: str, coach_id: str) -> bool:
    if not db_pool:
        return False
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT s.id FROM studio_sessions s
            JOIN studio_shows sh ON sh.id = s.show_id
            WHERE s.id = $1::uuid AND sh.coach_id = $2
            """,
            session_id,
            coach_id,
        )
    return bool(row)


async def list_session_callers(
    db_pool, session_id: str, coach_id: str
) -> Dict[str, Any]:
    if not await _owns_session(db_pool, session_id, coach_id):
        return {"ok": False, "reason": "not_found", "code": 404}
    rows: List[Any] = []
    if db_pool:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.id, c.opted_in, c.risk_flag, c.created_at,
                       (
                         SELECT t.topic_deidentified
                         FROM caller_topics t
                         WHERE t.caller_id = c.id
                         ORDER BY t.created_at DESC
                         LIMIT 1
                       ) AS topic
                FROM show_callers c
                WHERE c.session_id = $1::uuid
                ORDER BY c.created_at ASC
                """,
                session_id,
            )
    callers = []
    for r in rows:
        cid = str(r["id"])
        callers.append(
            {
                "id": cid,
                "identity": caller_identity(cid),
                "opted_in": bool(r["opted_in"]),
                "risk_flag": bool(r["risk_flag"]),
                "topic": (r["topic"] or "")[:120],
                "source": "screener",
            }
        )
    return {"ok": True, "callers": callers}


async def get_board(
    db_pool, redis, session_id: str, coach_id: str
) -> Dict[str, Any]:
    if not await _owns_session(db_pool, session_id, coach_id):
        return {"ok": False, "reason": "not_found", "code": 404}
    q = await _load_queue(redis, session_id)
    labels = dict(q.get("labels") or {})
    waiting = list(q.get("waiting") or [])
    active = q.get("active")

    from app.services.studio_livekit import list_room_participants

    db_out = await list_session_callers(db_pool, session_id, coach_id)
    for c in db_out.get("callers") or []:
        ident = c.get("identity") or ""
        if ident and ident not in labels:
            labels[ident] = (c.get("topic") or "Caller")[:48]
        if ident and ident not in waiting and ident != active:
            waiting.append(ident)

    lk = await list_room_participants(session_id)
    for p in lk.get("participants") or []:
        ident = (p.get("identity") or "").strip()
        if not ident or p.get("is_host"):
            continue
        name = (p.get("name") or ident)[:48]
        if ident not in labels:
            labels[ident] = name
        if ident not in waiting and ident != active:
            waiting.append(ident)

    board = {"active": active, "waiting": waiting, "labels": labels}
    await _save_queue(redis, session_id, board)
    return {
        "ok": True,
        "queue": {
            "active": active,
            "waiting": waiting,
            "labels": labels,
        },
        "participants": lk.get("participants") or [],
        "callers": db_out.get("callers") or [],
    }


async def _broadcast_queue(session_id: str, q: Dict[str, Any]) -> None:
    from app.services.studio_livekit import send_room_data

    await send_room_data(
        session_id,
        {
            "op": "queue",
            "active": q.get("active"),
            "waiting": list(q.get("waiting") or []),
        },
    )


async def apply_queue_op(
    db_pool,
    redis,
    session_id: str,
    coach_id: str,
    op: str,
    caller_id: str = "",
) -> Dict[str, Any]:
    if not await _owns_session(db_pool, session_id, coach_id):
        return {"ok": False, "reason": "not_found", "code": 404}
    op = (op or "").strip().lower()
    if op not in (
        "bring_on",
        "hold",
        "drop",
        "move_up",
        "move_down",
        "sync",
    ):
        return {"ok": False, "reason": "invalid_op", "code": 422}

    q = await _load_queue(redis, session_id)
    waiting = list(q.get("waiting") or [])
    active = q.get("active")
    labels = dict(q.get("labels") or {})
    cid = (caller_id or "").strip()

    if op == "move_up" and cid:
        waiting = move_waiting(waiting, cid, -1)
    elif op == "move_down" and cid:
        waiting = move_waiting(waiting, cid, 1)
    elif op == "bring_on" and cid and cid in waiting:
        waiting = [cid] + [w for w in waiting if w != cid]

    q = {"active": active, "waiting": waiting, "labels": labels}
    await _save_queue(redis, session_id, q)

    from app.services.studio_livekit import send_room_data

    if op in ("move_up", "move_down", "sync", "bring_on"):
        await _broadcast_queue(session_id, q)

    if op == "bring_on":
        await send_room_data(session_id, {"op": "bring_on"})
    elif op == "hold":
        await send_room_data(session_id, {"op": "hold"})
    elif op == "drop":
        await send_room_data(session_id, {"op": "drop"})

    board = await get_board(db_pool, redis, session_id, coach_id)
    board["op"] = op
    return board


async def enqueue_db_caller(
    redis,
    session_id: str,
    identity: str,
    label: str,
) -> None:
    if not session_id or not identity:
        return
    if redis is None:
        try:
            from app.services.api_server import _get_auth_redis

            redis = await _get_auth_redis()
        except Exception:
            redis = None
    q = await _load_queue(redis, session_id)
    waiting = list(q.get("waiting") or [])
    active = q.get("active")
    labels = dict(q.get("labels") or {})
    labels[identity] = (label or "Caller")[:48]
    if identity != active and identity not in waiting:
        waiting.append(identity)
    q = {"active": active, "waiting": waiting, "labels": labels}
    await _save_queue(redis, session_id, q)
    await _broadcast_queue(session_id, q)
