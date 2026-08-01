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
