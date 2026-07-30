"""Offline CI fences for Multi-LoRA flywheel wiring (Phase W / G0–G2).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parents[2]
FROZEN = REPO / "frozen-config"


def test_migrations_305_310_exist_not_303_304_reuse():
    mig = REPO / "backend" / "migrations"
    for n in (305, 306, 307, 308, 309, 310):
        assert list(mig.glob(f"{n}_*.sql")), f"missing migration {n}"
    # 303/304 are occupied by non-flywheel seeds
    assert (mig / "303_ln7_humaneval_subset_seed.sql").is_file()
    assert (mig / "304_ln7_backfill_authored_license.sql").is_file()


def test_fence_manifest_green():
    from app.services.ln7_frozen_config import verify_manifest

    with patch("app.services.ln7_frozen_config.frozen_config_dir", return_value=FROZEN):
        ok, mismatches = verify_manifest(FROZEN)
    assert ok, mismatches


def test_feature_flags_default_off_without_db():
    from app.services.ln7_feature_flags import (
        auto_promote_enabled,
        dual_coo_mechanical_promote,
    )

    async def _run():
        assert await auto_promote_enabled(None) is False
        assert await dual_coo_mechanical_promote(None) is False

    asyncio.run(_run())


def test_g0_promote_still_enqueues_ceo():
    """G0/G1: dual_coo path must keep enqueue_ceo when mechanical flag off."""
    from app.services import dual_coo_checklist as dcc

    enq = MagicMock(return_value={"ok": True, "id": "ceo1"})

    async def _run():
        with patch(
            "app.services.ln7_feature_flags.dual_coo_mechanical_promote",
            new=AsyncMock(return_value=False),
        ):
            with patch.object(dcc, "_enqueue_ceo_promote", enq):
                out = await dcc.maybe_promote_via_checklist_or_ceo(
                    None,
                    revision_id="LN7-test",
                    evidence={"evidence_uri": "s3://x"},
                    title="promote test",
                )
        assert out.get("path") == "ceo_inbox"
        assert enq.called
        assert out.get("activated") is False
        assert out.get("enqueued") == {"ok": True, "id": "ceo1"}

    asyncio.run(_run())


def test_g2_mechanical_skips_enqueue_ceo():
    from app.services import dual_coo_checklist as dcc

    enq = MagicMock(return_value={"ok": True})
    activate = AsyncMock(return_value=True)

    async def _run():
        with patch(
            "app.services.ln7_feature_flags.dual_coo_mechanical_promote",
            new=AsyncMock(return_value=True),
        ):
            with patch.object(
                dcc,
                "dual_coo_checklist_review",
                new=AsyncMock(return_value={"agree": True}),
            ):
                with patch(
                    "app.services.ln7_revision.activate_revision", activate
                ):
                    with patch.object(dcc, "_enqueue_ceo_promote", enq):
                        out = await dcc.maybe_promote_via_checklist_or_ceo(
                            MagicMock(),
                            revision_id="LN7-x",
                            evidence={"evidence_uri": "uri"},
                            title="promote",
                        )
        assert not enq.called
        assert out.get("path") == "mechanical"
        assert activate.called

    asyncio.run(_run())


def test_claims_gate_refuses_missing():
    from app.services.growth_claims import assert_claims_publishable

    async def _run():
        pool = MagicMock()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        pool.acquire = MagicMock(return_value=cm)
        out = await assert_claims_publishable(pool, ["missing_claim"], channel="email")
        assert out["ok"] is False
        assert out.get("error") in ("claim_missing", "missing_claim_ids")

    asyncio.run(_run())


def test_shadow_promote_gate_requires_rows():
    from app.services.ln7_shadow_fork import g1_promote_allowed

    async def _run():
        with patch(
            "app.services.ln7_outcome_envelope.has_shadow_outcome_for_patch",
            new=AsyncMock(return_value=False),
        ):
            assert await g1_promote_allowed(MagicMock(), "deadbeef") is False
        with patch(
            "app.services.ln7_outcome_envelope.has_shadow_outcome_for_patch",
            new=AsyncMock(return_value=True),
        ):
            assert await g1_promote_allowed(MagicMock(), "deadbeef") is True

    asyncio.run(_run())


def test_heldout_hard_block_in_export_script():
    src = (REPO / "backend" / "scripts" / "ln7_export_train_jsonl.py").read_text(
        encoding="utf-8"
    )
    assert "heldout hard-block" in src or "heldout" in src
    assert "--domain" in src


def test_qlora_default_base_is_7b():
    src = (REPO / "backend" / "scripts" / "ln7_qlora_train.py").read_text(
        encoding="utf-8"
    )
    assert "Qwen/Qwen2.5-Coder-7B-Instruct" in src
    svc = (
        REPO / "backend" / "scripts" / "orange" / "ln7_peft_server.service"
    ).read_text(encoding="utf-8")
    assert "Qwen2.5-Coder-7B-Instruct" in svc
    assert "1.5B" not in svc


def test_influence_gini_yellow_on_concentration():
    from app.services.ln7_influence_audit import gini, influence_audit

    assert gini([1, 1, 1, 1]) < 0.1
    assert gini([100, 1, 1, 1]) > 0.5
    audit = influence_audit(
        [{"weight": 100, "provenance_score": 1}, {"weight": 1}, {"weight": 1}],
        yellow_gini=0.5,
    )
    assert audit["yellow_hold"] is True


def test_flywheel_task_kinds_registered():
    from app.websocket.cli_task_bus import FLYWHEEL_TASK_KINDS

    assert "hive_burst" in FLYWHEEL_TASK_KINDS
    assert "ln7_shadow_fork" in FLYWHEEL_TASK_KINDS


def test_governance_json_present():
    data = json.loads((FROZEN / "governance.json").read_text(encoding="utf-8"))
    assert "bakeoff_margin" in data
