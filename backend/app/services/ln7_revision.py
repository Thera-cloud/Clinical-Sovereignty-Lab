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
                    status = EXCLUDED.status
                """,
                rid,
                base,
                quant,
                json.dumps(harness_config or {}),
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
    """Flip serving alias — previous revision stays registered (rollback = re-activate)."""
    _auto = os.getenv("ENABLE_LN7_AUTO_PROMOTE", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    _allowed = ("ceo", "Nathan", "DrNevedal1", "system_test", "policy_auto")
    if promote_requires_ceo() and promoted_by not in _allowed:
        return {"ok": False, "error": "ceo_approval_required"}
    if promoted_by == "policy_auto" and not _auto:
        return {"ok": False, "error": "auto_promote_disabled"}
    card = model_card_path(revision_id)
    root = Path(__file__).resolve().parents[3]
    if not (root / card).is_file() and revision_id != "LN7-baseline":
        # baseline card written at register; require card for others
        if not (root / "docs/ln7/LN7_baseline.md").is_file():
            return {"ok": False, "error": "model_card_missing"}
    if not db_pool:
        return {"ok": False, "error": "no_db"}
    try:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE ln7_revisions SET active = FALSE, status = CASE WHEN active THEN 'rolled_back' ELSE status END"
                )
                await conn.execute(
                    """
                    UPDATE ln7_revisions
                    SET active = TRUE, status = 'active',
                        promoted_by = $2, ceo_decision_id = $3
                    WHERE revision_id = $1
                    """,
                    revision_id,
                    promoted_by,
                    ceo_decision_id,
                )
        # Dual-COO notify (best-effort)
        try:
            if os.getenv("LN7_DUAL_COO_NOTIFY", "true").strip().lower() in ("1", "true", "yes", "on"):
                from app.websocket.cli_dual_coo import RISK_RED, enqueue_ceo
                enqueue_ceo(
                    risk=RISK_RED,
                    title=f"LN7 revision activated: {revision_id}",
                    detail=f"promoted_by={promoted_by} ceo_decision_id={ceo_decision_id}",
                    origin="ln7",
                )
        except Exception as exc:
            logger.debug("LN7 dual-coo notify: %s", exc)
        return {"ok": True, "revision_id": revision_id, "active": True}
    except Exception as exc:
        logger.warning("LN7 activate: %s", exc)
        return {"ok": False, "error": str(exc)}


async def notify_revision_candidate(revision_id: str) -> None:
    """RED-class enqueue for Dual-COO + CEO before activate."""
    try:
        from app.websocket.cli_dual_coo import RISK_RED, enqueue_ceo
        enqueue_ceo(
            risk=RISK_RED,
            title=f"LN7 revision candidate: {revision_id}",
            detail="Awaiting Dual-COO peer review + CEO APPROVE before serving flip.",
            origin="ln7",
        )
    except Exception as exc:
        logger.debug("LN7 candidate notify: %s", exc)
