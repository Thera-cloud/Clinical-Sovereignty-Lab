"""LN Sandbox promotion gate — draft practice corpus → production crystals.

Never auto-promotes. Admin/coach must approve. NateResponseValidator blocks
high-severity violations. Restraint_ref rows with metadata.immutable cannot
be rejected via this path (they are already promoted seeds).
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("sovereign.ln_sandbox_promotion")

PROMOTED_ORIGIN = "ln_sandbox_promoted"


async def enqueue_promotion(
    db_pool,
    corpus_id: str,
    *,
    requested_by: str = "system",
) -> Dict[str, Any]:
    """Queue a draft corpus row for human review."""
    if not db_pool:
        return {"ok": False, "error": "no_db"}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, status, track, kind, metadata
               FROM ln_sandbox_practice_corpus WHERE id = $1::uuid""",
            corpus_id,
        )
        if not row:
            return {"ok": False, "error": "not_found"}
        meta = row["metadata"] or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        if meta.get("immutable"):
            return {"ok": False, "error": "immutable_restraint_ref"}
        if row["status"] == "promoted":
            return {"ok": False, "error": "already_promoted"}
        await conn.execute(
            """UPDATE ln_sandbox_practice_corpus
               SET status = 'queued', updated_at = NOW()
               WHERE id = $1::uuid AND status IN ('draft', 'queued')""",
            corpus_id,
        )
        await conn.execute(
            """INSERT INTO ln_sandbox_promotion_queue (corpus_id, requested_by)
               VALUES ($1::uuid, $2)
               ON CONFLICT (corpus_id) DO UPDATE
               SET requested_by = EXCLUDED.requested_by,
                   decision = 'pending',
                   decided_by = NULL,
                   decided_at = NULL,
                   decision_notes = NULL""",
            corpus_id,
            (requested_by or "system")[:64],
        )
    return {"ok": True, "corpus_id": corpus_id, "status": "queued"}


async def decide_promotion(
    db_pool,
    corpus_id: str,
    *,
    approve: bool,
    decided_by: str,
    notes: str = "",
    app_state=None,
) -> Dict[str, Any]:
    """Approve → validate → write crystal; reject → archive draft."""
    if not db_pool:
        return {"ok": False, "error": "no_db"}

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT c.id, c.title, c.body, c.track, c.kind, c.scope,
                      c.target_user_id, c.confidence, c.metadata, c.status,
                      q.id AS queue_id, q.decision
               FROM ln_sandbox_practice_corpus c
               LEFT JOIN ln_sandbox_promotion_queue q ON q.corpus_id = c.id
               WHERE c.id = $1::uuid""",
            corpus_id,
        )
        if not row:
            return {"ok": False, "error": "not_found"}
        meta = row["metadata"] or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        if meta.get("immutable") and not approve:
            return {"ok": False, "error": "cannot_reject_immutable"}

        if not approve:
            await conn.execute(
                """UPDATE ln_sandbox_practice_corpus
                   SET status = 'rejected', updated_at = NOW()
                   WHERE id = $1::uuid""",
                corpus_id,
            )
            await conn.execute(
                """UPDATE ln_sandbox_promotion_queue
                   SET decision = 'rejected', decided_by = $2,
                       decision_notes = $3, decided_at = NOW()
                   WHERE corpus_id = $1::uuid""",
                corpus_id,
                (decided_by or "admin")[:64],
                (notes or "")[:2000],
            )
            return {"ok": True, "decision": "rejected", "corpus_id": corpus_id}

        crystal_text = f"{row['title']}\n\n{row['body']}".strip()
        blocked, warnings = await _validate_async(crystal_text, app_state)
        if blocked:
            return {
                "ok": False,
                "error": "validator_blocked",
                "violations": warnings[:8],
            }

        domain = _domain_for_track(row["track"])
        content_hash = hashlib.sha256(crystal_text.encode("utf-8")).hexdigest()
        user_uuid = None
        scope = row["scope"] or "admin_only"
        if row["target_user_id"] and str(scope).startswith("user"):
            user_uuid = await _resolve_user_uuid(conn, row["target_user_id"])

        conf = float(row["confidence"] or 0.55)
        conf = max(0.40, min(0.85, conf))

        write_scope = (
            scope
            if scope in ("global", "admin_only") or str(scope).startswith("user")
            else "admin_only"
        )
        if domain == "clinical" and write_scope == "global":
            write_scope = "admin_only"

        crystal_id = await conn.fetchval(
            """INSERT INTO nate_intelligence_crystals
               (crystal_text, domain, scope, topics, source_count,
                generation, confidence, content_hash, user_id,
                origin_surface, metadata)
               VALUES ($1, $2, $3, '{}'::text[], 2, 0, $4, $5, $6,
                       $7, $8::jsonb)
               ON CONFLICT (content_hash) DO UPDATE
               SET updated_at = NOW()
               RETURNING id""",
            crystal_text[:8000],
            domain,
            write_scope,
            conf,
            content_hash,
            user_uuid,
            PROMOTED_ORIGIN,
            json.dumps({
                "sandbox_corpus_id": str(row["id"]),
                "sandbox_track": row["track"],
                "sandbox_kind": row["kind"],
                "promoted_by": decided_by,
                "promoted_at": datetime.now(timezone.utc).isoformat(),
            }),
        )

        await conn.execute(
            """UPDATE ln_sandbox_practice_corpus
               SET status = 'promoted', updated_at = NOW(),
                   metadata = COALESCE(metadata, '{}'::jsonb) || $2::jsonb
               WHERE id = $1::uuid""",
            corpus_id,
            json.dumps({"crystal_id": crystal_id}),
        )
        await conn.execute(
            """UPDATE ln_sandbox_promotion_queue
               SET decision = 'approved', decided_by = $2,
                   decision_notes = $3, decided_at = NOW(),
                   crystal_id = $4
               WHERE corpus_id = $1::uuid""",
            corpus_id,
            (decided_by or "admin")[:64],
            (notes or "")[:2000],
            crystal_id,
        )

        # Optional harvest buffer nudge for crystallizer clustering
        try:
            crystallizer = (
                getattr(app_state, "nate_memory_crystallizer", None)
                if app_state
                else None
            )
            if crystallizer and hasattr(crystallizer, "_harvest_buffer"):
                crystallizer._harvest_buffer.append({
                    "text": crystal_text[:2000],
                    "source": PROMOTED_ORIGIN,
                    "domain": domain,
                    "scope": "admin_only" if domain == "clinical" else scope,
                    "created_at": datetime.now(timezone.utc),
                })
        except Exception as e:
            logger.warning("ln_sandbox_promotion: harvest append failed: %s", e)

    return {
        "ok": True,
        "decision": "approved",
        "corpus_id": corpus_id,
        "crystal_id": str(crystal_id),
    }


async def _validate_async(text: str, app_state=None) -> tuple:
    """Return (blocked: bool, warnings: list). High-severity warnings block."""
    try:
        validator = (
            getattr(app_state, "nate_response_validator", None) if app_state else None
        )
        if validator is None:
            from app.services.nate_response_validator import NateResponseValidator

            validator = NateResponseValidator()
        _, warnings = await validator.validate(text, {})
        warnings = list(warnings or [])
        if hasattr(validator, "is_high_severity") and validator.is_high_severity(warnings):
            return True, warnings
        return False, warnings
    except Exception as e:
        logger.warning("ln_sandbox_promotion: validator unavailable (allow): %s", e)
        return False, []


def _domain_for_track(track: str) -> str:
    if track == "engineering":
        return "research"
    if track in ("clinical_strategy", "client_prep"):
        return "clinical"
    return "general"


async def _resolve_user_uuid(conn, username_or_hw: str) -> Optional[Any]:
    try:
        return await conn.fetchval(
            """SELECT id FROM users
               WHERE username = $1 OR hardware_id = $1
               LIMIT 1""",
            username_or_hw,
        )
    except Exception:
        return None
