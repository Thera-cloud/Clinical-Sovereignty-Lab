"""LN7 held-out CI pack registry — single source of truth (Phase D).

`backend/app/data/ln_sandbox_ci_packs/packs_index.json` is the canonical list
of packs that must never enter training data. Before this module existed,
`ln7_export_train_jsonl.py` and `ln7_train_queue.py` each hardcoded their own
copy of that set (`{"env_redis_prefix"}`), silently drifting from the index
whenever a new heldout pack (e.g. the `mut_*` adversarial packs) was added.
Both callers now import `heldout_packs()` from here so one edit to
packs_index.json is enough.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import FrozenSet

# Historical fallback if packs_index.json is missing/unreadable — never widen
# training eligibility just because the index couldn't be loaded.
_FALLBACK: FrozenSet[str] = frozenset({"env_redis_prefix"})


def _packs_root() -> Path:
    here = Path(__file__).resolve()
    for cand in (
        here.parents[1] / "data" / "ln_sandbox_ci_packs",  # backend/app/data/...
        here.parents[2] / "app" / "data" / "ln_sandbox_ci_packs",  # /app/app/data/... (container)
    ):
        if cand.is_dir():
            return cand
    return here.parents[1] / "data" / "ln_sandbox_ci_packs"


def heldout_packs() -> FrozenSet[str]:
    """Load the heldout pack set from packs_index.json (fresh read; index is tiny)."""
    idx = _packs_root() / "packs_index.json"
    try:
        data = json.loads(idx.read_text(encoding="utf-8"))
        names = data.get("heldout") or []
        packs = frozenset(str(n).strip() for n in names if str(n).strip())
        return packs or _FALLBACK
    except Exception:
        return _FALLBACK
