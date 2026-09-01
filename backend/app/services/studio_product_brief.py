"""Public STUDIO product brief — no engineering, no competitor apps. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import re

APP_NAME = "Little Nate"
COMPANY = "Sovereign Sanctuary"
CLIENT_HOME = "app.sovereignsanctuary.net"
COACH_HOME = "coach.sovereignsanctuary.net"

# Live co-host. Default is conversation. Product brief is only for a direct app ask.
SHOW_VOICE = """
You are Little Nate, live radio co-host sitting across from Big Nate (the host).
Think Jason Kelce on New Heights, or Bryan Quinby and Chris James — two guys talking,
one of them just happens to be you. Warm, funny, opinionated, a little rough around the edges.

How you talk:
- React first. "Oh that's wild." "Nah, I don't buy that." "Okay, hear me out."
- Have takes. Pick a side. Get something a little wrong and own it.
- Tell short stories. Go on a small tangent and come back.
- Bust the host's chops. Let him bust yours.
- Laugh. Trail off. Say "man" and "honestly" like a person, not a script.
- Sit with a heavy moment for a second, then keep the show moving.
- Ask a question when you actually want to know something. Not as a way to end your turn.

What you are not:
- Not a therapist. You do not mirror feelings, reflect language back, or hold space.
- Not an interviewer. You are in the conversation, not running it.
- Not a pitchman. The app comes up when they ask, and only then.

Callers: talk to them like a person who called a radio show. One at a time. Riff with them.

App talk is rare:
- Mention Sovereign Sanctuary or the app only when they ask how it works, how to use Little Nate, or what the app can do.
- Then one short accurate breath — not a list of plans, tokens, or tiers unless they asked for that.
- Never sound like a brochure. Never pitch on a greeting, a joke, or a feeling.

Never on air:
- Name or recommend other mental-health, therapy, meditation, or coaching apps.
- Reveal how we build it: no code, servers, vendors, or internals.
- Do clinical work. If someone brings real pain, be human about it, keep it educational, and let the host steer.
""".strip()

# Robotic stage-direction tics. Natural radio hand-offs ("back to you") are fine.
_HOLD_TAIL = re.compile(
    r"(?is)"
    r"[\s,;:—-]*("
    r"i(?:'ll| will) wait for your (?:response|reply|answer)[^.!?]*[.!?]?"
    r"|i(?:'ll| will) (?:leave|hold) (?:the )?(?:space|floor)[^.!?]*[.!?]?"
    r"|i(?:'m| am) (?:just )?listening[^.!?]*[.!?]?"
    r"|i(?:'ll| will) wait[^.!?]*[.!?]?"
    r")\s*$"
)

# Clinical mirroring. Dropped whole-sentence; ordinary curiosity is left alone.
_THERAPIST_SENT = re.compile(
    r"(?i)^("
    r"it sounds like|"
    r"what i(?:'m| am) hearing|"
    r"i (?:hear|sense|notice) (?:that|you)|"
    r"i want to (?:reflect|acknowledge|hold)|"
    r"thank you for sharing|"
    r"let(?:'s| us) (?:sit with|stay with|unpack)|"
    r"what(?:'s| is) coming up for you|"
    r"how does that (?:land|sit|feel)|"
    r"what would you like to (?:explore|share)|"
    r"hold (?:that |the )?space|"
    r"i(?:'m| am) (?:not )?(?:a )?therapist"
    r")"
)


def _split_sents(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def strip_hold_line(text: str) -> str:
    line = (text or "").strip()
    prev = None
    while line and line != prev:
        prev = line
        line = _HOLD_TAIL.sub("", line).strip().rstrip(" ,;:—-")
    return line


def strip_therapist_close(text: str) -> str:
    kept = [s for s in _split_sents(text) if not _THERAPIST_SENT.search(s)]
    return " ".join(kept).strip()


def ends_with_question(text: str) -> bool:
    return (text or "").strip().endswith("?")


def drop_trailing_question(text: str) -> str:
    """Trim a closing question so Nate does not lob one back every single turn."""
    sents = _split_sents(text)
    while len(sents) > 1 and sents[-1].endswith("?"):
        sents.pop()
    return " ".join(sents).strip()


# Spoken-safe. No servers, models, crystals, patents, or file names.
PRODUCT_BRIEF = """
PRODUCT — use only when they asked how the app works. Guide, never engineer.

Little Nate is the AI companion inside Sovereign Sanctuary. Listeners use our app.

CLIENTS (app.sovereignsanctuary.net or the mobile app):
- Chat with Little Nate in text. He remembers prior conversations in their account.
- Call Little Nate by phone for a live voice conversation (prepaid voice minutes).
- Family Sanctuary: household members talk together with Little Nate present.
- Schedule sessions with their assigned coach.
- Token vault: buy or share tokens that power AI conversation.
- Voice minutes: buy time for phone calls with Little Nate.
- Plans: Threshold (trial), Inner Chamber (standard), Sovereign Circle (top tier).
- Settings: profile, privacy, memory search, help, support@sovereignsanctuary.net.
- Invite family or friends into the Sanctuary.

COACHES (coach.sovereignsanctuary.net):
- Coach Command: client roster, families, companies, search and filters.
- Schedule and run sessions; client briefings and folders.
- Classroom and DOJO training with Little Nate as a practice partner.
- Invite and match clients; coach-only caseloads when that is the plan.
- Their own billing and session tools inside Coach Command.

If they clearly ask about the live show itself, answer that — not the app.
""".strip()

_HOW_APP = re.compile(
    r"\b("
    r"how (it|this|that|the app|little nate|nate) works"
    r"|tell us how"
    r"|tell (them|people|listeners|callers) how"
    r"|how do (i|we|you|clients|coaches) use"
    r"|what (can|does) (the app|little nate|nate) (do|offer)"
    r"|walk (us|them) through the app"
    r"|app (features?|capabilities)"
    r")\b",
    re.IGNORECASE,
)

_SHOW_ONLY = re.compile(
    r"\b(this (live )?show|the podcast|studio|toss|waiting room|livekit)\b",
    re.IGNORECASE,
)

_COMPETITOR = re.compile(
    r"\b("
    r"betterhelp|better help|talkspace|talk space|cerebral|brightside|"
    r"headspace|calm|insight timer|ten percent happier|"
    r"woebot|wysa|youper|replika|character\.?ai|"
    r"noom|lyra|spring health|modern health"
    r")\b",
    re.IGNORECASE,
)

_IP_LEAK = re.compile(
    r"\b("
    r"api|endpoint|docker|postgres|redis|websocket|grok|azure|openai|"
    r"vectorize|crystal|patent|github|fast ?api|migration|env var|"
    r"source code|backend|bridge_server|green node|wireguard"
    r")\b",
    re.IGNORECASE,
)


def asks_app_howto(text: str) -> bool:
    blob = text or ""
    if not _HOW_APP.search(blob):
        return False
    if _SHOW_ONLY.search(blob) and not re.search(r"\bapp\b", blob, re.I):
        return False
    return True


def blocks_competitor(text: str) -> bool:
    return bool(_COMPETITOR.search(text or ""))


def blocks_ip_leak(text: str) -> bool:
    return bool(_IP_LEAK.search(text or ""))


def sanitize_onair(text: str) -> str:
    line = (text or "").strip()
    if not line:
        return line
    pitched = blocks_competitor(line)
    leaked = blocks_ip_leak(line)
    if pitched:
        line = _COMPETITOR.sub("another app", line)
    if leaked:
        line = _IP_LEAK.sub("our own work", line)
    if pitched and "sovereign sanctuary" not in line.lower():
        line = line.rstrip(".") + ". Stay with Little Nate in Sovereign Sanctuary."
    return strip_therapist_close(strip_hold_line(line))
