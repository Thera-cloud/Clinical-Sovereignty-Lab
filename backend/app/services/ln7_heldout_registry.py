"""LN7 held-out CI pack registry — single source of truth (Phase D / Phase H).

`backend/app/data/ln_sandbox_ci_packs/packs_index.json` is the canonical list
of packs that must never enter training data. Before this module existed,
`ln7_export_train_jsonl.py` and `ln7_train_queue.py` each hardcoded their own
copy of that set (`{"env_redis_prefix"}`), silently drifting from the index
whenever a new heldout pack (e.g. the `mut_*` adversarial packs) was added.
Both callers now import `heldout_packs()` from here so one edit to
packs_index.json is enough.

Phase H held-out weld: packs_index.json lives in the app data tree, which is
NOT protected by the frozen-config fence (manifest.sha256.json only pins
frozen-config/). A one-line edit removing a pack from packs_index.json's
"heldout" list would silently un-heldout it with no fence mismatch and no
promotion block. `frozen-config/ln7_heldout_packs.json` pins a floor set that
packs_index.json can only add to, never subtract from — heldout_packs()
returns the UNION of both files, and `heldout_weld_status()` reports whether
packs_index.json still honors the frozen floor (for observability / the
dual_coo_checklist `heldout_not_in_train` mechanical check).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, FrozenSet

# Historical fallback if packs_index.json is missing/unreadable — never widen
# training eligibility just because the index couldn't be loaded.
_FALLBACK: FrozenSet[str] = frozenset({"env_redis_prefix"})

_FROZEN_PIN_FILE = "ln7_heldout_packs.json"


def _packs_root() -> Path:
    here = Path(__file__).resolve()
    for cand in (
        here.parents[1] / "data" / "ln_sandbox_ci_packs",  # backend/app/data/...
        here.parents[2] / "app" / "data" / "ln_sandbox_ci_packs",  # /app/app/data/... (container)
    ):
        if cand.is_dir():
            return cand
    return here.parents[1] / "data" / "ln_sandbox_ci_packs"


def _read_index_heldout() -> FrozenSet[str]:
    idx = _packs_root() / "packs_index.json"
    try:
        data = json.loads(idx.read_text(encoding="utf-8"))
        names = data.get("heldout") or []
        return frozenset(str(n).strip() for n in names if str(n).strip())
    except Exception:
        return frozenset()


def _frozen_pinned_packs() -> FrozenSet[str]:
    """Phase H held-out weld floor. Missing/corrupt frozen file degrades to an
    empty floor (no crash, no widening) rather than blocking normal operation —
    the weld is defense-in-depth on top of packs_index.json, not a hard
    dependency for it."""
    try:
        from app.services.ln7_frozen_config import load_json

        data = load_json(_FROZEN_PIN_FILE, default={}) or {}
        names = data.get("heldout") or []
        return frozenset(str(n).strip() for n in names if str(n).strip())
    except Exception:
        return frozenset()


def heldout_packs() -> FrozenSet[str]:
    """Load the effective heldout pack set: packs_index.json ∪ the frozen pin
    floor (fresh read each call; both files are tiny)."""
    packs = _read_index_heldout() or _FALLBACK
    return packs | _frozen_pinned_packs()


def heldout_weld_status() -> Dict[str, Any]:
    """Phase H held-out weld observability: has packs_index.json silently
    dropped a pack that the frozen floor still requires held out?

    `ok=True` requires the frozen pin to exist AND be fully honored by
    packs_index.json. An empty/missing frozen pin is reported not-ok so the
    weld can't be silently disabled by deleting frozen-config/ln7_heldout_packs.json
    (that deletion also breaks fence_manifest_ok independently, per
    ln7_frozen_config.verify_manifest — this is the second, narrower signal).
    """
    frozen = _frozen_pinned_packs()
    index = _read_index_heldout()
    missing_from_index = sorted(frozen - index)
    return {
        "ok": bool(frozen) and not missing_from_index,
        "frozen_count": len(frozen),
        "index_count": len(index),
        "missing_from_index": missing_from_index,
    }
