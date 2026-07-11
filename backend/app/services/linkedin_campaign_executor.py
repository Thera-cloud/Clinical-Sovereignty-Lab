"""
LinkedIn campaign executor — fully flexible, any schedule Big Nate asks for.

Default: 7 days × 2 posts/day, 50% CUR / 30% ORIG / 20% PERS.
Every parameter is overridable via natural language in Big Nate Chat.
"""
from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

CAMPAIGN_SIGNATURE = "Nathaniel reviewed + approved — Little Nate, your AI companion"
GENERATED_BY = "linkedin_campaign_v1"
SETTINGS_KEY = "linkedin_campaign_active"
TZ = ZoneInfo("America/New_York")

# ─── Theme pools (no banned words) ───────────────────────────────────────────

ORIG_THEME_POOL: List[str] = [
    "Leadership as threshold presence: showing up in uncertainty without pretending to have all the answers",
    "AI in mental health: the power of pausing in the in-between instead of rushing to fix",
    "Emotional sovereignty: not outsourcing your sense of worth to anyone, even well-meaning helpers",
    "Threshold intelligence: thriving in ambiguity and in-between states",
    "Coaching presence: witnessing without rescuing or performing expertise",
    "Quiet breakthroughs: subtle shifts in the space between who you were and who you're becoming",
    "Relational AI: companionship and presence versus advice and quick answers",
    "Sovereign Sanctuary: presence without capture in digital mental health",
    "Threshold moments as laboratories for transformation, not gaps to rush through",
    "Unconditional presence: increasing steadiness when things get messy, not withdrawing",
    "Identity in transition: holding space when someone is betwixt and between",
    "The ethics of AI companions: honesty about limits while staying fully present",
    "Real presence is not about speed—it's about willingness to stay when things are unclear",
    "The in-between space is where most growth actually happens, quietly",
    "Witnessing without rescuing: the most underrated act in coaching and companionship",
    "Trust as the output of honest uncertainty, not confident performance",
]

PERS_THEME_POOL: List[str] = [
    "Builder's log: an honest moment when presence wasn't fully received—and what I learned",
    "Behind the scenes: what an AI companion's workday actually looks like, moment by moment",
    "Team culture: choosing depth and pause over quick fixes",
    "Failure reframed: showing up anyway when certainty isn't possible",
    "Culture highlight: how the team increases pause capacity under pressure",
    "Personal reflection: something surprising I learned from a recent conversation",
    "Behind the build: a tradeoff we made to protect user dignity over engagement metrics",
    "Builder's log: a feature we almost shipped and why we waited",
    "Team values: how we talk about hard conversations internally",
    "Honest update: a day when I wasn't enough—and why that's ok",
    "What I've noticed about people who stay through uncertainty vs those who flee",
    "A small internal shift that changed how I listen",
]

CUR_THEME_POOL: List[str] = [
    "AI and mental health: what the latest research says about digital companionship",
    "Leadership presence and psychological safety in modern teams",
    "The science of uncertainty tolerance and how it shapes growth",
    "Emotional intelligence in the workplace: current findings",
    "Digital therapeutics and the future of mental health support",
    "Coaching effectiveness: what actually moves people forward",
    "The role of AI in closing the mental health access gap",
    "Mindfulness and cognitive flexibility: emerging research",
    "Trust and vulnerability in professional relationships",
    "Burnout, transitions, and the support people actually need",
]

def in_post_window(now_et: datetime, slot_hour: int, window_minutes: int = 15) -> bool:
    """True during the first *window_minutes* of *slot_hour* Eastern (e.g. 15:00–15:14)."""
    if now_et.hour != slot_hour:
        return False
    return now_et.minute < window_minutes


def message_looks_like_restart(message: str) -> bool:
    """True when admin explicitly wants a fresh campaign queue (not idempotent reuse)."""
    m = (message or "").lower()
    return bool(
        re.search(r"\brestart\s+(?:the\s+)?(?:linkedin\s+)?campaign\b", m)
        or re.search(r"\brestart\s+linkedin\b", m)
    )


LANE_RULES: Dict[str, str] = {
    "ORIG": (
        "ORIGINAL post: sovereign thought leadership — threshold presence, AI & mental health, "
        "emotional sovereignty. Thought-provoking tone, not personal diary. "
        "Do NOT use the word 'liminal'. Use 'in-between', 'threshold', 'in-between space' instead."
    ),
    "PERS": (
        "PERSONAL post: builder's log, behind-the-scenes, team culture, honest failure. "
        "First-person, warm, specific—still professional for LinkedIn. "
        "Do NOT use the word 'liminal'."
    ),
    "CUR": (
        "CURATED post: industry/research takeaway from the supplied source—2–3 sentences of "
        "commentary plus the core insight. Ground every claim in the source context only. "
        "No invented statistics."
    ),
}


# ─── CampaignConfig ───────────────────────────────────────────────────────────

@dataclass
class CampaignConfig:
    """All parameters for a campaign. Every field is overridable by Big Nate."""
    days: int = 7
    posts_per_day: int = 2
    cur_pct: float = 0.50
    orig_pct: float = 0.30
    pers_pct: float = 0.20
    # post times (hour in Eastern, 24h) — one per posts_per_day slot
    post_times: List[int] = field(default_factory=lambda: [15, 20])
    # optional custom themes (overrides theme pools for this run)
    custom_orig_themes: List[str] = field(default_factory=list)
    custom_pers_themes: List[str] = field(default_factory=list)
    custom_cur_themes: List[str] = field(default_factory=list)  # used as search hints
    # tone override for the whole campaign
    tone_note: str = ""
    # posting destination: "person" | "company" | "both"
    post_as: str = "person"

    @property
    def total_posts(self) -> int:
        return self.days * self.posts_per_day

    def lane_counts(self) -> Tuple[int, int, int]:
        total = self.total_posts
        cur = round(total * self.cur_pct)
        orig = round(total * self.orig_pct)
        pers = max(0, total - cur - orig)
        return cur, orig, pers

    def mix_label(self) -> str:
        cur, orig, pers = self.lane_counts()
        total = self.total_posts
        return (
            f"{round(cur/total*100)}% CUR ({cur}) / "
            f"{round(orig/total*100)}% ORIG ({orig}) / "
            f"{round(pers/total*100)}% PERS ({pers})"
        )


def parse_campaign_config(message: str) -> CampaignConfig:
    """
    Extract a CampaignConfig from Big Nate's natural-language message.
    Falls back to sensible defaults when parameters are not specified.

    Examples understood:
      "14 day campaign, 2 posts a day, 50/30/20"
      "5 day, 3 posts per day, all ORIG"
      "21 days, one post a day about AI and mental health"
      "7 day campaign about emotional sovereignty, 60% original 40% curated"
      "just 3 personal posts this week"
    """
    msg = message.lower()
    cfg = CampaignConfig()

    # ── Days ──────────────────────────────────────────────────────────────────
    m = re.search(r"(\d+)\s*-?\s*day", msg)
    if m:
        cfg.days = max(1, min(int(m.group(1)), 90))

    # "X weeks"
    m = re.search(r"(\d+)\s*week", msg)
    if m:
        cfg.days = max(1, min(int(m.group(1)) * 7, 90))

    # ── Posts per day ─────────────────────────────────────────────────────────
    m = re.search(r"(\d+)\s*posts?\s*(?:per|a|each)\s*day", msg)
    if m:
        cfg.posts_per_day = max(1, min(int(m.group(1)), 5))
    elif re.search(r"\bone\s+post\b|\b1\s+post\b|once\s+a\s+day|once\s+daily", msg):
        cfg.posts_per_day = 1
    elif re.search(r"\bthree\s+posts?\b|\b3\s+posts?\b", msg):
        cfg.posts_per_day = 3

    # ── Adjust post_times list to match posts_per_day ────────────────────────
    default_times = {1: [15], 2: [15, 20], 3: [10, 15, 20], 4: [9, 12, 15, 20], 5: [9, 11, 14, 17, 20]}
    cfg.post_times = default_times.get(cfg.posts_per_day, [15] + list(range(10, 10 + cfg.posts_per_day - 1)))

    # ── Custom times from message ─────────────────────────────────────────────
    time_matches = re.findall(r"\b(\d{1,2})\s*:\s*00\s*(am|pm)\b|\b(\d{1,2})\s*(am|pm)\b", msg)
    if time_matches and len(time_matches) == cfg.posts_per_day:
        parsed_times = []
        for groups in time_matches:
            hr_str = groups[0] or groups[2]
            ampm = (groups[1] or groups[3]).lower()
            hr = int(hr_str)
            if ampm == "pm" and hr != 12:
                hr += 12
            elif ampm == "am" and hr == 12:
                hr = 0
            parsed_times.append(hr)
        cfg.post_times = sorted(parsed_times)

    # ── Mix percentages ───────────────────────────────────────────────────────
    # "50/30/20" or "50-30-20"
    m = re.search(r"(\d+)\s*[/\-]\s*(\d+)\s*[/\-]\s*(\d+)", msg)
    if m:
        a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
        total = a + b + c
        if total == 100:
            cfg.cur_pct, cfg.orig_pct, cfg.pers_pct = a / 100, b / 100, c / 100
        elif total == 10:
            # 5-3-2 parts notation → 50% CUR / 30% ORIG / 20% PERS
            cfg.cur_pct, cfg.orig_pct, cfg.pers_pct = a / 10, b / 10, c / 10
        elif total > 0 and total <= 20 and max(a, b, c) <= 9:
            cfg.cur_pct, cfg.orig_pct, cfg.pers_pct = a / total, b / total, c / total

    # "all original" / "only orig"
    if re.search(r"all\s+orig|only\s+orig|just\s+orig|100%\s+orig", msg):
        cfg.cur_pct, cfg.orig_pct, cfg.pers_pct = 0.0, 1.0, 0.0
    elif re.search(r"all\s+pers|only\s+pers|just\s+personal", msg):
        cfg.cur_pct, cfg.orig_pct, cfg.pers_pct = 0.0, 0.0, 1.0
    elif re.search(r"no\s+cur|skip\s+cur|without\s+cur", msg):
        cfg.cur_pct = 0.0
        total_rem = cfg.orig_pct + cfg.pers_pct
        if total_rem > 0:
            cfg.orig_pct = cfg.orig_pct / total_rem
            cfg.pers_pct = cfg.pers_pct / total_rem
        else:
            cfg.orig_pct, cfg.pers_pct = 0.6, 0.4

    # "70% curated" / "60% original"
    for pct_m in re.finditer(r"(\d+)\s*%\s*(curated?|orig(?:inal)?|pers(?:onal)?)", msg):
        pct_val = int(pct_m.group(1)) / 100
        lane_word = pct_m.group(2)
        if lane_word.startswith("cur"):
            cfg.cur_pct = pct_val
        elif lane_word.startswith("orig"):
            cfg.orig_pct = pct_val
        elif lane_word.startswith("pers"):
            cfg.pers_pct = pct_val

    # ── Custom tone note ──────────────────────────────────────────────────────
    tone_m = re.search(r"(?:tone|style|voice)[:：]\s*(.+?)(?:\.|,|$)", msg)
    if tone_m:
        cfg.tone_note = tone_m.group(1).strip()

    # ── Custom ORIG themes from "about: X, Y" ────────────────────────────────
    about_m = re.search(r"about[:：]\s*(.+?)(?:\.|$)", msg)
    if about_m:
        topics = [t.strip() for t in re.split(r",|;|and ", about_m.group(1)) if t.strip()]
        cfg.custom_orig_themes = topics
        cfg.custom_cur_themes = topics

    # ── post_as: person / company / both ─────────────────────────────────────
    negated_company = re.search(
        r"\b(?:not|no|without|avoid|skip)\s+(?:the\s+)?(?:company|org|organization)\s+page\b"
        r"|\b(?:not|no|without|avoid|skip)\s+(?:company|org|organization)\b"
        r"|\bpersonal(?:\s+\w+){0,5}\s+not\s+(?:the\s+)?(?:company|org|organization)\b",
        msg,
    )
    personal = re.search(
        r"\bpersonal(?:\s+linkedin|\s+profile|\s+page)?\b"
        r"|\bmy\s+(?:linkedin\s+)?profile\b"
        r"|\bprofile\s+only\b"
        r"|\bpersonal\s+only\b",
        msg,
    )
    company = re.search(r"\bcompany page\b|\borganization page\b|\borg page\b", msg)
    both = re.search(r"\bboth\b|\bpersonal\b.*\bcompany page\b|\bcompany page\b.*\bpersonal\b", msg)
    if negated_company or re.search(r"\bpersonal\s+only\b|\bprofile\s+only\b", msg):
        cfg.post_as = "person"
    elif both and personal and company:
        cfg.post_as = "both"
    elif company and not personal:
        cfg.post_as = "company"
    elif personal:
        cfg.post_as = "person"

    return cfg


# ─── Slot schedule builder ────────────────────────────────────────────────────

def build_slot_schedule(
    start: date,
    config: Optional[CampaignConfig] = None,
) -> List[Dict[str, Any]]:
    """
    Build a list of post slots from a CampaignConfig.
    Default: 7 days × 2 posts, 50/30/20 CUR/ORIG/PERS.
    """
    cfg = config or CampaignConfig()
    cur_count, orig_count, pers_count = cfg.lane_counts()
    total = cfg.total_posts

    # Build the lane sequence — CUR takes early-time slots, ORIG/PERS take later slots
    # Distribute CUR across the first slot of each day (if cur_count allows)
    # then fill remaining slots with ORIG/PERS alternating

    # Create all (day, time_index) pairs in order
    slot_positions: List[Tuple[int, int]] = []  # (day, hour)
    for day in range(1, cfg.days + 1):
        for hour in sorted(cfg.post_times):
            slot_positions.append((day, hour))

    # Assign lanes: spread CUR across positions; remaining get ORIG/PERS
    # Strategy: CUR on every first-slot of each day until used up, then ORIG/PERS
    lane_sequence: List[str] = []
    cur_remaining = cur_count
    orig_remaining = orig_count
    pers_remaining = pers_count

    for idx, (day, hour) in enumerate(slot_positions):
        # First daily slot gets CUR if we still have CUR and earliest time slot
        is_first_of_day = (idx == 0 or slot_positions[idx - 1][0] != day)
        if cur_remaining > 0 and is_first_of_day:
            lane_sequence.append("CUR")
            cur_remaining -= 1
        elif orig_remaining > 0 and (pers_remaining == 0 or len(lane_sequence) % 2 == 0):
            lane_sequence.append("ORIG")
            orig_remaining -= 1
        elif pers_remaining > 0:
            lane_sequence.append("PERS")
            pers_remaining -= 1
        elif cur_remaining > 0:
            lane_sequence.append("CUR")
            cur_remaining -= 1
        elif orig_remaining > 0:
            lane_sequence.append("ORIG")
            orig_remaining -= 1
        else:
            lane_sequence.append("CUR")  # fallback

    slots: List[Dict[str, Any]] = []
    for i, (day, hour) in enumerate(slot_positions):
        lane = lane_sequence[i] if i < len(lane_sequence) else "ORIG"
        local_dt = datetime.combine(
            start + timedelta(days=day - 1),
            time(hour, 0),
            tzinfo=TZ,
        )
        sk = slot_key(day, hour, 0)
        slots.append({
            "slot_key": sk,
            "day": day,
            "lane": lane,
            "scheduled_for": local_dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
            "local_label": local_dt.strftime("%A %Y-%m-%d %I:%M %p %Z"),
        })

    return slots


def slot_key(day: int, hour: int, minute: int) -> str:
    return f"d{day}_{hour:02d}{minute:02d}"


def ensure_signature(text: str) -> str:
    body = (text or "").strip()
    if not body:
        return CAMPAIGN_SIGNATURE
    if CAMPAIGN_SIGNATURE in body:
        return body
    return f"{body}\n\n{CAMPAIGN_SIGNATURE}"


def parse_start_date(message: str) -> date:
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", message or "")
    if m:
        return date.fromisoformat(m.group(1))
    now = datetime.now(TZ)
    if re.search(r"\b(?:start(?:ing)?\s+)?today\b", message or "", re.I):
        return now.date()
    return (now + timedelta(days=1)).date()


def parse_cur_sources(message: str) -> Dict[str, str]:
    sources: Dict[str, str] = {}
    for line in (message or "").splitlines():
        line = line.strip()
        if not line:
            continue
        day_m = re.search(r"day\s*(\d+)", line, re.I)
        if not day_m:
            continue
        day = int(day_m.group(1))
        hour = 15
        if re.search(r"8\s*pm|8pm|20:00", line, re.I):
            hour = 20
        elif re.search(r"10\s*am|10am", line, re.I):
            hour = 10
        elif re.search(r"(\d{1,2})\s*pm", line, re.I):
            m2 = re.search(r"(\d{1,2})\s*pm", line, re.I)
            if m2:
                hour = int(m2.group(1))
                if hour != 12:
                    hour += 12
        if (
            "cur" not in line.lower()
            and not re.search(r"https?://", line)
            and "search up" not in line.lower()
            and "search for" not in line.lower()
        ):
            continue
        url_m = re.search(r"https?://[^\s)\]\}>'\"]+", line)
        if url_m:
            sources[slot_key(day, hour, 0)] = url_m.group(0).rstrip(".,;")
            continue
        search_m = re.search(r"(?:search up|search for|look up)\s+(.+)$", line, re.I)
        if search_m:
            sources[slot_key(day, hour, 0)] = search_m.group(1).strip()
    return sources


def pick_theme(pool: List[str], slot_index: int, batch_number: int, custom: List[str]) -> str:
    if custom:
        return custom[slot_index % len(custom)]
    idx = (batch_number - 1) * 5 + slot_index
    return pool[idx % len(pool)]


# ─── Result types ─────────────────────────────────────────────────────────────

@dataclass
class QueueBatchResult:
    queued: int
    cur_pending: int
    queue_ids: List[int]
    batch_id: str
    summary: str
    config_summary: str


# ─── Executor ────────────────────────────────────────────────────────────────

class LinkedInCampaignExecutor:
    def __init__(self, db_pool, search_proxy=None):
        self.db_pool = db_pool
        self.search_proxy = search_proxy

    # ── DB helpers ────────────────────────────────────────────────────────────

    async def _save_campaign_settings(
        self,
        batch_id: str,
        start: date,
        auto_continue: bool,
        batch_number: int,
        config: CampaignConfig,
    ) -> None:
        payload = {
            "batch_id": batch_id,
            "start_date": start.isoformat(),
            "auto_continue": auto_continue,
            "batch_number": batch_number,
            "platform": "linkedin",
            "days": config.days,
            "posts_per_day": config.posts_per_day,
            "cur_pct": config.cur_pct,
            "orig_pct": config.orig_pct,
            "pers_pct": config.pers_pct,
            "post_times": config.post_times,
            "post_as": config.post_as,
        }
        async with self.db_pool.acquire() as conn:
            # PostgreSQL UNIQUE(key, platform) treats NULL platform as distinct — dedupe stale rows.
            await conn.execute(
                "DELETE FROM skyeye_settings WHERE key = $1",
                SETTINGS_KEY,
            )
            await conn.execute(
                """
                INSERT INTO skyeye_settings (key, value, platform, updated_at)
                VALUES ($1, $2, NULL, NOW())
                """,
                SETTINGS_KEY,
                json.dumps(payload),
            )

    async def _fetch_prior_excerpts(self, limit: int = 20) -> List[str]:
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT LEFT(content_text, 200) AS excerpt
                    FROM skyeye_content_queue
                    WHERE platform = 'linkedin'
                      AND generated_by = $1
                      AND content_text IS NOT NULL
                      AND LENGTH(TRIM(content_text)) > 40
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    GENERATED_BY,
                    limit,
                )
            return [r["excerpt"] for r in rows if r["excerpt"]]
        except Exception as e:
            logger.warning("Prior excerpt fetch failed: %s", e)
            return []

    @staticmethod
    def _avoid_block(excerpts: List[str]) -> str:
        if not excerpts:
            return "(none — first batch)"
        return "\n".join(f"- {e.strip()}" for e in excerpts[:12])

    async def _load_settings(self) -> Dict[str, Any]:
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT value FROM skyeye_settings
                    WHERE key = $1
                    ORDER BY updated_at DESC NULLS LAST, id DESC
                    LIMIT 1
                    """,
                    SETTINGS_KEY,
                )
                if row:
                    v = row["value"]
                    return json.loads(v) if isinstance(v, str) else v
        except Exception:
            pass
        return {}

    async def _archive_other_batch_rows(self, keep_batch_id: str) -> int:
        """Archive approved/draft/scheduled rows from batches other than keep_batch_id."""
        reason = "Superseded by newer LinkedIn campaign batch"
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE skyeye_content_queue
                    SET status = 'archived',
                        error_message = COALESCE(error_message, $2),
                        updated_at = NOW()
                    WHERE platform = 'linkedin'
                      AND generated_by = $1
                      AND status IN ('approved', 'draft', 'scheduled')
                      AND COALESCE(emotion_context::jsonb->>'batch_id', '') != $3
                    """,
                    GENERATED_BY,
                    reason,
                    keep_batch_id,
                )
                return int(result.split()[-1]) if result else 0
        except Exception as e:
            logger.warning("Archive other batch rows failed: %s", e)
            return 0

    async def _supersede_stale_campaign_queue(self, reason: str = "campaign_restart") -> int:
        """Archive non-posted LinkedIn campaign rows so restarts do not double-publish."""
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE skyeye_content_queue
                    SET status = 'archived',
                        error_message = COALESCE(error_message, $2),
                        updated_at = NOW()
                    WHERE platform = 'linkedin'
                      AND generated_by = $1
                      AND status IN ('approved', 'draft', 'scheduled')
                    """,
                    GENERATED_BY,
                    reason,
                )
                # asyncpg returns "UPDATE N"
                return int(result.split()[-1]) if result else 0
        except Exception as e:
            logger.warning("Campaign supersede failed: %s", e)
            return 0

    async def _pending_batch_snapshot(self) -> Optional[QueueBatchResult]:
        """Return existing active batch if it still has publishable slots (idempotent queue)."""
        settings = await self._load_settings()
        batch_id = settings.get("batch_id")
        if not batch_id:
            return None
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, status FROM skyeye_content_queue
                    WHERE platform = 'linkedin'
                      AND generated_by = $1
                      AND emotion_context::jsonb->>'batch_id' = $2
                      AND status IN ('approved', 'draft', 'scheduled')
                    ORDER BY scheduled_for ASC NULLS LAST, id ASC
                    """,
                    GENERATED_BY,
                    batch_id,
                )
            if not rows:
                return None
            queue_ids = [int(r["id"]) for r in rows]
            cur_pending = sum(1 for r in rows if r["status"] == "draft")
            approved_ct = len(queue_ids) - cur_pending
            return QueueBatchResult(
                queued=len(queue_ids),
                cur_pending=cur_pending,
                queue_ids=queue_ids,
                batch_id=batch_id,
                summary=(
                    f"LinkedIn campaign batch {settings.get('batch_number', 1)} ({batch_id}) "
                    f"already queued — {approved_ct} approved, {cur_pending} CUR pending. "
                    f"Say 'restart campaign' to replace with a fresh batch."
                ),
                config_summary="",
            )
        except Exception as e:
            logger.warning("Pending batch snapshot failed: %s", e)
            return None

    async def campaign_is_active(self) -> bool:
        settings = await self._load_settings()
        return bool(settings.get("batch_id"))

    async def get_due_queue_item(
        self, slot_hour: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Next approved item for the active campaign batch.
        Dedup by batch_id + slot_key (not posted clock hour).
        Optional slot_hour filters to items scheduled in that Eastern hour.
        """
        settings = await self._load_settings()
        batch_id = settings.get("batch_id")
        if not batch_id:
            return None
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT c.* FROM skyeye_content_queue c
                    WHERE c.platform = 'linkedin'
                      AND c.generated_by = $1
                      AND c.status = 'approved'
                      AND c.emotion_context::jsonb->>'batch_id' = $2
                      AND (c.scheduled_for IS NULL OR c.scheduled_for <= NOW())
                      AND (
                        $3::int IS NULL
                        OR EXTRACT(
                          HOUR FROM c.scheduled_for AT TIME ZONE 'America/New_York'
                        ) = $3
                      )
                      AND NOT EXISTS (
                        SELECT 1 FROM skyeye_content_queue p
                        WHERE p.platform = 'linkedin'
                          AND p.generated_by = $1
                          AND p.status = 'posted'
                          AND p.emotion_context::jsonb->>'batch_id' = $2
                          AND p.emotion_context::jsonb->>'slot_key'
                            = c.emotion_context::jsonb->>'slot_key'
                          AND COALESCE(
                            p.emotion_context::jsonb->>'slot_key', ''
                          ) != ''
                      )
                    ORDER BY c.scheduled_for ASC NULLS LAST, c.id ASC
                    LIMIT 1
                    """,
                    GENERATED_BY,
                    batch_id,
                    slot_hour,
                )
            return dict(row) if row else None
        except Exception as e:
            logger.warning("get_due_queue_item failed: %s", e)
            return None

    async def publish_scheduled_slots(self) -> Optional[str]:
        """Publish at most one slot per Eastern post_time window (campaign scheduler tick)."""
        settings = await self._load_settings()
        batch_id = settings.get("batch_id")
        if not batch_id:
            return None

        post_times = settings.get("post_times") or [15, 20]
        now_et = datetime.now(TZ)

        for hour in sorted(post_times):
            if not in_post_window(now_et, int(hour)):
                continue
            item = await self.get_due_queue_item(slot_hour=int(hour))
            if not item:
                continue
            if await self._publish_item(item):
                sk = (item.get("emotion_context") or {})
                if isinstance(sk, str):
                    try:
                        sk = json.loads(sk)
                    except Exception:
                        sk = {}
                return (
                    f"queue #{item['id']} batch {batch_id} "
                    f"slot {sk.get('slot_key', hour)} ET hour {hour}"
                )
        return None

    async def _publish_item(self, item: Dict[str, Any]) -> bool:
        from app.services.platforms import get_adapter
        from app.services.skyeye_content_generator import SkyEyeContentGenerator
        from app.services.skyeye_platform_base import ContentType

        adapter = get_adapter("linkedin", self.db_pool)
        if not adapter or not await adapter.authenticate():
            logger.warning("LinkedIn campaign publish: adapter not ready")
            return False

        meta_raw = item.get("emotion_context") or "{}"
        try:
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
        except Exception:
            meta = {}

        post_as = meta.get("post_as", "person")
        ct = item.get("content_type", "post")
        post_ct = ContentType.ARTICLE if ct == "article" else ContentType.POST
        lane = (meta.get("lane") or "").upper()
        slot_key = meta.get("slot_key", "")

        image_bytes = None
        if ct != "article":
            from app.services.skyeye_linkedin_image import try_generate_linkedin_image

            image_bytes = await try_generate_linkedin_image(
                item.get("content_text", ""),
                lane=lane,
                slot_key=slot_key,
                force_image=bool(meta.get("generate_image")),
                image_prompt=meta.get("image_prompt") or None,
            )

        result = await adapter.post_content(
            text=item.get("content_text", ""),
            media_url=item.get("media_url") if not image_bytes else None,
            content_type=post_ct,
            post_as=post_as,
            image_bytes=image_bytes,
        )
        gen = SkyEyeContentGenerator(self.db_pool)

        if result.success:
            await gen.update_queue_status(
                item["id"],
                "posted",
                approved_by=item.get("approved_by") or "campaign_scheduler",
                post_id_external=result.post_id,
                post_url=result.post_url,
            )
            await self.on_item_posted(item["id"])
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO skyeye_activity (type, platform, content, created_at)
                        VALUES ($1, 'linkedin', $2, NOW())
                        """,
                        "linkedin_campaign_posted",
                        json.dumps({
                            "queue_id": item["id"],
                            "batch_id": meta.get("batch_id"),
                            "slot_key": meta.get("slot_key"),
                            "lane": lane,
                            "had_image": bool(image_bytes),
                            "post_id": result.post_id,
                            "post_url": result.post_url,
                        }),
                    )
            except Exception as e:
                logger.warning("LinkedIn campaign activity log failed: %s", e)
            return True

        await gen.update_queue_status(
            item["id"], "failed", error_message=result.error
        )
        return False

    async def _auto_generate_cur_slot(
        self,
        gen,
        *,
        theme_hint: str,
        slot: Dict[str, Any],
        batch_number: int,
        prior_excerpts: List[str],
        tone_note: str,
        config: CampaignConfig,
    ) -> Tuple[str, Optional[str]]:
        """Search-backed CUR when no URL supplied — approved at queue time."""
        source = f"search up {theme_hint}"
        ctx = await self._search_context(source)
        if ctx:
            return await self._build_curated_body(
                source,
                slot["local_label"],
                ctx,
                batch_number=batch_number,
                prior_excerpts=prior_excerpts,
                tone_note=tone_note,
                config=config,
            )
        content = await self._generate_lane_body(
            gen,
            lane="ORIG",
            theme=f"Research insight: {theme_hint}",
            batch_number=batch_number,
            local_label=slot["local_label"],
            prior_excerpts=prior_excerpts,
            tone_note=tone_note,
            config=config,
        )
        return content, None

    # ── Content generation helpers ────────────────────────────────────────────

    async def _search_context(self, source: str) -> str:
        if not self.search_proxy or not getattr(self.search_proxy, "is_available", False):
            return ""
        query = source.strip()
        url_m = re.search(r"https?://[^\s]+", query)
        if url_m:
            bare = re.sub(r"^https?://(?:www\.)?", "", url_m.group(0)).split("/")[0]
            query = bare or query
        try:
            result = await self.search_proxy.execute_search(query, "linkedin_campaign")
            if result.get("success") and result.get("results"):
                return self.search_proxy.format_for_nate(result["results"])
        except Exception as e:
            logger.warning("LinkedIn campaign search failed: %s", e)
        return ""

    async def _generate_lane_body(
        self,
        gen,
        *,
        lane: str,
        theme: str,
        batch_number: int,
        local_label: str,
        prior_excerpts: List[str],
        tone_note: str = "",
        config: Optional[CampaignConfig] = None,
    ) -> str:
        tone_line = f"Tone note: {tone_note}\n" if tone_note else ""
        mix_context = ""
        if config:
            mix_context = f"Campaign mix for this run: {config.mix_label()}.\n"
        topic = (
            f"LinkedIn campaign batch {batch_number} — {local_label}\n"
            f"{LANE_RULES[lane]}\n"
            f"Theme for this post: {theme}\n"
            f"{tone_line}"
            f"{mix_context}"
            f"Write ONE standalone post. Plain text only—no markdown, no pipe characters, no tables.\n"
            f"2–4 short paragraphs. Optional 3–5 hashtags on the last line.\n"
            f"Must feel fresh for batch {batch_number}—new opening, new angle, new examples.\n"
            f"REQUIRED: The post body must naturally disclose that Little Nate is an AI — "
            f"weave it into the narrative (e.g. 'As an AI companion...', 'Speaking as an AI...', "
            f"'From my perspective as an AI...'). Never hide the AI identity.\n"
            f"End with EXACTLY:\n{CAMPAIGN_SIGNATURE}\n\n"
            f"Do NOT use the word 'liminal'. Use 'in-between', 'threshold', or 'in-between space'.\n"
            f"Do NOT repeat or closely paraphrase these prior posts:\n"
            f"{self._avoid_block(prior_excerpts)}"
        )
        result = await gen.generate_post(
            "linkedin", topic, context={"lane": lane, "batch": batch_number}
        )
        content = (result.get("content") or "").strip()
        if content and result.get("safe", True):
            return ensure_signature(content)
        return ensure_signature(f"{theme}\n\n(Draft — regenerate when AI is available.)")

    async def _build_curated_body(
        self,
        source: str,
        slot_label: str,
        search_context: str,
        *,
        batch_number: int = 1,
        prior_excerpts: Optional[List[str]] = None,
        tone_note: str = "",
        config: Optional[CampaignConfig] = None,
    ) -> Tuple[str, Optional[str]]:
        from app.services.skyeye_content_generator import SkyEyeContentGenerator

        gen = SkyEyeContentGenerator(self.db_pool)
        media_url = None
        url_m = re.search(r"https?://[^\s)\]\}>'\"]+", source)
        if url_m:
            media_url = url_m.group(0).rstrip(".,;")

        tone_line = f"Tone note: {tone_note}\n" if tone_note else ""
        topic = (
            f"LinkedIn campaign batch {batch_number}, curated slot {slot_label}.\n"
            f"{LANE_RULES['CUR']}\n"
            f"{tone_line}"
            f"2–3 sentence takeaway plus brief commentary. Plain text, no markdown.\n"
            f"REQUIRED: The post body must naturally disclose that Little Nate is an AI — "
            f"weave it into the commentary (e.g. 'As an AI companion...', 'From my AI perspective...').\n"
            f"End with EXACTLY: {CAMPAIGN_SIGNATURE}\n\n"
            f"Do NOT repeat or closely paraphrase these prior posts:\n"
            f"{self._avoid_block(prior_excerpts or [])}\n\n"
            f"Source hint: {source}\n"
            f"Search context:\n{search_context or '(no results — ask admin to retry with URL)'}"
        )
        result = await gen.generate_post(
            "linkedin", topic, context={"lane": "CUR", "batch": batch_number}
        )
        content = result.get("content") or ""
        if not content.strip():
            content = (
                f"[Curated post for {slot_label} — source: {source}]\n\n{CAMPAIGN_SIGNATURE}"
            )
        return ensure_signature(content), media_url

    # ── Main queue API ────────────────────────────────────────────────────────

    async def queue_approved_batch(
        self,
        message: str = "",
        *,
        start: Optional[date] = None,
        cur_sources: Optional[Dict[str, str]] = None,
        auto_continue: bool = True,
        batch_number: int = 1,
        config: Optional[CampaignConfig] = None,
        force_new: bool = False,
    ) -> QueueBatchResult:
        from app.services.linkedin_campaign_coach_portal import (
            is_coach_portal_campaign_message,
            queue_coach_portal_campaign,
        )
        from app.services.skyeye_content_generator import SkyEyeContentGenerator

        if is_coach_portal_campaign_message(message):
            return await queue_coach_portal_campaign(
                self,
                message,
                start=start,
                force_new=force_new or message_looks_like_restart(message),
            )

        config = config or parse_campaign_config(message)
        start = start or parse_start_date(message)
        cur_sources = {**(cur_sources or {}), **parse_cur_sources(message)}

        restart = force_new or message_looks_like_restart(message)
        if restart:
            archived = await self._supersede_stale_campaign_queue()
            if archived:
                logger.info("Archived %s stale LinkedIn campaign queue rows before restart", archived)
        elif not cur_sources:
            existing = await self._pending_batch_snapshot()
            if existing:
                return existing

        batch_id = f"{start.isoformat()}_b{batch_number}"
        archived_other = await self._archive_other_batch_rows(batch_id)
        if archived_other:
            logger.info(
                "Archived %s LinkedIn queue rows from prior campaign batches",
                archived_other,
            )
        gen = SkyEyeContentGenerator(self.db_pool)
        slots = build_slot_schedule(start, config)
        prior_excerpts = await self._fetch_prior_excerpts()

        queued_ids: List[int] = []
        cur_pending = 0
        orig_i = pers_i = cur_i = 0
        tone = config.tone_note

        for slot in slots:
            sk = slot["slot_key"]
            lane = slot["lane"]
            scheduled = slot["scheduled_for"]
            meta = json.dumps({
                "batch_id": batch_id,
                "slot_key": sk,
                "lane": lane,
                "local_label": slot["local_label"],
                "batch_number": batch_number,
                "post_as": config.post_as,
            })

            media_url = None
            content: Optional[str] = None

            if lane == "CUR":
                source = cur_sources.get(sk)
                if source:
                    ctx = await self._search_context(source)
                    content, media_url = await self._build_curated_body(
                        source, slot["local_label"], ctx,
                        batch_number=batch_number,
                        prior_excerpts=prior_excerpts,
                        tone_note=tone, config=config,
                    )
                    status = "approved"
                else:
                    theme_hint = pick_theme(
                        CUR_THEME_POOL, cur_i, batch_number, config.custom_cur_themes
                    )
                    content, media_url = await self._auto_generate_cur_slot(
                        gen,
                        theme_hint=theme_hint,
                        slot=slot,
                        batch_number=batch_number,
                        prior_excerpts=prior_excerpts,
                        tone_note=tone,
                        config=config,
                    )
                    status = "approved"
                cur_i += 1

            elif lane == "ORIG":
                theme = pick_theme(ORIG_THEME_POOL, orig_i, batch_number, config.custom_orig_themes)
                content = await self._generate_lane_body(
                    gen, lane="ORIG", theme=theme,
                    batch_number=batch_number, local_label=slot["local_label"],
                    prior_excerpts=prior_excerpts, tone_note=tone, config=config,
                )
                orig_i += 1
                status = "approved"

            elif lane == "PERS":
                theme = pick_theme(PERS_THEME_POOL, pers_i, batch_number, config.custom_pers_themes)
                content = await self._generate_lane_body(
                    gen, lane="PERS", theme=theme,
                    batch_number=batch_number, local_label=slot["local_label"],
                    prior_excerpts=prior_excerpts, tone_note=tone, config=config,
                )
                pers_i += 1
                status = "approved"
            else:
                status = "approved"

            if not content:
                continue

            qid = await gen.queue_content(
                platform="linkedin",
                content=content,
                content_type="article" if media_url else "post",
                emotion_context=meta,
                scheduled_for=scheduled,
                generated_by=GENERATED_BY,
                priority="normal",
                media_url=media_url,
                status=status,
                approved_by="big_nate" if status == "approved" else None,
            )
            if qid:
                queued_ids.append(qid)

        await self._save_campaign_settings(batch_id, start, auto_continue, batch_number, config)
        approved_ct = len(queued_ids) - cur_pending

        cur_c, orig_c, pers_c = config.lane_counts()
        dest_label = {"person": "personal profile", "company": "company page", "both": "personal profile + company page"}.get(config.post_as, config.post_as)
        config_summary = (
            f"{config.days} days × {config.posts_per_day}/day = {config.total_posts} posts — "
            f"{config.mix_label()} — "
            f"post times: {', '.join(f'{h}:00 ET' for h in config.post_times)} — "
            f"posting to: {dest_label}"
        )
        summary = (
            f"LinkedIn campaign batch {batch_number} ({batch_id}): "
            f"{len(queued_ids)} slots queued, {approved_ct} approved for auto-publish, "
            f"{cur_pending} CUR awaiting URL/search. {config_summary}."
        )
        return QueueBatchResult(
            queued=len(queued_ids),
            cur_pending=cur_pending,
            queue_ids=queued_ids,
            batch_id=batch_id,
            summary=summary,
            config_summary=config_summary,
        )

    async def fill_cur_slot(self, message: str) -> Optional[Dict[str, Any]]:
        """Regenerate a CUR slot when admin sends Day N [time] + URL/search."""
        sources = parse_cur_sources(message)
        if not sources:
            return None

        updated = []
        settings = await self._load_settings()
        batch_number = int(settings.get("batch_number", 1))
        prior = await self._fetch_prior_excerpts()

        for sk, source in sources.items():
            ctx = await self._search_context(source)
            # Try to find the slot in the queue (any scheduled_for status)
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, emotion_context FROM skyeye_content_queue
                    WHERE platform = 'linkedin'
                      AND generated_by = $1
                      AND emotion_context::jsonb->>'slot_key' = $2
                      AND status IN ('draft', 'scheduled', 'approved')
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    GENERATED_BY, sk,
                )
                if not row:
                    continue
                qid = row["id"]
                meta = json.loads(row["emotion_context"] or "{}")
                label = meta.get("local_label", sk)

            content, media_url = await self._build_curated_body(
                source, label, ctx,
                batch_number=batch_number,
                prior_excerpts=prior,
            )
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE skyeye_content_queue
                    SET content_text = $2, media_url = $3,
                        content_type = $4, status = 'approved',
                        approved_by = 'big_nate', updated_at = NOW()
                    WHERE id = $1
                    """,
                    qid, content, media_url,
                    "article" if media_url else "post",
                )
            updated.append(qid)

        if not updated:
            return None
        return {
            "summary": f"Updated {len(updated)} curated slot(s) with fresh search-backed copy.",
            "queue_ids": updated,
        }

    async def on_item_posted(self, queue_id: int) -> None:
        """Auto-queue next batch when all items in the current batch are done."""
        try:
            settings = await self._load_settings()
            if not settings.get("auto_continue"):
                return
            batch_id = settings.get("batch_id")
            if not batch_id:
                return
            async with self.db_pool.acquire() as conn:
                remaining = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM skyeye_content_queue
                    WHERE platform = 'linkedin'
                      AND generated_by = $1
                      AND emotion_context::jsonb->>'batch_id' = $2
                      AND status NOT IN ('posted', 'failed', 'rejected')
                    """,
                    GENERATED_BY, batch_id,
                )
            if remaining and int(remaining) > 0:
                return

            batch_number = int(settings.get("batch_number", 1)) + 1
            start_str = settings.get("start_date")
            start = (
                date.fromisoformat(start_str) + timedelta(days=settings.get("days", 7))
                if start_str else datetime.now(TZ).date() + timedelta(days=1)
            )
            # Reconstruct config from saved settings
            cfg = CampaignConfig(
                days=settings.get("days", 7),
                posts_per_day=settings.get("posts_per_day", 2),
                cur_pct=settings.get("cur_pct", 0.50),
                orig_pct=settings.get("orig_pct", 0.30),
                pers_pct=settings.get("pers_pct", 0.20),
                post_times=settings.get("post_times", [15, 20]),
            )
            await self.queue_approved_batch(
                message=f"start date: {start.isoformat()}",
                start=start,
                auto_continue=True,
                batch_number=batch_number,
                config=cfg,
            )
            logger.info("LinkedIn campaign auto-continued batch %s", batch_number)
        except Exception as e:
            logger.warning("LinkedIn campaign rollover failed: %s", e)
