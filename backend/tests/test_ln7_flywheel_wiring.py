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


def test_g1_gate_sql_requires_ci_pack_oracle():
    """Empty/probe oracle must not unlock promote (SQL filter in envelope)."""
    src = (
        REPO / "backend" / "app" / "services" / "ln7_outcome_envelope.py"
    ).read_text(encoding="utf-8")
    assert "'ci_pack'" in src or '"ci_pack"' in src
    assert "ci_pack_cycle" in src


def test_apply_unified_diff_creates_new_file(tmp_path):
    from app.services.ln_sandbox_engineering_ci import apply_unified_diff

    diff = (
        "--- /dev/null\n"
        "+++ b/__ln7_shadow_probe__.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+# probe\n"
        "+pass\n"
    )
    ok, msg = apply_unified_diff(tmp_path, diff)
    assert ok, msg
    assert (tmp_path / "__ln7_shadow_probe__.py").is_file()
    assert "pass" in (tmp_path / "__ln7_shadow_probe__.py").read_text()


def test_g1_shadow_oracle_applies_golden_pack():
    """Real pack golden.patch → pytest oracle (not empty_diff)."""
    from app.services.ln7_shadow_fork import run_shadow_fork
    from app.services.ln_sandbox_engineering_ci import (
        list_pack_names,
        materialize_pack,
    )

    names = list_pack_names()
    assert names, "sandbox packs missing"
    pack = "micro_ab_ok_on_fail" if "micro_ab_ok_on_fail" in names else names[0]
    workdir, _meta, err = materialize_pack(pack)
    assert workdir is not None, err
    golden = (workdir / "golden.patch").read_text(encoding="utf-8")
    assert "@@" in golden

    writes: list = []

    async def _write(*_a, **kwargs):
        writes.append(kwargs.get("shadow_outcome") or {})
        return "env-test"

    async def _run():
        with patch(
            "app.services.ln7_outcome_envelope.has_shadow_outcome_for_patch",
            new=AsyncMock(return_value=False),
        ):
            with patch(
                "app.services.ln7_outcome_envelope.write_envelope",
                new=_write,
            ):
                out = await run_shadow_fork(
                    MagicMock(),
                    patch_hash="g1testoraclehash01",
                    domain="coding",
                    counterfactual_diff=golden,
                    pack_ids=[pack],
                    force=True,
                )
        assert out.get("ok") is True
        so = out.get("shadow_outcome") or (writes[0] if writes else {})
        assert so.get("oracle") in ("ci_pack", "ci_pack_cycle")
        assert "passed" in so

    asyncio.run(_run())


def test_resolve_counterfactual_uses_golden_when_empty():
    from app.services.ln7_flywheel_pipeline import resolve_counterfactual

    async def _run():
        diff, packs = await resolve_counterfactual(
            None,
            {"revision_id": "LN7-none", "harness_config_json": {}},
            pack_ids=["micro_ab_ok_on_fail"],
        )
        assert "@@" in diff
        assert packs and packs[0] == "micro_ab_ok_on_fail"

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
    assert "sandbox_pack_sync" in FLYWHEEL_TASK_KINDS


def test_governance_json_present():
    data = json.loads((FROZEN / "governance.json").read_text(encoding="utf-8"))
    assert "bakeoff_margin" in data


def test_emit_queens_task_merged_calls_shadow():
    from app.services import ln7_flywheel_pipeline as pipe

    shadow = AsyncMock(return_value={"ok": True, "path": "inline"})

    async def _run():
        with patch.object(pipe, "_revision_row", new=AsyncMock(return_value=None)):
            with patch(
                "app.services.ln7_shadow_fork.on_queens_task_merged", shadow
            ):
                out = await pipe.emit_queens_task_merged(
                    None,
                    patch_hash="abc123deadbeef",
                    domain="coding",
                    counterfactual_diff="--- a/x\n+++ b/x\n",
                    run_inline=True,
                )
        assert out.get("ok") is True
        assert shadow.called

    asyncio.run(_run())


def test_promote_path_g0_does_not_activate():
    from app.services import ln7_flywheel_pipeline as pipe

    async def _run():
        with patch.object(
            pipe,
            "ensure_shadow_for_revision",
            new=AsyncMock(return_value={"ok": True, "patch_hash": "ph"}),
        ):
            with patch.object(
                pipe,
                "_revision_row",
                new=AsyncMock(return_value={"revision_id": "LN7-t", "harness_config_json": {}}),
            ):
                with patch(
                    "app.services.ln7_feature_flags.dual_coo_mechanical_promote",
                    new=AsyncMock(return_value=False),
                ):
                    with patch(
                        "app.services.ln7_revision.notify_revision_candidate",
                        new=AsyncMock(return_value={"ok": True}),
                    ):
                        with patch(
                            "app.services.dual_coo_checklist.maybe_promote_via_checklist_or_ceo",
                            new=AsyncMock(return_value={"path": "ceo_inbox", "activated": False}),
                        ):
                            out = await pipe.promote_path_after_gate(
                                MagicMock(), "LN7-t", title="t"
                            )
        assert out.get("governance") == "G0"
        assert out.get("activated") is False

    asyncio.run(_run())


def test_living_pack_materialize_writes_files(tmp_path, monkeypatch):
    from app.services import ln7_living_packs as lp

    monkeypatch.setenv("LN7_SANDBOX_PACKS_DIR", str(tmp_path))
    out = lp.materialize_living_pack(
        "living_testhash12",
        patch_hash="testhash12abcd",
        domain="coding",
        split="train",
    )
    assert out["ok"] is True
    root = tmp_path / "living_testhash12"
    assert (root / "task.json").is_file()
    assert (root / "broken" / "fix.py").is_file()
    assert (root / "golden.patch").is_file()
    hook = lp.sandbox_deploy_hook("living_testhash12")
    assert hook["ok"] is True
    assert (tmp_path / ".deploy_queue" / "living_testhash12.ready").is_file()


def test_hive_vllm_serve_script_exists():
    script = REPO / "scripts" / "ln7_hive_vllm_serve.sh"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "LN7_SERVE_URL=" in text


def test_phase_h_predicates_require_adversarial_file():
    """Tightened: goodhart_reference alone must not open Phase H."""
    from app.services.phase_h_predicate_poller import evaluate_predicates

    async def _run():
        pool = MagicMock()
        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=0)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        pool.acquire = MagicMock(return_value=cm)
        with patch(
            "app.services.ln7_frozen_config.frozen_config_dir",
            return_value=FROZEN,
        ):
            with patch(
                "app.services.ln7_frozen_config.verify_manifest",
                return_value=(True, []),
            ):
                ev = await evaluate_predicates(pool)
        by_id = {p["id"]: p["ok"] for p in ev["predicates"]}
        # Without adversarial_heldout.json, predicate must fail
        if not (FROZEN / "adversarial_heldout.json").is_file():
            assert by_id["adversarial_heldout"] is False
            assert ev["open"] is False

    asyncio.run(_run())


def test_fallback_drill_module_importable():
    from app.services.ln7_fallback_drill import FallbackDrillAgent, run_fallback_drill

    assert callable(run_fallback_drill)
    assert FallbackDrillAgent is not None
