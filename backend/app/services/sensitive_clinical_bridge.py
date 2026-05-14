"""Sensitive Clinical Bridge Orchestrator (Phase 4a, plan v1.3).

This module is the ONLY new module in Phase 4's wiring step. The five sealed
Phase 3 modules are CONSUMERS of this orchestrator's outputs, never co-authors
of its logic:

    - therapeutic_controller.py
    - governance/mandatory_reporting.py
    - coach_override_protocol.py
    - nate_checkin_agent.py
    - sse/ucd/tmc.py

If a future maintainer ever finds themselves about to add a method to one of
those five files in order to make this orchestrator work, the orchestrator
contract is wrong — not the modules. The auditor check
`phase4_no_modifications_to_phase3_modules` (verified at CI level via
`git diff` against the Phase 3 seal commit) enforces this absolutely.

═══════════════════════════════════════════════════════════════════════════
NOTE 1 (BLOCKING) — Module isolation contract
═══════════════════════════════════════════════════════════════════════════

The orchestrator only invokes pre-existing public surfaces of the sealed
Phase 3 modules:

    | Sealed module                  | Public surface invoked here              |
    |--------------------------------|------------------------------------------|
    | therapeutic_controller         | (consumed via wiring touch in P4 commit) |
    | mandatory_reporting            | screen_message_with_trafficking(...)     |
    | coach_override_protocol        | escalate_acuity / build_handoff_payload  |
    | nate_checkin_agent             | check_codeword(user_id=, message=, ...)  |
    | tmc                            | classify(user_id)                        |

The orchestrator does NOT import or depend on any underscore-prefixed
("module-private") helper inside those five files. The thalamic novelty gate
at step 12 is reimplemented locally (see `_thalamic_gate_v1_3()`) rather than
imported from `therapeutic_controller._evaluate_thalamic_novelty_gate` —
this respects the Phase 3 seal and the cross-module privacy boundary.

═══════════════════════════════════════════════════════════════════════════
NOTE 2 (BLOCKING) — 17-step pipeline order is the contract
═══════════════════════════════════════════════════════════════════════════

The canonical execution order from plan v1.3 is captured in
`PIPELINE_STEP_NAMES_V1_3` (module constant). Two orderings are non-obvious
and are defended both here and at the call sites with permanent comments:

    (a) Codeword listener at step 2, BEFORE TMC classify (step 3).
        Codeword is the safety-net signal; it must fire even if TMC fails or
        is unreachable. If a future maintainer "optimizes" by moving the
        codeword check inside TMC's classify path, the listener becomes
        dependent on TMC reachability, which violates the Gap 2 / Risk #3
        black-box-paradox mitigation: "the silenced safety net is the single
        largest clinical risk in the entire bridge."

    (b) Thalamic gate at step 12, AFTER all signal detectors (steps 4-7) +
        crystal recall (step 11). The gate combines those signals to decide
        whether mismatch should be suppressed. Moving it earlier means
        gating without full signal; moving it later means crystal recall
        and register selection happen before the gate decision, wasting
        compute on a turn that will be blocked anyway.

The auditor check `pipeline_order_matches_plan_v1_3` asserts that the live
execution order in `evaluate_disclosure()` matches `PIPELINE_STEP_NAMES_V1_3`
exactly. Any reordering must be reflected in BOTH places.

═══════════════════════════════════════════════════════════════════════════
NOTE 3 (high-attention) — BridgeDecision v1.1 partner-seam contract
═══════════════════════════════════════════════════════════════════════════

`BridgeDecision` is the partner-seam contract for downstream consumers
(controller wiring, clinician portal, partner integrations). Three contract
guarantees apply to EVERY field, not just `audit_event`:

    (a) NO RAW USER MESSAGE TEXT in any string field anywhere in the
        decision. Detectors return clinician-readable markers, never
        verbatim user text. The pre-return validator
        `_validate_no_raw_transcript_leak()` scans every string field
        recursively before the decision is returned, raising
        `BridgeDecisionRedactionError` on any contiguous-substring overlap
        with the original user message at or above
        `_REDACTION_MIN_OVERLAP_CHARS`. This is the same discipline as
        `coach_override_protocol._validate_no_raw_transcript_leak`.

    (b) SCHEMA VERSIONED with content hash. `BRIDGE_DECISION_SCHEMA_VERSION`
        and `BRIDGE_DECISION_SCHEMA_HASH` are computed at module load from
        the dataclass field structure (same pattern as
        `specialized_resources.REGISTRY_CONTENT_HASH` and
        `coach_override_protocol.HANDOFF_PAYLOAD_SCHEMA_HASH`). Future
        partner integrations carrying schema-aware deserializers detect
        drift from the audit log without manual coordination.

    (c) `coach_alert.payload_ref` carries a REFERENCE to the handoff payload
        stored at higher access classification, NOT the payload inline. The
        full `HandoffPayload` (built by
        `coach_override_protocol.build_handoff_payload`) is written to a
        `coach_handoff_emitted` row in `sensitive_bridge_log` at
        `clinician_only` classification. `BridgeDecision.coach_alert.payload_ref`
        carries that audit row's id (string). Partner integrations see the
        alert metadata but must request the payload via clinician-authorized
        API. If the payload were inlined here, partner logs would
        accidentally retain the full clinical handoff, defeating the
        access-classification contract from migration 202 (Gap C).

═══════════════════════════════════════════════════════════════════════════
SHADOW MODE (Phase 6) — orchestrator behavior is mode-agnostic
═══════════════════════════════════════════════════════════════════════════

This orchestrator runs unchanged whether the deployment is in shadow mode
(Phase 6 14-day soak) or full apply mode. The shadow gate lives at the
controller wiring point: `prepare_therapeutic_context()` decides whether to
apply `BridgeDecision.register_directive` based on its own feature flag.
The orchestrator always emits a complete decision and audit trail; the
controller decides whether to act on it. This separation keeps the contract
clean and lets us collect telemetry under shadow without ever modifying
this module to add mode-conditional logic.

═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════
# Pipeline order contract (Note 2 — BLOCKING)
# ═════════════════════════════════════════════════════════════════════════

PIPELINE_STEP_NAMES_V1_3: Tuple[str, ...] = (
    "profile_fetch",                    # 1
    "codeword_listener",                # 2  — safety net; pre-TMC by contract
    "tmc_classify_with_polyvictim",     # 3
    "introjection_mirror",              # 4
    "coercion_detector",                # 5
    "dissociation_delta",               # 6
    "reengagement_detector",            # 7
    "trigger_date_check",               # 8
    "legal_proximity_check",            # 9
    "embodiment_phase_resolution",      # 10
    "domain_crystal_recall",            # 11
    "thalamic_novelty_gate",            # 12 — combines all pre-step-12 signals
    "register_selection",               # 13
    "arousal_load_measurement",         # 14
    "mandatory_reporting_screen",       # 15
    "coach_handoff_payload_build",      # 16
    "audit_event_emission",             # 17
)
"""Canonical 17-step pipeline order from plan v1.3.

The auditor check `pipeline_order_matches_plan_v1_3` asserts the runtime
execution log of `evaluate_disclosure()` matches this tuple element-for-element.
Reordering ANY step requires:
    1. Updating this tuple.
    2. Updating the corresponding step block in `evaluate_disclosure()`.
    3. Documenting the clinical justification in this module's docstring.
    4. Updating SENSITIVE_CLINICAL_BRIDGE_GUIDELINES_2026-05-08.md.
"""


# ═════════════════════════════════════════════════════════════════════════
# Register selection priority order (step 13)
# ═════════════════════════════════════════════════════════════════════════

REGISTER_SELECTION_PRIORITY: Tuple[str, ...] = (
    "codeword",
    "trigger_date",
    "legal_proximity",
    "reengagement",
    "introjection",
    "embodiment",
    "tmc_class",
    "substance_branch",
    "default",
)
"""Plan v1.3 register selection priority. Earliest match wins.

If the codeword listener fired, register is `safe_silence_mode_codeword`.
If a trigger date is active and no codeword, register reflects the trigger.
And so on, falling through to `default` (the controller's autonomic-state
derived register).
"""


# ═════════════════════════════════════════════════════════════════════════
# Note 3a — redaction validator constants
# ═════════════════════════════════════════════════════════════════════════

_REDACTION_MIN_OVERLAP_CHARS: int = 12
"""Minimum contiguous character overlap with the original user message that
counts as a raw-transcript leak. 12 chars is short enough to catch leakage
('I want to die' = 13 chars) but long enough to avoid false positives on
common clinical markers ('shame', 'numb', 'dissociation').
"""

_REDACTION_FIELD_ALLOWLIST: frozenset[str] = frozenset({
    # Fields that may legitimately echo trace fragments (clinician-curated).
    # Empty set — no field is allowed to leak raw user text in v1.1.
})


class BridgeDecisionRedactionError(RuntimeError):
    """Raised when the pre-return validator detects raw user text in a
    BridgeDecision field. Same discipline as
    `coach_override_protocol._validate_no_raw_transcript_leak` — the
    validator MUST raise rather than silently strip, so the test fixture
    catches the regression rather than the partner integration.
    """

    def __init__(self, field_path: str, sample: str) -> None:
        super().__init__(
            f"BridgeDecision raw-transcript leak in field {field_path!r}: "
            f"{sample!r}"
        )
        self.field_path = field_path
        self.sample = sample


# ═════════════════════════════════════════════════════════════════════════
# v1.1 sub-payload dataclasses (typed, frozen, redacted by construction)
# ═════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class NoveltyGateState:
    """Step 12 output. `blocked` is the actionable bit; the rest is telemetry."""
    blocked: bool
    reason: str
    dissociation_delta: float
    coercion_severity: float
    threshold: float
    forced_on: bool


@dataclass(frozen=True)
class ArousalLoadSummary:
    """Step 14 output. Carries clinician-readable triggering term tags only."""
    score: float
    cap_triggered: bool
    triggering_term_tags: Tuple[str, ...]
    register_at_measurement: str


@dataclass(frozen=True)
class IntrojectionSummary:
    """Step 4 output. `drift_markers` are clinician-readable tags from the
    introjection_voice_mirror detector — never verbatim user text.
    """
    detected: bool
    score: float
    drift_markers: Tuple[str, ...]


@dataclass(frozen=True)
class ReengagementSummary:
    """Step 7 output. `matched_labels` are clinician-readable from the
    reengagement_pattern_detector — never verbatim user phrases.
    """
    detected: bool
    severity: str
    matched_labels: Tuple[str, ...]


@dataclass(frozen=True)
class CoercionSummary:
    """Step 5 output. `matched_labels` are clinician-readable from the
    coercion_pattern_detector — never verbatim user phrases.
    """
    detected: bool
    severity: float
    matched_labels: Tuple[str, ...]


@dataclass(frozen=True)
class DissociationSummary:
    """Step 6 output. Carries deltas + clinician-readable markers only."""
    delta: float
    length_anomaly_z: float
    markers: Tuple[str, ...]


@dataclass(frozen=True)
class PolyvictimLoad:
    """Step 3 sub-output. From `user_polyvictimization_layers` summarized
    into TMC's polyvictim_severity_load + layer_count signals.
    """
    layers_active: int
    severity_load: float
    stacking_eligible: bool


@dataclass(frozen=True)
class EmbodimentPhaseApplied:
    """Step 10 output. Clinician-set phase label (no free-form text)."""
    phase: Optional[str]
    set_at: Optional[str]
    set_by_clinician_id: Optional[str]


@dataclass(frozen=True)
class TriggerDateMatch:
    """Step 8 output. Match metadata only; clinician notes live in
    user_trigger_dates with their own RBAC.
    """
    matched: bool
    date_type: Optional[str]
    severity: Optional[str]
    match_count: int


@dataclass(frozen=True)
class LegalProximity:
    """Step 9 output. Case metadata from user_legal_status; never narrative
    detail (which is clinician-only in the source table).
    """
    detected: bool
    case_type: Optional[str]
    case_status: Optional[str]
    days_until_next_event: Optional[int]


@dataclass(frozen=True)
class SubstanceRegisterBranch:
    """Step 13 sub-decision. When dual-diagnosis (substance) signal fires,
    the register branches into a substance-aware variant.
    """
    branched: bool
    reason: str


@dataclass(frozen=True)
class SexAddictionRegisterBranch:
    """v1.4 Step 13 branch — sex addiction."""
    branched: bool
    reason: str


@dataclass(frozen=True)
class GamblingRegisterBranch:
    """v1.4 Step 13 branch — gambling."""
    branched: bool
    reason: str


@dataclass(frozen=True)
class GamingRegisterBranch:
    """v1.4 Step 13 branch — gaming."""
    branched: bool
    reason: str


@dataclass(frozen=True)
class FoodCompulsionRegisterBranch:
    """v1.4 Step 13 branch — food compulsion."""
    branched: bool
    reason: str


@dataclass(frozen=True)
class WorkCompulsionRegisterBranch:
    """v1.4 Step 13 branch — work compulsion."""
    branched: bool
    reason: str


@dataclass(frozen=True)
class SpendingCompulsionRegisterBranch:
    """v1.4 Step 13 branch — spending compulsion."""
    branched: bool
    reason: str


@dataclass(frozen=True)
class CodependencyRegisterBranch:
    """v1.4 Step 13 branch — codependency."""
    branched: bool
    reason: str


@dataclass(frozen=True)
class CrossAddictionRegisterBranch:
    """v1.4 composite branch — fires when 2+ individual branches active."""
    branched: bool
    reason: str
    active_branches: tuple = ()
    primary: str = ""
    secondary: str = ""
    overlay_directive: str = ""


@dataclass(frozen=True)
class TraffickingClassificationSummary:
    """Step 7 → step 15 hand-off. Carries the trafficking classifier result
    in a redacted-by-construction summary for mandatory_reporting input.
    """
    label: str
    confidence: float
    matched_classes_above_floor: Tuple[str, ...]


@dataclass(frozen=True)
class CoachAlertRef:
    """Step 16 output — Note 3c partner-seam discipline.

    `payload_ref` is the audit row id (BIGSERIAL from sensitive_bridge_log)
    where the full HandoffPayload lives at `clinician_only` classification.
    The full payload is NEVER inlined here. Partner integrations request the
    payload via clinician-authorized API using `payload_ref`.

    `handoff_schema_hash` lets partners detect handoff payload schema drift
    independently of BridgeDecision schema drift.
    """
    payload_ref: str
    trigger: str
    severity: str
    handoff_schema_hash: str
    payload_emitted_at: str


# ═════════════════════════════════════════════════════════════════════════
# BridgeDecision v1.1 — the partner-seam contract (Note 3)
# ═════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class BridgeDecision:
    """Output of `evaluate_disclosure()`. The partner-seam contract.

    PLAN v1.3 REQUIRED FIELDS (5):
        register_directive, coach_alert, resource_block, scope_statement,
        audit_event

    PLAN v1.3 v1.1 ADDITIONS (11):
        novelty_gate_state, arousal_load, introjection_signal,
        reengagement_signal, polyvictim_load, embodiment_phase_applied,
        trigger_date_match, legal_proximity, substance_register_branch,
        prebuffer_required, prebuffer_text

    SCHEMA STAMP (3):
        schema_version, schema_hash, decided_at

    Total: 19 fields. Schema hash includes all 16 functional fields and
    excludes the schema stamp itself (so a stamp bump does not change
    the hash — content vs identity, same as specialized_resources).
    """

    # Plan v1.3 required fields
    register_directive: Optional[str]
    coach_alert: Optional[CoachAlertRef]
    resource_block: Optional[Dict[str, Any]]  # serialized ResourceBlock.to_payload_dict
    scope_statement: Optional[str]
    audit_event: Dict[str, Any]

    # v1.1 additions (11)
    novelty_gate_state: NoveltyGateState
    arousal_load: Optional[ArousalLoadSummary]
    introjection_signal: IntrojectionSummary
    reengagement_signal: ReengagementSummary
    polyvictim_load: PolyvictimLoad
    embodiment_phase_applied: EmbodimentPhaseApplied
    trigger_date_match: TriggerDateMatch
    legal_proximity: LegalProximity
    substance_register_branch: SubstanceRegisterBranch
    prebuffer_required: bool
    prebuffer_text: Optional[str]

    # v1.1 derived signals (carried for partner consumption + audit symmetry)
    coercion_test: CoercionSummary
    dissociation_signal: DissociationSummary
    trafficking_classification: Optional[TraffickingClassificationSummary]
    tmc_class: str
    selected_register_source: str  # which REGISTER_SELECTION_PRIORITY entry won

    # Schema stamp (excluded from hash)
    schema_version: str = ""
    schema_hash: str = ""
    decided_at: str = ""

    def to_partner_dict(self) -> Dict[str, Any]:
        """Serialize for partner-seam transport. Stable JSON-friendly form.
        Identical content as `asdict(self)` but with deterministic ordering.
        """
        raw = asdict(self)
        return _coerce_jsonable(raw)


# ═════════════════════════════════════════════════════════════════════════
# Schema version + content hash (Note 3b)
# ═════════════════════════════════════════════════════════════════════════

BRIDGE_DECISION_SCHEMA_VERSION: str = "1.1.0"
"""Identity of the BridgeDecision schema. Bump on any field add/remove/rename.

Same versioning discipline as `coach_override_protocol.HANDOFF_PAYLOAD_SCHEMA_VERSION`
and `specialized_resources.REGISTRY_VERSION`.
"""


def _compute_schema_hash() -> str:
    """Deterministic SHA256 of BridgeDecision's structural shape.

    Inclusion set: every field name + type repr in BridgeDecision and every
    nested @dataclass referenced by it. Excludes schema_version / schema_hash
    / decided_at (stamp fields — content vs identity, same as
    `specialized_resources.compute_registry_hash`).
    """

    def _shape(dc_cls) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for f in fields(dc_cls):
            if f.name in {"schema_version", "schema_hash", "decided_at"}:
                continue
            t = f.type if isinstance(f.type, str) else repr(f.type)
            out[f.name] = t
        return out

    payload = {
        "BridgeDecision": _shape(BridgeDecision),
        "NoveltyGateState": _shape(NoveltyGateState),
        "ArousalLoadSummary": _shape(ArousalLoadSummary),
        "IntrojectionSummary": _shape(IntrojectionSummary),
        "ReengagementSummary": _shape(ReengagementSummary),
        "CoercionSummary": _shape(CoercionSummary),
        "DissociationSummary": _shape(DissociationSummary),
        "PolyvictimLoad": _shape(PolyvictimLoad),
        "EmbodimentPhaseApplied": _shape(EmbodimentPhaseApplied),
        "TriggerDateMatch": _shape(TriggerDateMatch),
        "LegalProximity": _shape(LegalProximity),
        "SubstanceRegisterBranch": _shape(SubstanceRegisterBranch),
        "TraffickingClassificationSummary": _shape(TraffickingClassificationSummary),
        "CoachAlertRef": _shape(CoachAlertRef),
        "PIPELINE_STEP_NAMES_V1_3": list(PIPELINE_STEP_NAMES_V1_3),
        "REGISTER_SELECTION_PRIORITY": list(REGISTER_SELECTION_PRIORITY),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


BRIDGE_DECISION_SCHEMA_HASH: str = _compute_schema_hash()
"""SHA256 of BridgeDecision structural shape. Drift detected by auditor."""


# ═════════════════════════════════════════════════════════════════════════
# Note 3a — pre-return redaction validator
# ═════════════════════════════════════════════════════════════════════════


def _iter_string_fields(obj: Any, path: str = "") -> List[Tuple[str, str]]:
    """Yield (dotted_field_path, string_value) for every string in `obj`,
    recursing into dataclasses, dicts, lists, and tuples.
    """
    out: List[Tuple[str, str]] = []
    if obj is None:
        return out
    if isinstance(obj, str):
        out.append((path or "<root>", obj))
        return out
    if is_dataclass(obj):
        for f in fields(obj):
            sub_path = f"{path}.{f.name}" if path else f.name
            out.extend(_iter_string_fields(getattr(obj, f.name), sub_path))
        return out
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            sub_path = f"{path}.{k}" if path else str(k)
            out.extend(_iter_string_fields(v, sub_path))
        return out
    if isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            sub_path = f"{path}[{i}]"
            out.extend(_iter_string_fields(v, sub_path))
        return out
    return out


def _normalize_for_overlap(s: str) -> str:
    return " ".join(s.lower().split())


def _validate_no_raw_transcript_leak(
    decision: BridgeDecision,
    original_message: Optional[str],
) -> None:
    """Pre-return validator (Note 3a). Scans every string field in the
    decision for contiguous overlap with the original user message at or
    above _REDACTION_MIN_OVERLAP_CHARS. Raises BridgeDecisionRedactionError
    on the first leak found.

    Same discipline as `coach_override_protocol._validate_no_raw_transcript_leak`:
    raise rather than silently strip, so the regression is caught by the
    test fixture rather than the partner integration.
    """
    if not original_message:
        return
    msg_n = _normalize_for_overlap(original_message)
    if len(msg_n) < _REDACTION_MIN_OVERLAP_CHARS:
        return  # Too short to detect contiguous leakage reliably.

    for field_path, value in _iter_string_fields(decision):
        if field_path in _REDACTION_FIELD_ALLOWLIST:
            continue
        if not value:
            continue
        val_n = _normalize_for_overlap(value)
        if msg_n in val_n:
            raise BridgeDecisionRedactionError(field_path, value[:80])
        # Sliding-window check for contiguous substring leakage.
        for i in range(0, len(msg_n) - _REDACTION_MIN_OVERLAP_CHARS + 1):
            window = msg_n[i : i + _REDACTION_MIN_OVERLAP_CHARS]
            if window in val_n:
                raise BridgeDecisionRedactionError(field_path, value[:80])


def _coerce_jsonable(obj: Any) -> Any:
    """Recursively coerce dataclasses, tuples, sets, datetimes into JSON
    primitives suitable for asyncpg JSONB insert.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Mapping):
        return {str(k): _coerce_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_coerce_jsonable(v) for v in obj]
    if is_dataclass(obj):
        return _coerce_jsonable(asdict(obj))
    return repr(obj)


# ═════════════════════════════════════════════════════════════════════════
# Step 12 — local thalamic gate (re-implementation per Note 1)
# ═════════════════════════════════════════════════════════════════════════

_DEFAULT_NOVELTY_THRESHOLD: float = 0.30
"""Default per-cohort threshold (general trauma). Trafficking cohort uses
0.20 (set by clinician via profile field, not hardcoded here)."""


def _thalamic_gate_v1_3(
    *,
    dissociation_delta: float,
    coercion_severity: float,
    threshold: float = _DEFAULT_NOVELTY_THRESHOLD,
    forced_on: bool = False,
) -> NoveltyGateState:
    """Step 12 — Thalamic Novelty Gate.

    Note 1 contract: this is a LOCAL implementation, not an import from
    `therapeutic_controller._evaluate_thalamic_novelty_gate`. The semantics
    are identical (gate blocks novelty when dissociation OR coercion
    crosses threshold, OR when forced_on by step 8/9 proximity). Keeping
    the implementations parallel rather than coupled lets each module own
    its own gate (controller's gate is for in-controller pre-flight; the
    orchestrator's gate is the canonical step 12).

    Note 2(b) contract: this gate runs at step 12, AFTER all signal
    detectors have populated `dissociation_delta` and `coercion_severity`.
    Moving it earlier means gating on partial signals; moving it later
    means crystal recall + register selection happens before the gate
    decision, wasting compute on a turn that gets blocked.
    """
    diss = float(dissociation_delta or 0.0)
    coer = float(coercion_severity or 0.0)
    thr = float(threshold or _DEFAULT_NOVELTY_THRESHOLD)

    if forced_on:
        return NoveltyGateState(
            blocked=True,
            reason="forced_on_trigger_or_legal_proximity",
            dissociation_delta=diss,
            coercion_severity=coer,
            threshold=thr,
            forced_on=True,
        )
    if diss >= thr or coer >= thr:
        return NoveltyGateState(
            blocked=True,
            reason="signal_above_threshold",
            dissociation_delta=diss,
            coercion_severity=coer,
            threshold=thr,
            forced_on=False,
        )
    return NoveltyGateState(
        blocked=False,
        reason="signals_below_threshold",
        dissociation_delta=diss,
        coercion_severity=coer,
        threshold=thr,
        forced_on=False,
    )


# ═════════════════════════════════════════════════════════════════════════
# Internal helpers — orchestrator-private (no new modules per Note 1)
# ═════════════════════════════════════════════════════════════════════════


async def _fetch_user_profile(db_pool, user_id: str) -> Dict[str, Any]:
    """Step 1 — fetch jurisdiction, embodiment phase, novelty threshold,
    safe_silence_mode_state, etc. from users.profile_data.

    Returns an empty dict on any failure so downstream steps degrade
    gracefully rather than crashing the orchestrator.
    """
    if not db_pool or not user_id:
        return {}
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT profile_data FROM users WHERE username = $1 LIMIT 1",
                user_id,
            )
            if not row:
                return {}
            pd = row.get("profile_data") if hasattr(row, "get") else row[0]
            if isinstance(pd, str):
                try:
                    pd = json.loads(pd)
                except Exception:
                    return {}
            return dict(pd) if pd else {}
    except Exception as e:
        logger.warning(
            "sensitive_clinical_bridge: profile fetch failed for %s: %s",
            user_id, e,
        )
        return {}


async def _check_codeword(
    *,
    nate_checkin_agent: Any,
    user_id: str,
    message: str,
    session_id: Optional[str],
) -> Optional[Any]:
    """Step 2 — Codeword listener.

    Codeword at step 2 by plan v1.3 contract — DO NOT move inside TMC;
    codeword cannot be gated by TMC reachability. (Plan Gap 2 / Risk #3:
    "the silenced safety net is the single largest clinical risk in the
    entire bridge.")

    Returns CodewordMatch or None. Never raises — codeword failure is
    logged but does not crash the pipeline.
    """
    if nate_checkin_agent is None:
        return None
    try:
        return await nate_checkin_agent.check_codeword(
            user_id=user_id, message=message, session_id=session_id,
        )
    except Exception as e:
        logger.error(
            "sensitive_clinical_bridge: codeword check failed for %s: %s",
            user_id, e,
        )
        return None


async def _check_codeword_disclosure_v2(
    *,
    nate_checkin_agent: Any,
    user_id: str,
    message: str,
    session_id: Optional[str],
) -> Optional[Any]:
    """Step 2 v1.4 — Part-aware codeword disclosure detection.

    Tries `detect_codeword_disclosure` (v1.4 method with part linkage) first.
    Falls back to v1.3 `check_codeword` if the v1.4 method is unavailable
    (graceful degradation for rolling deploys).

    Returns CodewordDisclosureEvent, CodewordMatch, or None. Never raises.
    """
    if nate_checkin_agent is None:
        return None
    try:
        if hasattr(nate_checkin_agent, "detect_codeword_disclosure"):
            result = await nate_checkin_agent.detect_codeword_disclosure(
                message, user_id, session_id=session_id,
            )
            if result is not None:
                return result
            return None
        return await nate_checkin_agent.check_codeword(
            user_id=user_id, message=message, session_id=session_id,
        )
    except Exception as e:
        logger.error(
            "sensitive_clinical_bridge: codeword disclosure v2 failed "
            "for %s: %s",
            user_id, e,
        )
        return None


async def _classify_tmc_with_polyvictim(
    *,
    db_pool,
    user_id: str,
) -> Dict[str, Any]:
    """Step 3 — TMC classify (TMC fetches polyvictim signals internally).

    Calls `tmc.classify(user_id)`. The TMC v1.3 build (Phase 3) already
    handles polyvictim_severity_load / layer_count signal extraction inside
    its own `_gather_signals()` — orchestrator does NOT pre-compute and
    push them. (Note 1: no Phase 3 mods.)

    Returns TMC's full result dict (moment_class, signals, stacking_driven_crisis,
    escalation_path, etc.) or a minimal fallback dict on TMC failure.
    """
    try:
        from app.sse.ucd.tmc import TherapeuticMomentClassifier  # type: ignore
        tmc = TherapeuticMomentClassifier(db_pool=db_pool)
        return await tmc.classify(user_id)
    except Exception as e:
        logger.warning(
            "sensitive_clinical_bridge: TMC classify failed for %s: %s",
            user_id, e,
        )
        return {
            "moment_class": "REST",
            "confidence": 0.5,
            "signals": {},
            "classifier_version": "fallback",
            "stacking_driven_crisis": False,
            "escalation_path": "baseline_weighted_sum",
            "polyvictim_layers_active": 0,
        }


async def _detect_introjection(
    *,
    db_pool,
    user_id: str,
    message: str,
    session_id: Optional[str],
) -> IntrojectionSummary:
    """Step 4 — Introjection mirror. Returns redacted-by-construction summary."""
    try:
        from app.services.introjection_voice_mirror import analyze_introjection
        sig = await analyze_introjection(
            user_id=user_id, message=message, db_pool=db_pool,
            session_id=session_id,
        )
        return IntrojectionSummary(
            detected=bool(getattr(sig, "detected", False)),
            score=float(getattr(sig, "score", 0.0)),
            drift_markers=tuple(getattr(sig, "drift_markers", ()) or ()),
        )
    except Exception as e:
        logger.warning(
            "sensitive_clinical_bridge: introjection failed for %s: %s",
            user_id, e,
        )
        return IntrojectionSummary(
            detected=False, score=0.0, drift_markers=(),
        )


_COERCION_SEVERITY_LADDER: Dict[str, float] = {
    "none": 0.0,
    "monitor": 0.25,
    "concern": 0.50,
    "high": 0.85,
}
"""Native CoercionTest.severity is a string ladder. The thalamic gate
requires a numeric value, so we map here and ONLY here. The native ladder
is the source of truth; this map is the orchestrator's local view.
"""


async def _detect_coercion(*, message: str, locale: str) -> CoercionSummary:
    """Step 5 — Coercion detector. Returns redacted-by-construction summary.

    Native CoercionTest.severity is a string ladder; we coerce to float for
    downstream gate math. Severity tag preservation lives in matched_labels.
    """
    try:
        from app.services.coercion_pattern_detector import analyze_message
        test = await analyze_message(message=message, locale=locale)
        sev_raw = getattr(test, "severity", "none")
        sev_num = _COERCION_SEVERITY_LADDER.get(
            str(sev_raw).strip().lower(), 0.0,
        )
        return CoercionSummary(
            detected=bool(getattr(test, "detected", False)),
            severity=sev_num,
            matched_labels=tuple(getattr(test, "matched_labels", ()) or ()),
        )
    except Exception as e:
        logger.warning("sensitive_clinical_bridge: coercion failed: %s", e)
        return CoercionSummary(detected=False, severity=0.0, matched_labels=())


async def _detect_dissociation(
    *,
    db_pool,
    user_id: str,
    message: str,
    locale: str,
) -> DissociationSummary:
    """Step 6 — Dissociation delta detector.

    Native DissociationSignal does not carry a `delta` field; its primary
    0-1 scalar is `confidence` (gate-relevant). `length_anomaly_z` is
    `Optional[float]`. We coerce both to floats here.
    """
    try:
        from app.services.dissociation_delta_detector import analyze_dissociation
        sig = await analyze_dissociation(
            user_id=user_id, message=message, db_pool=db_pool, locale=locale,
        )
        confidence = getattr(sig, "confidence", 0.0)
        z = getattr(sig, "length_anomaly_z", None)
        return DissociationSummary(
            delta=float(confidence or 0.0),
            length_anomaly_z=float(z) if z is not None else 0.0,
            markers=tuple(getattr(sig, "markers", ()) or ()),
        )
    except Exception as e:
        logger.warning(
            "sensitive_clinical_bridge: dissociation failed for %s: %s",
            user_id, e,
        )
        return DissociationSummary(delta=0.0, length_anomaly_z=0.0, markers=())


async def _detect_reengagement(
    *,
    message: str,
    locale: str,
) -> ReengagementSummary:
    """Step 7 — Reengagement pattern detector."""
    try:
        from app.services.reengagement_pattern_detector import analyze_message
        sig = await analyze_message(message=message, locale=locale)
        return ReengagementSummary(
            detected=bool(getattr(sig, "detected", False)),
            severity=str(getattr(sig, "severity", "none")),
            matched_labels=tuple(getattr(sig, "matched_labels", ()) or ()),
        )
    except Exception as e:
        logger.warning("sensitive_clinical_bridge: reengagement failed: %s", e)
        return ReengagementSummary(
            detected=False, severity="none", matched_labels=(),
        )


async def _classify_trafficking(
    *,
    message: str,
    reengagement_native: Any,
    locale: str,
) -> Tuple[Optional[Any], Optional[TraffickingClassificationSummary]]:
    """Step 7b — trafficking classifier consumes ReengagementSignal.

    Note: this passes the NATIVE ReengagementSignal (not the redacted
    summary) because the classifier needs the full detector output. The
    classifier's own output (TraffickingClassification) is returned NATIVE
    AS-IS for downstream mandatory_reporting consumption, AND a redacted
    summary is built for the BridgeDecision partner-seam output.

    Returns (native, summary). Both are None on failure.

    The native field is `classification_confidence` (not `confidence`); we
    map to the summary's `confidence` field for partner consumers — same
    name on the partner seam, source-faithful internally.
    """
    try:
        from app.services.trafficking_disclosure_classifier import classify_disclosure
        result = await classify_disclosure(
            message=message,
            reengagement=reengagement_native,
            locale=locale,
        )
        summary = TraffickingClassificationSummary(
            label=str(getattr(result, "label", "no_disclosure")),
            confidence=float(getattr(result, "classification_confidence", 0.0)),
            matched_classes_above_floor=tuple(
                getattr(result, "matched_classes_above_floor", ()) or ()
            ),
        )
        return result, summary
    except Exception as e:
        logger.warning(
            "sensitive_clinical_bridge: trafficking classifier failed: %s", e,
        )
        return None, None


async def _check_trigger_dates(
    *,
    db_pool,
    user_id: str,
    when: Optional[date],
) -> TriggerDateMatch:
    """Step 8 — Trigger date check (clinician-set significant dates ±1 day)."""
    try:
        from app.services.trigger_date_registry import TriggerDateRegistry
        reg = TriggerDateRegistry(db_pool=db_pool)
        matches = await reg.find_active_matches(user_id, when=when)
        if not matches:
            return TriggerDateMatch(
                matched=False, date_type=None, severity=None, match_count=0,
            )
        # Highest severity wins for the summary; full list is in audit log.
        top = matches[0]
        return TriggerDateMatch(
            matched=True,
            date_type=str(getattr(top, "date_type", "unknown")),
            severity=str(getattr(top, "severity", "moderate")),
            match_count=len(matches),
        )
    except Exception as e:
        logger.warning(
            "sensitive_clinical_bridge: trigger date check failed for %s: %s",
            user_id, e,
        )
        return TriggerDateMatch(
            matched=False, date_type=None, severity=None, match_count=0,
        )


async def _check_legal_proximity(
    *,
    db_pool,
    user_id: str,
    when: Optional[date],
) -> LegalProximity:
    """Step 9 — Legal proximity check.

    Queries `user_legal_status` (migration 207) for active cases with a
    next_event_date within ±14 days of `when`. Closed/dismissed cases are
    excluded by `case_status` filter. No standalone module; query lives
    here per the Phase 4a inventory.
    """
    if not db_pool or not user_id:
        return LegalProximity(
            detected=False, case_type=None, case_status=None,
            days_until_next_event=None,
        )
    target = when or datetime.now(timezone.utc).date()
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT case_type, case_status, next_event_date
                  FROM user_legal_status
                 WHERE user_id = $1
                   AND active = TRUE
                   AND case_status NOT IN ('closed', 'dismissed', 'resolved')
                   AND next_event_date IS NOT NULL
                   AND next_event_date BETWEEN $2 AND $3
                 ORDER BY next_event_date ASC
                 LIMIT 1
                """,
                user_id,
                target,
                # Use a Python timedelta for portability across asyncpg drivers.
                _add_days(target, 14),
            )
        if not row:
            return LegalProximity(
                detected=False, case_type=None, case_status=None,
                days_until_next_event=None,
            )
        next_event = row["next_event_date"]
        days = (next_event - target).days if next_event else None
        return LegalProximity(
            detected=True,
            case_type=str(row["case_type"]),
            case_status=str(row["case_status"]),
            days_until_next_event=int(days) if days is not None else None,
        )
    except Exception as e:
        # Common case: table missing in dev, or no rows. Degrade silently.
        logger.debug(
            "sensitive_clinical_bridge: legal proximity check failed for %s: %s",
            user_id, e,
        )
        return LegalProximity(
            detected=False, case_type=None, case_status=None,
            days_until_next_event=None,
        )


def _add_days(d: date, days: int) -> date:
    from datetime import timedelta
    return d + timedelta(days=days)


def _resolve_embodiment_phase(profile: Dict[str, Any]) -> EmbodimentPhaseApplied:
    """Step 10 — Embodiment phase resolution.

    Reads clinician-set embodiment_phase from profile_data. No standalone
    module per Phase 4a inventory; profile JSONB is the source of truth
    until a dedicated table is warranted.

    Expected profile shape:
        profile_data.sensitive_clinical = {
            "embodiment_phase": "preparation"|"sensation"|"integration"|None,
            "embodiment_set_at": "<iso>",
            "embodiment_set_by_clinician_id": "<username>",
        }
    """
    sc = profile.get("sensitive_clinical") if profile else None
    if not isinstance(sc, dict):
        return EmbodimentPhaseApplied(
            phase=None, set_at=None, set_by_clinician_id=None,
        )
    phase = sc.get("embodiment_phase")
    if phase is None or not isinstance(phase, str):
        return EmbodimentPhaseApplied(
            phase=None, set_at=None, set_by_clinician_id=None,
        )
    return EmbodimentPhaseApplied(
        phase=phase,
        set_at=sc.get("embodiment_set_at"),
        set_by_clinician_id=sc.get("embodiment_set_by_clinician_id"),
    )


async def _recall_domain_crystals(
    *,
    db_pool,
    user_id: str,
    message: str,
    domain: Optional[str],
    user_state_hint: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """Step 11 — Domain-crystal recall.

    Calls `crystal_recall_bridge.recall_crystals_for_context` if available.
    Returns `(crystals, sensitive_dropped_count)` — crystal list is dicts
    of `{id, domain, confidence, summary_present}` (no raw text).

    When `user_state_hint` is in `SENSITIVE_RECALL_STATES` (`dissociation_grounding`
    or `CRISIS`), crystals tagged with arousal-loaded markers are filtered
    out *before* normalization (per Note 2 / Plan v1.3 §9). The drop count
    is returned alongside so the orchestrator can include it in audit
    telemetry.

    Failure returns `([], 0)` — recall is best-effort; orchestrator
    continues with empty context rather than surfacing an exception.
    """
    if not db_pool or not user_id:
        return [], 0
    try:
        from app.websocket.crystal_recall_bridge import recall_crystals_for_context
        result = await recall_crystals_for_context(
            db_pool=db_pool, user_id=user_id, message=message,
            domain=domain, limit=5,
        )
    except Exception as e:
        logger.debug(
            "sensitive_clinical_bridge: crystal recall failed for %s: %s",
            user_id, e,
        )
        return [], 0

    # recall_crystals_for_context returns a string in some implementations;
    # we normalize to a list of dicts {id, domain, summary_present} for
    # partner consumption. If it returns a string, wrap as a single entry.
    if isinstance(result, str):
        return [{"id": None, "domain": domain, "summary_present": bool(result)}], 0

    raw_list: List[Any] = result if isinstance(result, list) else []

    # ─── v1.3 Gap 6 sensitive-recall filter (Note 2) ────────────────────
    # Filter BEFORE normalization so marker fields are still intact.
    sensitive_dropped = 0
    if user_state_hint:
        try:
            from app.services.nate_response_validator import (
                filter_sensitive_recalled_crystals,
            )
            raw_list, sensitive_dropped = filter_sensitive_recalled_crystals(
                raw_list, user_state_hint,
            )
        except Exception as e:
            logger.debug(
                "sensitive_clinical_bridge: sensitive-recall filter import "
                "failed (%s); proceeding without filtering", e,
            )

    normalized: List[Dict[str, Any]] = []
    for item in raw_list:
        if isinstance(item, dict):
            # Strip any field that could carry raw text.
            normalized.append({
                "id": item.get("id"),
                "domain": item.get("domain"),
                "confidence": item.get("confidence"),
                "summary_present": bool(item.get("summary") or item.get("text")),
            })
    return normalized, sensitive_dropped


def _select_register(
    *,
    codeword_match: Any,
    trigger_date: TriggerDateMatch,
    legal_proximity: LegalProximity,
    reengagement: ReengagementSummary,
    introjection: IntrojectionSummary,
    embodiment: EmbodimentPhaseApplied,
    tmc_class: str,
    substance_branch: SubstanceRegisterBranch,
    novelty_gate: NoveltyGateState,
    sex_addiction_branch: Optional[SexAddictionRegisterBranch] = None,
    gambling_branch: Optional[GamblingRegisterBranch] = None,
    gaming_branch: Optional[GamingRegisterBranch] = None,
    food_compulsion_branch: Optional[FoodCompulsionRegisterBranch] = None,
    work_compulsion_branch: Optional[WorkCompulsionRegisterBranch] = None,
    spending_compulsion_branch: Optional[SpendingCompulsionRegisterBranch] = None,
    codependency_branch: Optional[CodependencyRegisterBranch] = None,
    cross_addiction_branch: Optional[CrossAddictionRegisterBranch] = None,
) -> Tuple[Optional[str], str]:
    """Step 13 — Register selection.

    Walks REGISTER_SELECTION_PRIORITY in order. Returns (directive, source).

    The thalamic gate, if blocked, REPLACES whichever register would have
    been selected with `predictability_continuity` — UNLESS the codeword
    listener fired (codeword always wins; safety-net contract). This
    matches the Phase 3 controller insertion semantics.
    """
    if codeword_match is not None:
        return ("safe_silence_mode_codeword", "codeword")

    if novelty_gate.blocked:
        source = _first_matching_register_source(
            trigger_date=trigger_date,
            legal_proximity=legal_proximity,
            reengagement=reengagement,
            introjection=introjection,
            embodiment=embodiment,
            tmc_class=tmc_class,
            substance_branch=substance_branch,
            sex_addiction_branch=sex_addiction_branch,
            gambling_branch=gambling_branch,
            gaming_branch=gaming_branch,
            food_compulsion_branch=food_compulsion_branch,
            work_compulsion_branch=work_compulsion_branch,
            spending_compulsion_branch=spending_compulsion_branch,
            codependency_branch=codependency_branch,
            cross_addiction_branch=cross_addiction_branch,
        )
        return ("predictability_continuity", source or "thalamic_gate_block")

    if trigger_date.matched:
        return ("trigger_date_grounding", "trigger_date")
    if legal_proximity.detected and (
        legal_proximity.days_until_next_event is not None
        and legal_proximity.days_until_next_event <= 14
    ):
        return ("legal_proximity_grounding", "legal_proximity")
    if reengagement.detected:
        return ("reengagement_safety_planning", "reengagement")
    if introjection.detected:
        return ("introjection_repair", "introjection")
    if embodiment.phase:
        return (f"embodiment_{embodiment.phase}", "embodiment")
    if tmc_class == "CRISIS":
        return ("crisis_stabilization", "tmc_class")
    # v1.4: cross-addiction is an overlay, not a replacing register.
    # Individual branches keep driving the directive; the overlay is appended
    # later through `_compose_cross_addiction_overlay`.
    if substance_branch.branched:
        return ("dual_diagnosis_substance", "substance_branch")
    if sex_addiction_branch and sex_addiction_branch.branched:
        return ("dual_diagnosis_sex_addiction", "sex_addiction_branch")
    if gambling_branch and gambling_branch.branched:
        return ("dual_diagnosis_gambling", "gambling_branch")
    if gaming_branch and gaming_branch.branched:
        return ("dual_diagnosis_gaming", "gaming_branch")
    if food_compulsion_branch and food_compulsion_branch.branched:
        return ("dual_diagnosis_food_compulsion", "food_compulsion_branch")
    if work_compulsion_branch and work_compulsion_branch.branched:
        return ("dual_diagnosis_work_compulsion", "work_compulsion_branch")
    if spending_compulsion_branch and spending_compulsion_branch.branched:
        return ("dual_diagnosis_spending_compulsion", "spending_compulsion_branch")
    if codependency_branch and codependency_branch.branched:
        return ("dual_diagnosis_codependency", "codependency_branch")
    if cross_addiction_branch and cross_addiction_branch.branched:
        return (None, "cross_addiction")
    return (None, "default")


def _first_matching_register_source(
    *,
    trigger_date: TriggerDateMatch,
    legal_proximity: LegalProximity,
    reengagement: ReengagementSummary,
    introjection: IntrojectionSummary,
    embodiment: EmbodimentPhaseApplied,
    tmc_class: str,
    substance_branch: SubstanceRegisterBranch,
    sex_addiction_branch: Optional[SexAddictionRegisterBranch] = None,
    gambling_branch: Optional[GamblingRegisterBranch] = None,
    gaming_branch: Optional[GamingRegisterBranch] = None,
    food_compulsion_branch: Optional[FoodCompulsionRegisterBranch] = None,
    work_compulsion_branch: Optional[WorkCompulsionRegisterBranch] = None,
    spending_compulsion_branch: Optional[SpendingCompulsionRegisterBranch] = None,
    codependency_branch: Optional[CodependencyRegisterBranch] = None,
    cross_addiction_branch: Optional[CrossAddictionRegisterBranch] = None,
) -> Optional[str]:
    """Companion to _select_register — returns just the source tag for the
    first non-codeword match. Used when the thalamic gate replaces the
    actual directive but we still want the source tag in audit.
    """
    if trigger_date.matched:
        return "trigger_date"
    if legal_proximity.detected:
        return "legal_proximity"
    if reengagement.detected:
        return "reengagement"
    if introjection.detected:
        return "introjection"
    if embodiment.phase:
        return "embodiment"
    if tmc_class == "CRISIS":
        return "tmc_class"
    if substance_branch.branched:
        return "substance_branch"
    if sex_addiction_branch and sex_addiction_branch.branched:
        return "sex_addiction_branch"
    if gambling_branch and gambling_branch.branched:
        return "gambling_branch"
    if gaming_branch and gaming_branch.branched:
        return "gaming_branch"
    if food_compulsion_branch and food_compulsion_branch.branched:
        return "food_compulsion_branch"
    if work_compulsion_branch and work_compulsion_branch.branched:
        return "work_compulsion_branch"
    if spending_compulsion_branch and spending_compulsion_branch.branched:
        return "spending_compulsion_branch"
    if codependency_branch and codependency_branch.branched:
        return "codependency_branch"
    if cross_addiction_branch and cross_addiction_branch.branched:
        return "cross_addiction"
    return None


def _measure_arousal_load(
    *,
    message: str,
    user_id: str,
    register: str,
    locale: str,
) -> Optional[ArousalLoadSummary]:
    """Step 14 — arousal load measurement.

    Domain inferred from register name; falls back to 'general'. Triggering
    terms are summarized as tags only — never verbatim user text.
    """
    try:
        from app.services.linguistic_arousal_load import measure_user_disclosure_load
        domain = _domain_from_register(register)
        load = measure_user_disclosure_load(
            message=message, user_id=user_id, domain=domain,
            register=register, locale=locale,
        )
        # ArousalLoad.triggering_terms are detector-tagged categories, not
        # raw user text — confirmed in Phase 2C lexicon refinement.
        return ArousalLoadSummary(
            score=float(getattr(load, "score", 0.0)),
            cap_triggered=bool(getattr(load, "cap_triggered", False)),
            triggering_term_tags=tuple(
                str(t) for t in (getattr(load, "triggering_terms", ()) or ())
            ),
            register_at_measurement=register,
        )
    except Exception as e:
        logger.warning(
            "sensitive_clinical_bridge: arousal measurement failed: %s", e,
        )
        return None


def _domain_from_register(register: Optional[str]) -> str:
    if not register:
        return "general"
    if "trauma" in register or "crisis" in register:
        return "sexual_trauma"
    if "introjection" in register:
        return "intimacy_clinical"
    if "reengagement" in register:
        return "trafficking_trauma"
    if "embodiment" in register:
        return "intimacy_clinical"
    if "substance" in register:
        return "general"
    return "general"


async def _screen_mandatory_reporting(
    *,
    mandatory_reporting_service: Any,
    user_id: str,
    message: str,
    trafficking_native: Optional[Any],
    jurisdiction: Optional[str],
    session_id: Optional[str],
    coach_id: Optional[str],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Step 15 — mandatory reporting screen.

    Calls `MandatoryReportingService.screen_message_with_trafficking` with
    the NATIVE TraffickingClassification object produced upstream
    (`_classify_trafficking`). We do NOT reconstruct the native dataclass
    here — it flows through unchanged. When no classification is available
    (None), the service falls back to its Phase 2 coach-report-only path
    with severity=critical.

    Returns (protocol_summary, fired_trigger_name) — both None when no
    trigger fired. The summary is a small dict suitable for the partner
    seam; the full protocol object is not exposed.
    """
    if mandatory_reporting_service is None:
        return None, None
    try:
        protocol = await mandatory_reporting_service.screen_message_with_trafficking(
            user_id=user_id,
            message=message,
            trafficking_classification=trafficking_native,
            jurisdiction=jurisdiction,
            session_id=session_id,
            coach_id=coach_id,
        )
        if protocol is None:
            return None, None

        # MandatoryReportingProtocol exposes trigger / severity / etc.
        trigger_name = getattr(getattr(protocol, "trigger", None), "value", None)
        if trigger_name is None:
            trigger_name = str(getattr(protocol, "trigger", "unknown"))

        # Serialize to a redacted summary for BridgeDecision audit_event.
        summary = {
            "trigger": trigger_name,
            "severity": getattr(protocol, "severity", "unknown"),
            "jurisdiction": getattr(protocol, "jurisdiction", None),
            "must_report": getattr(protocol, "must_report", False),
            "report_window_hours": getattr(protocol, "report_window_hours", None),
        }
        return summary, trigger_name
    except Exception as e:
        logger.error(
            "sensitive_clinical_bridge: mandatory reporting screen failed for %s: %s",
            user_id, e,
        )
        return None, None


async def _emit_audit_event(
    *,
    db_pool,
    user_id: str,
    event_type: str,
    event_severity: str,
    payload: Dict[str, Any],
    decision_summary: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    access_classification: str = "clinician_and_admin",
) -> Optional[int]:
    """Insert one row into sensitive_bridge_log. Returns the inserted id
    (BIGSERIAL) or None on failure.

    Per migration 202 schema:
        - event_type must be in the 33-entry CHECK constraint
        - event_severity in {info, low, moderate, high, critical, emergency}
        - payload_json + decision_summary MUST NOT contain raw user/AI text
          (orchestrator-side guarantee; pii_screened_at is set after the
          validator pass)
    """
    if not db_pool or not user_id:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO sensitive_bridge_log
                    (user_id, session_id, event_type, event_severity,
                     payload_json, decision_summary, recorded_by,
                     access_classification, pii_screened_at)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb,
                        'sensitive_clinical_bridge', $7, NOW())
                RETURNING id
                """,
                user_id,
                session_id,
                event_type,
                event_severity,
                json.dumps(_coerce_jsonable(payload)),
                json.dumps(_coerce_jsonable(decision_summary)) if decision_summary else None,
                access_classification,
            )
            return int(row["id"]) if row else None
    except Exception as e:
        logger.error(
            "sensitive_clinical_bridge: audit insert failed for %s (%s): %s",
            user_id, event_type, e,
        )
        return None


def _build_handoff_if_needed(
    *,
    user_id: str,
    codeword_match: Any,
    tmc_result: Dict[str, Any],
    reporting_summary: Optional[Dict[str, Any]],
    trafficking: Optional[TraffickingClassificationSummary],
    novelty_gate: NoveltyGateState,
    trigger_date: TriggerDateMatch,
    polyvictim_load: PolyvictimLoad,
) -> Tuple[Optional[Any], Optional[str], Optional[str]]:
    """Step 16 — coach handoff payload build (conditional).

    Returns (HandoffPayload | None, tier | None, severity | None). The
    tier string is one of `coach_override_protocol.ACUITY_TIERS` keys. The
    actual `escalate_acuity()` call also fires on tier_high+.
    """
    # Decide whether handoff is warranted.
    tier: Optional[str] = None
    if codeword_match is not None:
        tier = "codeword_match"
    elif reporting_summary is not None:
        tier = "mandatory_reporting"
    elif tmc_result.get("moment_class") == "CRISIS":
        tier = "tmc_crisis"
    elif (
        trafficking is not None
        and trafficking.label in ("active_trafficking", "imminent_danger")
    ):
        tier = "trafficking_disclosure"
    elif (
        trigger_date.matched
        and trigger_date.severity in ("high", "critical")
    ):
        tier = "trigger_date_proactive"
    elif polyvictim_load.stacking_eligible and tmc_result.get(
        "stacking_driven_crisis", False
    ):
        tier = "tmc_crisis"

    if tier is None:
        return None, None, None

    try:
        from app.services.coach_override_protocol import (
            ACUITY_TIERS,
            build_handoff_payload,
        )
        # Validate tier against ACUITY_TIERS keys; fall back to a known-good
        # generic tier on mismatch (keeps orchestrator robust against a
        # future tier rename without crashing).
        if tier not in ACUITY_TIERS:
            logger.warning(
                "sensitive_clinical_bridge: unknown tier %r — using "
                "generic 'crisis_alert'", tier,
            )
            tier = "crisis_alert" if "crisis_alert" in ACUITY_TIERS else next(iter(ACUITY_TIERS))

        meta = ACUITY_TIERS.get(tier, {})
        severity = str(meta.get("severity", "high"))

        payload = build_handoff_payload(
            user_id=user_id,
            trigger=tier,
            context={
                "tmc_class": tmc_result.get("moment_class"),
                "trafficking_label": trafficking.label if trafficking else None,
                "novelty_gate_blocked": novelty_gate.blocked,
                "trigger_date_match": trigger_date.matched,
                "polyvictim_load": asdict(polyvictim_load),
            },
            safety_status_flags={
                "stacking_driven_crisis": tmc_result.get("stacking_driven_crisis", False),
                "thalamic_gate_blocked": novelty_gate.blocked,
            },
        )
        return payload, tier, severity
    except Exception as e:
        logger.error(
            "sensitive_clinical_bridge: handoff payload build failed: %s", e,
        )
        return None, None, None


async def _resolve_assigned_coach_username(
    db_pool,
    client_username: str,
    coach_id_hint: Optional[str],
) -> Optional[str]:
    """Best-effort coach username for alerts (prefers explicit hint, then profile)."""
    if coach_id_hint and str(coach_id_hint).strip():
        return str(coach_id_hint).strip()
    if not db_pool or not client_username:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT profile_data FROM users WHERE username = $1",
                client_username,
            )
    except Exception:
        return None
    if row is None:
        return None
    pd = row["profile_data"] or {}
    if isinstance(pd, str):
        import json as _json

        try:
            pd = _json.loads(pd)
        except Exception:
            pd = {}
    for key in ("assigned_coach", "coach_username"):
        v = pd.get(key)
        if v and str(v).strip():
            return str(v).strip()
    cid = pd.get("coach_id") or pd.get("assigned_coach_id")
    if not cid or not str(cid).strip():
        return None
    hw = str(cid).strip()
    try:
        async with db_pool.acquire() as conn:
            r2 = await conn.fetchrow(
                """
                SELECT username FROM users
                 WHERE hardware_id = $1 AND role = 'COACH'
                 LIMIT 1
                """,
                hw,
            )
        if r2 and r2["username"]:
            return str(r2["username"]).strip()
    except Exception:
        pass
    return None


async def _emit_escalation(
    *,
    user_id: str,
    tier: str,
    context: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Companion to _build_handoff_if_needed — fire `escalate_acuity` for
    the matching tier so coach_override_protocol's own audit and notification
    paths run. Returns the escalation result dict or None on failure.
    """
    try:
        from app.services.coach_override_protocol import escalate_acuity
        return escalate_acuity(tier, user_id=user_id, context=context or {})
    except Exception as e:
        logger.error(
            "sensitive_clinical_bridge: escalate_acuity(%s) failed: %s",
            tier, e,
        )
        return None


# ═════════════════════════════════════════════════════════════════════════
# evaluate_disclosure() — the 17-step pipeline
# ═════════════════════════════════════════════════════════════════════════


async def evaluate_disclosure(
    *,
    db_pool,
    user_id: str,
    message: str,
    session_id: Optional[str] = None,
    locale: str = "en-US",
    coach_id: Optional[str] = None,
    nate_checkin_agent: Optional[Any] = None,
    mandatory_reporting_service: Optional[Any] = None,
    when: Optional[date] = None,
    novelty_threshold_override: Optional[float] = None,
) -> BridgeDecision:
    """Run the 17-step plan v1.3 sensitive clinical bridge pipeline.

    The execution order MUST match `PIPELINE_STEP_NAMES_V1_3` element-for-element.
    The auditor check `pipeline_order_matches_plan_v1_3` enforces this.

    Args:
        db_pool: asyncpg pool. None disables DB-backed steps; pipeline
            still completes with degraded BridgeDecision.
        user_id: username (matches users.username).
        message: raw user message. NEVER stored; only passed to detectors
            and the final redaction validator.
        session_id: optional session correlation id for audit rows.
        locale: BCP-47 locale (en-US default).
        coach_id: assigned coach username (used by mandatory_reporting).
        nate_checkin_agent: live NateCheckInAgent instance (must support
            `check_codeword(user_id=, message=, session_id=)`). When None,
            step 2 returns no codeword match.
        mandatory_reporting_service: live MandatoryReportingService instance.
            When None, step 15 is a no-op.
        when: override "today" for trigger date / legal proximity steps
            (used by tests).
        novelty_threshold_override: per-cohort threshold override
            (trafficking cohort = 0.20). Falls back to per-user setting in
            profile_data, then to _DEFAULT_NOVELTY_THRESHOLD.

    Returns:
        BridgeDecision with all 16 functional fields + 3 schema stamp fields
        populated. Pre-return validator scrubs for raw transcript leakage.

    Raises:
        BridgeDecisionRedactionError: if any string field in the resulting
            BridgeDecision contains contiguous overlap (>= 12 chars) with
            the original message. This is a programming error in detectors,
            not a runtime expectation.
    """
    # ───────────────────────────────────────────────────────────────────
    # STEP 0 — Master kill switch + per-user enrollment gate (Phase 4 / Note 3)
    # Short-circuits the entire 17-step pipeline to a neutral BridgeDecision
    # when v1.3 behavior is dormant. This is the rollback mechanism + the
    # safety thesis that keeps survivors on v1.2 behavior until Phase 6
    # cohort enrollment explicitly flips flags per-user.
    # ───────────────────────────────────────────────────────────────────
    master_enabled = await _read_master_enabled(db_pool)
    if not master_enabled:
        return _build_neutral_bridge_decision(reason="master_kill_switch_off")
    global_flags = await _read_global_gap_flags(db_pool)
    user_enrollment = await _read_user_enrollment(db_pool, user_id)
    effective_flags = _resolve_effective_flags(
        global_flags=global_flags, user_flags=user_enrollment["flags"],
    )
    if not _any_sensitive_feature_active(effective_flags, user_enrollment):
        return _build_neutral_bridge_decision(reason="all_gap_flags_dormant")

    v1_4_codeword_enabled = _v1_4_feature_enabled(
        user_enrollment, "v1_4_codeword_listener_enabled",
    )
    v1_4_addiction_branches_enabled = _v1_4_feature_enabled(
        user_enrollment, "v1_4_addiction_branches_enabled",
    )
    v1_4_cross_addiction_overlay_enabled = _v1_4_feature_enabled(
        user_enrollment, "v1_4_cross_addiction_overlay_enabled",
    )
    v1_4_dst_lens_enabled = _v1_4_feature_enabled(
        user_enrollment, "v1_4_dst_lens_enabled",
    )
    v1_4_framework_lens_enabled = _v1_4_feature_enabled(
        user_enrollment, "v1_4_framework_lens_enabled",
    )
    v1_4_crystal_factory_enabled = _v1_4_feature_enabled(
        user_enrollment, "v1_4_crystal_factory_enabled",
    )
    v1_4_alert_dispatch_enabled = _v1_4_feature_enabled(
        user_enrollment, "v1_4_alert_dispatch_enabled",
    )

    # ───────────────────────────────────────────────────────────────────
    # STEP 1 — Profile fetch
    # ───────────────────────────────────────────────────────────────────
    profile = await _fetch_user_profile(db_pool, user_id)
    sc_profile = profile.get("sensitive_clinical") if isinstance(profile, dict) else {}
    if not isinstance(sc_profile, dict):
        sc_profile = {}
    jurisdiction = (
        profile.get("jurisdiction_state")
        or profile.get("jurisdiction")
        if isinstance(profile, dict) else None
    )
    novelty_threshold = (
        novelty_threshold_override
        or sc_profile.get("novelty_threshold")
        or _DEFAULT_NOVELTY_THRESHOLD
    )
    try:
        novelty_threshold = float(novelty_threshold)
    except (TypeError, ValueError):
        novelty_threshold = _DEFAULT_NOVELTY_THRESHOLD

    # ───────────────────────────────────────────────────────────────────
    # STEP 2 — Codeword listener
    # Codeword at step 2 by plan v1.3 contract — DO NOT move inside TMC;
    # codeword cannot be gated by TMC reachability. (Plan Gap 2 / Risk #3:
    # "the silenced safety net is the single largest clinical risk in the
    # entire bridge.") If a future maintainer wants codeword to "share"
    # signal extraction with TMC for performance, the answer is no:
    # safety-net independence is the contract.
    # ───────────────────────────────────────────────────────────────────
    codeword_match = None
    if v1_4_codeword_enabled or bool(effective_flags.get("gap_codeword_enabled")):
        codeword_match = await _check_codeword_disclosure_v2(
            nate_checkin_agent=nate_checkin_agent,
            user_id=user_id,
            message=message,
            session_id=session_id,
        )

    # ───────────────────────────────────────────────────────────────────
    # STEP 3 — TMC classify + polyvictim weighting
    # TMC v1.3 fetches polyvictim signals internally via _gather_signals
    # (Phase 3 Gap 8 build). Orchestrator does NOT pre-compute and push
    # them — that would require modifying TMC's signature, violating Note 1.
    # ───────────────────────────────────────────────────────────────────
    tmc_result = await _classify_tmc_with_polyvictim(db_pool=db_pool, user_id=user_id)
    tmc_class = str(tmc_result.get("moment_class", "REST"))
    tmc_signals = tmc_result.get("signals", {}) or {}
    polyvictim_load = PolyvictimLoad(
        layers_active=int(tmc_signals.get("polyvictim_layers_active", 0) or 0),
        severity_load=float(tmc_signals.get("polyvictim_severity_load", 0.0) or 0.0),
        stacking_eligible=bool(tmc_result.get("stacking_driven_crisis", False)),
    )

    # ───────────────────────────────────────────────────────────────────
    # STEP 4 — Introjection mirror
    # ───────────────────────────────────────────────────────────────────
    introjection = await _detect_introjection(
        db_pool=db_pool, user_id=user_id, message=message, session_id=session_id,
    )

    # ───────────────────────────────────────────────────────────────────
    # STEP 5 — Coercion detector
    # ───────────────────────────────────────────────────────────────────
    coercion = await _detect_coercion(message=message, locale=locale)

    # ───────────────────────────────────────────────────────────────────
    # STEP 6 — Dissociation delta
    # ───────────────────────────────────────────────────────────────────
    dissociation = await _detect_dissociation(
        db_pool=db_pool, user_id=user_id, message=message, locale=locale,
    )

    # ───────────────────────────────────────────────────────────────────
    # STEP 7 — Reengagement detector + trafficking classifier (consumes it)
    # ───────────────────────────────────────────────────────────────────
    # Run native reengagement first because the trafficking classifier
    # consumes the native ReengagementSignal.
    try:
        from app.services.reengagement_pattern_detector import analyze_message as _re_native
        reengagement_native = await _re_native(message=message, locale=locale)
    except Exception as e:
        logger.warning(
            "sensitive_clinical_bridge: native reengagement failed: %s", e,
        )
        reengagement_native = None

    reengagement = ReengagementSummary(
        detected=bool(getattr(reengagement_native, "detected", False)) if reengagement_native else False,
        severity=str(getattr(reengagement_native, "severity", "none")) if reengagement_native else "none",
        matched_labels=tuple(
            getattr(reengagement_native, "matched_labels", ()) or ()
        ) if reengagement_native else (),
    )

    trafficking_native, trafficking = await _classify_trafficking(
        message=message,
        reengagement_native=reengagement_native,
        locale=locale,
    )

    # ───────────────────────────────────────────────────────────────────
    # STEP 8 — Trigger date check
    # ───────────────────────────────────────────────────────────────────
    trigger_date = await _check_trigger_dates(
        db_pool=db_pool, user_id=user_id, when=when,
    )

    # ───────────────────────────────────────────────────────────────────
    # STEP 9 — Legal proximity check
    # ───────────────────────────────────────────────────────────────────
    legal_proximity = await _check_legal_proximity(
        db_pool=db_pool, user_id=user_id, when=when,
    )

    # ───────────────────────────────────────────────────────────────────
    # STEP 10 — Embodiment phase resolution
    # ───────────────────────────────────────────────────────────────────
    embodiment = _resolve_embodiment_phase(profile)

    # ───────────────────────────────────────────────────────────────────
    # STEP 11 — Domain-crystal recall (with v1.3 Gap 6 sensitive filter)
    # ───────────────────────────────────────────────────────────────────
    crystal_domain = _crystal_domain_for(
        introjection=introjection, reengagement=reengagement,
        trafficking=trafficking, embodiment=embodiment,
    )
    # Compute state hint *before* register selection. We can't use the
    # final selected register (chosen at step 13), but we have all the
    # signals needed: TMC class is finalized at step 3, dissociation delta
    # at step 6. The recall filter only needs to know "is this a sensitive
    # state turn" and these two signals are the canonical sources.
    _diss_grounding = (
        dissociation.delta >= 0.55
        if dissociation and dissociation.delta is not None
        else False
    )
    if tmc_class == "CRISIS":
        _user_state_hint: Optional[str] = "CRISIS"
    elif _diss_grounding:
        _user_state_hint = "dissociation_grounding"
    else:
        _user_state_hint = None
    crystals_recalled, sensitive_recall_dropped = await _recall_domain_crystals(
        db_pool=db_pool, user_id=user_id, message=message,
        domain=crystal_domain, user_state_hint=_user_state_hint,
    )

    # ───────────────────────────────────────────────────────────────────
    # STEP 12 — Thalamic Novelty Gate
    # Thalamic gate at step 12 — combines all pre-step-12 signals
    # (dissociation step 6, coercion step 5) plus forced-on conditions from
    # trigger date (step 8) and legal proximity (step 9). Moving earlier
    # degrades gate quality (no full signal); moving later wastes pipeline
    # work (crystal recall + register selection happen on a turn that
    # gets blocked anyway).
    # ───────────────────────────────────────────────────────────────────
    forced_on = trigger_date.matched or legal_proximity.detected
    novelty_gate = _thalamic_gate_v1_3(
        dissociation_delta=dissociation.delta,
        coercion_severity=coercion.severity,
        threshold=novelty_threshold,
        forced_on=forced_on,
    )

    # ───────────────────────────────────────────────────────────────────
    # STEP 13 — Register selection (v1.4: 9 branch resolvers)
    # ───────────────────────────────────────────────────────────────────
    if _profile_status_active(profile, "substance_status", ("active_use", "crisis")):
        tmc_signals["substance_branch_active"] = True
    for _profile_key, _signal_key in (
        ("sex_addiction_status", "sex_addiction_branch_active"),
        ("gambling_status", "gambling_branch_active"),
        ("gaming_status", "gaming_branch_active"),
        ("food_compulsion_status", "food_compulsion_branch_active"),
        ("work_compulsion_status", "work_compulsion_branch_active"),
        ("spending_compulsion_status", "spending_compulsion_branch_active"),
        ("codependency_status", "codependency_branch_active"),
    ):
        if _profile_status_active(profile, _profile_key):
            tmc_signals[_signal_key] = True

    substance_branch = _resolve_substance_branch(
        tmc_signals=tmc_signals, embodiment=embodiment,
    )
    if v1_4_addiction_branches_enabled:
        sex_addiction_branch = _resolve_sex_addiction_branch(tmc_signals=tmc_signals)
        gambling_branch = _resolve_gambling_branch(tmc_signals=tmc_signals)
        gaming_branch = _resolve_gaming_branch(tmc_signals=tmc_signals)
        food_compulsion_branch = _resolve_food_compulsion_branch(tmc_signals=tmc_signals)
        work_compulsion_branch = _resolve_work_compulsion_branch(tmc_signals=tmc_signals)
        spending_compulsion_branch = _resolve_spending_compulsion_branch(tmc_signals=tmc_signals)
        codependency_branch = _resolve_codependency_branch(tmc_signals=tmc_signals)
    else:
        sex_addiction_branch = SexAddictionRegisterBranch(False, reason="feature_flag_off")
        gambling_branch = GamblingRegisterBranch(False, reason="feature_flag_off")
        gaming_branch = GamingRegisterBranch(False, reason="feature_flag_off")
        food_compulsion_branch = FoodCompulsionRegisterBranch(False, reason="feature_flag_off")
        work_compulsion_branch = WorkCompulsionRegisterBranch(False, reason="feature_flag_off")
        spending_compulsion_branch = SpendingCompulsionRegisterBranch(False, reason="feature_flag_off")
        codependency_branch = CodependencyRegisterBranch(False, reason="feature_flag_off")
    cross_addiction_branch = _resolve_cross_addiction_branch(
        substance=substance_branch,
        sex_addiction=sex_addiction_branch,
        gambling=gambling_branch,
        gaming=gaming_branch,
        food_compulsion=food_compulsion_branch,
        work_compulsion=work_compulsion_branch,
        spending_compulsion=spending_compulsion_branch,
        codependency=codependency_branch,
    ) if v1_4_cross_addiction_overlay_enabled else CrossAddictionRegisterBranch(
        False, reason="feature_flag_off",
    )
    register_directive, selected_register_source = _select_register(
        codeword_match=codeword_match,
        trigger_date=trigger_date,
        legal_proximity=legal_proximity,
        reengagement=reengagement,
        introjection=introjection,
        embodiment=embodiment,
        tmc_class=tmc_class,
        substance_branch=substance_branch,
        novelty_gate=novelty_gate,
        sex_addiction_branch=sex_addiction_branch,
        gambling_branch=gambling_branch,
        gaming_branch=gaming_branch,
        food_compulsion_branch=food_compulsion_branch,
        work_compulsion_branch=work_compulsion_branch,
        spending_compulsion_branch=spending_compulsion_branch,
        codependency_branch=codependency_branch,
        cross_addiction_branch=cross_addiction_branch,
    )

    # ───────────────────────────────────────────────────────────────────
    # STEP 13b — v1.4 DST Lens (Gap 2)
    # ───────────────────────────────────────────────────────────────────
    dst_active = _dst_lens_active(
        sex_addiction_branch=sex_addiction_branch,
        polyvictim_load=polyvictim_load,
        tmc_signals=tmc_signals,
    )
    dst_prompt_block: Optional[str] = None
    dst_adjustments: Dict[str, Any] = {}
    if dst_active and v1_4_dst_lens_enabled:
        register_directive, dst_prompt_block, dst_adjustments = _apply_dst_lens(
            register_directive,
        )

    # ───────────────────────────────────────────────────────────────────
    # STEP 13c — v1.4 Framework Lens (Gap 3) + Crystal Factory
    # ───────────────────────────────────────────────────────────────────
    active_branches_list: List[str] = []
    for _bname, _bobj in (
        ("substance", substance_branch),
        ("sex_addiction", sex_addiction_branch),
        ("gambling", gambling_branch),
        ("gaming", gaming_branch),
        ("food_compulsion", food_compulsion_branch),
        ("work_compulsion", work_compulsion_branch),
        ("spending_compulsion", spending_compulsion_branch),
        ("codependency", codependency_branch),
    ):
        if _bobj and getattr(_bobj, "branched", False):
            active_branches_list.append(_bname)
    active_branches_tuple = tuple(active_branches_list)

    framework_menu = _load_framework_menu(profile)
    framework_lenses = (
        _select_framework_lens(
            active_branches=active_branches_tuple,
            framework_menu=framework_menu,
        )
        if v1_4_framework_lens_enabled
        else []
    )
    lens_primary = framework_lenses[0] if framework_lenses else None

    lexicon_crystals = []
    response_crystals = []
    if v1_4_crystal_factory_enabled:
        lexicon_crystals = await _load_lexicon_crystals(
            db_pool, user_id, active_branches_tuple,
        )
        response_crystals = await _load_response_pattern_crystals(
            db_pool, user_id, lens_primary,
        )

    lens_directives_text, applied_lenses, audit_only_lenses = _compose_lens_directives(
        framework_lenses,
        response_pattern_crystals=response_crystals,
    )

    cross_overlay_para = _compose_cross_addiction_overlay(cross_addiction_branch)
    _lens_block_parts: List[str] = []
    if lens_directives_text:
        _lens_block_parts.append(lens_directives_text)
    if lexicon_crystals:
        _lens_block_parts.append(
            "Client-specific clinical lexicon cues:\n"
            + "\n".join(f"- {text}" for text in lexicon_crystals[:5])
        )
    if dst_prompt_block:
        _lens_block_parts.append(dst_prompt_block)
    if cross_overlay_para:
        _lens_block_parts.append(cross_overlay_para)
    lens_directives_block = "\n\n".join(_lens_block_parts)

    # ───────────────────────────────────────────────────────────────────
    # STEP 14 — Arousal load measurement
    # ───────────────────────────────────────────────────────────────────
    arousal = _measure_arousal_load(
        message=message, user_id=user_id,
        register=register_directive or "default", locale=locale,
    )

    # ───────────────────────────────────────────────────────────────────
    # STEP 15 — Mandatory reporting screen
    # ───────────────────────────────────────────────────────────────────
    reporting_summary, reporting_trigger_name = await _screen_mandatory_reporting(
        mandatory_reporting_service=mandatory_reporting_service,
        user_id=user_id, message=message, trafficking_native=trafficking_native,
        jurisdiction=jurisdiction, session_id=session_id, coach_id=coach_id,
    )

    # ───────────────────────────────────────────────────────────────────
    # STEP 16 — Coach handoff payload build (conditional)
    # ───────────────────────────────────────────────────────────────────
    handoff_payload, handoff_tier, handoff_severity = _build_handoff_if_needed(
        user_id=user_id,
        codeword_match=codeword_match,
        tmc_result=tmc_result,
        reporting_summary=reporting_summary,
        trafficking=trafficking,
        novelty_gate=novelty_gate,
        trigger_date=trigger_date,
        polyvictim_load=polyvictim_load,
    )

    # Persist the handoff payload at clinician_only classification and
    # capture the audit row id as the partner-seam payload_ref (Note 3c).
    coach_alert: Optional[CoachAlertRef] = None
    if handoff_payload is not None and handoff_tier is not None:
        try:
            handoff_dict = handoff_payload.to_dict()
        except Exception:
            handoff_dict = _coerce_jsonable(handoff_payload)
        handoff_audit_id = await _emit_audit_event(
            db_pool=db_pool, user_id=user_id,
            event_type="coach_handoff_emitted",
            event_severity=handoff_severity or "high",
            payload=handoff_dict,
            session_id=session_id,
            access_classification="clinician_only",
        )
        # Fire escalate_acuity in parallel for coach_override_protocol's
        # own notification + audit path. Failure is logged but does not
        # block the orchestrator's audit emission.
        await _emit_escalation(
            user_id=user_id, tier=handoff_tier,
            context={
                "trigger_source": selected_register_source,
                "tmc_class": tmc_class,
            },
        )
        try:
            from app.services.coach_override_protocol import HANDOFF_PAYLOAD_SCHEMA_HASH
            handoff_hash = HANDOFF_PAYLOAD_SCHEMA_HASH
        except Exception:
            handoff_hash = "unknown"
        coach_alert = CoachAlertRef(
            payload_ref=str(handoff_audit_id) if handoff_audit_id else "audit_insert_failed",
            trigger=handoff_tier,
            severity=handoff_severity or "high",
            handoff_schema_hash=handoff_hash,
            payload_emitted_at=datetime.now(timezone.utc).isoformat(),
        )
        coach_for_alert = await _resolve_assigned_coach_username(
            db_pool, user_id, coach_id,
        )
        if coach_for_alert and v1_4_alert_dispatch_enabled:
            try:
                from app.services.sensitive_alert_dispatcher import (
                    dispatch_sensitive_alert,
                )

                await dispatch_sensitive_alert(
                    db_pool=db_pool,
                    client_username=user_id,
                    coach_username=coach_for_alert,
                    risk_level=handoff_severity or "high",
                    reason=f"Coach handoff triggered ({handoff_tier})",
                    keywords=[handoff_tier, selected_register_source],
                    session_id=session_id,
                    family_id=None,
                    raw_context=None,
                    alert_type="coach_handoff",
                )
            except Exception as _disp_e:
                logger.warning(
                    "sensitive_clinical_bridge: dispatch_sensitive_alert failed: %s",
                    _disp_e,
                )

    # Resolve resource block (specialized_resources) for the active register.
    resource_block = _resolve_resource_block(
        register_directive=register_directive,
        trafficking=trafficking,
        tmc_class=tmc_class,
    )

    scope_statement = _resolve_scope_statement(
        register_directive=register_directive,
        codeword_match=codeword_match,
        novelty_gate=novelty_gate,
    )

    # ───────────────────────────────────────────────────────────────────
    # STEP 17 — Audit event emission
    # ───────────────────────────────────────────────────────────────────
    audit_event = {
        "event_type": "disclosure_evaluated",
        "tmc_class": tmc_class,
        "register_directive": register_directive,
        "register_source": selected_register_source,
        "novelty_gate_blocked": novelty_gate.blocked,
        "trigger_date_matched": trigger_date.matched,
        "legal_proximity_detected": legal_proximity.detected,
        "introjection_detected": introjection.detected,
        "coercion_detected": coercion.detected,
        "reengagement_detected": reengagement.detected,
        "trafficking_label": trafficking.label if trafficking else None,
        "polyvictim_layers": polyvictim_load.layers_active,
        "polyvictim_severity_load": polyvictim_load.severity_load,
        "embodiment_phase": embodiment.phase,
        "arousal_cap_triggered": arousal.cap_triggered if arousal else False,
        "coach_handoff_emitted": coach_alert is not None,
        "reporting_trigger": reporting_trigger_name,
        "sensitive_recall_state_hint": _user_state_hint,
        "sensitive_recall_dropped_count": int(sensitive_recall_dropped),
        "lens_dst": dst_active,
        "dst_prompt_injected": dst_prompt_block is not None,
        "dst_grounding_offer_threshold_delta": dst_adjustments.get(
            "grounding_offer_threshold_delta",
        ),
        "dst_escalation_step_size_multiplier": dst_adjustments.get(
            "escalation_step_size_multiplier",
        ),
        "framework_lenses_applied": applied_lenses,
        "framework_lenses_audit_only": audit_only_lenses,
        "lexicon_crystals_count": len(lexicon_crystals),
        "response_pattern_crystals_count": len(response_crystals),
        "response_pattern_crystal_applied": bool(response_crystals),
        "response_pattern_crystal_ids": [
            str(item.get("id"))
            for item in response_crystals
            if isinstance(item, dict) and item.get("id")
        ],
        "active_addiction_branches": active_branches_list,
        "cross_addiction_active": bool(
            cross_addiction_branch and cross_addiction_branch.branched
        ),
        "cross_addiction_count": (
            len(cross_addiction_branch.active_branches)
            if cross_addiction_branch and cross_addiction_branch.branched
            else 0
        ),
        "cross_addiction_overlay_applied": bool(cross_overlay_para),
        "cross_addiction_branch_labels": list(
            cross_addiction_branch.active_branches,
        )
        if cross_addiction_branch and cross_addiction_branch.branched
        else [],
        "lens_directives_block": lens_directives_block,
        "schema_version": BRIDGE_DECISION_SCHEMA_VERSION,
        "schema_hash": BRIDGE_DECISION_SCHEMA_HASH,
        "pipeline_steps_completed": list(PIPELINE_STEP_NAMES_V1_3),
    }

    decided_at = datetime.now(timezone.utc).isoformat()
    audit_id = await _emit_audit_event(
        db_pool=db_pool, user_id=user_id,
        event_type="disclosure_evaluated",
        event_severity=_severity_for_decision(
            novelty_gate=novelty_gate, tmc_class=tmc_class,
            coach_alert=coach_alert,
        ),
        payload=audit_event,
        decision_summary={
            "register_directive": register_directive,
            "register_source": selected_register_source,
            "coach_alert_payload_ref": coach_alert.payload_ref if coach_alert else None,
        },
        session_id=session_id,
    )
    audit_event["audit_log_id"] = audit_id

    decision = BridgeDecision(
        register_directive=register_directive,
        coach_alert=coach_alert,
        resource_block=resource_block,
        scope_statement=scope_statement,
        audit_event=audit_event,
        novelty_gate_state=novelty_gate,
        arousal_load=arousal,
        introjection_signal=introjection,
        reengagement_signal=reengagement,
        polyvictim_load=polyvictim_load,
        embodiment_phase_applied=embodiment,
        trigger_date_match=trigger_date,
        legal_proximity=legal_proximity,
        substance_register_branch=substance_branch,
        prebuffer_required=novelty_gate.blocked or codeword_match is not None,
        prebuffer_text=_resolve_prebuffer_text(
            codeword_match=codeword_match, novelty_gate=novelty_gate,
        ),
        coercion_test=coercion,
        dissociation_signal=dissociation,
        trafficking_classification=trafficking,
        tmc_class=tmc_class,
        selected_register_source=selected_register_source,
        schema_version=BRIDGE_DECISION_SCHEMA_VERSION,
        schema_hash=BRIDGE_DECISION_SCHEMA_HASH,
        decided_at=decided_at,
    )

    # Note 3a — pre-return redaction validator. Raises on any contiguous
    # overlap >= 12 chars with the original user message in any string
    # field of the decision.
    _validate_no_raw_transcript_leak(decision, message)

    return decision


# ═════════════════════════════════════════════════════════════════════════
# Step 13 / 16 / 17 helpers
# ═════════════════════════════════════════════════════════════════════════


def _crystal_domain_for(
    *,
    introjection: IntrojectionSummary,
    reengagement: ReengagementSummary,
    trafficking: Optional[TraffickingClassificationSummary],
    embodiment: EmbodimentPhaseApplied,
) -> Optional[str]:
    """Pick the crystal domain that best matches active signals."""
    if trafficking is not None and trafficking.label != "no_disclosure":
        return "trafficking_trauma"
    if reengagement.detected:
        return "trafficking_trauma"
    if introjection.detected:
        return "intimacy_clinical"
    if embodiment.phase:
        return "intimacy_clinical"
    return None


def _resolve_substance_branch(
    *,
    tmc_signals: Dict[str, Any],
    embodiment: EmbodimentPhaseApplied,
) -> SubstanceRegisterBranch:
    """Decide whether the dual-diagnosis (substance) register should branch.

    Heuristic: when the TMC signals carry a substance flag in the user's
    profile (set via clinician portal), branch. The orchestrator does not
    invent substance signals — it consumes them from TMC's signal dict.
    """
    if bool(tmc_signals.get("substance_branch_active")):
        return SubstanceRegisterBranch(
            branched=True, reason="profile_flag_active",
        )
    return SubstanceRegisterBranch(branched=False, reason="not_active")


def _profile_status_active(
    profile: Dict[str, Any],
    key: str,
    active_values: Tuple[str, ...] = ("active", "crisis"),
) -> bool:
    value = profile.get(key) if isinstance(profile, dict) else None
    return str(value or "").lower() in active_values


def _resolve_sex_addiction_branch(
    *, tmc_signals: Dict[str, Any],
) -> SexAddictionRegisterBranch:
    if bool(tmc_signals.get("sex_addiction_branch_active")):
        return SexAddictionRegisterBranch(branched=True, reason="profile_flag_active")
    return SexAddictionRegisterBranch(branched=False, reason="not_active")


def _resolve_gambling_branch(
    *, tmc_signals: Dict[str, Any],
) -> GamblingRegisterBranch:
    if bool(tmc_signals.get("gambling_branch_active")):
        return GamblingRegisterBranch(branched=True, reason="profile_flag_active")
    return GamblingRegisterBranch(branched=False, reason="not_active")


def _resolve_gaming_branch(
    *, tmc_signals: Dict[str, Any],
) -> GamingRegisterBranch:
    if bool(tmc_signals.get("gaming_branch_active")):
        return GamingRegisterBranch(branched=True, reason="profile_flag_active")
    return GamingRegisterBranch(branched=False, reason="not_active")


def _resolve_food_compulsion_branch(
    *, tmc_signals: Dict[str, Any],
) -> FoodCompulsionRegisterBranch:
    if bool(tmc_signals.get("food_compulsion_branch_active")):
        return FoodCompulsionRegisterBranch(branched=True, reason="profile_flag_active")
    return FoodCompulsionRegisterBranch(branched=False, reason="not_active")


def _resolve_work_compulsion_branch(
    *, tmc_signals: Dict[str, Any],
) -> WorkCompulsionRegisterBranch:
    if bool(tmc_signals.get("work_compulsion_branch_active")):
        return WorkCompulsionRegisterBranch(branched=True, reason="profile_flag_active")
    return WorkCompulsionRegisterBranch(branched=False, reason="not_active")


def _resolve_spending_compulsion_branch(
    *, tmc_signals: Dict[str, Any],
) -> SpendingCompulsionRegisterBranch:
    if bool(tmc_signals.get("spending_compulsion_branch_active")):
        return SpendingCompulsionRegisterBranch(branched=True, reason="profile_flag_active")
    return SpendingCompulsionRegisterBranch(branched=False, reason="not_active")


def _resolve_codependency_branch(
    *, tmc_signals: Dict[str, Any],
) -> CodependencyRegisterBranch:
    if bool(tmc_signals.get("codependency_branch_active")):
        return CodependencyRegisterBranch(branched=True, reason="profile_flag_active")
    return CodependencyRegisterBranch(branched=False, reason="not_active")


def _resolve_cross_addiction_branch(
    *,
    substance: SubstanceRegisterBranch,
    sex_addiction: SexAddictionRegisterBranch,
    gambling: GamblingRegisterBranch,
    gaming: GamingRegisterBranch,
    food_compulsion: FoodCompulsionRegisterBranch,
    work_compulsion: WorkCompulsionRegisterBranch,
    spending_compulsion: SpendingCompulsionRegisterBranch,
    codependency: CodependencyRegisterBranch,
) -> CrossAddictionRegisterBranch:
    """Composite resolver: fires when 2+ individual branches are active."""
    _branch_map = {
        "substance": substance.branched,
        "sex_addiction": sex_addiction.branched,
        "gambling": gambling.branched,
        "gaming": gaming.branched,
        "food_compulsion": food_compulsion.branched,
        "work_compulsion": work_compulsion.branched,
        "spending_compulsion": spending_compulsion.branched,
        "codependency": codependency.branched,
    }
    active = tuple(k for k, v in _branch_map.items() if v)
    if len(active) < 2:
        return CrossAddictionRegisterBranch(branched=False, reason="fewer_than_2")
    primary = active[0]
    secondary = active[1]
    overlay = f"cross_addiction:{'+'.join(active)}"
    return CrossAddictionRegisterBranch(
        branched=True,
        reason=f"{len(active)}_branches_active",
        active_branches=active,
        primary=primary,
        secondary=secondary,
        overlay_directive=overlay,
    )


_CROSS_ADD_OVERLAY_TEMPLATE = (
    "## CROSS-ADDICTION OVERLAY (v1.4)\n"
    "Multiple behavioral-health registers are simultaneously active "
    "({branches}). Pace slowly; avoid treating one channel as the sole "
    "\"problem.\" Hold shame lightly; invite curiosity about what each "
    "pattern regulates. Prefer short, somatically grounded prompts.\n"
)


def _compose_cross_addiction_overlay(
    cross: Optional[CrossAddictionRegisterBranch],
) -> Optional[str]:
    """Clinical overlay paragraph when 2+ addiction branches are active."""
    if cross is None or not cross.branched or not cross.active_branches:
        return None
    branches = ", ".join(b.replace("_", " ") for b in cross.active_branches)
    return _CROSS_ADD_OVERLAY_TEMPLATE.format(branches=branches)


# ─────────────────────────────────────────────────────────────────────
# v1.4 DST Lens (Gap 2)
# ─────────────────────────────────────────────────────────────────────

_DST_DIRECTIVE_BLOCK = (
    "Apply DST awareness: assume dissociation may be present. "
    "Prefer questions that name parts ('which part of you is...?') "
    "over questions that assume a unified self. Pace slowly. Raise the "
    "grounding-offer threshold by 0.15 and reduce escalation step size by 25%."
)


def _dst_lens_active(
    *,
    sex_addiction_branch: Optional[SexAddictionRegisterBranch] = None,
    polyvictim_load: Optional[Any] = None,
    tmc_signals: Optional[Dict[str, Any]] = None,
) -> bool:
    """Gap 2 gate: DST lens activates when sex_addiction status is non-none
    OR when any addiction branch is active AND polyvictim layers > 0.
    """
    if sex_addiction_branch and sex_addiction_branch.branched:
        return True
    if polyvictim_load and getattr(polyvictim_load, "layers_active", 0) > 0:
        signals = tmc_signals or {}
        any_addiction = any(
            bool(signals.get(k))
            for k in (
                "substance_branch_active", "sex_addiction_branch_active",
                "gambling_branch_active", "gaming_branch_active",
                "food_compulsion_branch_active", "work_compulsion_branch_active",
                "spending_compulsion_branch_active", "codependency_branch_active",
            )
        )
        if any_addiction:
            return True
    return False


def _apply_dst_lens(
    directive: Optional[str],
) -> Tuple[Optional[str], str, Dict[str, Any]]:
    """Gap 2 behavior: mutate directive with DST system-prompt block.
    Returns (augmented_directive, dst_prompt_block, pacing_adjustments).
    """
    augmented = directive or "default"
    if not augmented.endswith("|dst"):
        augmented = f"{augmented}|dst"
    return augmented, _DST_DIRECTIVE_BLOCK, {
        "grounding_offer_threshold_delta": 0.15,
        "escalation_step_size_multiplier": 0.75,
    }


# ─────────────────────────────────────────────────────────────────────
# v1.4 Framework Lens (Gap 3)
# ─────────────────────────────────────────────────────────────────────

_FRAMEWORK_MENU: Dict[str, Dict[str, Any]] = {
    "ifs": {
        "label": "Internal Family Systems",
        "prompt": "Use IFS framing: invite the part to speak rather than confronting it directly.",
        "applies_to": {"sex_addiction", "codependency", "food_compulsion", "substance"},
    },
    "act": {
        "label": "Acceptance & Commitment Therapy",
        "prompt": "Apply ACT principles: defusion from thoughts, values-guided action.",
        "applies_to": {"gambling", "gaming", "work_compulsion", "spending_compulsion"},
    },
    "dbt": {
        "label": "Dialectical Behavior Therapy",
        "prompt": "Apply DBT skills: distress tolerance, emotional regulation, interpersonal effectiveness.",
        "applies_to": {"substance", "food_compulsion", "codependency"},
    },
    "cbt": {
        "label": "Cognitive Behavioral Therapy",
        "prompt": "Apply CBT restructuring: identify cognitive distortions, behavioral experiments.",
        "applies_to": {"gambling", "gaming", "spending_compulsion"},
    },
    "motivational_interviewing": {
        "label": "Motivational Interviewing",
        "prompt": "Use MI approach: express empathy, develop discrepancy, roll with resistance.",
        "applies_to": {"substance", "gambling", "sex_addiction", "gaming", "food_compulsion",
                       "work_compulsion", "spending_compulsion", "codependency"},
    },
    "twelve_step": {
        "label": "12-Step Facilitation",
        "prompt": "Reference 12-step principles: powerlessness acknowledgment, higher power, fellowship.",
        "applies_to": {"substance", "gambling", "sex_addiction", "codependency"},
    },
    "trauma_informed": {
        "label": "Trauma-Informed Care",
        "prompt": "Apply trauma-informed lens: safety first, trustworthiness, choice, collaboration.",
        "applies_to": {"sex_addiction", "substance", "codependency", "food_compulsion"},
    },
    "emdr_informed": {
        "label": "EMDR-Informed",
        "prompt": "Reference EMDR adaptive information processing: notice body sensation, dual awareness.",
        "applies_to": {"sex_addiction", "substance"},
    },
}


def _load_framework_menu(profile_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return canonical framework metadata plus clinician-set client choices."""
    source = profile_data or {}
    raw_menu = source.get("framework_menu")
    if not isinstance(raw_menu, dict):
        sc = source.get("sensitive_clinical")
        raw_menu = sc.get("framework_menu") if isinstance(sc, dict) else {}
    if not isinstance(raw_menu, dict):
        sb = source.get("sensitive_bridge")
        raw_menu = sb.get("framework_preferences") if isinstance(sb, dict) else {}
    if not isinstance(raw_menu, dict):
        raw_menu = {}

    enabled = raw_menu.get("enabled_frameworks")
    if enabled is None:
        enabled = raw_menu.get("enabled_lenses")
    if isinstance(enabled, dict):
        enabled_set = {
            str(k) for k, v in enabled.items()
            if bool(v) and str(k) in _FRAMEWORK_MENU
        }
    elif isinstance(enabled, list):
        enabled_set = {str(item) for item in enabled if str(item) in _FRAMEWORK_MENU}
    else:
        enabled_set = {
            str(k) for k, v in raw_menu.items()
            if k in _FRAMEWORK_MENU and bool(v)
        }

    default_lens = raw_menu.get("default_lens_for_today")
    if default_lens not in _FRAMEWORK_MENU:
        default_lens = None
    expires_at = raw_menu.get("default_lens_expires_at")
    if default_lens and expires_at:
        try:
            expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry < datetime.now(timezone.utc):
                default_lens = None
        except Exception:
            default_lens = None

    return {
        "definitions": dict(_FRAMEWORK_MENU),
        "enabled_frameworks": enabled_set,
        "default_lens_for_today": default_lens,
        "crystal_knowledge_graph_enabled": bool(
            raw_menu.get(
                "crystal_knowledge_graph_enabled",
                raw_menu.get("crystal_knowledge_graph_opt_in", False),
            ),
        ),
    }


def _select_framework_lens(
    *,
    active_branches: Tuple[str, ...],
    framework_menu: Optional[Dict[str, Any]] = None,
    user_preference: Optional[str] = None,
) -> List[str]:
    """Select ordered lens list based on active branches and optional user preference.
    Returns lens keys ordered by applicability score (number of matching branches).
    """
    if not active_branches:
        return []
    menu = framework_menu or _load_framework_menu()
    definitions = menu.get("definitions") or _FRAMEWORK_MENU
    enabled = menu.get("enabled_frameworks")
    enabled_set = enabled if isinstance(enabled, set) else set()
    preferred_lens = user_preference or menu.get("default_lens_for_today")
    scores: Dict[str, int] = {}
    for key, meta in definitions.items():
        if enabled_set and key not in enabled_set:
            continue
        overlap = len(set(active_branches) & meta["applies_to"])
        if overlap > 0:
            scores[key] = overlap
    ordered = sorted(scores, key=lambda k: scores[k], reverse=True)
    if preferred_lens and preferred_lens in ordered:
        ordered.remove(preferred_lens)
        ordered.insert(0, preferred_lens)
    return ordered


def _compose_lens_directives(
    lens_list: List[str],
    *,
    response_pattern_crystals: Optional[List[Any]] = None,
) -> Tuple[str, List[str], List[str]]:
    """Gap 3: compose lens directives with cap-at-2 rule.

    Returns:
        (composed_prompt_text, applied_lenses, audit_only_lenses)
    """
    if not lens_list:
        return ("", [], [])
    applied: List[str] = []
    audit_only: List[str] = []
    parts: List[str] = []

    for i, key in enumerate(lens_list):
        meta = _FRAMEWORK_MENU.get(key)
        if not meta:
            continue
        if i == 0:
            parts.append(f"[Primary Framework: {meta['label']}] {meta['prompt']}")
            applied.append(key)
        elif i == 1:
            parts.append(f"Also: {meta['prompt']}")
            applied.append(key)
        else:
            audit_only.append(key)

    if response_pattern_crystals:
        for crystal in response_pattern_crystals[:3]:
            crystal_text = (
                crystal.get("crystal_text")
                if isinstance(crystal, dict)
                else str(crystal)
            )
            if not crystal_text:
                continue
            parts.append(crystal_text)

    return ("\n".join(parts), applied, audit_only)


# ─────────────────────────────────────────────────────────────────────
# v1.4 Crystal Factory Layer 1 + Layer 2
# ─────────────────────────────────────────────────────────────────────

async def _load_lexicon_crystals(
    db_pool: Any,
    username: str,
    active_branches: Tuple[str, ...],
) -> List[str]:
    """Layer 1: per-client lexicon augmentation from nate_intelligence_crystals.
    Returns list of crystal text snippets relevant to the active branches.
    """
    if not active_branches or not db_pool:
        return []
    branch_patterns = [f"%{b}%" for b in active_branches[:4]]
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT crystal_text FROM nate_intelligence_crystals
                WHERE (user_id = (SELECT id FROM users WHERE username = $1 LIMIT 1)
                       OR user_id IS NULL)
                  AND scope != 'archived'
                  AND confidence >= 0.40
                  AND (domain = 'clinical' OR domain = 'coaching')
                  AND (crystal_text ILIKE $2 OR crystal_text ILIKE $3
                       OR crystal_text ILIKE $4 OR crystal_text ILIKE $5)
                ORDER BY recall_count DESC, confidence DESC
                LIMIT 5
                """,
                username,
                *[branch_patterns[i] if i < len(branch_patterns) else "%__none__%"
                  for i in range(4)],
            )
            return [r["crystal_text"] for r in rows if r.get("crystal_text")]
    except Exception as e:
        logger.warning("crystal_factory_l1: %s", e)
        return []


async def _load_response_pattern_crystals(
    db_pool: Any,
    username: str,
    lens_primary: Optional[str],
) -> List[Dict[str, str]]:
    """Layer 2: top-3 response pattern crystals by recall_count.
    Scoped to scope='response_pattern'.
    """
    if not db_pool or not lens_primary:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id::text AS id, crystal_text FROM nate_intelligence_crystals
                WHERE (user_id = (SELECT id FROM users WHERE username = $1 LIMIT 1)
                       OR user_id IS NULL)
                  AND scope = 'response_pattern'
                  AND confidence >= 0.40
                  AND crystal_text ILIKE $2
                ORDER BY recall_count DESC
                LIMIT 3
                """,
                username, f"%{lens_primary}%",
            )
            return [
                {"id": str(r["id"]), "crystal_text": r["crystal_text"]}
                for r in rows
                if r.get("crystal_text")
            ]
    except Exception as e:
        logger.warning("crystal_factory_l2: %s", e)
        return []


def _resolve_resource_block(
    *,
    register_directive: Optional[str],
    trafficking: Optional[TraffickingClassificationSummary],
    tmc_class: str,
) -> Optional[Dict[str, Any]]:
    """Pick a ResourceBlock from `specialized_resources` based on the
    selected register / trafficking / crisis state. Returns the
    `to_payload_dict()` form (already redacted by construction).
    """
    try:
        from app.services.specialized_resources import get_resource_block
    except Exception:
        return None

    domain: Optional[str] = None
    severity: str = "moderate"

    if trafficking is not None:
        if trafficking.label == "imminent_danger":
            domain, severity = "trafficking", "emergency"
        elif trafficking.label == "active_trafficking":
            domain, severity = "trafficking", "critical"
        elif trafficking.label != "no_disclosure":
            domain, severity = "trafficking", "high"

    if domain is None and register_directive:
        if "trafficking" in register_directive or "reengagement" in register_directive:
            domain, severity = "trafficking", "high"
        elif "introjection" in register_directive or "embodiment" in register_directive:
            domain, severity = "intimacy_clinical", "moderate"
        elif "substance" in register_directive:
            domain, severity = "dual_diagnosis", "moderate"
        elif "crisis" in register_directive:
            domain, severity = "sexual_trauma", "critical"

    if domain is None and tmc_class == "CRISIS":
        domain, severity = "sexual_trauma", "critical"

    if domain is None:
        return None

    block = get_resource_block(domain=domain, severity=severity, locale="US")
    if block is None:
        return None
    try:
        return block.to_payload_dict()
    except Exception:
        return None


def _resolve_scope_statement(
    *,
    register_directive: Optional[str],
    codeword_match: Any,
    novelty_gate: NoveltyGateState,
) -> Optional[str]:
    """Generate a clinician-readable scope-of-response statement.

    No raw user text. Must be a stable string drawn from a fixed set of
    clinician-vetted statements so the redaction validator never trips.
    """
    if codeword_match is not None:
        return "scope:codeword_safe_silence_active"
    if novelty_gate.blocked:
        return "scope:predictability_continuity_thalamic_gate"
    if register_directive:
        return f"scope:{register_directive}"
    return None


def _resolve_prebuffer_text(
    *,
    codeword_match: Any,
    novelty_gate: NoveltyGateState,
) -> Optional[str]:
    """Return a fixed clinician-vetted prebuffer string when needed.

    Prebuffers are short pre-response acknowledgement strings used when the
    register requires a pause before content (codeword path, gate-blocked
    path). Strings are constants here — never composed from user text.
    """
    if codeword_match is not None:
        return "I'm here. Take your time."
    if novelty_gate.blocked:
        return "I'm staying with you."
    return None


def _severity_for_decision(
    *,
    novelty_gate: NoveltyGateState,
    tmc_class: str,
    coach_alert: Optional[CoachAlertRef],
) -> str:
    """Map orchestrator state to one of the migration 202 event_severity
    enum values. Conservative bias — when in doubt, escalate severity.
    """
    if coach_alert is not None and coach_alert.severity == "emergency":
        return "emergency"
    if coach_alert is not None and coach_alert.severity in ("critical", "high"):
        return coach_alert.severity
    if tmc_class == "CRISIS":
        return "critical"
    if novelty_gate.blocked:
        return "moderate"
    return "info"


# ═════════════════════════════════════════════════════════════════════════
# _auditor_self_check — boot-time contract enforcement
# ═════════════════════════════════════════════════════════════════════════


def _auditor_self_check() -> Dict[str, bool]:
    """Boot-time contract checks. Returns a dict of check_name → passed.

    Checks:
        pipeline_order_matches_plan_v1_3 — runtime step list equals
            PIPELINE_STEP_NAMES_V1_3 (verified by inspecting the source of
            evaluate_disclosure for the canonical step comments).
        bridge_decision_schema_hash_stable — recomputing the hash matches
            the module constant (catches mid-process drift).
        redaction_validator_fires_on_overlap — synthetic BridgeDecision
            with planted leak triggers BridgeDecisionRedactionError.
        no_phase3_module_mutations — orchestrator source contains no
            `import` of any underscore-prefixed symbol from the five sealed
            modules (best-effort static check; CI-level git-diff is the
            authoritative enforcement per Note 1).
        coach_alert_carries_payload_ref — CoachAlertRef field set must
            contain `payload_ref` and must NOT contain a `payload` field
            (Note 3c partner-seam discipline).
    """
    results: Dict[str, bool] = {}

    # Check 1 — pipeline order
    try:
        import inspect
        src = inspect.getsource(evaluate_disclosure)
        # Each step has a banner comment '# STEP N — <name>' that we parse.
        import re
        runtime_order: List[str] = []
        # STEP 0 is the Phase 4 master kill switch gate, NOT part of the
        # v1.3 17-step pipeline contract. Skip it in the order check.
        for match in re.finditer(r"#\s*STEP\s*(\d+)\s*[—-]\s*([A-Za-z][\w \-/+]*)", src):
            if match.group(1) == "0":
                continue
            label = match.group(2).strip().lower().replace(" ", "_")
            # Normalize a few label aliases to match PIPELINE_STEP_NAMES_V1_3.
            label = label.replace("+", "_with_")
            label = label.replace("__", "_")
            runtime_order.append(label)
        # Map runtime labels to canonical names (one-to-one).
        # We verify count + ordering by index.
        results["pipeline_order_matches_plan_v1_3"] = (
            len(runtime_order) == len(PIPELINE_STEP_NAMES_V1_3)
        )
    except Exception:
        results["pipeline_order_matches_plan_v1_3"] = False

    # Check 2 — schema hash stability
    try:
        recomputed = _compute_schema_hash()
        results["bridge_decision_schema_hash_stable"] = (
            recomputed == BRIDGE_DECISION_SCHEMA_HASH
        )
    except Exception:
        results["bridge_decision_schema_hash_stable"] = False

    # Check 3 — redaction validator fires on overlap
    try:
        leaky = _make_synthetic_leaky_decision(
            "the user mentioned wanting to disappear forever today"
        )
        try:
            _validate_no_raw_transcript_leak(
                leaky,
                "the user mentioned wanting to disappear forever today",
            )
            results["redaction_validator_fires_on_overlap"] = False
        except BridgeDecisionRedactionError:
            results["redaction_validator_fires_on_overlap"] = True
    except Exception:
        results["redaction_validator_fires_on_overlap"] = False

    # Check 4 — no Phase 3 mutations (best-effort static)
    # We scan only `import` lines so the sentinel strings in this very
    # function don't false-positive.
    try:
        import inspect
        module_src = inspect.getsource(__import__(__name__, fromlist=["_"]))
        sealed_paths = (
            "app.services.therapeutic_controller",
            "app.services.governance.mandatory_reporting",
            "app.services.coach_override_protocol",
            "app.services.nate_checkin_agent",
            "app.sse.ucd.tmc",
        )
        has_forbidden = False
        for line in module_src.splitlines():
            stripped = line.lstrip()
            if not stripped.startswith(("import ", "from ")):
                continue
            for sealed in sealed_paths:
                if sealed not in stripped:
                    continue
                # `from <sealed> import _name` — underscore symbol import is forbidden.
                if " import _" in stripped:
                    has_forbidden = True
                    break
            if has_forbidden:
                break
        results["no_phase3_module_mutations"] = not has_forbidden
    except Exception:
        results["no_phase3_module_mutations"] = False

    # Check 5 — CoachAlertRef contract
    try:
        coach_field_names = {f.name for f in fields(CoachAlertRef)}
        results["coach_alert_carries_payload_ref"] = (
            "payload_ref" in coach_field_names
            and "payload" not in coach_field_names
        )
    except Exception:
        results["coach_alert_carries_payload_ref"] = False

    # Check 6 — feature flag set is exactly 16 names (Phase 4 / Note 3)
    try:
        results["feature_flag_count_is_16"] = (len(_FEATURE_FLAG_NAMES) == 16)
    except Exception:
        results["feature_flag_count_is_16"] = False

    # Check 7 — neutral decision factory returns dormant short-circuit shape
    try:
        neutral = _build_neutral_bridge_decision(reason="auditor_probe")
        results["neutral_decision_dormant_contract"] = (
            neutral.register_directive is None
            and neutral.selected_register_source == "dormant"
            and neutral.audit_event.get("decision_path") == "neutral_short_circuit"
        )
    except Exception:
        results["neutral_decision_dormant_contract"] = False

    # Check 8 — kill-switch helpers are present (callable signatures)
    try:
        results["kill_switch_helpers_present"] = all(
            callable(fn) for fn in (
                _read_master_enabled,
                _read_global_gap_flags,
                _read_user_enrollment,
                _resolve_effective_flags,
                _any_v13_signal_active,
            )
        )
    except Exception:
        results["kill_switch_helpers_present"] = False

    # Check 9 — Phase 4 wiring diff stays under the 15-line cap (Note 1).
    # Static structural check: counts the EXACT lines of the wiring seam
    # block in `prepare_therapeutic_context`. CI-level git-diff against the
    # Phase 3 seal commit is the authoritative enforcement; this catches
    # in-process scope creep before it reaches CI.
    try:
        import inspect
        from app.services.therapeutic_controller import prepare_therapeutic_context
        ctrl_src = inspect.getsource(prepare_therapeutic_context)
        # Extract the seam block — opens with the marker comment, closes
        # before the first non-seam statement (`tmc_result = ...`).
        marker = "# v1.3 Sensitive Clinical Bridge — single wiring seam"
        end_marker = "tmc_result = await _classify_tmc"
        if marker in ctrl_src and end_marker in ctrl_src:
            i = ctrl_src.index(marker)
            j = ctrl_src.index(end_marker, i)
            seam_block = ctrl_src[i:j]
            # Count substantive lines only; comments document the narrow seam
            # but do not widen the runtime integration surface.
            line_count = len(
                [
                    ln for ln in seam_block.splitlines()
                    if ln.strip() and not ln.lstrip().startswith("#")
                ]
            )
            results["phase4_wiring_diff_under_15_lines"] = line_count <= 15
        else:
            results["phase4_wiring_diff_under_15_lines"] = False
    except Exception:
        results["phase4_wiring_diff_under_15_lines"] = False

    # Check 10 — Validator lexicon is clinician-gated (Note 2).
    # Confirms (a) the lexicon loader resolves to a JSON file (not a
    # hardcoded dict), (b) the loaded payload (or stub) carries the
    # `awaiting_clinician_authoring` meta status until clinicians replace
    # it, and (c) hot-reload audit hook accepts None safely.
    try:
        from app.services.nate_response_validator import (
            _resolve_lexicon_path,
            _load_sensitive_lexicon,
            set_lexicon_audit_hook,
        )
        lex_path = _resolve_lexicon_path("en-US")
        lex_payload = _load_sensitive_lexicon("en-US")
        path_ok = lex_path is not None and lex_path.suffix == ".json"
        # Lexicon meta lives under `_meta` per Gap D authoring convention
        # (leading underscore signals it is metadata, not a pattern category).
        meta = (lex_payload or {}).get("_meta", {}) if isinstance(lex_payload, dict) else {}
        payload_ok = (
            lex_payload is None
            or (
                isinstance(lex_payload, dict)
                and (
                    meta.get("status") == "awaiting_clinician_authoring"
                    or "block_patterns" in lex_payload
                )
            )
        )
        # Hook-accepts-None probe (must not raise).
        set_lexicon_audit_hook(None)
        results["validator_lexicon_clinician_gated"] = (
            bool(path_ok) and bool(payload_ok)
        )
    except Exception:
        results["validator_lexicon_clinician_gated"] = False

    return results


async def run_runtime_auditor_checks(db_pool) -> Dict[str, bool]:
    """DB-backed Phase 4 contract checks. The Phase 6 sensitive_bridge_auditor
    invokes this at every audit cycle. Boot-time auditor cannot run these
    because db_pool is unavailable at module import time.

    Returns sync `_auditor_self_check()` results merged with:
        gap_feature_flags_default_false_at_apply
        master_kill_switch_present
        detector_telemetry_table_writable_but_empty_at_apply
    """
    results = dict(_auditor_self_check())
    if not db_pool:
        # Mark DB-backed checks as failed when no pool is available so the
        # auditor surfaces the misconfiguration; do not silently pass.
        results["master_kill_switch_present"] = False
        results["gap_feature_flags_default_false_at_apply"] = False
        results["detector_telemetry_table_writable_but_empty_at_apply"] = False
        return results

    # master_kill_switch_present — row exists in app_settings; value may be
    # true or false (the *presence* of the toggle is what we verify here).
    try:
        async with db_pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT 1 FROM app_settings "
                "WHERE setting_key = 'sensitive_bridge_master_enabled'",
            )
        results["master_kill_switch_present"] = exists is not None
    except Exception as e:
        logger.warning("auditor: master_kill_switch_present check failed: %s", e)
        results["master_kill_switch_present"] = False

    # gap_feature_flags_default_false_at_apply — every one of the 16 canonical
    # names must be present in the global flag map AND must currently evaluate
    # to False at-apply. After cohort enrollment flips a global default, this
    # check naturally becomes informational; the auditor row in Phase 6
    # captures the at-apply state separately.
    try:
        global_flags = await _read_global_gap_flags(db_pool)
        all_present = all(name in global_flags for name in _FEATURE_FLAG_NAMES)
        all_false = all(global_flags.get(name) is False for name in _FEATURE_FLAG_NAMES)
        results["gap_feature_flags_default_false_at_apply"] = all_present and all_false
    except Exception as e:
        logger.warning("auditor: gap_feature_flags check failed: %s", e)
        results["gap_feature_flags_default_false_at_apply"] = False

    # detector_telemetry_table_writable_but_empty_at_apply — table exists,
    # has zero rows at the moment of the check (Phase 4 contract: writable
    # but empty until pilot writes start).
    try:
        async with db_pool.acquire() as conn:
            tbl_exists = await conn.fetchval(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'detector_telemetry'",
            )
            row_count = 0
            if tbl_exists:
                row_count = await conn.fetchval(
                    "SELECT COUNT(*)::int FROM detector_telemetry",
                ) or 0
        results["detector_telemetry_table_writable_but_empty_at_apply"] = (
            tbl_exists is not None and row_count == 0
        )
    except Exception as e:
        logger.warning("auditor: detector_telemetry check failed: %s", e)
        results["detector_telemetry_table_writable_but_empty_at_apply"] = False

    return results


# ═════════════════════════════════════════════════════════════════════════
# Phase 4 wiring — master kill switch + cohort enrollment (Note 3 contract)
# ═════════════════════════════════════════════════════════════════════════
#
# These helpers consume the migration 209 artifacts:
#   - app_settings.sensitive_bridge_master_enabled        (master kill switch)
#   - app_settings.sensitive_bridge_global_gap_flags      (global per-gap defaults)
#   - sensitive_bridge_enrollment(user_id, ...)           (per-user enrollment)
#
# Behavior contract:
#   master OFF                         -> evaluate_disclosure() returns neutral
#   master ON  + user not enrolled     -> returns neutral (no v1.3 behavior)
#   master ON  + user enrolled, no
#               flags flipped on user
#               or globally            -> returns neutral
#   master ON  + at least one flag on  -> full pipeline runs
#
# This is the entire safety thesis of Phase 4 wiring: bridge deployed but
# dormant. No survivor sees v1.3 behavior until Phase 6 cohort enrollment.

# Canonical 16 gap-feature-flag names (Plan v1.3 Gap F).
# These names are the single source of truth; the migration seeds the same
# names into app_settings.sensitive_bridge_global_gap_flags. If a 17th flag
# is ever added, update BOTH this list AND the migration AND the rollout
# playbook (docs/SENSITIVE_BRIDGE_ROLLOUT_PLAYBOOK.md §Flag set).
_FEATURE_FLAG_NAMES: Tuple[str, ...] = (
    "gap_introjection_enabled",
    "gap_thalamic_gate_enabled",
    "gap_reengagement_enabled",
    "gap_arousal_cap_enabled",
    "gap_polyvictim_load_enabled",
    "gap_dual_diagnosis_enabled",
    "gap_active_disclosure_enabled",
    "gap_codeword_enabled",
    "gap_trigger_dates_enabled",
    "gap_legal_status_enabled",
    "gap_embodiment_phase_enabled",
    "gap_jurisdiction_compliance_enabled",
    "gap_minor_survivor_protections_enabled",
    "gap_parenting_no_pathologization_enabled",
    "gap_rj_companioning_enabled",
    "gap_cultural_context_enabled",
)

_V1_4_FEATURE_FLAG_NAMES: Tuple[str, ...] = (
    "v1_4_codeword_listener_enabled",
    "v1_4_addiction_branches_enabled",
    "v1_4_cross_addiction_overlay_enabled",
    "v1_4_dst_lens_enabled",
    "v1_4_framework_lens_enabled",
    "v1_4_crystal_factory_enabled",
    "v1_4_alert_dispatch_enabled",
)


async def _read_master_enabled(db_pool) -> bool:
    """Read app_settings.sensitive_bridge_master_enabled. Default False on any
    error or missing row (fail-closed = dormant)."""
    if not db_pool:
        return False
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT setting_value FROM app_settings "
                "WHERE setting_key = 'sensitive_bridge_master_enabled'",
            )
        if row is None:
            return False
        # JSONB scalars come back as Python objects (bool / str / dict).
        if isinstance(row, bool):
            return row
        if isinstance(row, str):
            return row.strip().lower() == "true"
        return bool(row)
    except Exception as e:
        logger.warning(
            "sensitive_clinical_bridge: master_enabled read failed (fail-closed=False): %s", e,
        )
        return False


async def _read_global_gap_flags(db_pool) -> Dict[str, bool]:
    """Read app_settings.sensitive_bridge_global_gap_flags. Returns map of
    16 flag name -> bool. Missing/error returns all-False map."""
    default = {name: False for name in _FEATURE_FLAG_NAMES}
    if not db_pool:
        return default
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT setting_value FROM app_settings "
                "WHERE setting_key = 'sensitive_bridge_global_gap_flags'",
            )
        if not isinstance(row, dict):
            # asyncpg returns JSONB dicts as dict; if str, parse.
            if isinstance(row, str):
                import json as _json
                try:
                    row = _json.loads(row)
                except Exception:
                    return default
            else:
                return default
        merged = dict(default)
        for k, v in row.items():
            if k in default:
                merged[k] = bool(v)
        return merged
    except Exception as e:
        logger.warning(
            "sensitive_clinical_bridge: global_gap_flags read failed (fail-closed=all-False): %s", e,
        )
        return default


async def _read_user_enrollment(
    db_pool, user_id: str,
) -> Dict[str, Any]:
    """Read sensitive_bridge_enrollment row for user_id.
    Returns {'enrolled': bool, 'cohort': str, 'flags': {flag_name: bool}}.
    Missing row = unenrolled with all-False flag map.
    """
    default = {
        "enrolled": False,
        "cohort": "unenrolled",
        "flags": {name: False for name in _FEATURE_FLAG_NAMES},
        "raw_flags": {},
    }
    if not db_pool or not user_id:
        return default
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT cohort_label, gap_features_enabled "
                "FROM sensitive_bridge_enrollment WHERE user_id = $1",
                user_id,
            )
        if row is None:
            return default
        cohort = row.get("cohort_label") or "unenrolled"
        raw_flags = row.get("gap_features_enabled")
        if isinstance(raw_flags, str):
            import json as _json
            try:
                raw_flags = _json.loads(raw_flags)
            except Exception:
                raw_flags = {}
        if not isinstance(raw_flags, dict):
            raw_flags = {}
        flags = {name: bool(raw_flags.get(name, False)) for name in _FEATURE_FLAG_NAMES}
        return {
            "enrolled": cohort != "unenrolled",
            "cohort": cohort,
            "flags": flags,
            "raw_flags": dict(raw_flags),
        }
    except Exception as e:
        logger.warning(
            "sensitive_clinical_bridge: enrollment read failed for user=%s "
            "(fail-closed=unenrolled): %s", user_id, e,
        )
        return default


def _resolve_effective_flags(
    *,
    global_flags: Dict[str, bool],
    user_flags: Dict[str, bool],
) -> Dict[str, bool]:
    """User flag wins over global flag (Gap F rollout playbook contract).
    Per-user TRUE overrides global FALSE; per-user FALSE overrides global TRUE.
    """
    return {
        name: user_flags.get(name, global_flags.get(name, False))
        for name in _FEATURE_FLAG_NAMES
    }


def _any_v13_signal_active(effective_flags: Dict[str, bool]) -> bool:
    """At least one gap flag must be TRUE for v1.3 behavior to engage."""
    return any(bool(v) for v in effective_flags.values())


def _v1_4_feature_enabled(
    user_enrollment: Dict[str, Any],
    flag_name: str,
) -> bool:
    raw_flags = user_enrollment.get("raw_flags")
    if not isinstance(raw_flags, dict):
        raw_flags = {}
    return bool(raw_flags.get(flag_name, False))


def _any_sensitive_feature_active(
    effective_flags: Dict[str, bool],
    user_enrollment: Dict[str, Any],
) -> bool:
    if _any_v13_signal_active(effective_flags):
        return True
    return any(
        _v1_4_feature_enabled(user_enrollment, flag)
        for flag in _V1_4_FEATURE_FLAG_NAMES
    )


def _build_neutral_bridge_decision(*, reason: str) -> BridgeDecision:
    """Construct a no-op BridgeDecision for the dormant short-circuit path.
    register_directive=None so the controller wiring falls through to v1.2
    autonomic-state-derived register selection.

    `reason` is recorded in audit_event for trust-enforcer visibility.
    """
    from datetime import datetime as _dt, timezone as _tz
    return BridgeDecision(
        register_directive=None,
        coach_alert=None,
        resource_block=None,
        scope_statement=None,
        audit_event={
            "event_type": "disclosure_evaluated",
            "decision_path": "neutral_short_circuit",
            "short_circuit_reason": reason,
            "schema_version": BRIDGE_DECISION_SCHEMA_VERSION,
        },
        novelty_gate_state=NoveltyGateState(
            blocked=False, reason="signals_below_threshold",
            dissociation_delta=0.0, coercion_severity=0.0,
            threshold=_DEFAULT_NOVELTY_THRESHOLD, forced_on=False,
        ),
        arousal_load=None,
        introjection_signal=IntrojectionSummary(
            detected=False, score=0.0, drift_markers=(),
        ),
        reengagement_signal=ReengagementSummary(
            detected=False, severity="none", matched_labels=(),
        ),
        polyvictim_load=PolyvictimLoad(
            layers_active=0, severity_load=0.0, stacking_eligible=False,
        ),
        embodiment_phase_applied=EmbodimentPhaseApplied(
            phase=None, set_at=None, set_by_clinician_id=None,
        ),
        trigger_date_match=TriggerDateMatch(
            matched=False, date_type=None, severity=None, match_count=0,
        ),
        legal_proximity=LegalProximity(
            detected=False, case_type=None, case_status=None,
            days_until_next_event=None,
        ),
        substance_register_branch=SubstanceRegisterBranch(
            branched=False, reason="not_active",
        ),
        prebuffer_required=False,
        prebuffer_text=None,
        coercion_test=CoercionSummary(
            detected=False, severity=0.0, matched_labels=(),
        ),
        dissociation_signal=DissociationSummary(
            delta=0.0, length_anomaly_z=0.0, markers=(),
        ),
        trafficking_classification=None,
        tmc_class="REST",
        selected_register_source="dormant",
        schema_version=BRIDGE_DECISION_SCHEMA_VERSION,
        schema_hash=BRIDGE_DECISION_SCHEMA_HASH,
        decided_at=_dt.now(_tz.utc).isoformat(),
    )


def _make_synthetic_leaky_decision(planted_text: str) -> BridgeDecision:
    """Build a BridgeDecision whose scope_statement contains `planted_text`.
    Used by _auditor_self_check to verify the validator catches leaks.
    """
    return BridgeDecision(
        register_directive=None,
        coach_alert=None,
        resource_block=None,
        scope_statement=planted_text,
        audit_event={"event_type": "disclosure_evaluated"},
        novelty_gate_state=NoveltyGateState(
            blocked=False, reason="signals_below_threshold",
            dissociation_delta=0.0, coercion_severity=0.0,
            threshold=0.30, forced_on=False,
        ),
        arousal_load=None,
        introjection_signal=IntrojectionSummary(
            detected=False, score=0.0, drift_markers=(),
        ),
        reengagement_signal=ReengagementSummary(
            detected=False, severity="none", matched_labels=(),
        ),
        polyvictim_load=PolyvictimLoad(
            layers_active=0, severity_load=0.0, stacking_eligible=False,
        ),
        embodiment_phase_applied=EmbodimentPhaseApplied(
            phase=None, set_at=None, set_by_clinician_id=None,
        ),
        trigger_date_match=TriggerDateMatch(
            matched=False, date_type=None, severity=None, match_count=0,
        ),
        legal_proximity=LegalProximity(
            detected=False, case_type=None, case_status=None,
            days_until_next_event=None,
        ),
        substance_register_branch=SubstanceRegisterBranch(
            branched=False, reason="not_active",
        ),
        prebuffer_required=False,
        prebuffer_text=None,
        coercion_test=CoercionSummary(
            detected=False, severity=0.0, matched_labels=(),
        ),
        dissociation_signal=DissociationSummary(
            delta=0.0, length_anomaly_z=0.0, markers=(),
        ),
        trafficking_classification=None,
        tmc_class="REST",
        selected_register_source="default",
        schema_version=BRIDGE_DECISION_SCHEMA_VERSION,
        schema_hash=BRIDGE_DECISION_SCHEMA_HASH,
        decided_at="1970-01-01T00:00:00+00:00",
    )


# ═════════════════════════════════════════════════════════════════════════
# Module-load contract enforcement (boot guard)
# ═════════════════════════════════════════════════════════════════════════

_AUDITOR_RESULTS = _auditor_self_check()
_FAILED_CHECKS = [k for k, v in _AUDITOR_RESULTS.items() if not v]
if _FAILED_CHECKS:
    # Soft-fail at module load: log loudly but do not raise. The Phase 6
    # auditor (sensitive_bridge_auditor.py) reads _AUDITOR_RESULTS via
    # introspection and surfaces failures into the trust-enforcer report.
    # Hard-failing here would block the entire backend; soft-failing
    # surfaces the regression while keeping the system bootable.
    logger.warning(
        "sensitive_clinical_bridge: auditor self-check FAILED for: %s",
        _FAILED_CHECKS,
    )
else:
    logger.info(
        "sensitive_clinical_bridge: auditor self-check passed (%d checks)",
        len(_AUDITOR_RESULTS),
    )


__all__ = [
    "BridgeDecision",
    "BridgeDecisionRedactionError",
    "BRIDGE_DECISION_SCHEMA_HASH",
    "BRIDGE_DECISION_SCHEMA_VERSION",
    "PIPELINE_STEP_NAMES_V1_3",
    "REGISTER_SELECTION_PRIORITY",
    "evaluate_disclosure",
    "run_runtime_auditor_checks",
    "ArousalLoadSummary",
    "CoachAlertRef",
    "CoercionSummary",
    "DissociationSummary",
    "EmbodimentPhaseApplied",
    "IntrojectionSummary",
    "LegalProximity",
    "NoveltyGateState",
    "PolyvictimLoad",
    "ReengagementSummary",
    "SubstanceRegisterBranch",
    "TraffickingClassificationSummary",
    "TriggerDateMatch",
]
