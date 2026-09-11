"""Focus-area practice tracker + goal ledger — QUANTUM-CRYSTAL-ARCH.

Owns ``client_focus_areas``, ``client_practice_log``, ``client_strengths`` and
the thrive columns added to ``nate_commitments`` (migration 434).

LN calls:
* ``adopt_practice`` when a client agrees to a practice ("let's do three good
  things each night") — sets cadence, time of day, next_due.
* ``detect_completion`` + ``log_completion`` when a turn contains evidence the
  practice was done (the "harvest" is what the client actually said).
* ``goal_trajectories`` for the coach briefing and the entry greeting.

The reminder agent calls ``due_practices`` / ``mark_reminded``.
Everything keyed on canonical ``users.username``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone, time as dtime
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from app.services._identity_resolver import resolve_username
from app.services.thrive import practice_catalog as pc
from app.services.thrive import strengths_interview as _si

logger = logging.getLogger(__name__)

CADENCES = ("daily", "weekdays", "3x_week", "weekly", "once")
TIMES_OF_DAY = ("morning", "midday", "evening", "late_night", "any")
_TOD_HOUR = {"morning": 8, "midday": 12, "evening": 20, "late_night": 22, "any": 18}


# ── completion detection (turn-time heuristic) ─────────────────────────────

_COMPLETION_CUES: Dict[str, Sequence[str]] = {
    "three_good_things": (
        r"\bthree (good )?things\b", r"\b(went well|good things? today)\b.*\b(1\.|first|one)\b",
        r"\bmy (three|3) (good )?things\b", r"\bgratitude (list|journal)\b",
    ),
    "best_possible_self": (r"\bbest possible self\b", r"\b(wrote|imagined|pictured) (my|the) (future|life in \d+ years)\b"),
    "strength_date": (r"\bstrength date\b", r"\bused my (strength|top strength)\b", r"\b(did|tried) (a|my) strength\b"),
    "self_compassion_break": (r"\bself[- ]compassion break\b", r"\bhand on my (heart|chest)\b", r"\bmay i be kind to myself\b"),
    "gratitude_letter": (r"\bgratitude letter\b", r"\bwrote (a )?letter (to|for) .* (thank|grateful)\b"),
    "savoring_walk": (r"\bsavor(ing)? walk\b", r"\bmindful walk\b"),
    "goal_ladder": (r"\bgoal ladder\b", r"\b(next|first) rung\b", r"\bbroke (it|the goal) (down|into steps)\b"),
    "strengths_spotting": (r"\bspotted (a )?strength\b", r"\bstrength spotting\b"),
    "antifragile_review": (r"\bantifragile\b", r"\bwhat (this|that) (taught|made) me stronger\b"),
    "appreciative_inquiry": (r"\bappreciative inquiry\b", r"\bwhat('s| is) working\b.*\bmore of\b"),
}
_DONE_VERBS = re.compile(
    r"\b(i (did|finished|completed|wrote|tried|practiced|done)|here('s| are| is) my|just did|last night i|this morning i)\b", re.I
)


def detect_completion(user_text: str, active_keys: Optional[Sequence[str]] = None) -> Optional[str]:
    """Return a practice_key if the turn reads like a completion report."""
    t = user_text or ""
    if len(t) < 12:
        return None
    keys = list(active_keys) if active_keys else list(_COMPLETION_CUES.keys())
    for k in keys:
        cues = _COMPLETION_CUES.get(k, ())
        if any(re.search(c, t, re.I) for c in cues):
            # Three Good Things gets a free pass on enumerated content; others need a done-verb.
            if k == "three_good_things" and re.search(r"(\b1\b|\bfirst\b|\bone\b).*(\b2\b|\bsecond\b|\btwo\b)", t, re.I | re.S):
                return k
            if _DONE_VERBS.search(t):
                return k
    return None


# ── scheduling ─────────────────────────────────────────────────────────────

def compute_next_due(cadence: str, time_of_day: str, after: datetime, tz: str = "UTC") -> Optional[datetime]:
    """Next due instant (UTC) strictly after ``after`` honouring the client's local time-of-day."""
    if cadence == "once":
        return None
    try:
        zone = ZoneInfo(tz or "UTC")
    except Exception:
        zone = ZoneInfo("UTC")
    local = after.astimezone(zone)
    hour = _TOD_HOUR.get(time_of_day or "any", 18)
    candidate = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    step = {"daily": 1, "weekdays": 1, "3x_week": 2, "weekly": 7}.get(cadence, 1)
    if cadence == "weekly":
        candidate = local.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=7)
    elif cadence == "3x_week":
        candidate = local.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=step)
    if cadence == "weekdays":
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


async def _tz_for(db_pool: Any, username: str) -> str:
    try:
        async with db_pool.acquire() as conn:
            tz = await conn.fetchval(
                "SELECT COALESCE(profile_data->>'timezone', profile_data->>'time_zone', 'UTC') FROM users WHERE username = $1",
                username,
            )
        return tz or "UTC"
    except Exception:
        return "UTC"


# ── focus areas ────────────────────────────────────────────────────────────

@dataclass
class FocusRow:
    username: str
    focus_area: str
    practice_key: str
    cadence: str
    time_of_day: str
    active: bool
    source: str
    started_at: Optional[datetime]
    last_completed_at: Optional[datetime]
    next_due_at: Optional[datetime]
    streak: int
    longest_streak: int
    total_completions: int
    total_reminders: int
    last_reminder_at: Optional[datetime]
    notes: Optional[str]

    @property
    def label(self) -> str:
        p = pc.PRACTICES.get(self.practice_key)
        return p.label if p else self.practice_key

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, datetime):
                d[k] = v.isoformat()
        d["label"] = self.label
        fa = pc.FOCUS_AREAS.get(self.focus_area)
        d["focus_label"] = getattr(fa, "label", None) or (fa.get("label") if isinstance(fa, dict) else self.focus_area)
        return d


def _row_to_focus(r: Any) -> FocusRow:
    return FocusRow(**{k: r[k] for k in FocusRow.__dataclass_fields__.keys()})


async def list_focus_areas(db_pool: Any, user_id: str, *, active_only: bool = True) -> List[FocusRow]:
    username = await resolve_username(db_pool, user_id) or user_id
    if not db_pool or not username:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM client_focus_areas WHERE username = $1 {'AND active' if active_only else ''} "
                "ORDER BY next_due_at NULLS LAST, started_at",
                username,
            )
        return [_row_to_focus(r) for r in rows]
    except Exception as e:
        logger.debug("practice_tracker: list_focus_areas failed for %s: %s", username, e)
        return []


async def adopt_practice(
    db_pool: Any,
    user_id: str,
    practice_key: str,
    *,
    cadence: Optional[str] = None,
    time_of_day: Optional[str] = None,
    source: str = "ln",
    notes: Optional[str] = None,
) -> Optional[FocusRow]:
    """Client (or LN/coach on their behalf) commits to a practice."""
    p = pc.PRACTICES.get(practice_key)
    if not p:
        raise ValueError(f"unknown practice {practice_key!r}")
    username = await resolve_username(db_pool, user_id) or user_id
    if not db_pool or not username:
        return None
    cadence = cadence if cadence in CADENCES else p.default_cadence
    tod = time_of_day if time_of_day in TIMES_OF_DAY else p.default_time_of_day
    tz = await _tz_for(db_pool, username)
    now = datetime.now(timezone.utc)
    next_due = compute_next_due(cadence, tod, now, tz)
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO client_focus_areas
                    (username, focus_area, practice_key, cadence, time_of_day, active, source,
                     started_at, next_due_at, notes, updated_at)
                VALUES ($1, $2, $3, $4, $5, TRUE, $6, NOW(), $7, $8, NOW())
                ON CONFLICT (username, practice_key) DO UPDATE SET
                    cadence = EXCLUDED.cadence, time_of_day = EXCLUDED.time_of_day, active = TRUE,
                    source = EXCLUDED.source, next_due_at = EXCLUDED.next_due_at,
                    notes = COALESCE(EXCLUDED.notes, client_focus_areas.notes), updated_at = NOW()
                RETURNING *
                """,
                username, p.focus_area, practice_key, cadence, tod, source, next_due, notes,
            )
        return _row_to_focus(row)
    except Exception as e:
        logger.warning("practice_tracker: adopt_practice failed for %s: %s", username, e)
        return None


async def retire_practice(db_pool: Any, user_id: str, practice_key: str) -> bool:
    username = await resolve_username(db_pool, user_id) or user_id
    try:
        async with db_pool.acquire() as conn:
            res = await conn.execute(
                "UPDATE client_focus_areas SET active = FALSE, updated_at = NOW() WHERE username = $1 AND practice_key = $2",
                username, practice_key,
            )
        return res.endswith("1")
    except Exception as e:
        logger.warning("practice_tracker: retire_practice failed: %s", e)
        return False


async def log_completion(
    db_pool: Any,
    user_id: str,
    practice_key: str,
    *,
    source: str = "chat",
    harvest: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[FocusRow]:
    """Record a completion; roll streak; advance next_due."""
    username = await resolve_username(db_pool, user_id) or user_id
    if not db_pool or not username:
        return None
    p = pc.PRACTICES.get(practice_key)
    focus_area = p.focus_area if p else "daily_happiness"
    now = datetime.now(timezone.utc)
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO client_practice_log (username, practice_key, focus_area, completed_at, source, harvest, metadata)
                    VALUES ($1, $2, $3, NOW(), $4, $5, $6::jsonb)
                    """,
                    username, practice_key, focus_area, source, (harvest or "")[:2000],
                    json.dumps(metadata or {}, default=str),
                )
                cur = await conn.fetchrow(
                    "SELECT * FROM client_focus_areas WHERE username = $1 AND practice_key = $2", username, practice_key
                )
                if cur is None:
                    # Completed a practice never adopted — adopt implicitly so it shows on the ledger.
                    tz = await _tz_for(db_pool, username)
                    cad = p.default_cadence if p else "daily"
                    tod = p.default_time_of_day if p else "any"
                    await conn.execute(
                        """
                        INSERT INTO client_focus_areas
                            (username, focus_area, practice_key, cadence, time_of_day, active, source, started_at,
                             last_completed_at, next_due_at, streak, longest_streak, total_completions, updated_at)
                        VALUES ($1, $2, $3, $4, $5, TRUE, 'ln', NOW(), NOW(), $6, 1, 1, 1, NOW())
                        ON CONFLICT (username, practice_key) DO NOTHING
                        """,
                        username, focus_area, practice_key, cad, tod, compute_next_due(cad, tod, now, tz),
                    )
                else:
                    last = cur["last_completed_at"]
                    gap_days = (now - last).total_seconds() / 86400 if last else None
                    window = {"daily": 1.75, "weekdays": 3.5, "3x_week": 3.5, "weekly": 8.5, "once": 9e9}.get(cur["cadence"], 1.75)
                    streak = (cur["streak"] or 0) + 1 if (gap_days is None or gap_days <= window) else 1
                    if last and gap_days is not None and gap_days < 0.3:
                        streak = cur["streak"] or 1  # same-day duplicate report
                    tz = await _tz_for(db_pool, username)
                    await conn.execute(
                        """
                        UPDATE client_focus_areas SET
                            last_completed_at = NOW(), next_due_at = $3, streak = $4,
                            longest_streak = GREATEST(longest_streak, $4), total_completions = total_completions + 1,
                            updated_at = NOW()
                        WHERE username = $1 AND practice_key = $2
                        """,
                        username, practice_key, compute_next_due(cur["cadence"], cur["time_of_day"], now, tz), streak,
                    )
                row = await conn.fetchrow(
                    "SELECT * FROM client_focus_areas WHERE username = $1 AND practice_key = $2", username, practice_key
                )
        if harvest and len(harvest.strip()) >= 40:
            # thrive-domain crystal so the harvest survives decay via recall (phase-aware memory)
            _label = p.label if p else practice_key
            asyncio.create_task(_si.crystallize_thrive(db_pool, username, f"{_label}: {harvest.strip()}", kind="practice"))
        return _row_to_focus(row) if row else None
    except Exception as e:
        logger.warning("practice_tracker: log_completion failed for %s/%s: %s", username, practice_key, e)
        return None


async def due_practices(db_pool: Any, *, now: Optional[datetime] = None, min_gap_hours: int = 20, limit: int = 200) -> List[FocusRow]:
    """Active practices past ``next_due_at`` not reminded in the last ``min_gap_hours``."""
    now = now or datetime.now(timezone.utc)
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM client_focus_areas
                WHERE active AND next_due_at IS NOT NULL AND next_due_at <= $1
                  AND (last_reminder_at IS NULL OR last_reminder_at <= $1 - ($2 || ' hours')::interval)
                  AND (last_completed_at IS NULL OR last_completed_at < next_due_at - interval '1 hour')
                ORDER BY next_due_at
                LIMIT $3
                """,
                now, str(int(min_gap_hours)), limit,
            )
        return [_row_to_focus(r) for r in rows]
    except Exception as e:
        logger.warning("practice_tracker: due_practices failed: %s", e)
        return []


async def mark_reminded(db_pool: Any, username: str, practice_key: str) -> None:
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE client_focus_areas
                SET last_reminder_at = NOW(), total_reminders = total_reminders + 1, updated_at = NOW()
                WHERE username = $1 AND practice_key = $2
                """,
                username, practice_key,
            )
    except Exception as e:
        logger.debug("practice_tracker: mark_reminded failed: %s", e)


# ── goal ledger (nate_commitments) ─────────────────────────────────────────

@dataclass
class GoalTrajectory:
    id: str
    text: str
    focus_area: Optional[str]
    status: str
    started_at: Optional[datetime]
    target_date: Optional[datetime]
    completed_at: Optional[datetime]
    progress_pct: float
    growth_phase: Optional[str]
    days_elapsed: Optional[float]
    days_remaining: Optional[float]
    projected_completion: Optional[datetime]
    on_track: Optional[bool]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, datetime):
                d[k] = v.isoformat()
        return d


def _trajectory(row: Any, now: datetime) -> GoalTrajectory:
    started = row["started_at"] or row["created_at"]
    target = row["target_date"]
    pct = float(row["progress_pct"] or 0)
    elapsed = (now - started).total_seconds() / 86400 if started else None
    remaining = (target - now).total_seconds() / 86400 if target else None
    projected = None
    on_track = None
    if row["status"] == "completed":
        projected, on_track = row["completed_at"], True
    elif elapsed and elapsed > 0 and 0 < pct < 100:
        rate = pct / elapsed  # pct per day
        projected = now + timedelta(days=(100 - pct) / rate) if rate > 0 else None
        if target and projected:
            on_track = projected <= target + timedelta(days=2)
    elif target and remaining is not None:
        on_track = remaining > 0 and pct > 0
    return GoalTrajectory(
        id=str(row["id"]), text=row["commitment_text"], focus_area=row["focus_area"], status=row["status"],
        started_at=started, target_date=target, completed_at=row["completed_at"], progress_pct=pct,
        growth_phase=row["growth_phase"], days_elapsed=round(elapsed, 1) if elapsed is not None else None,
        days_remaining=round(remaining, 1) if remaining is not None else None,
        projected_completion=projected, on_track=on_track,
    )


async def goal_trajectories(db_pool: Any, user_id: str, *, include_completed: bool = True, limit: int = 12) -> List[GoalTrajectory]:
    username = await resolve_username(db_pool, user_id) or user_id
    if not db_pool or not username:
        return []
    now = datetime.now(timezone.utc)
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, commitment_text, focus_area, status, started_at, target_date, completed_at,
                       progress_pct, growth_phase, created_at
                FROM nate_commitments
                WHERE user_id = $1 AND commitment_type IN ('practice_goal', 'milestone', 'custom')
                  {"" if include_completed else "AND status = 'active'"}
                  AND status IN ('active', 'completed')
                ORDER BY (status = 'active') DESC, COALESCE(target_date, created_at + interval '30 days')
                LIMIT $2
                """,
                username, limit,
            )
        return [_trajectory(r, now) for r in rows]
    except Exception as e:
        logger.debug("practice_tracker: goal_trajectories failed for %s: %s", username, e)
        return []


async def open_goal(
    db_pool: Any,
    user_id: str,
    text: str,
    *,
    focus_area: Optional[str] = None,
    target_date: Optional[datetime] = None,
    growth_phase: Optional[str] = None,
    coached_by: str = "ln",
    commitment_type: str = "practice_goal",
) -> Optional[str]:
    username = await resolve_username(db_pool, user_id) or user_id
    if not db_pool or not username or not (text or "").strip():
        return None
    try:
        async with db_pool.acquire() as conn:
            gid = await conn.fetchval(
                """
                INSERT INTO nate_commitments
                    (user_id, commitment_text, commitment_type, target_date, status, source, sensitivity,
                     focus_area, started_at, progress_pct, growth_phase, coached_by)
                VALUES ($1, $2, $3, $4, 'active', 'auto_extracted', 'routine', $5, NOW(), 0, $6, $7)
                RETURNING id
                """,
                username, text.strip()[:500], commitment_type, target_date, focus_area, growth_phase, coached_by,
            )
        return str(gid)
    except Exception as e:
        logger.warning("practice_tracker: open_goal failed for %s: %s", username, e)
        return None


async def update_goal_progress(db_pool: Any, goal_id: str, progress_pct: Optional[float], *, note: Optional[str] = None) -> bool:
    """Set progress (0–100; >=100 completes). ``progress_pct=None`` or negative = touch + note only."""
    pct = None if progress_pct is None or float(progress_pct) < 0 else max(0.0, min(100.0, float(progress_pct)))
    try:
        async with db_pool.acquire() as conn:
            res = await conn.execute(
                """
                UPDATE nate_commitments SET
                    progress_pct = COALESCE($2, progress_pct),
                    status = CASE WHEN $2 >= 100 THEN 'completed' ELSE status END,
                    completed_at = CASE WHEN $2 >= 100 THEN COALESCE(completed_at, NOW()) ELSE completed_at END,
                    touch_count = touch_count + 1, last_touched_at = NOW(), updated_at = NOW()
                WHERE id = $1::uuid AND status IN ('active', 'completed')
                """,
                goal_id, pct,
            )
            if note:
                await conn.execute(
                    """
                    INSERT INTO client_practice_log (username, practice_key, source, harvest, metadata)
                    SELECT user_id, 'goal_note', 'email_reply', $2, jsonb_build_object('goal_id', $1::text, 'progress_pct', $3::numeric)
                    FROM nate_commitments WHERE id = $1::uuid
                    """,
                    goal_id, note[:2000], pct,
                )
            if pct is not None and pct >= 100 and res.endswith("1"):
                done = await conn.fetchrow(
                    "SELECT user_id, commitment_text, started_at FROM nate_commitments WHERE id = $1::uuid", goal_id
                )
                if done:
                    _days = (datetime.now(timezone.utc) - done["started_at"]).days if done["started_at"] else None
                    _txt = f"Goal completed: {done['commitment_text']}" + (f" (in {_days} days)" if _days is not None else "")
                    asyncio.create_task(_si.crystallize_thrive(db_pool, done["user_id"], _txt, kind="goal"))
        return res.endswith("1")
    except Exception as e:
        logger.warning("practice_tracker: update_goal_progress failed: %s", e)
        return False


# ── strengths (in-house, free) ─────────────────────────────────────────────

async def get_strengths(db_pool: Any, user_id: str) -> Optional[Dict[str, Any]]:
    username = await resolve_username(db_pool, user_id) or user_id
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM client_strengths WHERE username = $1", username)
        if not row:
            return None
        d = dict(row)
        for k in ("assessed_at", "updated_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        if isinstance(d.get("answers"), str):
            d["answers"] = json.loads(d["answers"])
        return d
    except Exception as e:
        logger.debug("practice_tracker: get_strengths failed: %s", e)
        return None


async def save_strengths(
    db_pool: Any,
    user_id: str,
    *,
    via_top: Sequence[str],
    clifton_domains: Sequence[str] = (),
    answers: Optional[Dict[str, Any]] = None,
    method: str = "ln_interview",
) -> bool:
    username = await resolve_username(db_pool, user_id) or user_id
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO client_strengths (username, via_top, clifton_domains, answers, method, assessed_at, updated_at)
                VALUES ($1, $2, $3, $4::jsonb, $5, NOW(), NOW())
                ON CONFLICT (username) DO UPDATE SET
                    via_top = EXCLUDED.via_top, clifton_domains = EXCLUDED.clifton_domains,
                    answers = EXCLUDED.answers, method = EXCLUDED.method, assessed_at = NOW(), updated_at = NOW()
                """,
                username, list(via_top)[:7], list(clifton_domains)[:4], json.dumps(answers or {}, default=str), method,
            )
        return True
    except Exception as e:
        logger.warning("practice_tracker: save_strengths failed: %s", e)
        return False


# ── compact state for the prompt / greeting ────────────────────────────────

async def focus_state(db_pool: Any, user_id: str) -> Dict[str, Any]:
    """One dict the persona addendum + entry greeting can consume."""
    areas = await list_focus_areas(db_pool, user_id)
    goals = await goal_trajectories(db_pool, user_id, include_completed=True, limit=8)
    strengths = await get_strengths(db_pool, user_id)
    try:
        memory = await _si.thrive_memory(db_pool, user_id)
    except Exception as e:  # never let memory recall break the addendum
        logger.warning("practice_tracker: thrive_memory failed for %s: %s", user_id, e)
        memory = []
    now = datetime.now(timezone.utc)
    _method = (strengths or {}).get("method") or ""
    return {
        # phase-aware growth memory (thrive/coaching crystals, reinforced on recall)
        "thrive_memory": memory,
        # LN-led strengths interview state
        "has_signature": _method == "ln_interview" or _method.startswith("coach") or _method == "via_import",
        "strengths_answers": (strengths or {}).get("answers") or {},
        # persona._focus_lines contract
        "areas": [
            {
                "key": a.focus_area, "practice_key": a.practice_key, "cadence": a.cadence,
                "last_completed_at": a.last_completed_at.isoformat() if a.last_completed_at else None,
                "streak": a.streak, "due": bool(a.next_due_at and a.next_due_at <= now),
            }
            for a in areas
        ],
        "goals": [
            {"id": g.id, "title": g.text, "status": g.status, "progress_pct": g.progress_pct,
             "target_date": g.target_date.date().isoformat() if g.target_date else None,
             "on_track": g.on_track}
            for g in goals
        ],
        "strengths": (strengths or {}).get("via_top") or [],
        # richer shapes for greeting / coach briefing
        "practices": [a.to_dict() for a in areas],
        "due_now": [a.practice_key for a in areas if a.next_due_at and a.next_due_at <= now],
        "best_streak": max([a.streak for a in areas], default=0),
        "goals_active": [g.to_dict() for g in goals if g.status == "active"],
        "goals_completed": [g.to_dict() for g in goals if g.status == "completed"],
    }
