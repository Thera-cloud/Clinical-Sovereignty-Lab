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
        if iid == "heldout_not_in_train" and iid not in evidence and "checks" not in evidence:
            # Phase H held-out weld: mechanical floor-integrity check, not a
            # per-row training-set trace (that would require a separate
            # provenance table). This verifies the held-out *definition*
            # itself hasn't been silently narrowed in packs_index.json out
            # from under the frozen-config pin — see
            # ln7_heldout_registry.heldout_weld_status().
            try:
                from app.services.ln7_heldout_registry import heldout_weld_status

                ok = bool(heldout_weld_status().get("ok"))
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


async def evaluate_evidence_independent(
    evidence: Dict[str, Any],
    *,
    db_pool=None,
) -> Dict[str, Any]:
    """Independent second reviewer (TRUST_LEDGER.md Entry 24/27).

    evaluate_evidence() above has a deliberate, tested escape hatch (see
    test_dual_coo_heldout_weld_check.py::
    test_heldout_not_in_train_respects_explicit_evidence_override): a
    caller-supplied bool in `evidence[iid]` bypasses the mechanical check
    entirely for ANY item, by design. That's a legitimate feature for
    evaluate_evidence() as a single reviewer, but it is exactly why calling
    that same function twice ("mac"/"cloud") could never disagree — both
    calls trust the identical self-reported dict. This function is
    genuinely independent BY NEVER HONORING THAT ESCAPE HATCH: every item
    with a real mechanical source of truth is re-derived from source every
    time, ignoring whatever the proposer claims. Disagreement with
    evaluate_evidence() is therefore structurally possible whenever a
    proposer's self-report doesn't match ground truth — a genuinely
    different source of truth, not a second LLM call, since this checklist
    is pure mechanical fact-checking with no LLM in the loop today.

    Items with no independent mechanical check available (currently
    `beats_incumbent_on_heldout`, `license_train_eligible`) fail closed
    (ok=False) unless a corroborating `<id>_evidence_uri` artifact
    reference is present in `evidence` — a bare bool is never sufficient
    for this reviewer, unlike evaluate_evidence()'s escape hatch.
    """
    spec = load_checklist()
    items = list(spec.get("checklist") or [])
    results: List[Dict[str, Any]] = []
    all_required_ok = True

    for item in items:
        iid = item.get("id")
        required = bool(item.get("required"))
        ok = False
        verified_independently = False

        if iid == "fence_manifest_ok":
            try:
                from app.services.ln7_frozen_config import promotions_allowed

                ok = promotions_allowed()
                verified_independently = True
            except Exception:
                ok = False
        elif iid == "heldout_not_in_train":
            try:
                from app.services.ln7_heldout_registry import heldout_weld_status

                ok = bool(heldout_weld_status().get("ok"))
                verified_independently = True
            except Exception:
                ok = False
        elif iid == "not_suppressed":
            if db_pool and evidence.get("pattern_key"):
                try:
                    from app.services.ln7_suppress import is_suppressed

                    ok = not await is_suppressed(db_pool, str(evidence["pattern_key"]))
                    verified_independently = True
                except Exception:
                    ok = False
            else:
                # No pattern_key to check against -- nothing to suppress,
                # matches evaluate_evidence()'s own no-op condition, but
                # this reviewer marks it explicitly rather than silently
                # falling through to a bare bool.
                ok = True
                verified_independently = True
        elif iid == "base_checkpoint_pinned":
            base = str(evidence.get("base_checkpoint") or "")
            try:
                from app.services.ln7_frozen_config import load_json

                pin = load_json("governance.json", {}) or {}
                pinned_base = str(pin.get("base_checkpoint") or "Qwen2.5-Coder-7B")
                ok = pinned_base in base
                verified_independently = True
            except Exception:
                ok = "Qwen2.5-Coder-7B" in base
                verified_independently = True
        elif iid == "shadow_outcome_present_if_g1":
            patch_hash = evidence.get("patch_hash")
            if not patch_hash:
                # No patch_hash -- not in the G1 shadow-fork flow, matches
                # this item's own "_if_g1" conditional semantics.
                ok = True
                verified_independently = True
            elif db_pool:
                try:
                    from app.services.ln7_shadow_fork import g1_promote_allowed

                    ok = await g1_promote_allowed(db_pool, str(patch_hash))
                    verified_independently = True
                except Exception:
                    ok = False
            else:
                ok = False
        elif iid == "influence_gini_ok":
            try:
                from app.services.ln7_influence_audit import influence_audit

                audit = influence_audit(list(evidence.get("sources") or []))
                ok = not bool(audit.get("yellow_hold"))
                verified_independently = True
            except Exception:
                ok = False
        else:
            # No independent mechanical check exists for this item yet
            # (beats_incumbent_on_heldout, license_train_eligible as of
            # this writing). Fail closed rather than trust a bare bool --
            # a corroborating artifact reference is the only thing that
            # clears it, and even that is logged as not fully
            # mechanically verified.
            artifact = evidence.get(f"{iid}_evidence_uri") or evidence.get(
                f"{iid}_artifact"
            )
            ok = bool(artifact)
            verified_independently = False

        results.append(
            {
                "id": iid,
                "ok": ok,
                "required": required,
                "verified_independently": verified_independently,
            }
        )
        if required and not ok:
            all_required_ok = False

    return {
        "agree": all_required_ok,
        "items": results,
        "evidence_uri": evidence.get("evidence_uri"),
        "reviewer": "independent",
    }


async def dual_coo_checklist_review(
    evidence_uri: str,
    *,
    db_pool=None,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Two genuinely independent reviewers (TRUST_LEDGER.md Entry 24/27
    closes the "same function called twice" gap):

    - "mac" = evaluate_evidence() — trusts self-reported evidence for any
      item the proposer already claimed (the escape-hatch reviewer).
    - "cloud" = evaluate_evidence_independent() — re-derives every
      mechanically-checkable item from source, never trusting the
      proposer's claim for those items.

    These are two DIFFERENT functions consulting different sources of
    truth (proposer claim vs. independently re-derived fact), not the same
    function called twice — disagreement is now structurally possible
    whenever a proposer's self-report doesn't match ground truth.

    Agreement → promote path. Disagreement → RED hold + anomaly.
    Does NOT call enqueue_ceo (G2). Caller must gate on dual_coo_mechanical_promote.
    """
    payload = dict(evidence or {})
    payload.setdefault("evidence_uri", evidence_uri)

    mac = await evaluate_evidence(payload, db_pool=db_pool)
    cloud = await evaluate_evidence_independent(payload, db_pool=db_pool)
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
            from app.services.ln7_outcome_envelope import (
                cross_loop_attribution,
                write_envelope,
            )

            await notify_flywheel_anomaly(
                "queens_disagree_lineage",
                {"evidence_uri": evidence_uri, "mac": mac, "cloud": cloud},
                db_pool=db_pool,
            )
            if db_pool:
                # E2: carry revision_id/patch_hash through so this disagreement
                # can be joined against the shadow_fork/hive_burst/canary_eval
                # envelopes for the same lineage, not just viewed in isolation.
                attribution = cross_loop_attribution(payload, evidence_uri=evidence_uri)
                await write_envelope(
                    db_pool,
                    loop_name="dual_coo",
                    event_kind="checklist_disagree",
                    revision_id=payload.get("revision_id"),
                    patch_hash=payload.get("patch_hash"),
                    attribution=attribution,
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

    # G0/G1 — seed CI oracle shadow before CEO inbox (idempotent)
    try:
        from app.services.ln7_flywheel_pipeline import ensure_shadow_for_revision

        await ensure_shadow_for_revision(db_pool, revision_id)
    except Exception:
        pass

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
