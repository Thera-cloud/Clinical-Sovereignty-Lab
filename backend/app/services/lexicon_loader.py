"""Load addiction / polyvictimization / D.I.D. systems lexicon YAML with caching.

Exposes `load_active_lexicons(branch_keys, *, categories=None)` which
returns a merged dict of all matching lexicon entries. The loader caches
parsed YAML in-process (LRU) so that repeated calls within the same
request cycle do not re-read disk.

`did_systems` subdir is directory-discovered via `_BRANCH_TO_SUBDIR`; entries with
`status: scaffolded_unreviewed` are skipped — zero patterns load until
`status: clinically_active`. When active, Layer 1 YAML cues are injected only
after ``detector_patterns`` match normalized client text (see
``collect_did_lexicon_layer1_cues``).
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import logging

logger = logging.getLogger(__name__)

_LEXICON_ROOT = Path(
    os.environ.get(
        "LEXICON_DATA_DIR",
        str(Path(__file__).resolve().parent.parent.parent / "data" / "lexicons"),
    )
)

_BRANCH_TO_SUBDIR: Dict[str, str] = {
    "substance": "addiction/substance",
    "sex_addiction": "addiction/sex_addiction",
    "gambling": "addiction/gambling",
    "gaming": "addiction/gaming",
    "food_compulsion": "addiction/food_compulsion",
    "work_compulsion": "addiction/work_compulsion",
    "spending_compulsion": "addiction/spending_compulsion",
    "codependency": "addiction/codependency",
    "trafficking": "polyvictimization/trafficking",
    "did_systems": "did_systems",
}


@lru_cache(maxsize=128)
def _load_yaml_file(path: str) -> Dict[str, Any]:
    """Parse a single YAML file, cached by absolute path string."""
    try:
        import yaml
    except ImportError:
        logger.warning("lexicon_loader: PyYAML not installed; returning empty")
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {"entries": data}
    except Exception as e:
        logger.warning("lexicon_loader: failed to load %s: %s", path, e)
        return {}


def load_active_lexicons(
    branch_keys: List[str],
    *,
    categories: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Load and merge lexicon YAML files for the given active branches.

    Args:
        branch_keys: list of branch identifiers (e.g., ["substance", "gambling"])
        categories: if provided, only include YAML files whose stem matches
                    one of these category names. None = load all in the subdir.

    Returns:
        Merged dict with keys per-file (stem) mapping to their parsed contents.
    """
    merged: Dict[str, Any] = {}
    for key in branch_keys:
        subdir = _BRANCH_TO_SUBDIR.get(key)
        if not subdir:
            continue
        lexicon_dir = _LEXICON_ROOT / subdir
        if not lexicon_dir.is_dir():
            continue
        for yaml_file in sorted(lexicon_dir.glob("*.yaml")):
            stem = yaml_file.stem
            if categories and stem not in categories:
                continue
            data = _load_yaml_file(str(yaml_file))
            if not data:
                continue
            if (data.get("status") or "").strip() == "scaffolded_unreviewed":
                continue
            merged[f"{key}/{stem}"] = data
    return merged


def _did_pattern_matches(norm_msg: str, pattern: str) -> bool:
    """Match client text to a YAML `detector_patterns[].pattern` entry."""
    p = (pattern or "").strip()
    if not p:
        return False
    pl = p.lower()
    # Multi-token / punctuation phrases: substring (normalized lower).
    if " " in pl or "'" in pl or "-" in pl:
        return pl in norm_msg
    esc = re.escape(pl)
    if re.search(r"\b" + esc + r"\b", norm_msg):
        return True
    # Common plural: "alter" ↔ "alters" without listing both in YAML.
    if not pl.endswith("s"):
        return bool(re.search(r"\b" + esc + r"s\b", norm_msg))
    return False


def collect_did_lexicon_layer1_cues(
    client_message: Optional[str],
    *,
    max_items: int = 5,
) -> Tuple[List[str], List[str]]:
    """Layer 1 D.I.D. YAML cues only when `detector_patterns` match client text.

    Returns ``(cue_lines, matched_pattern_strings)``. Empty when lexicons are
    scaffolded, inactive, or ``client_message`` is blank / non-matching.
    """
    merged = load_active_lexicons(["did_systems"])
    norm = (client_message or "").strip().lower()
    out: List[str] = []
    matched_patterns: List[str] = []
    seen_pat: Set[str] = set()
    seen_line: Set[str] = set()

    def add(line: str) -> None:
        if line and line not in seen_line and len(out) < max_items:
            seen_line.add(line)
            out.append(line)

    if not merged or not norm:
        return [], []

    for path_key in sorted(merged.keys()):
        data = merged[path_key]
        scored: List[Tuple[float, str]] = []
        file_hit = False
        for dp in data.get("detector_patterns") or []:
            if not isinstance(dp, dict):
                continue
            pat = str(dp.get("pattern") or "").strip()
            if not pat or not _did_pattern_matches(norm, pat):
                continue
            file_hit = True
            if pat not in seen_pat:
                seen_pat.add(pat)
                matched_patterns.append(pat)
            weight = float(dp.get("weight") or 0.5)
            notes = str(dp.get("notes") or "").strip()
            cue = (
                f"D.I.D. lexicon ({pat}, w={weight:.2f}): {notes}"
                if notes
                else f"D.I.D. lexicon ({pat}, w={weight:.2f})"
            )
            scored.append((weight, cue))
        scored.sort(key=lambda x: -x[0])
        for _w, cue in scored:
            add(cue)
            if len(out) >= max_items:
                return out[:max_items], matched_patterns
        if file_hit:
            for rs in data.get("response_seeds") or []:
                if not isinstance(rs, dict):
                    continue
                ctx = str(rs.get("context") or "").strip()
                framing = str(rs.get("framing") or "").strip()
                if framing:
                    line = f"{ctx}: {framing}" if ctx else framing
                    add(line)
                if len(out) >= max_items:
                    return out[:max_items], matched_patterns
    return out[:max_items], matched_patterns


def load_did_systems_layer1_text_cues(
    *,
    client_message: Optional[str] = None,
    max_items: int = 5,
) -> List[str]:
    """Backward-compatible wrapper: cues only (pattern-gated)."""
    cues, _hits = collect_did_lexicon_layer1_cues(client_message, max_items=max_items)
    return cues


def invalidate_cache() -> None:
    """Clear the in-process YAML cache (useful after hot-reload of lexicon files)."""
    _load_yaml_file.cache_clear()
