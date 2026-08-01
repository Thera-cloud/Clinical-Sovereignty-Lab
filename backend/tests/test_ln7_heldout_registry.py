"""Phase D — flywheel harden: single source of truth for held-out CI packs.

ln7_export_train_jsonl.py and ln7_train_queue.py each used to hardcode their
own copy of the heldout pack set, silently drifting from
packs_index.json whenever a new heldout pack was added. This test locks in
that both consumers now resolve to the exact same frozenset as the registry,
and that the registry itself tracks packs_index.json (not a stale snapshot).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import mock_open, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def test_heldout_packs_matches_packs_index_json():
    from app.services.ln7_heldout_registry import heldout_packs

    idx = (
        ROOT
        / "backend"
        / "app"
        / "data"
        / "ln_sandbox_ci_packs"
        / "packs_index.json"
    )
    data = json.loads(idx.read_text(encoding="utf-8"))
    expected = frozenset(str(n).strip() for n in (data.get("heldout") or []))

    assert expected, "packs_index.json must declare at least one heldout pack"
    assert heldout_packs() == expected


def test_heldout_packs_includes_env_redis_prefix():
    """env_redis_prefix is the original, longest-standing heldout pack — a
    regression here silently widens training eligibility to a pack that was
    deliberately reserved for evaluation."""
    from app.services.ln7_heldout_registry import heldout_packs

    assert "env_redis_prefix" in heldout_packs()


def test_heldout_packs_falls_back_when_index_missing():
    from app.services import ln7_heldout_registry as reg

    with patch.object(Path, "read_text", side_effect=FileNotFoundError("nope")):
        result = reg.heldout_packs()
    assert result == reg._FALLBACK
    assert "env_redis_prefix" in result


def test_heldout_packs_falls_back_on_corrupt_json():
    from app.services import ln7_heldout_registry as reg

    with patch.object(Path, "read_text", return_value="{not valid json"):
        result = reg.heldout_packs()
    assert result == reg._FALLBACK


def test_heldout_packs_falls_back_on_empty_list():
    """An index with an empty 'heldout' key must never silently mean
    'nothing is held out' — that would let the CI pack that trains-on-eval
    slip straight into the QLoRA export."""
    from app.services import ln7_heldout_registry as reg

    with patch.object(Path, "read_text", return_value=json.dumps({"heldout": []})):
        result = reg.heldout_packs()
    assert result == reg._FALLBACK


def test_export_train_jsonl_and_train_queue_share_identical_heldout_set():
    """Both consumers must resolve to the exact same set — no local drift."""
    sys.path.insert(0, str(ROOT / "backend" / "scripts"))
    from ln7_export_train_jsonl import HELDOUT_PACKS as export_set
    from app.services.ln7_train_queue import HELDOUT_PACKS as queue_set

    assert export_set == queue_set
    assert isinstance(export_set, frozenset)


# --- Phase H held-out weld: frozen-config floor -----------------------------


def test_heldout_packs_is_superset_of_frozen_pin():
    """The live effective set must never be narrower than the frozen floor,
    even if packs_index.json is edited."""
    from app.services.ln7_heldout_registry import _frozen_pinned_packs, heldout_packs

    frozen = _frozen_pinned_packs()
    assert frozen, "frozen-config/ln7_heldout_packs.json must declare a floor"
    assert frozen <= heldout_packs()


def test_heldout_weld_status_ok_when_index_honors_frozen_pin():
    from app.services.ln7_heldout_registry import heldout_weld_status

    status = heldout_weld_status()
    assert status["ok"] is True
    assert status["missing_from_index"] == []
    assert status["frozen_count"] >= 1


def test_heldout_weld_status_flags_silent_narrowing():
    """If packs_index.json drops a pack the frozen pin still requires held
    out, the weld status must go not-ok — this is the exact drift the fence
    is designed to catch. Patches the index-reader only (not the frozen
    pin reader) so the two files stay independently controllable."""
    from app.services import ln7_heldout_registry as reg

    with patch.object(
        reg, "_read_index_heldout", return_value=frozenset({"env_redis_prefix"})
    ):
        status = reg.heldout_weld_status()
    assert status["ok"] is False
    assert "mut_off_by_one_range" in status["missing_from_index"]


def test_heldout_weld_status_not_ok_when_frozen_pin_missing():
    """An empty/missing frozen pin must never read as 'weld satisfied' —
    that would let deleting the frozen file silently disable the check."""
    from app.services import ln7_heldout_registry as reg

    with patch.object(reg, "_frozen_pinned_packs", return_value=frozenset()):
        status = reg.heldout_weld_status()
    assert status["ok"] is False
    assert status["frozen_count"] == 0
