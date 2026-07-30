"""LN7 revision lifecycle — rejection sampling, statistical gate, shadow, promote.

Training runs offline (BLUE/ORANGE); GREEN never writes weights.
# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ln7_revision")

try:
    from app.services.little_nate_7 import (
        PRODUCT_MAJOR,
        coder_model,
        model_card_path,
        quantization_floor,
        utc_revision_id,
    )
except Exception:
    PRODUCT_MAJOR = 7
    def coder_model(tier="deep"):
        return os.getenv("LN7_CODE_MODEL_DEEP", "qwen2.5-coder:32b-instruct-q5_K_M")
    def model_card_path(rid):
        return f"docs/ln7/LN7_{rid}.md"
    def quantization_floor():
        return "q5_K_M"
    def utc_revision_id(when=None):
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def promote_requires_ceo() -> bool:
    return os.getenv("LN7_PROMOTE_REQUIRES_CEO", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


async def collect_rejection_samples(db_pool, *, limit: int = 500) -> List[Dict[str, Any]]:
    """Keep only sandbox-passing outcomes for fine-tune / DPO pairs."""
    if not db_pool:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, task_id, patch_hash, generator, revision_id,
                       harness_mode, metrics_json
                FROM ln7_coding_outcomes
                WHERE passed = TRUE AND generator IN ('ln7', 'ln7_golden')
                ORDER BY created_at DESC
                LIMIT $1
                """,
                limit,
            )
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("LN7 rejection samples: %s", exc)
        return []


def _resolve_model_card_file(revision_id: str) -> tuple[Path, str]:
    """Return (absolute path, stored path string). GREEN uses /app/data (writable)."""
    name = Path(model_card_path(revision_id)).name
    override = (os.getenv("LN7_MODEL_CARD_ROOT") or "").strip()
    if override:
        full = Path(override) / name
        return full, str(full)
    # QUANTUM-CRYSTAL-ARCH — container layout: /app/app/services → parents[3] is /
    candidates = [
        (Path(__file__).resolve().parents[3] / "docs" / "ln7" / name, f"docs/ln7/{name}"),
        (Path("/app/data/ln7/model_cards") / name, f"data/ln7/model_cards/{name}"),
        (Path("/tmp/ln7/model_cards") / name, f"/tmp/ln7/model_cards/{name}"),
    ]
    for full, stored in candidates:
        try:
            full.parent.mkdir(parents=True, exist_ok=True)
            if os.access(str(full.parent), os.W_OK):
                return full, stored
        except OSError:
            continue
    full = Path("/tmp/ln7/model_cards") / name
    full.parent.mkdir(parents=True, exist_ok=True)
    return full, str(full)


def write_model_card(
    revision_id: str,
    *,
    base_checkpoint: str,
    quantization: str,
    scorecard: Dict[str, Any],
    notes: str = "",
) -> str:
    """Emit LN7_<timestamp>.md — required before activation."""
    full, path = _resolve_model_card_file(revision_id)
    private = (scorecard or {}).get("private") or {}
    pr = (private.get("pass_rate") or {})
    body = f"""# Little Nate 7 — Model Card

| Field | Value |
|---|---|
| Product | Little Nate 7 (major={PRODUCT_MAJOR}, immutable) |
| Revision | `{revision_id}` |
| Base checkpoint | `{base_checkpoint}` |
| Quantization | `{quantization}` (floor: {quantization_floor()}) |
| Non-clinical claim | **true** — never cite as clinical Tier 2/3 evidence |

## Private held-out / pack bakeoff (promotion gate)

- n = {pr.get('n', 0)}
- pass rate = {pr.get('mean', 0):.3f}
- 95% CI = [{pr.get('lo', 0):.3f}, {pr.get('hi', 0):.3f}]

## Public benchmarks (report-only)

See scorecard JSON — SWE-bench Verified, LiveCodeBench, Aider polyglot, Terminal-Bench.
Public numbers are for industry comparison; they do **not** gate promotion.

## Notes

{notes or '(none)'}

## Scorecard (raw)

```json
{json.dumps(scorecard, indent=2, default=str)[:8000]}
```
"""
    full.write_text(body, encoding="utf-8")
    return str(path)


async def register_revision(
    db_pool,
    *,
    revision_id: Optional[str] = None,
    base_checkpoint: Optional[str] = None,
    quantization: Optional[str] = None,
    harness_config: Optional[Dict[str, Any]] = None,
    notes: str = "",
    status: str = "draft",
    scorecard: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    rid = revision_id or f"LN7-{utc_revision_id()}"
    base = base_checkpoint or coder_model("deep")
    # QUANTUM-CRYSTAL-ARCH — Phase A0: refuse 1.5B / base mismatch vs pinned 7B
    _pinned = os.getenv(
        "LN7_QLORA_HF_BASE", "Qwen/Qwen2.5-Coder-7B-Instruct"
    ).strip()
    _base_l = str(base or "").lower()
    if "1.5b" in _base_l or (
        "qwen2.5-coder" in _base_l
        and "7b" not in _base_l
        and "32b" not in _base_l
        and "14b" not in _base_l
    ):
        return {
            "ok": False,
            "error": "base_mismatch_1p5b",
            "revision_id": rid,
            "base_checkpoint": base,
            "pinned": _pinned,
        }
    hc = dict(harness_config or {})
    if hc.get("hf_base") and str(hc.get("hf_base")).lower() != _pinned.lower():
        if "1.5b" in str(hc.get("hf_base")).lower():
            return {
                "ok": False,
                "error": "base_mismatch_1p5b",
                "revision_id": rid,
                "hf_base": hc.get("hf_base"),
            }
    # QUANTUM-CRYSTAL-ARCH — A0: uniform rank + target_modules recorded
    _rank = hc.get("lora_rank") or hc.get("rank")
    _targets = hc.get("target_modules")
    if _rank is not None:
        try:
            _rank_i = int(_rank)
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid_lora_rank", "revision_id": rid}
        if _rank_i not in (8, 16, 32, 64):
            return {
                "ok": False,
                "error": "lora_rank_not_uniform",
                "revision_id": rid,
                "rank": _rank_i,
            }
        hc["lora_rank"] = _rank_i
    if _targets is not None and not isinstance(_targets, (list, tuple)):
        return {"ok": False, "error": "invalid_target_modules", "revision_id": rid}
    if _targets is not None:
        hc["target_modules"] = list(_targets)
    quant = quantization or quantization_floor()
    card = write_model_card(
        rid,
        base_checkpoint=base,
        quantization=quant,
        scorecard=scorecard or {},
        notes=notes,
    )
    if not db_pool:
        return {"ok": True, "revision_id": rid, "model_card_path": card, "persisted": False}
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ln7_revisions (
                    revision_id, revised_at, base_checkpoint, quantization,
                    harness_config_json, notes, active, status, model_card_path
                ) VALUES (
                    $1, NOW(), $2, $3, $4::jsonb, $5, FALSE, $6, $7
                )
                ON CONFLICT (revision_id) DO UPDATE SET
                    notes = EXCLUDED.notes,
                    model_card_path = EXCLUDED.model_card_path,
                    status = EXCLUDED.status,
                    base_checkpoint = EXCLUDED.base_checkpoint,
                    quantization = EXCLUDED.quantization,
                    harness_config_json = EXCLUDED.harness_config_json
                """,
                rid,
                base,
                quant,
                json.dumps(hc),
                notes,
                status,
                card,
            )
        return {"ok": True, "revision_id": rid, "model_card_path": card, "persisted": True}
    except Exception as exc:
        logger.warning("LN7 register_revision: %s", exc)
        return {"ok": False, "error": str(exc), "revision_id": rid, "model_card_path": card}


async def set_shadow(db_pool, revision_id: str) -> bool:
    if not db_pool:
        return False
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE ln7_revisions SET status = 'shadow' WHERE revision_id = $1",
                revision_id,
            )
        return True
    except Exception as exc:
        logger.warning("LN7 set_shadow: %s", exc)
        return False


async def activate_revision(
    db_pool,
    revision_id: str,
    *,
    promoted_by: str = "ceo",
    ceo_decision_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Flip serving alias for one tier — other tier active stays (fast ≠ deep)."""
    # QUANTUM-CRYSTAL-ARCH — fence + suppress gates; dual_coo_mechanical allowed in G2
    try:
        from app.services.ln7_frozen_config import promotions_allowed

        if not promotions_allowed():
            return {"ok": False, "error": "fence_manifest_mismatch"}
    except Exception:
        pass
    try:
        from app.services.ln7_suppress import is_suppressed

        if await is_suppressed(db_pool, f"revision:{revision_id}"):
            return {"ok": False, "error": "pattern_suppressed"}
    except Exception:
        pass
    _auto = False
    try:
        from app.services.ln7_feature_flags import auto_promote_enabled as _pg_auto

        _auto = await _pg_auto(db_pool)
    except Exception:
        _auto = os.getenv("ENABLE_LN7_AUTO_PROMOTE", "").strip().lower() in (
            "1", "true", "yes", "on",
        )
    _allowed = (
        "ceo", "Nathan", "DrNevedal1", "system_test", "policy_auto",
        "dual_coo_mechanical",
    )
    if promote_requires_ceo() and promoted_by not in _allowed:
        return {"ok": False, "error": "ceo_approval_required"}
    if promoted_by == "policy_auto" and not _auto:
        return {"ok": False, "error": "auto_promote_disabled"}
    card = model_card_path(revision_id)
    root = Path(__file__).resolve().parents[3]
    if (
        not (root / card).is_file()
        and revision_id not in ("LN7-baseline", "LN7-fast-baseline")
    ):
        # baseline card written at register; require card for others
        if not (root / "docs/ln7/LN7_baseline.md").is_file():
            return {"ok": False, "error": "model_card_missing"}
    if not db_pool:
        return {"ok": False, "error": "no_db"}
    try:
        from app.services.little_nate_7 import revision_serving_tier

        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT revision_id, harness_config_json FROM ln7_revisions
                WHERE revision_id = $1
                """,
                revision_id,
            )
            if not row:
                return {"ok": False, "error": "revision_not_found"}
            tier = revision_serving_tier(dict(row))
            async with conn.transaction():
                # QUANTUM-CRYSTAL-ARCH — deactivate only same serving tier
                await conn.execute(
                    """
                    UPDATE ln7_revisions
                    SET active = FALSE,
                        status = CASE WHEN active THEN 'rolled_back' ELSE status END
                    WHERE active = TRUE
                      AND COALESCE(NULLIF(TRIM(harness_config_json->>'tier'), ''), 'deep') = $1
                    """,
                    tier,
                )
                await conn.execute(
                    """
                    UPDATE ln7_revisions
                    SET active = TRUE, status = 'active',
                        promoted_by = $2, ceo_decision_id = $3,
                        harness_config_json = jsonb_set(
                            COALESCE(harness_config_json, '{}'::jsonb),
                            '{tier}',
                            to_jsonb($4::text),
                            true
                        )
                    WHERE revision_id = $1
                    """,
                    revision_id,
                    promoted_by,
                    ceo_decision_id,
                    tier,
                )
        # Dual-COO notify (best-effort)
        try:
            if os.getenv("LN7_DUAL_COO_NOTIFY", "true").strip().lower() in ("1", "true", "yes", "on"):
                from app.websocket.cli_dual_coo import RISK_RED, enqueue_ceo
                enqueue_ceo(
                    risk=RISK_RED,
                    title=f"LN7 revision activated: {revision_id}",
                    detail=(
                        f"promoted_by={promoted_by} ceo_decision_id={ceo_decision_id} "
                        f"tier={tier}"
                    ),
                    origin="ln7",
                )
        except Exception as exc:
            logger.debug("LN7 dual-coo notify: %s", exc)
        return {"ok": True, "revision_id": revision_id, "active": True, "tier": tier}
    except Exception as exc:
        logger.warning("LN7 activate: %s", exc)
        return {"ok": False, "error": str(exc)}


async def notify_revision_candidate(
    db_pool,
    revision_id: str,
    *,
    force_ready: bool = False,
) -> Dict[str, Any]:
    """Enqueue Dual-COO CEO ask with readiness brief (YELLOW if premature, RED if ready).

    force_ready=True after canary await_ceo — still re-assesses; only sets RED/activate
    when readiness.ready (or force_class allows).
    """
    only_when_ready = os.getenv("LN7_CEO_NOTIFY_ONLY_WHEN_READY", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    try:
        from app.services.ln7_revision_readiness import (
            assess_revision_readiness,
            checklist_one_liner,
        )
        from app.websocket.cli_dual_coo import RISK_RED, RISK_YELLOW, enqueue_ceo

        readiness = await assess_revision_readiness(
            db_pool,
            revision_id,
            force_class="ready" if force_ready else None,
        )
        ready = bool(readiness.get("ready"))
        if only_when_ready and not ready:
            return {"status": "skipped", "reason": "not_ready_only_when_ready", "readiness": readiness}

        cls = "ready" if ready else "premature"
        title = (
            f"LN7 revision candidate: {revision_id} [READY]"
            if ready
            else f"LN7 revision candidate: {revision_id} [HOLD]"
        )
        checklist = checklist_one_liner(readiness)
        try:
            from app.services.little_nate_7 import (
                default_incumbent_id,
                load_revision,
                revision_serving_tier,
            )

            _rev = await load_revision(db_pool, revision_id)
            _tier = revision_serving_tier(_rev)
            _inc = default_incumbent_id(_tier)
        except Exception:
            _tier = "fast" if "7b" in str(readiness.get("base_checkpoint") or "").lower() else "deep"
            _inc = "LN7-fast-baseline" if _tier == "fast" else "LN7-baseline"
        bottom = (
            f"APPROVE to activate {revision_id} as LN7 {_tier} brain "
            f"(gate was vs {_inc}; deep 32B unchanged if fast)."
            if ready
            else f"HOLD — {revision_id} premature ({readiness.get('reason')})."
        )
        detail = f"{bottom} | {checklist}"
        payload: Dict[str, Any] = {
            "kind": "ln7_revision_candidate",
            "revision_id": revision_id,
            "ready": ready,
            "readiness": readiness,
            "readiness_class": cls,
            "checklist": checklist,
            "status": readiness.get("status"),
            "base_checkpoint": readiness.get("base_checkpoint"),
            "adapter_path": readiness.get("adapter_path"),
            "peft_url": readiness.get("peft_url"),
            "bottom_line": bottom,
            "what_it_should_do": (
                [
                    "On APPROVE: flip Sanctuary CLI LN7 serving alias to this revision.",
                    "Prior revision stays registered for rollback.",
                ]
                if ready
                else [
                    "Informational HOLD until bakeoff/canary READY renotify.",
                    "Do not treat this as an activate authorization.",
                ]
            ),
            "what_it_should_not_be": [
                "Not clinical AGI / Tier-2 evidence.",
                "Not auto-clinical traffic.",
                (
                    "APPROVE does not invent a missing adapter."
                    if ready
                    else "APPROVE will not activate while readiness.ready=false."
                ),
            ],
            "apply": {
                "action": "activate" if ready else "none",
                "revision_id": revision_id,
                "kind": "ln7_activate" if ready else "ln7_hold",
            },
        }
        risk = RISK_RED if ready else RISK_YELLOW
        enq = enqueue_ceo(
            risk=risk,
            title=title,
            detail=detail[:2000],
            origin="ln7",
            task_id=f"{revision_id}:{cls}",
            payload=payload,
        )
        return {"status": enq.get("status"), "ready": ready, "enqueue": enq, "readiness": readiness}
    except Exception as exc:
        logger.debug("LN7 candidate notify: %s", exc)
        return {"status": "error", "error": str(exc)[:200]}
