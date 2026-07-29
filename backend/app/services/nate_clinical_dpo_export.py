"""QUANTUM-CRYSTAL-ARCH — DPO JSONL export for sovereign checkpoints only."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.nate_clinical_flags import dpo_export_dir, dpo_export_enabled

logger = logging.getLogger("nate.clinical_dpo")


async def export_preferences_jsonl(
    db_pool,
    *,
    out_dir: Optional[str] = None,
) -> Dict[str, Any]:
    if not dpo_export_enabled():
        return {"ok": False, "reason": "ENABLE_NATE_CLINICAL_DPO_EXPORT=false"}
    if db_pool is None:
        return {"ok": False, "reason": "no_db"}

    try:
        from app.services.night_school_director import PIIDetector

        detector = PIIDetector()
    except Exception:
        return {"ok": False, "reason": "pii_detector_unavailable"}

    rows: List[Dict[str, Any]] = []
    async with db_pool.acquire() as conn:
        fetched = await conn.fetch(
            """
            SELECT p.match_id, p.x, p.y_win, p.y_lose, p.confidence, p.split
            FROM nate_clinical_preferences p
            WHERE p.split = 'train'
            ORDER BY p.created_at DESC
            LIMIT 5000
            """
        )
        for r in fetched:
            y_win = r["y_win"] or ""
            y_lose = r["y_lose"] or ""
            # Fail closed: any PII hit drops the row
            try:
                hits = list(detector.detect(y_win) or []) + list(
                    detector.detect(y_lose) or []
                )
            except Exception:
                return {"ok": False, "reason": "pii_detector_error"}
            if hits:
                continue
            rows.append(
                {
                    "prompt": r["x"] if isinstance(r["x"], dict) else json.loads(r["x"] or "{}"),
                    "chosen": y_win,
                    "rejected": y_lose,
                    "match_id": str(r["match_id"]),
                    "confidence": float(r["confidence"] or 0.5),
                    "target": "sovereign_or_home_gpu_checkpoint",
                }
            )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    directory = Path(out_dir or dpo_export_dir())
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"preferences_{stamp}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    return {
        "ok": True,
        "path": str(path),
        "rows": len(rows),
        "note": "Fine-tune sovereign ORANGE/Home GPU only — never vendor Grok/Azure APIs",
    }


async def register_revision(
    db_pool,
    *,
    revision_id: str,
    checkpoint_ref: str,
    provider: str,
    activate: bool = False,
    ceo_decision_id: Optional[str] = None,
) -> Dict[str, Any]:
    if provider not in ("sovereign", "home_gpu"):
        return {"ok": False, "reason": "provider_must_be_sovereign_or_home_gpu"}
    if db_pool is None:
        return {"ok": False, "reason": "no_db"}
    async with db_pool.acquire() as conn:
        if activate:
            await conn.execute("UPDATE nate_clinical_revisions SET active = FALSE")
        await conn.execute(
            """
            INSERT INTO nate_clinical_revisions
                (revision_id, checkpoint_ref, provider, active, ceo_decision_id)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (revision_id) DO UPDATE SET
                checkpoint_ref = EXCLUDED.checkpoint_ref,
                active = EXCLUDED.active,
                ceo_decision_id = EXCLUDED.ceo_decision_id
            """,
            revision_id,
            checkpoint_ref,
            provider,
            activate,
            ceo_decision_id,
        )
    return {"ok": True, "revision_id": revision_id, "active": activate}


async def rollback_revision(db_pool, revision_id: str) -> Dict[str, Any]:
    if db_pool is None:
        return {"ok": False, "reason": "no_db"}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT revision_id FROM nate_clinical_revisions WHERE revision_id = $1",
            revision_id,
        )
        if not row:
            return {"ok": False, "reason": "not_found"}
        await conn.execute("UPDATE nate_clinical_revisions SET active = FALSE")
        await conn.execute(
            "UPDATE nate_clinical_revisions SET active = TRUE WHERE revision_id = $1",
            revision_id,
        )
    return {"ok": True, "active": revision_id}
