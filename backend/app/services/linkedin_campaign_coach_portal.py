"""
Coach Portal Acquisition — 5-week LinkedIn campaign (verbatim brief).

10 posts: Tue–Thu weekly, 3 PM + 8 PM ET, founder voice + Post-2 images.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from app.services.linkedin_campaign_executor import (
    GENERATED_BY,
    SETTINGS_KEY,
    QueueBatchResult,
    TZ,
)

logger = logging.getLogger(__name__)

CAMPAIGN_TEMPLATE = "coach_portal_acquisition"
WEEKS = 5
POST_TIMES = [15, 20]
POST1_MAX_CHARS = 1200
POST2_MAX_CHARS = 300
WEEKDAY_ROTATION = (1, 2, 3, 1, 2)  # Tue, Wed, Thu, Tue, Wed

BANNED_WORDS = re.compile(
    r"\b(sentient|quantum|revolutionary|magic|dojo|night\s*school|"
    r"ble\s*mesh|path-c|nevedal|c_emo|gap|"
    r"cure|diagnose|diagnosis|guaranteed\s+outcomes|"
    r"replace\s+your\s+therapist)\b",
    re.IGNORECASE,
)
ALL_CAPS_URGENCY = re.compile(r"\b[A-Z]{4,}\b")

DETECTION_PHRASES = (
    "coach portal acquisition",
    "skyeye campaign brief",
    "skyeeye campaign brief",
    "pre-session briefings",
    "walk in already knowing",
    "coach_portal_acquisition",
    "the ai answers to you",
    "one continuous thread",
    "support at the moment of care",
    "platform behind the companion",
)


@dataclass(frozen=True)
class CoachPortalPost:
    week: int
    slot: str  # "post1" | "post2"
    theme: str
    text: str
    image_prompt: str = ""
    max_chars: int = POST1_MAX_CHARS
    needs_image: bool = False
    extra_compliance: bool = False


# ─── Verbatim copy from SKYEYE CAMPAIGN BRIEF ───────────────────────────────

WEEK_THEMES = (
    "PRE-SESSION BRIEFINGS",
    "COACH-CONTROLLED AI",
    "CONTINUITY",
    "LIVE SESSION ASSISTANT",
    "COMBINED",
)

POSTS: Tuple[CoachPortalPost, ...] = (
    CoachPortalPost(
        1, "post1", WEEK_THEMES[0],
        """Every session used to start the same way: "So… how have you been since last time?" And I'd spend the first ten minutes reconstructing a week I wasn't there for.

What if you already knew?

Here's something most people don't know about Little Nate — the AI companion you've been hearing about. He's not just for the person using him. There's a platform behind him, built for coaches and clinicians.

When your client talks to Little Nate between sessions, you get a brief before they sit down — what they've been carrying, what surfaced, where they are today. Not a transcript. A summary that lets you walk in mid-thread instead of starting from zero.

Ten minutes of "catching up" becomes ten minutes of actual work.

No other platform can do this, because no other platform has a companion generating that context in the first place.

That's the difference between practice management and practice partnership.

This is the part of Little Nate professionals haven't seen yet. I'll be sharing more this week.""",
    ),
    CoachPortalPost(
        1, "post2", WEEK_THEMES[0],
        """You shouldn't have to spend the first ten minutes of a session catching up on a week you weren't there for.

With Little Nate, you walk in already knowing.

That's session prep, reimagined.""",
        image_prompt=(
            "A calm, minimal scene in deep black and gold: an open notebook or a single "
            "soft-glowing card on a clean desk, with the words \"Walk in already knowing\" "
            "in elegant serif. Warm, quiet, professional — the feeling of being prepared, "
            "not rushed. No faces, no UI screenshots, no sci-fi. "
            "Palette #0A0A0A background, #C9A962 gold accent. Text in image at most 6 words."
        ),
        max_chars=POST2_MAX_CHARS,
        needs_image=True,
    ),
    CoachPortalPost(
        2, "post1", WEEK_THEMES[1],
        """The number one thing professionals say to me about AI in this work:
"I'm afraid it'll override me."

Good. You should be. An AI that makes clinical decisions on its own doesn't belong anywhere near a vulnerable person.

So we built Little Nate the opposite way.

With the coach platform behind him, you govern how Little Nate shows up for each client. You decide whether he simply observes, gently suggests, or respectfully challenges. You set the pacing. You choose the focus. You can place a hold on a topic that isn't ready to be touched.

He doesn't decide the direction of care. You do. He works inside the boundaries you set, for the client you know better than any model ever will.

That's not a black box. It's an instrument — and you're holding it.

The fear of AI replacing the professional is legitimate. The answer isn't less AI. It's AI that answers to you.

More this week on how that works.""",
    ),
    CoachPortalPost(
        2, "post2", WEEK_THEMES[1],
        """AI that makes its own clinical calls doesn't belong near a vulnerable person.

With Little Nate, you set the boundaries. He works inside them.

The AI answers to you — not the other way around.""",
        image_prompt=(
            "Deep black and gold, minimal. A single hand adjusting a dial or a set of clean "
            "sliders/controls (abstract, elegant — not a cockpit), suggesting a professional "
            "in command of a calm instrument. Words: \"You're in command.\" "
            "No faces, warm and controlled feeling, #0A0A0A / #C9A962. "
            "Text in image at most 6 words."
        ),
        max_chars=POST2_MAX_CHARS,
        needs_image=True,
    ),
    CoachPortalPost(
        3, "post1", WEEK_THEMES[2],
        """A client shouldn't have to tell their story from the beginning every time they meet someone new in their own care.

But that's how most of it works. They tell the intake person. Then the coach. Then, if it escalates, the clinician. Same painful story, three times, to three strangers — each starting from zero.

We built Sovereign Sanctuary as one continuous thread instead.

Little Nate remembers what your client shares. You, the coach, see what he saw. And when a moment needs a licensed professional, they step in already holding the context — not asking the client to start over.

The client experiences one relationship, not a relay race. You never lose the thread between sessions. The professional never inherits a blank page.

Companion, coach, clinician — one system, one memory, one person at the center of it.

That's not three tools stapled together. It's continuity of care, the way it should have worked all along.""",
    ),
    CoachPortalPost(
        3, "post2", WEEK_THEMES[2],
        """Your client shouldn't have to retell their story to every new person in their own care.

Companion. Coach. Clinician. One continuous thread.

Nobody starts from zero.""",
        image_prompt=(
            "Deep black and gold. A single unbroken golden thread or line weaving gently "
            "through three soft points/nodes, then continuing — suggesting continuity and "
            "connection without breaks. Elegant, minimal, warm. Words: \"One continuous thread.\" "
            "No faces, no UI. #0A0A0A / #C9A962. Text in image at most 6 words."
        ),
        max_chars=POST2_MAX_CHARS,
        needs_image=True,
    ),
    CoachPortalPost(
        4, "post1", WEEK_THEMES[3],
        """Most tools help you after the session. You write your notes, you code the visit, you try to remember what mattered — all from memory, hours later.

What if support showed up during the work, when it actually helps?

With Little Nate's platform, professionals have a quiet co-pilot in the room. As the session unfolds, it can surface relevant context from the client's history, gently flag what may deserve attention, and offer coding suggestions — all for you to use, ignore, or override at your discretion.

Let me be clear about the boundary, because it matters: the platform never makes a clinical decision. It surfaces; you decide. Everything clinical stays in the hands of the licensed professional it's meant to support. The AI is a second set of eyes, never a second opinion that overrules yours.

Fewer things slip past in the moment. Less scrambling afterward. More of your attention where it belongs — on the person in front of you.

Support at the moment of care, not a reconstruction after it.""",
        extra_compliance=True,
    ),
    CoachPortalPost(
        4, "post2", WEEK_THEMES[3],
        """Most tools help after the session.

Little Nate is a quiet co-pilot during it — surfacing context and flags for you to use at your discretion.

Your attention stays where it belongs: on the person in front of you.""",
        image_prompt=(
            "Deep black and gold, calm and focused. Two soft overlapping circles or a gentle "
            "\"second set of eyes\" motif — suggesting quiet support and presence, not surveillance "
            "or tech-overload. Warm, unobtrusive. Words: \"Support in the moment.\" "
            "No faces, no clinical imagery, no fake dashboards. #0A0A0A / #C9A962. "
            "Text in image at most 6 words."
        ),
        max_chars=POST2_MAX_CHARS,
        needs_image=True,
        extra_compliance=True,
    ),
    CoachPortalPost(
        5, "post1", WEEK_THEMES[4],
        """For a month I've been showing professionals the part of Little Nate they hadn't seen — the platform built for the people who do this work.

Here's all of it, in one place.

Your client has a companion between sessions who remembers their story. You walk in already knowing where they are. You govern how that AI supports each client — it answers to you. The whole relationship stays one continuous thread, so no one starts from zero. And in the room, you have a quiet co-pilot surfacing what matters, while every clinical call stays yours.

Companion, coach, clinician — one system.

This isn't a chatbot with a calendar bolted on. It's the first coaching platform where the AI works for you and stays with your client between the moments you can't be there.

The professionals who build on this now will be the ones their clients can't imagine leaving. The rest will spend the next few years catching up.

If you coach, counsel, or run a practice — let's talk. I'll show you exactly how it works.""",
    ),
    CoachPortalPost(
        5, "post2", WEEK_THEMES[4],
        """The companion your clients already trust.
The platform built for you.
One system: companion, coach, clinician.

Build on it now — or spend the next few years catching up.

Let's talk.""",
        image_prompt=(
            "Deep black and gold, the most complete/arrival image of the set. Three golden "
            "elements resolving into one unified form or circle — companion, coach, clinician "
            "becoming one system. Confident, warm, professional. Words: \"One system.\" "
            "Optional small Sovereign Sanctuary mark. No faces, no UI. #0A0A0A / #C9A962. "
            "Text in image at most 6 words."
        ),
        max_chars=POST2_MAX_CHARS,
        needs_image=True,
    ),
)


def is_coach_portal_campaign_message(message: str) -> bool:
    m = (message or "").lower()
    if any(p in m for p in DETECTION_PHRASES):
        return True
    if "5 week" in m and "coach portal" in m:
        return True
    if "coach portal" in m and ("verbatim" in m or "campaign brief" in m):
        return True
    return False


def parse_post_as(message: str) -> str:
    m = (message or "").lower()
    if re.search(r"\bboth\b|\bcompany page\b.*\bfounder\b|\bfounder\b.*\bcompany\b", m):
        return "both"
    if re.search(r"\bcompany page\b|\borganization page\b", m):
        return "company"
    return "both"


def first_tuesday_on_or_after(start: date) -> date:
    d = start
    while d.weekday() != 1:
        d += timedelta(days=1)
    return d


def campaign_week_dates(start: date, weeks: int = WEEKS) -> List[date]:
    anchor = first_tuesday_on_or_after(start)
    dates: List[date] = []
    for w in range(weeks):
        target_wd = WEEKDAY_ROTATION[w]
        week_tuesday = anchor + timedelta(weeks=w)
        offset = {1: 0, 2: 1, 3: 2}[target_wd]
        dates.append(week_tuesday + timedelta(days=offset))
    return dates


def slot_key_for(week: int, hour: int) -> str:
    return f"w{week}_{hour:02d}00"


def validate_post_text(text: str, *, max_chars: int, extra_compliance: bool = False) -> List[str]:
    errors: List[str] = []
    body = (text or "").strip()
    if not body:
        errors.append("empty post body")
    if len(body) > max_chars:
        errors.append(f"exceeds {max_chars} chars ({len(body)})")
    if BANNED_WORDS.search(body):
        errors.append("contains banned term")
    if "!" in body:
        errors.append("contains exclamation mark")
    if ALL_CAPS_URGENCY.search(body):
        errors.append("contains ALL-CAPS urgency")
    if extra_compliance:
        if re.search(r"\b(diagnos|clinical decision|autonomous)\b", body, re.I):
            if not re.search(r"at your discretion|you decide|licensed professional", body, re.I):
                errors.append("week-4 licensing boundary weak")
    return errors


def build_verbatim_slots(start: date) -> List[Dict[str, Any]]:
    week_dates = campaign_week_dates(start)
    slots: List[Dict[str, Any]] = []
    post_idx = 0
    for week_i, post_date in enumerate(week_dates, start=1):
        for hour in POST_TIMES:
            post = POSTS[post_idx]
            post_idx += 1
            local_dt = datetime.combine(post_date, time(hour, 0), tzinfo=TZ)
            sk = slot_key_for(week_i, hour)
            slots.append({
                "slot_key": sk,
                "week": week_i,
                "hour": hour,
                "post": post,
                "scheduled_for": local_dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None),
                "local_label": local_dt.strftime("%A %Y-%m-%d %I:%M %p %Z"),
            })
    return slots


async def queue_coach_portal_campaign(
    executor,
    message: str = "",
    *,
    start: Optional[date] = None,
    force_new: bool = False,
    post_as: Optional[str] = None,
) -> QueueBatchResult:
    from app.services.linkedin_campaign_executor import message_looks_like_restart, parse_start_date
    from app.services.skyeye_content_generator import SkyEyeContentGenerator

    now = datetime.now(TZ)
    start = start or parse_start_date(message)
    post_as = post_as or parse_post_as(message)
    restart = force_new or message_looks_like_restart(message)

    if restart:
        archived = await executor._supersede_stale_campaign_queue("coach_portal_restart")
        if archived:
            logger.info("Archived %s rows for coach portal campaign restart", archived)
    else:
        settings = await executor._load_settings()
        if settings.get("campaign_template") == CAMPAIGN_TEMPLATE and settings.get("batch_id"):
            existing = await executor._pending_batch_snapshot()
            if existing:
                existing.summary = (
                    f"Coach Portal Acquisition campaign already queued ({existing.batch_id}). "
                    "Say 'restart campaign' to replace."
                )
                return existing

    batch_id = f"coach_portal_{start.isoformat()}"
    await executor._archive_other_batch_rows(batch_id)

    slots = build_verbatim_slots(start)
    gen = SkyEyeContentGenerator(executor.db_pool)
    queued_ids: List[int] = []
    validation_errors: List[str] = []

    for slot in slots:
        post: CoachPortalPost = slot["post"]
        errs = validate_post_text(
            post.text,
            max_chars=post.max_chars,
            extra_compliance=post.extra_compliance,
        )
        if errs:
            validation_errors.append(f"{slot['slot_key']}: {', '.join(errs)}")
            continue

        lane = "FOUNDER" if post.slot == "post1" else "ORIG"
        meta = {
            "batch_id": batch_id,
            "slot_key": slot["slot_key"],
            "lane": lane,
            "local_label": slot["local_label"],
            "batch_number": 1,
            "post_as": post_as,
            "campaign_template": CAMPAIGN_TEMPLATE,
            "week": slot["week"],
            "theme": post.theme,
            "verbatim": True,
            "generate_image": post.needs_image,
            "image_prompt": post.image_prompt if post.needs_image else "",
            "extra_compliance": post.extra_compliance,
        }

        qid = await gen.queue_content(
            platform="linkedin",
            content=post.text.strip(),
            content_type="post",
            emotion_context=json.dumps(meta),
            scheduled_for=slot["scheduled_for"],
            generated_by=GENERATED_BY,
            priority="normal",
            status="approved",
            approved_by="coach_portal_brief",
        )
        if qid:
            queued_ids.append(qid)

    if validation_errors:
        logger.error("Coach portal validation failures: %s", validation_errors)

    payload = {
        "batch_id": batch_id,
        "start_date": start.isoformat(),
        "auto_continue": False,
        "batch_number": 1,
        "platform": "linkedin",
        "campaign_template": CAMPAIGN_TEMPLATE,
        "weeks": WEEKS,
        "posts_total": len(POSTS),
        "posts_per_day": 0,
        "post_times": POST_TIMES,
        "post_as": post_as,
        "weekday_rotation": list(WEEKDAY_ROTATION),
        "verbatim": True,
    }
    async with executor.db_pool.acquire() as conn:
        await conn.execute("DELETE FROM skyeye_settings WHERE key = $1", SETTINGS_KEY)
        await conn.execute(
            """
            INSERT INTO skyeye_settings (key, value, platform, updated_at)
            VALUES ($1, $2, NULL, NOW())
            """,
            SETTINGS_KEY,
            json.dumps(payload),
        )

    first_slot = slots[0]["local_label"] if slots else "n/a"
    last_slot = slots[-1]["local_label"] if slots else "n/a"
    dest = {
        "person": "personal profile",
        "company": "company page",
        "both": "personal profile + company page",
    }.get(post_as, post_as)
    summary = (
        f"Coach Portal Acquisition ({batch_id}): {len(queued_ids)}/{len(POSTS)} verbatim posts "
        f"queued for auto-publish — {dest}. "
        f"Schedule: {first_slot} → {last_slot} (Tue–Thu, 3 PM + 8 PM ET). "
        f"Publishing only; no auto-engage."
    )
    if validation_errors:
        summary += f" Validation issues: {len(validation_errors)}."

    return QueueBatchResult(
        queued=len(queued_ids),
        cur_pending=0,
        queue_ids=queued_ids,
        batch_id=batch_id,
        summary=summary,
        config_summary=f"5 weeks × 2 posts = 10 verbatim slots — post_as={post_as}",
    )


async def bootstrap_coach_portal_campaign_if_enabled(db_pool) -> Optional[str]:
    import os

    flag = os.getenv("ENABLE_LINKEDIN_COACH_PORTAL_CAMPAIGN", "").strip().lower()
    if flag not in ("1", "true", "yes"):
        return None
    from app.services.linkedin_campaign_executor import LinkedInCampaignExecutor

    executor = LinkedInCampaignExecutor(db_pool)
    settings = await executor._load_settings()
    if settings.get("campaign_template") == CAMPAIGN_TEMPLATE:
        pending = await executor._pending_batch_snapshot()
        if pending and pending.queued > 0:
            return f"Coach portal campaign already active ({pending.batch_id})"
    result = await queue_coach_portal_campaign(
        executor,
        "Coach Portal Acquisition verbatim campaign starting today",
        force_new=False,
    )
    return result.summary
