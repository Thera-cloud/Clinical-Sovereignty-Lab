"""Phase H held-out weld — mechanical `heldout_not_in_train` check in the
Dual-COO checklist (dual_coo_checklist.evaluate_evidence).

Before this, `heldout_not_in_train` was a required checklist item with no
built-in check: `ok = bool(evidence.get(iid) or ...)` defaulted False unless
a caller explicitly self-reported True/False in the evidence payload —
i.e. nothing actually verified the held-out set's integrity. This locks in
the mechanical fallback that consults
`app.services.ln7_heldout_registry.heldout_weld_status()`.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def _run(coro):
    # NOTE: intentionally NOT asyncio.run() — on Py3.9 that calls
    # events.set_event_loop(None) on exit, which breaks every later test
    # file in the same session that relies on the legacy
    # asyncio.get_event_loop().run_until_complete(...) pattern (e.g.
    # test_family_system_field.py, test_growth_ops_closure.py). Reuse the
    # thread's existing event loop instead, matching the rest of this suite.
    return asyncio.get_event_loop().run_until_complete(coro)


def _checklist_ids(result):
    return {item["id"]: item["ok"] for item in result["items"]}


def test_heldout_not_in_train_uses_mechanical_weld_when_evidence_silent():
    from app.services import dual_coo_checklist as dcc

    async def _go():
        with patch(
            "app.services.ln7_heldout_registry.heldout_weld_status",
            return_value={"ok": True, "missing_from_index": []},
        ):
            out = await dcc.evaluate_evidence({"evidence_uri": "s3://x"})
        return out

    out = _run(_go())
    assert _checklist_ids(out)["heldout_not_in_train"] is True


def test_heldout_not_in_train_fails_closed_on_weld_drift():
    from app.services import dual_coo_checklist as dcc

    async def _go():
        with patch(
            "app.services.ln7_heldout_registry.heldout_weld_status",
            return_value={
                "ok": False,
                "missing_from_index": ["mut_off_by_one_range"],
            },
        ):
            out = await dcc.evaluate_evidence({"evidence_uri": "s3://x"})
        return out

    out = _run(_go())
    result = _checklist_ids(out)
    assert result["heldout_not_in_train"] is False
    assert out["agree"] is False  # required item failing blocks the whole checklist


def test_heldout_not_in_train_fails_closed_on_import_error():
    """If the registry itself can't be imported/evaluated, the checklist must
    fail closed (False), never silently pass."""
    from app.services import dual_coo_checklist as dcc

    async def _go():
        with patch(
            "app.services.ln7_heldout_registry.heldout_weld_status",
            side_effect=RuntimeError("boom"),
        ):
            out = await dcc.evaluate_evidence({"evidence_uri": "s3://x"})
        return out

    out = _run(_go())
    assert _checklist_ids(out)["heldout_not_in_train"] is False


def test_heldout_not_in_train_respects_explicit_evidence_override():
    """Callers may still self-report via evidence[iid] or evidence['checks'],
    bypassing the mechanical check entirely (existing pattern for all
    checklist items) — this test locks that escape hatch stays intact."""
    from app.services import dual_coo_checklist as dcc

    async def _go():
        with patch(
            "app.services.ln7_heldout_registry.heldout_weld_status",
            return_value={"ok": False, "missing_from_index": ["x"]},
        ) as mocked:
            out = await dcc.evaluate_evidence(
                {"evidence_uri": "s3://x", "heldout_not_in_train": True}
            )
        return out, mocked

    out, mocked = _run(_go())
    assert _checklist_ids(out)["heldout_not_in_train"] is True
    assert not mocked.called
