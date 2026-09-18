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
            "narrative_text",
            "archetype_hint",
            "recommended_follow_up",
            "clinical_summary",
            "therapeutic_modality",
        ):
            val = trans_d.get(key) or block.get(key)
            if val:
                out.append(_plain(val))
    return [t for t in out if t]


_SKIP_NARR = re.compile(
    r"ifs-informed|therapeutic_modality|clinical_summary|recommended_follow",
    re.I,
)


BIOME_CUE: Dict[str, str] = {
    "dark_forest": "fog path / lantern cairn — one more step or stop",
    "fortress_plains": "open door or rope bridge — one plank, not the whole crossing",
    "river_valley": "still water or the bench that remembers company — what looks back",
    "crystal_mountains": "cave glow or overlook — what they can finally see",
    "open_sky": "cloak set down / first dawn — what they no longer need to carry",
}
CORE_CHAR_MOVE: Dict[str, str] = {
    "mirror": "Ask which reflection they are standing in. Don't pick it for them.",
    "serpent": "The circling is the charge. Don't slay it; ask what it is guarding.",
    "pride/shame": "Warm and cold in one frame. Ask which side they live in at the door.",
    "reflection": "The picture already shows a slightly different self. Stay until they feel it.",
    "holy spirit": "The seam of light is enough. Don't preach; ask if they can let it be there.",
    "curiosity": "The open path is Curiosity. Ask what they want to look at, not what it means.",
}
GENERIC_PANEL = re.compile(
    r"who protects, who structures"
    r"|the image is the door"
    r"|art-as-witness"
    r"|whichever figure they cannot stop looking at"
    r"|psychotherapeutic approaches in reach",
    re.I,
)


def _parts_named(texts: Sequence[str]) -> List[str]:
    blob = _blob(texts)
    found: List[str] = []
    seen: set[str] = set()
    for needle, label in NAMED_PARTS:
        if needle in blob and label.lower() not in seen:
            seen.add(label.lower())
            found.append(label)
    return found


def _scene(brief: Dict[str, Any]) -> Dict[str, Any]:
    raw = brief.get("thera_world_scene")
    return raw if isinstance(raw, dict) else {}


def _npc_names(scene: Dict[str, Any]) -> List[str]:
    found: List[str] = []
    seen: set[str] = set()
    raw = scene.get("npcs") or scene.get("last_panel_npcs") or []
    items: List[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                items.append(str(item.get("name") or item.get("label") or ""))
            else:
                items.append(str(item or ""))
    elif isinstance(raw, str):
        items.append(raw)
    for name in items:
        label = _plain(name)
        key = label.lower()
        if len(label) < 3 or key in seen:
            continue
        seen.add(key)
        found.append(label)
    return found


def _crystal_thread(brief: Dict[str, Any]) -> Tuple[str, str]:
    for crystal in brief.get("crystal_memory") or []:
        if isinstance(crystal, dict):
            text = _plain(crystal)
            domain = str(crystal.get("domain") or "clinical").strip().lower()
        else:
            text = _plain(crystal)
            domain = "clinical"
        if text and not _is_junk(text):
            return domain or "clinical", text
    return "", ""


def _chat_thread(brief: Dict[str, Any]) -> str:
    for raw in brief.get("recent_conversations") or []:
        if not isinstance(raw, dict):
            continue
        user = _plain(raw.get("user") or raw.get("user_text") or raw.get("preview"))
        if user and not _is_junk(user) and len(user) >= 18:
            return user
    return ""


def _pattern_label(blob: str) -> str:
    for label, words in PATTERNS:
        if any(w in blob for w in words):
            return label
    return ""


def _biome_key(raw: str) -> str:
    return _plain(raw).lower().replace(" ", "_")


def _character_key(raw: str) -> str:
    return _plain(raw).lower().replace("pride/shame", "pride/shame")


def compose_panel_prep_points(brief: Optional[Dict[str, Any]] = None) -> List[str]:
    """Coach moves from this client's Thera-world panel + LN memory — not IFS slogans."""
    brief = brief or {}
    scene = _scene(brief)
    texts = _panel_texts(brief)
    narrative = _plain(scene.get("narrative") or scene.get("last_panel_summary") or "")
    if not narrative:
        narrative = next(
            (
                t for t in texts
                if t and not _is_junk(t) and len(t) >= 24 and not _SKIP_NARR.search(t)
            ),
            "",
        )
    biome = _plain(scene.get("biome") or scene.get("current_biome") or "")
    character = _plain(
        scene.get("character")
        or scene.get("character_manifest")
        or scene.get("dominant_character")
        or ""
    )
    names = _npc_names(scene) + _parts_named(
        texts + [narrative, character, " ".join(_npc_names(scene))]
    )
    # de-dupe names, keep order
    uniq: List[str] = []
    seen_n: set[str] = set()
    for name in names:
        key = name.lower()
        if key in seen_n:
            continue
        seen_n.add(key)
        uniq.append(name)
    names = uniq[:4]
    if character and character.lower() not in seen_n:
        names = [character] + names
        names = names[:4]
    domain, crystal = _crystal_thread(brief)
    chat = _chat_thread(brief)
    corpus = _user_corpus(brief)
    blob = _blob(corpus + texts + [narrative, biome, character])
    secondary = _label_hits(blob, SECONDARY)
    core = _label_hits(blob, CORE)
    pattern = _pattern_label(blob)
    has_world = bool(narrative or biome or character or names or texts)
    if not has_world:
        return []

    points: List[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        line = _plain(raw)
        if not line or _FRAMEWORK_LINE.search(line) or _is_junk(line):
            return
        if GENERIC_PANEL.search(line):
            return
        key = line.lower()[:90]
        if key in seen:
            return
        seen.add(key)
        points.append(_clip(line, 220) if len(line) > 220 else line)

    part = names[0] if names else (character or "the figure LN placed")
    others = ", ".join(names[1:3])
    ifs = f"IFS / Thera-world: {part} is in their last panel"
    if others:
        ifs += f" with {others}"
    if biome:
        ifs += f" ({biome.replace('_', ' ')})"
    ifs += "."
    if pattern:
        ifs += (
            f" LN's chats show {pattern}. Ask if {part} is that cycle on the image. "
            "Don't interpret."
        )
    elif secondary:
        under = core[0] if core else (
            "fear" if "anxiety" in secondary else
            "conviction" if "shame" in secondary else
            "sadness"
        )
        ifs += (
            f" Memory is carrying {', '.join(secondary[:2])} as cover. "
            f"Unblend {part}; go toward {under}. Don't coach the cover."
        )
    else:
        move = CORE_CHAR_MOVE.get(_character_key(character))
        ifs += " " + (move or "Let the part speak from the picture. Don't name it for them.")
    add(ifs)

    bkey = _biome_key(biome)
    cue = BIOME_CUE.get(bkey, "")
    mem = crystal or chat
    art = "Thera-world: "
    if narrative:
        art += _clip(narrative, 110)
        if not art.endswith("."):
            art += "."
    elif cue:
        art += cue + "."
    else:
        art += f"Stay with {part} until a feeling updates."
    if mem:
        art += (
            f" Hold the image against what LN already holds — {_clip(mem, 80)}. "
            "Don't translate the scene for them."
        )
    elif cue and narrative:
        art += f" Art move: {cue}. Stay until the body answers."
    add(art)

    approach = ""
    if _hits(blob, TRAUMA) or _hits(blob, TRAUMA_SEX):
        approach = (
            f"Consent, slow. Image before the trauma story. {part} already knows the pace."
        )
    elif "shame" in secondary:
        approach = (
            "Conviction, not another confession. Stay with what they already know is true "
            f"while looking at {part}."
        )
    elif "anxiety" in secondary:
        approach = (
            "Don't solve the spin. Ask what fear sits under it while they stay with the image."
        )
    elif pattern:
        approach = (
            f"One experiment on {pattern} — skill in the hour, not a diagnosis of the picture."
        )
    else:
        approach = CORE_CHAR_MOVE.get(_character_key(character)) or (
            f"One move with {part}. Don't stack modalities."
        )
    learn = "LN learning"
    if domain:
        learn += f" ({domain})"
    learn += ": "
    if crystal:
        learn += _clip(crystal, 90)
        if not learn.endswith("."):
            learn += "."
        learn += " " + approach
    elif chat:
        learn += _clip(chat, 80) + ". " + approach
    else:
        quest = _plain(scene.get("quest") or scene.get("goal") or "")
        mission = _plain(scene.get("mission") or scene.get("relationship_target") or "")
        if quest:
            learn += f"Active quest thread: {_clip(quest, 70)}. {approach}"
        elif mission:
            learn += f"Active mission thread: {_clip(mission, 70)}. {approach}"
        else:
            learn += approach
    add(learn)

    if len(points) < 3 and cue:
        add(f"Stay in {biome.replace('_', ' ') or 'Thera-world'}: {cue}. LN holds the chats.")
    if len(points) < 3 and part:
        add(f"Ask {part} what it needs before any plan. LN already has the history.")
    return points[:3]
