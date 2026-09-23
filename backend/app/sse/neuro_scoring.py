"""Neuro region scoring — theme stems → 4 structures → 12 poles → place + champion.

QUANTUM-CRYSTAL-ARCH — additive to Thera-world. Pure functions, no DB, no LLM.

Methodology (engine-only): the theme stems already mined from a client's crystals
(`thera_world_engine._THEME_KEYWORDS`) are synced onto four psyche structures —
authority, integration, separation, attachment — each measured on three poles:

    deficit  ∈ [-1, 0]   (stored signed; harvested magnitude is negated)
    mature   ∈ [ 0, 1]
    hyper    ∈ [ 0, 1]

    H_d = mature_d - abs(deficit_d) - hyper_d          (per structure, max 1)
    H   = mean(H_d)                                     (world health)

Client language wall: nothing in this module that is returned to a client
surface may contain the structure names as labels or any numeric score.
`assert_client_safe()` is the guard; composers call it before returning copy.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.sse.thera_world_regions import (
    BIOME_TO_STRUCTURE,
    COLISEUM_FLOORS,
    NEURO_BIOMES,
    NEURO_POLES,
    NEURO_STRUCTURES,
    EXPLORE_WANDER,
    REGION_NEURO,
    REGION_ORIGIN,
    STRUCTURE_TO_BIOME,
)

# ---------------------------------------------------------------------------
# Stem → structure sync (the "methodology" LN learns from this client)
# ---------------------------------------------------------------------------

# theme stem (key of _THEME_KEYWORDS) -> (structure, pole)
STEM_TO_POLE: Dict[str, Tuple[str, str]] = {
    # authority — voice / agency
    "control": ("authority", "hyper"),
    "anger": ("authority", "hyper"),
    "fear": ("authority", "deficit"),
    "identity": ("authority", "deficit"),
    "self-worth": ("authority", "deficit"),
    # integration — holding both
    "shame": ("integration", "deficit"),
    "guilt": ("integration", "deficit"),
    "trauma": ("integration", "deficit"),
    "perfectionism": ("integration", "hyper"),
    "forgiveness": ("integration", "mature"),
    # separation — own name
    # "boundaries" is the corrective move (a limit, an own name), not a deficit.
    # Enmeshment stays on codependency.
    "boundaries": ("separation", "mature"),
    # Co-dependency is the attachment defense (enmeshment), not a missing boundary.
    # Boundaryless diffusion stays a separation deficit when the stem is about having no "no".
    "codependency": ("attachment", "hyper"),
    "rejection": ("separation", "hyper"),
    # themes the miner already counts that previously moved no pole
    "anxiety": ("authority", "deficit"),
    "resentment": ("authority", "hyper"),
    "deception": ("integration", "hyper"),
    "grief": ("attachment", "deficit"),
    "loss": ("attachment", "deficit"),
    "depression": ("attachment", "deficit"),
    # attachment — hearth
    "attachment": ("attachment", "hyper"),
    "love": ("attachment", "mature"),
    "trust": ("attachment", "deficit"),
    "abandonment": ("attachment", "deficit"),
    "loneliness": ("attachment", "deficit"),
    "vulnerability": ("attachment", "mature"),
}

# Stems that signal growth across all four structures (light mature lift).
GROWTH_STEMS: Tuple[str, ...] = ("growth", "hope", "discovery", "wonder", "faith", "spiritual")
GROWTH_WEIGHT = 0.5

STEM_TO_STRUCTURE: Dict[str, str] = {k: v[0] for k, v in STEM_TO_POLE.items()}
STRUCTURE_STEMS: Dict[str, Tuple[str, ...]] = {
    s: tuple(k for k, v in STEM_TO_POLE.items() if v[0] == s) for s in NEURO_STRUCTURES
}

POLE_KEYS: Tuple[str, ...] = tuple(f"{s}_{p}" for s in NEURO_STRUCTURES for p in NEURO_POLES)

# Rolling blend — new evidence moves the stored vector by this fraction.
ROLLING_ALPHA = 0.35
# Minimum stem hits before a pole registers at full intensity.
_INTENSITY_FLOOR = 4.0

# Region routing (engine-only).
# The journey walks Origin and Neuro. A healthy or quiet vector still enters
# Neuro — growth is not gated on a deficit. Back-to-back Neuro days are reserved
# for a deeply strained structure (corrective intensity).
NEURO_DEEP_HD = -0.5
NEURO_ENV_FLAG = "SSE_NEURO_REGION_ENABLED"

_FORBIDDEN_LABELS = re.compile(
    r"\b(authority|integration|separation|attachment)\b", re.IGNORECASE
)
_FORBIDDEN_SCORE = re.compile(
    r"(-?\d\.\d+|\d+\s?%|\byour deficit\b|\bhyper-?regulated\b|\bmature adult level\b)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Pole math
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def normalize_poles(raw: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Return a full 12-key vector with sign/range enforced. Missing keys → 0."""
    out: Dict[str, float] = {}
    src = raw or {}
    for s in NEURO_STRUCTURES:
        for p in NEURO_POLES:
            key = f"{s}_{p}"
            try:
                v = float(src.get(key, 0.0) or 0.0)
            except (TypeError, ValueError):
                v = 0.0
            if math.isnan(v):
                v = 0.0
            if p == "deficit":
                # accept harvested magnitude (positive) or stored signed value
                v = -abs(v)
                out[key] = _clamp(v, -1.0, 0.0)
            else:
                out[key] = _clamp(v, 0.0, 1.0)
    return out


def domain_health(scores: Dict[str, Any], structure: str) -> float:
    s = normalize_poles(scores)
    return s[f"{structure}_mature"] - abs(s[f"{structure}_deficit"]) - s[f"{structure}_hyper"]


def all_domain_health(scores: Dict[str, Any]) -> Dict[str, float]:
    return {d: domain_health(scores, d) for d in NEURO_STRUCTURES}


def neuro_health(scores: Dict[str, Any]) -> float:
    hd = all_domain_health(scores)
    return sum(hd.values()) / float(len(NEURO_STRUCTURES))


# Three measurement ranges. Center and upper are both 0..1 and must not be
# collapsed: center is calm integration, upper is defensive over-compensation.
BAND_LOWER = "lower"    # deficit, stored -1..0 — passive / deficient injury path
BAND_CENTER = "center"  # mature, 0..1 — authentic calm mastery
BAND_UPPER = "upper"    # hyper, 0..1 — defensive / high-anxiety over-compensation
BAND_BOTH = "oscillating"  # both injury paths loud; change still aims at center
BAND_QUIET = "quiet"

# Lived picture for the still. No structure names — safe if a phrase reaches the image prompt.
IMAGE_CHANGE: Dict[str, Dict[str, str]] = {
    "authority": {
        BAND_LOWER: "The figure is small in the hall and will not take the floor. The meeting offers one step of a steady voice, not a throne and not a further collapse.",
        BAND_CENTER: "The figure stands as an equal. Keep the light calm. Do not crown them and do not shrink them.",
        BAND_UPPER: "The figure is gripping the hall too hard, the grip covering a fear. The meeting loosens that grip toward shared ground, without dropping them into helplessness.",
        BAND_BOTH: "The figure swings between shrinking and forcing the room. The meeting finds the middle stance: a voice that neither disappears nor dominates.",
        BAND_QUIET: "Nothing in this hall is loud yet. Keep the meeting open and ungraded.",
    },
    "integration": {
        BAND_LOWER: "The figure is coming apart under one hard look, sunk in shame. The meeting helps them stay present with a flaw without the flaw becoming the whole person.",
        BAND_CENTER: "The figure can own a mistake and still keep their worth. Deepen that groundedness. Do not polish them into a mask.",
        BAND_UPPER: "The figure is wearing a perfect mask and will not let a crack show. The meeting lets one true flaw be visible without the mask shattering into self-hatred.",
        BAND_BOTH: "The figure swings between self-hatred and a perfect mask. The meeting holds one real flaw and one real worth in the same light.",
        BAND_QUIET: "No crack and no mask are loud yet. Keep the meeting open and ungraded.",
    },
    "separation": {
        BAND_LOWER: "The figure has no edge: other people's weather moves straight through them, and they cannot say no. The meeting grows one calm limit that is not an exile.",
        BAND_CENTER: "The figure keeps their own name and stays near. Deepen that. Do not wall them off and do not dissolve them.",
        BAND_UPPER: "The figure has built a wall and reads closeness as a threat to freedom. The meeting opens one gate without tearing the wall down into diffusion.",
        BAND_BOTH: "The figure swings between having no edge and sealing every gate. The meeting practices one limit that still lets someone near.",
        BAND_QUIET: "No wall and no flood are loud yet. Keep the meeting open and ungraded.",
    },
    "attachment": {
        BAND_LOWER: "The figure circles the fire and will not sit, shut off from relying on anyone. The meeting offers one moment of trusting nearness without fusion.",
        BAND_CENTER: "The figure can ask for warmth and keep a self. Deepen that. Do not fuse them and do not send them back into the cold.",
        BAND_UPPER: "The figure is fused to the other, smothering, giving themselves away to avoid being left. The meeting returns a little room without abandoning them.",
        BAND_BOTH: "The figure swings between total shutdown and total fusion. The meeting practices nearness that still leaves room.",
        BAND_QUIET: "No shutdown and no fusion are loud yet. Keep the meeting open and ungraded.",
    },
}


def active_band(scores: Dict[str, Any], structure: str) -> str:
    """Which path is driving this structure. Center is not the upper band.

    Upper and center are both positive. The louder neural driver wins. When
    both injury paths are material, the person is oscillating; the aim is
    still the calm center, not either injury.
    """
    s = normalize_poles(scores)
    lower = abs(s[f"{structure}_deficit"])
    center = s[f"{structure}_mature"]
    upper = s[f"{structure}_hyper"]
    if lower < 0.2 and center < 0.2 and upper < 0.2:
        return BAND_QUIET
    if lower >= 0.35 and upper >= 0.35:
        return BAND_BOTH
    if upper >= 0.35 and upper >= center and upper >= lower:
        return BAND_UPPER
    if lower >= 0.35 and lower >= center and lower >= upper:
        return BAND_LOWER
    if center > 0 and center >= lower and center >= upper:
        return BAND_CENTER
    if lower >= upper and lower > 0:
        return BAND_LOWER
    if upper > 0:
        return BAND_UPPER
    return BAND_QUIET


def image_change_line(scores: Dict[str, Any], structure: str) -> str:
    """Client-safe direction for the still: change toward the calm center."""
    band = active_band(scores, structure)
    return IMAGE_CHANGE[structure][band]


def compose_growth_navigation(scores: Dict[str, Any]) -> str:
    """Main-chat map. Engine-only: Nate may read the labels; the client must not hear them."""
    lines = [
        "NEURO GROWTH MAP — internal only. Never say these labels. Never quote a number, a level, or a grade.",
        "Each capacity has three paths of one injury: a passive deficient path (below center), "
        "a calm integrated center, and a defensive over-compensation (above center, high-anxiety, not mastery). "
        "The center and the defense both look strong. They are not the same. "
        "Neuroplastic change always aims at the calm center. "
        "Do not push a collapsed person up into the defense. Do not collapse a defended person down into shutdown. "
        "If both injury paths are loud, they are swinging; meet the swing and aim at the middle.",
    ]
    for structure in NEURO_STRUCTURES:
        band = active_band(scores, structure)
        lines.append(f"- {structure}: path={band}. {IMAGE_CHANGE[structure][band]}")
    lines.append(
        "In this reply, meet the path they are on and offer one lived step toward the calm center. Do not name the map."
    )
    return "\n".join(lines)


def classify_stage(scores: Dict[str, Any], structure: str) -> str:
    """Derived, not a 13th score: underdeveloped | developing | mature | quiet."""
    s = normalize_poles(scores)
    mature = s[f"{structure}_mature"]
    strain = abs(s[f"{structure}_deficit"]) + s[f"{structure}_hyper"]
    if mature >= 0.75 and strain <= 0.35:
        return "mature"
    if mature < 0.35 and abs(s[f"{structure}_deficit"]) >= 0.5:
        return "underdeveloped"
    if 0.25 < mature < 0.75 and strain > 0.25:
        return "developing"
    if mature == 0 and strain == 0:
        return "quiet"
    return "developing"


def blend_scores(prev: Optional[Dict[str, Any]], fresh: Dict[str, Any], alpha: float = ROLLING_ALPHA) -> Dict[str, float]:
    """Rolling update: prev*(1-alpha) + fresh*alpha. No prev → fresh."""
    f = normalize_poles(fresh)
    if not prev:
        return f
    p = normalize_poles(prev)
    return normalize_poles({k: p[k] * (1.0 - alpha) + f[k] * alpha for k in POLE_KEYS})


# ---------------------------------------------------------------------------
# Harvest: theme counts (already mined from crystals) → 12 poles
# ---------------------------------------------------------------------------

def scores_from_theme_counts(theme_counts: Optional[Dict[str, int]]) -> Dict[str, float]:
    """Heuristic v1. Same crystals that drive Origin panels; no new harvest pass."""
    tc = {str(k): int(v or 0) for k, v in (theme_counts or {}).items()}
    raw: Dict[str, float] = {k: 0.0 for k in POLE_KEYS}
    for stem, cnt in tc.items():
        if cnt <= 0:
            continue
        hit = STEM_TO_POLE.get(stem)
        if hit:
            raw[f"{hit[0]}_{hit[1]}"] += cnt
        elif stem in GROWTH_STEMS:
            for s in NEURO_STRUCTURES:
                raw[f"{s}_mature"] += cnt * GROWTH_WEIGHT / len(NEURO_STRUCTURES)
    top = max(raw.values()) if raw else 0.0
    scale = max(_INTENSITY_FLOOR, top)
    if top <= 0:
        return normalize_poles({})
    return normalize_poles({k: v / scale for k, v in raw.items()})


def neuro_metadata_for_stems(stems: Iterable[str]) -> Dict[str, Any]:
    """Crystal metadata stamp from mined stems. Keeps domain=clinical untouched.

    Returns {neuro_stems, neuro_structures, neuro_pole_hint?}. `neuro_pole_hint`
    is present only when the polarity is unambiguous across the hit stems.
    """
    hits = [s for s in stems if s in STEM_TO_POLE]
    structures: List[str] = []
    poles: List[str] = []
    for s in hits:
        st, pole = STEM_TO_POLE[s]
        if st not in structures:
            structures.append(st)
        poles.append(pole)
    meta: Dict[str, Any] = {
        "neuro_stems": list(dict.fromkeys(str(s) for s in stems)),
        "neuro_structures": structures,
    }
    if poles and len(set(poles)) == 1:
        meta["neuro_pole_hint"] = poles[0]
    return meta


# ---------------------------------------------------------------------------
# Place + champion selection
# ---------------------------------------------------------------------------

def select_neuro_biome(scores: Dict[str, Any], *, avoid: Optional[Iterable[str]] = None) -> str:
    """Setting doorway = weakest H_d, skipping places already walked recently.

    Tie order is the fixed structure order. `avoid` is how the journey visits
    all four Neuro places instead of camping on one strained doorway.
    """
    hd = all_domain_health(scores)
    ranked = sorted(NEURO_STRUCTURES, key=lambda d: (hd[d], NEURO_STRUCTURES.index(d)))
    skipped = {a for a in (avoid or []) if a}
    for d in ranked:
        bid = STRUCTURE_TO_BIOME[d]
        if bid not in skipped:
            return bid
    return STRUCTURE_TO_BIOME[ranked[0]]


_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "neuro_champions.json")
_roster_cache: Optional[List[Dict[str, Any]]] = None


def load_champions() -> List[Dict[str, Any]]:
    global _roster_cache
    if _roster_cache is None:
        with open(_DATA_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        rows = []
        for c in data.get("champions", []):
            row = dict(c)
            row["poles"] = normalize_poles(c.get("poles") or {})
            rows.append(row)
        _roster_cache = rows
    return list(_roster_cache)


def champions_for_biome(biome_id: str, roster: Optional[Sequence[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    return [c for c in (roster or load_champions()) if c.get("biome_id") == biome_id]


def champion_by_name(name: str, roster: Optional[Sequence[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    n = (name or "").strip().lower()
    if not n:
        return None
    for c in (roster or load_champions()):
        if (c.get("name") or "").lower() == n or (c.get("id") or "").lower() == n:
            return c
    return None


def is_neuro_champion(name: str) -> bool:
    return champion_by_name(name) is not None


def _l2(a: Dict[str, float], b: Dict[str, float]) -> float:
    return math.sqrt(sum((a[k] - b[k]) ** 2 for k in POLE_KEYS))


# Literal-force / death figures. Age-gated panels must not pair these.
AGE_GATE_EXCLUDE: Tuple[str, ...] = (
    "Warlord", "Dragon Sovereign", "Beast Queen", "Death Knight", "Leviathan",
)


def pair_champion(
    scores: Dict[str, Any],
    biome_id: str,
    roster: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    skip_names: Iterable[str] = (),
    exclude_names: Iterable[str] = (),
    epsilon: float = 1e-6,
) -> Optional[Dict[str, Any]]:
    """Nearest champion (L2 on the 12-vector) within the selected place only.

    `skip_names` lets the caller avoid repeating yesterday's mirror; if every
    candidate is skipped the nearest overall is returned. `exclude_names` is
    a hard drop (age-gate) — those figures are never returned.
    """
    user = normalize_poles(scores)
    banned = {s.lower() for s in exclude_names if s}
    cands = [c for c in champions_for_biome(biome_id, roster) if (c.get("name") or "").lower() not in banned]
    if not cands:
        return None
    skip = {s.lower() for s in skip_names if s}
    ranked = sorted(cands, key=lambda c: (_l2(user, c["poles"]), c.get("id", "")))
    for c in ranked:
        if (c.get("name") or "").lower() in skip:
            continue
        # ε-skip: a champion with an identical vector is a copy, not a mirror
        if _l2(user, c["poles"]) < epsilon and len(ranked) > 1:
            continue
        return c
    return ranked[0]


def visiting_figures(
    scores: Dict[str, Any],
    biome_id: str,
    k: int = 2,
    roster: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    exclude_names: Iterable[str] = (),
) -> List[Dict[str, Any]]:
    """1–2 champions from OTHER Neuro places at middle distance, so the panel is
    not a single-structure classroom. One per other place, weakest H_d first."""
    k = max(0, min(2, int(k)))
    if k == 0:
        return []
    hd = all_domain_health(scores)
    home = BIOME_TO_STRUCTURE.get(biome_id)
    others = [d for d in sorted(NEURO_STRUCTURES, key=lambda d: (hd[d], NEURO_STRUCTURES.index(d))) if d != home]
    out: List[Dict[str, Any]] = []
    for d in others[:k]:
        c = pair_champion(scores, STRUCTURE_TO_BIOME[d], roster, exclude_names=exclude_names)
        if c:
            out.append(c)
    return out


def roll_coliseum_floor(seed: Optional[str] = None) -> str:
    """Every Coliseum panel rolls one floor from the allowlist."""
    rng = random.Random(seed) if seed else random
    return rng.choice(COLISEUM_FLOORS)


# ---------------------------------------------------------------------------
# Region routing
# ---------------------------------------------------------------------------

def neuro_enabled() -> bool:
    return os.getenv(NEURO_ENV_FLAG, "true").strip().lower() in ("1", "true", "yes", "on")


def neuro_unlocked(journey: Optional[Dict[str, Any]], scores: Optional[Dict[str, Any]]) -> bool:
    """Unlock = a Neuro score row exists (neuro_last_scored_at) OR Origin reached open_sky."""
    j = journey or {}
    if (j.get("current_biome") or "") == "open_sky":
        return True
    if j.get("neuro_last_scored_at"):
        return True
    prev = j.get("neuro_scores")
    if isinstance(prev, str):
        try:
            prev = json.loads(prev)
        except Exception:
            prev = None
    if isinstance(prev, dict) and any(abs(float(v or 0)) > 0 for v in prev.values()):
        return True
    return False


def explore_region_choice(journey: Optional[Dict[str, Any]]) -> str:
    """Client pick stored on journey_metadata.explore_region. Default wander."""
    meta = (journey or {}).get("journey_metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    if not isinstance(meta, dict):
        meta = {}
    choice = str(meta.get("explore_region") or EXPLORE_WANDER).strip().lower()
    if choice in (REGION_ORIGIN, REGION_NEURO, EXPLORE_WANDER):
        return choice
    return EXPLORE_WANDER


def resolve_panel_region(
    journey: Optional[Dict[str, Any]],
    scores: Dict[str, Any],
    *,
    last_region: str = REGION_ORIGIN,
) -> str:
    """Which stream fills today's single image slot.

    A client pick of Origin or Neuro wins. Wander (the default) alternates
    once Neuro is unlocked. A deeply strained structure may stay in Neuro a
    second day. Healthy, quiet, and zero vectors are not locked out.
    """
    if not neuro_enabled():
        return REGION_ORIGIN
    choice = explore_region_choice(journey)
    if choice == REGION_ORIGIN:
        return REGION_ORIGIN
    if choice == REGION_NEURO:
        return REGION_NEURO
    if not neuro_unlocked(journey, scores):
        return REGION_ORIGIN
    hd = all_domain_health(scores)
    weakest = min(hd.values()) if hd else 0.0
    if last_region == REGION_NEURO and weakest > NEURO_DEEP_HD:
        return REGION_ORIGIN
    return REGION_NEURO


def scrub_client_copy(text: str) -> str:
    """Rewrite leaked engine labels in client-facing scene text. Never blank the scene."""
    out = text or ""
    out = re.sub(r"\bauthority\b", "voice", out, flags=re.IGNORECASE)
    out = re.sub(r"\bintegration\b", "holding both", out, flags=re.IGNORECASE)
    out = re.sub(r"\bseparation\b", "an own name", out, flags=re.IGNORECASE)
    out = re.sub(r"\battachment\b", "the hearth", out, flags=re.IGNORECASE)
    out = re.sub(r"-?\d+\.\d+", "", out)
    out = re.sub(r"\d+\s?%", "", out)
    out = re.sub(r"\byour deficit\b", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\bhyper-?regulated\b", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\bmature adult level\b", "", out, flags=re.IGNORECASE)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def compose_neuro_bible(ctx: Dict[str, Any]) -> str:
    """LLM-only block. Place, figure, corrective meeting. No scores."""
    meta = ctx.get("metadata") or {}
    champ = ctx.get("champion") or {}
    biome = ctx.get("biome") or {}
    place = meta.get("place_label") or biome.get("biome") or ""
    name = champ.get("name") or ""
    purpose = champ.get("purpose") or ""
    healing = biome.get("healing_visual") or meta.get("healing_visual") or ""
    floor_id = ctx.get("floor_id") or meta.get("floor_id")
    visitors = ", ".join(meta.get("visitors") or []) or "none"
    lines = [
        f"NEURO REGION — same Thera-world as the Path of Five, not a second world. Today's place: {place}.",
        f"This panel is a corrective relational meeting between the protagonist and {name}.",
        f"Why {name} is here: {purpose}",
        f"Other figures at middle distance (keep them in frame): {visitors}.",
        "The meeting practices four lived moves together in this one scene: a voice that neither shrinks nor crushes, holding two true things at once, an own name that is not exile, and warmth that still leaves room. Do not sequence them as lessons. Do not grade them.",
        "Never write the words authority, integration, separation, or attachment. Never write a score, a percent, a level, or a grade.",
    ]
    if healing:
        lines.append(f"Include this healing image in the scene and the image prompt: {healing}")
    if floor_id:
        lines.append(f"Coliseum floor for this still: {floor_id}.")
    scores = ctx.get("scores") or {}
    biome_id = ""
    if isinstance(biome, dict):
        biome_id = biome.get("biome") or ""
    structure = BIOME_TO_STRUCTURE.get(biome_id) or champ.get("structure") or ""
    if structure in NEURO_STRUCTURES and scores:
        lines.append(image_change_line(scores, structure))
        lines.append(
            "The still is one step of change toward calm balance. Do not portrait the injury as destiny "
            "and do not celebrate the defense as strength."
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Client language wall + copy composers
# ---------------------------------------------------------------------------

def client_safe_violations(text: str) -> List[str]:
    found: List[str] = []
    for m in _FORBIDDEN_LABELS.finditer(text or ""):
        found.append(m.group(0))
    for m in _FORBIDDEN_SCORE.finditer(text or ""):
        found.append(m.group(0))
    return found


def assert_client_safe(text: str) -> str:
    """Raise if client-facing Neuro copy leaks a structure label or a score."""
    bad = client_safe_violations(text)
    if bad:
        raise ValueError(f"Neuro client copy leaks engine terms: {bad!r}")
    return text


# What each champion's *stance* sounds like in myth — per structure, per lean.
_STANCE_PHRASES: Dict[str, Dict[str, str]] = {
    "authority": {
        "deficit": "what it is to want a voice and not take it",
        "hyper": "what it costs to hold a floor by force",
        "mature": "how to stand on a floor without shrinking or crushing",
    },
    "integration": {
        "deficit": "how hard it is to look at the cold current",
        "hyper": "the pull to call the bright water the whole sea",
        "mature": "how two true things can share one harbor",
    },
    "separation": {
        "deficit": "how easy it is to live under someone else's shadow",
        "hyper": "the safety of cutting every tether",
        "mature": "how a bridge can stay without becoming a chain",
    },
    "attachment": {
        "deficit": "what it is to circle the fire and not sit down",
        "hyper": "the grip that keeps a bridge from breathing",
        "mature": "how to ask for warmth and for room in the same breath",
    },
}


def _lean(vec: Dict[str, float], structure: str) -> str:
    d, m, h = abs(vec[f"{structure}_deficit"]), vec[f"{structure}_mature"], vec[f"{structure}_hyper"]
    if m >= d and m >= h and m > 0:
        return "mature"
    if d >= h and d > 0:
        return "deficit"
    if h > 0:
        return "hyper"
    return "mature"


# Second person, for the Legend. Same three bands as IMAGE_CHANGE, spoken to the
# person rather than directed at the image model. No structure names, no scores.
LEGEND_YOU: Dict[str, Dict[str, str]] = {
    "authority": {
        BAND_LOWER: "You are small in the hall and have not taken the floor. The step is one steady voice — not a throne, and not a further collapse.",
        BAND_CENTER: "You are standing as an equal. Keep that. Do not take a crown, and do not shrink.",
        BAND_UPPER: "You are gripping the hall hard, and the grip is covering a fear. The step is to loosen toward shared ground without falling into helplessness.",
        BAND_BOTH: "You swing between shrinking and forcing the room. The step is a voice that neither disappears nor dominates.",
        BAND_QUIET: "Nothing in this hall is loud in you yet. Stay with the meeting. It is not a grade.",
    },
    "integration": {
        BAND_LOWER: "You are coming apart under one hard look, sunk in shame. The step is to stay present with a flaw without the flaw becoming all of you.",
        BAND_CENTER: "You can own a mistake and still keep your worth. Deepen that. Do not polish it into a mask.",
        BAND_UPPER: "You are wearing a perfect mask and will not let a crack show. The step is to let one true flaw be visible without the mask shattering into self-hatred.",
        BAND_BOTH: "You swing between self-hatred and a perfect mask. The step is to hold one real flaw and one real worth in the same light.",
        BAND_QUIET: "No crack and no mask are loud in you yet. Stay with the meeting. It is not a grade.",
    },
    "separation": {
        BAND_LOWER: "You have no edge: other people's weather moves straight through you, and you cannot say no. The step is one calm limit that is not an exile.",
        BAND_CENTER: "You keep your own name and stay near. Deepen that. Do not wall yourself off, and do not dissolve.",
        BAND_UPPER: "You have built a wall and read closeness as a threat to freedom. The step is to open one gate without tearing the wall down into diffusion.",
        BAND_BOTH: "You swing between having no edge and sealing every gate. The step is one limit that still lets someone near.",
        BAND_QUIET: "No wall and no flood are loud in you yet. Stay with the meeting. It is not a grade.",
    },
    "attachment": {
        BAND_LOWER: "You circle the fire and will not sit, shut off from relying on anyone. The step is one moment of trusting nearness without fusion.",
        BAND_CENTER: "You can ask for warmth and keep a self. Deepen that. Do not fuse, and do not go back into the cold.",
        BAND_UPPER: "You are fused to the other, giving yourself away to avoid being left. The step is a little room without abandonment.",
        BAND_BOTH: "You swing between total shutdown and total fusion. The step is nearness that still leaves room.",
        BAND_QUIET: "No shutdown and no fusion are loud in you yet. Stay with the meeting. It is not a grade.",
    },
}


def legend_insight(scores: Optional[Dict[str, Any]], structure: str) -> str:
    """Client-safe Legend line: where this person is, and the one step toward center."""
    if structure not in NEURO_STRUCTURES:
        return ""
    band = active_band(scores or {}, structure)
    return LEGEND_YOU[structure][band]


def _band_lean(band: str) -> str:
    return {BAND_LOWER: "deficit", BAND_CENTER: "mature", BAND_UPPER: "hyper"}.get(band, "")


def compose_archetype_mirror(
    champion: Dict[str, Any],
    archetype_hint: str,
    user_scores: Optional[Dict[str, Any]] = None,
) -> str:
    """How this champion meets THIS person — no numbers, no structure labels.

    Without a score vector, do not invent a shared stance. With one, say where
    the person is (second person) and where the champion stands.
    """
    name = (champion.get("name") or "this figure").strip()
    st = champion.get("structure") or BIOME_TO_STRUCTURE.get(champion.get("biome_id", ""), "authority")
    cvec = normalize_poles(champion.get("poles") or {})
    arch = (archetype_hint or "").strip() or "traveler"
    phrase = _STANCE_PHRASES[st][_lean(cvec, st)]
    place = {
        "authority": "at the empty crowns",
        "integration": "on the center platform",
        "separation": "on the bridge between spires",
        "attachment": "beside the First Hearth",
    }[st]
    if not user_scores:
        text = (
            f"Your {arch} meets {name} {place}. "
            f"They know {phrase}. The meeting is for you to notice where you stand. It is not a grade."
        )
        return assert_client_safe(text)
    band = active_band(user_scores, st)
    you = legend_insight(user_scores, st)
    same = _band_lean(band) == _lean(cvec, st) and band not in (BAND_QUIET, BAND_BOTH)
    if same:
        text = f"Your {arch} meets {name} {place}. {you} They know that same pull: {phrase}."
    else:
        text = f"Your {arch} meets {name} {place}. {you} They stand somewhere else — they know {phrase}."
    return assert_client_safe(text)


# Four lived moves — the Go Deeper braid. Never named as structures to the client.
FOUR_MOVES: Tuple[Dict[str, str], ...] = (
    {
        "key": "voice",
        "structure": "authority",
        "move": "Stand, speak, claim a floor or a voice without shrinking and without crushing — "
                "the Crown of Verdict, not a performance review.",
    },
    {
        "key": "holding_both",
        "structure": "integration",
        "move": "Hold two true things at once — three currents, a mosaic that only reads whole "
                "from every side.",
    },
    {
        "key": "own_name",
        "structure": "separation",
        "move": "Keep your own lamp, your own name, a 'no' that is not exile — bridges, not chains.",
    },
    {
        "key": "hearth",
        "structure": "attachment",
        "move": "Ask for warmth, ask for space, say hurt without making it the last word of the bond — "
                "the First Hearth.",
    },
)


def four_move_braid_block(
    place_name: str,
    champion_name: str,
    visitors: Iterable[str] = (),
    change_line: str = "",
) -> str:
    """Protocol block for Go Deeper on a Neuro panel. All four moves, braided,
    in-scene. No structure labels, no scores, no homework list."""
    vis = [v for v in visitors if v]
    vis_line = (
        f"Visiting figures at middle distance ({', '.join(vis)}) give the other moves a body in frame. "
        if vis else ""
    )
    lines = [
        "[NEURO VISIT — four lived moves, one sitting]",
        f"This panel is in {place_name}; {champion_name} is the mirror in frame. "
        "The place is a doorway, not a lesson plan.",
        "Practice ALL FOUR moves inside the painted scene this visit — braid them (one sentence each, "
        "or two woven). They are invitations to do something in the picture, not to improve anything:",
    ]
    for mv in FOUR_MOVES:
        lines.append(f"  - {mv['move']}")
    lines += [
        vis_line + "Work them together. Do not sequence only the move that matches the place.",
        "SIFT doorways still come first, as four choices the person can pick: Sense, Image, Feel, Think. "
        "The four moves live inside whichever doorway they choose. Do not replace those choices.",
        "Never name a category, a score, a level, or 'today we work on'. No grades, "
        "no stock journaling trio. Speak place, figure, and the move itself.",
    ]
    if (change_line or "").strip():
        lines.append(change_line.strip())
        lines.append("That is the step of change in this visit. Keep all four moves in the same scene.")
    return assert_client_safe("\n".join(lines))


def neuro_score_snapshot(scores: Dict[str, Any]) -> Dict[str, Any]:
    """Engine/coach JSON (never client): scores, H_d, H, stages."""
    s = normalize_poles(scores)
    hd = all_domain_health(s)
    return {
        "scores": s,
        "h_d": hd,
        "h": neuro_health(s),
        "stages": {d: classify_stage(s, d) for d in NEURO_STRUCTURES},
        "bands": {d: active_band(s, d) for d in NEURO_STRUCTURES},
        "selected_biome": select_neuro_biome(s),
    }
