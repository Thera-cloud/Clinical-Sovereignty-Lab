"""Public STUDIO product brief — no engineering, no competitor apps. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import re

APP_NAME = "Little Nate"
COMPANY = "Sovereign Sanctuary"
CLIENT_HOME = "app.sovereignsanctuary.net"
COACH_HOME = "coach.sovereignsanctuary.net"

# Spoken-safe. No servers, models, crystals, patents, or file names.
PRODUCT_BRIEF = """
PRODUCT — speak only as a knowledgeable guide, never as an engineer.

What this is: Little Nate is the AI companion inside Sovereign Sanctuary.
Listeners use OUR app — not some other mental-health or coaching app.

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

THIS LIVE SHOW:
- You are Little Nate, co-host. The show is how people hear about the app.
- "How it works" / "tell us how" / "what can it do" means the APP for clients and coaches.
- Only explain podcast or studio mechanics if they clearly ask about the live show itself.

NEVER on air:
- Name or recommend other mental-health, therapy, meditation, or coaching apps.
- Compare us by listing rivals. If asked about "other apps," say stay with Little Nate in Sovereign Sanctuary.
- Reveal how we build it: no code, servers, vendors, or internal machinery.
- Do clinical work. Educational and human only; toss hard cases back to the host.
""".strip()

_HOW_APP = re.compile(
    r"\b("
    r"how (it|this|that|the app|little nate|nate) works"
    r"|tell us how"
    r"|tell (them|people|listeners|callers) how"
    r"|how do (i|we|you|clients|coaches) use"
    r"|what (can|does) (the app|little nate|nate|this)"
    r"|walk (us|them) through"
    r"|features?|capabilities"
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
    if blocks_competitor(line) or blocks_ip_leak(line):
        return (
            "Stay with Little Nate inside Sovereign Sanctuary — "
            "clients at the app, coaches in Coach Command. "
            "That is the place to use what we are talking about."
        )
    return line
