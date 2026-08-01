"""Flywheel pipeline wiring — activate-ready, flip-gated.

All paths stay G0-safe: CEO activate remains valid; DUAL_COO_MECHANICAL_PROMOTE
and ENABLE_LN7_AUTO_PROMOTE stay false until Step 0 + W1 shadow rows proven.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ln7_flywheel_pipeline")


async def _revision_row(db_pool, revision_id: str) -> Optional[Dict[str, Any]]:
    if not db_pool or not revision_id:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT revision_id, base_checkpoint, notes,
                       harness_config_json, status
                FROM ln7_revisions WHERE revision_id = $1
                """,
                revision_id,
            )
        return dict(row) if row else None
    except Exception as e:
        logger.warning("revision_row: %s", e)
        return None


def _adapter_hint(row: Dict[str, Any]) -> str:
    cfg = row.get("harness_config_json") or {}
    if isinstance(cfg, dict):
        for key in ("adapter_path", "adapter", "lora_path", "peft_adapter"):
            if cfg.get(key):
                return str(cfg[key])
    return ""


def _patch_hash_for_revision(row: Dict[str, Any], revision_id: str) -> str:
    raw = (
        _adapter_hint(row)
        + "|"
        + str(row.get("notes") or "")
        + "|"
        + revision_id
    )
    cfg = row.get("harness_config_json") or {}
    if isinstance(cfg, dict) and cfg.get("patch_hash"):
        return str(cfg["patch_hash"])[:64]
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _counterfactual_from_revision(row: Dict[str, Any]) -> str:
    """Sync harness_config / notes only — prefer async resolve_counterfactual."""
    cfg = row.get("harness_config_json") or {}
    if isinstance(cfg, dict):
        for key in ("counterfactual_diff", "unified_diff", "patch"):
            v = cfg.get(key)
            if isinstance(v, str) and v.strip():
                return v
    notes = str(row.get("notes") or "")
    if notes.lstrip().startswith("diff ") or notes.lstrip().startswith("--- "):
        return notes
    return ""


async def resolve_counterfactual(
    db_pool,
    row: Dict[str, Any],
    *,
    pack_ids: Optional[List[str]] = None,
) -> tuple[str, List[str]]:
    """Resolve LN7 counterfactual diff for W1 shadow oracle.

    Order: harness_config → latest ln7_coding_outcomes.patch_text for revision
    → pack golden.patch (Queens-merged fixture; still runs real ci_pack oracle).
    Never invent a fake new-file probe that can't score packs.
    """
    diff = _counterfactual_from_revision(row)
    packs: List[str] = list(pack_ids or [])
    rid = str(row.get("revision_id") or "")

    if not diff and db_pool and rid:
        try:
            async with db_pool.acquire() as conn:
                prow = await conn.fetchrow(
                    """
                    SELECT patch_text, metrics_json
                    FROM ln7_coding_outcomes
                    WHERE revision_id = $1
                      AND generator = 'ln7'
                      AND patch_text IS NOT NULL
                      AND LENGTH(patch_text) > 20
                      AND COALESCE(metrics_json->>'invalidated', '') = ''
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    rid,
                )
            if prow and prow.get("patch_text"):
                diff = str(prow["patch_text"])
                meta = prow.get("metrics_json") or {}
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}
                pack = (meta or {}).get("pack") if isinstance(meta, dict) else None
                if pack and pack not in packs:
                    packs = [str(pack)] + packs
        except Exception as e:
            logger.info("resolve_counterfactual outcomes: %s", e)

    if not diff:
        try:
            from app.services.ln_sandbox_engineering_ci import (
                list_pack_names,
                materialize_pack,
            )

            names = packs or list_pack_names()[:1]
            for name in names:
                workdir, _meta, _err = materialize_pack(name)
                if not workdir:
                    continue
                gpath = workdir / "golden.patch"
                if gpath.is_file():
                    body = gpath.read_text(encoding="utf-8").strip()
                    if body:
                        diff = body
                        if name not in packs:
                            packs = [name] + packs
                        break
        except Exception as e:
            logger.info("resolve_counterfactual golden: %s", e)

    return diff, packs



async def emit_queens_task_merged(
    db_pool,
    *,
    revision_id: str = "",
    patch_hash: str = "",
    domain: str = "",
    evidence_uri: str = "",
    counterfactual_diff: str = "",
    pack_ids: Optional[List[str]] = None,
    run_inline: bool = True,
) -> Dict[str, Any]:
    """W1 production trigger — Queens/LN7 merge → shadow fork + pack candidate."""
    from app.services.ln7_shadow_fork import on_queens_task_merged, run_shadow_fork

    row = await _revision_row(db_pool, revision_id) if revision_id else None
    resolved_packs = list(pack_ids or [])
    if row:
        patch_hash = patch_hash or _patch_hash_for_revision(row, revision_id)
        if not counterfactual_diff:
            counterfactual_diff, resolved_packs = await resolve_counterfactual(
                db_pool, row, pack_ids=resolved_packs or None
            )
        if not evidence_uri:
            evidence_uri = f"revision:{revision_id}"
        cfg = row.get("harness_config_json") or {}
        if isinstance(cfg, dict) and not domain:
            domain = str(cfg.get("domain") or cfg.get("domain_tag") or "")

    if not patch_hash:
        patch_hash = hashlib.sha256(
            (counterfactual_diff or revision_id or "empty").encode()
        ).hexdigest()[:32]

    if run_inline:
        return await on_queens_task_merged(
            db_pool,
            patch_hash=patch_hash,
            domain=domain,
            evidence_uri=evidence_uri,
            counterfactual_diff=counterfactual_diff,
            pack_ids=resolved_packs or None,
        )

    # Bus-only publish (consumer runs shadow)
    try:
        from app.websocket.cli_task_bus import publish_task
        from app.services.ln7_living_packs import record_pack_candidate
        from app.services.ln7_injection_firewall import (
            tripwire_check,
            validate_tool_dispatch,
        )
        import json

        _raw_diff = counterfactual_diff or ""
        _notes: Dict[str, Any] = {
            "patch_hash": patch_hash,
            "domain": domain,
            "evidence_uri": evidence_uri,
            "revision_id": revision_id,
            "pack_ids": resolved_packs or [],
        }
        if _raw_diff.strip():
            # R4: same external-content scan as the inline path — this diff
            # is about to sit in another CLI consumer's task notes.
            trip = await tripwire_check(_raw_diff, db_pool=db_pool, agent="ln7_flywheel_pipeline")
            if trip.get("tripped"):
                _notes["counterfactual_diff_redacted"] = True
                _notes["injection_flagged"] = trip.get("token")
            else:
                _notes["counterfactual_diff"] = _raw_diff[:1200]
                if len(_raw_diff) > 1200:
                    _notes["counterfactual_diff_truncated"] = True
        _kind = "ln7_shadow_fork"
        if validate_tool_dispatch(_kind):
            publish_task(
                origin="queens",
                kind=_kind,
                notes=json.dumps(_notes)[:2000],
                files=[],
            )
        else:
            logger.warning("emit_queens_task_merged: kind %s not in R4 allowlist", _kind)
        if db_pool:
            await record_pack_candidate(
                db_pool,
                patch_hash=patch_hash,
                domain=domain,
                evidence_uri=evidence_uri,
            )
    except Exception as e:
        logger.warning("emit_queens bus publish: %s", e)
        return await run_shadow_fork(
            db_pool,
            patch_hash=patch_hash,
            domain=domain,
            evidence_uri=evidence_uri,
            counterfactual_diff=counterfactual_diff,
            pack_ids=pack_ids,
        )
    return {
        "ok": True,
        "path": "bus",
        "patch_hash": patch_hash,
        "revision_id": revision_id,
    }


async def ensure_shadow_for_revision(
    db_pool,
    revision_id: str,
    *,
    force: bool = False,
) -> Dict[str, Any]:
    """Idempotent W1: create shadow_outcome rows for revision before promote ask."""
    from app.services.ln7_outcome_envelope import has_shadow_outcome_for_patch

    row = await _revision_row(db_pool, revision_id)
    if not row:
        return {"ok": False, "error": "revision_not_found"}
    patch_hash = _patch_hash_for_revision(row, revision_id)
    if not force and await has_shadow_outcome_for_patch(db_pool, patch_hash):
        return {
            "ok": True,
            "skipped": True,
            "patch_hash": patch_hash,
            "reason": "shadow_outcome_exists",
        }
    out = await emit_queens_task_merged(
        db_pool,
        revision_id=revision_id,
        patch_hash=patch_hash,
        run_inline=True,
    )
    return {"ok": bool(out.get("ok")), "patch_hash": patch_hash, "shadow": out}


async def promote_path_after_gate(
    db_pool,
    revision_id: str,
    *,
    evidence: Optional[Dict[str, Any]] = None,
    title: str = "",
) -> Dict[str, Any]:
    """G0: ensure shadow → Dual-COO helper (still CEO enqueue). G2: mechanical.

    Does NOT flip flags. Does NOT strip CEO activate under G0/G1.
    """
    from app.services.dual_coo_checklist import maybe_promote_via_checklist_or_ceo
    from app.services.ln7_feature_flags import dual_coo_mechanical_promote

    shadow = await ensure_shadow_for_revision(db_pool, revision_id)
    row = await _revision_row(db_pool, revision_id) or {}
    patch_hash = shadow.get("patch_hash") or _patch_hash_for_revision(
        row, revision_id
    )
    ev = dict(evidence or {})
    ev.setdefault("evidence_uri", f"revision:{revision_id}")
    ev.setdefault("revision_id", revision_id)
    ev.setdefault("patch_hash", patch_hash)
    ev.setdefault("fence_manifest_ok", True)

    mechanical = False
    try:
        mechanical = await dual_coo_mechanical_promote(db_pool)
    except Exception:
        mechanical = False

    if not mechanical:
        # G0/G1 — keep rich CEO readiness notify as primary activate path
        from app.services.ln7_feature_flags import g1_open
        from app.services.ln7_revision import notify_revision_candidate

        ceo = await notify_revision_candidate(
            db_pool, revision_id, force_ready=True
        )
        # Also record thin checklist enqueue for lineage (dedup may skip)
        thin = await maybe_promote_via_checklist_or_ceo(
            db_pool,
            revision_id=revision_id,
            evidence=ev,
            title=title or f"LN7 promote candidate: {revision_id}",
        )
        epoch = "G1" if await g1_open(db_pool) else "G0"
        return {
            "ok": True,
            "governance": epoch,
            "shadow": shadow,
            "ceo_notify": ceo,
            "checklist_path": thin,
            "activated": False,
        }

    # G2 only — mechanical Dual-COO (flags must already be true)
    out = await maybe_promote_via_checklist_or_ceo(
        db_pool,
        revision_id=revision_id,
        evidence=ev,
        title=title or f"LN7 promote candidate: {revision_id}",
    )
    return {
        "ok": True,
        "governance": "G2",
        "shadow": shadow,
        "promote": out,
        "activated": bool(out.get("activated")),
    }


async def route_coding_turn(
    db_pool,
    prompt: str,
    *,
    file_paths: Optional[List[str]] = None,
    task_hash: str = "",
) -> Dict[str, Any]:
    """W5/B2: domain router when ENABLE_LN7_DOMAIN_ROUTER; else no-op."""
    try:
        from app.services.ln7_domain_router import route, router_enabled

        if not await router_enabled(db_pool):
            return {"ok": True, "skipped": True, "reason": "router_disabled"}
        return await route(
            db_pool,
            prompt=prompt,
            file_paths=file_paths or [],
            task_hash=task_hash,
        )
    except Exception as e:
        logger.info("route_coding_turn: %s", e)
        return {"ok": False, "error": str(e)[:200]}
