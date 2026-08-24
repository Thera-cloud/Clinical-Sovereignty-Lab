"""
Client Data API — REST endpoints for client sub-screens.
Replaces WebSocket-based data fetching that fails on mobile Safari.
Covers: Memory Search, Family Members, Coach Info.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import get_current_user_id
from app.services.api_server import get_current_user as _require_auth

logger = logging.getLogger("client_data_api")

router = APIRouter(prefix="/api/client", tags=["client_data"], dependencies=[Depends(_require_auth)])

_DATA_ROOT = Path(os.environ.get("DATA_DIR", "/app/data"))
_VAULT_ROOT = _DATA_ROOT / "Vaults"


def _memory_path(hw_id: str, role: str = "CLIENT") -> Path:
    folder = "Clients"
    if role == "COACH":
        folder = "Coaches"
    elif role == "ADMIN":
        folder = "Admin"
    return _VAULT_ROOT / folder / hw_id / "memory.json"


def _verify_ownership(hw_id: str, user: dict):
    caller_hw = user.get("hardware_id", "")
    caller_role = user.get("role", "")
    if caller_role == "ADMIN":
        return
    if caller_hw == hw_id:
        return
    if caller_role == "COACH":
        return
    raise HTTPException(403, "Access denied")

@router.get("/memory/search/{hw_id}")
async def memory_search(
    hw_id: str,
    q: str = "",
    limit: int = 30,
    request: Request = None,
    _user: dict = Depends(_require_auth),
):
    """
    Search a client's conversation memory by keyword.
    PG-first: uses conversation_history FTS index.
    Falls back to memory.json if db_pool is unavailable.
    """
    _verify_ownership(hw_id, _user)
    query = q.strip()
    if not query:
        return {"query": "", "total_matches": 0, "results": []}

    limit = min(limit, 50)

    db_pool = getattr(request.app.state, "db_pool", None) if request else None
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                user_row = await conn.fetchrow(
                    "SELECT username FROM users WHERE hardware_id = $1 AND deleted_at IS NULL",
                    hw_id,
                )
                if not user_row:
                    return {"query": query, "total_matches": 0, "results": []}
                username = user_row["username"]

                rows = await conn.fetch(
                    """SELECT session_id, user_text, ai_text, created_at
                       FROM conversation_history
                       WHERE user_id = $1
                         AND to_tsvector('english', user_text || ' ' || ai_text)
                             @@ plainto_tsquery('english', $2)
                       ORDER BY created_at DESC
                       LIMIT $3""",
                    username, query, limit,
                )

            results = []
            for r in rows:
                ts = r["created_at"].isoformat() if r["created_at"] else ""
                user_raw = r["user_text"] or ""
                ai_raw = r["ai_text"] or ""
                results.append({
                    "timestamp": ts,
                    "session_id": r["session_id"],
                    "session_date": ts[:10] if ts else "",
                    "user_preview": user_raw[:200] + ("..." if len(user_raw) > 200 else ""),
                    "ai_preview": ai_raw[:200] + ("..." if len(ai_raw) > 200 else ""),
                    "user_full": user_raw,
                    "ai_full": ai_raw,
                })

            return {"query": query, "total_matches": len(results), "results": results}
        except Exception as e:
            logger.warning("memory_search PG failed, falling back to JSON: %s", e)

    return _search_memory_json(hw_id, query, limit)


def _search_memory_json(hw_id: str, query: str, limit: int) -> dict:
    """Fallback: search memory.json flat file."""
    mem_path = _memory_path(hw_id)
    if not mem_path.exists():
        return {"query": query, "total_matches": 0, "results": []}

    try:
        raw = mem_path.read_text()
        all_entries = json.loads(raw) if raw.strip() else []
    except Exception:
        return {"query": query, "total_matches": 0, "results": []}

    query_lower = query.lower()
    matches = []
    for entry in all_entries:
        user_text = (entry.get("user") or "").lower()
        ai_text = (entry.get("ai") or "").lower()
        if query_lower in user_text or query_lower in ai_text:
            user_raw = entry.get("user", "")
            ai_raw = entry.get("ai", "")
            ts = entry.get("timestamp", "")
            matches.append({
                "timestamp": ts,
                "session_id": entry.get("session_id"),
                "session_date": ts[:10] if ts else "",
                "user_preview": user_raw[:200] + ("..." if len(user_raw) > 200 else ""),
                "ai_preview": ai_raw[:200] + ("..." if len(ai_raw) > 200 else ""),
                "user_full": user_raw,
                "ai_full": ai_raw,
            })

    matches.reverse()
    return {"query": query, "total_matches": len(matches), "results": matches[:limit]}


@router.get("/memory/sessions/{hw_id}")
async def memory_sessions(
    hw_id: str,
    request: Request = None,
    _user: dict = Depends(_require_auth),
):
    """
    Return memory entries grouped by session/date as story chapters.
    PG-first: uses conversation_history table.
    Falls back to memory.json if db_pool is unavailable.
    """
    _verify_ownership(hw_id, _user)
    db_pool = getattr(request.app.state, "db_pool", None) if request else None
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                user_row = await conn.fetchrow(
                    "SELECT username FROM users WHERE hardware_id = $1 AND deleted_at IS NULL",
                    hw_id,
                )
                if not user_row:
                    return {"sessions": [], "total_sessions": 0}
                username = user_row["username"]

                rows = await conn.fetch(
                    """SELECT session_id, user_text, ai_text, created_at
                       FROM conversation_history
                       WHERE user_id = $1
                       ORDER BY created_at ASC""",
                    username,
                )

            from collections import OrderedDict
            sessions: OrderedDict = OrderedDict()
            for r in rows:
                ts = r["created_at"].isoformat() if r["created_at"] else ""
                key = r["session_id"] or ts[:10]
                if not key:
                    key = "unknown"
                if key not in sessions:
                    sessions[key] = []
                sessions[key].append({
                    "timestamp": ts,
                    "user": r["user_text"] or "",
                    "ai": r["ai_text"] or "",
                })

            result = []
            for key, entries in sessions.items():
                first_ts = entries[0]["timestamp"] if entries else ""
                last_ts = entries[-1]["timestamp"] if entries else ""
                first_user = (entries[0]["user"] or "")[:120]
                result.append({
                    "session_key": key,
                    "date": first_ts[:10] if first_ts else key,
                    "first_timestamp": first_ts,
                    "last_timestamp": last_ts,
                    "entry_count": len(entries),
                    "preview": first_user + ("..." if len(first_user) >= 120 else ""),
                    "entries": entries,
                })

            result.reverse()
            return {"sessions": result, "total_sessions": len(result)}
        except Exception as e:
            logger.warning("memory_sessions PG failed, falling back to JSON: %s", e)

    return _sessions_from_json(hw_id)


def _sessions_from_json(hw_id: str) -> dict:
    """Fallback: read sessions from memory.json flat file."""
    mem_path = _memory_path(hw_id)
    if not mem_path.exists():
        return {"sessions": [], "total_sessions": 0}

    try:
        raw = mem_path.read_text()
        all_entries = json.loads(raw) if raw.strip() else []
    except Exception:
        return {"sessions": [], "total_sessions": 0}

    from collections import OrderedDict
    sessions: OrderedDict = OrderedDict()
    for entry in all_entries:
        key = entry.get("session_id") or entry.get("timestamp", "")[:10]
        if not key:
            key = "unknown"
        if key not in sessions:
            sessions[key] = []
        sessions[key].append(entry)

    result = []
    for key, entries in sessions.items():
        first_ts = entries[0].get("timestamp", "") if entries else ""
        last_ts = entries[-1].get("timestamp", "") if entries else ""
        first_user = (entries[0].get("user", "") or "")[:120] if entries else ""
        result.append({
            "session_key": key,
            "date": first_ts[:10] if first_ts else key,
            "first_timestamp": first_ts,
            "last_timestamp": last_ts,
            "entry_count": len(entries),
            "preview": first_user + ("..." if len(first_user) >= 120 else ""),
            "entries": [
                {
                    "timestamp": e.get("timestamp", ""),
                    "user": e.get("user", ""),
                    "ai": e.get("ai", ""),
                }
                for e in entries
            ],
        })

    result.reverse()
    return {"sessions": result, "total_sessions": len(result)}


@router.get("/family/members/{hw_id}")
async def get_family_members(
    hw_id: str,
    request: Request = None,
    _user: dict = Depends(_require_auth),
):
    """
    Get family members and pending invites for a client's family.
    PG-first: queries the users table for family_id match.
    Falls back to JSON registry if db_pool is unavailable.
    Excludes ADMIN-role accounts from the member list.
    """
    _verify_ownership(hw_id, _user)
    db_pool = getattr(request.app.state, "db_pool", None) if request else None
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                target = await conn.fetchrow(
                    "SELECT family_id, profile_data FROM users "
                    "WHERE hardware_id = $1 AND deleted_at IS NULL",
                    hw_id,
                )
                if not target or not target["family_id"]:
                    return {"family_id": None, "members": [], "pending_invites": []}

                family_id = str(target["family_id"])
                members_rows = await conn.fetch(
                    "SELECT hardware_id, role, profile_data FROM users "
                    "WHERE family_id = $1 AND deleted_at IS NULL AND role != 'ADMIN'",
                    target["family_id"],
                )
                members = []
                for r in members_rows:
                    pd = r["profile_data"] or {}
                    if isinstance(pd, str):
                        try:
                            pd = json.loads(pd)
                        except Exception:
                            pd = {}
                    members.append({
                        "id": r["hardware_id"],
                        "name": pd.get("name"),
                        "email": pd.get("email", ""),
                        "phone": pd.get("phone", ""),
                        "role": r["role"],
                        "family_role": pd.get("family_role", ""),
                        "tier": pd.get("tier"),
                        "is_minor": pd.get("is_minor", False),
                        "guardian_id": pd.get("guardian_id", ""),
                    })

                # Pending invites still come from JSON registry (no PG table for invites)
                pending_invites = []
                registry = _load_registry()
                for token, invite in registry.get("_family_invites", {}).items():
                    if invite.get("family_id") == family_id:
                        pending_invites.append({
                            "token": token,
                            "name": invite.get("invitee_name", ""),
                            "contact": invite.get("invitee_contact", ""),
                            "role": invite.get("role", ""),
                            "status": "pending",
                            "created_at": invite.get("created_at", ""),
                        })

                return {
                    "family_id": family_id,
                    "members": members,
                    "pending_invites": pending_invites,
                }
        except Exception as e:
            logger.warning("get_family_members PG lookup failed, falling back to JSON: %s", e)

    # JSON fallback
    registry = _load_registry()
    if not registry:
        return {"family_id": None, "members": [], "pending_invites": []}

    target_profile = None
    for k, v in registry.items():
        if k.startswith("_"):
            continue
        p = v.get("profile", {})
        if p.get("hardware_id") == hw_id:
            target_profile = p
            break

    if not target_profile:
        return {"family_id": None, "members": [], "pending_invites": []}

    family_id = target_profile.get("family_id")
    if not family_id:
        return {"family_id": None, "members": [], "pending_invites": []}

    members = []
    for k, v in registry.items():
        if k.startswith("_"):
            continue
        p = v.get("profile", {})
        if p.get("family_id") == family_id and p.get("role") != "ADMIN":
            members.append({
                "id": p.get("hardware_id"),
                "name": p.get("name"),
                "email": p.get("email", ""),
                "phone": p.get("phone", ""),
                "role": p.get("role"),
                "family_role": p.get("family_role", ""),
                "tier": p.get("tier"),
                "is_minor": p.get("is_minor", False),
                "guardian_id": p.get("guardian_id", ""),
            })

    pending_invites = []
    for token, invite in registry.get("_family_invites", {}).items():
        if invite.get("family_id") == family_id:
            pending_invites.append({
                "token": token,
                "name": invite.get("invitee_name", ""),
                "contact": invite.get("invitee_contact", ""),
                "role": invite.get("role", ""),
                "status": "pending",
                "created_at": invite.get("created_at", ""),
            })

    return {
        "family_id": family_id,
        "members": members,
        "pending_invites": pending_invites,
    }


@router.get("/coach-info/{coach_id}")
async def get_coach_info(
    coach_id: str,
    request: Request = None,
):
    """
    Get basic info about an assigned coach (name, email, specializations).
    PG-first: queries the users table by hardware_id + role=COACH.
    Falls back to JSON registry if db_pool is unavailable.
    """
    if not coach_id or coach_id.strip() == "":
        return {"coach_id": "", "coach_name": "Not Assigned", "specializations": []}

    db_pool = getattr(request.app.state, "db_pool", None) if request else None
    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT profile_data FROM users "
                    "WHERE hardware_id = $1 AND role = 'COACH' AND deleted_at IS NULL",
                    coach_id,
                )
                if row:
                    pd = row["profile_data"] or {}
                    if isinstance(pd, str):
                        try:
                            pd = json.loads(pd)
                        except Exception:
                            pd = {}
                    return {
                        "coach_id": coach_id,
                        "coach_name": pd.get("name") or pd.get("display_name") or "Coach",
                        "coach_email": pd.get("email") or "",
                        "specializations": pd.get("specializations") or [],
                        "coaching_fee": pd.get("coaching_fee") or 0,
                        "zoom_link": pd.get("zoom_link") or "",
                    }
        except Exception as e:
            logger.warning("get_coach_info PG lookup failed, falling back to JSON: %s", e)

    # JSON fallback
    registry = _load_registry()
    coach_name = "Coach"
    coach_email = ""
    specializations = []
    coaching_fee = 0
    zoom_link = ""

    for _k, v in registry.items():
        if _k.startswith("_"):
            continue
        p = v.get("profile", {})
        if p.get("hardware_id") == coach_id and p.get("role") == "COACH":
            coach_name = p.get("name") or p.get("display_name") or "Coach"
            coach_email = p.get("email") or ""
            specializations = p.get("specializations") or []
            coaching_fee = p.get("coaching_fee") or 0
            zoom_link = p.get("zoom_link") or ""
            break

    return {
        "coach_id": coach_id,
        "coach_name": coach_name,
        "coach_email": coach_email,
        "specializations": specializations,
        "coaching_fee": coaching_fee,
        "zoom_link": zoom_link,
    }


@router.post("/ai-consent")
async def store_ai_consent(request: Request, user=Depends(_require_auth)):
    """Store AI data processing consent timestamp in the user's profile."""
    body = await request.json()
    consent_ts = body.get("ai_consent_granted_at")
    if not consent_ts:
        raise HTTPException(400, "ai_consent_granted_at required")

    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        return {"status": "stored_locally_only"}

    username = user.get("username", "") if isinstance(user, dict) else str(user)
    if not username:
        raise HTTPException(400, "Could not resolve username")

    try:
        await db_pool.execute(
            """
            UPDATE users SET profile_data = jsonb_set(
                COALESCE(profile_data, '{}'::jsonb),
                '{ai_consent_granted_at}',
                to_jsonb($1::text)
            )
            WHERE username = $2
            """,
            consent_ts, username,
        )
    except Exception as e:
        logger.warning("ai-consent write failed for %s: %s", username, e)
        raise HTTPException(500, "Failed to store consent")

    return {"status": "ok", "ai_consent_granted_at": consent_ts}


@router.get("/proactive-presence-consent")
async def get_proactive_presence_consent(request: Request, user=Depends(_require_auth)):
    """QUANTUM-CRYSTAL-ARCH: Read proactive presence opt-in (Agentic Phase 0)."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    identity = ""
    if isinstance(user, dict):
        identity = (user.get("hardware_id") or user.get("username") or "").strip()
    if not identity:
        raise HTTPException(400, "identity missing")
    from app.services.nate_commitment_service import get_proactive_consent

    return await get_proactive_consent(db_pool, identity)


@router.put("/proactive-presence-consent")
async def put_proactive_presence_consent(request: Request, user=Depends(_require_auth)):
    """QUANTUM-CRYSTAL-ARCH: Persist proactive presence opt-in via REST (Safari-safe)."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    if not isinstance(user, dict) or (user.get("role") or "").upper() != "CLIENT":
        raise HTTPException(403, "Clients only")
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    if "enabled" not in body:
        raise HTTPException(400, "enabled field required")
    enabled = bool(body.get("enabled"))
    identity = (user.get("hardware_id") or user.get("username") or "").strip()
    if not identity:
        raise HTTPException(400, "identity missing")
    from app.services.nate_commitment_service import update_proactive_consent

    result = await update_proactive_consent(db_pool, hardware_id=identity, enabled=enabled)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "persist_failed")
    return result


# ── Slice 0: Client self-serve voice biometrics opt-out (IL BIPA §15(b)) ──
@router.get("/biometrics-opt-out")
async def get_client_biometrics_opt_out(request: Request, user=Depends(_require_auth)):
    """Return the caller's current voice biometrics opt-out state."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    username = (user.get("username") or "").strip() if isinstance(user, dict) else ""
    if not username:
        raise HTTPException(400, "identity missing")
    from app.services.biometrics_consent import get_biometrics_status

    current = await get_biometrics_status(username, db_pool)
    if current is None:
        raise HTTPException(404, "user not found")
    return {"username": username, "biometrics_disabled": bool(current)}


@router.put("/biometrics-opt-out")
async def put_client_biometrics_opt_out(request: Request, user=Depends(_require_auth)):
    """Client self-toggle for voice biometrics extraction (BAA §6.3 disable control)."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    username = (user.get("username") or "").strip() if isinstance(user, dict) else ""
    if not username:
        raise HTTPException(400, "identity missing")
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    if "disabled" not in body:
        raise HTTPException(400, "disabled field required")
    disabled = bool(body.get("disabled"))
    reason = (body.get("reason") or None)
    from app.services.biometrics_consent import set_biometrics_opt_out, get_biometrics_status

    ok = await set_biometrics_opt_out(
        username=username,
        disabled=disabled,
        actor=username,
        reason=reason,
        db_pool=db_pool,
    )
    if not ok:
        raise HTTPException(500, "update failed")
    current = await get_biometrics_status(username, db_pool)
    return {"status": "ok", "username": username, "biometrics_disabled": bool(current)}


# ── Slice 1: Retention tombstones — Flutter local-cache sync ──────────
@router.get("/data-tombstones")
async def get_data_tombstones(
    request: Request,
    since: Optional[str] = None,
    limit: int = 500,
    user=Depends(_require_auth),
):
    """Return tombstones for the caller since a timestamp.

    Consumed by the Flutter client on reconnect (see
    `device-history-sync-on-login.mdc`) so the local SQLite/hive cache
    can drop rows that the server has deleted under the retention
    policy or R2 archive path.

    `since` is an ISO 8601 timestamp. Omit for the last 30 days.
    `limit` is capped at 5000 to keep response size bounded.
    """
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(503, "Database unavailable")
    username = (user.get("username") or "").strip() if isinstance(user, dict) else ""
    hw_id = (user.get("hardware_id") or "").strip() if isinstance(user, dict) else ""
    identities = [i for i in dict.fromkeys([username, hw_id]) if i]
    if not identities:
        raise HTTPException(400, "identity missing")

    limit = max(1, min(int(limit or 500), 5000))
    from datetime import datetime, timedelta, timezone as _tz

    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except Exception:
            raise HTTPException(400, "invalid since timestamp")
    else:
        since_dt = datetime.now(_tz.utc) - timedelta(days=30)

    try:
        rows = await db_pool.fetch(
            """
            SELECT id, table_name, row_id, reason, tombstoned_at
            FROM data_tombstones
            WHERE user_id = ANY($1::text[]) AND tombstoned_at > $2
            ORDER BY tombstoned_at ASC
            LIMIT $3
            """,
            identities,
            since_dt,
            limit,
        )
    except Exception as exc:
        logger.warning("data-tombstones query failed for %s: %s", username, exc)
        return {"username": username, "since": since_dt.isoformat(), "tombstones": []}

    return {
        "username": username,
        "since": since_dt.isoformat(),
        "count": len(rows),
        "tombstones": [
            {
                "id": r["id"],
                "table": r["table_name"],
                "row_id": r["row_id"],
                "reason": r["reason"],
                "tombstoned_at": r["tombstoned_at"].isoformat()
                if r.get("tombstoned_at")
                else None,
            }
            for r in rows
        ],
    }


@router.get("/health-check")
async def client_health_check(request: Request, user=Depends(_require_auth)):
    """Enhanced health check that includes ai_consent_granted_at for consent gate."""
    db_pool = getattr(request.app.state, "db_pool", None)
    username = user.get("username", "") if isinstance(user, dict) else str(user)

    result = {
        "vault_ready": True,
        "memory_ready": True,
        "needs_backfill": False,
        "server_entry_count": 0,
        "last_server_entry_at": None,
        "ai_consent_granted_at": None,
        "timezone": "UTC",
        "timezone_source": "default_utc",
        "proactive_presence_consent": False,
        "proactive_presence_consent_key_set": False,
    }

    if db_pool and username:
        try:
            row = await db_pool.fetchrow(
                """SELECT profile_data->>'ai_consent_granted_at' as consent,
                          profile_data ? 'proactive_presence_consent' as presence_key_set,
                          COALESCE((profile_data->>'proactive_presence_consent')::boolean, false)
                              as presence_consent,
                          timezone,
                          timezone_source
                   FROM users WHERE username = $1""",
                username,
            )
            if row and row["consent"]:
                result["ai_consent_granted_at"] = row["consent"]
            if row:
                result["timezone"] = row["timezone"] or "UTC"
                result["timezone_source"] = row["timezone_source"] or "default_utc"
                result["proactive_presence_consent"] = bool(row["presence_consent"])
                result["proactive_presence_consent_key_set"] = bool(row["presence_key_set"])
        except Exception as e:
            logger.warning("health-check consent lookup failed: %s", e)

        try:
            ch_row = await db_pool.fetchrow(
                "SELECT COUNT(*) as cnt, MAX(created_at) as last_at "
                "FROM conversation_history WHERE user_id = $1",
                username,
            )
            if ch_row:
                result["server_entry_count"] = ch_row["cnt"] or 0
                if ch_row["last_at"]:
                    result["last_server_entry_at"] = ch_row["last_at"].isoformat()
        except Exception as e:
            logger.warning("health-check conversation count failed: %s", e)

    return result


@router.patch("/timezone")
async def patch_client_timezone(request: Request, payload: dict, user=Depends(_require_auth)):
    """Persist IANA timezone (user_explicit). Bridge/WebSocket profile stays in sync via PG columns + registry reload."""
    tz_string = (payload.get("timezone") or "").strip()
    if not tz_string:
        raise HTTPException(status_code=400, detail="timezone field required")
    try:
        ZoneInfo(tz_string)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid IANA timezone: {tz_string}")
    db_pool = getattr(request.app.state, "db_pool", None)
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database unavailable")
    uname = user.get("username") if isinstance(user, dict) else None
    if not uname:
        raise HTTPException(status_code=400, detail="username missing")
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE users
            SET timezone = $1,
                timezone_source = 'user_explicit',
                timezone_updated_at = NOW(),
                profile_data = jsonb_set(
                    jsonb_set(
                        COALESCE(profile_data, '{}'::jsonb),
                        '{timezone}',
                        to_jsonb($1::text),
                        true
                    ),
                    '{timezone_source}',
                    to_jsonb('user_explicit'::text),
                    true
                )
            WHERE username = $2 AND (deleted_at IS NULL)
            """,
            tz_string,
            uname,
        )
    try:
        from app.services.api_server import _get_auth_redis

        r = await _get_auth_redis()
        if r:
            await r.publish("nate:user_reload", json.dumps({"username": uname}))
    except Exception as e:
        logger.warning("timezone PATCH user_reload publish failed for %s: %s", uname, e)
    return {"timezone": tz_string, "source": "user_explicit"}


def _load_registry() -> dict:
    """Load user registry from JSON backup. Matches bridge load_registry()."""
    paths = [
        _DATA_ROOT / "bridge" / "user_registry.json",
        _DATA_ROOT / "user_registry.json",
        Path("/app/data/user_registry.json"),
    ]
    for p in paths:
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                continue
    return {}
