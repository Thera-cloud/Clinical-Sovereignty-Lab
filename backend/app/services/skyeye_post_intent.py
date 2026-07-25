"""
Unified post-intent resolver for Big Nate Chat.

Maps natural-language publish requests to queue rows or inline content,
without requiring magic phrases like 'post this to LinkedIn:'.
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.skyeye_chat import SkyEyeChatService

PUBLISH_VERBS = (
    "post", "publish", "send", "push", "share", "push live", "go live",
    "put up", "put this up", "ship", "execute",
)
PLATFORM_ALIASES = {
    "linkedin": "linkedin",
    "linked in": "linkedin",
    "x": "x",
    "twitter": "x",
    "instagram": "instagram",
    "facebook": "facebook",
    "reddit": "reddit",
    "tiktok": "tiktok",
    "pinterest": "pinterest",
}
APPROVAL_PHRASES = (
    "approved", "go for it", "do it", "yes", "proceed", "looks good",
    "ship it", "launch it", "make it happen", "post it", "send it",
    "execute it", "go ahead", "post it now", "send it now", "publish it",
    "publish it now", "approved to post", "approved to publish",
)
REJECTION_PHRASES = (
    "reject", "cancel", "don't do that", "nope", "hold", "wait",
)
# 'no' only as whole word — never match inside 'now' / 'know'
REJECTION_WORDS = ("no",)


@dataclass
class PostIntent:
    action: str  # publish_inline | publish_queue | queue_campaign | none
    platform: str = "linkedin"
    post_as: str = "person"
    queue_id: Optional[int] = None
    inline_text: Optional[str] = None
    queue_pick: Optional[str] = None  # index | random | first | last
    list_index: Optional[int] = None
    campaign_context: Optional[str] = None
    confidence: float = 0.0


def phrase_in_message(phrase: str, msg_lower: str) -> bool:
    if phrase in REJECTION_WORDS or phrase in ("yes", "no"):
        return bool(re.search(rf"\b{re.escape(phrase)}\b", msg_lower))
    return phrase in msg_lower


def has_publish_intent(msg_lower: str) -> bool:
    if is_approval_execute(msg_lower):
        return True
    # Word-bound multi-word verbs first; single tokens need boundaries
    for v in PUBLISH_VERBS:
        if " " in v:
            if v in msg_lower:
                return True
        elif re.search(rf"\b{re.escape(v)}\b", msg_lower):
            return True
    if re.search(r"\bpost\s*#\s*\d+\b", msg_lower):
        return True
    if re.search(r"\bpost\s+(?:number|item|no\.?)\s*\d+\b", msg_lower):
        return True
    if "random" in msg_lower and ("queue" in msg_lower or "approved" in msg_lower):
        return True
    if re.search(r"\b(?:send|publish|post)\s+(?:that|it|this|one)\b", msg_lower):
        return True
    return False


def is_approval_execute(msg_lower: str) -> bool:
    """Short go-ahead / retry phrases that should publish (queue or chat draft)."""
    m = (msg_lower or "").lower().strip().rstrip(".!").strip()
    if not m:
        return False
    if m in APPROVAL_PHRASES:
        return True
    if re.search(
        r"\bapproved\s+to\s+(?:post|publish|send|go)(?:\s+it)?\b",
        m,
    ):
        return True
    if re.search(r"\bretry\s+now\b|^(?:please\s+)?retry\b", m):
        return True
    if re.search(
        r"\b(?:go\s+ahead\s+and\s+)?(?:post|publish|send)\s+(?:it|this|that)(?:\s+now)?\b",
        m,
    ):
        return True
    return False


def is_immediate_publish(msg_lower: str) -> bool:
    if is_approval_execute(msg_lower):
        return True
    if re.search(r"\b(?:now|immediately|right now|asap|today)\b", msg_lower):
        return True
    if re.search(r"\bpost\s*#\s*\d+", msg_lower):
        return True
    if "random" in msg_lower and "queue" in msg_lower:
        return True
    if phrase_in_message("post it", msg_lower) or phrase_in_message("send it", msg_lower):
        return True
    if re.search(r"\bpost\s+(?:that|this|it)\b", msg_lower):
        return True
    return False


def is_campaign_schedule_intent(msg_lower: str) -> bool:
    cadence = (
        "3pm", "3:00 pm", "8pm", "8:00 pm", "twice a day", "2x", "two times",
        "posts a day", "posts per day", "per day", "daily cadence",
    )
    campaign = (
        "campaign", "restart", "resume", "unpause", "50/30/20", "50-30-20",
        "5-3-2", "5/3/2", "5-3-2", "curated", "cadence", "sequence",
    )
    has_cadence = any(s in msg_lower for s in cadence)
    has_campaign = any(s in msg_lower for s in campaign)
    if "linkedin" in msg_lower and has_cadence and has_campaign:
        return True
    if has_cadence and has_campaign and re.search(
        r"\bpersonal\b|\bprofile\b|\bnot\s+(?:the\s+)?company\b", msg_lower
    ):
        return True
    return False


def detect_platform(msg_lower: str, history_blob: str = "") -> str:
    combined = f"{msg_lower} {history_blob.lower()}"
    for name, key in PLATFORM_ALIASES.items():
        if name in combined:
            return key
    return "linkedin"


def detect_post_as(message: str) -> str:
    """Resolve LinkedIn destination (mirrors skyeye_chat negation-aware logic)."""
    msg = (message or "").lower()
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
    both = re.search(
        r"\bboth\b|\bpersonal\b.*\bcompany page\b|\bcompany page\b.*\bpersonal\b", msg
    )
    if negated_company or re.search(r"\bpersonal\s+only\b|\bprofile\s+only\b", msg):
        return "person"
    if both and personal and company:
        return "both"
    if company and not personal:
        return "company"
    return "person"


def parse_list_index(msg_lower: str) -> Optional[int]:
    m = re.search(r"\bpost\s*#\s*(\d+)\b", msg_lower)
    if m:
        return int(m.group(1))
    m = re.search(r"\bpost\s+(?:number|item|no\.?)\s*(\d+)\b", msg_lower)
    if m:
        return int(m.group(1))
    m = re.search(r"\b#(\d+)\s+now\b", msg_lower)
    if m:
        return int(m.group(1))
    return None


_META_POST_PREFIX = re.compile(
    r"^(?:the topic of(?: the post)?|topic of the post|please (?:write|draft|create)|"
    r"generate (?:a |an )?(?:post|draft)|post (?:should|about)|here(?:'s| is) (?:the )?topic)\b",
    re.IGNORECASE,
)


def looks_like_publishable_post(text: str) -> bool:
    """Reject meta-instructions that are not LinkedIn-ready copy."""
    t = (text or "").strip()
    if len(t) < 40:
        return False
    if _META_POST_PREFIX.match(t):
        return False
    # Prefer posts that look like feed copy (sentences / paragraphs)
    if t.count(" ") < 6:
        return False
    return True


def parse_inline_content(message: str) -> Optional[str]:
    for sep in (":", "—", "–"):
        if sep in message:
            idx = message.find(sep)
            tail = message[idx + 1 :].strip()
            if len(tail) >= 40 and looks_like_publishable_post(tail):
                return tail
    return None


def build_numbered_list_from_history(chat_history: List[Dict]) -> List[Dict[str, Any]]:
    """Parse Nate's numbered approved-post list from recent assistant messages."""
    items: List[Dict[str, Any]] = []
    for msg in reversed(chat_history):
        if str(msg.get("sender", "")).lower() != "little_nate":
            continue
        text = str(msg.get("message", ""))
        if "approved" not in text.lower() and "ready to send" not in text.lower():
            continue
        for m in re.finditer(
            r"(?m)^\s*(\d+)\.\s+(?:\*\*)?APPROVED(?:\*\*)?[^\"]*\"([^\"]{20,})",
            text,
        ):
            items.append({"index": int(m.group(1)), "preview": m.group(2).strip()})
        if items:
            break
    return sorted(items, key=lambda x: x["index"])


async def fetch_approved_linkedin(db_pool, post_as: Optional[str] = None, limit: int = 20) -> List[Dict]:
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, content_text, status, scheduled_for, emotion_context,
                       LEFT(content_text, 120) AS preview
                FROM skyeye_content_queue
                WHERE platform = 'linkedin'
                  AND status = 'approved'
                ORDER BY scheduled_for ASC NULLS LAST, id ASC
                LIMIT $1
                """,
                limit,
            )
        out = []
        for r in rows:
            meta = r["emotion_context"]
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            pa = (meta or {}).get("post_as", "person")
            if post_as and pa != post_as:
                continue
            out.append({**dict(r), "post_as": pa})
        return out
    except Exception:
        return []


_STATUS_ESSAY_RE = re.compile(
    r"(?:CURRENT STATE|Verified Execution|FULL EXECUTION|POSTING HISTORY|"
    r"has NOT yet published|No published LinkedIn|RESOLUTION PROTOCOL|"
    r"execution analysis|status update)",
    re.IGNORECASE,
)


def extract_draft_from_history(chat_history: List[Dict]) -> Optional[str]:
    """Pull a publishable LinkedIn draft from recent Little Nate messages."""
    for msg in reversed(chat_history or []):
        if str(msg.get("sender", "")).lower() not in ("little_nate", "nate"):
            continue
        text = str(msg.get("message", "") or "")
        if len(text) < 80:
            continue
        for m in re.finditer(r"```(?:linkedin|post)?\s*\n([\s\S]{80,}?)```", text, re.I):
            draft = m.group(1).strip()
            if looks_like_publishable_post(draft) and not _STATUS_ESSAY_RE.search(draft):
                return draft[:4000]
        for sep in (
            "final draft:",
            "approved draft:",
            "post text:",
            "here's the post:",
            "here is the post:",
            "full post:",
            "linkedin post:",
            "draft for linkedin:",
            "hybrid draft:",
        ):
            low = text.lower()
            if sep in low:
                tail = text[low.rfind(sep) + len(sep) :].strip()
                # Strip trailing system-ish lines
                cut = re.split(r"\n(?:Shall I|Ready to|\[SYSTEM|\*\*Next)", tail, maxsplit=1)
                draft = cut[0].strip().strip('"')
                if looks_like_publishable_post(draft) and not _STATUS_ESSAY_RE.search(draft):
                    return draft[:4000]
        # Long double-quoted body (common Nate draft format)
        for m in re.finditer(r'"([^"]{120,})"', text, re.DOTALL):
            draft = re.sub(r"\s+", " ", m.group(1)).strip()
            if (
                looks_like_publishable_post(draft)
                and len(draft) >= 120
                and not _STATUS_ESSAY_RE.search(draft)
            ):
                return draft[:4000]
        # Paragraph fallback: skip status essays; take longest publishable block
        if _STATUS_ESSAY_RE.search(text):
            continue
        blocks = re.split(r"\n\s*\n", text)
        candidates = []
        for block in blocks:
            draft = block.strip().strip('"')
            if len(draft) < 160:
                continue
            if _STATUS_ESSAY_RE.search(draft):
                continue
            if looks_like_publishable_post(draft):
                candidates.append(draft)
        if candidates:
            return max(candidates, key=len)[:4000]
    return None


async def resolve_queue_id(
    db_pool,
    message: str,
    chat_history: List[Dict],
    post_as: str = "person",
) -> Optional[int]:
    msg_lower = message.lower()
    approved = await fetch_approved_linkedin(db_pool, post_as=post_as)
    if not approved:
        approved = await fetch_approved_linkedin(db_pool)

    list_index = parse_list_index(msg_lower)
    if list_index is not None:
        numbered = build_numbered_list_from_history(chat_history)
        if numbered:
            for item in numbered:
                if item["index"] == list_index:
                    preview = item["preview"][:60]
                    for row in approved:
                        if (row.get("preview") or "").startswith(preview[:40]):
                            return row["id"]
        if 1 <= list_index <= len(approved):
            return approved[list_index - 1]["id"]

    if "random" in msg_lower and approved:
        return random.choice(approved)["id"]

    if re.search(r"\b(?:first|next)\s+(?:approved|one|post)\b", msg_lower) and approved:
        return approved[0]["id"]

    m = re.search(r"\bqueue\s*(?:id|#)\s*(\d+)\b", msg_lower)
    if m:
        return int(m.group(1))

    # Explicit queue language without an index → first approved
    if approved and re.search(
        r"\b(?:approved\s+queue|queue\s+item|from\s+the\s+queue|post\s+from\s+queue)\b",
        msg_lower,
    ):
        return approved[0]["id"]

    return None


def resolve_post_intent(message: str, chat_history: List[Dict]) -> PostIntent:
    msg_lower = message.lower().strip()
    history_blob = " ".join(
        str(m.get("message", "")) for m in chat_history[-6:]
    )

    if is_campaign_schedule_intent(msg_lower) and not is_immediate_publish(msg_lower):
        return PostIntent(
            action="queue_campaign",
            platform=detect_platform(msg_lower, history_blob),
            post_as=detect_post_as(message),
            campaign_context=f"{history_blob}\n\n{message}",
            confidence=0.85,
        )

    # Explicit go-ahead / retry — publish queue or chat Final draft (not status talk)
    if is_approval_execute(msg_lower):
        # Only honor post #N from the *current* message (not stale history #1)
        return PostIntent(
            action="publish_queue",
            platform=detect_platform(msg_lower, history_blob),
            post_as=detect_post_as(history_blob + " " + message),
            queue_pick="first",
            list_index=parse_list_index(msg_lower),
            confidence=0.86,
        )

    if not has_publish_intent(msg_lower):
        return PostIntent(action="none")

    platform = detect_platform(msg_lower, history_blob)
    post_as = detect_post_as(message + " " + history_blob)

    inline = parse_inline_content(message)
    if inline and is_immediate_publish(msg_lower):
        return PostIntent(
            action="publish_inline",
            platform=platform,
            post_as=post_as,
            inline_text=inline,
            confidence=0.9,
        )

    if is_immediate_publish(msg_lower) or parse_list_index(msg_lower) is not None:
        pick = "random" if "random" in msg_lower else "index"
        return PostIntent(
            action="publish_queue",
            platform=platform,
            post_as=post_as,
            queue_pick=pick,
            list_index=parse_list_index(msg_lower),
            confidence=0.88,
        )

    if has_publish_intent(msg_lower):
        inline_fallback = parse_inline_content(message)
        if inline_fallback:
            return PostIntent(
                action="publish_inline",
                platform=platform,
                post_as=post_as,
                inline_text=inline_fallback,
                confidence=0.7,
            )

    return PostIntent(action="none")


async def _resolve_publish_image(
    message: str,
    content_text: str,
) -> Optional[bytes]:
    """Attach latest screenshot/generated image, or generate when requested."""
    from app.services.skyeye_chat_media import (
        extract_image_prompt,
        generate_linkedin_image_for_chat,
        load_image_bytes_for_publish,
        wants_image_generation,
    )

    existing = load_image_bytes_for_publish(prefer_latest=True)
    if wants_image_generation(message) or (existing is None and "illustration" in message.lower()):
        prompt = extract_image_prompt(message)
        gen = await generate_linkedin_image_for_chat(content_text, image_prompt=prompt)
        if gen:
            return load_image_bytes_for_publish(attachment_id=gen.get("id"), prefer_latest=False)
    return existing


async def execute_post_intent(
    chat: SkyEyeChatService,
    intent: PostIntent,
    message: str,
) -> Optional[Dict[str, Any]]:
    from app.services.marketing_brain import MarketingBrain

    if intent.action == "none":
        return None

    if intent.action == "queue_campaign":
        return None  # caller runs existing campaign queue path

    brain = MarketingBrain(chat.db_pool)
    history = await chat.get_chat_history(limit=30)

    if intent.action == "publish_inline" and intent.inline_text:
        if not looks_like_publishable_post(intent.inline_text):
            return await chat._finalize_command_verification(
                {"action_type": "post_linkedin", "title": "Direct chat post", "id": None},
                {
                    "error": (
                        "Refused to publish meta/instructions text. Paste the full LinkedIn "
                        "post body after a colon, or approve a Final draft from chat history."
                    ),
                    "posted": False,
                },
            )
        image_bytes = await _resolve_publish_image(message, intent.inline_text)
        result = await brain.publish_content_inline(
            platform=intent.platform,
            content_text=intent.inline_text,
            approved_by="direct_chat_command",
            generated_by="direct_chat_command",
            post_as=intent.post_as,
            image_bytes=image_bytes,
        )
        stub = {
            "action_type": f"post_{intent.platform}",
            "title": "Direct chat post",
            "description": intent.inline_text[:200],
            "id": None,
        }
        return await chat._finalize_command_verification(stub, result)

    if intent.action == "publish_queue":
        msg_l = message.lower()
        explicit_queue = (
            parse_list_index(msg_l) is not None
            or bool(re.search(r"\bqueue\s*(?:id|#)\s*\d+\b", msg_l))
            or bool(re.search(r"\b(?:from\s+the\s+queue|approved\s+queue)\b", msg_l))
        )
        draft = (
            intent.inline_text
            or parse_inline_content(message)
            or extract_draft_from_history(history)
        )
        # Chat Final draft wins over unrelated coach-portal approved[0]
        if draft and looks_like_publishable_post(draft) and not explicit_queue:
            image_bytes = await _resolve_publish_image(message, draft)
            result = await brain.publish_content_inline(
                platform=intent.platform,
                content_text=draft,
                approved_by="direct_chat_command",
                generated_by="direct_chat_draft_fallback",
                post_as=intent.post_as,
                image_bytes=image_bytes,
            )
            stub = {
                "action_type": f"post_{intent.platform}",
                "title": "Chat draft publish",
                "description": draft[:200],
                "id": None,
            }
            return await chat._finalize_command_verification(stub, result)

        queue_id = intent.queue_id or await resolve_queue_id(
            chat.db_pool, message, history, post_as=intent.post_as,
        )
        if not queue_id:
            err = (
                "No approved LinkedIn queue item matched and no chat draft found. "
                f"Searched for index={intent.list_index}, pick={intent.queue_pick}. "
                "Paste the full Final draft in chat (or after a colon), then say "
                "'approved to post' / 'post it now', or 'post #N now' for a queue item."
            )
            return await chat._finalize_command_verification(
                {"action_type": "post_linkedin", "title": "Publish queue item", "id": None},
                {"error": err, "posted": False},
            )
        # Prefer chat draft image / generation over bare text queue publish
        preview_row = None
        try:
            async with chat.db_pool.acquire() as conn:
                preview_row = await conn.fetchrow(
                    "SELECT content_text FROM skyeye_content_queue WHERE id = $1",
                    queue_id,
                )
        except Exception:
            preview_row = None
        content_for_image = (preview_row["content_text"] if preview_row else "") or ""
        image_bytes = await _resolve_publish_image(message, content_for_image)
        result = await brain.publish_queue_item(
            queue_id,
            approved_by="big_nate",
            post_as=intent.post_as,
            image_bytes=image_bytes,
        )
        stub = {
            "action_type": "post_linkedin",
            "title": f"Publish queue #{queue_id}",
            "description": result.get("content_preview", "")[:200],
            "id": queue_id,
        }
        return await chat._finalize_command_verification(stub, result)

    return None
