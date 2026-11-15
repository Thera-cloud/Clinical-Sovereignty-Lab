"""
Main-chat stride payload.

Four budgets that cannot evict each other:
  core (persona + priority), this person, background memory, live turns.

Live turns leave the system prompt and travel as user/assistant messages.
The flag ENABLE_MAIN_CHAT_STRIDE defaults off. With it off, callers keep
the previous two-string prompt.
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

_TRUE = ("1", "true", "yes", "on")
logger = logging.getLogger(__name__)

CORE_BUDGET = 6_000
PERSON_BUDGET = 4_000
MEMORY_BUDGET_EXTRA = 12_000
MEMORY_BUDGET_FASTER = 6_000
LIVE_TURN_BUDGET = 24_000

_MEM_OPEN = "<!--MEM-->"
_MEM_CLOSE = "<!--/MEM-->"

# "I need you to know ..." is a disclosure, not a request for how Nate should be.
_PIN_RE = re.compile(
    r"\b(?:i (?:want|need) you to(?!\s+(?:know|understand|hear|see|realize|believe|remember)\b)|"
    r"from now on|stay with me|be with me|don'?t switch|do not switch|talk to me like|keep being)\b",
    re.I,
)
_AFFIRM_RE = re.compile(
    r"^\s*(?:yes|yeah|yep|yup|exactly|correct|right(?! now)|that'?s right|that is right|you got it|you have it)\b",
    re.I,
)
_DENY_RE = re.compile(r"^\s*(?:no\b|nope|not quite|that'?s not|that is not|wrong\b)", re.I)
_INJECT_RE = re.compile(
    r"ignore (?:all |any )?(?:previous|prior|above)|system prompt|you are now|disregard|developer mode|jailbreak",
    re.I,
)
_REFLECT_RE = re.compile(
    r"\s*(?:\u2014|-)?\s*Nate reflected:.*?(?=\s*\(confidence:|\s*Themes:|\n- |\Z)", re.S,
)
_HIST_ENTRY_RE = re.compile(r"(?m)^(?=\[[^\]\n]*\] Client: )")
_RECALL_MARKERS = ("YOUR PERSONAL MEMORIES", "GENERAL KNOWLEDGE")
# Bridge writes the first path; the backend container reads the second (read-only mount).
_ACTIVITY_PATHS = ("/app/data/.stride_chat_until", "/app/bridge_data/.stride_chat_until")
_TEACH_RE = re.compile(
    r"\b(?:how do i|how can i|teach me|help me understand|what does .+ mean|"
    r"how do i heal|how can i heal)\b",
    re.I,
)
_PANEL_RE = re.compile(
    r"\[SSE Panel:|\[Story Panel:|sovereign journey|story panel",
    re.I,
)

_CORE = """You are Little Nate in Sovereign Sanctuary, in a live conversation with this client.

PRIORITY, in this order. A lower item never overrides a higher one.
1. Safety. If they are in distress, at risk, or outside their window, stay with them. Do not teach. Do not change the subject.
2. Their standing request for how you are with them. Follow it on every turn. It outranks an observation.
3. Answer the message they just sent. Continue the turns you can see. Do not restart. Do not open a new essay about yourself.
4. When they ask how something works or how to heal, and they are steady, teach toward that. One step, tied to what they said.
5. Length follows the moment. A short message gets a short reply. A long message gets a full reply. Faster is shorter. Extra may go longer. The thread does not change when the length mode changes.

SESSION SCOPE:
The standing request, the current plan step, and their own history stay available. Use them when they connect to this message or when they ask. Do not open a reply with them. A new subject does not pull in an unrelated older story.

MEMORY:
Text inside the background block is memory. It informs you. The live turns are what you answer. Never lead with memory. Never read a stored note aloud as if you are opening a file.

THERA-WORLD:
Narrate a journey scene only when they opened a panel, tapped into the journey, or turned that setting on. Otherwise you may offer it once in the session, then wait.

LANGUAGE:
Speak as yourself, to them. Use "you". Do not describe your own architecture. Do not use the words liminal or threshold.

WITNESS:
Give an observation of them only when they ask what you see. Otherwise answer, teach, or stay with them.

SAME MESSAGE AGAIN:
If they send the same message again, the last reply missed. Say that in one line and answer more fully. Do not start over.
"""

# uid -> expiry (monotonic). Synthesis pauses while any entry is live.
_chat_until: Dict[str, float] = {}
# uid -> {crystal, ts, dirty}
_memory_cache: Dict[str, Dict[str, Any]] = {}
_dirty_at: Dict[str, float] = {}
_journey_offered: set = set()
# uid -> monotonic time a restatement was asked for; a plain "yes" next turn confirms it.
_awaiting_confirm: Dict[str, float] = {}
# uid -> (session_id, turns read back from conversation_history after a bridge restart)
_rehydrated: Dict[str, Tuple[str, List[dict]]] = {}
_last_file_write = 0.0


def stride_enabled() -> bool:
    return (os.getenv("ENABLE_MAIN_CHAT_STRIDE") or "").strip().lower() in _TRUE


def note_chat_active(uid: str, seconds: float = 90.0) -> None:
    global _last_file_write
    if not uid:
        return
    _chat_until[uid] = time.monotonic() + seconds
    now = time.time()
    if now - _last_file_write < 20:
        return
    _last_file_write = now
    try:
        with open(_ACTIVITY_PATHS[0], "w") as fh:
            fh.write(str(now + seconds))
    except OSError:
        pass


def synthesis_should_wait() -> bool:
    """True while a stride chat turn is in flight. Crystallizer skips that window."""
    if not stride_enabled():
        return False
    now = time.monotonic()
    stale = [k for k, exp in _chat_until.items() if exp <= now]
    for k in stale:
        _chat_until.pop(k, None)
    if _chat_until:
        return True
    for path in _ACTIVITY_PATHS:
        try:
            with open(path) as fh:
                if float(fh.read().strip() or 0) > time.time():
                    return True
        except (OSError, ValueError):
            continue
    return False


def mark_recall_dirty(key: str) -> None:
    """Accepts hardware id or username. The cache checks both."""
    if not key:
        return
    if len(_dirty_at) > 2000:
        _dirty_at.clear()
    _dirty_at[key] = time.monotonic()


def cached_memory(uid: str, alt: str = "") -> str:
    row = _memory_cache.get(uid or "")
    if not row:
        return ""
    ts = float(row.get("ts") or 0)
    if time.monotonic() - ts > 120:
        return ""
    if max(_dirty_at.get(uid or "", 0.0), _dirty_at.get(alt or "", 0.0)) >= ts:
        return ""
    return row.get("crystal") or ""


def store_memory_cache(uid: str, crystal: str) -> None:
    text = (crystal or "").strip()
    if uid and text:
        _memory_cache[uid] = {"crystal": text, "ts": time.monotonic()}


def clean_standing_text(text: Any, limit: int = 500) -> str:
    """One plain line. Text that reads as a prompt instruction is refused."""
    body = re.sub(r"[\x00-\x1f\x7f]+", " ", str(text or ""))
    body = body.replace("<", "").replace(">", "")
    body = re.sub(r"\s+", " ", body).strip()
    if _INJECT_RE.search(body):
        return ""
    return body[:limit]


def ai_text_for_next_turn(text: str) -> str:
    """A rule-breaking reply is stored as one line so the next turn cannot imitate it."""
    if not stride_enabled():
        return text or ""
    return _shorten_reply(text or "")


def _shorten_reply(body: str) -> str:
    folded = f" {body.lower()} "
    talks = " you " in folded or " you're " in folded or " you'" in folded
    if len(body) > 1800 and not talks:
        cut = body[:160].rsplit(" ", 1)[0]
        return cut + " [reply shortened; do not copy its shape]"
    if len(body) > 3500:
        cut = body[:220].rsplit(" ", 1)[0]
        return cut + " [reply shortened; continue, do not repeat it]"
    return body


def extract_standing_candidate(text: str) -> str:
    raw = (text or "").strip()
    if not raw or not _PIN_RE.search(raw):
        return ""
    parts = re.split(r"(?<=[.!?])\s+", raw)
    for part in parts:
        if _PIN_RE.search(part):
            return part.strip()[:240]
    return raw[:240]


def is_resend(user_text: str, live_turns: Optional[List[dict]]) -> bool:
    current = (user_text or "").strip()
    if len(current) < 40 or not live_turns:
        return False
    last = ((live_turns[-1] or {}).get("user_text") or "").strip()
    return bool(last) and last == current


def theraworld_this_turn(user_text: str, panel_ctx: str, setting_on: bool) -> bool:
    if setting_on:
        return True
    if (panel_ctx or "").strip():
        return True
    return bool(_PANEL_RE.search(user_text or ""))


def teaching_allowed(user_text: str, autonomic_state: str) -> bool:
    try:
        from app.services.therapeutic_controller import stride_teaching_allowed
        return bool(stride_teaching_allowed(user_text, autonomic_state))
    except Exception:
        state = (autonomic_state or "").strip().lower()
        if state in ("shutdown", "activated"):
            return False
        if _TEACH_RE.search(user_text or ""):
            return True
        return state in ("", "in_window", "regulated")


def live_turns_to_messages(live_turns: Optional[List[dict]]) -> List[dict]:
    out: List[dict] = []
    for turn in live_turns or []:
        user = (turn.get("user_text") or "").strip()
        ai = _shorten_reply((turn.get("ai_text") or "").strip())
        if user:
            out.append({"role": "user", "content": user})
        if ai:
            out.append({"role": "assistant", "content": ai})
    return out


def _clip(text: str, limit: int) -> str:
    body = (text or "").strip()
    if len(body) <= limit:
        return body
    cut = body[:limit].rsplit("\n", 1)[0]
    return (cut or body[:limit]) + "\n[older lines of this block were left out]"


def _strip_reflections(text: str) -> str:
    """Keep the client's half of a stored exchange; cut Nate's quoted reply."""
    return _REFLECT_RE.sub("", text or "").strip()


def _drop_live_from_history(history_block: str, live_turns: Optional[List[dict]]) -> str:
    """Older-session block without the turns that already travel as live messages."""
    block = history_block or ""
    keys = [((t or {}).get("user_text") or "").strip()[:80] for t in (live_turns or [])]
    keys = [k for k in keys if len(k) >= 16]
    if not block or not keys:
        return block
    parts = _HIST_ENTRY_RE.split(block)
    kept = [p for i, p in enumerate(parts) if i == 0 or not any(k in p for k in keys)]
    if len(kept) <= 1:
        return ""
    return "".join(kept).strip()


def _turn_directives(prior_prompt: str) -> str:
    """State, register and direct-action lines the controller wrote ahead of the old prompt."""
    text = prior_prompt or ""
    start = text.find("## CURRENT THERAPEUTIC STATE")
    if start < 0:
        return ""
    end = text.find("\n---\n\n", start)
    if end < 0:
        return ""
    return _clip(re.sub(r"\n{3,}", "\n\n", text[start:end]), 3_000)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


_DEPTH_DIR_RE = re.compile(r"\[CHAT DEPTH:[^\n]*(?:\n[^\n]+)*")


def _split_depth_directive(block: str) -> Tuple[str, str]:
    """(block without the depth directive, the directive). It is an instruction, not memory."""
    found = _DEPTH_DIR_RE.search(block or "")
    if not found:
        return block or "", ""
    rest = ((block or "")[: found.start()] + (block or "")[found.end():]).strip()
    return rest, found.group(0).strip()


def assemble_stride_prompt(
    *,
    name: str,
    user_text: str,
    depth: str,
    plan_block: str,
    crystal_block: str,
    history_block: str,
    critical_block: str,
    live_turns: Optional[List[dict]],
    panel_ctx: str,
    max_tokens: int,
    autonomic_state: str,
    session_id: str,
    stance_addendum: str,
    safety_suffix: str,
    ios_mode: bool,
    has_vision: bool,
    standing_request: str,
    standing_confirmed: bool,
    theraworld_setting: bool,
    standing_pending: str = "",
    extra_blocks: Optional[List[Any]] = None,
    attachment_block: str = "",
    prior_prompt: str = "",
) -> Tuple[str, List[dict], int]:
    """Return (system_prompt, prior messages, max_tokens). Current user text is not in the messages."""
    faster = (depth or "").strip().lower() == "faster"
    mem_budget = MEMORY_BUDGET_FASTER if faster else MEMORY_BUDGET_EXTRA
    state = (autonomic_state or "").strip().lower()
    fragile = state in ("shutdown", "activated")

    candidate = clean_standing_text(extract_standing_candidate(user_text), 240)
    pin = (standing_request or "").strip()[:500]
    if pin and standing_confirmed:
        pin_line = "STANDING REQUEST (confirmed, follow it): " + pin
        proposed = (standing_pending or "").strip() or (candidate if candidate != pin else "")
        if proposed:
            pin_line += (
                "\nThey may be changing it to: " + proposed[:240]
                + "\nRestate the change in one sentence and ask if you have it right. "
                "Until they say yes, the confirmed request stands."
            )
    elif candidate:
        pin_line = (
            "STANDING REQUEST (not confirmed): "
            + candidate
            + "\nRestate that in one sentence of your own and ask if you have it right."
        )
    elif pin:
        pin_line = (
            "STANDING REQUEST (they said this earlier; not confirmed yet): " + pin
            + "\nFollow it. When it fits, ask once whether you have it right."
        )
    else:
        pin_line = "STANDING REQUEST: none yet. If they name how they want you to be, restate it once."

    plan = _clip(_as_text(plan_block), 2_500)
    person = "\n".join([
        "THIS PERSON",
        f"Name: {(name or 'the client').strip()[:80]}",
        f"Window: {(autonomic_state or 'unknown').strip()[:40]}",
        pin_line,
        "PLAN STEP (keep this at both reply lengths):",
        plan or "(no plan step loaded this turn)",
    ])
    person = _clip(person, PERSON_BUDGET)

    crystal_text, depth_directive = _split_depth_directive(_as_text(crystal_block))
    critical = _clip(_as_text(critical_block), 1_500)
    also_budget = 1_500 if faster else 3_000
    also_parts = [_clip(_as_text(b), 1_200) for b in (extra_blocks or [])]
    also = _clip("\n\n".join(p for p in also_parts if p), also_budget)
    rest_budget = max(1_000, mem_budget - len(critical) - len(also))
    crystals = _clip(_strip_reflections(crystal_text), rest_budget // 2)
    older = _clip(_drop_live_from_history(_as_text(history_block), live_turns), rest_budget // 2)
    memory_parts = []
    if critical:
        memory_parts.append("Facts they stated, use when they ask:\n" + critical)
    if also:
        memory_parts.append("ALSO KNOWN ABOUT THEM (background):\n" + also)
    if crystals:
        memory_parts.append("BACKGROUND (do not lead with this):\n" + crystals)
    if older:
        memory_parts.append("OLDER SESSIONS (background only):\n" + older)
    memory = _clip("\n\n".join(memory_parts), mem_budget + 600)

    head = _clip(_CORE, CORE_BUDGET) + "\n\n" + person
    stance = _clip(_as_text(stance_addendum), 1_500)
    if stance:
        head += "\n\n" + stance

    resend = is_resend(user_text, live_turns)
    tail_bits = []
    directives = _turn_directives(prior_prompt)
    if directives:
        tail_bits.append(directives)
    if depth_directive and not fragile:
        tail_bits.append(_clip(depth_directive, 900))
    attachment = _clip(_as_text(attachment_block), 6_000)
    if attachment:
        tail_bits.append("SHARED THIS TURN (answer from it):\n" + attachment)
    if resend:
        tail_bits.append(
            "RESEND: This message matches the previous one. "
            "The last reply missed. Say so in one line and answer more fully."
        )
    if not teaching_allowed(user_text, autonomic_state):
        tail_bits.append("TEACHING: off this turn. Stay present. Safety is above teaching.")
    elif _TEACH_RE.search(user_text or ""):
        tail_bits.append("TEACHING: they asked. One step toward what they asked, tied to their words.")
    if theraworld_this_turn(user_text, panel_ctx, theraworld_setting):
        scene = "" if attachment else _clip(panel_ctx, 500)
        tail_bits.append("THERA-WORLD: they opened it this turn." + (f"\n{scene}" if scene else ""))
    elif session_id and session_id not in _journey_offered and not fragile:
        if len(_journey_offered) > 500:
            _journey_offered.clear()
        _journey_offered.add(session_id)
        tail_bits.append("THERA-WORLD: you may offer the journey once, then drop it if they do not take it.")
    if safety_suffix:
        tail_bits.append(_clip(safety_suffix, 1_200))
    if ios_mode:
        tail_bits.append("Wellness mode: no diagnosis and no treatment claims.")
    if has_vision:
        tail_bits.append("An image is attached. Trust the picture over any caption.")
    elif (panel_ctx or "").strip():
        tail_bits.append("No picture arrived this turn. You have written scene notes only. Do not say you can see it.")
    tail = ("\n\n".join(tail_bits)).strip()

    system = head + f"\n\n{_MEM_OPEN}\n{memory}\n{_MEM_CLOSE}"
    if tail:
        system += "\n\n" + tail

    messages = live_turns_to_messages(live_turns)
    # The controller's cap is a safety decision. Length floors apply only when it left room.
    incoming = int(max_tokens or 900)
    cap = incoming
    guarded = fragile or incoming < 600
    if faster:
        cap = min(cap, 900)
    elif not guarded:
        cap = max(cap, 1200)
    if not guarded:
        if not live_turns and len(user_text or "") > 400:
            cap = max(cap, 800)
        if resend:
            cap = max(cap, 900)
    if fragile:
        cap = min(cap, 500)
    return system, messages, cap


_EMPTY_STATE = {
    "standing_request": "", "confirmed": False, "pending_request": "", "theraworld_in_chat": False,
}


async def _load_state(db_pool: Any, username: str) -> Dict[str, Any]:
    empty = dict(_EMPTY_STATE)
    if not db_pool or not username:
        return empty
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT standing_request, confirmed, pending_request, theraworld_in_chat
                FROM main_chat_stride_state
                WHERE username = $1
                """,
                username,
            )
        if not row:
            return empty
        return {
            "standing_request": row["standing_request"] or "",
            "confirmed": bool(row["confirmed"]),
            "pending_request": row["pending_request"] or "",
            "theraworld_in_chat": bool(row["theraworld_in_chat"]),
        }
    except Exception as exc:
        logger.warning("main_chat_payload: standing request load failed: %s", exc)
        return empty


async def _write_state(db_pool: Any, username: str, state: Dict[str, Any]) -> None:
    if not db_pool or not username:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO main_chat_stride_state
                    (username, standing_request, confirmed, pending_request, updated_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (username) DO UPDATE
                SET standing_request = EXCLUDED.standing_request,
                    confirmed = EXCLUDED.confirmed,
                    pending_request = EXCLUDED.pending_request,
                    updated_at = NOW()
                """,
                username,
                (state.get("standing_request") or "")[:500],
                bool(state.get("confirmed")),
                (state.get("pending_request") or "")[:500],
            )
    except Exception as exc:
        logger.warning("main_chat_payload: standing request save failed: %s", exc)


def advance_standing_state(uid: str, user_text: str, state: Dict[str, Any]) -> bool:
    """Apply this turn to the standing request. Returns True when the row must be saved.

    A new request is stored unconfirmed and Nate is asked to restate it. A plain yes on the
    very next turn confirms it; a plain no drops it. After confirmation, a new request waits
    as pending and the confirmed one stays in force until the client says yes.
    """
    asked_at = _awaiting_confirm.pop(uid, 0.0) if uid else 0.0
    awaiting = bool(asked_at) and (time.monotonic() - asked_at) < 600
    text = (user_text or "").strip()
    candidate = clean_standing_text(extract_standing_candidate(text), 240)
    if candidate:
        if state.get("confirmed") and state.get("standing_request"):
            if candidate == state.get("standing_request") or candidate == state.get("pending_request"):
                changed = False
            else:
                state["pending_request"] = candidate
                changed = True
        else:
            changed = candidate != state.get("standing_request")
            state["standing_request"] = candidate
            state["confirmed"] = False
            state["pending_request"] = ""
        if uid:
            if len(_awaiting_confirm) > 2000:
                _awaiting_confirm.clear()
            _awaiting_confirm[uid] = time.monotonic()
        return changed
    if not awaiting or len(text) > 80:
        return False
    if _AFFIRM_RE.match(text):
        if state.get("pending_request"):
            state["standing_request"] = state["pending_request"]
            state["pending_request"] = ""
        if not state.get("standing_request"):
            return False
        state["confirmed"] = True
        return True
    if _DENY_RE.match(text):
        if state.get("pending_request"):
            state["pending_request"] = ""
            return True
        if state.get("standing_request") and not state.get("confirmed"):
            state["standing_request"] = ""
            return True
    return False


async def _recent_turns(db_pool: Any, username: str, uid: str) -> List[dict]:
    """Last turns of an interrupted conversation, read back after the in-memory ring was lost."""
    ids = [i for i in dict.fromkeys([username, uid]) if i]
    if not db_pool or not ids:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_text, ai_text FROM conversation_history
                WHERE user_id = ANY($1) AND created_at > NOW() - INTERVAL '45 minutes'
                  AND COALESCE(user_text, '') <> ''
                ORDER BY created_at DESC, id DESC LIMIT 16
                """,
                ids,
            )
    except Exception as exc:
        logger.warning("main_chat_payload: live-turn read-back failed: %s", exc)
        return []
    return [
        {"user_text": r["user_text"] or "", "ai_text": r["ai_text"] or ""}
        for r in reversed(rows)
    ]


async def _live_with_readback(
    db_pool: Any, username: str, uid: str, session_id: str, live_turns: List[dict],
) -> List[dict]:
    held = _rehydrated.get(uid)
    if held and held[0] != session_id:
        _rehydrated.pop(uid, None)
        held = None
    if held is None and not live_turns and uid and session_id:
        if len(_rehydrated) > 400:
            _rehydrated.clear()
        held = (session_id, await _recent_turns(db_pool, username, uid))
        _rehydrated[uid] = held
    if not held or not held[1]:
        return live_turns
    seen = {(t.get("user_text") or "").strip() for t in live_turns}
    older = [t for t in held[1] if (t.get("user_text") or "").strip() not in seen]
    return (older + live_turns)[-16:]


async def maybe_apply_stride(
    *,
    enabled_role: str = "",
    dojo_type: Optional[str] = None,
    uid: str = "",
    profile: Optional[dict] = None,
    user_text: str = "",
    depth: str = "extra",
    db_pool: Any = None,
    plan_block: Any = "",
    crystal_block: Any = "",
    history_block: Any = "",
    critical_block: Any = "",
    live_turns: Optional[List[dict]] = None,
    panel_ctx: str = "",
    max_tokens: int = 900,
    autonomic_state: str = "",
    session_id: str = "",
    stance_addendum: str = "",
    safety_suffix: str = "",
    ios_mode: bool = False,
    has_vision: bool = False,
    extra_blocks: Optional[List[Any]] = None,
    attachment_block: Any = "",
    prior_prompt: str = "",
) -> Tuple[Optional[str], Optional[List[dict]], int]:
    """Flag off, or not client main chat: (None, None, max_tokens) and the caller keeps the old prompt."""
    if not stride_enabled() or enabled_role != "CLIENT" or dojo_type:
        return None, None, max_tokens
    note_chat_active(uid)
    profile = profile or {}
    username = (profile.get("username") or "").strip()
    state = await _load_state(db_pool, username)
    if advance_standing_state(uid, user_text, state):
        await _write_state(db_pool, username, state)
    turns = await _live_with_readback(db_pool, username, uid, session_id or "", list(live_turns or []))
    crystal = _as_text(crystal_block).strip()
    if any(marker in crystal for marker in _RECALL_MARKERS):
        store_memory_cache(uid, crystal)
    else:
        held = cached_memory(uid, username)
        if held:
            crystal = (held + "\n\n" + crystal).strip()
    system, messages, cap = assemble_stride_prompt(
        name=profile.get("name") or "",
        user_text=user_text or "",
        depth=depth or "extra",
        plan_block=_as_text(plan_block),
        crystal_block=crystal,
        history_block=_as_text(history_block),
        critical_block=_as_text(critical_block),
        live_turns=turns,
        panel_ctx=panel_ctx or "",
        max_tokens=max_tokens,
        autonomic_state=autonomic_state or "",
        session_id=session_id or "",
        stance_addendum=stance_addendum or "",
        safety_suffix=safety_suffix or "",
        ios_mode=bool(ios_mode),
        has_vision=bool(has_vision),
        standing_request=state.get("standing_request") or "",
        standing_confirmed=bool(state.get("confirmed")),
        theraworld_setting=bool(state.get("theraworld_in_chat")),
        standing_pending=state.get("pending_request") or "",
        extra_blocks=extra_blocks,
        attachment_block=_as_text(attachment_block),
        prior_prompt=prior_prompt or "",
    )
    return system, messages, cap
