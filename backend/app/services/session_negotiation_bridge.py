"""
QUANTUM-CRYSTAL-ARCH: Thin bridge adapters for session_negotiation_service.
Keeps protected bridge_server.py edits small.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("nate.session_negotiation_bridge")


async def _send(ws: Any, payload: Dict[str, Any]) -> None:
    if not ws or not payload:
        return
    try:
        await ws.send(json.dumps(payload))
    except Exception as e:
        logger.warning("session_negotiation_bridge: send failed: %s", e)


async def dispatch_notifies(
    result: Dict[str, Any],
    *,
    connected_clients: Dict[str, Any],
    connected_coaches: Dict[str, Any],
    primary_ws: Any = None,
    primary_role: str = "",
) -> None:
    neg = result.get("negotiation") or {}
    client_id = neg.get("client_id") or ""
    coach_id = neg.get("coach_id") or ""

    cn = result.get("client_notify")
    if cn:
        await _send(connected_clients.get(client_id), cn)
        if primary_role == "CLIENT" and primary_ws and result.get("client_nate_text"):
            await _send(primary_ws, {"type": "nate_response", "text": result["client_nate_text"]})

    coach_n = result.get("coach_notify")
    if coach_n:
        await _send(connected_coaches.get(coach_id), coach_n)
        if primary_role == "COACH" and primary_ws and result.get("coach_nate_text"):
            await _send(primary_ws, {"type": "nate_response", "text": result["coach_nate_text"]})

    # Coach-initiated decide: also nate_response to coach
    if primary_role == "COACH" and primary_ws and result.get("coach_nate_text") and not coach_n:
        await _send(primary_ws, {"type": "nate_response", "text": result["coach_nate_text"]})
    if primary_role == "CLIENT" and primary_ws and result.get("client_nate_text") and not cn:
        await _send(primary_ws, {"type": "nate_response", "text": result["client_nate_text"]})


def _mutate_session(
    sessions: List[Dict[str, Any]],
    session_id: str,
    *,
    status: Optional[str] = None,
    new_start: Optional[str] = None,
    new_end: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    for s in sessions:
        if s.get("session_id") != session_id:
            continue
        if status:
            s["status"] = status
            if status == "scheduled":
                s["approved_at"] = str(datetime.now())
                s["approved_via"] = "nate_negotiation"
            if status == "declined":
                s["declined_at"] = str(datetime.now())
                s["declined_via"] = "nate_negotiation"
        if new_start:
            s["scheduled_start"] = new_start
        if new_end:
            s["scheduled_end"] = new_end
        return s
    return None


async def apply_bridge_action(
    result: Dict[str, Any],
    *,
    load_sessions: Callable[[], List[Dict[str, Any]]],
    save_sessions: Callable[[List[Dict[str, Any]]], None],
    db_pool: Any = None,
    connected_clients: Optional[Dict[str, Any]] = None,
    connected_coaches: Optional[Dict[str, Any]] = None,
    primary_ws: Any = None,
    primary_role: str = "",
) -> Dict[str, Any]:
    """Apply approve / decline / reschedule side effects on JSON sessions + notify."""
    connected_clients = connected_clients or {}
    connected_coaches = connected_coaches or {}
    action = result.get("bridge_action") or "none"
    session_id = result.get("session_id") or ""
    found = None

    if action in ("approve_session", "decline_session", "reschedule_and_approve") and session_id:
        sessions = load_sessions()
        if action == "approve_session":
            found = _mutate_session(sessions, session_id, status="scheduled")
        elif action == "decline_session":
            found = _mutate_session(sessions, session_id, status="declined")
        elif action == "reschedule_and_approve":
            found = _mutate_session(
                sessions,
                session_id,
                status="scheduled",
                new_start=result.get("new_start"),
                new_end=result.get("new_end"),
            )
        if found:
            save_sessions(sessions)
            if db_pool:
                try:
                    from app.services.pg_data_helpers import upsert_session_pg
                    await upsert_session_pg(db_pool, found)
                except Exception as e:
                    logger.warning("session_negotiation_bridge: PG upsert failed: %s", e)
            # Mirror classic booking_status_update to client
            client_id = found.get("client_id") or ""
            await _send(
                connected_clients.get(client_id),
                {
                    "type": "booking_status_update",
                    "session": found,
                    "status": found.get("status"),
                },
            )

    await dispatch_notifies(
        result,
        connected_clients=connected_clients,
        connected_coaches=connected_coaches,
        primary_ws=primary_ws,
        primary_role=primary_role,
    )
    return {"session": found, "action": action}


async def after_pending_booking(
    db_pool: Any,
    session: Dict[str, Any],
    *,
    connected_clients: Dict[str, Any],
    connected_coaches: Dict[str, Any],
) -> None:
    from app.services.session_negotiation_service import (
        negotiation_enabled,
        open_from_pending_session,
    )

    if not negotiation_enabled():
        return
    result = await open_from_pending_session(db_pool, session)
    if not result.get("ok"):
        return
    await dispatch_notifies(
        result,
        connected_clients=connected_clients,
        connected_coaches=connected_coaches,
    )
    # QUANTUM-CRYSTAL-ARCH: email + SMS + mailto for coach (slot-engine alts on busy/alt)
    try:
        from app.services.session_negotiation_notify import send_coach_negotiation_notify

        channels = await send_coach_negotiation_notify(
            db_pool, result.get("negotiation") or {}, session
        )
        logger.info(
            "session_negotiation_bridge: coach notify email=%s sms=%s",
            channels.get("email"),
            channels.get("sms"),
        )
    except Exception as e:
        logger.warning("session_negotiation_bridge: coach channel notify failed: %s", e)


async def handle_ws(
    t: str,
    d: Dict[str, Any],
    profile: Dict[str, Any],
    websocket: Any,
    *,
    db_pool: Any,
    connected_clients: Dict[str, Any],
    connected_coaches: Dict[str, Any],
    load_sessions: Callable[[], List[Dict[str, Any]]],
    save_sessions: Callable[[List[Dict[str, Any]]], None],
) -> bool:
    """
    Handle coach_negotiation_decide / client_negotiation_respond.
    Returns True if message was consumed.
    """
    from app.services.session_negotiation_service import (
        coach_decide,
        client_respond,
        negotiation_enabled,
    )

    if not negotiation_enabled() or not profile or not db_pool:
        return False

    role = (profile.get("role") or "").upper()
    hw = (profile.get("hardware_id") or "").strip()

    if t == "coach_negotiation_decide" and role == "COACH":
        result = await coach_decide(
            db_pool,
            coach_id=hw,
            session_id=(d.get("session_id") or "").strip() or None,
            negotiation_id=(d.get("negotiation_id") or "").strip() or None,
            decision=(d.get("decision") or "").strip(),
            alt_slots=d.get("alt_slots"),
            note=(d.get("note") or d.get("reason") or "")[:2000],
        )
        if not result.get("ok"):
            await _send(websocket, {"type": "error", "message": result.get("error", "NEGOTIATION_FAILED")})
            return True
        await apply_bridge_action(
            result,
            load_sessions=load_sessions,
            save_sessions=save_sessions,
            db_pool=db_pool,
            connected_clients=connected_clients,
            connected_coaches=connected_coaches,
            primary_ws=websocket,
            primary_role="COACH",
        )
        await _send(websocket, {"type": "session_negotiation_update", "negotiation": result.get("negotiation"), "ok": True})
        return True

    if t == "client_negotiation_respond" and role == "CLIENT":
        result = await client_respond(
            db_pool,
            client_id=hw,
            session_id=(d.get("session_id") or "").strip() or None,
            negotiation_id=(d.get("negotiation_id") or "").strip() or None,
            decision=(d.get("decision") or "").strip(),
            chosen_start=(d.get("chosen_start") or d.get("slot_start") or None),
            note=(d.get("note") or "")[:2000],
        )
        if not result.get("ok"):
            await _send(websocket, {"type": "error", "message": result.get("error", "NEGOTIATION_FAILED")})
            return True
        await apply_bridge_action(
            result,
            load_sessions=load_sessions,
            save_sessions=save_sessions,
            db_pool=db_pool,
            connected_clients=connected_clients,
            connected_coaches=connected_coaches,
            primary_ws=websocket,
            primary_role="CLIENT",
        )
        await _send(websocket, {"type": "session_negotiation_update", "negotiation": result.get("negotiation"), "ok": True})
        return True

    return False


def handle_redis_fanout(
    raw_data: str,
    *,
    connected_clients: Dict[str, Any],
    connected_coaches: Dict[str, Any],
    load_sessions: Callable[[], List[Dict[str, Any]]],
    save_sessions: Callable[[List[Dict[str, Any]]], None],
) -> None:
    """
    QUANTUM-CRYSTAL-ARCH: Sync path for Redis nate:session_negotiation.
    Mutates bridge sessions.json and pushes WS (thread-safe via call_soon_threadsafe).
    """
    import asyncio

    try:
        data = json.loads(raw_data)
    except Exception as e:
        logger.warning("session_negotiation_bridge: fanout JSON bad: %s", e)
        return

    sess = data.get("session")
    if isinstance(sess, dict) and sess.get("session_id"):
        try:
            sessions = load_sessions() or []
            sid = sess["session_id"]
            replaced = False
            for i, s in enumerate(sessions):
                if s.get("session_id") == sid:
                    sessions[i] = {**s, **sess}
                    replaced = True
                    break
            if not replaced:
                sessions.append(sess)
            save_sessions(sessions)
        except Exception as e:
            logger.warning("session_negotiation_bridge: fanout sessions write failed: %s", e)

    def _push(hw: str, payload: dict) -> None:
        if not hw or not payload:
            return
        ws = connected_clients.get(hw) or connected_coaches.get(hw)
        if not ws:
            return
        msg = json.dumps(payload)
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(lambda: loop.create_task(ws.send(msg)))
        except RuntimeError:
            pass

    client_id = data.get("client_id") or ""
    coach_id = data.get("coach_id") or ""
    if data.get("booking_status_update"):
        _push(client_id, data["booking_status_update"])
    if data.get("client_notify"):
        _push(client_id, data["client_notify"])
    if data.get("coach_notify"):
        _push(coach_id, data["coach_notify"])
    if data.get("session_negotiation_update"):
        _push(client_id, data["session_negotiation_update"])
        _push(coach_id, data["session_negotiation_update"])
    logger.info(
        "session_negotiation_bridge: fanout client=%s coach=%s",
        (client_id[:8] if client_id else "-"),
        (coach_id[:8] if coach_id else "-"),
    )


async def try_chat_hooks(
    profile: Dict[str, Any],
    text: str,
    websocket: Any,
    *,
    db_pool: Any,
    connected_clients: Dict[str, Any],
    connected_coaches: Dict[str, Any],
    load_sessions: Callable[[], List[Dict[str, Any]]],
    save_sessions: Callable[[List[Dict[str, Any]]], None],
) -> bool:
    """Coach/client nate_query short-circuit for open negotiations."""
    from app.services.session_negotiation_service import (
        handle_client_chat_turn,
        handle_coach_chat_turn,
        negotiation_enabled,
    )

    if not negotiation_enabled() or not profile or not db_pool or not text:
        return False
    role = (profile.get("role") or "").upper()
    hw = (profile.get("hardware_id") or "").strip()
    if role == "COACH":
        result = await handle_coach_chat_turn(db_pool, hw, text)
    elif role == "CLIENT":
        result = await handle_client_chat_turn(db_pool, hw, text)
    else:
        return False
    if not result.get("handled"):
        return False
    await apply_bridge_action(
        result,
        load_sessions=load_sessions,
        save_sessions=save_sessions,
        db_pool=db_pool,
        connected_clients=connected_clients,
        connected_coaches=connected_coaches,
        primary_ws=websocket,
        primary_role=role,
    )
    return True
