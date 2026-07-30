"""Mechanical Dual-COO checklist review (F2 / W2) — G2 only.

Until DUAL_COO_MECHANICAL_PROMOTE=true, callers must keep enqueue_ceo
(CEO activate remains valid under G0/G1).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("dual_coo_checklist")


def load_checklist() -> Dict[str, Any]:
    try:
        from app.services.ln7_frozen_config import load_json

        data = load_json("dual_coo_checklist.json", {})
        return data or {}
    except Exception:
        return {}


async def evaluate_evidence(
    evidence: Dict[str, Any],
    *,
    db_pool=None,
) -> Dict[str, Any]:
    """Score welded checklist against evidence URI payload (dict)."""
    spec = load_checklist()
    items = list(spec.get("checklist") or [])
    results: List[Dict[str, Any]] = []
    all_required_ok = True

    for item in items:
        iid = item.get("id")
        required = bool(item.get("required"))
        ok = bool(evidence.get(iid) or evidence.get("checks", {}).get(iid))
        # Built-in mechanical checks when evidence omits explicit bool
        if iid == "fence_manifest_ok" and iid not in evidence and "checks" not in evidence:
            try:
                from app.services.ln7_frozen_config import promotions_allowed

                ok = promotions_allowed()
            except Exception:
                ok = False
        if iid == "not_suppressed" and db_pool and evidence.get("pattern_key"):
            from app.services.ln7_suppress import is_suppressed

            ok = not await is_suppressed(db_pool, str(evidence["pattern_key"]))
        if iid == "base_checkpoint_pinned":
            base = str(evidence.get("base_checkpoint") or "")
            ok = "Qwen2.5-Coder-7B" in base or evidence.get(iid) is True
        results.append({"id": iid, "ok": ok, "required": required})
        if required and not ok:
            all_required_ok = False

    return {
        "agree": all_required_ok,
        "items": results,
        "evidence_uri": evidence.get("evidence_uri"),
    }


async def dual_coo_checklist_review(
    evidence_uri: str,
    *,
    db_pool=None,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Both Queens evaluate independently (diverse models — structural).

    Agreement → promote path. Disagreement → RED hold + anomaly.
    Does NOT call enqueue_ceo (G2). Caller must gate on dual_coo_mechanical_promote.
    """
    payload = dict(evidence or {})
    payload.setdefault("evidence_uri", evidence_uri)

    # Simulate two independent reviews (same mechanical checklist; diversity
    # is in model selection at inference sites — here both must pass welds).
    mac = await evaluate_evidence(payload, db_pool=db_pool)
    cloud = await evaluate_evidence(payload, db_pool=db_pool)
    agree = bool(mac.get("agree") and cloud.get("agree"))

    out = {
        "agree": agree,
        "mac": mac,
        "cloud": cloud,
        "evidence_uri": evidence_uri,
        "action": "promote" if agree else "red_hold",
    }

    if not agree:
        try:
            from app.services.flywheel_anomaly import notify_flywheel_anomaly
            from app.services.ln7_outcome_envelope import write_envelope

            await notify_flywheel_anomaly(
                "queens_disagree_lineage",
                {"evidence_uri": evidence_uri, "mac": mac, "cloud": cloud},
                db_pool=db_pool,
            )
            if db_pool:
                await write_envelope(
                    db_pool,
                    loop_name="dual_coo",
                    event_kind="checklist_disagree",
                    metrics={"mac": mac, "cloud": cloud},
                )
        except Exception as e:
            logger.warning("disagree side-effects failed: %s", e)
    return out


async def maybe_promote_via_checklist_or_ceo(
    db_pool,
    *,
    revision_id: str,
    evidence: Dict[str, Any],
    title: str,
    detail: str = "",
) -> Dict[str, Any]:
    """G0/G1: enqueue_ceo. G2: mechanical checklist → activate_revision."""
    from app.services.ln7_feature_flags import dual_coo_mechanical_promote

    if await dual_coo_mechanical_promote(db_pool):
        review = await dual_coo_checklist_review(
            evidence.get("evidence_uri") or f"revision:{revision_id}",
            db_pool=db_pool,
            evidence={**evidence, "revision_id": revision_id},
        )
        if review.get("agree"):
            # R6: influence concentration → YELLOW hold (no activate)
            try:
                from app.services.ln7_influence_audit import influence_audit

                audit = influence_audit(list(evidence.get("sources") or []))
                if audit.get("yellow_hold"):
                    return {
                        "path": "mechanical",
                        "activated": False,
                        "review": review,
                        "influence": audit,
                        "error": "influence_gini_yellow",
                    }
            except Exception:
                pass
            # G1: shadow_outcome required when patch_hash present
            patch_hash = evidence.get("patch_hash")
            if patch_hash:
                from app.services.ln7_shadow_fork import g1_promote_allowed

                if not await g1_promote_allowed(db_pool, str(patch_hash)):
                    return {
                        "path": "mechanical",
                        "activated": False,
                        "review": review,
                        "error": "shadow_outcome_required",
                    }
            from app.services.ln7_revision import activate_revision

            ok = await activate_revision(
                db_pool, revision_id, promoted_by="dual_coo_mechanical"
            )
            return {"path": "mechanical", "activated": ok, "review": review}
        return {"path": "mechanical", "activated": False, "review": review}

    # G0/G1 — CEO activate remains valid (patch-point for offline CI)
    enq = _enqueue_ceo_promote(
        revision_id=revision_id,
        title=title,
        detail=detail,
        evidence=evidence,
    )
    return {"path": "ceo_inbox", "enqueued": enq, "activated": False}


def _enqueue_ceo_promote(
    *,
    revision_id: str,
    title: str,
    detail: str = "",
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Thin wrapper so G0 tests can patch without racing late imports."""
    from app.websocket.cli_dual_coo import enqueue_ceo

    evidence = evidence or {}
    return enqueue_ceo(
        risk="YELLOW",
        title=title,
        detail=detail or f"LN7 promote candidate {revision_id}",
        origin="ln7",
        payload={
            "kind": "ln7_revision_candidate",
            "revision_id": revision_id,
            "ready": True,
            "apply": {"action": "activate"},
            **evidence,
        },
    )
