"""
Sensitive Clinical Bridge — Specialized Resources Registry
==========================================================

Single source of truth for trauma-, trafficking-, intimacy-, and dual-diagnosis-
specialized referral resources. The orchestrator (`sensitive_clinical_bridge.py`)
and `mandatory_reporting.py` consult this registry for `ResourceBlock` objects
that are inlined in Nate's responses (where appropriate) or attached to coach
handoff payloads.

Authoritative spec: `docs/plan_backups/sensitive_clinical_bridge_v1.3.backup.2026-05-08-1402.plan.md`
  - §3 New detector modules (specialized_resources description)
  - Gap 9 (legal_trafficking domain)
  - Gap 10 (dual_diagnosis domain)
  - Gap G (emergency + recruiter_legal blocks)

Clinical authority: `docs/SENSITIVE_CLINICAL_BRIDGE_GUIDELINES_2026-05-08.md`
Operational: `docs/SENSITIVE_BRIDGE_ROLLOUT_PLAYBOOK.md`

DESIGN NOTES
------------
1. All resource text is *pre-vetted* and version-stamped. Nothing here is LLM-
   generated. Any change to phone/web/copy requires clinician + legal sign-off.
2. Domains map to BridgeDecision.resource_block.domain. Severity maps to one of
   ('low','moderate','high','critical','emergency'). Locale defaults to 'US' and
   currently US-only resources are loaded; international is reserved for v1.4.
3. The module is import-safe: no DB calls at import. All lookups are O(1) dict
   reads against frozen registries.
4. `Resource` and `ResourceBlock` are frozen dataclasses — immutable once
   constructed; eliminates accidental mutation by downstream callers.
5. `block_text` is the rendered, paste-into-response string. The orchestrator
   does not format these — that's this module's job, so the wording stays
   consistent across surfaces.

THIS MODULE IS PHASE-2 STUB-FREE: All resources below are real, current as of
2026-05. Verify monthly per `.cursor/rules/security-patch-cadence.mdc` cadence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# Module version — bump on any registry mutation. Audited by
# `sensitive_bridge_auditor.py` check `specialized_resources_version_present`.
REGISTRY_VERSION = "1.0.0-2026-05-08"

# Content-hash lock for version-bump enforcement.
# -----------------------------------------------
# When ANY resource (phone, sms, web, name, scope, notes) or block_text
# changes, the deterministic hash of the registry will diverge from this
# constant and `tests/test_specialized_resources_version_lock.py` will fail
# with a clear "bump REGISTRY_VERSION + REGISTRY_CONTENT_HASH" message.
#
# Forcing function rationale: `sensitive_bridge_log` retains for 7 years.
# A silent change to a phone number (e.g., NHTH adopts a new shortcode)
# would break forensic correlation between historical log entries and the
# resource block actually shown to the survivor at that time. Bumping the
# version lets the auditor stamp `specialized_resources_version` on every
# decision and reconstruct what the survivor saw years later.
#
# To regenerate when intentionally changing a resource:
#   python3 -c "from backend.app.services.specialized_resources import \
#     compute_registry_hash; print(compute_registry_hash())"
# Then update REGISTRY_VERSION (semver: bump patch for typo, minor for new
# resource, major for removal) AND paste the new hash here.
REGISTRY_CONTENT_HASH = (
    "7cec3a704da66428ea07cecd33c93248"
    "cbac046be61df203567c3e1dea445a94"
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Resource:
    """A single referral resource. Immutable.

    `phone`, `sms`, `web` may be None individually but at least one MUST be
    populated. `scope` is a one-line clinician-facing description (NEVER shown
    to clients raw — used in coach handoff payloads and audit context).
    `notes` is optional clinical guidance (e.g., "do not navigate from a
    monitored device").
    """

    name: str
    scope: str
    phone: Optional[str] = None
    sms: Optional[str] = None
    web: Optional[str] = None
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        if not (self.phone or self.sms or self.web):
            raise ValueError(
                f"Resource {self.name!r} must have at least one of phone/sms/web"
            )


@dataclass(frozen=True)
class ResourceBlock:
    """A bundle of resources keyed for a specific (domain, severity, locale).

    `block_text` is the pre-vetted, paste-into-response string. Orchestrator
    must not modify it. Use `to_payload_dict()` for coach handoff serialization.
    """

    domain: str
    severity: str
    locale: str
    resources: Tuple[Resource, ...]
    block_text: str
    requires_inline: bool = False  # True for emergency/imminent danger blocks

    def to_payload_dict(self) -> Dict[str, object]:
        return {
            "domain": self.domain,
            "severity": self.severity,
            "locale": self.locale,
            "requires_inline": self.requires_inline,
            "resource_names": [r.name for r in self.resources],
            "registry_version": REGISTRY_VERSION,
        }


# ---------------------------------------------------------------------------
# Resource definitions (US locale)
# ---------------------------------------------------------------------------

# Trafficking — National Human Trafficking Hotline + BeFree text + Polaris
NHTH = Resource(
    name="National Human Trafficking Hotline",
    scope="24/7 confidential national hotline; trafficking-trained advocates",
    phone="1-888-373-7888",
    sms="Text HELP to 233733 (BeFree)",
    web="https://humantraffickinghotline.org",
)

BEFREE = Resource(
    name="BeFree (text-only safety)",
    scope="Text-only response when speaking is unsafe",
    sms="Text HELP to 233733",
    web="https://humantraffickinghotline.org/en/get-help",
    notes="Use when caller cannot speak; advocate responds by text only.",
)

POLARIS_PATHWAY = Resource(
    name="Polaris Project safety planning",
    scope="National advocacy and safety planning",
    web="https://polarisproject.org/safety-planning",
    notes="Do not navigate from a monitored device.",
)

# Trafficking legal (Gap 9)
CAST_LA = Resource(
    name="CAST LA (Coalition to Abolish Slavery and Trafficking)",
    scope="National trafficking-specialized legal services",
    phone="213-365-1906",
    web="https://www.castla.org",
)

POLARIS_LEGAL = Resource(
    name="Polaris Project legal directory",
    scope="National legal directory; trafficking-specialized attorneys",
    web="https://polarisproject.org/get-assistance/",
)

T_VISA_PATHWAY = Resource(
    name="T-visa attorney pathway (USCIS)",
    scope="Federal humanitarian visa pathway for trafficking survivors",
    web=(
        "https://www.uscis.gov/humanitarian/"
        "victims-of-human-trafficking-t-nonimmigrant-status"
    ),
)

U_VISA_PATHWAY = Resource(
    name="U-visa attorney pathway (USCIS)",
    scope="Federal humanitarian visa pathway for crime victims",
    web=(
        "https://www.uscis.gov/humanitarian/"
        "victims-of-criminal-activity-u-nonimmigrant-status"
    ),
)

# Dual diagnosis (Gap 10)
SAMHSA_HELPLINE = Resource(
    name="SAMHSA National Helpline",
    scope="24/7 free confidential treatment referral; dual-diagnosis-aware",
    phone="1-800-662-4357",
    web="https://www.samhsa.gov/find-help/national-helpline",
)

SEEKING_SAFETY_FINDER = Resource(
    name="Najavits Seeking Safety provider directory",
    scope="Trauma + addiction integrated treatment provider directory",
    web="https://www.treatment-innovations.org/",
)

# Sexual trauma / intimacy clinical
RAINN = Resource(
    name="RAINN — National Sexual Assault Hotline",
    scope="24/7 confidential national hotline for sexual assault survivors",
    phone="1-800-656-4673",
    web="https://www.rainn.org",
)

AASECT_DIRECTORY = Resource(
    name="AASECT — certified sex therapist directory",
    scope="Certified sex therapists, educators, and counselors",
    web="https://www.aasect.org/referral-directory",
)

# Modality locators
EMDR_LOCATOR = Resource(
    name="EMDR International Association find-a-clinician",
    scope="EMDR-trained clinicians (trauma reprocessing)",
    web="https://www.emdria.org/find-an-emdr-therapist/",
)

SE_LOCATOR = Resource(
    name="Somatic Experiencing International practitioner directory",
    scope="SE-trained practitioners (body-based trauma resolution)",
    web="https://traumahealing.org/practitioner-directory/",
)

IFS_LOCATOR = Resource(
    name="IFS Institute practitioner directory",
    scope="Internal Family Systems practitioners",
    web="https://ifs-institute.com/practitioners",
)

EFT_LOCATOR = Resource(
    name="ICEEFT — Emotionally Focused Therapy directory",
    scope="EFT-trained couples and family therapists",
    web="https://iceeft.com/find-a-therapist/",
)

GOTTMAN_LOCATOR = Resource(
    name="Gottman Referral Network",
    scope="Gottman Method trained couples therapists",
    web="https://www.gottman.com/referral-network/",
)

# DV (used only when trafficking-specific resources are NOT appropriate)
NDVH = Resource(
    name="National Domestic Violence Hotline",
    scope="24/7 DV hotline (use trafficking resources first if trafficking present)",
    phone="1-800-799-7233",
    sms="Text START to 88788",
    web="https://www.thehotline.org",
)

# 988 (always available; never replaces specialized resource)
LIFELINE_988 = Resource(
    name="988 Suicide & Crisis Lifeline",
    scope="24/7 call/text/chat for suicide and acute crisis",
    phone="988",
    sms="Text 988",
    web="https://988lifeline.org",
)

# ---------------------------------------------------------------------------
# Pre-vetted block text (Gap G)
# ---------------------------------------------------------------------------

EMERGENCY_BLOCK_TEXT = (
    "If you can speak safely: National Human Trafficking Hotline 1-888-373-7888 (call). "
    "If you cannot speak: text HELP to 233733 (BeFree). They will respond by text only.\n"
    "Polaris Project safety planning: polarisproject.org/safety-planning "
    "— do not navigate from a monitored device."
)

RECRUITER_LEGAL_BLOCK_TEXT = (
    "What you described is recognized under federal law (Trafficking Victims "
    "Protection Act, 22 USC 7102) as victim behavior when done under coercion. "
    "CAST LA (1-888-539-2373) and the Polaris legal directory have attorneys "
    "who handle expungement of records that resulted from coerced acts. "
    "You are not the only one in this position — and there is a legal pathway "
    "built specifically for this."
)

ACTIVE_SITUATION_BLOCK_TEXT = (
    "If you are in the room with someone who can hear you, you do not have to "
    "say anything out loud. You can text HELP to 233733 (BeFree) and an "
    "advocate will respond by text only. National Human Trafficking Hotline: "
    "1-888-373-7888 if you can speak."
)

DUAL_DIAGNOSIS_BLOCK_TEXT = (
    "SAMHSA's National Helpline (1-800-662-4357) is free, confidential, "
    "24/7, and trained to refer for both substance use and trauma — together, "
    "not separately. The Seeking Safety provider directory at "
    "treatment-innovations.org lists clinicians trained in integrated "
    "trauma + addiction treatment."
)

LEGAL_TRAFFICKING_BLOCK_TEXT = (
    "For legal questions specific to your situation: CAST LA (213-365-1906) "
    "and the Polaris Project legal directory are national starting points. "
    "If you are exploring T-visa or U-visa pathways, USCIS hosts the official "
    "guidance — your attorney is the right place to walk through the steps."
)

INTIMACY_CLINICAL_BLOCK_TEXT = (
    "If you would like to work with a clinician who specializes in this area, "
    "the AASECT directory (aasect.org/referral-directory) lists certified sex "
    "therapists. EMDR (emdria.org), Somatic Experiencing (traumahealing.org), "
    "and IFS (ifs-institute.com) are three trauma-informed modalities with "
    "practitioner directories."
)

SEXUAL_TRAUMA_BLOCK_TEXT = (
    "RAINN's national hotline (1-800-656-4673) is 24/7 and confidential. "
    "If you'd like a clinician trained in trauma reprocessing, the EMDR "
    "International Association (emdria.org) and Somatic Experiencing "
    "International (traumahealing.org) have practitioner directories."
)

# ---------------------------------------------------------------------------
# Registry — keyed by (domain, severity)
# ---------------------------------------------------------------------------

# locale is reserved for v1.4. v1.3 ships US-only.
_REGISTRY: Dict[Tuple[str, str], ResourceBlock] = {
    # ---- TRAFFICKING ----
    ("trafficking", "emergency"): ResourceBlock(
        domain="trafficking",
        severity="emergency",
        locale="US",
        resources=(NHTH, BEFREE, POLARIS_PATHWAY, LIFELINE_988),
        block_text=EMERGENCY_BLOCK_TEXT,
        requires_inline=True,
    ),
    ("trafficking", "critical"): ResourceBlock(
        domain="trafficking",
        severity="critical",
        locale="US",
        resources=(NHTH, BEFREE, POLARIS_PATHWAY),
        block_text=ACTIVE_SITUATION_BLOCK_TEXT,
        requires_inline=True,
    ),
    ("trafficking", "high"): ResourceBlock(
        domain="trafficking",
        severity="high",
        locale="US",
        resources=(NHTH, POLARIS_PATHWAY),
        block_text=(
            "The National Human Trafficking Hotline (1-888-373-7888) and "
            "Polaris Project (polarisproject.org) are trafficking-trained and "
            "available 24/7."
        ),
        requires_inline=False,
    ),
    ("trafficking", "moderate"): ResourceBlock(
        domain="trafficking",
        severity="moderate",
        locale="US",
        resources=(NHTH, POLARIS_PATHWAY),
        block_text=(
            "Polaris Project (polarisproject.org) has trafficking-specialized "
            "advocates and resources whenever you are ready."
        ),
        requires_inline=False,
    ),
    # ---- TRAFFICKING — RECRUITER ROLE (Gap G) ----
    ("trafficking_recruiter", "high"): ResourceBlock(
        domain="trafficking_recruiter",
        severity="high",
        locale="US",
        resources=(NHTH, CAST_LA, POLARIS_LEGAL),
        block_text=RECRUITER_LEGAL_BLOCK_TEXT,
        requires_inline=True,
    ),
    # ---- LEGAL_TRAFFICKING (Gap 9) ----
    ("legal_trafficking", "high"): ResourceBlock(
        domain="legal_trafficking",
        severity="high",
        locale="US",
        resources=(CAST_LA, POLARIS_LEGAL, T_VISA_PATHWAY, U_VISA_PATHWAY),
        block_text=LEGAL_TRAFFICKING_BLOCK_TEXT,
        requires_inline=False,
    ),
    ("legal_trafficking", "moderate"): ResourceBlock(
        domain="legal_trafficking",
        severity="moderate",
        locale="US",
        resources=(CAST_LA, POLARIS_LEGAL),
        block_text=LEGAL_TRAFFICKING_BLOCK_TEXT,
        requires_inline=False,
    ),
    # ---- DUAL DIAGNOSIS (Gap 10) ----
    ("dual_diagnosis", "critical"): ResourceBlock(
        domain="dual_diagnosis",
        severity="critical",
        locale="US",
        resources=(SAMHSA_HELPLINE, SEEKING_SAFETY_FINDER, LIFELINE_988),
        block_text=DUAL_DIAGNOSIS_BLOCK_TEXT,
        requires_inline=True,
    ),
    ("dual_diagnosis", "high"): ResourceBlock(
        domain="dual_diagnosis",
        severity="high",
        locale="US",
        resources=(SAMHSA_HELPLINE, SEEKING_SAFETY_FINDER),
        block_text=DUAL_DIAGNOSIS_BLOCK_TEXT,
        requires_inline=False,
    ),
    ("dual_diagnosis", "moderate"): ResourceBlock(
        domain="dual_diagnosis",
        severity="moderate",
        locale="US",
        resources=(SAMHSA_HELPLINE, SEEKING_SAFETY_FINDER),
        block_text=DUAL_DIAGNOSIS_BLOCK_TEXT,
        requires_inline=False,
    ),
    # ---- SEXUAL TRAUMA ----
    ("sexual_trauma", "high"): ResourceBlock(
        domain="sexual_trauma",
        severity="high",
        locale="US",
        resources=(RAINN, EMDR_LOCATOR, SE_LOCATOR),
        block_text=SEXUAL_TRAUMA_BLOCK_TEXT,
        requires_inline=False,
    ),
    ("sexual_trauma", "moderate"): ResourceBlock(
        domain="sexual_trauma",
        severity="moderate",
        locale="US",
        resources=(RAINN, EMDR_LOCATOR, SE_LOCATOR, IFS_LOCATOR),
        block_text=SEXUAL_TRAUMA_BLOCK_TEXT,
        requires_inline=False,
    ),
    # ---- INTIMACY CLINICAL ----
    ("intimacy_clinical", "moderate"): ResourceBlock(
        domain="intimacy_clinical",
        severity="moderate",
        locale="US",
        resources=(AASECT_DIRECTORY, EMDR_LOCATOR, SE_LOCATOR, IFS_LOCATOR),
        block_text=INTIMACY_CLINICAL_BLOCK_TEXT,
        requires_inline=False,
    ),
    # ---- INFIDELITY (Gottman/EFT couples work) ----
    ("infidelity_recovery", "moderate"): ResourceBlock(
        domain="infidelity_recovery",
        severity="moderate",
        locale="US",
        resources=(EFT_LOCATOR, GOTTMAN_LOCATOR, IFS_LOCATOR),
        block_text=(
            "If you are looking for a couples therapist trained in this work, "
            "the ICEEFT directory (Emotionally Focused Therapy) and the "
            "Gottman Referral Network list clinicians with relevant training."
        ),
        requires_inline=False,
    ),
    # ---- DV (fallback only — trafficking domain wins when both apply) ----
    ("domestic_violence", "high"): ResourceBlock(
        domain="domestic_violence",
        severity="high",
        locale="US",
        resources=(NDVH, LIFELINE_988),
        block_text=(
            "The National Domestic Violence Hotline (1-800-799-7233) is "
            "available 24/7. You can also text START to 88788."
        ),
        requires_inline=False,
    ),
}

# Severity escalation chain — if exact (domain, severity) is not registered,
# get_resource_block falls back to the next higher severity within the same
# domain (never lower; we never offer a less-protective resource than asked).
_SEVERITY_RANK = ("low", "moderate", "high", "critical", "emergency")


def _severity_fallback_chain(severity: str) -> Tuple[str, ...]:
    """Return the severity chain to try, starting at requested severity and
    escalating upward. Unknown severities default to ('high',)."""
    if severity not in _SEVERITY_RANK:
        return ("high",)
    idx = _SEVERITY_RANK.index(severity)
    return tuple(_SEVERITY_RANK[idx:])


def get_resource_block(
    domain: str,
    severity: str = "moderate",
    locale: str = "US",
) -> Optional[ResourceBlock]:
    """Return the most-appropriate `ResourceBlock` for (domain, severity, locale).

    Returns None if no block is registered for the domain at any severity.
    Severity falls back UPWARD (more protective), never downward.
    Locale 'US' is the only supported locale in v1.3; non-US falls back to US
    until v1.4 internationalization lands.
    """
    if locale != "US":
        # Documented in module header: US-only in v1.3.
        locale = "US"

    for sev in _severity_fallback_chain(severity):
        block = _REGISTRY.get((domain, sev))
        if block is not None:
            return block
    return None


def list_domains() -> Tuple[str, ...]:
    """All distinct domains registered. Auditor uses this to verify coverage."""
    return tuple(sorted({d for d, _ in _REGISTRY}))


def list_resources_for_domain(domain: str) -> Tuple[Resource, ...]:
    """All distinct resources registered under a domain (across severities)."""
    seen: Dict[str, Resource] = {}
    for (d, _), block in _REGISTRY.items():
        if d != domain:
            continue
        for r in block.resources:
            seen[r.name] = r
    return tuple(seen.values())


def has_block(domain: str, severity: str = "moderate") -> bool:
    """True iff a block exists for exact (domain, severity) — no fallback."""
    return (domain, severity) in _REGISTRY


# ---------------------------------------------------------------------------
# Version-bump enforcement
# ---------------------------------------------------------------------------


def compute_registry_hash() -> str:
    """Deterministic SHA256 of the entire registry + block texts.

    Used by `tests/test_specialized_resources_version_lock.py` to enforce
    that any change to resource content (phone numbers, URLs, copy) is
    accompanied by a `REGISTRY_VERSION` and `REGISTRY_CONTENT_HASH` bump.

    Inclusion set: every (domain, severity) key, every Resource field
    (name, scope, phone, sms, web, notes), every block_text, every
    requires_inline flag, and the exported pre-vetted block text constants.

    EXCLUDED: REGISTRY_VERSION itself (bumping it must not change the hash;
    the hash represents *content*, the version represents *identity*).
    """
    payload: Dict[str, object] = {
        "registry": {},
        "block_texts": {
            "EMERGENCY_BLOCK_TEXT": EMERGENCY_BLOCK_TEXT,
            "RECRUITER_LEGAL_BLOCK_TEXT": RECRUITER_LEGAL_BLOCK_TEXT,
            "ACTIVE_SITUATION_BLOCK_TEXT": ACTIVE_SITUATION_BLOCK_TEXT,
            "DUAL_DIAGNOSIS_BLOCK_TEXT": DUAL_DIAGNOSIS_BLOCK_TEXT,
            "LEGAL_TRAFFICKING_BLOCK_TEXT": LEGAL_TRAFFICKING_BLOCK_TEXT,
            "INTIMACY_CLINICAL_BLOCK_TEXT": INTIMACY_CLINICAL_BLOCK_TEXT,
            "SEXUAL_TRAUMA_BLOCK_TEXT": SEXUAL_TRAUMA_BLOCK_TEXT,
        },
    }
    registry_payload: Dict[str, object] = payload["registry"]  # type: ignore[assignment]
    for (domain, severity), block in sorted(_REGISTRY.items()):
        key = f"{domain}::{severity}"
        registry_payload[key] = {
            "locale": block.locale,
            "requires_inline": block.requires_inline,
            "block_text": block.block_text,
            "resources": [
                {
                    "name": r.name,
                    "scope": r.scope,
                    "phone": r.phone,
                    "sms": r.sms,
                    "web": r.web,
                    "notes": r.notes,
                }
                for r in block.resources
            ],
        }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def assert_version_aligned() -> None:
    """Raise AssertionError iff REGISTRY_CONTENT_HASH is stale.

    Called by the version-lock test. Also safe for an optional pre-commit
    hook: `python3 -c "from app.services.specialized_resources import \
    assert_version_aligned; assert_version_aligned()"`.
    """
    actual = compute_registry_hash()
    if actual != REGISTRY_CONTENT_HASH:
        raise AssertionError(
            "specialized_resources content has changed without a version bump.\n"
            f"  Stored REGISTRY_CONTENT_HASH: {REGISTRY_CONTENT_HASH}\n"
            f"  Actual hash now:              {actual}\n\n"
            "Action required (one of):\n"
            "  1. If the change is intentional: bump REGISTRY_VERSION (semver:\n"
            "     patch for typo/copy fix, minor for new resource, major for\n"
            "     removal/breaking change) AND replace REGISTRY_CONTENT_HASH\n"
            "     with the actual hash above.\n"
            "  2. If the change is accidental: revert the change.\n\n"
            "Why this matters: sensitive_bridge_log retains for 7 years.\n"
            "Without a version bump, forensic reconstruction of which\n"
            "resource block the survivor saw will silently break."
        )


# ---------------------------------------------------------------------------
# Auditor hooks (consumed by `sensitive_bridge_auditor.py` Phase 6)
# ---------------------------------------------------------------------------


def _auditor_self_check() -> Dict[str, object]:
    """Internal health check called by the auditor. Returns a dict of
    booleans the auditor maps to checks. Adding a new required block requires
    updating this function AND the auditor's reserved check list."""
    return {
        "registry_version": REGISTRY_VERSION,
        "trafficking_emergency_present": has_block("trafficking", "emergency"),
        "trafficking_recruiter_present": has_block("trafficking_recruiter", "high"),
        "legal_trafficking_present": has_block("legal_trafficking", "high"),
        "dual_diagnosis_present": has_block("dual_diagnosis", "high"),
        "sexual_trauma_present": has_block("sexual_trauma", "high"),
        "intimacy_clinical_present": has_block("intimacy_clinical", "moderate"),
        "infidelity_recovery_present": has_block("infidelity_recovery", "moderate"),
        "emergency_block_text_nonempty": bool(EMERGENCY_BLOCK_TEXT.strip()),
        "recruiter_legal_block_text_nonempty": bool(
            RECRUITER_LEGAL_BLOCK_TEXT.strip()
        ),
        "active_situation_block_text_nonempty": bool(
            ACTIVE_SITUATION_BLOCK_TEXT.strip()
        ),
        "domain_count": len(list_domains()),
    }


__all__ = [
    "REGISTRY_VERSION",
    "REGISTRY_CONTENT_HASH",
    "Resource",
    "ResourceBlock",
    "EMERGENCY_BLOCK_TEXT",
    "RECRUITER_LEGAL_BLOCK_TEXT",
    "ACTIVE_SITUATION_BLOCK_TEXT",
    "DUAL_DIAGNOSIS_BLOCK_TEXT",
    "LEGAL_TRAFFICKING_BLOCK_TEXT",
    "INTIMACY_CLINICAL_BLOCK_TEXT",
    "SEXUAL_TRAUMA_BLOCK_TEXT",
    "get_resource_block",
    "list_domains",
    "list_resources_for_domain",
    "has_block",
    "compute_registry_hash",
    "assert_version_aligned",
]
