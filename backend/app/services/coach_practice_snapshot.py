"""Roster-level coach practice snapshot (healing / cycles / LN / live).

QUANTUM-CRYSTAL-ARCH — UI may include display names for hover; print must not.
"""

from __future__ import annotations

import datetime as dt
import logging
import random
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.thrive.healing_cycle import score_coherence, score_language

logger = logging.getLogger(__name__)

WINDOWS = (30, 90, 180)
SAMPLE_SIZES = (1, 5, 10, 25, 100)
_CLIENT_SPLIT = re.compile(r"[,;\n]+")


def parse_client_tokens(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        parts = [str(x) for x in raw]
    else:
        parts = _CLIENT_SPLIT.split(str(raw))
    return [p.strip() for p in parts if p and p.strip()]


def parse_sample_size(raw: Any) -> Optional[int]:
    """None = ALL. Else 1, 5, 10, 25, or 100."""
    if raw is None:
        return None
    text = str(raw).strip().upper()
    if text in ("", "ALL", "0", "NONE"):
        return None
    try:
        n = int(text)
    except (TypeError, ValueError):
        return None
    if n in SAMPLE_SIZES:
        return n
    return min(SAMPLE_SIZES, key=lambda x: abs(x - n))


def parse_sample_mode(raw: Any) -> str:
    mode = str(raw or "pick").strip().lower()
    if mode in ("random", "grab", "ln"):
        return "random"
    return "pick"


def select_roster_sample(
    clients: List[Dict[str, str]],
    *,
    mode: str = "pick",
    size: Optional[int] = None,
    tokens: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """Pick named clients or a fresh random grab. Random is never sticky."""
    book = list(clients)
    mode = parse_sample_mode(mode)
    if mode == "random":
        random.shuffle(book)
        if size is None:
            return book
        return book[: min(size, len(book))]
    picked = filter_roster(book, tokens) if tokens else []
    if not tokens:
        return book if size is None else []
    if size is None:
        return picked
    return picked[:size]


def filter_roster(
    clients: List[Dict[str, str]],
    tokens: Optional[List[str]],
) -> List[Dict[str, str]]:
    wanted = [t.lower() for t in (tokens or []) if t]
    if not wanted:
        return list(clients)
    out: List[Dict[str, str]] = []
    seen = set()
    for c in clients:
        un = (c.get("username") or "").strip()
        dn = (c.get("display_name") or "").strip()
        key = un.lower()
        if key in seen:
            continue
        hay = f"{un} {dn}".lower()
        if any(t in hay or hay in t for t in wanted if t):
            seen.add(key or dn.lower())
            out.append(c)
    return out


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
        """SELECT username, hardware_id, id::text AS uuid,
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
            "uuid": r["uuid"],
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
    client_tokens: Optional[List[str]] = None,
    sample_size: Optional[Any] = None,
    sample_mode: Optional[str] = None,
) -> Dict[str, Any]:
    days = _clamp_days(days)
    size = parse_sample_size(sample_size)
    mode = parse_sample_mode(sample_mode)
    empty = {
        "window_days": days,
        "coach": {},
        "master": None,
        "client_count": 0,
        "roster_members": [],
        "selected_clients": [],
        "sample": {"size": size or "ALL", "mode": mode, "roster": 0, "selected": 0},
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
        book = await roster_clients(conn, coach["hardware_id"], coach["username"])
        tokens = parse_client_tokens(client_tokens)
        clients = select_roster_sample(
            book, mode=mode, size=size, tokens=tokens
        )
        usernames = [c["username"] for c in clients]
        hw_ids = [c["hardware_id"] for c in clients]
        uuids = [c.get("uuid") or "" for c in clients if c.get("uuid")]
        name_by_user = {c["username"]: c["display_name"] for c in clients}
        alias = _identity_alias(clients)

        start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
        series, scatter = await _daily_series(
            conn, coach, clients, usernames, hw_ids, uuids, alias, name_by_user, start, days, include_names
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
        "roster_members": [
            {"username": c["username"], "display_name": c["display_name"]}
            for c in book
        ],
        "selected_clients": [c["username"] for c in clients],
        "sample": {
            "size": size if size is not None else "ALL",
            "mode": mode,
            "roster": len(book),
            "selected": len(clients),
        },
        "series": series,
        "scatter": scatter,
        "totals": totals,
        "skills": skills,
        "live_influence": influence,
    }


def _identity_alias(clients: List[Dict[str, str]]) -> Dict[str, str]:
    alias: Dict[str, str] = {}
    for c in clients:
        user = c.get("username") or ""
        if not user:
            continue
        alias[user] = user
        for key in ("hardware_id", "uuid"):
            val = (c.get(key) or "").strip()
            if val:
                alias[val] = user
    return alias


def compose_chart(
    *,
    days: int,
    start: dt.date,
    last_before: Dict[str, float],
    observations: List[Dict[str, Any]],
    dips: List[Dict[str, Any]],
    live: List[Dict[str, Any]],
    ln_by_day: Dict[str, int],
    ln_by_user_day: Dict[Tuple[str, str], int],
    live_count_by_day: Dict[str, int],
    name_by_user: Dict[str, str],
    include_names: bool,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Gold mean uses last-known carry-forward. Scatter keeps observed + weekly cloud."""
    rank = {"coherence": 0, "session_cee": 1, "healing": 2}
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for obs in observations:
        d = str(obs.get("date") or "")
        if not d or obs.get("score") is None:
            continue
        by_day.setdefault(d, []).append(obs)
    for bucket in by_day.values():
        bucket.sort(key=lambda o: rank.get(str(o.get("kind") or ""), 0))

    last = {
        k: max(0.0, min(1.0, float(v)))
        for k, v in last_before.items()
        if v is not None
    }
    dip_count: Dict[str, int] = {}
    for row in dips:
        d = str(row.get("date") or "")
        if d:
            dip_count[d] = dip_count.get(d, 0) + 1

    series: List[Dict[str, Any]] = []
    scatter: List[Dict[str, Any]] = []
    observed_keys: set = set()
    step = 7 if days > 45 else 3
    for i in range(days):
        day = start + dt.timedelta(days=i + 1)
        d = day.isoformat()
        for obs in by_day.get(d, []):
            user = str(obs.get("user") or "")
            score = max(0.0, min(1.0, float(obs["score"])))
            kind = str(obs.get("kind") or "healing")
            if user and kind == "healing":
                last[user] = score
                observed_keys.add((d, user))
            scatter.append(_scatter_point(
                d, score, kind, user,
                name_by_user, include_names, observed=True,
                ln=ln_by_user_day.get((user, d), 0),
                live=live_count_by_day.get(d, 0) > 0,
            ))
        scores = list(last.values())
        mean_h = round(sum(scores) / len(scores), 4) if scores else None
        series.append({
            "date": d,
            "healing_mean": mean_h,
            "cycle_dips": dip_count.get(d, 0),
            "ln_turns": ln_by_day.get(d, 0),
            "live_sessions": live_count_by_day.get(d, 0),
            "live": live_count_by_day.get(d, 0) > 0,
        })
        if i % step == (step - 1) or i == days - 1:
            for user, score in last.items():
                if (d, user) in observed_keys:
                    continue
                scatter.append(_scatter_point(
                    d, score, "carried", user, name_by_user, include_names,
                    observed=False,
                    ln=ln_by_user_day.get((user, d), 0),
                    live=live_count_by_day.get(d, 0) > 0,
                ))

    for row in dips:
        d = str(row.get("date") or "")
        user = str(row.get("user") or "")
        if not d:
            continue
        y = last.get(user)
        if y is None:
            y = 0.38
        scatter.append(_scatter_point(
            d, y, "cycle_dip", user, name_by_user, include_names,
            observed=True,
            ln=ln_by_user_day.get((user, d), 0),
            live=live_count_by_day.get(d, 0) > 0,
        ))

    for row in live:
        d = str(row.get("date") or "")
        user = str(row.get("user") or "")
        if not d:
            continue
        y = row.get("score")
        if y is None:
            y = last.get(user)
        if y is None:
            y = next((s["healing_mean"] for s in series if s["date"] == d), None)
        if y is None:
            continue
        scatter.append(_scatter_point(
            d, float(y), "live_session", user, name_by_user, include_names,
            observed=True,
            ln=ln_by_user_day.get((user, d), 0),
            live=True,
        ))
    return series, scatter


def _scatter_point(
    date: str,
    healing: float,
    kind: str,
    user: str,
    name_by_user: Dict[str, str],
    include_names: bool,
    *,
    observed: bool,
    ln: int,
    live: bool,
) -> Dict[str, Any]:
    point: Dict[str, Any] = {
        "date": date,
        "healing": round(float(healing), 4),
        "kind": kind,
        "observed": observed,
        "ln": int(ln or 0),
        "live": bool(live),
        "user": user,
    }
    if include_names:
        point["client"] = name_by_user.get(user) or ("Cycle dip" if kind == "cycle_dip" else "Client")
    return point


def apply_language_floors(
    last_before: Dict[str, float],
    texts_by_user: Dict[str, List[str]],
) -> Dict[str, float]:
    """Fill missing clients from LN language so the whole book can hover."""
    out = dict(last_before)
    for user, texts in texts_by_user.items():
        if not user or user in out:
            continue
        lang = score_language(texts)
        if lang and lang.get("score") is not None:
            out[user] = float(lang["score"])
        elif texts:
            out[user] = 0.5
    return out


async def _fill_roster_healing(
    conn,
    clients: List[Dict[str, str]],
    alias: Dict[str, str],
    last_before: Dict[str, float],
    start: dt.datetime,
) -> None:
    missing = [c for c in clients if c.get("username") and c["username"] not in last_before]
    if not missing:
        return
    idents = list({
        x for c in missing
        for x in (c.get("username"), c.get("hardware_id"), c.get("uuid"))
        if x
    })
    texts_by_user: Dict[str, List[str]] = {}
    try:
        rows = await conn.fetch(
            """SELECT user_id, user_text
               FROM conversation_history
               WHERE user_id = ANY($1::text[])
                 AND created_at >= $2
                 AND user_text IS NOT NULL
                 AND length(user_text) > 8
               ORDER BY created_at DESC
               LIMIT 8000""",
            idents,
            start,
        )
        for r in rows:
            user = alias.get(str(r["user_id"] or ""), str(r["user_id"] or ""))
            if not user:
                continue
            bucket = texts_by_user.setdefault(user, [])
            if len(bucket) < 80:
                bucket.append(r["user_text"])
    except Exception as e:
        logger.debug("practice snapshot language floors: %s", e)
    filled = apply_language_floors(last_before, texts_by_user)
    last_before.update(filled)

    still = [c for c in missing if c["username"] not in last_before]
    if not still:
        return
    still_ids = list({
        x for c in still
        for x in (c.get("username"), c.get("hardware_id"), c.get("uuid"))
        if x
    })
    try:
        rows = await conn.fetch(
            """SELECT COALESCE(hardware_id, user_id::text) AS ident, c_emo::float AS score
               FROM client_metrics
               WHERE (hardware_id = ANY($1::text[]) OR user_id::text = ANY($1::text[]))
                 AND c_emo IS NOT NULL
               ORDER BY updated_at DESC""",
            still_ids,
        )
        recent: Dict[str, List[float]] = {}
        for r in rows:
            user = alias.get(str(r["ident"] or ""), "")
            if not user or user in last_before:
                continue
            recent.setdefault(user, []).append(float(r["score"]))
        for user, vals in recent.items():
            if user in last_before:
                continue
            coh = score_coherence(vals[:20], vals[20:40] if len(vals) > 20 else [])
            if coh and coh.get("score") is not None:
                last_before[user] = float(coh["score"])
            elif vals:
                last_before[user] = max(0.0, min(1.0, sum(vals[:8]) / min(8, len(vals))))
    except Exception as e:
        logger.debug("practice snapshot metric floors: %s", e)


async def _daily_series(
    conn,
    coach: Dict[str, str],
    clients: List[Dict[str, str]],
    usernames: List[str],
    hw_ids: List[str],
    uuids: List[str],
    alias: Dict[str, str],
    name_by_user: Dict[str, str],
    start: dt.datetime,
    days: int,
    include_names: bool,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    ident_all = list({x for x in [*usernames, *hw_ids, *uuids] if x})
    observations: List[Dict[str, Any]] = []
    last_before: Dict[str, float] = {}
    dips: List[Dict[str, Any]] = []
    live: List[Dict[str, Any]] = []
    ln_by_day: Dict[str, int] = {}
    ln_by_user_day: Dict[Tuple[str, str], int] = {}
    live_count_by_day: Dict[str, int] = {}

    def _user(raw: Any) -> str:
        return alias.get(str(raw or ""), "")

    if usernames:
        try:
            rows = await conn.fetch(
                """SELECT DISTINCT ON (username) username, healing_score::float AS score
                   FROM client_growth_phase_history
                   WHERE username = ANY($1::text[])
                     AND created_at < $2
                     AND healing_score IS NOT NULL
                   ORDER BY username, created_at DESC""",
                usernames,
                start,
            )
            for r in rows:
                last_before[r["username"]] = float(r["score"])
        except Exception as e:
            logger.debug("practice snapshot last-before: %s", e)
        try:
            rows = await conn.fetch(
                """SELECT username, healing_score::float AS score
                   FROM client_growth_phase
                   WHERE username = ANY($1::text[])
                     AND healing_score IS NOT NULL""",
                usernames,
            )
            for r in rows:
                last_before.setdefault(r["username"], float(r["score"]))
        except Exception as e:
            logger.debug("practice snapshot current phase: %s", e)
        try:
            rows = await conn.fetch(
                """SELECT username, created_at::date AS d, healing_score::float AS score
                   FROM client_growth_phase_history
                   WHERE username = ANY($1::text[])
                     AND created_at >= $2
                     AND healing_score IS NOT NULL""",
                usernames,
                start,
            )
            for r in rows:
                observations.append({
                    "user": r["username"], "date": str(r["d"]),
                    "score": float(r["score"]), "kind": "healing",
                })
        except Exception as e:
            logger.debug("practice snapshot healing: %s", e)
        try:
            rows = await conn.fetch(
                """SELECT user_id::text AS uid, recorded_at::date AS d,
                          AVG(c_emo)::float AS score
                   FROM nevedal_metrics
                   WHERE user_id::text = ANY($1::text[])
                     AND recorded_at >= $2
                     AND c_emo IS NOT NULL
                   GROUP BY 1, 2""",
                ident_all,
                start,
            )
            for r in rows:
                user = _user(r["uid"])
                if user and r["score"] is not None:
                    observations.append({
                        "user": user, "date": str(r["d"]),
                        "score": float(r["score"]), "kind": "coherence",
                    })
        except Exception as e:
            logger.debug("practice snapshot nevedal: %s", e)
        try:
            rows = await conn.fetch(
                """SELECT user_id, observed_at::date AS d
                   FROM cycle_observations
                   WHERE user_id = ANY($1::text[])
                     AND observed_at >= $2
                     AND (phase IN ('low', 'trough', 'dip') OR value < 0.40)""",
                ident_all,
                start,
            )
            for r in rows:
                dips.append({"user": _user(r["user_id"]), "date": str(r["d"])})
        except Exception as e:
            logger.debug("practice snapshot cycles: %s", e)
        try:
            rows = await conn.fetch(
                """SELECT user_id, created_at::date AS d, COUNT(*)::int AS n
                   FROM conversation_history
                   WHERE user_id = ANY($1::text[])
                     AND created_at >= $2
                   GROUP BY 1, 2""",
                ident_all,
                start,
            )
            for r in rows:
                d = str(r["d"])
                n = int(r["n"] or 0)
                ln_by_day[d] = ln_by_day.get(d, 0) + n
                user = _user(r["user_id"])
                if user:
                    ln_by_user_day[(user, d)] = ln_by_user_day.get((user, d), 0) + n
        except Exception as e:
            logger.debug("practice snapshot ln: %s", e)
    try:
        rows = await conn.fetch(
            f"""SELECT COALESCE(actual_start, scheduled_start, created_at)::date AS d,
                      client_id, COUNT(*)::int AS n,
                      AVG({_safe_cee()}) AS score
               FROM coaching_sessions
               WHERE coach_id::text = ANY($1::text[])
                 AND upper(COALESCE(session_type, '')) NOT IN ('MASTER_CONSULTATION', 'CONSULTATION')
                 AND status IN ('completed', 'active')
                 AND COALESCE(actual_start, scheduled_start, created_at) >= $2
               GROUP BY 1, 2""",
            [coach["hardware_id"], coach["uuid"], coach["username"]],
            start,
        )
        for r in rows:
            d = str(r["d"])
            live_count_by_day[d] = live_count_by_day.get(d, 0) + int(r["n"] or 0)
            user = _user(r["client_id"])
            score = float(r["score"]) if r["score"] is not None else None
            if score is not None and user:
                observations.append({
                    "user": user, "date": d, "score": score, "kind": "session_cee",
                })
            live.append({"user": user, "date": d, "score": score})
    except Exception as e:
        logger.debug("practice snapshot live: %s", e)
    try:
        rows = await conn.fetch(
            f"""SELECT DISTINCT ON (client_id) client_id,
                      {_safe_cee()} AS score
               FROM coaching_sessions
               WHERE client_id::text = ANY($1::text[])
                 AND status IN ('completed', 'active')
                 AND COALESCE(actual_start, scheduled_start, created_at) < $2
               ORDER BY client_id,
                        COALESCE(actual_start, scheduled_start, created_at) DESC""",
            ident_all,
            start,
        )
        for r in rows:
            user = _user(r["client_id"])
            if user and r["score"] is not None:
                last_before.setdefault(user, max(0.0, min(1.0, float(r["score"]))))
    except Exception as e:
        logger.debug("practice snapshot last-before session: %s", e)

    await _fill_roster_healing(conn, clients, alias, last_before, start)

    return compose_chart(
        days=days,
        start=start.date(),
        last_before=last_before,
        observations=observations,
        dips=dips,
        live=live,
        ln_by_day=ln_by_day,
        ln_by_user_day=ln_by_user_day,
        live_count_by_day=live_count_by_day,
        name_by_user=name_by_user,
        include_names=include_names,
    )


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
