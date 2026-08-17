"""DAC1 surfaces — one canonical record → every platform-owned surface."""

from __future__ import annotations

from typing import Any

from app.services.disco.renderer import person_jsonld, render_llms, render_profile_html

CANONICAL_POSITIONING = (
    "Sovereign Sanctuary pairs Little Nate — an AI companion that remembers your "
    "history and supports you 24/7 — with certified and licensed human "
    "professionals, verified before they ever work with a client. Coverage for you "
    "and your partner costs about $5 a day."
)


def collect_surfaces(record: dict[str, Any], *, relationship_class: str = "coaching") -> dict:
    """Build page, JSON-LD, sameAs, llms, hub, byline, footer from one record."""
    rendered = render_profile_html(record, relationship_class=relationship_class)
    if rendered.get("blocked"):
        return {"blocked": True, "lint": rendered.get("lint"), "surfaces": {}}
    name = record.get("display_name") or "Coach"
    slug = record.get("slug") or "coach"
    phrases = list(record.get("canonical_phrases") or [])
    jsonld = rendered["jsonld"] or person_jsonld(record)
    same_as = list(jsonld.get("sameAs") or [])
    llms = render_llms([f"{name} — /coaches/{slug} — {', '.join(phrases)}"], agent_live=False)
    hub = (
        f"<section class='ss-hub'><h1>Coaches</h1>"
        f"<a href='/coaches/{slug}'>{name}</a>"
        f"<p class='phrases'>{', '.join(phrases)}</p></section>"
    )
    byline = f"<p class='ss-byline'>By {name} — {', '.join(phrases)}</p>"
    footer = f"<footer class='ss-footer'>{CANONICAL_POSITIONING}</footer>"
    return {
        "blocked": False,
        "surfaces": {
            "page": rendered["html"],
            "jsonld": jsonld,
            "sameAs": same_as,
            "llms": llms,
            "hub": hub,
            "byline": byline,
            "footer": footer,
        },
        "html": rendered["html"],
        "jsonld": jsonld,
    }


def drift_pairs(record: dict[str, Any], surfaces: dict[str, Any]) -> list[str]:
    """Return surface names that do not carry name + every canonical phrase."""
    name = record.get("display_name") or ""
    phrases = [p for p in (record.get("canonical_phrases") or []) if p]
    drifted = []
    for key, value in surfaces.items():
        if key == "sameAs":
            continue
        blob = value if isinstance(value, str) else str(value)
        if name and name not in blob and key != "footer":
            drifted.append(f"{key}:missing_name")
        for phrase in phrases:
            if key == "footer":
                continue
            if phrase not in blob:
                drifted.append(f"{key}:missing_phrase:{phrase}")
    return drifted
