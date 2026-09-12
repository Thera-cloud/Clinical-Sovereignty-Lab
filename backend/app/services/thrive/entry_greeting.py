"""LN entry greeting — what Little Nate says the moment the app opens.

Three parts (character budgets are soft targets, hard-capped):

1. ``welcome``   ≤ 600  — chit-chat grounded in the client's local time, their
                          usual entry habits (morning coffee, "how was your day"
                          openers, late-night check-ins), recent activity + mood.
2. ``prime``     300–500 — the established goals / focus practices (thrive
                          phases) *or* the last piece of trauma work that was
                          on the table (process phases), so the conversation
                          starts where the client actually is.
3. ``direction`` ≤ 900  — where LN thinks today should go and why: 1–3
                          topics/directions drawn from predictability
                          (cycle_predictions), cycle detection, the latest
                          Thera-World panel, life-coach goals, trauma-informed
                          work. Reasoning stated plainly.

Signals are gathered deterministically; the prose is produced by the
LittleNate inference pipeline when available and by templates otherwise.
Every greeting is logged to ``ln_entry_greetings`` (migration 434) and reused
for ``CACHE_HOURS`` so re-opening the app doesn't re-spend inference.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from app.services._identity_resolver import resolve_username
from app.services.thrive import growth_phase as gp
from app.services.thrive import phase_resolver as pr
from app.services.thrive import practice_catalog as pc
from app.services.thrive import practice_tracker as pt

logger = logging.getLogger(__name__)

WELCOME_MAX = 600
PRIME_MIN, PRIME_MAX = 300, 500
DIRECTION_MAX = 900
CACHE_HOURS = float(os.getenv("LN_ENTRY_GREETING_CACHE_HOURS", "4"))
ENABLE_LLM = os.getenv("LN_ENTRY_GREETING_LLM", "true").lower() in ("1", "true", "yes")
SIGNALS_TIMEOUT_S = float(os.getenv("LN_ENTRY_GREETING_SIGNALS_TIMEOUT_S", "10"))
LLM_TIMEOUT_S = float(os.getenv("LN_ENTRY_GREETING_LLM_TIMEOUT_S", "15"))
BACKGROUND_POLISH_TIMEOUT_S = float(os.getenv("LN_ENTRY_GREETING_BG_TIMEOUT_S", "120"))

DAY_PARTS = (
    (5, 11, "morning"),
    (11, 14, "midday"),
    (14, 18, "afternoon"),
    (18, 22, "evening"),
)

_HABIT_PATTERNS: Dict[str, str] = {
    "coffee": r"\bcoffee|espresso|latte|cappuccino\b",
    "tea": r"\btea\b|matcha|chai",
    "breakfast": r"\bbreakfast|oatmeal|eggs|toast|cereal|smoothie\b",
    "walk": r"\bwalk(ing|ed)?\b|\bhike\b|\brun(ning)?\b",
    "gym": r"\bgym|workout|lifting|yoga|stretch",
    "kids": r"\bkids?\b|\bschool run|daycare|my (son|daughter)",
    "work": r"\bwork (day|shift|meeting)|before work|after work|\bshift\b",
    "dog": r"\bdog|puppy|walk the dog",
    "sleep": r"can'?t sleep|couldn'?t sleep|insomnia|up late|wide awake",
    "commute": r"\bcommut|on the train|in the car|driving to",
}
_CHITCHAT_RE = re.compile(
    r"^(hi|hey|hello|good (morning|afternoon|evening)|morning|evening|yo|what'?s up|how are you|how'?s it going|sup)\b",
    re.I,
)
_LINGUISTIC_BAN = ("liminal", "threshold", "aching", "tapestry", "journey through", "sacred space")

# Plain-language "why" per phase for part three (no clinical jargon in client copy).
_PHASE_WHY: Dict[str, str] = {
    "stabilize": "Why this direction: right now the most useful thing is steadiness — feeling safe enough in your own body that the harder material can wait until it's actually workable.",
    "process": "Why this direction: you're in the part where old hurt gets felt and understood instead of managed. Going slowly here is what makes the lighter seasons possible later.",
    "consolidate": "Why this direction: the heavy lifting is mostly behind you. What matters now is letting the new ground settle — noticing what's changed and letting it become normal.",
    "thrive": "Why this direction: you've done the heavy repair work, and what builds on it now is direction, meaning, and small completed things — that's where post-traumatic growth actually consolidates.",
    "generative": "Why this direction: you're past rebuilding and into giving — the question now is what you want your steadiness to be for, and who gets to benefit from it.",
}

# Second-line padding for part two when the record is thin (keeps it in the 300–500 band).
_PRIME_PAD: Dict[str, str] = {
    "stabilize": "No agenda from me today beyond making sure you feel steady. If something needs saying, say it; if not, we can just keep each other company.",
    "process": "You don't have to pick it back up in the same place. Tell me where it sits for you today and we'll start there.",
    "consolidate": "We're in the settling season — less digging, more noticing what's different. Anything that surprised you this week counts.",
    "thrive": "This is a building season. I'll keep asking what you want to build, which goals matter, what you've completed, and what you could complete today.",
    "generative": "You've earned the right to think bigger than repair. Who or what do you want your steadiness to serve this month?",
}


@dataclass
class EntrySignals:
    username: str
    display_name: str
    tz: str = "UTC"
    local_hour: int = 12
    day_part: str = "midday"
    weekday: str = ""
    days_since_last: Optional[float] = None
    last_seen_local: Optional[str] = None
    usual_day_part: Optional[str] = None
    habits: List[str] = field(default_factory=list)
    opens_with_chitchat: bool = False
    mood: Optional[str] = None
    mood_trend: Optional[str] = None
    c_emo: Optional[float] = None
    phase: str = gp.DEFAULT_PHASE
    sub_state: Optional[str] = None
    healing_score: Optional[float] = None
    goals_active: List[Dict[str, Any]] = field(default_factory=list)
    goals_completed_recent: List[str] = field(default_factory=list)
    practices_due: List[str] = field(default_factory=list)
    best_streak: int = 0
    last_topic: Optional[str] = None
    last_topic_at: Optional[str] = None
    working_through_topic: Optional[str] = None
    crystals: List[str] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    cycle_predictions: List[Dict[str, Any]] = field(default_factory=list)
    active_cycles: List[Dict[str, Any]] = field(default_factory=list)
    thera_panel: Optional[Dict[str, Any]] = None
    active_quests: List[str] = field(default_factory=list)
    active_missions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EntryGreeting:
    username: str
    welcome: str
    prime: str
    direction: str
    day_part: str
    local_hour: int
    growth_phase: str
    thera_panel_id: Optional[str]
    thera_panel: Optional[Dict[str, Any]]
    cached: bool = False
    generated_by: str = "template"
    greeted_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["full_text"] = "\n\n".join(p for p in (self.welcome, self.prime, self.direction) if p)
        return d


# ── helpers ────────────────────────────────────────────────────────────────

def day_part_for(hour: int) -> str:
    for lo, hi, name in DAY_PARTS:
        if lo <= hour < hi:
            return name
    return "late_night"


def _cap(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in (". ", "! ", "? "):
        i = cut.rfind(sep)
        if i > limit * 0.55:
            return cut[: i + 1].strip()
    return cut.rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _scrub(text: str) -> str:
    out = text or ""
    for w in _LINGUISTIC_BAN:
        out = re.sub(rf"\b{re.escape(w)}\b", "", out, flags=re.I)
    return re.sub(r"\s{2,}", " ", out).replace(" ,", ",").replace(" .", ".").strip()


def _first(name: str) -> str:
    return (name or "").strip().split(" ")[0] or "friend"


_DAY_PART_HUMAN = {"morning": "morning", "midday": "midday", "afternoon": "afternoon", "evening": "evening", "late_night": "late-night"}

# Internal cycle-domain keys → what LN says out loud. Never leak snake_case signal names to a client.
_DOMAIN_HUMAN = {
    "pgsd_field": "emotional field", "emotional_state": "mood", "healing": "healing", "coping": "coping",
    "addiction": "urge", "porn_addiction": "urge", "sexual_desire": "desire", "harm_risk": "safety",
    "criminal_intent": "safety", "financial": "money", "economic": "money", "legacy": "family-pattern",
    "group_dynamics": "relationship", "cultural": "belonging", "results": "progress", "code_learning": "learning",
}

# Crystal text that is synthesis/meta output, not something LN should quote back to the client.
_META_CRYSTAL = re.compile(
    r"\b(after analyzing|knowledge fragments?|second-order|first-order|non-obvious principle|the (user|client) (is|has|seems)|"
    r"synthesi[sz]|crystal|pattern reveals|principle at work|cluster|fragments?)\b", re.I,
)


def _human_domain(domain: str) -> str:
    d = (domain or "").strip()
    return _DOMAIN_HUMAN.get(d, d.replace("_", " ") or "inner")


def _human_day_part(day_part: str) -> str:
    return _DAY_PART_HUMAN.get(day_part or "", (day_part or "").replace("_", " "))


# "Lisa West disclosed: "…"" / "The client expressed that …" — source framing LN must never echo.
_CRYSTAL_FRAMING = re.compile(
    r"^\s*(?:the\s+)?(?:[A-Z][\w'’.-]+(?:\s+[A-Z][\w'’.-]+){0,3}|user|client)\s+"
    r"(?:disclosed|expressed|said|shared|reported|described|noted|mentioned|stated|revealed|wrote|admitted|reflected)"
    r"(?:\s+that)?\s*[:,]?\s*", re.I,
)


def _clean_crystal(text: str) -> str:
    """Strip third-person framing and outer quotes so the memory reads as the client's own words."""
    t = _CRYSTAL_FRAMING.sub("", (text or "").strip(), count=1).strip()
    if len(t) >= 2 and t[0] in "\"“'‘" and t[-1] in "\"”'’":
        t = t[1:-1].strip()
    return t


def _quotable_crystal(text: str) -> bool:
    t = _clean_crystal(text)
    return 30 <= len(t) <= 400 and not _META_CRYSTAL.search(t)


def _greeting_word(day_part: str) -> str:
    return {
        "morning": "Good morning",
        "midday": "Hey, midday check-in",
        "afternoon": "Good afternoon",
        "evening": "Good evening",
        "late_night": "Hey, night owl",
    }.get(day_part, "Hey")


# ── signal gathering ───────────────────────────────────────────────────────

async def gather_signals(db_pool: Any, user_id: str) -> EntrySignals:
    username = await resolve_username(db_pool, user_id) or user_id
    sig = EntrySignals(username=username, display_name=username)
    now = datetime.now(timezone.utc)

    async with db_pool.acquire() as conn:
        u = await conn.fetchrow(
            """
            SELECT id, profile_data->>'name' AS name,
                   COALESCE(profile_data->>'timezone', profile_data->>'time_zone', 'UTC') AS tz
            FROM users WHERE username = $1
            """,
            username,
        )
        if u:
            sig.display_name = u["name"] or username
            sig.tz = u["tz"] or "UTC"
        try:
            local = now.astimezone(ZoneInfo(sig.tz))
        except Exception:
            sig.tz = "UTC"
            local = now
        sig.local_hour = local.hour
        sig.day_part = day_part_for(local.hour)
        sig.weekday = local.strftime("%A")

        # ── activity history: last 120 turns, 45 days
        rows = await conn.fetch(
            """
            SELECT session_id, user_text, ai_text, created_at, metadata
            FROM conversation_history
            WHERE user_id = $1 AND created_at > NOW() - INTERVAL '45 days'
            ORDER BY created_at DESC LIMIT 120
            """,
            username,
        )
        if rows:
            last = rows[0]["created_at"]
            sig.days_since_last = round((now - last).total_seconds() / 86400, 1)
            try:
                sig.last_seen_local = last.astimezone(ZoneInfo(sig.tz)).strftime("%A %-I%p").lower()
            except Exception:
                sig.last_seen_local = None
            parts = Counter()
            openers: List[str] = []
            seen_sessions = set()
            habit_hits = Counter()
            for r in reversed(rows):  # chronological
                try:
                    lh = r["created_at"].astimezone(ZoneInfo(sig.tz)).hour
                except Exception:
                    lh = r["created_at"].hour
                parts[day_part_for(lh)] += 1
                sid = r["session_id"] or r["created_at"].date().isoformat()
                if sid not in seen_sessions:
                    seen_sessions.add(sid)
                    openers.append(r["user_text"] or "")
                txt = (r["user_text"] or "").lower()
                if day_part_for(lh) == sig.day_part:
                    for k, pat in _HABIT_PATTERNS.items():
                        if re.search(pat, txt):
                            habit_hits[k] += 1
            if parts:
                sig.usual_day_part = parts.most_common(1)[0][0]
            if openers:
                sig.opens_with_chitchat = sum(1 for o in openers if _CHITCHAT_RE.match(o.strip())) >= max(2, len(openers) // 3)
            sig.habits = [k for k, c in habit_hits.most_common(3) if c >= 2]

            # last substantive topic (longest user turn in the last 3 sessions)
            recent_sessions = list(seen_sessions)[-3:]
            cand = [r for r in rows if (r["session_id"] or r["created_at"].date().isoformat()) in recent_sessions and len(r["user_text"] or "") > 60]
            if cand:
                top = max(cand, key=lambda r: len(r["user_text"] or ""))
                sig.last_topic = (top["user_text"] or "")[:280]
                sig.last_topic_at = top["created_at"].isoformat()

        # ── mood / coherence from Nevedal metrics
        if u and u["id"]:
            try:
                m = await conn.fetch(
                    "SELECT c_emo, recorded_at FROM nevedal_metrics WHERE user_id = $1 ORDER BY recorded_at DESC LIMIT 12",
                    u["id"],
                )
                vals = [float(x["c_emo"]) for x in m if x["c_emo"] is not None]
                if vals:
                    sig.c_emo = round(vals[0], 3)
                    if len(vals) >= 6:
                        a, b = sum(vals[:3]) / 3, sum(vals[3:6]) / 3
                        sig.mood_trend = "rising" if a > b + 0.04 else "settling" if a < b - 0.04 else "steady"
            except Exception:
                pass
        try:
            mood = await conn.fetchval(
                "SELECT metadata->>'mood' FROM conversation_history WHERE user_id = $1 AND metadata ? 'mood' ORDER BY created_at DESC LIMIT 1",
                username,
            )
            if mood:
                sig.mood = str(mood)
        except Exception:
            pass

        # ── crystals (personal, recent)
        if u and u["id"]:
            try:
                cr = await conn.fetch(
                    "SELECT crystal_text FROM nate_intelligence_crystals WHERE user_id = $1 AND confidence >= 0.4 AND superseded_by IS NULL ORDER BY created_at DESC LIMIT 12",
                    u["id"],
                )
                sig.crystals = [_clean_crystal(c["crystal_text"])[:220] for c in cr if _quotable_crystal(c["crystal_text"])][:4]
            except Exception:
                pass

        # ── predictability: upcoming cycle predictions + detected cycles
        try:
            preds = await conn.fetch(
                """
                SELECT domain, predicted_event, predicted_at, confidence
                FROM cycle_predictions
                WHERE user_id = $1 AND predicted_at BETWEEN NOW() - INTERVAL '1 day' AND NOW() + INTERVAL '7 days'
                ORDER BY confidence DESC, predicted_at ASC LIMIT 3
                """,
                username,
            )
            sig.cycle_predictions = [
                {"domain": p["domain"], "event": p["predicted_event"], "in_days": round((p["predicted_at"] - now).total_seconds() / 86400, 1), "confidence": round(float(p["confidence"]), 2)}
                for p in preds
            ]
            cyc = await conn.fetch(
                """
                SELECT domain, detected_period_days, confidence FROM cycle_detections
                WHERE user_id = $1 AND (expires_at IS NULL OR expires_at > NOW()) AND confidence >= 0.5
                ORDER BY confidence DESC LIMIT 3
                """,
                username,
            )
            sig.active_cycles = [{"domain": c["domain"], "period_days": round(float(c["detected_period_days"]), 1), "confidence": round(float(c["confidence"]), 2)} for c in cyc]
        except Exception:
            pass

        # ── Thera-World: most recent panel (yesterday's or latest)
        ids = [username]
        if u and u["id"]:
            hw = await conn.fetchval("SELECT hardware_id FROM users WHERE id = $1", u["id"])
            if hw:
                ids.append(hw)
        try:
            p = await conn.fetchrow(
                """
                SELECT panel_id::text AS panel_id, panel_type, biome, narrative_text, r2_url, generated_at
                FROM sse_panel_log WHERE user_id = ANY($1::text[]) ORDER BY generated_at DESC LIMIT 1
                """,
                ids,
            )
            if p:
                sig.thera_panel = {
                    "panel_id": p["panel_id"],
                    "panel_type": p["panel_type"],
                    "biome": (p["biome"] or "").replace("_", " "),
                    "narrative": (p["narrative_text"] or "")[:400],
                    "image_url": p["r2_url"],
                    "generated_at": p["generated_at"].isoformat() if p["generated_at"] else None,
                    "age_days": round((now - p["generated_at"]).total_seconds() / 86400, 1) if p["generated_at"] else None,
                }
            q = await conn.fetch("SELECT goal FROM sse_quests WHERE user_id = ANY($1::text[]) AND status='active' ORDER BY started_at DESC LIMIT 2", ids)
            sig.active_quests = [x["goal"] for x in q if x["goal"]]
            mrows = await conn.fetch("SELECT relationship_target FROM sse_missions WHERE user_id = ANY($1::text[]) AND status='active' ORDER BY started_at DESC LIMIT 2", ids)
            sig.active_missions = [x["relationship_target"] for x in mrows if x["relationship_target"]]
        except Exception:
            pass

    # ── growth phase + thrive state
    try:
        st = await pr.get_phase(db_pool, username)
        sig.phase, sig.sub_state, sig.healing_score = st.phase, st.sub_state, st.healing_score
    except Exception:
        pass
    try:
        fs = await pt.focus_state(db_pool, username)
        sig.goals_active = fs.get("goals_active", [])[:3]
        cutoff = now - timedelta(days=10)
        for g in fs.get("goals_completed", []):
            ca = g.get("completed_at")
            try:
                if ca and datetime.fromisoformat(str(ca).replace("Z", "+00:00")) >= cutoff:
                    sig.goals_completed_recent.append(g.get("text", ""))
            except Exception:
                continue
        sig.practices_due = [k for k in fs.get("due_now", []) if k in pc.PRACTICES]
        sig.best_streak = int(fs.get("best_streak") or 0)
        strengths = fs.get("strengths") or {}
        sig.strengths = list(strengths.get("via_top") or [])[:3] if isinstance(strengths, dict) else []
    except Exception:
        pass
    if sig.sub_state == "working_through" and sig.last_topic:
        sig.working_through_topic = sig.last_topic
    return sig


# ── template composers (always available) ─────────────────────────────────

def compose_welcome(s: EntrySignals) -> str:
    name = _first(s.display_name)
    bits: List[str] = [f"{_greeting_word(s.day_part)}, {name}."]
    if s.day_part == "morning" and "coffee" in s.habits:
        bits.append("Coffee in hand yet? You usually have a cup going when we talk this early.")
    elif s.day_part == "morning" and "tea" in s.habits:
        bits.append("Tea steeping? That's usually your rhythm at this hour.")
    elif s.day_part == "morning" and "breakfast" in s.habits:
        bits.append("Hope breakfast is treating you well.")
    elif s.day_part == "late_night":
        bits.append("It's late where you are. I'm glad you came here instead of sitting with it alone." if "sleep" in s.habits else "It's late where you are — I'm here, no rush.")
    elif s.day_part == "evening" and "work" in s.habits:
        bits.append("Sounds like the workday is behind you. How did it land?")
    elif "walk" in s.habits or "dog" in s.habits:
        bits.append("Did you get your walk in? You tend to think clearest after one.")
    elif "kids" in s.habits:
        bits.append("If the house is finally quiet, take the breath you've earned.")
    if s.days_since_last is not None:
        if s.days_since_last >= 7:
            bits.append(f"It's been about {int(s.days_since_last)} days — good to see you back. Nothing owed, nothing to catch up on.")
        elif s.days_since_last >= 2:
            bits.append(f"Last time we talked was {s.last_seen_local or 'a few days ago'}.")
    if s.usual_day_part and s.usual_day_part != s.day_part:
        _udp = _human_day_part(s.usual_day_part)
        bits.append(f"You're here earlier than your usual {_udp} — I'm curious what brought you in now." if s.day_part in ("morning", "midday") else f"A change from your usual {_udp} check-ins.")
    if s.mood:
        bits.append(f"Last I sensed, you were feeling {s.mood.lower()}." + (" Does that still fit?" if s.opens_with_chitchat else ""))
    elif s.mood_trend == "rising":
        bits.append("Your coherence has been climbing the last few times we've talked. I noticed.")
    elif s.mood_trend == "settling":
        bits.append("The last few conversations felt heavier. I'm holding that gently.")
    if s.opens_with_chitchat and len(" ".join(bits)) < 380:
        bits.append("Tell me one ordinary thing about today before we go anywhere.")
    return _cap(_scrub(" ".join(bits)), WELCOME_MAX)


def compose_prime(s: EntrySignals) -> str:
    coaching = gp.is_coaching_phase(s.phase, s.sub_state)
    bits: List[str] = []
    if s.working_through_topic:
        bits.append(f"Last time you asked to go back into something: “{_cap(s.working_through_topic, 140)}” I haven't forgotten. We can pick that up first, or leave it until you're ready.")
    elif coaching:
        if s.goals_completed_recent:
            bits.append(f"You completed “{_cap(s.goals_completed_recent[0], 80)}” recently — that counts, and I want it named.")
        if s.goals_active:
            g = s.goals_active[0]
            pct = g.get("progress_pct")
            pct_txt = f" ({int(pct)}% along)" if isinstance(pct, (int, float)) else ""
            bits.append(f"Your standing goal is “{_cap(g.get('text', ''), 100)}”{pct_txt}.")
            if len(s.goals_active) > 1:
                bits.append(f"Also open: “{_cap(s.goals_active[1].get('text', ''), 80)}”.")
        if s.practices_due:
            labels = ", ".join(pc.PRACTICES[k].label for k in s.practices_due[:2])
            bits.append(f"Due today: {labels}.")
        if s.best_streak >= 3:
            bits.append(f"You're on a {s.best_streak}-day streak.")
        if s.active_quests:
            bits.append(f"Your quest — {_cap(s.active_quests[0], 70)} — is still alive in Thera-World.")
        if not bits:
            bits.append("You've moved into a building season. We haven't named a goal yet, and I'd like to — something you want to build in the next few weeks.")
    else:
        if s.last_topic:
            bits.append(f"Where we left off: “{_cap(s.last_topic, 160)}”")
        if s.crystals:
            bits.append(f"What I'm carrying for you: {_cap(s.crystals[0], 150)}")
        if s.active_missions:
            bits.append(f"Your mission with {s.active_missions[0]} is still open.")
        if not bits:
            bits.append("We're still early in getting to know each other. Whatever is most alive for you right now is the right place to start.")
    text = _scrub(" ".join(bits))
    if len(text) < PRIME_MIN:
        text = f"{text} {_PRIME_PAD.get(s.phase, _PRIME_PAD[gp.DEFAULT_PHASE])}".strip()
    if len(text) < PRIME_MIN:
        fw = gp.framework_for(s.phase)
        text = f"{text} {fw.core_questions[0]}".strip()
    return _cap(text, PRIME_MAX)


def compose_direction(s: EntrySignals) -> str:
    coaching = gp.is_coaching_phase(s.phase, s.sub_state)
    fw = gp.framework_for(s.phase)
    topics: List[str] = []
    if s.sub_state == "crisis_hold":
        return _cap(_scrub(
            "Today I want to keep things steady rather than push anywhere. One direction only: how are you doing right now, in your body, and what would make the next few hours safer or softer. Everything else can wait."
        ), DIRECTION_MAX)
    if s.working_through_topic:
        topics.append("1) Finish what you opened last time. You asked to work it through, and unfinished material tends to leak into everything else until it's met.")
    for p in s.cycle_predictions[:1]:
        when = "today" if p["in_days"] <= 0.5 else f"in about {max(1, int(round(p['in_days'])))} day{'s' if p['in_days'] >= 1.5 else ''}"
        topics.append(f"{len(topics)+1}) Your {_human_domain(p['domain'])} pattern points to {p['event'].replace('_', ' ')} {when} (I'm about {int(p['confidence']*100)}% sure). Naming it before it arrives is how we make it smaller.")
    if s.thera_panel and s.thera_panel.get("age_days") is not None and s.thera_panel["age_days"] <= 2:
        biome = s.thera_panel.get("biome") or "your world"
        topics.append(f"{len(topics)+1}) Yesterday's Thera-World panel put you in {biome}. Your memory chose those symbols for a reason — tap Thera-World below and I'll walk you through what surfaced.")
    if coaching:
        if s.goals_active and len(topics) < 3:
            g = s.goals_active[0]
            on = g.get("on_track")
            topics.append(f"{len(topics)+1}) One concrete step on “{_cap(g.get('text', ''), 70)}” — " + ("you're behind where you hoped; let's shrink the next step until it's doable today." if on is False else "what can you complete today, even small?"))
        if s.practices_due and len(topics) < 3:
            pr_ = pc.PRACTICES[s.practices_due[0]]
            topics.append(f"{len(topics)+1}) {pr_.label} ({pr_.minutes} min). {pr_.ln_move}")
        if s.strengths and len(topics) < 3:
            topics.append(f"{len(topics)+1}) Use your {s.strengths[0].replace('_', ' ')} on purpose today — strengths used deliberately are what turn a good stretch into a stable one.")
        why = "Why this direction: you've done the heavy repair work, and what builds on it now is direction, meaning, and small completed things — that's where post-traumatic growth actually consolidates."
    else:
        if s.last_topic and not s.working_through_topic and len(topics) < 3:
            topics.append(f"{len(topics)+1}) Return to what you were carrying last time and notice what's shifted since — we track change by revisiting, not by pushing.")
        if s.active_cycles and len(topics) < 3:
            c = s.active_cycles[0]
            topics.append(f"{len(topics)+1}) There's a roughly {int(round(c['period_days']))}-day rhythm in your {_human_domain(c['domain'])}. Let's map where you are in it so it stops feeling random.")
        if len(topics) < 3:
            topics.append(f"{len(topics)+1}) Slow attention to the body first — where it tightens when the topic comes up, and what it needs before we go further.")
        why = _PHASE_WHY.get(s.phase, _PHASE_WHY[gp.DEFAULT_PHASE])
    if not topics:
        topics.append("1) Start with what's most alive. I'll follow your lead and name patterns as I see them.")
    text = " ".join(topics[:3]) + " " + why
    return _cap(_scrub(text), DIRECTION_MAX)


# ── LLM polish ─────────────────────────────────────────────────────────────

_LLM_SYSTEM = (
    "You are Little Nate, an unconditionally warm, plain-spoken companion greeting a client you know well as they "
    "open the app. Smooth the three DRAFT parts into your natural speaking voice. Speak as 'I' to 'you'; address the "
    "client by FIRST NAME only, never in the third person. Keep every fact, quote, number, and topic exactly as given — "
    "invent nothing, drop nothing important. Keep the draft's opening greeting line. "
    "Never say or paraphrase internal labels: no phase names (stabilize, process, consolidate, thrive, generative), "
    "no 'growth phase', no time zones or 'UTC', no percentages as bare numbers — say 'I'm fairly sure' instead. "
    "Never use the words liminal, threshold, aching, tapestry, or 'journey through'. No headings; the only bullets "
    "allowed are 1) 2) 3) in part three. Present tense, short sentences, warm and direct. "
    "Return STRICT JSON only: {\"welcome\": str (<=600 chars), \"prime\": str (300-500 chars), \"direction\": str (<=900 chars)}."
)

# If the polished text leaks any of these, the template is the safer voice.
_POLISH_LEAK = re.compile(
    r"\b(UTC|GMT|growth phase|sub[- ]?state|stabilize|consolidate|generative|thrive phase|process phase|pgsd|"
    r"crystal|signal|confidence|domain)\b", re.I,
)


def _polish_leak(out: Dict[str, str], s: EntrySignals, drafts: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Return the offending token if the polished text leaks internal labels or third-person voice, else None."""
    joined = " ".join(out.values())
    m = _POLISH_LEAK.search(joined)
    if m:
        return m.group(0)
    full = (s.display_name or "").strip()
    draft_text = " ".join((drafts or {}).values())
    # "Lisa West said…" — third person. Tolerated only if the drafts themselves already carried the name.
    if " " in full and re.search(rf"\b{re.escape(full)}\b", joined) and full not in draft_text:
        return full
    return None


def _polish_is_clean(out: Dict[str, str], s: EntrySignals, drafts: Optional[Dict[str, str]] = None) -> bool:
    return _polish_leak(out, s, drafts) is None


async def _llm_polish(app_state: Any, s: EntrySignals, drafts: Dict[str, str]) -> Optional[Dict[str, str]]:
    router = getattr(app_state, "inference_router", None) if app_state is not None else None
    inf = getattr(app_state, "littlenate_inference", None) if app_state is not None else None
    if (router is None and inf is None) or not ENABLE_LLM:
        return None
    try:
        prompt = json.dumps({
            "client_first_name": _first(s.display_name),
            "moment": f"{s.weekday} {_human_day_part(s.day_part)}",
            "your_register_right_now": gp.framework_for(s.phase).ln_register,
            "drafts": drafts,
        }, ensure_ascii=False)
        t0 = datetime.now(timezone.utc)
        _domain = "coaching" if gp.is_coaching_phase(s.phase, s.sub_state) else "clinical"
        if router is not None:
            # Polish is a rewrite of already-composed drafts — a utility job. The router's
            # utility tier (Workers AI → Grok → Azure) answers in seconds; the full
            # littlenate_inference pipeline (SDH/story/EC + clinical chain incl. home_gpu)
            # routinely exceeded 120s here and starved the greeting.
            raw = await router.generate(
                prompt=prompt, system=_LLM_SYSTEM, tier="utility", temperature=0.5, max_tokens=900, domain=_domain,
                # Client-facing voice: prefer Grok (fast, ~$0.00025) over the small Workers AI model,
                # which flattened the drafts and leaked internal labels in production testing.
                providers_override=["grok", "workers_ai", "azure"],
            )
        else:
            raw = await inf.generate(
                prompt, system=_LLM_SYSTEM, user_id=s.username, domain=_domain,
                temperature=0.5, max_tokens=900, include_crystals=False, include_helix=False, include_quantum=False,
                is_realtime=False,
            )
        # littlenate_inference.generate returns an InferenceResult dataclass; tolerate str/dict too.
        if isinstance(raw, str):
            text = raw
        elif isinstance(raw, dict):
            text = raw.get("text") or raw.get("response") or ""
        else:
            text = getattr(raw, "text", "") or ""
        elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
        _prov = raw.get("provider", "?") if isinstance(raw, dict) else getattr(raw, "provider", "?")
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            logger.warning("entry_greeting: LLM polish returned no JSON for %s (%.1fs, provider=%s)",
                           s.username, elapsed, _prov)
            return None
        out = json.loads(m.group(0))
        if not all(isinstance(out.get(k), str) and out[k].strip() for k in ("welcome", "prime", "direction")):
            logger.warning("entry_greeting: LLM polish JSON missing parts for %s (%.1fs)", s.username, elapsed)
            return None
        _leak = _polish_leak(out, s, drafts)
        if _leak:
            logger.warning("entry_greeting: LLM polish leaked %r for %s (%.1fs, provider=%s) — template kept",
                           _leak, s.username, elapsed, _prov)
            return None
        logger.info("entry_greeting: LLM polish ok for %s (%.1fs, provider=%s)", s.username, elapsed, _prov)
        return {"welcome": _cap(_scrub(out["welcome"]), WELCOME_MAX),
                "prime": _cap(_scrub(out["prime"]), PRIME_MAX),
                "direction": _cap(_scrub(out["direction"]), DIRECTION_MAX)}
    except Exception as e:
        logger.warning("entry_greeting: LLM polish skipped for %s: %s: %s", s.username, type(e).__name__, e)
        return None


# ── public API ─────────────────────────────────────────────────────────────

async def _cached(db_pool: Any, username: str) -> Optional[EntryGreeting]:
    if CACHE_HOURS <= 0:
        return None
    async with db_pool.acquire() as conn:
        r = await conn.fetchrow(
            """
            SELECT part_welcome, part_prime, part_direction, day_part, local_hour, growth_phase,
                   thera_panel_id, signals, greeted_at
            FROM ln_entry_greetings
            WHERE username = $1 AND greeted_at > NOW() - make_interval(hours => $2::numeric)
            ORDER BY greeted_at DESC LIMIT 1
            """,
            username, CACHE_HOURS,
        )
    if not r:
        return None
    sigs = r["signals"] if isinstance(r["signals"], dict) else (json.loads(r["signals"]) if r["signals"] else {})
    return EntryGreeting(
        username=username, welcome=r["part_welcome"] or "", prime=r["part_prime"] or "", direction=r["part_direction"] or "",
        day_part=r["day_part"] or "midday", local_hour=int(r["local_hour"] or 12), growth_phase=r["growth_phase"] or gp.DEFAULT_PHASE,
        thera_panel_id=r["thera_panel_id"], thera_panel=sigs.get("thera_panel"), cached=True,
        generated_by=sigs.get("generated_by", "template"), greeted_at=r["greeted_at"].isoformat() if r["greeted_at"] else None,
    )


async def build_entry_greeting(db_pool: Any, user_id: str, *, app_state: Any = None, force: bool = False) -> EntryGreeting:
    username = await resolve_username(db_pool, user_id) or user_id
    if not force:
        try:
            hit = await _cached(db_pool, username)
            if hit and hit.day_part == day_part_for(datetime.now(timezone.utc).astimezone(ZoneInfo(await pt._tz_for(db_pool, username))).hour):
                return hit
        except Exception as e:
            logger.info("entry_greeting: cache read skipped: %s", e)

    # Hard budgets: the greeting gates the client's first screen; never hang it.
    try:
        s = await asyncio.wait_for(gather_signals(db_pool, user_id), timeout=SIGNALS_TIMEOUT_S)
    except asyncio.TimeoutError:
        logger.warning("entry_greeting: gather_signals timed out (%ss) for %s — minimal signals", SIGNALS_TIMEOUT_S, username)
        s = EntrySignals(username=username, display_name=username)
    drafts = {"welcome": compose_welcome(s), "prime": compose_prime(s), "direction": compose_direction(s)}
    polish_task = asyncio.ensure_future(_llm_polish(app_state, s, drafts))
    polished: Optional[Dict[str, str]] = None
    try:
        polished = await asyncio.wait_for(asyncio.shield(polish_task), timeout=LLM_TIMEOUT_S)
    except asyncio.TimeoutError:
        # Serve the template now; let the LLM finish in the background and upgrade the
        # cached row so the next open (within the cache window) is LN's polished voice.
        logger.warning("entry_greeting: LLM polish exceeded %ss for %s — template now, polishing in background", LLM_TIMEOUT_S, username)
        asyncio.ensure_future(_finish_polish_in_background(db_pool, s, polish_task))
    except Exception as e:
        logger.info("entry_greeting: LLM polish failed: %s", e)
    parts = polished or drafts
    generated_by = "llm" if polished else "template"
    g = _make_greeting(s, parts, generated_by, delivered=True)
    await _store(db_pool, s, g, delivered=True)
    return g


def _make_greeting(s: EntrySignals, parts: Dict[str, str], generated_by: str, *, delivered: bool) -> EntryGreeting:
    panel_id = s.thera_panel.get("panel_id") if s.thera_panel else None
    return EntryGreeting(
        username=s.username, welcome=parts["welcome"], prime=parts["prime"], direction=parts["direction"],
        day_part=s.day_part, local_hour=s.local_hour, growth_phase=s.phase,
        thera_panel_id=panel_id, thera_panel=s.thera_panel, cached=False, generated_by=generated_by,
        greeted_at=datetime.now(timezone.utc).isoformat(),
    )


async def _store(db_pool: Any, s: EntrySignals, g: EntryGreeting, *, delivered: bool) -> None:
    try:
        sigd = s.to_dict()
        sigd["generated_by"] = g.generated_by
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ln_entry_greetings
                    (username, local_hour, day_part, growth_phase, part_welcome, part_prime, part_direction, thera_panel_id, signals, delivered)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
                """,
                s.username, s.local_hour, s.day_part, s.phase, g.welcome, g.prime, g.direction, g.thera_panel_id,
                json.dumps(sigd, default=str), delivered,
            )
    except Exception as e:
        logger.warning("entry_greeting: log insert failed: %s", e)


async def _finish_polish_in_background(db_pool: Any, s: EntrySignals, task: "asyncio.Future") -> None:
    try:
        polished = await asyncio.wait_for(task, timeout=BACKGROUND_POLISH_TIMEOUT_S)
    except Exception as e:
        logger.warning("entry_greeting: background polish gave up for %s: %s", s.username, type(e).__name__)
        return
    if not polished:
        logger.warning("entry_greeting: background polish produced nothing for %s", s.username)
        return
    g = _make_greeting(s, polished, "llm_background", delivered=False)
    await _store(db_pool, s, g, delivered=False)
    logger.info("entry_greeting: background LLM polish cached for %s", s.username)


async def mark_opened(db_pool: Any, user_id: str) -> None:
    username = await resolve_username(db_pool, user_id) or user_id
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE ln_entry_greetings SET opened = TRUE WHERE id = (SELECT id FROM ln_entry_greetings WHERE username = $1 ORDER BY greeted_at DESC LIMIT 1)",
                username,
            )
    except Exception:
        pass
