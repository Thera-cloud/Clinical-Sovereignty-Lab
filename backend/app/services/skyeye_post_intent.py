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
    "execute it", "go ahead",
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
    if any(v in msg_lower for v in PUBLISH_VERBS):
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


def is_immediate_publish(msg_lower: str) -> bool:
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


def parse_inline_content(message: str) -> Optional[str]:
    for sep in (":", "—", "–"):
        if sep in message:
            idx = message.find(sep)
            tail = message[idx + 1 :].strip()
            if len(tail) >= 20:
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

    if not has_publish_intent(msg_lower):
        short_approval = msg_lower in {"proceed", "yes", "approved", "do it", "go ahead", "execute it", "post it", "send it"}
        if short_approval:
            blob = history_blob.lower()
            if any(p in blob for p in ("post #", "ready to send", "approved and ready", "publish")):
                return PostIntent(
                    action="publish_queue",
                    platform=detect_platform(blob, history_blob),
                    post_as=detect_post_as(history_blob + " " + message),
                    queue_pick="first",
                    list_index=1,
                    confidence=0.75,
                )
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
    history = await chat.get_chat_history(limit=12)

    if intent.action == "publish_inline" and intent.inline_text:
        result = await brain.publish_content_inline(
            platform=intent.platform,
            content_text=intent.inline_text,
            approved_by="direct_chat_command",
            generated_by="direct_chat_command",
            post_as=intent.post_as,
        )
        stub = {
            "action_type": f"post_{intent.platform}",
            "title": "Direct chat post",
            "description": intent.inline_text[:200],
            "id": None,
        }
        return await chat._finalize_command_verification(stub, result)

    if intent.action == "publish_queue":
        queue_id = intent.queue_id or await resolve_queue_id(
            chat.db_pool, message, history, post_as=intent.post_as,
        )
        if not queue_id:
            err = (
                "No approved LinkedIn queue item matched. "
                f"Searched for index={intent.list_index}, pick={intent.queue_pick}."
            )
            return await chat._finalize_command_verification(
                {"action_type": "post_linkedin", "title": "Publish queue item", "id": None},
                {"error": err, "posted": False},
            )
        result = await brain.publish_queue_item(
            queue_id,
            approved_by="big_nate",
            post_as=intent.post_as,
        )
        stub = {
            "action_type": "post_linkedin",
            "title": f"Publish queue #{queue_id}",
            "description": result.get("content_preview", "")[:200],
            "id": queue_id,
        }
        return await chat._finalize_command_verification(stub, result)

    return None
