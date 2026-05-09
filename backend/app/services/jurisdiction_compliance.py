"""
Sensitive Clinical Bridge — Jurisdiction Compliance Registry (Gap L)
=====================================================================

Per-jurisdiction policy lookup for mandatory reporting age thresholds,
trafficking-specific reporting statutes, retention period in years, and
consent age for `safe_silence_mode` two-step gate (Gap A).

Initial coverage: IL, CA, TX, FL, NY (top 5 trafficking-survivor states per
Polaris Project state data 2024). Federal HIPAA/CAPTA fallback for all others.

Authoritative spec: `docs/plan_backups/sensitive_clinical_bridge_v1.3.backup.2026-05-08-1402.plan.md`
  - Gap L (lines 1507-1571)
Clinical authority: `docs/SENSITIVE_CLINICAL_BRIDGE_GUIDELINES_2026-05-08.md`
Operational: `docs/SENSITIVE_BRIDGE_ROLLOUT_PLAYBOOK.md`

INTEGRATION POINTS
------------------
- `mandatory_reporting.py` — calls `get_policy(user.legal_jurisdiction)` before
  firing a reporting decision; uses `mandatory_reporting_age_threshold` and
  `trafficking_specific_reporting_required`.
- `sensitive_bridge_log.retained_until` — Phase 4 BEFORE INSERT trigger reads
  jurisdiction from `users.profile_data->>'jurisdiction_state'` and computes
  retention as `policy.retention_period_years`. Until that trigger lands,
  migration 202 default of 7 years applies (most-protective baseline).
- `safe_silence_mode` two-step gate (Gap A) — `consent_age_for_silence_mode`
  blocks self-approval for minors regardless of clinician proposal.
- `nate_response_validator.py` — Gap O child-survivor protections consult
  `mandatory_reporting_age_threshold` to determine minor classification.

DESIGN INVARIANTS
-----------------
1. Registry is import-time constant. No DB calls at module load.
2. Unknown jurisdictions ALWAYS fall back to FEDERAL_FALLBACK — never raise.
   The fallback is the most-protective HIPAA + CAPTA baseline.
3. Retention period is the MAX of state law vs HIPAA 6yr (the audited rationale
   for the 7-year default in `202_sensitive_clinical_bridge_core.sql` header).
4. `consent_age_for_silence_mode` MUST be >= mandatory_reporting_age_threshold
   in every entry. This invariant is asserted at module load.
5. Adding a new jurisdiction requires updating `JURISDICTION_REGISTRY` AND
   the Phase 4 retained_until trigger AND the `_auditor_self_check()` count
   expectation. See "Adding a jurisdiction" runbook below.

ADDING A JURISDICTION
---------------------
1. Cite the controlling statute(s) in the `notes` field — auditor reads this.
2. Confirm `mandatory_reporting_age_threshold` against the live state code.
   If the state has different age thresholds for trafficking vs general abuse,
   record the LOWER (more-protective) age.
3. Set `retention_period_years` to MAX(state_clinical_records_law, 6).
4. Update `_EXPECTED_REGISTRY_COUNT` below.
5. Update Phase 4 trigger SQL to include the new jurisdiction code.
6. File a clinician sign-off note in `docs/SENSITIVE_BRIDGE_ROLLOUT_PLAYBOOK.md`
   runtime log under the deployment date.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# Module version — bump on any registry mutation. Audited.
REGISTRY_VERSION = "1.0.0-2026-05-08"

# Asserted at module load (see end of file). Update when adding jurisdictions.
_EXPECTED_REGISTRY_COUNT = 5


@dataclass(frozen=True)
class JurisdictionPolicy:
    """Per-jurisdiction policy bundle. Immutable.

    Attributes
    ----------
    jurisdiction
        Format: 'US-XX' for US states (ISO 3166-2 subset) or 'XX' for other
        ISO-3166-1 alpha-2 country codes (reserved for v1.4).
    mandatory_reporting_age_threshold
        Anyone under this age is automatically classified as a minor for
        mandatory-reporting purposes (Gap O integration).
    trafficking_specific_reporting_required
        True iff the jurisdiction has a trafficking-specific reporting statute
        beyond general abuse reporting.
    trafficking_reporting_statute
        Citation string (e.g., '740 ILCS 110 + 325 ILCS 5'). None for fallback.
    retention_period_years
        Audit log retention (sensitive_bridge_log.retained_until). MAX of
        state clinical records law and HIPAA 45 CFR 164.530(j) 6-year minimum.
    consent_age_for_silence_mode
        Minimum age to participate in `safe_silence_mode` two-step gate.
        MUST be >= mandatory_reporting_age_threshold (asserted at module load).
    notes
        Plain-language summary of the controlling law(s). Read by auditor.
    """

    jurisdiction: str
    mandatory_reporting_age_threshold: int
    trafficking_specific_reporting_required: bool
    trafficking_reporting_statute: Optional[str]
    retention_period_years: int
    consent_age_for_silence_mode: int
    notes: str


# ---------------------------------------------------------------------------
# Registry — top 5 trafficking-survivor states (Polaris 2024 data)
# ---------------------------------------------------------------------------

JURISDICTION_REGISTRY: Dict[str, JurisdictionPolicy] = {
    "US-IL": JurisdictionPolicy(
        jurisdiction="US-IL",
        mandatory_reporting_age_threshold=18,
        trafficking_specific_reporting_required=True,
        trafficking_reporting_statute="740 ILCS 110 + 325 ILCS 5",
        retention_period_years=7,
        consent_age_for_silence_mode=18,
        notes=(
            "Illinois MHDDCA (740 ILCS 110) requires 7-year minimum retention "
            "from last interaction; CAPTA + Abused and Neglected Child "
            "Reporting Act (325 ILCS 5) requires reporting suspected abuse "
            "of any person under 18."
        ),
    ),
    "US-CA": JurisdictionPolicy(
        jurisdiction="US-CA",
        mandatory_reporting_age_threshold=18,
        trafficking_specific_reporting_required=True,
        trafficking_reporting_statute="Penal Code 11164-11174.4 + AB-260",
        retention_period_years=7,
        consent_age_for_silence_mode=18,
        notes=(
            "California CANRA (Penal Code 11164-11174.4) plus AB-260 "
            "trafficking provisions; 7-year minimum retention."
        ),
    ),
    "US-TX": JurisdictionPolicy(
        jurisdiction="US-TX",
        mandatory_reporting_age_threshold=18,
        trafficking_specific_reporting_required=True,
        trafficking_reporting_statute="Family Code 261.101 + HB 3079",
        # State law allows 5yr but HIPAA 6yr is the floor — use HIPAA.
        retention_period_years=6,
        consent_age_for_silence_mode=18,
        notes=(
            "Texas DFPS reporting under Family Code 261.101 and HB 3079 "
            "trafficking provisions. State retention is 5yr but HIPAA "
            "45 CFR 164.530(j) 6yr floor controls."
        ),
    ),
    "US-FL": JurisdictionPolicy(
        jurisdiction="US-FL",
        mandatory_reporting_age_threshold=18,
        trafficking_specific_reporting_required=True,
        trafficking_reporting_statute="Statute 39.201 + HB 167",
        retention_period_years=6,
        consent_age_for_silence_mode=18,
        notes=(
            "Florida CWA (Statute 39.201) plus HB 167 trafficking framework. "
            "6-year retention (state minimum aligns with HIPAA floor)."
        ),
    ),
    "US-NY": JurisdictionPolicy(
        jurisdiction="US-NY",
        mandatory_reporting_age_threshold=18,
        trafficking_specific_reporting_required=True,
        trafficking_reporting_statute=(
            "Social Services Law 413 + Trafficking Victims Protection and "
            "Justice Act"
        ),
        retention_period_years=6,
        consent_age_for_silence_mode=18,
        notes=(
            "NY SSL 413 mandates reporting; Trafficking Victims Protection and "
            "Justice Act adds trafficking-specific provisions; 6-year retention."
        ),
    ),
}

FEDERAL_FALLBACK = JurisdictionPolicy(
    jurisdiction="US-FALLBACK",
    mandatory_reporting_age_threshold=18,
    trafficking_specific_reporting_required=False,
    trafficking_reporting_statute=None,
    retention_period_years=7,  # MAX of common state laws + HIPAA 6yr
    consent_age_for_silence_mode=18,
    notes=(
        "Federal HIPAA 45 CFR 164.530(j) baseline plus CAPTA reporting. "
        "Used for any jurisdiction not present in JURISDICTION_REGISTRY. "
        "Coach portal MUST surface a 'consult legal_advisor for state-specific "
        "guidance' badge for users on this fallback."
    ),
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_policy(jurisdiction: Optional[str]) -> JurisdictionPolicy:
    """Return the JurisdictionPolicy for a jurisdiction code.

    Parameters
    ----------
    jurisdiction
        US state code in 'US-XX' format, or ISO-3166-1 alpha-2 country code.
        None / empty / unknown -> FEDERAL_FALLBACK.

    Returns
    -------
    JurisdictionPolicy
        Always returns a policy — never raises. Falls back to
        FEDERAL_FALLBACK for unknown jurisdictions, which is the most-
        protective HIPAA + CAPTA baseline (7yr retention, age 18 threshold).

    Notes
    -----
    The fallback path is intentional. Raising on unknown jurisdiction would
    create a clinical-safety failure if intake data is missing or malformed —
    the orchestrator MUST always be able to compute a policy.
    """
    if not jurisdiction:
        return FEDERAL_FALLBACK
    normalized = jurisdiction.strip().upper()
    return JURISDICTION_REGISTRY.get(normalized, FEDERAL_FALLBACK)


def is_registered(jurisdiction: Optional[str]) -> bool:
    """True iff the jurisdiction has an explicit registry entry (not fallback)."""
    if not jurisdiction:
        return False
    return jurisdiction.strip().upper() in JURISDICTION_REGISTRY


def list_registered_jurisdictions() -> Tuple[str, ...]:
    """Sorted tuple of all registered jurisdiction codes (excluding fallback)."""
    return tuple(sorted(JURISDICTION_REGISTRY.keys()))


def retention_interval_sql(jurisdiction: Optional[str]) -> str:
    """Return a Postgres INTERVAL literal string for the jurisdiction.

    Used by the Phase 4 BEFORE INSERT trigger on `sensitive_bridge_log` to
    compute `retained_until` dynamically. Returns e.g. "7 years" or "6 years".
    Format is the literal that goes inside `INTERVAL '...'` — never trust
    this with user input; only the policy lookup feeds it.
    """
    policy = get_policy(jurisdiction)
    return f"{policy.retention_period_years} years"


# ---------------------------------------------------------------------------
# Auditor hooks (Phase 6 — sensitive_bridge_auditor.py)
# ---------------------------------------------------------------------------


def _auditor_self_check() -> Dict[str, object]:
    """Internal health check returning a dict of facts the auditor maps to
    checks. The audited check IDs (per `docs/SENSITIVE_BRIDGE_ROLLOUT_PLAYBOOK.md`)
    that consume this output are:

    - jurisdiction_compliance_loaded
    - jurisdiction_fallback_applied_logged (audit-side; see orchestrator)
    - retention_period_dynamic
    """
    return {
        "registry_version": REGISTRY_VERSION,
        "registered_count": len(JURISDICTION_REGISTRY),
        "expected_count": _EXPECTED_REGISTRY_COUNT,
        "fallback_loaded": FEDERAL_FALLBACK is not None,
        "fallback_retention_years": FEDERAL_FALLBACK.retention_period_years,
        "registered_jurisdictions": list(list_registered_jurisdictions()),
        "all_have_statute": all(
            p.trafficking_reporting_statute
            for p in JURISDICTION_REGISTRY.values()
        ),
    }


# ---------------------------------------------------------------------------
# Module-load invariants
# ---------------------------------------------------------------------------


def _validate_registry() -> None:
    """Assert design invariants at module load. Raises ValueError on violation.
    Intentionally hard-fail at import — a misconfigured jurisdiction registry
    is a clinical-safety hazard."""

    if len(JURISDICTION_REGISTRY) != _EXPECTED_REGISTRY_COUNT:
        raise ValueError(
            f"jurisdiction_compliance: registry has "
            f"{len(JURISDICTION_REGISTRY)} entries; expected "
            f"{_EXPECTED_REGISTRY_COUNT}. Update _EXPECTED_REGISTRY_COUNT "
            "and the Phase 4 retained_until trigger when adding jurisdictions."
        )

    for code, policy in JURISDICTION_REGISTRY.items():
        if policy.consent_age_for_silence_mode < policy.mandatory_reporting_age_threshold:
            raise ValueError(
                f"jurisdiction_compliance: {code} has consent_age "
                f"{policy.consent_age_for_silence_mode} < mandatory_reporting_age "
                f"{policy.mandatory_reporting_age_threshold}. consent_age MUST "
                "be >= mandatory_reporting_age."
            )
        if policy.retention_period_years < 6:
            raise ValueError(
                f"jurisdiction_compliance: {code} retention "
                f"{policy.retention_period_years}yr is below HIPAA 6yr floor."
            )
        if policy.trafficking_specific_reporting_required and not policy.trafficking_reporting_statute:
            raise ValueError(
                f"jurisdiction_compliance: {code} requires trafficking-specific "
                "reporting but has no statute citation."
            )


_validate_registry()


__all__ = [
    "REGISTRY_VERSION",
    "JurisdictionPolicy",
    "JURISDICTION_REGISTRY",
    "FEDERAL_FALLBACK",
    "get_policy",
    "is_registered",
    "list_registered_jurisdictions",
    "retention_interval_sql",
]
