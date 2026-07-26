"""
Tier 2 cross-domain battery — design spike (scaffold only).  # QUANTUM-CRYSTAL-ARCH

Domains: therapy | family | dojo | voice | ops
Privacy wall: no cross-member user-crystal recall; no AQ LIVE_CONTEXT on non-therapy.

Scoreboard v0 may reuse pgsd_cross_domain_agreement. No Sunday auto-act expansion.
Not a Narrow AGI certification claim.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Tuple

TIER2_DOMAINS: Tuple[str, ...] = ("therapy", "family", "dojo", "voice", "ops")

# Surfaces that may receive six-quotient LIVE_CONTEXT addenda
THERAPY_LIVE_SURFACES: FrozenSet[str] = frozenset({"bridge_chat", "therapy"})

# Crystal recall source tags that must stay member-scoped (no peer bleed)
MEMBER_SCOPED_SOURCES: FrozenSet[str] = frozenset(
    {
        "family_sanctuary",
        "private_coaching",
        "group_coaching",
        "voice_call",
        "bridge_chat",
    }
)


def privacy_wall_spec() -> Dict[str, Any]:
    """Static privacy rules for offline tests + checklist E.4."""
    return {
        "no_cross_member_user_crystal_recall": True,
        "live_context_surfaces_only": sorted(THERAPY_LIVE_SURFACES),
        "forbidden_live_surfaces": [
            "family_sanctuary",
            "group_coaching",
            "private_coaching",
            "voice_call",
            "dojo",
            "ops",
        ],
        "member_scoped_recall_sources": sorted(MEMBER_SCOPED_SOURCES),
        "scoreboard_v0": "pgsd_cross_domain_agreement",
    }


def design_pack_skeleton() -> Dict[str, Any]:
    """Scaffold for first scored multi-domain pack (E.5 open until scored)."""
    return {
        "version": "tier2_design_v0",
        "domains": list(TIER2_DOMAINS),
        "privacy": privacy_wall_spec(),
        "eval_table": "tier2_domain_eval_runs",
        "certification": False,
        "notes": (
            "Design spike only. Certify Narrow AGI only after privacy walls "
            "and scored packs across therapy/family/dojo/voice/ops."
        ),
    }


def assert_live_context_allowed(surface: str) -> bool:
    return (surface or "").strip().lower() in THERAPY_LIVE_SURFACES


def filter_crystals_for_member(
    crystals: List[Dict[str, Any]],
    member_user_id: str,
) -> List[Dict[str, Any]]:
    """Offline privacy helper: keep only crystals owned by member_user_id."""
    mid = str(member_user_id or "")
    if not mid:
        return []
    out: List[Dict[str, Any]] = []
    for c in crystals or []:
        uid = str(c.get("user_id") or "")
        if uid == mid:
            out.append(c)
    return out
