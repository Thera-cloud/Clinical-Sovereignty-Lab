"""Load addiction / polyvictimization lexicon YAML with caching. Phase B.

Exposes `load_active_lexicons(branch_keys, *, categories=None)` which
returns a merged dict of all matching lexicon entries. The loader caches
parsed YAML in-process (LRU) so that repeated calls within the same
request cycle do not re-read disk.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

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


def invalidate_cache() -> None:
    """Clear the in-process YAML cache (useful after hot-reload of lexicon files)."""
    _load_yaml_file.cache_clear()
