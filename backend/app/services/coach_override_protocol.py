"""
Coach Override Protocol — validation, TTL, and audit logging for coach_client_overrides.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

ALLOWED_FOCUS_DOMAINS = frozenset(
    {
        "clinical",
        "coaching",
        "family_systems",
        "crisis",
        "mindfulness",
        "boundaries",
        "trauma_informed",
        "attachment",
        "general",
        "cbt_techniques",
        "motivational",
    }
)

PACING_EXPIRY_DAYS = 30
FOCUS_EXPIRY_DAYS = 14


def _norm_pacing(v: Any) -> str:
    p = (str(v or "normal")).strip().lower()
    return p if p in ("slow", "normal", "fast") else "normal"


def merge_override_payload(prev: Optional[Dict[str, Any]], d: Dict[str, Any]) -> Dict[str, Any]:
    prev = prev or {}
    out: Dict[str, Any] = {
        "focus_domain": d["focus_domain"] if "focus_domain" in d else prev.get("focus_domain"),
        "pacing": d["pacing"] if "pacing" in d else prev.get("pacing") or "normal",
        "clinical_hold": bool(d["clinical_hold"])
        if "clinical_hold" in d
        else bool(prev.get("clinical_hold")),
        "mission_priority": d["mission_priority"]
        if "mission_priority" in d
        else prev.get("mission_priority"),
        "notes": d["notes"] if "notes" in d else prev.get("notes"),
    }
    out["pacing"] = _norm_pacing(out["pacing"])
    fd = out["focus_domain"]
    if fd is not None and isinstance(fd, str) and not fd.strip():
        out["focus_domain"] = None
    elif isinstance(fd, str):
        out["focus_domain"] = fd.strip()
    mp = out["mission_priority"]
    if mp is not None and isinstance(mp, str) and not mp.strip():
        out["mission_priority"] = None
    elif isinstance(mp, str):
        out["mission_priority"] = mp.strip()
    return out


def compute_expiry_columns(
    prev: Dict[str, Any],
    merged: Dict[str, Any],
    prev_expires_at: Optional[datetime],
    prev_focus_expires: Optional[datetime],
) -> Tuple[Optional[datetime], Optional[datetime]]:
    now = datetime.now(timezone.utc)
    prev_p = _norm_pacing(prev.get("pacing"))
    new_p = merged["pacing"]
    pacing_exp = prev_expires_at
    focus_exp = prev_focus_expires

    if prev_p != new_p:
        if new_p == "normal":
            pacing_exp = None
        else:
            pacing_exp = now + timedelta(days=PACING_EXPIRY_DAYS)
    prev_f = prev.get("focus_domain")
    new_f = merged.get("focus_domain")
    prev_f_n = (prev_f or None) if not prev_f else prev_f
    new_f_n = (new_f or None) if not new_f else new_f
    if prev_f_n != new_f_n:
        if not new_f_n:
            focus_exp = None
        else:
            focus_exp = now + timedelta(days=FOCUS_EXPIRY_DAYS)

    return pacing_exp, focus_exp


def validate_merged(role: str, prev: Dict[str, Any], merged: Dict[str, Any], reason: str) -> Optional[str]:
    r = (reason or "").strip()
    if len(r) < 1:
        return "override_reason is required"

    if merged.get("clinical_hold") and role not in ("COACH", "ADMIN"):
        return "clinical_hold may only be set by COACH or ADMIN"

    prev_p = _norm_pacing(prev.get("pacing"))
    new_p = merged["pacing"]
    if prev_p == "slow" and new_p == "fast" and len(r) < 20:
        return "Changing pacing from slow to fast requires a reason of at least 20 characters"

    fd = merged.get("focus_domain")
    if fd:
        key = fd.strip().lower()
        if key not in ALLOWED_FOCUS_DOMAINS:
            return "focus_domain is not in the allowed domain list"

    return None


async def mission_reference_valid(conn: asyncpg.Connection, client_user_id: str, ref: str) -> bool:
    ref = (ref or "").strip()
    if not ref:
        return True
    row = await conn.fetchrow(
        """
        SELECT 1 FROM sse_missions
        WHERE user_id = $1 AND mission_id::text = $2
        LIMIT 1
        """,
        client_user_id,
        ref,
    )
    if row:
        return True
    row2 = await conn.fetchrow(
        """
        SELECT 1 FROM sse_quests
        WHERE user_id = $1 AND quest_id::text = $2
        LIMIT 1
        """,
        client_user_id,
        ref,
    )
    return row2 is not None


async def insert_audit_rows(
    conn: asyncpg.Connection,
    coach_user_id: str,
    client_user_id: str,
    prev: Dict[str, Any],
    merged: Dict[str, Any],
    reason: str,
) -> None:
    pairs: List[Tuple[str, Any, Any]] = [
        ("pacing", prev.get("pacing"), merged.get("pacing")),
        ("focus_domain", prev.get("focus_domain"), merged.get("focus_domain")),
        ("clinical_hold", bool(prev.get("clinical_hold")), bool(merged.get("clinical_hold"))),
        ("mission_priority", prev.get("mission_priority"), merged.get("mission_priority")),
    ]
    rsn = (reason or "")[:8000]
    for otype, old, new in pairs:
        if otype == "clinical_hold":
            o_old = "true" if old else "false"
            o_new = "true" if new else "false"
        else:
            o_old = None if old is None else str(old)
            o_new = None if new is None else str(new)
        if o_old == o_new:
            continue
        await conn.execute(
            """
            INSERT INTO coach_override_audit (
                coach_user_id, client_user_id, override_type,
                previous_value, new_value, reason
            ) VALUES ($1, $2, $3, $4, $5, $6)
            """,
            coach_user_id,
            client_user_id,
            otype,
            o_old,
            o_new,
            rsn,
        )


async def insert_clear_audit(
    conn: asyncpg.Connection,
    coach_user_id: str,
    client_user_id: str,
    snapshot: Dict[str, Any],
    reason: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO coach_override_audit (
            coach_user_id, client_user_id, override_type,
            previous_value, new_value, reason
        ) VALUES ($1, $2, 'clear_all', $3, NULL, $4)
        """,
        coach_user_id,
        client_user_id,
        json.dumps(snapshot, default=str)[:20000],
        (reason or "")[:8000],
    )


def filter_active_overrides(row: asyncpg.Record, now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Apply expires_at (pacing) and focus_domain_expires_at; clinical_hold has no expiry.
    """
    if not row:
        return {}
    if now is None:
        now = datetime.now(timezone.utc)
    d = dict(row)
    out: Dict[str, Any] = {}

    exp = d.get("expires_at")
    p_ok = exp is None or (hasattr(exp, "replace") and exp > now)
    pacing_val = d.get("pacing") or "normal"
    if p_ok and pacing_val and pacing_val != "normal":
        out["pacing"] = pacing_val

    fe = d.get("focus_domain_expires_at")
    f_ok = fe is None or (hasattr(fe, "replace") and fe > now)
    if f_ok and d.get("focus_domain"):
        out["focus_domain"] = d["focus_domain"]

    if d.get("clinical_hold"):
        out["clinical_hold"] = True

    if d.get("mission_priority"):
        out["mission_priority"] = d["mission_priority"]

    if d.get("notes"):
        out["notes"] = d["notes"]

    u = d.get("updated_at")
    out["updated_at"] = u.isoformat() if u and hasattr(u, "isoformat") else str(u) if u else None
    out["expires_at"] = exp.isoformat() if exp and hasattr(exp, "isoformat") else None
    out["focus_domain_expires_at"] = (
        fe.isoformat() if fe and hasattr(fe, "isoformat") else None
    )
    return out
