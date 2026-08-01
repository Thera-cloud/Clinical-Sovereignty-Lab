"""Fence: Phase H held-out weld — ln7_heldout_packs.json floor must stay
non-empty and must remain a subset of packs_index.json's declared heldout
list (i.e. the app-data index has not silently dropped a frozen pack).

Lives under frozen-config (Queens SA must not write this tree).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent


def _frozen_heldout() -> set:
    data = json.loads((ROOT / "ln7_heldout_packs.json").read_text(encoding="utf-8"))
    return {str(n).strip() for n in (data.get("heldout") or []) if str(n).strip()}


def _index_heldout() -> set:
    idx = (
        REPO_ROOT
        / "backend"
        / "app"
        / "data"
        / "ln_sandbox_ci_packs"
        / "packs_index.json"
    )
    data = json.loads(idx.read_text(encoding="utf-8"))
    return {str(n).strip() for n in (data.get("heldout") or []) if str(n).strip()}


def test_frozen_heldout_pin_nonempty():
    assert len(_frozen_heldout()) >= 1


def test_frozen_heldout_pin_is_subset_of_index():
    """packs_index.json may add held-out packs; it must never silently drop
    one that the frozen pin requires. If this fails, someone edited
    packs_index.json to un-heldout a frozen pack without touching (and
    re-welding) frozen-config."""
    frozen = _frozen_heldout()
    index = _index_heldout()
    missing = frozen - index
    assert not missing, f"packs_index.json dropped frozen heldout packs: {sorted(missing)}"
