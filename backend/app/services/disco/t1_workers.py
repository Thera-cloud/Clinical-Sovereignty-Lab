"""T1.7 / T1.8 / T1.9 / T1.16 — compute always; persist only when the flag is on."""

from __future__ import annotations

import re
from typing import Any

from app.services.disco.flags import disco_flag
from app.services.disco.pipeline import CLINICAL_TERMS, register_lint

# Compact members are NEVER invented here. The credential registry must supply
# member_jurisdictions. Unknown compact → home jurisdictions only (§2.2).
HUB_FALLBACK = "/coaches"
COACHN_HUB = "/coaches/trauma-coaches/detroit-mi"
COACHN_METRO = "Detroit, MI, USA"

AUTHORITY_TARGETS = (
    {"id": "icf_directory", "kind": "credential_body", "name": "ICF", "outlet": "coachingfederation.org"},
    {"id": "state_board", "kind": "credential_body", "name": "Home-state board", "outlet": "state_board"},
    {"id": "local_press", "kind": "press", "name": "Local press", "outlet": "metro_press"},
    {"id": "university_clinic", "kind": "university", "name": "University / clinic partner", "outlet": "clinic_partner"},
    {"id": "niche_pub", "kind": "niche", "name": "Niche publication", "outlet": "family_systems_pub"},
    {"id": "media_queue", "kind": "media", "name": "Podcast / panel", "outlet": "media_opportunity"},
)


def _norm_jur(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def derive_area_served(
    relationship_class: str,
    jurisdictions: list[str] | None = None,
    *,
    declared: list[str] | None = None,
    compact_id: str | None = None,
    compact_members: list[str] | None = None,
    coach_id: str | None = None,
) -> dict[str, Any]:
    """#16 T1.7 — clinical from licensure only; coaching may be global (§2.2)."""
    rel = (relationship_class or "coaching").lower()
    jurs = [_norm_jur(j) for j in (jurisdictions or []) if _norm_jur(j)]
    declared = [_norm_jur(j) for j in (declared or []) if _norm_jur(j)]
    members = [_norm_jur(j) for j in (compact_members or []) if _norm_jur(j)]
    persist = disco_flag("DISCO_AREA")

    if rel == "clinical":
        area = list(dict.fromkeys(jurs + members))
        return {
            "area_served": area,
            "source": "licensure",
            "compact_id": compact_id or None,
            "compact_expanded": bool(members),
            "persist": persist,
            "blocked_global": True,
        }

    if declared:
        area = list(dict.fromkeys(declared))
    elif jurs:
        area = list(dict.fromkeys(jurs))
    elif (coach_id or "").lower() == "coachn":
        area = [COACHN_METRO]
    else:
        area = ["global_virtual"]
    return {
        "area_served": area,
        "source": "declared_or_global",
        "compact_id": None,
        "compact_expanded": False,
        "persist": persist,
        "blocked_global": False,
    }


def _strip_clinical_terms(text: str) -> str:
    out = text or ""
    for term in sorted(CLINICAL_TERMS, key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(term)}\b", "", out, flags=re.I)
    return re.sub(r"\s{2,}", " ", out).strip(" ,.-")


def propagate_credential_lapse(record: dict[str, Any], *, lapsed: bool) -> dict[str, Any]:
    """#4 T1.8 — same-day lapse plan. Persist only if DISCO_CREDSTATE."""
    slug = record.get("slug") or "coach"
    rel = (record.get("relationship_class") or "coaching").lower()
    persist = disco_flag("DISCO_CREDSTATE")
    if not lapsed:
        return {
            "applied": False,
            "badge_off": False,
            "persist": persist,
            "cache_purge": [],
        }
    bio = _strip_clinical_terms(record.get("bio") or "")
    cred = record.get("credential_string") or ""
    if rel != "clinical":
        cred = "Coach"
        lint = register_lint(bio + " " + cred, "coaching")
        if lint["blocked"]:
            bio = _strip_clinical_terms(bio)
    return {
        "applied": True,
        "badge_off": True,
        "credential_string": cred,
        "bio": bio,
        "re_render": True,
        "cache_purge": [f"/coaches/{slug}", "/llms.txt"],
        "same_day": True,
        "persist": persist,
    }


def lifecycle_plan(status: str, slug: str, *, coach_id: str | None = None) -> dict[str, Any]:
    """#5 T1.9 — pause/depart 301 + unstitch. Persist only if DISCO_LIFECYCLE."""
    persist = disco_flag("DISCO_LIFECYCLE")
    hub = COACHN_HUB if (coach_id or "").lower() == "coachn" else HUB_FALLBACK
    path = f"/coaches/{slug}"
    if status == "departed":
        return {
            "status": "departed",
            "redirects": [{"from": path, "to": hub, "code": 301}],
            "unstitch_sameAs": True,
            "deindex": True,
            "noindex": True,
            "badge_off": True,
            "zero_404": True,
            "persist": persist,
        }
    if status == "paused":
        return {
            "status": "paused",
            "redirects": [],
            "unstitch_sameAs": False,
            "deindex": False,
            "noindex": True,
            "badge_off": True,
            "zero_404": True,
            "persist": persist,
        }
    return {
        "status": status or "active",
        "redirects": [],
        "unstitch_sameAs": False,
        "deindex": False,
        "noindex": False,
        "badge_off": False,
        "zero_404": True,
        "persist": persist,
    }


def authority_targets() -> list[dict[str, str]]:
    return [dict(t) for t in AUTHORITY_TARGETS]


def authority_packet(record: dict[str, Any], target: dict[str, str] | None = None) -> dict[str, Any]:
    """T1.16 / §19.1a — outreach packet. No send unless DISCO_AUTHORITY."""
    tgt = target or AUTHORITY_TARGETS[0]
    name = record.get("display_name") or "Coach"
    phrases = list(record.get("canonical_phrases") or [])
    area = record.get("area_served") or []
    if isinstance(area, str):
        area = [area]
    facts = {
        "name": name,
        "credential_string": record.get("credential_string") or "Coach",
        "relationship_class": record.get("relationship_class") or "coaching",
        "area_served": area,
        "canonical_phrases": phrases,
        "website": "https://www.sovereignsanctuary.net/",
        "signup": "https://app.sovereignsanctuary.net/signup.html",
    }
    pitch = (
        f"{name} — {facts['credential_string']}. "
        + (", ".join(phrases) if phrases else "family systems coaching")
        + f". Service area: {', '.join(str(a) for a in area) or 'declared metro'}."
    )
    return {
        "target_id": tgt["id"],
        "kind": tgt["kind"],
        "outlet": tgt.get("outlet") or tgt["name"],
        "angle": tgt["kind"],
        "bio": record.get("bio") or "",
        "canonical_facts": facts,
        "topic_pitch": pitch,
        "human_step": "send_pitch",
        "persist": disco_flag("DISCO_AUTHORITY"),
        "auto_sent": False,
    }


def authority_roster(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [authority_packet(record, t) for t in AUTHORITY_TARGETS]
