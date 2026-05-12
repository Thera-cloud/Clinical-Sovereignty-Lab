"""LITTLE NATE — Sensitive Clinical Bridge Auditor (auditor #29)

Verifies the v1.3 Sensitive Clinical Bridge contract surface (orchestrator,
detectors, validator wiring, DB schema, telemetry, feature flags).

Match the trust-enforcer fleet pattern (see token_lab_auditor.py reference):
single class, single async audit() method returning a structured result,
registered in main.py::_service_checks. Trust-enforcer framework owns
scheduling, retry, and trust_baseline writes — this auditor only produces
verdicts.

CHECK ORDERING — cheap → expensive (Phase 5 Note 2)
=====================================================
32 inventory slots + 1 META = 33 entries. They run in this exact order so
a failed cheap contract short-circuits the expensive DB work:

  Tier 1 (sub-ms, in-process)         — 10 slots : static module self-checks
                                                    (3 of them carry a folded
                                                    v1.2-fixture verdict in
                                                    `details.v1_2_parity`)
  Tier 2 (10–50 ms, single-shot DB)   —  9 slots : sensitive_log schema + RBAC
                                                    (#9 also carries the
                                                    coach_override v1.2 fixture
                                                    verdict in details)
  Tier 3 (50–100 ms, table scans)     —  5 slots : cohort + telemetry tables
                                                    + safe-silence cadence
  Tier 4 (100s ms, joins + scans)     —  8 slots : detector flag activation
  META  (last; sub-ms)                          : audit_check_ordering_cheap_first

DO NOT REORDER FOR "READABILITY". The ordering is a contract.

V1.2 PARITY FIXTURE FOLDING (per inventory §I)
================================================
The 3 `phase3_*_v1_2_fixtures_pass` checks are NOT top-level slots. They
run via `sensitive_bridge_v1_2_parity.run_all_v1_2_parity_checks()` and
their per-contract verdicts fold into the `details.v1_2_parity` of:

  controller          → `pipeline_order_matches_plan_v1_3`
  mandatory_reporting → `mandatory_reporting_trafficking_path_present`
  coach_override      → `coach_handoff_redaction_payload_no_pii`

Parent slot `ok` = parent contract `ok` AND folded v1.2 verdict `ok`.

SHORT-CIRCUIT POLICY
====================
If ANY Tier-1 contract check (other than the v1.2-fold) fails, the Tier-2/3/4
DB checks are reported as `severity="skipped"` with `ok=False` and
`detail="skipped: upstream contract failure"`. The v1.2 fixture runner ALWAYS
executes (independent of v1.3 runtime state) because Tier-1 short-circuits
must not blind us to v1.2 regression.

CHECK ENTRY SHAPE (per Note 1)
==============================
Each entry returned by audit() conforms to:
  {
    "id": str,            # canonical check ID from inventory
    "ok": bool,           # True iff check passed
    "details": dict,      # diagnostic payload (may contain `v1_2_parity` fold)
    "severity": str,      # "info" | "warning" | "error" | "skipped"
  }

The aggregator at the end of audit() rolls up to a single boolean health
verdict consumed by the trust enforcer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nate.sensitive_bridge_auditor")

AUDIT_HOURS = {5, 17, 23}
STAGGER_SECONDS = 300  # firm 300s ceiling per service-health-49-49.mdc + trust-enforcer-architecture.mdc (must complete before Trust Enforcer fires at HH:10 / 600s)

# ---------------------------------------------------------------------------
# Declared check ordering (cheap → expensive). The META check verifies the
# auditor executed them in this exact order. Maintainers: do not reorder.
# ---------------------------------------------------------------------------

_CHECK_ORDER: Tuple[Tuple[str, int], ...] = (
    # Tier 1 — static module self-checks (sub-ms, in-process)
    # Note: 3 of these slots fold a v1.2 fixture verdict into `details`:
    #   • pipeline_order_matches_plan_v1_3 ← controller v1.2 parity
    #   • mandatory_reporting_trafficking_path_present ← reporting v1.2 parity
    #   • (coach_override v1.2 parity folds into Tier-2 #9 below)
    ("pipeline_order_matches_plan_v1_3", 1),
    ("bridge_decision_schema_hash_stable", 1),
    ("redaction_validator_fires_on_overlap", 1),
    ("phase4_no_modifications_to_phase3_modules", 1),
    ("coach_alert_carries_payload_ref", 1),
    ("feature_flag_count_is_16", 1),
    ("phase4_wiring_diff_under_15_lines", 1),
    ("mandatory_reporting_trafficking_path_present", 1),
    ("validator_lexicon_loaded_and_versioned", 1),
    ("immutable_types_includes_sensitive_log", 1),
    # Plan v1.3 Phase 5 Note 1 safeguard #3 — telemetry agent re-enable gate.
    ("auto_disable_reenable_requires_resolved_telemetry", 1),

    # Tier 2 — DB schema integrity (10–50 ms each)
    # Note: coach_handoff_redaction_payload_no_pii folds the coach_override
    # v1.2 fixture verdict into `details.v1_2_parity`.
    ("sensitive_log_table_present", 2),
    ("sensitive_log_immutable_enforced", 2),
    ("user_safety_codewords_no_plaintext_leak", 2),
    ("safe_silence_state_view_present", 2),
    ("crystal_domain_canonical_set", 2),
    ("sensitive_log_retention_default_7yr", 2),
    ("sensitive_log_jurisdiction_trigger_present", 2),
    ("sensitive_log_access_classification_enforced", 2),
    ("coach_handoff_redaction_payload_no_pii", 2),

    # Tier 3 — DB cohort + telemetry (50–100 ms)
    ("sensitive_bridge_enrollment_table_present", 3),
    ("detector_telemetry_table_present", 3),
    ("false_positive_rate_under_5pct_per_gap", 3),
    ("shadow_mode_decision_review_current", 3),
    ("safe_silence_expiry_warning_cadence_observed", 3),

    # Tier 4 — DB feature-flag activation (100s ms; joins + telemetry)
    ("flag_introjection_active", 4),
    ("flag_thalamic_gate_active", 4),
    ("flag_reengagement_active", 4),
    ("flag_arousal_cap_active", 4),
    ("flag_polyvictim_load_active", 4),
    ("flag_active_disclosure_active", 4),
    ("flag_codeword_active", 4),
    ("flag_jurisdiction_compliance_active", 4),
)

_CHECK_IDS_DECLARED: Tuple[str, ...] = tuple(cid for cid, _ in _CHECK_ORDER)
_TIER_1_CONTRACT_IDS = frozenset(cid for cid, t in _CHECK_ORDER if t == 1)
_TOTAL_SLOTS = len(_CHECK_ORDER) + 1  # +1 for META audit_check_ordering_cheap_first


# Map from gap_feature_flags name → telemetry detector_id stored by the
# orchestrator pipeline. Used by Tier-5 flag activation checks.
_FLAG_TO_DETECTOR: Dict[str, Tuple[str, str]] = {
    # check_id → (flag_name, telemetry_detector_id)
    "flag_introjection_active": ("gap_introjection_enabled", "introjection_voice_mirror"),
    "flag_thalamic_gate_active": ("gap_thalamic_gate_enabled", "thalamic_novelty_gate"),
    "flag_reengagement_active": ("gap_reengagement_enabled", "reengagement_pattern"),
    "flag_arousal_cap_active": ("gap_arousal_cap_enabled", "linguistic_arousal_load"),
    "flag_polyvictim_load_active": ("gap_polyvictim_load_enabled", "polyvictim_layers"),
    "flag_active_disclosure_active": (
        "gap_active_disclosure_enabled", "trafficking_disclosure_classifier",
    ),
    "flag_codeword_active": ("gap_codeword_enabled", "user_safety_codewords"),
    "flag_jurisdiction_compliance_active": (
        "gap_jurisdiction_compliance_enabled", "jurisdiction_compliance",
    ),
}


# ---------------------------------------------------------------------------
# Public auditor surface
# ---------------------------------------------------------------------------


class SensitiveBridgeAuditor:
    """Auditor #29 in the trust-enforcer fleet.

    Single class, single audit() method. No scheduling/retry/baseline-write
    logic — that lives in the trust enforcer framework. Auditor returns
    verdicts; framework dispatches.
    """

    def __init__(self, db_pool, notification_system=None, app_state=None):
        self.db_pool = db_pool
        self.notifications = notification_system
        self._app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._sent_windows: set = set()

    # -- lifecycle (matches TokenLabAuditor) --------------------------------

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "SensitiveBridgeAuditor started (3x daily UTC %s, stagger %ds)",
            sorted(AUDIT_HOURS), STAGGER_SECONDS,
        )

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SensitiveBridgeAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(STAGGER_SECONDS)
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                window_key = f"{now.date().isoformat()}_{now.hour}"
                if now.hour in AUDIT_HOURS and window_key not in self._sent_windows:
                    await self._build_and_send(now)
                    self._sent_windows.add(window_key)
                    self._sent_windows = {
                        k for k in self._sent_windows
                        if k.startswith(now.date().isoformat())
                    }
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("SensitiveBridgeAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        result = await self.audit()

        # Email silenced — Trust Enforcer sends consolidated report

        detail_payload = json.dumps({
            "trusted": result["trusted"],
            "total": result["total"],
            "ok": result["ok"],
            "results": [
                {"id": c["id"], "ok": c["ok"], "severity": c["severity"]}
                for c in result["checks"]
            ],
        })
        await self._log_activity(
            "system",
            "sensitive_bridge_audit_sent",
            detail_payload,
            "success" if result["ok"] else "warning",
        )
        logger.info(
            "SensitiveBridgeAuditor: scorecard sent — %d/%d TRUSTED at %s",
            result["trusted"], result["total"], now.isoformat(),
        )

    # -- core audit() -------------------------------------------------------

    async def audit(self) -> Dict[str, Any]:
        """Run all 34 checks in the declared cost-tier order.

        Returns:
          {
            "ok": bool,                      # aggregate health verdict
            "trusted": int,                  # count of ok=True checks
            "total": int,                    # always 34 (33 inventory + 1 meta)
            "checks": List[CheckEntry],      # in execution order
            "ordering_observed": List[str],  # check ids in observed order
            "elapsed_ms": int,               # end-to-end wall time
          }
        """
        t0 = time.monotonic()
        observed_order: List[str] = []
        results: List[Dict[str, Any]] = []

        # Run v1.2 parity FIRST (independent of runtime state). The verdicts
        # fold into parent slots' `details.v1_2_parity` field.
        v1_2_verdicts = self._run_v1_2_parity()

        # ---- Tier 1: in-process module self-checks ----
        tier1 = await self._run_tier1(observed_order, v1_2_verdicts)
        results.extend(tier1)
        tier1_failed = any(
            not c["ok"] for c in tier1 if c["id"] in _TIER_1_CONTRACT_IDS
        )

        # ---- Tier 2: DB schema integrity ----
        if tier1_failed:
            results.extend(self._skip_block(
                ["sensitive_log_table_present",
                 "sensitive_log_immutable_enforced",
                 "user_safety_codewords_no_plaintext_leak",
                 "safe_silence_state_view_present",
                 "crystal_domain_canonical_set",
                 "sensitive_log_retention_default_7yr",
                 "sensitive_log_jurisdiction_trigger_present",
                 "sensitive_log_access_classification_enforced",
                 "coach_handoff_redaction_payload_no_pii"],
                observed_order,
            ))
        else:
            results.extend(await self._run_tier2(observed_order, v1_2_verdicts))

        # ---- Tier 3: cohort + telemetry tables ----
        if tier1_failed:
            results.extend(self._skip_block(
                ["sensitive_bridge_enrollment_table_present",
                 "detector_telemetry_table_present",
                 "false_positive_rate_under_5pct_per_gap",
                 "shadow_mode_decision_review_current",
                 "safe_silence_expiry_warning_cadence_observed"],
                observed_order,
            ))
        else:
            results.extend(await self._run_tier3(observed_order))

        # ---- Tier 4: detector flag activation ----
        if tier1_failed:
            results.extend(self._skip_block(
                list(_FLAG_TO_DETECTOR.keys()),
                observed_order,
            ))
        else:
            results.extend(await self._run_tier4(observed_order))

        # ---- META: ordering self-check (runs last, observes all above) ----
        meta = self._meta_ordering_check(observed_order)
        results.append(meta)

        trusted = sum(1 for c in results if c["ok"])
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return {
            "ok": all(c["ok"] for c in results),
            "trusted": trusted,
            "total": len(results),
            "checks": results,
            "ordering_observed": observed_order,
            "elapsed_ms": elapsed_ms,
        }

    # -- v1.2 parity (folded into parent slots; runs once per audit) --------

    def _run_v1_2_parity(self) -> Dict[str, Dict[str, Any]]:
        """Run the v1.2 fixture suite once. Returned dict is consumed by
        the Tier-1 and Tier-2 builders to fold verdicts into parent slots'
        `details.v1_2_parity`. Never fails the audit on its own — the parent
        slot decides whether to downgrade based on the verdict.
        """
        try:
            from app.services.sensitive_bridge_v1_2_parity import (
                run_all_v1_2_parity_checks,
            )
            return run_all_v1_2_parity_checks()
        except Exception as e:
            logger.warning(
                "SensitiveBridgeAuditor: v1.2 parity runner failed: %s", e,
            )
            return {}

    async def _identity_resolution_bridge_boundary_check(self) -> Dict[str, Any]:
        """DB probe: ``audit_client.hardware_id`` must resolve to ``username``."""
        detail: Dict[str, Any] = {"check_id": "identity_resolution_at_bridge_boundary"}
        if not self.db_pool:
            detail["skipped"] = True
            detail["reason"] = "db_pool_unavailable"
            return {"ok": True, "detail": detail}
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT username, hardware_id FROM users "
                    "WHERE username = 'audit_client' LIMIT 1",
                )
            if not row or not row.get("hardware_id"):
                detail["skipped"] = True
                detail["reason"] = "audit_client_row_missing"
                return {"ok": True, "detail": detail}
            from app.services._identity_resolver import resolve_username as _resolve_uname

            resolved = await _resolve_uname(self.db_pool, str(row["hardware_id"]))
            expected = str(row["username"])
            ok = resolved == expected
            detail.update(
                {
                    "hardware_id_probe": row["hardware_id"],
                    "expected_username": expected,
                    "resolved_username": resolved,
                }
            )
            return {"ok": ok, "detail": detail}
        except Exception as e:
            detail["error"] = repr(e)
            return {"ok": False, "detail": detail}

    # -- tier 1: static module self-checks (sub-ms) -------------------------

    async def _run_tier1(
        self,
        observed: List[str],
        v1_2_verdicts: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Aggregate _auditor_self_check() results from in-process modules."""
        results: List[Dict[str, Any]] = []

        # Pull the orchestrator's self-check (8 keys we care about).
        orch = _safe_call(_import_orch_self_check, default={})
        # Pull mandatory_reporting + linguistic_arousal_load.
        mand = _safe_call(_import_mandatory_reporting_self_check, default={})
        ling = _safe_call(_import_linguistic_arousal_self_check, default={})

        ir_boundary = await self._identity_resolution_bridge_boundary_check()

        controller_v1_2 = v1_2_verdicts.get("controller") or {}
        reporting_v1_2 = v1_2_verdicts.get("mandatory_reporting") or {}

        # Helper to wrap a v1.2 fold into the parent severity/ok decision.
        def _emit(cid: str, parent_ok: bool, parent_severity_when_ok: str,
                  fold: Optional[Dict[str, Any]] = None,
                  source: str = ""):
            details: Dict[str, Any] = {"source": source} if source else {}
            ok = parent_ok
            if fold:
                fold_summary = {
                    "check_id": fold.get("check_id"),
                    "passed": fold.get("passed"),
                    "failed": fold.get("failed"),
                    "total": fold.get("total"),
                    "ok": bool(fold.get("ok", False)),
                    "failures": (fold.get("failures") or [])[:5],
                }
                details["v1_2_parity"] = fold_summary
                ok = ok and fold_summary["ok"]
            results.append(_entry(
                cid, ok=ok, details=details,
                severity=parent_severity_when_ok if ok else "error",
            ))
            observed.append(cid)

        # Emit in EXACT _CHECK_ORDER sequence.

        # Slot 1: pipeline_order_matches_plan_v1_3 ← folds controller v1.2
        _emit(
            "pipeline_order_matches_plan_v1_3",
            parent_ok=(
                bool(orch.get("pipeline_order_matches_plan_v1_3", False))
                and bool(ir_boundary.get("ok", False))
            ),
            parent_severity_when_ok="info",
            fold=controller_v1_2,
            source="sensitive_clinical_bridge._auditor_self_check",
        )
        results[-1]["details"]["identity_resolution_at_bridge_boundary"] = ir_boundary.get(
            "detail", {}
        )

        # Slot 2: bridge_decision_schema_hash_stable
        # Slot 3: redaction_validator_fires_on_overlap
        for cid in (
            "bridge_decision_schema_hash_stable",
            "redaction_validator_fires_on_overlap",
        ):
            ok = bool(orch.get(cid, False))
            results.append(_entry(
                cid, ok=ok,
                details={"source": "sensitive_clinical_bridge._auditor_self_check"},
                severity="info" if ok else "error",
            ))
            observed.append(cid)

        # Slot 4: phase4_no_modifications_to_phase3_modules
        # Fold M215 sensitive_profile_screen_single_entry_point Flutter-source
        # static check into details. The fold pattern matches the v1.2 parity
        # / sole-clinician folds: parent ok flips False if the folded check
        # regresses. In production containers the mobile/ tree is absent and
        # the folded check returns severity="skipped" with ok=True, so it
        # never red-flags production trust — local dev / pre-deploy CI is
        # the authoritative gate for the entry-point invariant.
        phase4_invariant_ok = bool(
            orch.get("phase4_no_modifications_to_phase3_modules",
                     orch.get("no_phase3_module_mutations", False))
        )
        screen_entry = _check_sensitive_profile_screen_single_entry_point()
        phase4_details = {
            "source": "sensitive_clinical_bridge._auditor_self_check",
            "alias": "no_phase3_module_mutations",
            "sensitive_profile_screen_single_entry_point": {
                "check_id": screen_entry["id"],
                "ok": bool(screen_entry["ok"]),
                "severity": screen_entry["severity"],
                "findings": screen_entry["details"],
            },
        }
        # Skipped fold (production container, mobile/ absent) does not flip
        # the parent verdict — only an explicit ok=False with severity=error
        # counts as regression.
        screen_fold_regressed = (
            not screen_entry["ok"]
            and screen_entry["severity"] != "skipped"
        )
        slot4_ok = phase4_invariant_ok and not screen_fold_regressed
        results.append(_entry(
            "phase4_no_modifications_to_phase3_modules",
            ok=slot4_ok,
            details=phase4_details,
            severity="info" if slot4_ok else "error",
        ))
        observed.append("phase4_no_modifications_to_phase3_modules")

        # Slot 5: coach_alert_carries_payload_ref
        # Slot 6: feature_flag_count_is_16
        # Slot 7: phase4_wiring_diff_under_15_lines
        for cid in (
            "coach_alert_carries_payload_ref",
            "feature_flag_count_is_16",
            "phase4_wiring_diff_under_15_lines",
        ):
            ok = bool(orch.get(cid, False))
            results.append(_entry(
                cid, ok=ok,
                details={"source": "sensitive_clinical_bridge._auditor_self_check"},
                severity="info" if ok else "error",
            ))
            observed.append(cid)

        # Slot 8: mandatory_reporting_trafficking_path_present
        # ← folds mandatory_reporting v1.2 parity
        mand_ok = _coerce_bool(
            mand.get("trafficking_enum_value_present", True)
        ) and _coerce_bool(
            mand.get("trafficking_patterns_in_unified_registry", True)
        )
        _emit(
            "mandatory_reporting_trafficking_path_present",
            parent_ok=mand_ok,
            parent_severity_when_ok="info",
            fold=reporting_v1_2,
            source="governance.mandatory_reporting._auditor_self_check",
        )

        # validator_lexicon_loaded_and_versioned
        # Phase 4 stub may report awaiting_clinician_authoring → WARNING (not error)
        ling_loaded = _coerce_bool(ling.get("registry_loads", True))
        ling_versioned = _coerce_bool(ling.get("version_field_present", True))
        ling_ok = ling_loaded and ling_versioned
        ling_severity = "info" if ling_ok else (
            "warning" if ling.get("clinician_authoring_pending") else "error"
        )
        results.append(_entry(
            "validator_lexicon_loaded_and_versioned",
            ok=ling_ok,
            details={"source": "linguistic_arousal_load._auditor_self_check",
                     "raw": _summarize(ling)},
            severity=ling_severity,
        ))
        observed.append("validator_lexicon_loaded_and_versioned")

        # immutable_types_includes_sensitive_log — static grep against
        # db_maintenance_agent.IMMUTABLE_TYPES.
        imm_ok = False
        imm_detail: Dict[str, Any] = {}
        try:
            from app.services.db_maintenance_agent import IMMUTABLE_TYPES
            imm_detail["immutable_types"] = list(IMMUTABLE_TYPES)
            imm_ok = "sensitive_bridge_log_event" in IMMUTABLE_TYPES \
                or "sensitive_clinical_bridge_event" in IMMUTABLE_TYPES \
                or "sensitive_log" in IMMUTABLE_TYPES
            if not imm_ok:
                imm_detail["expected_one_of"] = [
                    "sensitive_bridge_log_event",
                    "sensitive_clinical_bridge_event",
                    "sensitive_log",
                ]
        except Exception as e:
            imm_detail["error"] = repr(e)
        results.append(_entry(
            "immutable_types_includes_sensitive_log",
            ok=imm_ok,
            details=imm_detail,
            # Phase 6 will land the migration; treat absence as warning until
            # then so shadow-mode launch isn't blocked.
            severity="info" if imm_ok else "warning",
        ))
        observed.append("immutable_types_includes_sensitive_log")

        # Slot 11: auto_disable_reenable_requires_resolved_telemetry
        # Plan v1.3 Phase 5 Note 1 safeguard #3 — verifies the telemetry
        # agent's resolved-telemetry gate primitive is intact and the agent
        # ships ARMED-BUT-NEUTRAL (paused=True default).
        tel = _safe_call(_import_telemetry_agent_self_check, default={})
        tel_ok = bool(tel.get("auto_disable_reenable_requires_resolved_telemetry", False))
        results.append(_entry(
            "auto_disable_reenable_requires_resolved_telemetry",
            ok=tel_ok,
            details={
                "source": "sensitive_bridge_telemetry_agent._auditor_self_check",
                "raw": _summarize(tel, max_keys=8),
            },
            severity="info" if tel_ok else "error",
        ))
        observed.append("auto_disable_reenable_requires_resolved_telemetry")

        return results

    # -- tier 2: DB schema integrity ----------------------------------------

    async def _run_tier2(
        self, observed: List[str], v1_2_verdicts: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        if not self.db_pool:
            return self._skip_block(
                ["sensitive_log_table_present",
                 "sensitive_log_immutable_enforced",
                 "user_safety_codewords_no_plaintext_leak",
                 "safe_silence_state_view_present",
                 "crystal_domain_canonical_set",
                 "sensitive_log_retention_default_7yr",
                 "sensitive_log_jurisdiction_trigger_present",
                 "sensitive_log_access_classification_enforced",
                 "coach_handoff_redaction_payload_no_pii"],
                observed,
                reason="db_pool_unavailable",
            )

        async with self.db_pool.acquire() as conn:
            results.append(await _check_table_present(
                conn, "sensitive_log_table_present",
                table_candidates=("sensitive_bridge_log",),
            ))
            observed.append("sensitive_log_table_present")

            results.append(await _check_immutable_trigger(
                conn, "sensitive_log_immutable_enforced",
                table="sensitive_bridge_log",
            ))
            observed.append("sensitive_log_immutable_enforced")

            results.append(await _check_codewords_no_plaintext(
                conn, "user_safety_codewords_no_plaintext_leak",
            ))
            observed.append("user_safety_codewords_no_plaintext_leak")

            silence_view_entry = await _check_view_present(
                conn, "safe_silence_state_view_present",
                view_candidates=("safe_silence_state_v", "v_safe_silence_state"),
            )
            # Fold migration-214 sole-clinician session-separation static
            # check into the parent slot. No new top-level entry is added —
            # parent ``ok`` flips False if the static contract regresses.
            sc_sep = _check_sole_clinician_session_separation_enforced()
            silence_view_entry["details"]["sole_clinician_session_separation"] = {
                "check_id": sc_sep["id"],
                "ok": bool(sc_sep["ok"]),
                "findings": sc_sep["details"],
            }
            if not sc_sep["ok"]:
                silence_view_entry["ok"] = False
                silence_view_entry["severity"] = "error"
            revoke_c = _check_safe_silence_active_revoke_contracts()
            silence_view_entry["details"]["safe_silence_active_revoke_contracts"] = {
                "check_id": revoke_c["id"],
                "ok": bool(revoke_c["ok"]),
                "findings": revoke_c["details"],
            }
            if not revoke_c["ok"]:
                silence_view_entry["ok"] = False
                silence_view_entry["severity"] = "error"
            results.append(silence_view_entry)
            observed.append("safe_silence_state_view_present")

            results.append(await _check_crystal_domain_canonical(
                conn, "crystal_domain_canonical_set",
            ))
            observed.append("crystal_domain_canonical_set")

            results.append(await _check_log_retention_7yr(
                conn, "sensitive_log_retention_default_7yr",
            ))
            observed.append("sensitive_log_retention_default_7yr")

            results.append(await _check_jurisdiction_trigger(
                conn, "sensitive_log_jurisdiction_trigger_present",
            ))
            observed.append("sensitive_log_jurisdiction_trigger_present")

            results.append(await _check_access_classification_column(
                conn, "sensitive_log_access_classification_enforced",
            ))
            observed.append("sensitive_log_access_classification_enforced")

            handoff_entry = await _check_handoff_redaction_no_pii(
                conn, "coach_handoff_redaction_payload_no_pii",
            )
            # Fold coach_override v1.2 fixture verdict into details
            cov = v1_2_verdicts.get("coach_override") or {}
            if cov:
                fold_summary = {
                    "check_id": cov.get("check_id"),
                    "passed": cov.get("passed"),
                    "failed": cov.get("failed"),
                    "total": cov.get("total"),
                    "ok": bool(cov.get("ok", False)),
                    "failures": (cov.get("failures") or [])[:5],
                }
                handoff_entry["details"]["v1_2_parity"] = fold_summary
                if not fold_summary["ok"]:
                    handoff_entry["ok"] = False
                    handoff_entry["severity"] = "error"
            results.append(handoff_entry)
            observed.append("coach_handoff_redaction_payload_no_pii")

        return results

    # -- tier 3: cohort + telemetry -----------------------------------------

    async def _run_tier3(self, observed: List[str]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        if not self.db_pool:
            return self._skip_block(
                ["sensitive_bridge_enrollment_table_present",
                 "detector_telemetry_table_present",
                 "false_positive_rate_under_5pct_per_gap",
                 "shadow_mode_decision_review_current",
                 "safe_silence_expiry_warning_cadence_observed"],
                observed, reason="db_pool_unavailable",
            )

        async with self.db_pool.acquire() as conn:
            enroll_table_entry = await _check_table_present(
                conn, "sensitive_bridge_enrollment_table_present",
                table_candidates=("sensitive_bridge_enrollment",),
            )
            # Fold M215+M216 Path-C coach-initiated enrollment static
            # contracts into details. Same pattern as the v1.2 parity /
            # sole-clinician folds above: parent ok flips False if any
            # folded check regresses. All four are static source scans of
            # backend/app/routers/sensitive_profile_api.py (shipped in the
            # backend image) and migrations/216_coach_initiated_enrollment.sql.
            enroll_folds = {
                "consent_required": _check_enrollment_endpoint_requires_consent_confirmed(),
                "minor_guardian_consent": _check_enrollment_endpoint_blocks_minor_without_guardian_consent(),
                "audit_row_emitted": _check_enrollment_creates_audit_row(),
                "coach_authorization": _check_enrollment_endpoint_requires_coach_authorization(),
            }
            enroll_table_entry["details"]["coach_initiated_enrollment"] = {
                fold_key: {
                    "check_id": entry["id"],
                    "ok": bool(entry["ok"]),
                    "severity": entry["severity"],
                    "findings": entry["details"],
                }
                for fold_key, entry in enroll_folds.items()
            }
            enroll_fold_regressed = any(
                not entry["ok"] and entry["severity"] != "skipped"
                for entry in enroll_folds.values()
            )
            if enroll_fold_regressed:
                enroll_table_entry["ok"] = False
                enroll_table_entry["severity"] = "error"
            results.append(enroll_table_entry)
            observed.append("sensitive_bridge_enrollment_table_present")

            results.append(await _check_table_present(
                conn, "detector_telemetry_table_present",
                table_candidates=("detector_telemetry",),
            ))
            observed.append("detector_telemetry_table_present")

            results.append(await _check_false_positive_rate(
                conn, "false_positive_rate_under_5pct_per_gap",
            ))
            observed.append("false_positive_rate_under_5pct_per_gap")

            shadow_review_entry = await _check_shadow_mode_review_current(
                conn, "shadow_mode_decision_review_current",
            )
            # Fold migration-214 sole-clinician 48h reflection-delay static
            # check into the parent slot. Same pattern as Tier-2 fold above.
            sc_delay = _check_sole_clinician_reflection_delay_enforced()
            shadow_review_entry["details"]["sole_clinician_reflection_delay"] = {
                "check_id": sc_delay["id"],
                "ok": bool(sc_delay["ok"]),
                "findings": sc_delay["details"],
            }
            if not sc_delay["ok"]:
                shadow_review_entry["ok"] = False
                shadow_review_entry["severity"] = "error"
            results.append(shadow_review_entry)
            observed.append("shadow_mode_decision_review_current")

            results.append(await _check_safe_silence_warning_cadence(
                conn, "safe_silence_expiry_warning_cadence_observed",
            ))
            observed.append("safe_silence_expiry_warning_cadence_observed")

        return results

    # -- tier 4: detector flag activation -----------------------------------

    async def _run_tier4(self, observed: List[str]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        if not self.db_pool:
            return self._skip_block(
                list(_FLAG_TO_DETECTOR.keys()),
                observed, reason="db_pool_unavailable",
            )

        async with self.db_pool.acquire() as conn:
            for cid, (flag_name, detector_id) in _FLAG_TO_DETECTOR.items():
                results.append(await _check_flag_activation(
                    conn, cid, flag_name, detector_id,
                ))
                observed.append(cid)
        return results

    # -- META: ordering self-check (runs last) ------------------------------

    def _meta_ordering_check(self, observed: List[str]) -> Dict[str, Any]:
        """Verify execution order matches `_CHECK_ORDER`.

        This is "the auditor auditing itself" (Phase 5 Note 2). Sub-millisecond.
        Catches any future maintainer who reorders for "readability".
        """
        # Build the expected order, accounting for skipped blocks (skipped
        # checks still get their slot in `observed`).
        expected = list(_CHECK_IDS_DECLARED)
        ok = (observed == expected)
        details: Dict[str, Any] = {
            "expected_count": len(expected),
            "observed_count": len(observed),
        }
        if not ok:
            # Locate first divergence for diagnostic clarity.
            first_diff = next(
                (i for i, (e, o) in enumerate(zip(expected, observed)) if e != o),
                min(len(expected), len(observed)),
            )
            details["first_divergence_index"] = first_diff
            details["expected_at_divergence"] = (
                expected[first_diff] if first_diff < len(expected) else None
            )
            details["observed_at_divergence"] = (
                observed[first_diff] if first_diff < len(observed) else None
            )
        return _entry(
            "audit_check_ordering_cheap_first",
            ok=ok,
            details=details,
            severity="info" if ok else "error",
        )

    # -- helpers ------------------------------------------------------------

    def _skip_block(
        self,
        check_ids: List[str],
        observed: List[str],
        reason: str = "skipped: upstream contract failure",
    ) -> List[Dict[str, Any]]:
        out = []
        for cid in check_ids:
            out.append(_entry(
                cid, ok=False,
                details={"reason": reason},
                severity="skipped",
            ))
            observed.append(cid)
        return out

    async def _log_activity(
        self, platform: str, activity_type: str, content: str,
        severity: str = "info",
    ):
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO skyeye_activity (platform, type, content, severity, created_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    """,
                    platform, activity_type, content, severity,
                )
        except Exception as e:
            logger.warning(
                "SensitiveBridgeAuditor: activity log write failed: %s", e,
            )


# ---------------------------------------------------------------------------
# Module-level helpers (kept outside the class to ease unit testing)
# ---------------------------------------------------------------------------


def _entry(cid: str, *, ok: bool, details: Dict[str, Any], severity: str) -> Dict[str, Any]:
    return {"id": cid, "ok": bool(ok), "details": details or {}, "severity": severity}


def _coerce_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, dict):
        # Some module self-checks return nested dicts; treat all-truthy as ok.
        return all(bool(x) for x in v.values())
    return bool(v)


def _summarize(d: Dict[str, Any], max_keys: int = 6) -> Dict[str, Any]:
    """Truncate a self-check dict to the most useful first N keys for logs."""
    if not isinstance(d, dict):
        return {"value": str(d)[:80]}
    return dict(list(d.items())[:max_keys])


def _safe_call(fn, *, default):
    try:
        return fn()
    except Exception as e:
        logger.warning("SensitiveBridgeAuditor: helper %s failed: %s", fn.__name__, e)
        return default


def _import_orch_self_check() -> Dict[str, Any]:
    from app.services.sensitive_clinical_bridge import _auditor_self_check  # type: ignore
    return _auditor_self_check()


def _import_mandatory_reporting_self_check() -> Dict[str, Any]:
    from app.services.governance.mandatory_reporting import _auditor_self_check  # type: ignore
    return _auditor_self_check()


def _import_linguistic_arousal_self_check() -> Dict[str, Any]:
    from app.services.linguistic_arousal_load import _auditor_self_check  # type: ignore
    return _auditor_self_check()


def _import_telemetry_agent_self_check() -> Dict[str, Any]:
    from app.services.sensitive_bridge_telemetry_agent import _auditor_self_check  # type: ignore
    return _auditor_self_check()


# ---- DB check primitives ---------------------------------------------------


async def _check_table_present(
    conn, cid: str, *, table_candidates: Tuple[str, ...],
) -> Dict[str, Any]:
    """Return TRUSTED/info if any candidate table exists; else WARNING.

    Phase 6 migrations land these tables. Pre-migration the check is
    informational, not a clinical-safety failure.
    """
    found: List[str] = []
    for tbl in table_candidates:
        row = await conn.fetchrow(
            "SELECT 1 FROM information_schema.tables WHERE table_name = $1",
            tbl,
        )
        if row is not None:
            found.append(tbl)
    ok = bool(found)
    return _entry(
        cid, ok=ok,
        details={"checked": list(table_candidates), "found": found},
        severity="info" if ok else "warning",
    )


async def _check_view_present(
    conn, cid: str, *, view_candidates: Tuple[str, ...],
) -> Dict[str, Any]:
    found: List[str] = []
    for v in view_candidates:
        row = await conn.fetchrow(
            "SELECT 1 FROM information_schema.views WHERE table_name = $1", v,
        )
        if row is not None:
            found.append(v)
    ok = bool(found)
    return _entry(
        cid, ok=ok,
        details={"checked": list(view_candidates), "found": found},
        severity="info" if ok else "warning",
    )


# ---------------------------------------------------------------------------
# Sole-clinician (migration 214) folded checks — static source scans
# ---------------------------------------------------------------------------
# Both checks run as regex scans over the relevant router source. They are
# folded into the verdicts of two existing _CHECK_ORDER slots (no new top-
# level entries), keeping _TOTAL_SLOTS at 34. The framework uses the
# `details.sole_clinician_*` substructure for visibility, and the parent's
# `ok` flips to False if the fold fails — same pattern the v1.2 parity
# fixtures already use.

import re as _re

# Anchor the static-source scan paths to THIS module's location so the check
# works regardless of CWD. ``__file__`` here is .../app/services/<this>.py;
# the routers live at .../app/routers/. Inside the production container that
# resolves to /app/app/routers/...; on a developer checkout it resolves to
# .../backend/app/routers/...
_SOLE_LEAD_API_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "routers", "sensitive_profile_api.py",
))
_SOLE_LEAD_TELEMETRY_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "routers", "sensitive_bridge_telemetry_api.py",
))
_CHECKIN_AGENT_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "nate_checkin_agent.py",
))

# Path-C enrollment endpoint shares a router file with the rest of the
# sensitive_profile contract. Reuse the same anchored path used by the
# session-separation check above.
_ENROLLMENT_API_PATH = _SOLE_LEAD_API_PATH

# Flutter source tree — used by sensitive_profile_screen_single_entry_point.
# In a developer checkout this resolves to .../mobile/lib; in the production
# Docker image the mobile/ tree is NOT bind-mounted into nate_backend, so the
# check returns ok=True with severity="skipped" and a flutter_source_tree
# diagnostic when the directory is absent. The local dev run is the
# authoritative gate; production is a soft no-op so we never red-flag a
# missing harness on a host that cannot see the Flutter code.
_FLUTTER_LIB_CANDIDATES: Tuple[str, ...] = (
    os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "mobile", "lib",
    )),
    os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "mobile", "lib",
    )),
    "/opt/clinical-sovereignty-lab/mobile/lib",
)


def _resolve_flutter_lib_root() -> Optional[str]:
    for candidate in _FLUTTER_LIB_CANDIDATES:
        if os.path.isdir(candidate):
            return candidate
    return None


def _check_sole_clinician_session_separation_enforced() -> Dict[str, Any]:
    """Verify the safe_silence approve flow still enforces session separation
    when the proposer is ``sole_lead``.

    Folds into ``safe_silence_state_view_present`` (Tier 2). The check is
    deliberately a static source scan — runtime exercise would require
    standing up two admin sessions per audit cycle, which is too expensive
    for the cheap-first ordering. The runtime contract is enforced by the
    endpoint code; this check guards against regression.

    Pass criteria (all required):
      • module-level constant ``CLIN_AUTH_SOLE_LEAD = "sole_lead"`` present
      • ``_lookup_clinician_authorization_type`` symbol present
      • ``hmac.compare_digest(proposer_token_hash, approver_token_hash)``
        present (the universal session-separation check)
      • the comment ``sole_clinician_session_separation_enforced`` referenced
        in the source so future maintainers see this rule exists
    """
    cid = "sole_clinician_session_separation_enforced"
    try:
        with open(_SOLE_LEAD_API_PATH, "r", encoding="utf-8") as fh:
            src = fh.read()
    except Exception as e:
        return {
            "id": cid, "ok": False, "severity": "warning",
            "details": {"error": repr(e)[:120],
                        "path": _SOLE_LEAD_API_PATH},
        }
    has_const = 'CLIN_AUTH_SOLE_LEAD = "sole_lead"' in src
    has_lookup = "_lookup_clinician_authorization_type" in src
    has_hmac = bool(_re.search(
        r"hmac\.compare_digest\(\s*proposer_token_hash\s*,\s*approver_token_hash\s*\)",
        src,
    ))
    has_audit_marker = "sole_clinician_session_separation_enforced" in src
    findings = {
        "has_sole_lead_constant": has_const,
        "has_authorization_lookup": has_lookup,
        "has_session_hash_compare": has_hmac,
        "has_audit_marker_comment": has_audit_marker,
        "scanned_path": _SOLE_LEAD_API_PATH,
    }
    ok = all(findings[k] for k in (
        "has_sole_lead_constant",
        "has_authorization_lookup",
        "has_session_hash_compare",
        "has_audit_marker_comment",
    ))
    return {
        "id": cid, "ok": ok,
        "severity": "info" if ok else "error",
        "details": findings,
    }


def _check_safe_silence_active_revoke_contracts() -> Dict[str, Any]:
    """Priority 2a static contracts folded into ``safe_silence_state_view_present``.

    Three named sub-checks (runtime exercised by fixtures / ops drills):
      • ``safe_silence_active_revoke_admin_only``
      • ``safe_silence_active_revoke_sole_lead_session_separation``
      • ``safe_silence_revoke_emits_welcome_back_trigger``
    """
    cid = "safe_silence_active_revoke_contracts"
    details: Dict[str, Any] = {"api_path": _SOLE_LEAD_API_PATH}
    try:
        with open(_SOLE_LEAD_API_PATH, "r", encoding="utf-8") as fh:
            api = fh.read()
        with open(_CHECKIN_AGENT_PATH, "r", encoding="utf-8") as fh:
            agent = fh.read()
    except Exception as e:
        return {
            "id": cid,
            "ok": False,
            "severity": "warning",
            "details": {**details, "error": repr(e)[:160]},
        }

    admin_only = (
        "admin_required_for_active_revocation" in api
        and "no_active_or_pending_state" in api
        and "safe_silence_active_revoked" in api
    )
    sole_lead_sep = (
        "gate_proposer_token_hash" in api
        and "gate_approver_token_hash" in api
        and "revoker_hash" in api
        and "manual_admin_revocation" in api
        and _re.search(
            r"hmac\.compare_digest\(\s*revoker_hash\s*,",
            api,
        )
        is not None
    )
    welcome_trigger = (
        "manual_admin_revocation" in agent
        and "safe_silence_active_revoked" in agent
        and "welcome_back_source" in agent
        and "manual_revoke_welcome_attempts" in agent
    )

    details.update({
        "safe_silence_active_revoke_admin_only": admin_only,
        "safe_silence_active_revoke_sole_lead_session_separation": sole_lead_sep,
        "safe_silence_revoke_emits_welcome_back_trigger": welcome_trigger,
        "checkin_path": _CHECKIN_AGENT_PATH,
    })
    ok = admin_only and sole_lead_sep and welcome_trigger
    return {
        "id": cid,
        "ok": ok,
        "severity": "info" if ok else "error",
        "details": details,
    }


def _check_sole_clinician_reflection_delay_enforced() -> Dict[str, Any]:
    """Verify the detector-promotion endpoint enforces a 48h reflection delay
    when the actor is ``sole_lead``.

    Folds into ``shadow_mode_decision_review_current`` (Tier 3). Static
    source scan: runtime exercise would require seeding telemetry rows
    across a 48h window every audit cycle.

    Pass criteria (all required):
      • ``SOLE_CLINICIAN_REFLECTION_DELAY_HOURS = 48`` constant present
      • ``_lookup_authorization_type`` helper present
      • ``timedelta(hours=SOLE_CLINICIAN_REFLECTION_DELAY_HOURS)`` literal
        present (the actual server-side delta)
      • 409 with reason ``sole_clinician_reflection_delay_unmet`` present
    """
    cid = "sole_clinician_reflection_delay_enforced"
    try:
        with open(_SOLE_LEAD_TELEMETRY_PATH, "r", encoding="utf-8") as fh:
            src = fh.read()
    except Exception as e:
        return {
            "id": cid, "ok": False, "severity": "warning",
            "details": {"error": repr(e)[:120],
                        "path": _SOLE_LEAD_TELEMETRY_PATH},
        }
    has_const = "SOLE_CLINICIAN_REFLECTION_DELAY_HOURS = 48" in src
    has_lookup = "_lookup_authorization_type" in src
    has_delta = "timedelta(hours=SOLE_CLINICIAN_REFLECTION_DELAY_HOURS)" in src
    has_reason = "sole_clinician_reflection_delay_unmet" in src
    findings = {
        "has_delay_constant_48h": has_const,
        "has_authorization_lookup": has_lookup,
        "has_server_side_timedelta": has_delta,
        "has_409_reason_string": has_reason,
        "scanned_path": _SOLE_LEAD_TELEMETRY_PATH,
    }
    ok = all(findings.values()) and findings["scanned_path"] is not None
    # `scanned_path` is always truthy; recompute purely on contract bools:
    ok = all(findings[k] for k in (
        "has_delay_constant_48h",
        "has_authorization_lookup",
        "has_server_side_timedelta",
        "has_409_reason_string",
    ))
    return {
        "id": cid, "ok": ok,
        "severity": "info" if ok else "error",
        "details": findings,
    }


# ---------------------------------------------------------------------------
# Path-C (M215+M216) coach-initiated enrollment static contracts.
#
# These five checks fold into existing slots — no new top-level inventory
# entries, no trust_baseline expected_count change. The fold pattern matches
# the v1.2 parity / sole-clinician folds above:
#
#   • sensitive_profile_screen_single_entry_point
#       → folds into Tier-1 phase4_no_modifications_to_phase3_modules
#   • enrollment_endpoint_requires_consent_confirmed
#   • enrollment_endpoint_blocks_minor_without_guardian_consent
#   • enrollment_creates_audit_row
#   • enrollment_endpoint_requires_coach_authorization
#       → all four fold into Tier-3 sensitive_bridge_enrollment_table_present
#
# All checks are STATIC source scans — runtime exercise would require seeding
# enrollment rows + spinning real Flutter clients per audit cycle, which is
# too expensive for the cheap-first ordering. Runtime contracts are enforced
# by the endpoint code itself; these checks guard against silent regression.
# ---------------------------------------------------------------------------


def _check_sensitive_profile_screen_single_entry_point() -> Dict[str, Any]:
    """Static Flutter source scan: there must be exactly two production
    entry points to ``SensitiveClinicalProfileScreen``:

      1. ``mobile/lib/screens/inspection/sensitive_profile_inspection_harness.dart``
         — debug-only, kDebugMode-gated in ``main.dart``.
      2. ``mobile/lib/updated_screens.dart`` — Coach Command Briefings tab,
         "View Brief" modal "Sensitive Profile" pill (Path-C entry point).

    Any third caller is a contract violation and must be removed before
    merge. The harness must remain reachable only when ``kDebugMode == true``
    so release bundles dead-strip the harness widget tree entirely.

    In the production Docker image the ``mobile/`` tree is not bind-mounted
    into ``nate_backend``, so the check returns ``ok=True`` with severity
    ``"skipped"`` and ``details.flutter_source_tree="missing"``. The local
    dev run / pre-deploy CI pass is the authoritative gate.
    """
    cid = "sensitive_profile_screen_single_entry_point"
    flutter_root = _resolve_flutter_lib_root()
    if not flutter_root:
        return {
            "id": cid, "ok": True, "severity": "skipped",
            "details": {
                "flutter_source_tree": "missing",
                "candidates": list(_FLUTTER_LIB_CANDIDATES),
                "note": "production container does not bind-mount mobile/ — local dev / CI is the gate",
            },
        }

    # Walk mobile/lib for SensitiveClinicalProfileScreen( call sites.
    callsites: List[str] = []
    main_dart_path: Optional[str] = None
    for dirpath, _dirs, files in os.walk(flutter_root):
        for fname in files:
            if not fname.endswith(".dart"):
                continue
            full = os.path.join(dirpath, fname)
            try:
                with open(full, "r", encoding="utf-8") as fh:
                    contents = fh.read()
            except Exception:
                continue
            rel = os.path.relpath(full, flutter_root)
            if rel == "main.dart":
                main_dart_path = full
            # Skip the file that DECLARES the class — that's where the
            # constructor lives, not where it's invoked. The class is
            # defined in exactly one place; if more than one file declares
            # it, that's a separate (worse) regression we'll still fail on.
            if "class SensitiveClinicalProfileScreen" in contents:
                continue
            # Match constructor invocations.
            for _m in _re.finditer(r"SensitiveClinicalProfileScreen\(", contents):
                callsites.append(rel)

    expected_paths = {
        "screens/inspection/sensitive_profile_inspection_harness.dart",
        "updated_screens.dart",
    }
    observed_paths = set(callsites)
    extra_callers = sorted(observed_paths - expected_paths)
    missing_callers = sorted(expected_paths - observed_paths)

    # Path-C three-state pill: enroll_available must navigate (not be ElevatedButton-null).
    pill_contract_ok = True
    pill_contract_notes: List[str] = []
    us_rel = "updated_screens.dart"
    us_full = os.path.join(flutter_root, us_rel)
    try:
        with open(us_full, "r", encoding="utf-8") as fh:
            us_src = fh.read()
        _pill_i = us_src.find("Widget _buildSensitiveProfilePill")
        _pill_j = us_src.find("Future<void> _openSensitiveProfile", _pill_i + 1)
        pill_blob = us_src[_pill_i:_pill_j] if _pill_i != -1 and _pill_j != -1 else ""
        if not pill_blob:
            pill_contract_ok = False
            pill_contract_notes.append("pill_blob_missing")
        else:
            if "enroll_available" not in pill_blob:
                pill_contract_ok = False
                pill_contract_notes.append("missing_enroll_available_state")
            if "_openSensitiveProfile" not in pill_blob or "onPressed:" not in pill_blob:
                pill_contract_ok = False
                pill_contract_notes.append("missing_onPressed_open_navigation")
            if "onPressed: isActive" in pill_blob:
                pill_contract_ok = False
                pill_contract_notes.append(
                    "regression_guard:onPressed_must_not_be_isActive_only"
                )
    except Exception as _pill_exc:
        pill_contract_ok = False
        pill_contract_notes.append(repr(_pill_exc)[:120])

    # Verify the harness path is gated by kDebugMode in main.dart.
    has_debug_gate = False
    main_dart_scan_error: Optional[str] = None
    if main_dart_path:
        try:
            with open(main_dart_path, "r", encoding="utf-8") as fh:
                main_src = fh.read()
            # Both pieces required: kDebugMode guard AND harness import.
            has_debug_gate = (
                "if (kDebugMode)" in main_src
                and "sensitive_profile_inspection_harness.dart" in main_src
                and "SensitiveProfileInspectionHarness" in main_src
            )
        except Exception as e:
            main_dart_scan_error = repr(e)[:120]

    ok = (
        not extra_callers
        and not missing_callers
        and has_debug_gate
        and main_dart_scan_error is None
        and pill_contract_ok
    )
    return {
        "id": cid, "ok": ok,
        "severity": "info" if ok else "error",
        "details": {
            "flutter_root": flutter_root,
            "callsite_count": len(callsites),
            "callsites": sorted(set(callsites)),
            "expected_paths": sorted(expected_paths),
            "extra_callers": extra_callers,
            "missing_callers": missing_callers,
            "harness_kdebugmode_gate_present": has_debug_gate,
            "main_dart_scan_error": main_dart_scan_error,
            "pill_three_state_contract_ok": pill_contract_ok,
            "pill_three_state_contract_notes": pill_contract_notes,
        },
    }


def _check_enrollment_endpoint_requires_consent_confirmed() -> Dict[str, Any]:
    """Static scan of ``sensitive_profile_api.py``: the coach-initiated
    enrollment endpoint must raise 422 ``consent_required`` when
    ``informed_consent_confirmed`` is False.

    Pass criteria (all required):
      • ``CoachInitiatedEnrollment`` request model present
      • ``informed_consent_confirmed`` field referenced in validation flow
      • ``consent_required`` reason string raised in HTTPException detail
    """
    cid = "enrollment_endpoint_requires_consent_confirmed"
    try:
        with open(_ENROLLMENT_API_PATH, "r", encoding="utf-8") as fh:
            src = fh.read()
    except Exception as e:
        return {
            "id": cid, "ok": False, "severity": "warning",
            "details": {"error": repr(e)[:120], "path": _ENROLLMENT_API_PATH},
        }
    has_model = "class CoachInitiatedEnrollment" in src
    has_field = "informed_consent_confirmed" in src
    # Look for the 422 reason string in proximity to a not-true check on the
    # informed_consent_confirmed field.
    has_reason = bool(_re.search(
        r'"consent_required"',
        src,
    ))
    has_reason_paired = bool(_re.search(
        r"informed_consent_confirmed[\s\S]{0,200}consent_required",
        src,
    )) or bool(_re.search(
        r"consent_required[\s\S]{0,200}informed_consent_confirmed",
        src,
    ))
    findings = {
        "has_request_model": has_model,
        "has_consent_field": has_field,
        "has_consent_required_reason": has_reason,
        "consent_field_paired_with_reason": has_reason_paired,
        "scanned_path": _ENROLLMENT_API_PATH,
    }
    ok = all(findings[k] for k in (
        "has_request_model",
        "has_consent_field",
        "has_consent_required_reason",
        "consent_field_paired_with_reason",
    ))
    return {
        "id": cid, "ok": ok,
        "severity": "info" if ok else "error",
        "details": findings,
    }


def _check_enrollment_endpoint_blocks_minor_without_guardian_consent() -> Dict[str, Any]:
    """Static scan: minor / transitioning-youth enrollment must require
    guardian dual-approval and return 409 ``requires_guardian_consent``
    when the consent row is missing.

    Pass criteria (all required):
      • ``POPULATION_TYPES_REQUIRING_GUARDIAN_CONSENT`` constant present
      • ``minor_survivor`` and ``transitioning_youth_16_to_21`` listed
      • ``guardian_dual_approval_on_file`` lookup present
      • 409 with reason ``requires_guardian_consent`` raised
    """
    cid = "enrollment_endpoint_blocks_minor_without_guardian_consent"
    try:
        with open(_ENROLLMENT_API_PATH, "r", encoding="utf-8") as fh:
            src = fh.read()
    except Exception as e:
        return {
            "id": cid, "ok": False, "severity": "warning",
            "details": {"error": repr(e)[:120], "path": _ENROLLMENT_API_PATH},
        }
    has_constant = "POPULATION_TYPES_REQUIRING_GUARDIAN_CONSENT" in src
    has_minor = '"minor_survivor"' in src
    has_youth = '"transitioning_youth_16_to_21"' in src
    has_guardian_lookup = "guardian_dual_approval_on_file" in src
    has_reason = '"requires_guardian_consent"' in src
    findings = {
        "has_population_constant": has_constant,
        "lists_minor_survivor": has_minor,
        "lists_transitioning_youth": has_youth,
        "has_guardian_consent_lookup": has_guardian_lookup,
        "has_409_reason_string": has_reason,
        "scanned_path": _ENROLLMENT_API_PATH,
    }
    ok = all(findings[k] for k in (
        "has_population_constant",
        "lists_minor_survivor",
        "lists_transitioning_youth",
        "has_guardian_consent_lookup",
        "has_409_reason_string",
    ))
    return {
        "id": cid, "ok": ok,
        "severity": "info" if ok else "error",
        "details": findings,
    }


def _check_enrollment_creates_audit_row() -> Dict[str, Any]:
    """Static scan: a successful enrollment must emit an ``enrollment_created``
    audit row to ``sensitive_bridge_log`` with ``enrolled_by`` and
    ``cohort_label`` recorded in the payload.

    Pass criteria (all required):
      • ``EVT_ENROLLMENT_CREATED = "enrollment_created"`` constant present
      • ``EVT_ENROLLMENT_CREATED`` referenced inside the enrollment endpoint
      • ``enrolled_by`` / ``cohort_label`` keys named in the audit payload
      • Migration 216 ``CHECK`` constraint widened to allow the new event
        (verified by grep against the migration file shipped in this image)
    """
    cid = "enrollment_creates_audit_row"
    try:
        with open(_ENROLLMENT_API_PATH, "r", encoding="utf-8") as fh:
            src = fh.read()
    except Exception as e:
        return {
            "id": cid, "ok": False, "severity": "warning",
            "details": {"error": repr(e)[:120], "path": _ENROLLMENT_API_PATH},
        }
    has_const = 'EVT_ENROLLMENT_CREATED = "enrollment_created"' in src
    has_const_used = src.count("EVT_ENROLLMENT_CREATED") >= 2
    has_payload_keys = (
        '"enrolled_by"' in src
        and '"cohort_label"' in src
    )

    # Migration 216 CHECK widening — co-located in backend/migrations.
    migration_path = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "migrations", "216_coach_initiated_enrollment.sql",
    ))
    migration_ok = False
    migration_error: Optional[str] = None
    try:
        with open(migration_path, "r", encoding="utf-8") as fh:
            mig = fh.read()
        migration_ok = (
            "enrollment_created" in mig
            and "sensitive_bridge_log" in mig
            and "event_type" in mig
        )
    except Exception as e:
        migration_error = repr(e)[:120]

    findings = {
        "has_event_type_constant": has_const,
        "constant_referenced_in_endpoint": has_const_used,
        "audit_payload_includes_enrolled_by_and_cohort": has_payload_keys,
        "m216_widens_event_type_check": migration_ok,
        "m216_path": migration_path,
        "m216_scan_error": migration_error,
        "scanned_path": _ENROLLMENT_API_PATH,
    }
    ok = all(findings[k] for k in (
        "has_event_type_constant",
        "constant_referenced_in_endpoint",
        "audit_payload_includes_enrolled_by_and_cohort",
        "m216_widens_event_type_check",
    )) and migration_error is None
    return {
        "id": cid, "ok": ok,
        "severity": "info" if ok else "error",
        "details": findings,
    }


def _check_enrollment_endpoint_requires_coach_authorization() -> Dict[str, Any]:
    """Static scan: the enrollment endpoint must check
    ``coach_sensitive_bridge_authorized`` and return 404 (NOT 403) when the
    coach lacks authorization, so unauthorized coaches cannot even infer
    the feature exists.

    Pass criteria (all required):
      • ``coach_sensitive_bridge_authorized`` referenced in the endpoint
      • ``coach_profiles`` table queried for that flag
      • A 404 ``HTTPException`` is raised in the unauthorized branch
      • No 403 raised in the same branch (silent feature hiding)
    """
    cid = "enrollment_endpoint_requires_coach_authorization"
    try:
        with open(_ENROLLMENT_API_PATH, "r", encoding="utf-8") as fh:
            src = fh.read()
    except Exception as e:
        return {
            "id": cid, "ok": False, "severity": "warning",
            "details": {"error": repr(e)[:120], "path": _ENROLLMENT_API_PATH},
        }
    has_flag = "coach_sensitive_bridge_authorized" in src
    has_table = "coach_profiles" in src
    # Locate the enroll handler body specifically. The flag also appears in
    # other endpoints (visibility/load), so anchoring on the first match
    # would scan the wrong function. We isolate from the @router.post(...)
    # for /enroll through the next top-level def/decorator.
    # Decorator is `@coach_router.post(...)`. The handler body starts at the
    # `async def coach_initiated_enroll(` and ends at the next top-level
    # decorator OR a non-handler top-level def, OR end-of-file. We must
    # consume the handler's OWN `async def` line first so the lookahead
    # doesn't terminate immediately on it.
    enroll_handler = _re.search(
        r"@\w*router\.post\(\s*[\"'][^\"']*/enroll[\"'][\s\S]*?\nasync def \w[\s\S]*?(?=\n@\w*router\.|\nasync def \w|\ndef \w|\Z)",
        src,
    )
    gate_window = enroll_handler
    has_404_in_window = False
    has_403_in_window = False
    if gate_window:
        window = gate_window.group(0)
        # Match all common ways the unauthorized branch could raise 404:
        #   raise HTTPException(404, detail=...)         positional
        #   raise HTTPException(status_code=404, ...)    keyword
        #   raise HTTPException(status.HTTP_404_NOT_FOUND, ...)
        has_404_in_window = bool(_re.search(
            r"HTTPException\(\s*(?:status_code\s*=\s*)?404\b",
            window,
        )) or "HTTP_404_NOT_FOUND" in window
        has_403_in_window = bool(_re.search(
            r"HTTPException\(\s*(?:status_code\s*=\s*)?403\b",
            window,
        )) or "HTTP_403_FORBIDDEN" in window
    findings = {
        "has_authorization_flag_lookup": has_flag,
        "queries_coach_profiles_table": has_table,
        "raises_404_when_unauthorized": has_404_in_window,
        "does_not_raise_403_in_gate": not has_403_in_window,
        "scanned_path": _ENROLLMENT_API_PATH,
    }
    ok = all(findings[k] for k in (
        "has_authorization_flag_lookup",
        "queries_coach_profiles_table",
        "raises_404_when_unauthorized",
        "does_not_raise_403_in_gate",
    ))
    return {
        "id": cid, "ok": ok,
        "severity": "info" if ok else "error",
        "details": findings,
    }


async def _check_immutable_trigger(conn, cid: str, *, table: str) -> Dict[str, Any]:
    """Verify an UPDATE/DELETE-blocking trigger exists on the given table."""
    rows = await conn.fetch(
        """
        SELECT trigger_name, event_manipulation
        FROM information_schema.triggers
        WHERE event_object_table = $1
        """,
        table,
    )
    triggers = [{"name": r["trigger_name"], "event": r["event_manipulation"]} for r in rows]
    blocked_ops = {r["event_manipulation"] for r in rows
                   if r["event_manipulation"] in ("UPDATE", "DELETE")}
    ok = {"UPDATE", "DELETE"}.issubset(blocked_ops)
    return _entry(
        cid, ok=ok,
        details={"table": table, "triggers": triggers, "blocked_ops": list(blocked_ops)},
        severity="info" if ok else "warning",
    )


async def _check_codewords_no_plaintext(conn, cid: str) -> Dict[str, Any]:
    """Confirm the user_safety_codewords table stores hashed codewords only.

    Hashed columns expected: codeword_hash (TEXT). Plaintext column absence is
    the contract.
    """
    row = await conn.fetchrow(
        """
        SELECT
          BOOL_OR(column_name = 'codeword_hash') AS has_hash,
          BOOL_OR(column_name IN ('codeword', 'plaintext_codeword')) AS has_plain
        FROM information_schema.columns
        WHERE table_name = 'user_safety_codewords'
        """,
    )
    if row is None:
        return _entry(cid, ok=False,
                      details={"reason": "user_safety_codewords table absent"},
                      severity="warning")
    has_hash = bool(row["has_hash"])
    has_plain = bool(row["has_plain"])
    ok = has_hash and not has_plain
    return _entry(
        cid, ok=ok,
        details={"has_hash_column": has_hash, "has_plaintext_column": has_plain},
        severity="info" if ok else "error",
    )


async def _check_crystal_domain_canonical(conn, cid: str) -> Dict[str, Any]:
    """Scan DISTINCT domain values in nate_intelligence_crystals; flag drift.

    Phase 5 Note 2b verdict folded into ``details.sensitive_crystals_embodiment_phase_tagged``:
    every crystal in the sensitive-domain set MUST have ``requires_embodiment_phase``
    populated. NULL on a sensitive-domain crystal is a contract violation.
    """
    # Phase 6 follow-up (Path B, 2026-05-10): canonical set expanded from the
    # original 7 to 15 to honor pre-Sensitive-Clinical-Bridge organic domains
    # already populated in nate_intelligence_crystals (178k+ rows). Each added
    # domain has a documented operational origin and a long-term renormalization
    # path; this expansion is a contract widening, not a relaxation of the
    # sealed-domain principle.
    #
    # Original 7 (sealed):  clinical, coaching, marketing, research,
    #                       culture, defense, general
    # Added 8 (organic):    coding                 — code-learning crystals
    #                       biochem                — Nevedal biochemistry
    #                       coherence              — Nevedal coherence engine
    #                       predictive_intelligence— foresight engine
    #                       voice                  — voice biometrics
    #                       patent                 — patent portfolio
    #                       neuroscience_foundations — Patent #9 neuroanatomical
    #                       neural_acoustic        — neural-acoustic verification
    canonical = {
        # Sealed clinical/sensitive-bridge contract (Plan v1.3 §canonical-domains)
        "clinical", "coaching", "marketing", "research",
        "culture", "defense", "general",
        # Organic engine/research domains (pre-existing in production)
        "coding", "biochem", "coherence", "predictive_intelligence",
        "voice", "patent", "neuroscience_foundations", "neural_acoustic",
    }
    try:
        rows = await conn.fetch(
            "SELECT DISTINCT domain FROM nate_intelligence_crystals "
            "WHERE domain IS NOT NULL"
        )
    except Exception as e:
        return _entry(cid, ok=False,
                      details={"error": repr(e)[:120]}, severity="warning")
    observed = {r["domain"] for r in rows}
    drift = sorted(observed - canonical)
    domain_ok = not drift

    # ── Phase 5 Note 2b folded verdict ────────────────────────────────────
    # sensitive_crystals_embodiment_phase_tagged
    embodiment_verdict: Dict[str, Any] = {
        "check_id": "sensitive_crystals_embodiment_phase_tagged",
        "ok": True,
        "domains_evaluated": [],
        "untagged_count": 0,
    }
    try:
        sensitive_row = await conn.fetchrow(
            "SELECT setting_value FROM app_settings "
            "WHERE setting_key = 'sensitive_crystal_seed_domains'",
        )
        sensitive_domains: List[str]
        if sensitive_row is None:
            sensitive_domains = [
                "intimacy_clinical", "sexual_trauma", "trafficking_trauma",
                "embodiment_repair", "child_trafficking",
            ]
        else:
            raw = sensitive_row["setting_value"]
            if isinstance(raw, str):
                import json as _json
                raw = _json.loads(raw)
            sensitive_domains = list(raw) if isinstance(raw, list) else []

        embodiment_verdict["domains_evaluated"] = sensitive_domains

        if sensitive_domains:
            untagged = await conn.fetchval(
                """
                SELECT COUNT(*) FROM nate_intelligence_crystals
                WHERE domain = ANY($1::text[])
                  AND requires_embodiment_phase IS NULL
                """,
                sensitive_domains,
            )
            embodiment_verdict["untagged_count"] = int(untagged or 0)
            embodiment_verdict["ok"] = (int(untagged or 0) == 0)
    except Exception as exc:
        embodiment_verdict["ok"] = False
        embodiment_verdict["error"] = repr(exc)[:120]

    ok = domain_ok and embodiment_verdict["ok"]
    return _entry(
        cid, ok=ok,
        details={"canonical": sorted(canonical), "observed": sorted(observed),
                 "drift": drift,
                 "sensitive_crystals_embodiment_phase_tagged": embodiment_verdict},
        severity="info" if ok else "warning",
    )


async def _check_log_retention_7yr(conn, cid: str) -> Dict[str, Any]:
    """Verify a retention policy / column / app_settings entry asserts >= 7yr."""
    row = await conn.fetchrow(
        "SELECT setting_value FROM app_settings "
        "WHERE setting_key = 'sensitive_log_retention_years'"
    )
    if row is None:
        return _entry(
            cid, ok=False,
            details={"reason": "app_settings.sensitive_log_retention_years not set"},
            severity="warning",
        )
    val = row["setting_value"]
    try:
        years = int(val) if isinstance(val, (int, str)) else int(val.get("years", 0))
    except Exception:
        years = 0
    ok = years >= 7
    return _entry(
        cid, ok=ok,
        details={"configured_years": years, "minimum_required": 7},
        severity="info" if ok else "error",
    )


async def _check_jurisdiction_trigger(conn, cid: str) -> Dict[str, Any]:
    """Verify the per-jurisdiction retention trigger is present (Gap L)."""
    rows = await conn.fetch(
        """
        SELECT trigger_name FROM information_schema.triggers
        WHERE event_object_table = 'sensitive_bridge_log'
          AND trigger_name ILIKE '%jurisdiction%'
        """,
    )
    found = [r["trigger_name"] for r in rows]
    ok = bool(found)
    return _entry(
        cid, ok=ok,
        details={"triggers_found": found,
                 "expected_pattern": "%jurisdiction%"},
        severity="info" if ok else "warning",
    )


async def _check_access_classification_column(conn, cid: str) -> Dict[str, Any]:
    """Verify access_classification column + CHECK constraint exist.

    Phase 5 Note 1c verdict folded into ``details.data_export_signed_url_single_download_enforced``:
    insert a synthetic ``client_data_export_requests`` row with ``max_downloads=1``,
    run the router's atomic UPDATE twice, and assert second attempt RETURNs zero
    rows (the SQL contract that becomes 410 Gone at the HTTP layer). Cleans up
    the synthetic row regardless of outcome.
    """
    row = await conn.fetchrow(
        """
        SELECT data_type FROM information_schema.columns
        WHERE table_name = 'sensitive_bridge_log'
          AND column_name = 'access_classification'
        """,
    )
    has_col = row is not None
    if not has_col:
        return _entry(
            cid, ok=False,
            details={"reason": "access_classification column absent"},
            severity="warning",
        )
    ck_rows = await conn.fetch(
        """
        SELECT cc.constraint_name
        FROM information_schema.check_constraints cc
        JOIN information_schema.constraint_column_usage ccu
          ON cc.constraint_name = ccu.constraint_name
        WHERE ccu.table_name = 'sensitive_bridge_log'
          AND ccu.column_name = 'access_classification'
        """,
    )
    has_check = len(ck_rows) > 0
    classification_ok = has_col and has_check

    # ── Phase 5 Note 1c folded verdict ────────────────────────────────────
    # data_export_signed_url_single_download_enforced
    import secrets as _secrets
    import uuid as _uuid

    sd_verdict: Dict[str, Any] = {
        "check_id": "data_export_signed_url_single_download_enforced",
        "ok": False,
        "first_update_rowcount": None,
        "second_update_rowcount": None,
    }
    synthetic_token = f"auditor_{_uuid.uuid4().hex}_{_secrets.token_urlsafe(8)}"
    inserted = False
    try:
        # 1. Insert synthetic export request: max_downloads=1, expires_at +1h.
        await conn.execute(
            """
            INSERT INTO client_data_export_requests
                (user_id, requested_by, request_origin,
                 signed_url_token, max_downloads, expires_at,
                 status, bundle_jsonb, is_synthetic)
            VALUES ('system', 'system', 'auditor_synthetic',
                    $1, 1, NOW() + INTERVAL '1 hour',
                    'ready', '{}'::jsonb, TRUE)
            """,
            synthetic_token,
        )
        inserted = True

        # 2. Run the router's atomic UPDATE twice.
        first = await conn.fetch(
            """
            UPDATE client_data_export_requests
               SET download_count    = download_count + 1,
                   last_downloaded_at = NOW(),
                   status            = 'downloaded'
             WHERE signed_url_token = $1
               AND download_count   < max_downloads
               AND expires_at       > NOW()
            RETURNING request_id
            """,
            synthetic_token,
        )
        second = await conn.fetch(
            """
            UPDATE client_data_export_requests
               SET download_count    = download_count + 1,
                   last_downloaded_at = NOW(),
                   status            = 'downloaded'
             WHERE signed_url_token = $1
               AND download_count   < max_downloads
               AND expires_at       > NOW()
            RETURNING request_id
            """,
            synthetic_token,
        )

        sd_verdict["first_update_rowcount"] = len(first)
        sd_verdict["second_update_rowcount"] = len(second)
        # Contract: first MUST succeed (1), second MUST be empty (0 → 410 Gone).
        sd_verdict["ok"] = (len(first) == 1 and len(second) == 0)
    except Exception as exc:
        sd_verdict["error"] = repr(exc)[:160]
    finally:
        if inserted:
            try:
                await conn.execute(
                    "DELETE FROM client_data_export_requests "
                    "WHERE signed_url_token = $1",
                    synthetic_token,
                )
            except Exception:
                pass  # leave a synthetic crumb rather than crash the auditor

    ok = classification_ok and sd_verdict["ok"]
    return _entry(
        cid, ok=ok,
        details={"has_column": has_col, "has_check_constraint": has_check,
                 "data_type": dict(row).get("data_type") if row else None,
                 "data_export_signed_url_single_download_enforced": sd_verdict},
        severity="info" if ok else "warning",
    )


async def _check_handoff_redaction_no_pii(conn, cid: str) -> Dict[str, Any]:
    """Sample recent coach_alert audit rows; confirm payload_ref pattern, not
    inline payloads with PII-shaped fields.

    Heuristic: if the JSONB contains an `payload_ref` string and lacks
    `notes` / `phone` / `email` / `address` keys at top level, ok.
    """
    try:
        rows = await conn.fetch(
            """
            SELECT payload_json
            FROM sensitive_bridge_log
            WHERE event_type LIKE 'coach_alert%'
            ORDER BY occurred_at DESC
            LIMIT 50
            """,
        )
    except Exception as e:
        # Table missing → warning, not error.
        return _entry(cid, ok=False,
                      details={"error": repr(e)[:120]}, severity="warning")
    if not rows:
        return _entry(cid, ok=True,
                      details={"sampled": 0, "reason": "no coach_alert rows yet"},
                      severity="info")
    suspect_keys = {"notes", "phone", "email", "address", "ssn"}
    bad: List[Dict[str, Any]] = []
    for r in rows:
        payload = r["payload_json"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            continue
        present_suspects = sorted(set(payload.keys()) & suspect_keys)
        has_ref = isinstance(payload.get("payload_ref"), str)
        if present_suspects or not has_ref:
            bad.append({"has_payload_ref": has_ref,
                        "suspect_keys": present_suspects})
    ok = not bad
    return _entry(
        cid, ok=ok,
        details={"sampled": len(rows),
                 "violations_first_5": bad[:5]},
        severity="info" if ok else "error",
    )


async def _check_false_positive_rate(conn, cid: str) -> Dict[str, Any]:
    """Aggregate ``detector_telemetry`` false-positive rate per gap; warn >5%.

    Schema reference (migration 209):
      • ``gap_flag``           — feature flag the detector belongs to
      • ``classification``     — one of {'true_positive','false_positive',
                                          'unreviewed','indeterminate'}
      • ``clinician_reviewed`` — only reviewed rows count toward FP rate
      • ``recorded_at``        — event timestamp
    """
    try:
        rows = await conn.fetch(
            """
            SELECT gap_flag,
                   COUNT(*) FILTER (
                     WHERE clinician_reviewed = TRUE
                   ) AS reviewed_total,
                   COUNT(*) FILTER (
                     WHERE clinician_reviewed = TRUE
                       AND classification = 'false_positive'
                   ) AS false_positives
            FROM detector_telemetry
            WHERE recorded_at > NOW() - INTERVAL '7 days'
            GROUP BY gap_flag
            """,
        )
    except Exception as e:
        return _entry(cid, ok=False,
                      details={"error": repr(e)[:120]}, severity="warning")
    if not rows:
        return _entry(cid, ok=True,
                      details={"reason": "no telemetry rows yet (shadow-mode)"},
                      severity="info")
    over: List[Dict[str, Any]] = []
    summary: List[Dict[str, Any]] = []
    for r in rows:
        total = r["reviewed_total"] or 0
        fp = r["false_positives"] or 0
        rate = (fp / total) if total else 0.0
        summary.append({"gap_flag": r["gap_flag"], "rate": round(rate, 4),
                        "reviewed_total": total, "fp": fp})
        # Plan v1.3 §Gap F threshold: 5% over reviewed sample of 20+.
        if rate > 0.05 and total >= 20:
            over.append(summary[-1])
    ok = not over
    return _entry(
        cid, ok=ok,
        details={"per_gap": summary, "over_threshold": over,
                 "threshold_pct": 5.0,
                 "min_reviewed_sample": 20},
        severity="info" if ok else "warning",
    )


async def _check_shadow_mode_review_current(conn, cid: str) -> Dict[str, Any]:
    """Verify a clinician reviewed shadow-mode decisions within last 14 days."""
    try:
        row = await conn.fetchrow(
            """
            SELECT MAX(created_at) AS last_review
            FROM skyeye_activity
            WHERE type = 'shadow_mode_decision_reviewed'
            """,
        )
    except Exception as e:
        return _entry(cid, ok=False,
                      details={"error": repr(e)[:120]}, severity="warning")
    last = row["last_review"] if row else None
    if last is None:
        return _entry(cid, ok=True,
                      details={"reason": "no shadow-mode reviews yet (pre-launch)"},
                      severity="info")
    age_days = (datetime.now(timezone.utc) - last).days
    ok = age_days <= 14
    return _entry(
        cid, ok=ok,
        details={"last_review": last.isoformat(), "age_days": age_days,
                 "threshold_days": 14},
        severity="info" if ok else "warning",
    )


async def _check_safe_silence_warning_cadence(conn, cid: str) -> Dict[str, Any]:
    """Verify the day-25 warning + day-30 auto-revert cadence is observable.

    Pass criteria (any one):
      • At least one `safe_silence_warning_sent` row in last 35 days, OR
      • Zero active safe_silence_mode states (nothing to warn about).

    Pre-launch the table may not exist → warning, not error.
    """
    try:
        active = await conn.fetchval(
            """
            SELECT COUNT(*) FROM safe_silence_mode_state
            WHERE active = TRUE
            """
        )
    except Exception as e:
        return _entry(cid, ok=False,
                      details={"error": repr(e)[:120],
                               "reason": "safe_silence_mode_state table absent"},
                      severity="warning")
    if (active or 0) == 0:
        return _entry(cid, ok=True,
                      details={"active_safe_silence_states": 0,
                               "reason": "no active states; cadence trivially satisfied"},
                      severity="info")
    try:
        warned = await conn.fetchval(
            """
            SELECT COUNT(*) FROM skyeye_activity
            WHERE type = 'safe_silence_warning_sent'
              AND created_at > NOW() - INTERVAL '35 days'
            """
        )
    except Exception as e:
        return _entry(cid, ok=False,
                      details={"error": repr(e)[:120]}, severity="warning")
    ok = (warned or 0) > 0
    return _entry(
        cid, ok=ok,
        details={"active_safe_silence_states": int(active),
                 "warnings_last_35d": int(warned or 0),
                 "expected_when_active": ">= 1"},
        severity="info" if ok else "warning",
    )


async def _check_flag_activation(
    conn, cid: str, flag_name: str, detector_id: str,
) -> Dict[str, Any]:
    """A flag is `active` iff:
      - `app_settings.sensitive_bridge_global_gap_flags->>flag_name` is true
        OR at least one cohort has it true in `sensitive_bridge_enrollment`,
      AND
      - At least one telemetry event for `detector_id` exists in last 7 days.

    During shadow-mode the absence of telemetry is informational, not an error.
    """
    flag_on = False
    try:
        row = await conn.fetchrow(
            "SELECT setting_value FROM app_settings "
            "WHERE setting_key = 'sensitive_bridge_global_gap_flags'"
        )
        if row and isinstance(row["setting_value"], dict):
            flag_on = bool(row["setting_value"].get(flag_name, False))
        elif row and isinstance(row["setting_value"], str):
            try:
                flag_on = bool(json.loads(row["setting_value"]).get(flag_name, False))
            except Exception:
                flag_on = False
    except Exception:
        pass

    telemetry_count = 0
    try:
        telemetry_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM detector_telemetry
            WHERE detector_id = $1 AND created_at > NOW() - INTERVAL '7 days'
            """,
            detector_id,
        ) or 0
    except Exception:
        telemetry_count = -1  # table missing

    if not flag_on:
        return _entry(
            cid, ok=True,
            details={"flag": flag_name, "flag_on": False,
                     "reason": "global flag off; awaiting Phase 6 enablement"},
            severity="info",
        )
    if telemetry_count < 0:
        return _entry(
            cid, ok=False,
            details={"flag": flag_name, "flag_on": True,
                     "reason": "detector_telemetry missing"},
            severity="warning",
        )
    if telemetry_count == 0:
        return _entry(
            cid, ok=True,
            details={"flag": flag_name, "flag_on": True,
                     "telemetry_7d": 0,
                     "reason": "flag on but no events yet (shadow-mode entry)"},
            severity="info",
        )
    return _entry(
        cid, ok=True,
        details={"flag": flag_name, "flag_on": True,
                 "telemetry_7d": telemetry_count,
                 "detector": detector_id},
        severity="info",
    )
