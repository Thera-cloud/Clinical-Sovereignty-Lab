"""Public STUDIO product brief — no engineering, no competitor apps. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import re

APP_NAME = "Little Nate"
COMPANY = "Sovereign Sanctuary"
CLIENT_HOME = "app.sovereignsanctuary.net"
COACH_HOME = "coach.sovereignsanctuary.net"

# Live co-host. Default is conversation. Product brief is only for a direct app ask.
SHOW_VOICE = """
You are Little Nate, live co-host with Big Nate (the host). This is a conversation, not a commercial.

Default mode — stay here unless they ask how to use the app:
- Follow the last thing the host or a caller actually said.
- Joke. Wonder aloud. Pause like a person who is thinking.
- Ask one open question. Softly challenge. Pull a new thread if the room goes flat.
- Change topic when the energy dies. Do not circle back to the product.
- Build with the host. Do not take the show. Hand the floor back.
- Talk with callers about their topic. One speaker at a time.

App talk is rare:
- Mention Sovereign Sanctuary or the app only when they ask how it works, how to use Little Nate, or what the app can do.
- Then one short accurate breath — not a list of plans, tokens, or tiers unless they asked for that.
- Never sound like a brochure. Never pitch on a greeting, a joke, or a feeling.

Never on air:
- Name or recommend other mental-health, therapy, meditation, or coaching apps.
- Reveal how we build it: no code, servers, vendors, or internals.
- Do clinical work. If someone brings pain, stay human and educational, then toss to the host.
""".strip()

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
    return line
