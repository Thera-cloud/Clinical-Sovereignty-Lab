"""Roster-level coach practice snapshot (healing / cycles / LN / live).

QUANTUM-CRYSTAL-ARCH — UI may include display names for hover; print must not.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

WINDOWS = (30, 90, 180)


def _clamp_days(days: int) -> int:
    if days in WINDOWS:
        return days
    if days <= 45:
        return 30
    if days <= 135:
        return 90
    return 180


async def resolve_coach_ids(conn, ident: str) -> Optional[Dict[str, str]]:
    row = await conn.fetchrow(
        """SELECT username, hardware_id, id::text AS uuid,
                  COALESCE(profile_data->>'name', username) AS display_name
           FROM users
           WHERE role = 'COACH'
             AND (username = $1 OR hardware_id = $1 OR id::text = $1)
             AND deleted_at IS NULL
           LIMIT 1""",
        ident,
    )
    if not row:
        return None
    return {
        "username": row["username"],
        "hardware_id": row["hardware_id"],
        "uuid": row["uuid"],
        "display_name": row["display_name"] or row["username"],
    }


async def resolve_master_for(conn, assistant_hw: str) -> Optional[Dict[str, str]]:
    row = await conn.fetchrow(
        """SELECT u.username, u.hardware_id,
                  COALESCE(u.profile_data->>'name', u.username) AS display_name
           FROM coach_hierarchy ch
           JOIN users u ON u.hardware_id = ch.master_coach_id
           WHERE ch.assistant_id = $1
             AND ch.status IN ('active', 'accepted')
           ORDER BY ch.accepted_at DESC NULLS LAST
           LIMIT 1""",
        assistant_hw,
    )
    if not row:
        return None
    return {
        "username": row["username"],
        "hardware_id": row["hardware_id"],
        "display_name": row["display_name"] or row["username"],
    }


async def roster_clients(conn, coach_hw: str, coach_username: str) -> List[Dict[str, str]]:
    rows = await conn.fetch(
        """SELECT username, hardware_id,
                  COALESCE(profile_data->>'name', username) AS display_name
           FROM users
           WHERE role = 'CLIENT'
             AND (profile_data->>'coach_id' = $1
                  OR profile_data->>'assigned_coach_id' = $1
                  OR profile_data->>'assigned_coach' = $2)""",
        coach_hw,
        coach_username,
    )
    return [
        {
            "username": r["username"],
            "hardware_id": r["hardware_id"],
            "display_name": r["display_name"] or r["username"],
        }
        for r in rows
    ]


async def build_snapshot(
    db_pool,
    *,
    coach_ident: str,
    days: int = 90,
    include_names: bool = True,
) -> Dict[str, Any]:
    days = _clamp_days(days)
    empty = {
        "window_days": days,
        "coach": {},
        "master": None,
        "client_count": 0,
        "series": [],
        "scatter": [],
        "totals": {},
        "skills": [],
        "live_influence": {},
    }
    if not db_pool:
        return empty
    async with db_pool.acquire() as conn:
        coach = await resolve_coach_ids(conn, coach_ident)
        if not coach:
            return empty
        master = await resolve_master_for(conn, coach["hardware_id"])
        clients = await roster_clients(conn, coach["hardware_id"], coach["username"])
        usernames = [c["username"] for c in clients]
        hw_ids = [c["hardware_id"] for c in clients]
        name_by_user = {c["username"]: c["display_name"] for c in clients}

        start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
        series, scatter = await _daily_series(
            conn, coach, usernames, hw_ids, name_by_user, start, days, include_names
        )
        skills = await _skill_clusters(conn, coach, start)
        influence = _live_influence(series)
        totals = _totals(series, clients)

    return {
        "window_days": days,
        "coach": {
            "username": coach["username"],
            "display_name": coach["display_name"],
            "hardware_id": coach["hardware_id"],
        },
        "master": master,
        "client_count": len(clients),
        "series": series,
        "scatter": scatter,
        "totals": totals,
        "skills": skills,
        "live_influence": influence,
    }


async def _daily_series(
    conn,
    coach: Dict[str, str],
    usernames: List[str],
    hw_ids: List[str],
    name_by_user: Dict[str, str],
    start: dt.datetime,
    days: int,
    include_names: bool,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    healing_rows = []
    cycle_rows = []
    ln_rows = []
    live_rows = []
    ident_all = list({*usernames, *hw_ids})
    if usernames:
        try:
            healing_rows = await conn.fetch(
                """SELECT username, created_at::date AS d, healing_score::float AS score
                   FROM client_growth_phase_history
                   WHERE username = ANY($1::text[])
                     AND created_at >= $2
                     AND healing_score IS NOT NULL""",
                usernames,
                start,
            )
        except Exception as e:
            logger.debug("practice snapshot healing: %s", e)
        try:
            cycle_rows = await conn.fetch(
                """SELECT user_id, observed_at::date AS d, value
                   FROM cycle_observations
                   WHERE user_id = ANY($1::text[])
                     AND observed_at >= $2
                     AND (phase IN ('low', 'trough', 'dip') OR value < 0.40)""",
                ident_all,
                start,
            )
        except Exception as e:
            logger.debug("practice snapshot cycles: %s", e)
        try:
            ln_rows = await conn.fetch(
                """SELECT user_id, created_at::date AS d, COUNT(*)::int AS n
                   FROM conversation_history
                   WHERE user_id = ANY($1::text[])
                     AND created_at >= $2
                   GROUP BY 1, 2""",
                ident_all,
                start,
            )
        except Exception as e:
            logger.debug("practice snapshot ln: %s", e)
    try:
        live_rows = await conn.fetch(
            """SELECT COALESCE(actual_start, scheduled_start, created_at)::date AS d,
                      client_id, COUNT(*)::int AS n
               FROM coaching_sessions
               WHERE coach_id::text = ANY($1::text[])
                 AND upper(COALESCE(session_type, '')) NOT IN ('MASTER_CONSULTATION', 'CONSULTATION')
                 AND status IN ('completed', 'active')
                 AND COALESCE(actual_start, scheduled_start, created_at) >= $2
               GROUP BY 1, 2""",
            [coach["hardware_id"], coach["uuid"], coach["username"]],
            start,
        )
    except Exception as e:
        logger.debug("practice snapshot live: %s", e)

    by_day_heal: Dict[str, List[float]] = {}
    scatter: List[Dict[str, Any]] = []
    for r in healing_rows:
        d = str(r["d"])
        score = float(r["score"] or 0)
        by_day_heal.setdefault(d, []).append(score)
        point = {
            "date": d,
            "healing": round(score, 4),
            "kind": "healing",
        }
        if include_names:
            point["client"] = name_by_user.get(r["username"], "Client")
        scatter.append(point)

    dips: Dict[str, int] = {}
    for r in cycle_rows:
        d = str(r["d"])
        dips[d] = dips.get(d, 0) + 1
        point = {"date": d, "healing": None, "kind": "cycle_dip"}
        if include_names:
            point["client"] = "Cycle dip"
        scatter.append(point)

    ln_day: Dict[str, int] = {}
    for r in ln_rows:
        d = str(r["d"])
        ln_day[d] = ln_day.get(d, 0) + int(r["n"] or 0)

    live_day: Dict[str, int] = {}
    live_clients: Dict[str, set] = {}
    for r in live_rows:
        d = str(r["d"])
        live_day[d] = live_day.get(d, 0) + int(r["n"] or 0)
        live_clients.setdefault(d, set()).add(str(r["client_id"] or ""))

    series: List[Dict[str, Any]] = []
    for i in range(days):
        day = (start.date() + dt.timedelta(days=i + 1))
        d = day.isoformat()
        scores = by_day_heal.get(d) or []
        mean_h = round(sum(scores) / len(scores), 4) if scores else None
        series.append({
            "date": d,
            "healing_mean": mean_h,
            "cycle_dips": dips.get(d, 0),
            "ln_turns": ln_day.get(d, 0),
            "live_sessions": live_day.get(d, 0),
            "live": live_day.get(d, 0) > 0,
        })
        if live_day.get(d, 0) and include_names:
            scatter.append({
                "date": d,
                "healing": mean_h,
                "kind": "live_session",
                "client": "Live session",
            })
    return series, scatter


async def _skill_clusters(conn, coach: Dict[str, str], start: dt.datetime) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    try:
        rows = await conn.fetch(
            f"""SELECT topics_covered,
                      COALESCE({_safe_cee()}, 0) AS cee
               FROM coaching_sessions
               WHERE coach_id::text = ANY($1::text[])
                 AND status = 'completed'
                 AND COALESCE(actual_end, updated_at, created_at) >= $2""",
            [coach["hardware_id"], coach["uuid"], coach["username"]],
            start,
        )
        for r in rows:
            cee = float(r["cee"] or 0)
            topics = r["topics_covered"]
            if isinstance(topics, str):
                try:
                    import json
                    topics = json.loads(topics)
                except Exception:
                    topics = []
            if not isinstance(topics, list):
                topics = []
            for t in topics:
                label = str(t).strip()
                if not label or len(label) < 3:
                    continue
                weight = 2 if cee >= 0.55 else 1
                counts[label] = counts.get(label, 0) + weight
    except Exception as e:
        logger.debug("practice snapshot skills: %s", e)
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
    return [{"skill": k, "weight": v} for k, v in ranked]


def _safe_cee() -> str:
    return (
        "CASE WHEN COALESCE(TRIM(session_data->>'avg_c_emo'), '') ~ "
        "'^[-+]?[0-9]*\\.?[0-9]+([eE][-+]?[0-9]+)?$' "
        "THEN TRIM(session_data->>'avg_c_emo')::double precision ELSE NULL END"
    )


def _live_influence(series: List[Dict[str, Any]]) -> Dict[str, Any]:
    lifts = []
    for i, row in enumerate(series):
        if not row.get("live"):
            continue
        prior = series[max(0, i - 3):i]
        after = series[i + 1:i + 4]
        if not prior or not after:
            continue
        p = sum(x.get("ln_turns") or 0 for x in prior) / len(prior)
        a = sum(x.get("ln_turns") or 0 for x in after) / len(after)
        if p > 0:
            lifts.append((a - p) / p)
        elif a > 0:
            lifts.append(1.0)
    if not lifts:
        return {"sample": 0, "mean_lift": None, "direction": "flat"}
    mean = sum(lifts) / len(lifts)
    direction = "up" if mean > 0.08 else ("down" if mean < -0.08 else "flat")
    return {"sample": len(lifts), "mean_lift": round(mean, 3), "direction": direction}


def _totals(series: List[Dict[str, Any]], clients: List[Dict[str, str]]) -> Dict[str, Any]:
    heals = [s["healing_mean"] for s in series if s.get("healing_mean") is not None]
    return {
        "healing_mean": round(sum(heals) / len(heals), 4) if heals else None,
        "cycle_dips": sum(s.get("cycle_dips") or 0 for s in series),
        "ln_turns": sum(s.get("ln_turns") or 0 for s in series),
        "live_sessions": sum(s.get("live_sessions") or 0 for s in series),
        "roster": len(clients),
    }
