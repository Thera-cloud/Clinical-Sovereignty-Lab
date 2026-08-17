"""Independent second reviewer for dual_coo_checklist_review()
(TRUST_LEDGER.md Entry 24/27).

Before this: mac and cloud both called evaluate_evidence() on the identical
payload -- the same deterministic function, same input, guaranteed same
output. Disagreement was structurally impossible, so "Dual-COO agreement"
carried zero information -- every historical "both Queens approved" was one
function agreeing with itself.

evaluate_evidence_independent() fixes this by NEVER honoring evaluate_
evidence()'s deliberate self-report escape hatch: every mechanically-
checkable item is re-derived from source every time, regardless of what the
proposer claims. This file proves disagreement is now structurally
possible, not just theoretically different code paths that happen to
always agree in practice.
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
SERVICES = APP / "services"


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _ensure_pkg(name: str, path: Path) -> None:
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(path)]  # type: ignore[attr-defined]
        sys.modules[name] = pkg


def _load(name: str, path: Path):
    _ensure_pkg("app", APP)
    _ensure_pkg("app.services", SERVICES)
    if name in sys.modules and getattr(sys.modules[name], "__file__", None) == str(path):
        return sys.modules[name]
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _checklist():
    return _load("app.services.dual_coo_checklist", SERVICES / "dual_coo_checklist.py")


def _ids(result):
    return {item["id"]: item["ok"] for item in result["items"]}


# ── evaluate_evidence_independent() ─────────────────────────────────────


def test_independent_reviewer_ignores_false_self_report_for_fence():
    """The exact scenario that matters: a proposer self-reports
    fence_manifest_ok=True in the evidence dict while the REAL fence is
    broken. evaluate_evidence() (mac) trusts the claim; the independent
    reviewer (cloud) must not."""
    dcc = _checklist()

    async def _go():
        with patch(
            "app.services.ln7_frozen_config.promotions_allowed",
            return_value=False,
        ):
            mac = await dcc.evaluate_evidence({"fence_manifest_ok": True})
            cloud = await dcc.evaluate_evidence_independent({"fence_manifest_ok": True})
        return mac, cloud

    mac, cloud = _run_async(_go())
    assert _ids(mac)["fence_manifest_ok"] is True  # trusted the claim
    assert _ids(cloud)["fence_manifest_ok"] is False  # independently verified false


def test_independent_reviewer_ignores_false_self_report_for_heldout():
    dcc = _checklist()

    async def _go():
        with patch(
            "app.services.ln7_heldout_registry.heldout_weld_status",
            return_value={"ok": False, "missing_from_index": ["x"]},
        ):
            mac = await dcc.evaluate_evidence({"heldout_not_in_train": True})
            cloud = await dcc.evaluate_evidence_independent(
                {"heldout_not_in_train": True}
            )
        return mac, cloud

    mac, cloud = _run_async(_go())
    assert _ids(mac)["heldout_not_in_train"] is True
    assert _ids(cloud)["heldout_not_in_train"] is False


def test_independent_reviewer_fails_closed_on_unverifiable_custom_item_without_artifact():
    dcc = _checklist()

    async def _go():
        return await dcc.evaluate_evidence_independent(
            {"beats_incumbent_on_heldout": True}  # bare bool claim, no artifact
        )

    out = _run_async(_go())
    assert _ids(out)["beats_incumbent_on_heldout"] is False
    assert out["agree"] is False  # required item failing blocks the whole checklist


def test_independent_reviewer_accepts_custom_item_with_corroborating_artifact():
    dcc = _checklist()

    async def _go():
        return await dcc.evaluate_evidence_independent(
            {"beats_incumbent_on_heldout_evidence_uri": "s3://bakeoff/run-42"}
        )

    out = _run_async(_go())
    assert _ids(out)["beats_incumbent_on_heldout"] is True


def test_independent_reviewer_shadow_outcome_not_applicable_without_patch_hash():
    dcc = _checklist()

    async def _go():
        return await dcc.evaluate_evidence_independent({})

    out = _run_async(_go())
    assert _ids(out)["shadow_outcome_present_if_g1"] is True  # not_if_g1 -> vacuously ok


def test_independent_reviewer_shadow_outcome_checks_real_function_when_patch_hash_present():
    dcc = _checklist()

    async def _go():
        with patch(
            "app.services.ln7_shadow_fork.g1_promote_allowed",
            AsyncMock(return_value=False),
        ):
            return await dcc.evaluate_evidence_independent(
                {"patch_hash": "abc123", "shadow_outcome_present_if_g1": True},
                db_pool=object(),
            )

    out = _run_async(_go())
    assert _ids(out)["shadow_outcome_present_if_g1"] is False  # ignored the self-report


def test_independent_reviewer_influence_gini_uses_real_audit():
    dcc = _checklist()

    async def _go():
        return await dcc.evaluate_evidence_independent(
            {
                "influence_gini_ok": True,  # self-report says fine
                # 5 nearly-empty sources + 1 dominant one -> gini well above
                # the 0.72 yellow threshold (verified against gini() directly:
                # sorted [1,1,1,1,1,100], n=6 -> ~0.786).
                "sources": [{"weight": 1, "provenance_score": 1.0}] * 5
                + [{"weight": 100, "provenance_score": 1.0}],
            }
        )

    out = _run_async(_go())
    # Highly concentrated sources -> yellow_hold True -> ok should be False,
    # regardless of the self-reported True.
    assert _ids(out)["influence_gini_ok"] is False


# ── domain-scoped clinical/defense exclusion (TRUST_LEDGER Entry 24/27's
# 3rd named prerequisite) ──────────────────────────────────────────────


def test_independent_reviewer_blocks_clinical_domain_even_when_everything_else_passes():
    dcc = _checklist()

    async def _go():
        with patch(
            "app.services.ln7_frozen_config.promotions_allowed", return_value=True
        ), patch(
            "app.services.ln7_heldout_registry.heldout_weld_status",
            return_value={"ok": True, "missing_from_index": []},
        ):
            return await dcc.evaluate_evidence_independent(
                {
                    "domain_tag": "clinical",
                    "fence_manifest_ok": True,
                    "heldout_not_in_train": True,
                    "base_checkpoint_pinned": True,
                    "base_checkpoint": "Qwen2.5-Coder-7B",
                    "beats_incumbent_on_heldout_evidence_uri": "s3://x",
                    "license_train_eligible_evidence_uri": "s3://y",
                }
            )

    out = _run_async(_go())
    assert _ids(out)["domain_not_excluded"] is False
    assert out["agree"] is False  # required item failing blocks everything


def test_independent_reviewer_blocks_defense_domain():
    dcc = _checklist()

    async def _go():
        return await dcc.evaluate_evidence_independent({"domain_tag": "defense"})

    out = _run_async(_go())
    assert _ids(out)["domain_not_excluded"] is False


def test_independent_reviewer_allows_non_excluded_domain():
    """Proves this is a targeted block, not a default-deny-everything --
    ordinary flywheel domains must keep flowing through G2 normally."""
    dcc = _checklist()

    async def _go():
        with patch(
            "app.services.ln7_frozen_config.promotions_allowed", return_value=True
        ), patch(
            "app.services.ln7_heldout_registry.heldout_weld_status",
            return_value={"ok": True, "missing_from_index": []},
        ):
            return await dcc.evaluate_evidence_independent(
                {
                    "domain_tag": "python",
                    "fence_manifest_ok": True,
                    "heldout_not_in_train": True,
                    "base_checkpoint_pinned": True,
                    "base_checkpoint": "Qwen2.5-Coder-7B",
                    "beats_incumbent_on_heldout_evidence_uri": "s3://x",
                    "license_train_eligible_evidence_uri": "s3://y",
                }
            )

    out = _run_async(_go())
    assert _ids(out)["domain_not_excluded"] is True
    assert out["agree"] is True


def test_independent_reviewer_missing_domain_tag_is_not_excluded():
    dcc = _checklist()

    async def _go():
        return await dcc.evaluate_evidence_independent({})

    out = _run_async(_go())
    assert _ids(out)["domain_not_excluded"] is True


def test_domain_exclusion_check_bypasses_no_bare_bool_escape_hatch():
    """Even a proposer claiming domain_tag_evidence_uri or a bare
    domain_not_excluded=True must not clear this gate -- it is computed
    directly from domain_tag, never from a self-reported override."""
    dcc = _checklist()

    async def _go():
        return await dcc.evaluate_evidence_independent(
            {
                "domain_tag": "clinical",
                "domain_not_excluded": True,  # attempted self-report override
                "domain_not_excluded_evidence_uri": "s3://fake",
            }
        )

    out = _run_async(_go())
    assert _ids(out)["domain_not_excluded"] is False


def test_dual_coo_review_red_holds_on_clinical_domain_even_when_mac_agrees():
    """End-to-end proof: dual_coo_checklist_review() RED-holds a clinical-
    domain candidate even when evaluate_evidence() (mac) trusts every
    self-reported claim -- cloud's domain gate alone is sufficient."""
    dcc = _checklist()

    async def _go():
        with patch(
            "app.services.ln7_frozen_config.promotions_allowed", return_value=True
        ), patch(
            "app.services.ln7_heldout_registry.heldout_weld_status",
            return_value={"ok": True, "missing_from_index": []},
        ), patch(
            "app.services.flywheel_anomaly.notify_flywheel_anomaly", AsyncMock()
        ):
            return await dcc.dual_coo_checklist_review(
                "s3://evidence/clinical-candidate",
                db_pool=None,
                evidence={
                    "domain_tag": "clinical",
                    "fence_manifest_ok": True,
                    "heldout_not_in_train": True,
                    "base_checkpoint_pinned": True,
                    "base_checkpoint": "Qwen2.5-Coder-7B",
                    "not_suppressed": True,
                    "beats_incumbent_on_heldout": True,
                    "beats_incumbent_on_heldout_evidence_uri": "s3://x",
                    "license_train_eligible": True,
                    "license_train_eligible_evidence_uri": "s3://y",
                },
            )

    result = _run_async(_go())
    assert result["mac"]["agree"] is True  # trusted every self-reported claim
    assert result["cloud"]["agree"] is False  # domain gate alone blocks it
    assert result["agree"] is False
    assert result["action"] == "red_hold"


def test_independent_reviewer_reports_verified_independently_flag():
    dcc = _checklist()

    async def _go():
        with patch(
            "app.services.ln7_frozen_config.promotions_allowed", return_value=True
        ):
            return await dcc.evaluate_evidence_independent({})

    out = _run_async(_go())
    by_id = {i["id"]: i for i in out["items"]}
    assert by_id["fence_manifest_ok"]["verified_independently"] is True
    assert by_id["beats_incumbent_on_heldout"]["verified_independently"] is False


def test_independent_reviewer_result_tagged_with_reviewer_name():
    dcc = _checklist()

    async def _go():
        return await dcc.evaluate_evidence_independent({})

    out = _run_async(_go())
    assert out.get("reviewer") == "independent"


# ── dual_coo_checklist_review() — disagreement now structurally possible ──


def test_dual_coo_review_disagrees_when_proposer_lies_about_fence():
    """The headline test: a false self-report that evaluate_evidence()
    alone would rubber-stamp now produces a real disagreement and RED
    hold, because cloud independently re-derives the fact."""
    dcc = _checklist()

    async def _go():
        with patch(
            "app.services.ln7_frozen_config.promotions_allowed",
            return_value=False,
        ), patch(
            "app.services.ln7_heldout_registry.heldout_weld_status",
            return_value={"ok": True, "missing_from_index": []},
        ), patch(
            "app.services.flywheel_anomaly.notify_flywheel_anomaly", AsyncMock()
        ):
            return await dcc.dual_coo_checklist_review(
                "s3://evidence/lie",
                db_pool=None,
                evidence={
                    "fence_manifest_ok": True,  # false claim
                    "heldout_not_in_train": True,
                    "base_checkpoint_pinned": True,
                    "base_checkpoint": "Qwen2.5-Coder-7B",
                    "not_suppressed": True,
                    "beats_incumbent_on_heldout": True,
                    "beats_incumbent_on_heldout_evidence_uri": "s3://x",
                    "license_train_eligible": True,
                    "license_train_eligible_evidence_uri": "s3://y",
                },
            )

    result = _run_async(_go())
    assert result["mac"]["agree"] is True  # trusted every self-reported claim
    assert result["cloud"]["agree"] is False  # independently caught the false fence claim
    assert result["agree"] is False
    assert result["action"] == "red_hold"


def test_dual_coo_review_agrees_when_proposer_tells_the_truth():
    """Positive control: when the self-report actually matches ground
    truth, both reviewers agree -- proving this isn't just "cloud always
    fails," it's a genuine independent check that can also confirm."""
    dcc = _checklist()

    async def _go():
        with patch(
            "app.services.ln7_frozen_config.promotions_allowed",
            return_value=True,
        ), patch(
            "app.services.ln7_heldout_registry.heldout_weld_status",
            return_value={"ok": True, "missing_from_index": []},
        ):
            return await dcc.dual_coo_checklist_review(
                "s3://evidence/truth",
                db_pool=None,
                evidence={
                    "fence_manifest_ok": True,
                    "heldout_not_in_train": True,
                    "base_checkpoint_pinned": True,
                    "base_checkpoint": "Qwen2.5-Coder-7B",
                    "not_suppressed": True,
                    "beats_incumbent_on_heldout": True,
                    "beats_incumbent_on_heldout_evidence_uri": "s3://x",
                    "license_train_eligible": True,
                    "license_train_eligible_evidence_uri": "s3://y",
                },
            )

    result = _run_async(_go())
    assert result["mac"]["agree"] is True
    assert result["cloud"]["agree"] is True
    assert result["agree"] is True
    assert result["action"] == "promote"


def test_dual_coo_review_mac_and_cloud_are_different_functions_not_same_call_twice():
    """Structural guard against silently reverting to the Entry 24 bug:
    dual_coo_checklist_review must call two DIFFERENT functions."""
    dcc = _checklist()
    import inspect

    src = inspect.getsource(dcc.dual_coo_checklist_review)
    assert "mac = await evaluate_evidence(" in src
    assert "cloud = await evaluate_evidence_independent(" in src
    assert "cloud = await evaluate_evidence(" not in src
