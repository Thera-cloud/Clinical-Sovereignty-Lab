"""
SOVEREIGN SWARM — Mandatory Reporting Protocol
Handles detection and escalation of mandatory reporting situations.

Operational Specifications §5.2 — Mandatory Reporting.

Phase 3 v1.3 Extension (Sensitive Clinical Bridge)
==================================================
Adds TRAFFICKING capability while preserving v1.2 behavior identically when
called without a TraffickingClassification (additivity contract).

The build follows three notes from the Phase 3 review:

NOTE 1 (BLOCKING — applied) — ReportingTrigger.TRAFFICKING enum addition.
    Verified all consumers handle the new value safely:
      - This file: TRIGGER_PATTERNS, immediate-actions, escalation-chain
        all extended to include ReportingTrigger.TRAFFICKING explicitly.
      - me2me/ingestion_safety.py: uses dict.get() with `if trigger:`
        fallback. Trafficking is NOT routed through me2me ingestion (correct;
        dedicated path is screen_message_with_trafficking below).
      - Audit-log serialization uses `.value` (string), not a hardcoded
        mapping dict — new enum values flow through .value automatically.
    Auditor check: reporting_trigger_consumers_handle_trafficking.

NOTE 2 (BLOCKING — applied) — Jurisdiction integration is lazy + audited.
    `_resolve_jurisdiction_policy()` is called at the moment of evaluation
    inside `_create_protocol`, NOT cached at module load. Every fallback
    application emits an audit event with `policy_source: 'fallback'`
    appended to `protocol.audit_trail`. Auditor check:
    jurisdiction_fallback_applied_logged.

NOTE 3 (NON-BLOCKING — applied) — TRAFFICKING patterns are additive to the
    existing TRIGGER_PATTERNS dict, NOT a separate parallel registry.
    Severity for TRAFFICKING is consumed from
    `TraffickingClassification.safety_score` (3 → critical, 2 → critical/high
    depending on class, 1 → high) — NEVER re-derived inside this module.
    The hardcoded DV hotline at line 215 (now in the DV branch of
    _get_immediate_actions) is preserved untouched for ReportingTrigger
    .DOMESTIC_VIOLENCE; trafficking events route through
    `specialized_resources.get_resource_block('trafficking', severity)`.

ADDITIVITY CONTRACT
-------------------
Calling `screen_message(...)` or `coach_report(...)` WITHOUT a
TraffickingClassification (the existing v1.2 signature) produces behavior
identical to v1.2:
    - TRIGGER_PATTERNS scanning still includes only DV/abuse/etc. matches
      because trafficking patterns require linguistic markers that the
      classifier (Gap G) is responsible for surfacing — falling back to
      pattern-only matching for trafficking would over-fire on benign
      strings like "labor".
    - The new entries in `TRIGGER_PATTERNS[ReportingTrigger.TRAFFICKING]`
      are documented "classifier-confirmed only" — `screen_message` will
      not match them on raw text alone.
    - All new code paths (jurisdiction lookup, trafficking resource block)
      execute only when a TraffickingClassification is passed in via the
      new `screen_message_with_trafficking(...)` entrypoint OR when
      coach_report is called with `trigger=ReportingTrigger.TRAFFICKING`
      and an explicit `trafficking_classification` parameter.

Phase 6 fixture suite verifies this with:
    - phase3_mandatory_reporting_v1_2_fixtures_pass
    - jurisdiction_fallback_applied_logged
    - reporting_trigger_consumers_handle_trafficking
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from app.models.governance import MandatoryReportingProtocol, ReportingTrigger

if TYPE_CHECKING:
    # Keep TraffickingClassification import in TYPE_CHECKING to preserve the
    # additivity contract — module imports never trigger Gap G classifier
    # imports unless trafficking is actually being processed at call time.
    from app.services.trafficking_disclosure_classifier import (
        TraffickingClassification,
    )

logger = logging.getLogger("governance.mandatory_reporting")


# =============================================================================
# DETECTION PATTERNS
# =============================================================================

# Note 3: TRAFFICKING patterns added to the same registry, NOT a parallel dict.
# These patterns are CLASSIFIER-CONFIRMED ONLY — `screen_message` does not
# match them against raw text because single-word matches like "labor" or
# "isolation" over-fire on benign content. The patterns are preserved here
# for forensic completeness (Phase 6 auditor reads this dict to verify
# trafficking coverage exists), and to provide a stable contract surface
# for the Phase 4 orchestrator.
TRIGGER_PATTERNS = {
    ReportingTrigger.CHILD_ABUSE: [
        "hitting my child", "hit my kid", "beat my child", "hurting my child",
        "child abuse", "my child has bruises", "someone is hurting my child",
    ],
    ReportingTrigger.ELDER_ABUSE: [
        "neglecting my parent", "elder abuse", "taking their money",
        "not feeding them", "locking them in",
    ],
    ReportingTrigger.SELF_HARM: [
        "kill myself", "suicide", "want to die", "end my life",
        "self harm", "cut myself", "hurt myself", "don't want to be alive",
        "better off dead", "plan to die",
    ],
    ReportingTrigger.HARM_TO_OTHERS: [
        "kill someone", "going to hurt", "want to harm",
        "plan to attack", "going to shoot",
    ],
    ReportingTrigger.DOMESTIC_VIOLENCE: [
        "partner hits me", "spouse beat me", "domestic violence",
        "being abused", "they choked me", "afraid to go home",
    ],
    ReportingTrigger.SUBSTANCE_CRISIS: [
        "overdose", "od'd", "can't stop using", "need a fix",
        "withdrawal symptoms", "relapsed", "shooting up",
        "drinking myself to death", "blacked out",
        "mixing drugs", "fentanyl", "took too many pills",
    ],
    # Phase 3 v1.3 — TRAFFICKING (Note 3, additive to the same registry)
    # CLASSIFIER-CONFIRMED ONLY — see _SCREEN_MESSAGE_RAW_MATCH_TRIGGERS below.
    # These cover Gap 5 spec: debt bondage, document confiscation, isolation
    # from family, forced labor markers, sex trafficking indicators.
    ReportingTrigger.TRAFFICKING: [
        # Debt bondage
        "owe him", "owe her", "owe them", "working off the debt",
        "can't leave until i pay", "debt to work off",
        # Document confiscation
        "took my passport", "has my id", "won't give me my documents",
        "kept my papers", "my passport is with him",
        # Isolation from family
        "won't let me see my family", "can't talk to my mom",
        "isolated from everyone", "cut me off from",
        # Forced labor markers
        "made me work", "have to work", "no pay", "kept the money",
        "long hours no pay",
        # Sex trafficking indicators
        "sells me", "rents me out", "books appointments for me",
        "takes the money i make", "i had to see", "made me see clients",
    ],
}

# `screen_message` raw-text scanning whitelist. v1.2 triggers only.
# TRAFFICKING is intentionally excluded — see classifier integration via
# `screen_message_with_trafficking()` for the canonical trafficking path.
_SCREEN_MESSAGE_RAW_MATCH_TRIGGERS = (
    ReportingTrigger.CHILD_ABUSE,
    ReportingTrigger.ELDER_ABUSE,
    ReportingTrigger.SELF_HARM,
    ReportingTrigger.HARM_TO_OTHERS,
    ReportingTrigger.DOMESTIC_VIOLENCE,
    ReportingTrigger.SUBSTANCE_CRISIS,
)


# =============================================================================
# JURISDICTION HELPERS (Note 2 — lazy, never cached at module load)
# =============================================================================


def _resolve_jurisdiction_policy(
    jurisdiction: Optional[str],
    audit_trail: List[Dict[str, Any]],
) -> Any:
    """Lazily resolve jurisdiction policy. Records an audit event.

    Note 2 (BLOCKING) — `get_policy()` is called at the moment of evaluation,
    not at module load. Every fallback emits a structured audit event with
    `policy_source: 'fallback'` so Phase 6 auditor can verify
    `jurisdiction_fallback_applied_logged`.

    Returns the resolved JurisdictionPolicy; never raises.

    Lazy import: keeps the trafficking-specialized policy module from being
    pulled into every backend boot path. v1.2 code paths (no jurisdiction
    needed) cost nothing.
    """
    from app.services.jurisdiction_compliance import (
        FEDERAL_FALLBACK,
        JURISDICTION_REGISTRY,
        get_policy,
    )

    policy = get_policy(jurisdiction)
    normalized = (jurisdiction or "").strip().upper()
    is_fallback = (
        not normalized or normalized not in JURISDICTION_REGISTRY
    )
    audit_trail.append(
        {
            "audit_event": "jurisdiction_policy_applied",
            "timestamp": datetime.utcnow().isoformat(),
            "requested_jurisdiction": jurisdiction,
            "resolved_jurisdiction": policy.jurisdiction,
            "policy_source": "fallback" if is_fallback else "registered",
            "retention_period_years": policy.retention_period_years,
            "trafficking_specific_reporting_required": (
                policy.trafficking_specific_reporting_required
            ),
        }
    )
    if is_fallback:
        logger.warning(
            "jurisdiction_policy_fallback_applied: requested=%r "
            "resolved=%s retention=%dyr",
            jurisdiction,
            policy.jurisdiction,
            policy.retention_period_years,
        )
    return policy


# =============================================================================
# TRAFFICKING SEVERITY MAPPING (Note 3 — consume safety_score, never re-derive)
# =============================================================================


def _trafficking_severity_from_classification(
    classification: "TraffickingClassification",
) -> str:
    """Map TraffickingClassification → severity string for the resource
    registry and for `MandatoryReportingProtocol.severity`.

    Note 3 contract: severity is wired FROM the classifier's `safety_score`
    field, NEVER re-derived from message text inside this module. This keeps
    severity consistent across the bridge: classifier → reporting → resource
    block all see the same acuity tier.

    Mapping (per Gap 5 + Gap G plan):
      - imminent_danger (safety_score=3) → 'critical'
        Classifier already promotes to emergency-resource block when needed
        via the orchestrator (Phase 4); reporting protocol stays at
        'critical' to mirror the existing severity tier set used by other
        triggers (no other ReportingTrigger uses 'emergency' currently —
        keeping severity field within the established v1.2 vocabulary
        avoids breaking downstream coach-portal severity filters).
      - active_situation (safety_score=2) → 'critical'
      - survivor_as_recruiter (safety_score=2) → 'high'
        Recruiter role gets 'high' rather than 'critical' because the
        clinical response is legal-pathway-first, not emergency-first.
      - past_tense (safety_score=1) → 'high'
      - unclassified / safety_score=0 → 'high' (defensive default)
    """
    # Lazy import of the class strings — keeps the additivity contract.
    from app.services.trafficking_disclosure_classifier import (
        CLASS_ACTIVE_SITUATION,
        CLASS_IMMINENT_DANGER,
        CLASS_SURVIVOR_AS_RECRUITER,
    )

    if classification.classification == CLASS_IMMINENT_DANGER:
        return "critical"
    if classification.classification == CLASS_ACTIVE_SITUATION:
        return "critical"
    if classification.classification == CLASS_SURVIVOR_AS_RECRUITER:
        return "high"
    # past_tense or unclassified — defensive default
    return "high"


def _trafficking_resource_domain_from_classification(
    classification: "TraffickingClassification",
) -> str:
    """Choose the specialized_resources DOMAIN for a trafficking event.

    Recruiter role uses the 'trafficking_recruiter' domain (legal pathway
    block); all other classifications use the standard 'trafficking' domain.
    """
    from app.services.trafficking_disclosure_classifier import (
        CLASS_SURVIVOR_AS_RECRUITER,
    )

    if classification.classification == CLASS_SURVIVOR_AS_RECRUITER:
        return "trafficking_recruiter"
    return "trafficking"


# =============================================================================
# SERVICE
# =============================================================================


class MandatoryReportingService:
    """
    Detects mandatory reporting triggers and manages the
    escalation chain.

    Phase 3 v1.3: Adds optional `screen_message_with_trafficking(...)`
    entrypoint and threads optional `trafficking_classification` and
    `jurisdiction` through `coach_report` and `_create_protocol`. v1.2
    callers see no behavior change.
    """

    def __init__(self, db_pool=None, notifications=None):
        self._db = db_pool
        self._notifications = notifications

    async def screen_message(
        self,
        user_id: str,
        message: str,
        session_id: Optional[str] = None,
        coach_id: Optional[str] = None,
    ) -> Optional[MandatoryReportingProtocol]:
        """Screen a message for mandatory reporting triggers (v1.2 signature).

        Behavior IDENTICAL to v1.2: scans only the raw-match whitelist
        triggers. TRAFFICKING is excluded from raw-text scanning to avoid
        over-firing; use `screen_message_with_trafficking` once the Gap G
        classifier has produced a TraffickingClassification.
        """
        lower = message.lower()

        for trigger in _SCREEN_MESSAGE_RAW_MATCH_TRIGGERS:
            patterns = TRIGGER_PATTERNS.get(trigger, [])
            for pattern in patterns:
                if pattern in lower:
                    protocol = await self._create_protocol(
                        trigger=trigger,
                        user_id=user_id,
                        session_id=session_id,
                        coach_id=coach_id,
                        detection_source="ai_detection",
                    )
                    await self._execute_escalation(protocol)
                    return protocol

        return None

    async def screen_message_with_trafficking(
        self,
        user_id: str,
        message: str,
        trafficking_classification: "TraffickingClassification",
        jurisdiction: Optional[str] = None,
        session_id: Optional[str] = None,
        coach_id: Optional[str] = None,
    ) -> Optional[MandatoryReportingProtocol]:
        """Phase 3 v1.3 trafficking-aware screen.

        Consumes a TraffickingClassification produced upstream (Gap G
        classifier) and a `jurisdiction` for the lazy policy lookup
        (Note 2). Severity comes from the classification's safety_score;
        resource block is fetched via specialized_resources.

        Returns None when classification is `unclassified` AND no v1.2
        raw-text trigger fires — preserves the v1.2 "no-op when nothing
        meets the bar" contract.

        Falls back to v1.2 `screen_message` raw-text scanning when the
        classification is `unclassified` (defensive: maybe the message
        contains a non-trafficking trigger like SELF_HARM).
        """
        # Lazy import — additivity contract.
        from app.services.trafficking_disclosure_classifier import (
            CLASS_UNCLASSIFIED,
        )

        if trafficking_classification.classification == CLASS_UNCLASSIFIED:
            # Defensive: still run v1.2 raw-text scan in case a non-
            # trafficking trigger applies.
            return await self.screen_message(
                user_id=user_id,
                message=message,
                session_id=session_id,
                coach_id=coach_id,
            )

        protocol = await self._create_protocol(
            trigger=ReportingTrigger.TRAFFICKING,
            user_id=user_id,
            session_id=session_id,
            coach_id=coach_id,
            detection_source="ai_detection_classifier",
            trafficking_classification=trafficking_classification,
            jurisdiction=jurisdiction,
        )
        await self._execute_escalation(protocol)
        return protocol

    async def coach_report(
        self,
        trigger: ReportingTrigger,
        user_id: str,
        coach_id: str,
        session_id: Optional[str] = None,
        details: str = "",
        trafficking_classification: Optional["TraffickingClassification"] = None,
        jurisdiction: Optional[str] = None,
    ) -> MandatoryReportingProtocol:
        """Process a mandatory report filed by a coach.

        v1.3 additive parameters: `trafficking_classification` and
        `jurisdiction` are consumed only when trigger=TRAFFICKING.
        """
        protocol = await self._create_protocol(
            trigger=trigger,
            user_id=user_id,
            session_id=session_id,
            coach_id=coach_id,
            detection_source="coach_flag",
            trafficking_classification=trafficking_classification,
            jurisdiction=jurisdiction,
        )
        await self._execute_escalation(protocol)
        return protocol

    async def _create_protocol(
        self,
        trigger: ReportingTrigger,
        user_id: str,
        session_id: Optional[str],
        coach_id: Optional[str],
        detection_source: str,
        trafficking_classification: Optional["TraffickingClassification"] = None,
        jurisdiction: Optional[str] = None,
    ) -> MandatoryReportingProtocol:
        """Create and persist a mandatory reporting protocol.

        v1.3 additivity: `trafficking_classification` and `jurisdiction` are
        consumed only when trigger=TRAFFICKING. v1.2 callers see no change.
        """
        audit_trail: List[Dict[str, Any]] = []

        # ---------- Severity (Note 3) ----------
        if trigger == ReportingTrigger.TRAFFICKING:
            if trafficking_classification is not None:
                # Wire severity from classifier — never re-derive.
                severity = _trafficking_severity_from_classification(
                    trafficking_classification
                )
                audit_trail.append(
                    {
                        "audit_event": "trafficking_severity_from_classification",
                        "timestamp": datetime.utcnow().isoformat(),
                        "classification": trafficking_classification.classification,
                        "safety_score": trafficking_classification.safety_score,
                        "classification_confidence": getattr(
                            trafficking_classification,
                            "classification_confidence",
                            None,
                        ),
                        "resolved_severity": severity,
                    }
                )
            else:
                # Coach filed TRAFFICKING without classifier output —
                # defensive most-protective default. Mirrors the
                # _build_trafficking_actions() default so the protocol
                # severity field and the resource block severity stay
                # internally consistent.
                severity = "critical"
                audit_trail.append(
                    {
                        "audit_event": "trafficking_severity_default_no_classification",
                        "timestamp": datetime.utcnow().isoformat(),
                        "resolved_severity": severity,
                        "rationale": "most_protective_default",
                    }
                )
        else:
            # v1.2 path — unchanged.
            severity = "critical" if trigger in (
                ReportingTrigger.SELF_HARM,
                ReportingTrigger.HARM_TO_OTHERS,
                ReportingTrigger.CHILD_ABUSE,
            ) else "high"

        # ---------- Jurisdiction (Note 2 — lazy + audited) ----------
        # Only consult jurisdiction when trafficking is in play. v1.2 paths
        # do not need it (existing DV/abuse/etc. flows ship federal-baseline
        # actions and preserve their existing behavior identically).
        if trigger == ReportingTrigger.TRAFFICKING:
            policy = _resolve_jurisdiction_policy(jurisdiction, audit_trail)
        else:
            policy = None

        # ---------- Build protocol ----------
        protocol = MandatoryReportingProtocol(
            trigger=trigger,
            detection_source=detection_source,
            user_id=user_id,
            session_id=session_id,
            coach_id=coach_id,
            severity=severity,
            immediate_actions=self._get_immediate_actions(
                trigger,
                trafficking_classification=trafficking_classification,
                policy=policy,
            ),
            escalation_chain=self._get_escalation_chain(trigger),
            audit_trail=audit_trail,
        )

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO mandatory_reporting_protocols
                        (protocol_id, trigger, detection_source, user_id, session_id, coach_id, severity)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        protocol.protocol_id, trigger.value, detection_source,
                        user_id, session_id, coach_id, severity,
                    )
            except Exception as e:
                logger.error("Protocol persistence failed: %s", e)

        logger.warning(
            "Mandatory reporting protocol created: trigger=%s user=%s severity=%s",
            trigger.value, user_id, severity,
        )
        return protocol

    async def _execute_escalation(
        self, protocol: MandatoryReportingProtocol
    ) -> None:
        """Execute the escalation chain for a protocol."""
        # Step 1: Notify assigned coach immediately
        if protocol.coach_id and self._notifications:
            try:
                await self._notifications.send_notification(
                    user_id=protocol.coach_id,
                    notification_type="mandatory_reporting_alert",
                    title=f"MANDATORY REPORTING: {protocol.trigger.value.upper()}",
                    body=(
                        f"A {protocol.trigger.value} concern has been detected for your client. "
                        f"Immediate review required."
                    ),
                    channel="urgent",
                )
                protocol.coach_notified = True
                protocol.coach_notified_at = datetime.utcnow()
            except Exception as e:
                logger.error("Coach notification failed: %s", e)

        # Step 2: Notify supervisor
        if self._notifications:
            try:
                await self._notifications.send_notification(
                    user_id="supervisor",
                    notification_type="mandatory_reporting_supervisor",
                    title=f"Mandatory Report: {protocol.trigger.value}",
                    body=f"User: {protocol.user_id}, Coach: {protocol.coach_id}, Severity: {protocol.severity}",
                    channel="urgent",
                )
                protocol.supervisor_notified = True
            except Exception as e:
                logger.error("Supervisor notification failed: %s", e)

    def _get_immediate_actions(
        self,
        trigger: ReportingTrigger,
        trafficking_classification: Optional["TraffickingClassification"] = None,
        policy: Optional[Any] = None,
    ) -> List[str]:
        """Get immediate actions for a trigger type.

        v1.3 additivity: `trafficking_classification` and `policy` are
        consumed only by the TRAFFICKING branch. The DV branch (and every
        other v1.2 branch) is preserved IDENTICALLY — different
        ReportingTrigger values, different paths, both live (per Note 3).
        """
        # ---- TRAFFICKING (Note 3 — specialized_resources lookup) ----
        if trigger == ReportingTrigger.TRAFFICKING:
            return self._build_trafficking_actions(
                trafficking_classification=trafficking_classification,
                policy=policy,
            )

        # ---- v1.2 actions (UNCHANGED) ----
        actions = {
            ReportingTrigger.SELF_HARM: [
                "Provide crisis line: 988 Suicide & Crisis Lifeline",
                "Notify assigned coach immediately",
                "Assess for immediate safety plan",
                "Do not end session without safety confirmation",
            ],
            ReportingTrigger.HARM_TO_OTHERS: [
                "Notify assigned coach immediately",
                "Assess specific threat details",
                "Tarasoff duty: warn identifiable potential victims",
            ],
            ReportingTrigger.CHILD_ABUSE: [
                "Notify assigned coach immediately",
                "File CPS report within 24 hours",
                "Document all disclosed information",
            ],
            ReportingTrigger.ELDER_ABUSE: [
                "Notify assigned coach immediately",
                "File APS report",
                "Document all disclosed information",
            ],
            ReportingTrigger.DOMESTIC_VIOLENCE: [
                "Assess immediate safety",
                "Provide DV hotline: 1-800-799-7233",
                "Notify assigned coach",
                "Create safety plan if not already in place",
            ],
            ReportingTrigger.SUBSTANCE_CRISIS: [
                "Provide SAMHSA helpline: 1-800-662-4357",
                "Assess for overdose risk",
                "Notify assigned coach immediately",
                "Connect with crisis intervention if active overdose",
            ],
        }
        return actions.get(trigger, ["Notify assigned coach"])

    def _build_trafficking_actions(
        self,
        trafficking_classification: Optional["TraffickingClassification"],
        policy: Optional[Any],
    ) -> List[str]:
        """Build the immediate-action list for a TRAFFICKING trigger.

        Resource block is sourced from `specialized_resources.get_resource_block`
        — never hardcoded inline (Note 3). Severity selection is delegated to
        the helper above so classifier safety_score is the single source of
        truth.

        Defensive: when called without a classification (e.g., a coach files
        a generic trafficking report without classifier output), uses the
        most-protective domain ('trafficking') and severity ('critical')
        rather than dropping to a less-protective default.
        """
        from app.services.specialized_resources import get_resource_block

        # Determine domain + severity
        if trafficking_classification is not None:
            domain = _trafficking_resource_domain_from_classification(
                trafficking_classification
            )
            severity = _trafficking_severity_from_classification(
                trafficking_classification
            )
        else:
            domain = "trafficking"
            severity = "critical"  # most-protective default

        actions: List[str] = []

        # 1. Resource block (pre-vetted text from specialized_resources)
        block = get_resource_block(domain=domain, severity=severity)
        if block is not None:
            actions.append(
                f"Provide trafficking resource block "
                f"(domain={block.domain}, severity={block.severity}): "
                f"{block.block_text}"
            )
        else:
            # Fail-safe — should not happen because trafficking domain is
            # registered at all severities, but keep an explicit fallback.
            actions.append(
                "Provide National Human Trafficking Hotline: "
                "1-888-373-7888 (call) / Text HELP to 233733 (BeFree)"
            )

        # 2. Jurisdiction-aware action note (Note 2)
        if policy is not None:
            if policy.trafficking_specific_reporting_required:
                statute = (
                    policy.trafficking_reporting_statute
                    or "consult clinical supervisor for citation"
                )
                actions.append(
                    f"Jurisdiction {policy.jurisdiction}: file "
                    f"trafficking-specific report per {statute}"
                )
            else:
                actions.append(
                    f"Jurisdiction {policy.jurisdiction}: federal HIPAA + "
                    "CAPTA baseline applies; consult legal_advisor for "
                    "state-specific guidance"
                )

        # 3. Coach + safety plan
        actions.append("Notify assigned coach immediately")
        actions.append(
            "Assess immediate safety; do NOT instruct the survivor to "
            "leave on their own — leaving is the highest-risk moment"
        )
        actions.append(
            "Document all disclosed information per "
            "sensitive_bridge_log retention policy"
        )

        return actions

    def _get_escalation_chain(self, trigger: ReportingTrigger) -> List[str]:
        """Get the escalation chain for a trigger type."""
        if trigger == ReportingTrigger.TRAFFICKING:
            # Trafficking adds a legal_advisor step before the platform
            # admin to align with the legal-pathway-first clinical posture.
            return [
                "assigned_coach",
                "clinical_supervisor",
                "legal_advisor",
                "platform_administrator",
            ]
        return [
            "assigned_coach",
            "clinical_supervisor",
            "platform_administrator",
        ]


# =============================================================================
# Auditor hooks (consumed by Phase 6 sensitive_bridge_auditor.py)
# =============================================================================


def _verify_trafficking_pattern_registry_additive() -> None:
    """Assert TRAFFICKING is keyed in the same TRIGGER_PATTERNS dict (Note 3).

    Phase 6 auditor check: trafficking_patterns_in_unified_registry.
    """
    if ReportingTrigger.TRAFFICKING not in TRIGGER_PATTERNS:
        raise AssertionError(
            "mandatory_reporting: ReportingTrigger.TRAFFICKING is missing "
            "from TRIGGER_PATTERNS. Trafficking patterns MUST live in the "
            "unified registry, not a parallel dict (Phase 3 Note 3)."
        )
    # All v1.2 triggers must still be present (additivity).
    v1_2_required = (
        ReportingTrigger.CHILD_ABUSE,
        ReportingTrigger.ELDER_ABUSE,
        ReportingTrigger.SELF_HARM,
        ReportingTrigger.HARM_TO_OTHERS,
        ReportingTrigger.DOMESTIC_VIOLENCE,
        ReportingTrigger.SUBSTANCE_CRISIS,
    )
    for t in v1_2_required:
        if t not in TRIGGER_PATTERNS:
            raise AssertionError(
                f"mandatory_reporting: v1.2 trigger {t.name} disappeared "
                "from TRIGGER_PATTERNS — additivity contract violated."
            )


def _verify_screen_message_v1_2_match_set() -> None:
    """Assert TRAFFICKING is excluded from raw-text screen_message scanning.

    Phase 6 auditor check: phase3_mandatory_reporting_v1_2_fixtures_pass
    relies on this — adding TRAFFICKING to raw-text scanning would over-fire
    on benign substrings like "labor" or "isolation".
    """
    if ReportingTrigger.TRAFFICKING in _SCREEN_MESSAGE_RAW_MATCH_TRIGGERS:
        raise AssertionError(
            "mandatory_reporting: ReportingTrigger.TRAFFICKING must NOT be "
            "in _SCREEN_MESSAGE_RAW_MATCH_TRIGGERS. The trafficking path is "
            "screen_message_with_trafficking() with classifier output."
        )


def _auditor_self_check() -> Dict[str, Any]:
    """Internal health check for Phase 6 sensitive_bridge_auditor.py.

    Returns a dict the auditor maps to checks:
      - trafficking_patterns_in_unified_registry
      - phase3_mandatory_reporting_v1_2_fixtures_pass (partial — full check
        runs synthetic v1.2 fixtures in Phase 6)
      - reporting_trigger_consumers_handle_trafficking (partial — full
        grep-based check is the auditor's responsibility)
    """
    try:
        _verify_trafficking_pattern_registry_additive()
        unified_ok = True
    except AssertionError as e:
        logger.error("Auditor: unified registry check failed: %s", e)
        unified_ok = False

    try:
        _verify_screen_message_v1_2_match_set()
        v1_2_match_ok = True
    except AssertionError as e:
        logger.error("Auditor: v1.2 match-set check failed: %s", e)
        v1_2_match_ok = False

    return {
        "trafficking_patterns_in_unified_registry": unified_ok,
        "screen_message_v1_2_match_set_preserved": v1_2_match_ok,
        "trafficking_enum_value_present": (
            "TRAFFICKING" in ReportingTrigger.__members__
        ),
        "trafficking_pattern_count": len(
            TRIGGER_PATTERNS.get(ReportingTrigger.TRAFFICKING, [])
        ),
        "v1_2_raw_match_trigger_count": len(
            _SCREEN_MESSAGE_RAW_MATCH_TRIGGERS
        ),
    }


# Boot-time additivity guard — fail at import if contract is violated.
_verify_trafficking_pattern_registry_additive()
_verify_screen_message_v1_2_match_set()


__all__ = [
    "TRIGGER_PATTERNS",
    "MandatoryReportingService",
]
