"""View Brief session-prep: LN clinical/coaching direction, not last-chat echo.

Growth keeps the phase framework. Memory keeps crystals. Prep is up to five
coach moves: how to bring feeling in, history patterns LN can hold, trauma /
unresolved anxiety / depression, secondary vs core emotion, or — when the
client is not in trauma repair — positive-psychology coaching.
"""

from __future__ import annotations

import re
import json
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_GENERIC_CRYSTAL = re.compile(
    r"here(?:'s| is) the (?:synthesized |crystallized )?insight"
    r"|insight crystal"
    r"|after analyzing the provided knowledge"
    r"|crystallized insight for the",
    re.I,
)
_FRAMEWORK_LINE = re.compile(
    r"^(register:|eft:|watch for:|time focus|companion into the wound)",
    re.I,
)
_JUNK = re.compile(
    r"sovereign journey|story panel|zoom ai|quick recap"
    r"|the meeting began with|saying ['\"]hello"
    r"|skills practice check-in|5-4-3-2-1|grounding and mindful"
    r"|asking about my .*image",
    re.I,
)
_WS = re.compile(r"\s+")

SECONDARY: Dict[str, Tuple[str, ...]] = {
    "shame": ("shame", "ashamed", "humiliat", "embarrass", "worthless", "pathetic"),
    "guilt": ("guilt", "guilty", "my fault", "i ruined", "i should have"),
    "anxiety": (
        "anxi", "panic", "worried", "worry", "nervous", "can't sleep",
        "cant sleep", "racing", "on edge", "spiral",
    ),
    "grief": ("grief", "grieving", "mourning", "i miss", "passed away", "died"),
    "frustration": ("frustrat", "fed up", "sick of", "irritat", "this again"),
}
CORE: Dict[str, Tuple[str, ...]] = {
    "fear": ("afraid", "scared", "terror", "unsafe", "i'm scared", "im scared"),
    "anger": ("angry", "anger", "rage", "furious", "i hate"),
    "sadness": ("sad", "heartbroken", "cry", "tears", "empty"),
    "disgust": ("disgust", "revolted", "sickened", "repulsed"),
    "joy": ("joy", "grateful", "proud of", "light", "alive"),
    "conviction": ("i won't go back", "i will not", "this is true", "i know what i need"),
    "positive sexual excitement": ("turned on", "desire for", "wanted him", "wanted her", "felt desire"),
}
TRAUMA = (
    "trauma", "flashback", "triggered", "assault", "abused", "abuse",
    "molest", "rape", "raped", "childhood", "war", "ptsd",
    "they hurt me", "he hurt me", "she hurt me",
)
TRAUMA_SEX = ("raped", "molest", "sexual abuse", "assaulted")
DEPRESSION = (
    "depress", "hopeless", "can't get out of bed", "cant get out of bed",
    "no point", "what's the point", "numb", "don't want to be here",
)
ANXIETY_UNRESOLVED = (
    "still anxious", "still worried", "panic came back", "can't settle",
    "cant settle", "hasn't gone", "keeps coming back",
)
PATTERNS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("withdraw / shut down when asked to need", ("disappear", "shut down", "go quiet", "withdraw", "i freeze")),
    ("caretaker / fixer", ("fix it", "take care of", "family fixer", "everyone else first")),
    ("people-please / can't say no", ("can't say no", "cant say no", "let them down", "people pleas")),
    ("conflict avoidance", ("don't want a fight", "keep the peace", "just drop it")),
    ("work / schedule overwhelm", ("behind at work", "too many", "no time", "calendar", "deadline")),
    ("unfinished tasks", ("didn't finish", "still haven't", "keep putting off", "procrastin")),
    ("creative stall", ("blocked", "can't create", "nothing comes", "stuck creat")),
)
COACH_MOVES: Tuple[Tuple[str, Tuple[str, ...], str], ...] = (
    ("scheduling", ("calendar", "schedule", "late", "deadline", "time"),
     "They're buildable, not in repair. One calendar commitment they can finish this week — LN can hold the follow-through."),
    ("task completion", ("finish", "didn't finish", "still haven't", "to-do", "homework"),
     "Lead with one completable task, then stop. LN can track whether it actually closed."),
    ("goal forming", ("i want", "goal", "next year", "if i could"),
     "Form one concrete goal from what they already want. Don't open a wound hunt."),
    ("conflict resolution", ("fight", "argument", "we keep", "they never listen"),
     "Conflict is the work: one repair sentence, not a trauma excavation."),
    ("creativity", ("create", "write", "paint", "music", "idea"),
     "Protect a short creative block this week. LN can ask what they actually made."),
)

REPAIR_PHASES = frozenset({"stabilize", "process"})
COACH_PHASES = frozenset({"thrive", "generative"})

FILL_REPAIR = (
    "If a secondary shows — anxiety, shame, guilt, grief, frustration — go under it to fear, anger, sadness, disgust, or conviction.",
    "Name one cycle from their chat history once. Don't interview the whole timeline.",
    "Ask what feeling is still unfinished. Not the to-do list.",
    "LN already has the chats. You hold the hour.",
    "Open in sensation, not content. One feeling, then silence.",
)
FILL_COACH = (
    "One completable task before next session. LN will ask if it actually closed.",
    "Protect a calendar block or a creative hour — skill work, not a wound hunt.",
    "If conflict is live: one repair sentence, then stop.",
    "Ask what they want built, not what they want explained.",
    "LN can remember the goal. You pick the one finish line.",
)
FILL_EMPTY = (
    "LN has no personal thread yet. One question about why they booked, then one feeling.",
    "Don't teach a framework. Follow the first feeling that shows.",
    "If an image or panel is on file, start there — which figure do they feel closest to?",
)

NAMED_PARTS: Tuple[Tuple[str, str], ...] = (
    ("wandering scholar", "Wandering Scholar"),
    ("cloakless traveler", "Cloakless Traveler"),
    ("orchard keeper", "Orchard Keeper"),
    ("root tender", "Root Tender"),
    ("bridgewright", "Bridgewright"),
    ("archivist", "Archivist"),
    ("curiosity", "Curiosity"),
    ("seraph", "Seraph"),
    ("scholar", "Scholar"),
    ("protector", "Protector"),
    ("firefighter", "Firefighter"),
    ("exile", "Exile"),
    ("manager", "Manager"),
    ("explorer", "Explorer"),
    ("keeper", "Keeper"),
)


def _plain(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, dict):
        for key in (
            "text", "summary", "content_summary", "clinical_summary",
            "clinical_translation", "user", "user_text", "topic_summary",
            "note", "harvest",
        ):
            val = raw.get(key)
            if val:
                return _plain(val)
        return ""
    return _WS.sub(" ", str(raw)).strip()


def _clip(text: str, n: int = 90) -> str:
    t = _plain(text)
    if len(t) <= n:
        return t
    cut = t[:n].rsplit(" ", 1)[0].rstrip(".,;:")
    return (cut or t[:n]) + "…"


def _is_junk(text: str) -> bool:
    t = _plain(text)
    if len(t) < 12 or t.startswith("{") or t.startswith("["):
        return True
    return bool(_JUNK.search(t) or _GENERIC_CRYSTAL.search(t))


def _blob(texts: Iterable[str]) -> str:
    return " ".join(t.lower() for t in texts if t)


def _hits(blob: str, words: Sequence[str]) -> List[str]:
    found: List[str] = []
    for w in words:
        if w in blob:
            found.append(w)
    return found


def _label_hits(blob: str, table: Dict[str, Tuple[str, ...]]) -> List[str]:
    out: List[str] = []
    for label, words in table.items():
        if any(w in blob for w in words):
            out.append(label)
    return out


def _num(metrics: Dict[str, Any], *keys: str) -> float:
    cur: Any = metrics
    for key in keys:
        if not isinstance(cur, dict):
            return 0.0
        cur = cur.get(key)
    try:
        return float(cur or 0)
    except (TypeError, ValueError):
        return 0.0


def _phase(brief: Dict[str, Any], thrive: Dict[str, Any]) -> Tuple[str, str]:
    block = brief.get("growth_phase")
    if not isinstance(block, dict):
        raw = thrive.get("phase")
        block = raw if isinstance(raw, dict) else {}
    phase = str(block.get("phase") or "process").strip().lower()
    sub = str(block.get("sub_state") or "").strip().lower()
    return phase, sub


def _user_corpus(brief: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for raw in brief.get("recent_conversations") or []:
        if not isinstance(raw, dict):
            continue
        user = _plain(raw.get("user") or raw.get("user_text") or raw.get("preview"))
        if user and not _is_junk(user):
            out.append(user)
    for crystal in brief.get("crystal_memory") or []:
        text = _plain(crystal)
        if text and not _is_junk(text):
            out.append(text)
    for raw in brief.get("prior_session_summaries") or []:
        text = _plain(raw)
        if text and not _is_junk(text):
            out.append(text)
    return out


def _in_repair(
    brief: Dict[str, Any],
    thrive: Dict[str, Any],
    blob: str,
    metrics: Dict[str, Any],
) -> bool:
    phase, sub = _phase(brief, thrive)
    if sub in ("crisis_hold", "working_through"):
        return True
    if phase in REPAIR_PHASES:
        return True
    if _hits(blob, TRAUMA) or _hits(blob, TRAUMA_SEX):
        return True
    risk = str(metrics.get("risk_level") or "").upper()
    if risk in ("HIGH", "CRITICAL", "CRISIS"):
        return True
    if _num(metrics, "anxiety_level") >= 0.55 or _num(metrics, "depression_indicators") >= 0.55:
        return True
    if phase in COACH_PHASES:
        return False
    return bool(_label_hits(blob, SECONDARY) or _label_hits(blob, CORE))


def compose_session_prep_points(
    brief: Optional[Dict[str, Any]],
    thrive: Optional[Dict[str, Any]] = None,
) -> List[str]:
    brief = brief or {}
    thrive = thrive or {}
    metrics = brief.get("metrics") if isinstance(brief.get("metrics"), dict) else {}
    corpus = _user_corpus(brief)
    blob = _blob(corpus)
    secondary = _label_hits(blob, SECONDARY)
    shame = metrics.get("shame_profile")
    if isinstance(shame, dict):
        try:
            if float(shame.get("shame_index") or 0) >= 0.4 and "shame" not in secondary:
                secondary.append("shame")
        except (TypeError, ValueError):
            pass
    core = _label_hits(blob, CORE)
    if "positive sexual excitement" in core and _hits(blob, TRAUMA_SEX):
        core = [c for c in core if c != "positive sexual excitement"]
    repair = _in_repair(brief, thrive, blob, metrics)
    points: List[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        line = _plain(raw)
        if not line or _FRAMEWORK_LINE.search(line) or _is_junk(line):
            return
        key = line.lower()[:80]
        if key in seen:
            return
        seen.add(key)
        points.append(line)

    if not corpus:
        add(FILL_EMPTY[0])
    elif repair:
        if secondary:
            under = core[0] if core else (
                "conviction" if "shame" in secondary else
                "fear" if "anxiety" in secondary else
                "sadness" if "grief" in secondary else
                "anger" if "frustration" in secondary else
                "sadness"
            )
            add(
                f"Secondary in the room: {', '.join(secondary)}. "
                f"Don't coach the cover. Bring them toward the core under it "
                f"({under}"
                f"{', ' + ', '.join(c for c in core if c != under) if len(core) > 1 else ''}) "
                "— body first, story second."
            )
        elif core:
            add(
                f"Core affect already named: {', '.join(core)}. "
                "Stay with the feeling in the body before any plan."
            )
        else:
            add(
                "Open in sensation, not content. One feeling, then silence. "
                "LN can hold the history so you don't have to recap it."
            )

        for label, words in PATTERNS:
            if any(w in blob for w in words):
                add(
                    f"History pattern LN can hold: {label}. "
                    "Name the cycle once; don't interview the whole timeline."
                )
                break

        if _hits(blob, TRAUMA) or _hits(blob, TRAUMA_SEX):
            add(
                "A traumatic thread is live in their chat history. "
                "Consent, slow, no technique dump. LN already has the details."
            )
        anx_metric = _num(metrics, "anxiety_level")
        if _hits(blob, ANXIETY_UNRESOLVED) or "anxiety" in secondary or anx_metric >= 0.45:
            add(
                "Anxiety is still unresolved. Treat it as a secondary. "
                "Ask what fear or anger sits under the spin — then stop solving."
            )
        dep_metric = _num(metrics, "depression_indicators")
        if _hits(blob, DEPRESSION) or dep_metric >= 0.45:
            add(
                "Depressive weight is in the history. "
                "Go toward sadness or disgust underneath numbness, not a goal list."
            )
        if "shame" in secondary:
            add(
                "Shame is covering. Invite conviction — what they already know is true — "
                "instead of another confession."
            )
        ready = _num(metrics, "pmb", "reconsolidation_readiness")
        if ready >= 0.6:
            add(
                "Reconsolidation window is open. Stay in the charge. "
                "Don't soothe it away."
            )
    else:
        add(
            "Not in trauma repair this hour. Lead with what they want to build — "
            "one goal, one finish line — not a wound hunt."
        )
        if "joy" in core or "conviction" in core or "positive sexual excitement" in core:
            add(
                f"Positive core is available: {', '.join(c for c in core if c in ('joy', 'conviction', 'positive sexual excitement'))}. "
                "Amplify that. Don't drag them back into shame."
            )
        placed = False
        for _key, words, line in COACH_MOVES:
            if any(w in blob for w in words):
                add(line)
                placed = True
        if not placed:
            add(
                "Positive coaching: pick one of goal forming, a finished task, "
                "a calendar block, a conflict repair, or a creative hour. LN will remember which."
            )
        for label, words in PATTERNS:
            if any(w in blob for w in words):
                add(
                    f"LN can coach the {label} pattern as a skill, not a diagnosis. "
                    "One experiment before next session."
                )
                break

    fills = FILL_EMPTY if not corpus else (FILL_REPAIR if repair else FILL_COACH)
    for line in fills:
        if len(points) >= 3:
            break
        add(line)
    n = 0
    while len(points) < 3 and n < 5:
        add(f"Stay with the next feeling that shows. LN holds the rest ({n + 1}).")
        n += 1
    return points[:5]


def _as_dict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    parsed = json.loads(match.group())
                    return parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    return {}
    return {}


def _panel_texts(brief: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for raw in brief.get("recent_panel_insights") or []:
        block = raw if isinstance(raw, dict) else _as_dict(raw)
        if not block:
            text = _plain(raw)
            if text and not text.startswith("{"):
                out.append(text)
            continue
        trans = block.get("clinical_translation")
        trans_d = trans if isinstance(trans, dict) else _as_dict(trans)
        for key in (
            "clinical_summary",
            "therapeutic_modality",
            "recommended_follow_up",
            "narrative_text",
            "archetype_hint",
        ):
            val = trans_d.get(key) or block.get(key)
            if val:
                out.append(_plain(val))
    return [t for t in out if t]


def _parts_named(texts: Sequence[str]) -> List[str]:
    blob = _blob(texts)
    found: List[str] = []
    seen: set[str] = set()
    for needle, label in NAMED_PARTS:
        if needle in blob and label.lower() not in seen:
            seen.add(label.lower())
            found.append(label)
    return found


def compose_panel_prep_points(brief: Optional[Dict[str, Any]] = None) -> List[str]:
    """IFS + art-therapy + psychotherapeutic moves from panels — not the raw summary."""
    brief = brief or {}
    texts = _panel_texts(brief)
    if not texts:
        return []
    names = _parts_named(texts)
    named = ", ".join(names[:4]) if names else "whichever figure they cannot stop looking at"
    return [
        (
            f"IFS: get to know the parts on the image — {named}. "
            "Ask who protects, who structures, who explores. Don't interpret. "
            "Let the part introduce itself."
        ),
        (
            "Art therapy: the image is the door. Let them look first. "
            "Ask what the scene already knows that their recent chats circled. "
            "Curiosity on the panel is the reconsolidation cue — stay until a memory "
            "or feeling updates, don't translate it for them."
        ),
        (
            "Psychotherapeutic approaches in reach: IFS unblending (Self with the part), "
            "art-as-witness (image before words), memory reconsolidation "
            "(old chat + new felt sense in the picture). Pick one. Don't stack."
        ),
    ]
