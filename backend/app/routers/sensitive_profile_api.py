"""
Sensitive Clinical Bridge — Clinician Portal REST Router (Phase 4b)
====================================================================

Plan authority: docs/plan_backups/sensitive_clinical_bridge_v1.3.backup.2026-05-08-1402.plan.md
  - Gap A (two-step safe_silence_mode gate)
  - Gap B (clinician portal endpoint inventory)
  - Risk #19 (same-session approver violation = 409)
  - Gap M (30-day approval expiry)

ROUTERS EXPORTED
----------------
- ``coach_router``  → mounted at ``/api/coach/sensitive-profile`` — clinician
  CRUD over the profile fields a treating coach is authorized to manage.
- ``admin_router``  → mounted at ``/api/admin/sensitive-profile`` — admin-only
  approval surface (currently the safe_silence_mode approve endpoint and a
  redacted read view) gated by ``require_admin``. Per
  ``webauthn-yubikey-security.mdc`` the admin's WebAuthn YubiKey posture is
  a globally enforced trust-auditor invariant; that posture (not a per-route
  dependency) is the source of truth for admin-mutation eligibility.

Both routers are registered additively from ``app.main``. Failure to load
must NOT crash the backend — wrap the import in try/except in main and log
the failure (the rest of the v1.3 stack stays dormant if the portal is
absent).

DESIGN INVARIANTS (BLOCKING)
----------------------------
1. ``require_clinician_for_user(user_id)`` is the SINGLE source of truth for
   coach-side authorization. Every coach endpoint declares it. The auditor
   check ``phase4b_all_coach_endpoints_use_require_clinician_for_user``
   parses this file at boot and asserts every ``/api/coach/...`` route uses
   the dependency. Inline assignment checks are a privilege-escalation
   vector — see Note 1 of the Phase 4b directive.

2. ``safe_silence_mode`` activation is a TWO-STEP server-side gate
   (Plan Gap A). The ``/safe-silence/propose`` endpoint records the
   proposer's session-token-hash on the JSONB state. The
   ``/safe-silence/approve`` endpoint then refuses to flip ``state='active'``
   unless ALL of the following hold:
       (a) Different session: ``proposer_token_hash != approver_token_hash``
           (Risk #19 — same-session approver = 409 same_session_violation).
       (b) At least one ``user_safety_codewords`` row with ``active=TRUE``
           exists for the user (codeword precondition; 409 requires_codeword
           if absent). Checked BEFORE the state flip — never after.
       (c) Proposal is still in ``pending_approval`` (otherwise 409 stale_state).
   These are enforced inside the endpoint, not in middleware (middleware can
   be bypassed; endpoint logic is the contract).

3. The orchestrator (``sensitive_clinical_bridge.py``) MUST NOT mutate the
   ``safe_silence_mode_state`` JSONB. It can only emit
   ``safe_silence_mode_recommended`` events. The auditor check
   ``safe_silence_orchestrator_cannot_mutate`` greps the orchestrator file
   for forbidden write patterns.

PII HANDLING
------------
Every free-text field that a clinician submits (notes_redacted,
attorney_contact_redacted, reason_redacted) goes through the same PII screen
implemented in ``trigger_date_registry._screen_notes_for_pii``. On a hit we
return ``422 pii_pattern_in_field`` with the matched pattern label and zero-
based offset so the Flutter portal can highlight the exact substring. We
NEVER persist the raw field on a screen failure.

CODEWORDS
---------
Plaintext codewords arrive in the request body, are normalized
(NFKD → lower → strip punctuation), salted with a freshly generated
per-codeword 16-byte hex secret, hashed with SHA-256, and DISCARDED from
memory before returning. The endpoint response carries the hash prefix only
so the clinician can recognize which codeword they just rotated. Plaintext
is NEVER logged, NEVER returned, NEVER cached. Comparison at runtime uses
``hmac.compare_digest`` (constant-time) — not handled here; that lives in
``nate_checkin_agent``.

AUDIT EMISSION
--------------
Every mutating endpoint writes a single ``sensitive_profile_mutation`` row
into ``sensitive_bridge_log`` with ``event_severity='moderate'`` (or the
event-specific severity for safe_silence_mode_state_change events) and a
JSONB payload that contains:
    - mutation_kind: e.g. 'embodiment_phase_set', 'codeword_added'
    - actor_role: 'COACH' | 'ADMIN'
    - actor_id_hash: SHA-256 hex of the actor's username + a daily salt
                     (avoids leaking actor identity into long-retention logs
                     while still letting auditors correlate same-actor
                     sequences within a day)
    - target_user_id: the survivor's username
    - additional_fields_redacted: bounded structured detail (no plaintext)

A defense-in-depth PII scan (via ``trigger_date_registry._screen_notes_for_pii``)
runs over every string value in ``additional_fields_redacted`` before insert.
The audit row is silently dropped — never raised — when the scan trips, so a
mutation never blocks on audit infrastructure failures.

NOT IN SCOPE
------------
- The Flutter screen (Note 3 of the Phase 4b directive) is a parallel
  deliverable, not part of this file.
- The 25-day expiry warning + 30-day auto-revert scheduler lives in
  ``nate_checkin_agent`` (Phase 3); this router only writes the timestamps.
- Trust-baseline registration of the new auditor checks is a Phase 5
  follow-up (``sensitive_bridge_auditor.py``).

EXPECTED FAILURE MODES (return shapes for the Flutter client)
-------------------------------------------------------------
- 401 → token invalid (handled upstream by ``get_current_user``)
- 403 ``not_assigned`` → coach is not on the user's coach_client_overrides
                        chain and not the assigned_coach in profile_data
- 403 ``role_required`` → caller lacks COACH/ADMIN role
- 404 ``user_not_found`` → target ``user_id`` not present in ``users``
- 409 ``same_session_violation`` → admin approver shares the proposer's
                                   session token; reject hard
- 409 ``requires_codeword`` → no active codeword for the user; the safe
                              silence channel has no fallback signal
- 409 ``stale_state`` → safe_silence_mode is not in ``pending_approval``
- 422 ``pii_pattern_in_field`` → free-text field tripped the PII screen;
                                 surface the offset to highlight
- 422 ``invalid_enum_value`` → caller submitted a value outside the
                               migration's CHECK constraint set
- 503 ``database_unavailable`` → no db_pool on app.state (cold-boot window)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import string
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, validator

from app.services.api_server import (
    get_current_user,
    require_admin,
    require_coach,
    security as _bearer_security,
)
from app.services.sensitive_clinical_bridge import FULL_ACTIVATION_GAP_FEATURES

logger = logging.getLogger(__name__)

# =============================================================================
# Module constants
# =============================================================================

#: Bumped whenever the request/response contract changes in a non-additive
#: way. Auditor reads this and asserts it matches the trust-baseline
#: ``sensitive_profile_api_contract_version`` row.
CONTRACT_VERSION = "1.0.0-2026-05-09"

#: Approval window from ``approved_at``. Plan Gap M.
SAFE_SILENCE_APPROVAL_TTL_DAYS = 30

#: Audit event names mirror the CHECK constraint on
#: ``sensitive_bridge_log.event_type`` (migration 202).
EVT_SENSITIVE_PROFILE_MUTATION = "sensitive_profile_mutation"
EVT_SAFE_SILENCE_STATE_CHANGE = "safe_silence_mode_state_change"

#: Audit access classifications (migration 202 CHECK).
ACCESS_CLINICIAN_AND_ADMIN = "clinician_and_admin"
ACCESS_CLINICIAN_ONLY = "clinician_only"
#: Admin-redacted view; clinicians MUST NOT receive these rows from the
#: ``/log`` endpoint (Note 2). The classification is a write-time tag set
#: by future orchestrator paths; we declare it here so the read endpoint
#: can filter explicitly rather than implicitly.
ACCESS_ADMIN_ONLY_REDACTED = "admin_only_redacted"

#: Safe-silence state values (migration 208 commentary).
SAFE_SILENCE_INACTIVE = "inactive"
SAFE_SILENCE_PENDING = "pending_approval"
SAFE_SILENCE_ACTIVE = "active"

#: Embodiment phase enum values per Gap 6 spec.
VALID_EMBODIMENT_PHASES = frozenset({"repair", "transitioning", "ready"})

#: Substance-status enum per Gap B.
VALID_SUBSTANCE_STATUSES = frozenset(
    {"none", "recovery", "active_use", "crisis"}
)

#: Behavioral / process addiction branches (v1.4) — coach-set scalar statuses.
VALID_ADDICTION_BRANCH_STATUSES = frozenset(
    {"none", "recovery", "active", "crisis"}
)

#: Codeword type values must match migration 204 CHECK constraint.
VALID_CODEWORD_TYPES = frozenset({"explicit_word", "innocuous_phrase"})

#: v1.4 part-aware codeword values (migration 217).
VALID_CODEWORD_DISCLOSURE_TYPES = frozenset(
    {
        "explicit_word",
        "innocuous_phrase",
        "soft_pause",
        "grounding_request",
        "covert_observation",
        "reengagement_risk",
        "active_harm",
        "imminent_danger",
        "addict_part_speaking",
        "dissociation_indicator",
        "part_conflict",
        "trafficking_history_disclosure",
        "trafficking_active_risk",
        "trafficking_imminent_danger",
    }
)
VALID_PART_CATEGORIES = frozenset(
    {
        "protector",
        "exile",
        "firefighter",
        "manager",
        "self_energy",
        "addict_part",
        "inner_critic",
        "caretaker",
        "dissociative_part",
        "inner_child",
        "other",
    }
)
VALID_CODEWORD_ADDICTION_LINKS = frozenset(
    {
        "substance",
        "sex",
        "sex_addiction",
        "gambling",
        "gaming",
        "food",
        "food_compulsion",
        "work",
        "work_compulsion",
        "spending",
        "spending_compulsion",
        "codependency",
        "trafficking",
        "none",
    }
)

#: Date type values must match migration 205 CHECK constraint.
VALID_TRIGGER_DATE_TYPES = frozenset(
    {
        "escape_anniversary",
        "first_exploitation",
        "legal_outcome",
        "related_death",
        "custody_outcome",
        "court_appearance",
        "medical_anniversary",
        "other",
    }
)

#: Severity values used across migrations 205/206.
VALID_SEVERITIES = frozenset({"low", "moderate", "high", "critical"})

#: Polyvictim layer types per migration 206.
VALID_POLYVICTIM_LAYERS = frozenset(
    {
        "childhood_abuse",
        "family_dysfunction",
        "prior_partner_violence",
        "trafficking",
        "post_trafficking_exploitation",
        "legal_system_trauma",
        "medical_trauma",
        "religious_trauma",
        "community_violence",
    }
)

#: Legal status enums per migration 207.
VALID_LEGAL_CASE_TYPES = frozenset(
    {
        "criminal_against_trafficker",
        "t_visa",
        "u_visa",
        "civil",
        "custody",
        "expungement",
        "protective_order",
        "other",
    }
)
VALID_LEGAL_CASE_STATUSES = frozenset(
    {
        "pending",
        "active_hearing_scheduled",
        "testifying_imminent",
        "deposition_imminent",
        "outcome_pending",
        "closed",
    }
)

#: Sliders accept floats in these ranges; out-of-range → 422.
NOVELTY_THRESHOLD_RANGE = (0.0, 1.0)
AROUSAL_THRESHOLD_RANGE = (0.0, 3.0)

#: Path C (M216) — coach-initiated enrollment cohort labels. Subset of the
#: full M209+M216 CHECK constraint that a coach is allowed to set from the
#: SensitiveClinicalProfileScreen banner. Admin retains the full set
#: (unenrolled, shadow_only, cohort_5, cohort_ga, etc.) via the existing
#: telemetry-agent surface.
VALID_COACH_ENROLLMENT_COHORTS = frozenset(
    {
        "inspection_test",
        "pilot_5",
        "cohort_25",
        "cohort_100",
        "general_availability",
    }
)

#: Path C — population type labels written to users.profile_data on
#: enrollment. The minor + transitioning_youth values trigger the
#: guardian-consent precondition; adult_survivor does not.
VALID_POPULATION_TYPES = frozenset(
    {
        "adult_survivor",
        "minor_survivor",
        "transitioning_youth_16_to_21",
    }
)

#: Population types that require ``users.profile_data->>'guardian_dual_approval_on_file' = 'true'``
#: before the enrollment endpoint will write the row. Path C explicitly
#: refuses to auto-enroll minors via this surface — admin must run the
#: existing guardian-consent flow first.
POPULATION_TYPES_REQUIRING_GUARDIAN_CONSENT = frozenset(
    {"minor_survivor", "transitioning_youth_16_to_21"}
)

#: Path C — audit event_type. Mirrors the M216 CHECK constraint addition
#: on ``sensitive_bridge_log.event_type``. If you add another enrollment-
#: adjacent event, also extend the migration's CHECK list.
EVT_ENROLLMENT_CREATED = "enrollment_created"

#: Activity log default window (Note 3 — Flutter UX expectation).
ACTIVITY_LOG_DEFAULT_DAYS = 7
ACTIVITY_LOG_MAX_DAYS = 365
ACTIVITY_LOG_MAX_ROWS = 500

#: Codeword normalization helpers — must MATCH ``nate_checkin_agent`` exactly,
#: otherwise a stored hash will never match a runtime utterance. The agent
#: uses NFKD → ASCII fold → lower → strip ``string.punctuation``.
_CODEWORD_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


def _normalize_codeword(text: str) -> str:
    """Mirror ``nate_checkin_agent._normalize_for_codeword`` for a single
    candidate string, returning the joined normalized form. Caller is
    responsible for never logging the input.
    """
    if not text:
        return ""
    folded = (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii", "ignore")
    )
    folded = folded.lower().translate(_CODEWORD_PUNCT_TABLE)
    return " ".join(t for t in folded.split() if t)


def _hash_codeword(plaintext: str, salt: str) -> str:
    """``sha256(normalize(plaintext) || salt)`` hex digest — same recipe the
    runtime listener uses. Plaintext is never persisted or logged.
    """
    return hashlib.sha256(
        (_normalize_codeword(plaintext) + salt).encode("utf-8")
    ).hexdigest()


def _token_session_hash(credentials: Optional[HTTPAuthorizationCredentials]) -> str:
    """Stable, irreversible hash of the bearer token. Used as the
    ``session_id`` for the same-session-violation check on
    ``/safe-silence/approve`` (Risk #19).

    We hash because the raw bearer must NEVER be persisted. The hash is
    deterministic so two requests bearing the same token produce identical
    hashes; once approval succeeds the proposer hash is wiped from the JSONB
    so it cannot be used to correlate sessions later.
    """
    if credentials is None or not credentials.credentials:
        return ""
    return hashlib.sha256(credentials.credentials.encode("utf-8")).hexdigest()


# =============================================================================
# Sole-clinician authorization lookup (migration 214)
# =============================================================================

CLIN_AUTH_SOLE_LEAD = "sole_lead"
CLIN_AUTH_MULTI = "multi_clinician_team"


async def _lookup_clinician_authorization_type(conn, actor_username: str) -> str:
    """Return the actor's ``clinician_authorization_type`` per migration 214.

    Falls back to ``'multi_clinician_team'`` if the row, the column, or the
    table is missing (pre-migration boot, fresh staging clone). The default
    is the SAFE answer because it forces the strict two-clinician gate; a
    missing row must never accidentally widen the sole-lead exemption.
    """
    if not actor_username:
        return CLIN_AUTH_MULTI
    try:
        val = await conn.fetchval(
            """
            SELECT clinician_authorization_type
              FROM coach_profiles
             WHERE username = $1
             LIMIT 1
            """,
            actor_username,
        )
    except Exception as e:  # pragma: no cover - defense in depth
        logger.warning(
            "sensitive_profile_api: clinician_authorization_type lookup failed "
            "for actor=%s: %s — defaulting to multi_clinician_team",
            actor_username,
            e,
        )
        return CLIN_AUTH_MULTI
    if val == CLIN_AUTH_SOLE_LEAD:
        return CLIN_AUTH_SOLE_LEAD
    return CLIN_AUTH_MULTI


# =============================================================================
# PII screen — reuses trigger_date_registry's pattern set so both write paths
# enforce identical guarantees.
# =============================================================================


def _import_pii_screen():
    """Lazy import so a missing module surfaces as 503 at request time, not as
    an ImportError at boot that would kill the entire FastAPI process.
    """
    from app.services.trigger_date_registry import (
        _screen_notes_for_pii as _screen,
        PIIScreenViolation as _Exc,
    )

    return _screen, _Exc


def _raise_if_pii(field_name: str, text: Optional[str]) -> None:
    """422 if ``text`` trips the PII screen. No-op for ``None`` / empty."""
    if not text:
        return
    screen, PIIScreenViolation = _import_pii_screen()
    hit = screen(text)
    if hit is not None:
        label, position = hit
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "reason": "pii_pattern_in_field",
                "field": field_name,
                "pattern_matched": label,
                "field_position": position,
            },
        )


# =============================================================================
# Auth dependency — Note 1 (BLOCKING)
# =============================================================================
#
# Every coach endpoint declares ``Depends(require_clinician_for_user)``.
# The auditor at ``phase4b_all_coach_endpoints_use_require_clinician_for_user``
# greps the route definitions in this file. If a developer adds a new
# /api/coach/sensitive-profile/... endpoint without the dependency, the
# auditor fails the next trust window. Single fix surface.
#
# Why we don't drop assignment-check logic into middleware:
#   - middleware sees the request before path params are resolved
#   - FastAPI deps run after path resolution, so they get ``user_id`` cleanly
#   - middleware can be skipped via ``include_in_schema`` route ordering;
#     a Depends() declared on the route cannot be elided.


async def require_clinician_for_user(
    user_id: str,
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        _bearer_security
    ),
    principal: Dict[str, Any] = Depends(require_coach),
) -> Dict[str, Any]:
    """Gate every coach-side sensitive-profile route.

    Verifies:
      1. Caller has COACH or ADMIN role (delegated to ``require_coach``).
      2. Target ``user_id`` exists in ``users``.
      3. Caller is the assigned/supervising clinician for that user via:
         (a) ``coach_client_overrides`` (canonical override mapping), OR
         (b) ``users.profile_data->>'coach_id'``,
             ``users.profile_data->>'assigned_coach_id'``, or
             ``users.profile_data->>'assigned_coach'`` (legacy assignment
             paths still supported per
             ``coach-client-assignment-fields.mdc``).

    Returns a copy of the principal with two private keys appended:
      - ``_target_user_id``: echoed for downstream handler convenience.
      - ``_token_session_hash``: SHA-256 of the bearer token; the
        ``/safe-silence/approve`` endpoint reads this to enforce the
        same-session-violation guarantee.

    Raises:
      - 403 ``role_required`` (delegated to ``require_coach``).
      - 403 ``not_assigned`` if the assignment query returns no rows.
      - 404 ``user_not_found`` if the target username is not in ``users``.
      - 503 ``database_unavailable`` if the connection pool is missing.
    """
    # Audit token: trust-auditor probes every protected endpoint and must
    # round-trip without DB lookups. Mirrors api_server.get_current_user's
    # bypass logic.
    if principal.get("is_audit"):
        return {
            **principal,
            "_target_user_id": user_id,
            "_token_session_hash": _token_session_hash(credentials),
        }

    # Slice 6c: PHI MFA freshness gate. Dormant unless ENABLE_PHI_MFA_GATE
    # is on. Runs BEFORE the admin bypass on purpose — admins must
    # re-verify too. Auditors already returned above. Raises 401 with
    # code=MFA_REVERIFY_REQUIRED when stale.
    from app.services.mfa_gate import enforce_mfa_recent
    await enforce_mfa_recent(
        getattr(request.app.state, "db_pool", None), principal
    )

    # Admin role ALWAYS satisfies the assignment check — admins are the
    # supervising layer for every clinician relationship.
    if principal.get("role") == "ADMIN":
        return {
            **principal,
            "_target_user_id": user_id,
            "_token_session_hash": _token_session_hash(credentials),
        }

    db_pool = getattr(request.app.state, "db_pool", None)
    if db_pool is None:
        raise HTTPException(
            status_code=503,
            detail={"reason": "database_unavailable"},
        )

    coach_username = principal.get("username") or principal.get("user_id") or ""
    coach_hardware_id = principal.get("hardware_id") or ""
    if not coach_username:
        # Defensive: should be impossible after require_coach succeeds.
        raise HTTPException(
            status_code=403,
            detail={"reason": "principal_missing_username"},
        )

    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow(
            "SELECT username FROM users WHERE username = $1",
            user_id,
        )
        if user_row is None:
            raise HTTPException(
                status_code=404,
                detail={"reason": "user_not_found", "user_id": user_id},
            )

        # Path A: coach_client_overrides table. The coach_user_id column is
        # VARCHAR and may carry either a username or a hardware_id depending
        # on how the override was set; check both.
        ov_row = await conn.fetchrow(
            """
            SELECT 1 FROM coach_client_overrides
             WHERE coach_user_id IN ($1, $2)
               AND client_user_id = $3
             LIMIT 1
            """,
            coach_username,
            coach_hardware_id,
            user_id,
        )
        if ov_row is not None:
            return {
                **principal,
                "_target_user_id": user_id,
                "_token_session_hash": _token_session_hash(credentials),
            }

        # Path B: legacy assignment fields in profile_data JSONB. Per
        # coach-client-assignment-fields.mdc all three fields must be in
        # sync, but defensively we check all three.
        assign_row = await conn.fetchrow(
            """
            SELECT 1 FROM users
             WHERE username = $1
               AND (
                     profile_data->>'assigned_coach' = $2
                  OR profile_data->>'coach_id' = $3
                  OR profile_data->>'assigned_coach_id' = $3
                  OR profile_data->>'assigned_coach' = $4
                   )
             LIMIT 1
            """,
            user_id,
            coach_username,
            coach_hardware_id,
            coach_hardware_id,
        )
        if assign_row is not None:
            return {
                **principal,
                "_target_user_id": user_id,
                "_token_session_hash": _token_session_hash(credentials),
            }

    raise HTTPException(
        status_code=403,
        detail={"reason": "not_assigned", "user_id": user_id},
    )


async def require_admin_with_session_token(
    user_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        _bearer_security
    ),
    principal: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Admin-only dependency that also exposes the session-token hash.

    The WebAuthn YubiKey requirement is enforced as a global session
    posture by the trust auditors (see ``webauthn-yubikey-security.mdc``);
    we do NOT re-check it per route. Adding a per-route check would be
    duplicative and would let a developer accidentally diverge from the
    global posture.
    """
    return {
        **principal,
        "_target_user_id": user_id,
        "_token_session_hash": _token_session_hash(credentials),
    }


# =============================================================================
# Audit emission helper
# =============================================================================


def _hash_actor_id(actor_id: str) -> str:
    """Day-bucketed hash of the actor identifier so auditors can correlate
    a sequence of mutations from the same actor within a single day without
    persisting plaintext usernames into a 7-year-retention table.
    """
    if not actor_id:
        return ""
    today = datetime.now(timezone.utc).date().isoformat()
    return hashlib.sha256(f"{actor_id}|{today}".encode("utf-8")).hexdigest()[:32]


async def _emit_profile_mutation_audit(
    db_pool,
    *,
    target_user_id: str,
    actor_id: str,
    actor_role: str,
    mutation_kind: str,
    additional_fields_redacted: Dict[str, Any],
    severity: str = "moderate",
    event_type: str = EVT_SENSITIVE_PROFILE_MUTATION,
    access_classification: str = ACCESS_CLINICIAN_AND_ADMIN,
) -> None:
    """Write a single ``sensitive_bridge_log`` row. Best-effort: failure
    logs a warning but does NOT fail the mutating request — the mutation
    itself has already committed. Audit gaps are visible to the Phase 5
    auditor's freshness check, which is the correct alarm path.
    """
    payload = {
        "mutation_kind": mutation_kind,
        "actor_role": actor_role,
        "actor_id_hash": _hash_actor_id(actor_id),
        "target_user_id": target_user_id,
        "additional_fields_redacted": additional_fields_redacted,
        "contract_version": CONTRACT_VERSION,
    }

    # Defense-in-depth PII scan over any string values that bubbled into the
    # audit payload via additional_fields_redacted. The API entry points
    # (_raise_if_pii) already screened user-supplied notes/reasons; this
    # second pass catches a developer who appends an unscreened scalar to
    # additional_fields_redacted in a future patch. We log and skip rather
    # than raise — audit infrastructure must never block a mutation.
    try:
        screen_fn, _PIIExc = _import_pii_screen()
        for k, v in (additional_fields_redacted or {}).items():
            if isinstance(v, str) and v:
                hit = screen_fn(v)
                if hit is not None:
                    label, position = hit
                    logger.warning(
                        "sensitive_profile_api: PII detected in audit payload "
                        "kind=%s user=%s field=%s pattern=%s pos=%d — skipping audit row",
                        mutation_kind,
                        target_user_id,
                        f"audit:{k}",
                        label,
                        position,
                    )
                    return
    except Exception as e:  # pragma: no cover — defense in depth
        logger.warning(
            "sensitive_profile_api: audit payload validator failed unexpectedly "
            "for kind=%s user=%s — skipping audit row: %s",
            mutation_kind,
            target_user_id,
            e,
        )
        return

    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sensitive_bridge_log (
                    user_id, event_type, event_severity,
                    payload_json, decision_summary,
                    occurred_at, recorded_by, access_classification,
                    pii_screened_at, redaction_pass_count
                ) VALUES ($1, $2, $3, $4::jsonb, $5::jsonb,
                          NOW(), $6, $7, NOW(), 1)
                """,
                target_user_id,
                event_type,
                severity,
                json.dumps(payload),
                json.dumps({"contract_version": CONTRACT_VERSION}),
                "sensitive_profile_api",
                access_classification,
            )
    except Exception as e:
        logger.warning(
            "sensitive_profile_api: audit insert failed for kind=%s user=%s: %s",
            mutation_kind,
            target_user_id,
            e,
        )


# =============================================================================
# Pydantic request bodies
# =============================================================================


class EmbodimentPhaseUpdate(BaseModel):
    embodiment_phase: str = Field(..., description="repair|transitioning|ready")

    @validator("embodiment_phase")
    def _v_phase(cls, v):
        if v not in VALID_EMBODIMENT_PHASES:
            raise ValueError("embodiment_phase must be one of repair|transitioning|ready")
        return v


class NoveltyThresholdUpdate(BaseModel):
    novelty_threshold: float = Field(..., ge=0.0, le=1.0)
    population_preset: Optional[str] = Field(
        default=None,
        description="Optional preset label for telemetry (e.g., 'general', 'survivor_high_acuity')",
    )


class ArousalThresholdUpdate(BaseModel):
    arousal_threshold: float = Field(..., ge=0.0, le=3.0)
    population_preset: Optional[str] = Field(default=None)


class SubstanceStatusUpdate(BaseModel):
    substance_status: str

    @validator("substance_status")
    def _v_status(cls, v):
        if v not in VALID_SUBSTANCE_STATUSES:
            raise ValueError("substance_status must be one of none|recovery|active_use|crisis")
        return v


class AddictionBranchStatusUpdate(BaseModel):
    """v1.4 coach-set status for sex/gambling/gaming/food/work/spending/codependency."""

    status: str
    subtype: Optional[str] = Field(default=None, max_length=64)

    @validator("status")
    def _v_status(cls, v):
        if v not in VALID_ADDICTION_BRANCH_STATUSES:
            raise ValueError(
                "status must be one of none|recovery|active|crisis"
            )
        return v


class CrossAddictionProfileUpdate(BaseModel):
    cross_addiction_profile: Dict[str, Any] = Field(default_factory=dict)


class CodewordCreate(BaseModel):
    plaintext_codeword: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description="Plaintext codeword. Hashed and discarded; never persisted or returned.",
    )
    codeword_type: str = Field(...)
    codeword_label: Optional[str] = Field(default=None, max_length=64)
    triggers_mandatory_reporting: bool = Field(default=False)
    disclosure_type: Optional[str] = Field(default=None)
    part_name: Optional[str] = Field(default=None, max_length=80)
    part_number: Optional[int] = Field(default=None, ge=1, le=999)
    part_category: Optional[str] = Field(default=None)
    addiction_link: Optional[str] = Field(default=None)

    @validator("codeword_type")
    def _v_type(cls, v):
        if v not in VALID_CODEWORD_TYPES:
            raise ValueError("codeword_type must be one of explicit_word|innocuous_phrase")
        return v

    @validator("disclosure_type")
    def _v_disclosure_type(cls, v):
        if v is not None and v not in VALID_CODEWORD_DISCLOSURE_TYPES:
            raise ValueError(
                "disclosure_type must be one of "
                + "|".join(sorted(VALID_CODEWORD_DISCLOSURE_TYPES))
            )
        return v

    @validator("part_category")
    def _v_part_category(cls, v):
        if v is not None and v not in VALID_PART_CATEGORIES:
            raise ValueError(
                "part_category must be one of " + "|".join(sorted(VALID_PART_CATEGORIES))
            )
        return v

    @validator("addiction_link")
    def _v_addiction_link(cls, v):
        if v is not None and v not in VALID_CODEWORD_ADDICTION_LINKS:
            raise ValueError(
                "addiction_link must be one of "
                + "|".join(sorted(VALID_CODEWORD_ADDICTION_LINKS))
            )
        return v


class TriggerDateCreate(BaseModel):
    trigger_date: date
    date_type: str
    severity: str = "high"
    recurring_annually: bool = True
    notes_redacted: Optional[str] = Field(default=None, max_length=1000)

    @validator("date_type")
    def _v_dtype(cls, v):
        if v not in VALID_TRIGGER_DATE_TYPES:
            raise ValueError(
                "date_type must be one of " + "|".join(sorted(VALID_TRIGGER_DATE_TYPES))
            )
        return v

    @validator("severity")
    def _v_sev(cls, v):
        if v not in VALID_SEVERITIES:
            raise ValueError("severity must be one of low|moderate|high|critical")
        return v


class PolyvictimLayerCreate(BaseModel):
    layer_type: str
    severity: str
    notes_redacted: Optional[str] = Field(default=None, max_length=1000)

    @validator("layer_type")
    def _v_layer(cls, v):
        if v not in VALID_POLYVICTIM_LAYERS:
            raise ValueError(
                "layer_type must be one of " + "|".join(sorted(VALID_POLYVICTIM_LAYERS))
            )
        return v

    @validator("severity")
    def _v_sev(cls, v):
        if v not in VALID_SEVERITIES:
            raise ValueError("severity must be one of low|moderate|high|critical")
        return v


class LegalStatusCreate(BaseModel):
    case_type: str
    case_status: str
    next_event_date: Optional[date] = None
    attorney_contact_redacted: Optional[str] = Field(default=None, max_length=200)

    @validator("case_type")
    def _v_ct(cls, v):
        if v not in VALID_LEGAL_CASE_TYPES:
            raise ValueError(
                "case_type must be one of " + "|".join(sorted(VALID_LEGAL_CASE_TYPES))
            )
        return v

    @validator("case_status")
    def _v_cs(cls, v):
        if v not in VALID_LEGAL_CASE_STATUSES:
            raise ValueError(
                "case_status must be one of " + "|".join(sorted(VALID_LEGAL_CASE_STATUSES))
            )
        return v


class LegalStatusPatch(BaseModel):
    case_status: Optional[str] = None
    next_event_date: Optional[date] = None
    attorney_contact_redacted: Optional[str] = Field(default=None, max_length=200)

    @validator("case_status")
    def _v_cs(cls, v):
        if v is None:
            return v
        if v not in VALID_LEGAL_CASE_STATUSES:
            raise ValueError(
                "case_status must be one of " + "|".join(sorted(VALID_LEGAL_CASE_STATUSES))
            )
        return v


class SafeSilencePropose(BaseModel):
    reason_redacted: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Short clinical reason; PII-screened. Surfaces to admin reviewer.",
    )


class SafeSilenceApprove(BaseModel):
    proposal_id: str = Field(
        ...,
        min_length=8,
        max_length=64,
        description="Echo of the proposal record's id (hex token returned by "
        "/propose). Prevents an admin from approving a stale or rotated "
        "proposal. Stored verbatim in safe_silence_mode_state.proposal_id.",
    )
    approver_note_redacted: Optional[str] = Field(default=None, max_length=500)


class CoachInitiatedEnrollment(BaseModel):
    """Path C — coach-initiated self-enrollment from the
    SensitiveClinicalProfileScreen banner. Field names are sealed (the
    Flutter dialog parses them verbatim).

    ``informed_consent_confirmed`` is gated server-side: the endpoint
    refuses to write the row unless this is True. The dialog's submit
    button is disabled until the checkbox is checked, but never trust the
    client — the server is the contract.

    ``cohort_label`` and ``population_type`` are validated against the
    M216-extended enums; mismatches surface as 422 invalid_enum_value.
    """

    cohort_label: str = Field(
        ...,
        description="One of: inspection_test, pilot_5, cohort_25, cohort_100, general_availability",
    )
    population_type: str = Field(
        ...,
        description="One of: adult_survivor, minor_survivor, transitioning_youth_16_to_21",
    )
    # QUANTUM-CRYSTAL-ARCH: occupational crisis routing (orthogonal to population_type)
    occupational_population: Optional[str] = Field(
        default=None,
        description="Optional: veteran|first_responder_le|first_responder_fire_ems|"
        "military_family|general — writes profile_data.population for crisis lines",
    )
    informed_consent_confirmed: bool = Field(
        ...,
        description="Coach confirms the client has provided HIPAA-grade informed "
        "consent. Server refuses enrollment if False.",
    )

    @validator("cohort_label")
    def _v_cohort(cls, v):
        if v not in VALID_COACH_ENROLLMENT_COHORTS:
            raise ValueError(
                "cohort_label must be one of "
                + "|".join(sorted(VALID_COACH_ENROLLMENT_COHORTS))
            )
        return v

    @validator("population_type")
    def _v_pop(cls, v):
        if v not in VALID_POPULATION_TYPES:
            raise ValueError(
                "population_type must be one of "
                + "|".join(sorted(VALID_POPULATION_TYPES))
            )
        return v


# =============================================================================
# Profile read helpers — used by both GET endpoints
# =============================================================================


async def _load_profile_data(
    db_pool,
    user_id: str,
    *,
    coach_username: Optional[str] = None,
) -> Dict[str, Any]:
    """Pull the JSONB profile fields the portal cares about.

    Returns an empty dict if the user has no rows in any sub-table; the
    Flutter screen treats missing keys as "not configured yet" — never as
    an error.

    Path C (M215+M216) attaches three additional keys consumed by the new
    _NotEnrolledBanner widget on SensitiveClinicalProfileScreen:
      • ``is_enrolled``                          — bool, from sensitive_bridge_enrollment
      • ``coach_sensitive_bridge_authorized``    — bool, from coach_profiles
      • ``population_type``                      — str|None, mirrored from
        users.profile_data so the post-enrollment refresh shows the value
        the coach just set in the dialog without a second round-trip.
    """
    out: Dict[str, Any] = {
        "user_id": user_id,
        "embodiment_phase": None,
        "novelty_threshold": None,
        "arousal_threshold": None,
        "substance_status": None,
        "sex_addiction_status": None,
        "gambling_status": None,
        "gaming_status": None,
        "food_compulsion_status": None,
        "work_compulsion_status": None,
        "spending_compulsion_status": None,
        "codependency_status": None,
        "cross_addiction_profile": {},
        "population_type": None,
        "safe_silence_mode_state": {},
        "codewords": [],
        "trigger_dates": [],
        "polyvictim_layers": [],
        "legal_status": [],
        # Path C visibility flags (M215+M216). Defaults are the closed
        # state: not enrolled, coach not authorized.
        "is_enrolled": False,
        "coach_sensitive_bridge_authorized": False,
    }

    async with db_pool.acquire() as conn:
        urow = await conn.fetchrow(
            """
            SELECT profile_data
              FROM users
             WHERE username = $1
            """,
            user_id,
        )
        if urow is not None:
            pd = urow["profile_data"] or {}
            if isinstance(pd, str):
                try:
                    pd = json.loads(pd)
                except Exception:
                    pd = {}
            out["embodiment_phase"] = pd.get("embodiment_phase")
            out["novelty_threshold"] = pd.get("novelty_threshold")
            out["arousal_threshold"] = pd.get("arousal_threshold")
            out["substance_status"] = pd.get("substance_status")
            out["sex_addiction_status"] = pd.get("sex_addiction_status")
            out["gambling_status"] = pd.get("gambling_status")
            out["gaming_status"] = pd.get("gaming_status")
            out["food_compulsion_status"] = pd.get("food_compulsion_status")
            out["work_compulsion_status"] = pd.get("work_compulsion_status")
            out["spending_compulsion_status"] = pd.get("spending_compulsion_status")
            out["codependency_status"] = pd.get("codependency_status")
            cap = pd.get("cross_addiction_profile")
            out["cross_addiction_profile"] = (
                cap if isinstance(cap, dict) else {}
            )
            out["population_type"] = pd.get("population_type")
            sss = pd.get("safe_silence_mode_state") or {}
            # NEVER surface the proposer_token_hash to clients — it's a
            # session secret used only by the approve endpoint.
            sss_safe = {k: v for k, v in sss.items() if k != "proposer_token_hash"}
            out["safe_silence_mode_state"] = sss_safe

        # Path C: attach enrollment + coach authorization flags. Both are
        # tiny SELECTs on indexed columns; the cost is negligible compared
        # to the four sub-table fetches below.
        try:
            enroll_row = await conn.fetchrow(
                "SELECT 1 FROM sensitive_bridge_enrollment WHERE user_id = $1",
                user_id,
            )
            out["is_enrolled"] = enroll_row is not None
        except Exception as e:
            logger.warning(
                "sensitive_profile_api: enrollment lookup failed for %s: %s",
                user_id, e,
            )

        if coach_username:
            try:
                cp_row = await conn.fetchrow(
                    """
                    SELECT coach_sensitive_bridge_authorized
                      FROM coach_profiles
                     WHERE username = $1
                    """,
                    coach_username,
                )
                if cp_row is not None:
                    out["coach_sensitive_bridge_authorized"] = bool(
                        cp_row["coach_sensitive_bridge_authorized"]
                    )
            except Exception as e:
                logger.warning(
                    "sensitive_profile_api: coach auth lookup failed for %s: %s",
                    coach_username, e,
                )

        cw_rows = await conn.fetch(
            """
            SELECT codeword_hash, codeword_type, codeword_label,
                   triggers_mandatory_reporting, set_by_clinician_id, set_at,
                   active, last_triggered_at, trigger_count,
                   disclosure_type, part_name, part_number, part_category, addiction_link
              FROM user_safety_codewords
             WHERE user_id = $1
             ORDER BY set_at DESC
            """,
            user_id,
        )
        out["codewords"] = [
            {
                "hash_prefix": r["codeword_hash"][:12],
                "codeword_type": r["codeword_type"],
                "codeword_label": r["codeword_label"],
                "triggers_mandatory_reporting": r["triggers_mandatory_reporting"],
                "set_by_clinician_id": r["set_by_clinician_id"],
                "set_at": r["set_at"].isoformat() if r["set_at"] else None,
                "active": r["active"],
                "last_triggered_at": (
                    r["last_triggered_at"].isoformat()
                    if r["last_triggered_at"]
                    else None
                ),
                "trigger_count": r["trigger_count"],
                "disclosure_type": r.get("disclosure_type"),
                "part_name": r.get("part_name"),
                "part_number": r.get("part_number"),
                "part_category": r.get("part_category"),
                "addiction_link": r.get("addiction_link"),
            }
            for r in cw_rows
        ]

        td_rows = await conn.fetch(
            """
            SELECT id, trigger_date, date_type, severity, recurring_annually,
                   notes_redacted, set_by_clinician_id, set_at, active
              FROM user_trigger_dates
             WHERE user_id = $1
             ORDER BY set_at DESC
            """,
            user_id,
        )
        out["trigger_dates"] = [
            {
                "id": r["id"],
                "trigger_date": r["trigger_date"].isoformat(),
                "date_type": r["date_type"],
                "severity": r["severity"],
                "recurring_annually": r["recurring_annually"],
                "notes_redacted": r["notes_redacted"],
                "set_by_clinician_id": r["set_by_clinician_id"],
                "set_at": r["set_at"].isoformat() if r["set_at"] else None,
                "active": r["active"],
            }
            for r in td_rows
        ]

        pv_rows = await conn.fetch(
            """
            SELECT id, layer_type, severity, active,
                   set_by_clinician_id, set_at, notes_redacted
              FROM user_polyvictimization_layers
             WHERE user_id = $1
             ORDER BY set_at DESC
            """,
            user_id,
        )
        out["polyvictim_layers"] = [
            {
                "id": r["id"],
                "layer_type": r["layer_type"],
                "severity": r["severity"],
                "active": r["active"],
                "set_by_clinician_id": r["set_by_clinician_id"],
                "set_at": r["set_at"].isoformat() if r["set_at"] else None,
                "notes_redacted": r["notes_redacted"],
            }
            for r in pv_rows
        ]

        ls_rows = await conn.fetch(
            """
            SELECT id, case_type, case_status, next_event_date,
                   attorney_contact_redacted, set_by_case_manager_id,
                   set_at, active
              FROM user_legal_status
             WHERE user_id = $1
             ORDER BY set_at DESC
            """,
            user_id,
        )
        out["legal_status"] = [
            {
                "id": r["id"],
                "case_type": r["case_type"],
                "case_status": r["case_status"],
                "next_event_date": (
                    r["next_event_date"].isoformat()
                    if r["next_event_date"]
                    else None
                ),
                "attorney_contact_redacted": r["attorney_contact_redacted"],
                "set_by_case_manager_id": r["set_by_case_manager_id"],
                "set_at": r["set_at"].isoformat() if r["set_at"] else None,
                "active": r["active"],
            }
            for r in ls_rows
        ]

    return out


async def _patch_user_profile_data(
    db_pool, user_id: str, key: str, value: Any
) -> None:
    """Patch a single key in users.profile_data JSONB without clobbering
    other keys. Uses ``jsonb_set`` so we never overwrite the whole blob.
    """
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE users
               SET profile_data = jsonb_set(
                       COALESCE(profile_data, '{}'::jsonb),
                       ARRAY[$2],
                       to_jsonb($3::text)::jsonb,
                       true
                   ),
                   updated_at = NOW()
             WHERE username = $1
            """,
            user_id,
            key,
            json.dumps(value) if not isinstance(value, str) else value,
        )


async def _patch_profile_jsonb_object(
    db_pool, user_id: str, key: str, value: Dict[str, Any]
) -> None:
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE users
               SET profile_data = jsonb_set(
                       COALESCE(profile_data, '{}'::jsonb),
                       $2::text[],
                       $3::jsonb,
                       true
                   ),
                   updated_at = NOW()
             WHERE username = $1
            """,
            user_id,
            [key],
            json.dumps(value),
        )


async def _fetch_profile_text_field(
    db_pool, user_id: str, field_key: str
) -> Optional[str]:
    async with db_pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT profile_data->>$2 FROM users WHERE username = $1",
            user_id,
            field_key,
        )


async def _append_addiction_status_history(
    db_pool,
    user_id: str,
    addiction_type: str,
    previous_status: Optional[str],
    new_status: str,
    set_by: str,
    *,
    subtype: Optional[str] = None,
    notes: Optional[str] = None,
) -> None:
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO addiction_status_history (
                user_id, addiction_type, previous_status, new_status,
                subtype, set_by, notes
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            user_id,
            addiction_type,
            previous_status,
            new_status,
            subtype,
            set_by,
            notes,
        )


async def _coach_put_addiction_branch_status(
    *,
    db_pool,
    user_id: str,
    profile_key: str,
    addiction_type: str,
    body: AddictionBranchStatusUpdate,
    principal: Dict[str, Any],
) -> Dict[str, Any]:
    prev = await _fetch_profile_text_field(db_pool, user_id, profile_key)
    await _patch_user_profile_data(db_pool, user_id, profile_key, body.status)
    actor = principal.get("username", "") or principal.get("user_id", "") or ""
    await _append_addiction_status_history(
        db_pool,
        user_id,
        addiction_type,
        previous_status=str(prev) if prev is not None else None,
        new_status=body.status,
        set_by=actor,
        subtype=body.subtype,
        notes=None,
    )
    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=actor,
        actor_role=principal.get("role", "COACH"),
        mutation_kind=f"{profile_key}_set",
        additional_fields_redacted={
            "new_value": body.status,
            "subtype": body.subtype,
        },
    )
    return {"ok": True, profile_key: body.status}


# =============================================================================
# Routers
# =============================================================================

coach_router = APIRouter(
    prefix="/api/coach/sensitive-profile",
    tags=["sensitive-profile-coach"],
)
admin_router = APIRouter(
    prefix="/api/admin/sensitive-profile",
    tags=["sensitive-profile-admin"],
)


# ------- COACH: full profile read --------------------------------------------


@coach_router.get("/{user_id}")
async def get_full_profile(
    user_id: str,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    """Return the full clinician-visible profile for ``user_id``.

    Codewords are returned as hash-prefixes ONLY; plaintext is unrecoverable
    from the database. The Flutter screen renders each prefix alongside its
    label/type/active flag so a clinician can identify which codeword to
    rotate or revoke.
    """
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    coach_username = principal.get("username") or principal.get("user_id") or ""
    return await _load_profile_data(
        db_pool, user_id, coach_username=coach_username
    )


# ------- COACH: scalar setters ------------------------------------------------


@coach_router.put("/{user_id}/embodiment-phase")
async def set_embodiment_phase(
    user_id: str,
    body: EmbodimentPhaseUpdate,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    await _patch_user_profile_data(
        db_pool, user_id, "embodiment_phase", body.embodiment_phase
    )
    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=principal.get("username", ""),
        actor_role=principal.get("role", "COACH"),
        mutation_kind="embodiment_phase_set",
        additional_fields_redacted={"new_value": body.embodiment_phase},
    )
    return {"ok": True, "embodiment_phase": body.embodiment_phase}


@coach_router.put("/{user_id}/novelty-threshold")
async def set_novelty_threshold(
    user_id: str,
    body: NoveltyThresholdUpdate,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    await _patch_user_profile_data(
        db_pool, user_id, "novelty_threshold", float(body.novelty_threshold)
    )
    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=principal.get("username", ""),
        actor_role=principal.get("role", "COACH"),
        mutation_kind="novelty_threshold_set",
        additional_fields_redacted={
            "new_value": body.novelty_threshold,
            "population_preset": body.population_preset,
        },
    )
    return {"ok": True, "novelty_threshold": body.novelty_threshold}


@coach_router.put("/{user_id}/arousal-threshold")
async def set_arousal_threshold(
    user_id: str,
    body: ArousalThresholdUpdate,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    await _patch_user_profile_data(
        db_pool, user_id, "arousal_threshold", float(body.arousal_threshold)
    )
    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=principal.get("username", ""),
        actor_role=principal.get("role", "COACH"),
        mutation_kind="arousal_threshold_set",
        additional_fields_redacted={
            "new_value": body.arousal_threshold,
            "population_preset": body.population_preset,
        },
    )
    return {"ok": True, "arousal_threshold": body.arousal_threshold}


@coach_router.put("/{user_id}/substance-status")
async def set_substance_status(
    user_id: str,
    body: SubstanceStatusUpdate,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    prev = await _fetch_profile_text_field(db_pool, user_id, "substance_status")
    await _patch_user_profile_data(
        db_pool, user_id, "substance_status", body.substance_status
    )
    actor = principal.get("username", "") or principal.get("user_id", "") or ""
    await _append_addiction_status_history(
        db_pool,
        user_id,
        "substance",
        previous_status=str(prev) if prev is not None else None,
        new_status=body.substance_status,
        set_by=actor,
        subtype=None,
        notes=None,
    )
    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=actor,
        actor_role=principal.get("role", "COACH"),
        mutation_kind="substance_status_set",
        additional_fields_redacted={"new_value": body.substance_status},
    )
    return {"ok": True, "substance_status": body.substance_status}


@coach_router.put("/{user_id}/sex-addiction-status")
async def set_sex_addiction_status(
    user_id: str,
    body: AddictionBranchStatusUpdate,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    return await _coach_put_addiction_branch_status(
        db_pool=db_pool,
        user_id=user_id,
        profile_key="sex_addiction_status",
        addiction_type="sex_addiction",
        body=body,
        principal=principal,
    )


@coach_router.put("/{user_id}/gambling-status")
async def set_gambling_status(
    user_id: str,
    body: AddictionBranchStatusUpdate,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    return await _coach_put_addiction_branch_status(
        db_pool=db_pool,
        user_id=user_id,
        profile_key="gambling_status",
        addiction_type="gambling",
        body=body,
        principal=principal,
    )


@coach_router.put("/{user_id}/gaming-status")
async def set_gaming_status(
    user_id: str,
    body: AddictionBranchStatusUpdate,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    return await _coach_put_addiction_branch_status(
        db_pool=db_pool,
        user_id=user_id,
        profile_key="gaming_status",
        addiction_type="gaming",
        body=body,
        principal=principal,
    )


@coach_router.put("/{user_id}/food-compulsion-status")
async def set_food_compulsion_status(
    user_id: str,
    body: AddictionBranchStatusUpdate,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    return await _coach_put_addiction_branch_status(
        db_pool=db_pool,
        user_id=user_id,
        profile_key="food_compulsion_status",
        addiction_type="food_compulsion",
        body=body,
        principal=principal,
    )


@coach_router.put("/{user_id}/work-compulsion-status")
async def set_work_compulsion_status(
    user_id: str,
    body: AddictionBranchStatusUpdate,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    return await _coach_put_addiction_branch_status(
        db_pool=db_pool,
        user_id=user_id,
        profile_key="work_compulsion_status",
        addiction_type="work_compulsion",
        body=body,
        principal=principal,
    )


@coach_router.put("/{user_id}/spending-compulsion-status")
async def set_spending_compulsion_status(
    user_id: str,
    body: AddictionBranchStatusUpdate,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    return await _coach_put_addiction_branch_status(
        db_pool=db_pool,
        user_id=user_id,
        profile_key="spending_compulsion_status",
        addiction_type="spending_compulsion",
        body=body,
        principal=principal,
    )


@coach_router.put("/{user_id}/codependency-status")
async def set_codependency_status(
    user_id: str,
    body: AddictionBranchStatusUpdate,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    return await _coach_put_addiction_branch_status(
        db_pool=db_pool,
        user_id=user_id,
        profile_key="codependency_status",
        addiction_type="codependency",
        body=body,
        principal=principal,
    )


@coach_router.put("/{user_id}/cross-addiction-profile")
async def set_cross_addiction_profile(
    user_id: str,
    body: CrossAddictionProfileUpdate,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    await _patch_profile_jsonb_object(
        db_pool, user_id, "cross_addiction_profile", body.cross_addiction_profile
    )
    actor = principal.get("username", "") or principal.get("user_id", "") or ""
    await _append_addiction_status_history(
        db_pool,
        user_id,
        "cross_addiction_profile",
        previous_status=None,
        new_status="profile_updated",
        set_by=actor,
        subtype=None,
        notes=None,
    )
    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=actor,
        actor_role=principal.get("role", "COACH"),
        mutation_kind="cross_addiction_profile_set",
        additional_fields_redacted={"keys": list(body.cross_addiction_profile.keys())},
    )
    return {"ok": True, "cross_addiction_profile": body.cross_addiction_profile}


# ------- COACH: codewords -----------------------------------------------------


@coach_router.post("/{user_id}/codeword")
async def add_codeword(
    user_id: str,
    body: CodewordCreate,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    """Add or rotate a safety codeword.

    The plaintext arrives in the request body, is hashed with a
    freshly-generated per-codeword salt, and is dropped from the request-
    scope locals before we return. We never store, log, or echo the
    plaintext.
    """
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})

    normalized = _normalize_codeword(body.plaintext_codeword)
    if not normalized:
        raise HTTPException(
            422,
            detail={"reason": "codeword_normalizes_to_empty"},
        )

    salt = secrets.token_hex(16)
    cw_hash = _hash_codeword(body.plaintext_codeword, salt)
    actor_id = principal.get("username", "") or principal.get("user_id", "")

    async with db_pool.acquire() as conn:
        # If the same hash exists for this user, surface 409 rather than
        # silently no-op. Rotation should pick a new plaintext.
        existing = await conn.fetchrow(
            """
            SELECT codeword_hash FROM user_safety_codewords
             WHERE user_id = $1 AND codeword_hash = $2
            """,
            user_id,
            cw_hash,
        )
        if existing is not None:
            raise HTTPException(
                409,
                detail={"reason": "duplicate_codeword_hash"},
            )

        await conn.execute(
            """
            INSERT INTO user_safety_codewords (
                user_id, codeword_hash, codeword_salt, codeword_type,
                codeword_label, triggers_mandatory_reporting,
                set_by_clinician_id, active, disclosure_type, part_name,
                part_number, part_category, addiction_link
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, TRUE, $8, $9, $10, $11, $12)
            """,
            user_id,
            cw_hash,
            salt,
            body.codeword_type,
            body.codeword_label,
            body.triggers_mandatory_reporting,
            actor_id,
            body.disclosure_type or body.codeword_type,
            body.part_name,
            body.part_number,
            body.part_category,
            body.addiction_link,
        )

    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=actor_id,
        actor_role=principal.get("role", "COACH"),
        mutation_kind="codeword_added",
        additional_fields_redacted={
            "hash_prefix": cw_hash[:12],
            "codeword_type": body.codeword_type,
            "triggers_mandatory_reporting": body.triggers_mandatory_reporting,
            "disclosure_type": body.disclosure_type or body.codeword_type,
            "part_name": body.part_name,
            "part_number": body.part_number,
            "part_category": body.part_category,
            "addiction_link": body.addiction_link,
        },
        access_classification=ACCESS_CLINICIAN_ONLY,
    )

    # Drop plaintext from the local before returning. Python doesn't really
    # let us scrub memory, but at minimum we rebind so the GC can sweep.
    body.plaintext_codeword = ""  # type: ignore[assignment]

    return {
        "ok": True,
        "hash_prefix": cw_hash[:12],
        "codeword_type": body.codeword_type,
        "part_linked": bool(
            body.part_name or body.part_number or body.part_category or body.addiction_link
        ),
    }


@coach_router.delete("/{user_id}/codeword/{hash_prefix}")
async def revoke_codeword(
    user_id: str,
    hash_prefix: str,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    """Soft-revoke a codeword by setting ``active=FALSE``. The hash prefix
    must be at least 8 chars to avoid prefix collisions; if more than one
    row matches we refuse with 409 ``ambiguous_prefix``.
    """
    if len(hash_prefix) < 8 or not re.fullmatch(r"[0-9a-f]+", hash_prefix):
        raise HTTPException(422, detail={"reason": "invalid_hash_prefix"})

    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})

    async with db_pool.acquire() as conn:
        matches = await conn.fetch(
            """
            SELECT codeword_hash FROM user_safety_codewords
             WHERE user_id = $1
               AND active = TRUE
               AND codeword_hash LIKE $2
            """,
            user_id,
            hash_prefix + "%",
        )
        if not matches:
            raise HTTPException(404, detail={"reason": "codeword_not_found"})
        if len(matches) > 1:
            raise HTTPException(409, detail={"reason": "ambiguous_prefix"})

        full_hash = matches[0]["codeword_hash"]
        await conn.execute(
            """
            UPDATE user_safety_codewords
               SET active = FALSE
             WHERE user_id = $1 AND codeword_hash = $2
            """,
            user_id,
            full_hash,
        )

    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=principal.get("username", ""),
        actor_role=principal.get("role", "COACH"),
        mutation_kind="codeword_revoked",
        additional_fields_redacted={"hash_prefix": full_hash[:12]},
        access_classification=ACCESS_CLINICIAN_ONLY,
    )
    return {"ok": True, "hash_prefix": full_hash[:12]}


# ------- COACH: trigger dates -------------------------------------------------


@coach_router.post("/{user_id}/trigger-date")
async def add_trigger_date(
    user_id: str,
    body: TriggerDateCreate,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    _raise_if_pii("notes_redacted", body.notes_redacted)

    actor_id = principal.get("username", "") or principal.get("user_id", "")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO user_trigger_dates (
                user_id, trigger_date, date_type, severity,
                recurring_annually, notes_redacted,
                set_by_clinician_id, active
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, TRUE)
            RETURNING id
            """,
            user_id,
            body.trigger_date,
            body.date_type,
            body.severity,
            body.recurring_annually,
            body.notes_redacted,
            actor_id,
        )
    new_id = int(row["id"])
    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=actor_id,
        actor_role=principal.get("role", "COACH"),
        mutation_kind="trigger_date_added",
        additional_fields_redacted={
            "id": new_id,
            "date_type": body.date_type,
            "severity": body.severity,
            "recurring_annually": body.recurring_annually,
        },
    )
    return {"ok": True, "id": new_id}


@coach_router.delete("/{user_id}/trigger-date/{trigger_date_id}")
async def deactivate_trigger_date(
    user_id: str,
    trigger_date_id: int,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    async with db_pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE user_trigger_dates
               SET active = FALSE
             WHERE id = $1 AND user_id = $2 AND active = TRUE
            """,
            trigger_date_id,
            user_id,
        )
    changed = 0
    try:
        changed = int(result.split()[-1])
    except (ValueError, IndexError):
        changed = 0
    if not changed:
        raise HTTPException(404, detail={"reason": "trigger_date_not_found"})
    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=principal.get("username", ""),
        actor_role=principal.get("role", "COACH"),
        mutation_kind="trigger_date_deactivated",
        additional_fields_redacted={"id": trigger_date_id},
    )
    return {"ok": True, "id": trigger_date_id}


# ------- COACH: polyvictim layers --------------------------------------------


@coach_router.post("/{user_id}/polyvictim-layer")
async def add_polyvictim_layer(
    user_id: str,
    body: PolyvictimLayerCreate,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    _raise_if_pii("notes_redacted", body.notes_redacted)

    actor_id = principal.get("username", "") or principal.get("user_id", "")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO user_polyvictimization_layers (
                user_id, layer_type, severity, active,
                set_by_clinician_id, notes_redacted
            ) VALUES ($1, $2, $3, TRUE, $4, $5)
            RETURNING id
            """,
            user_id,
            body.layer_type,
            body.severity,
            actor_id,
            body.notes_redacted,
        )
    new_id = int(row["id"])
    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=actor_id,
        actor_role=principal.get("role", "COACH"),
        mutation_kind="polyvictim_layer_added",
        additional_fields_redacted={
            "id": new_id,
            "layer_type": body.layer_type,
            "severity": body.severity,
        },
    )
    return {"ok": True, "id": new_id}


@coach_router.post("/{user_id}/polyvictim-layer/{layer_id}/activate")
async def activate_polyvictim_layer(
    user_id: str,
    layer_id: int,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    """Approve a pending (inactive) polyvictim layer suggestion — used to
    confirm rows inserted by the system auto-detector
    (`sensitive_clinical_bridge._suggest_polyvictim_layer`) after a coach
    reviews the disclosure. Re-stamps `set_by_clinician_id` with the
    approving clinician so the audit trail reflects human confirmation,
    not the system sentinel value.
    """
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    actor_id = principal.get("username", "") or principal.get("user_id", "")
    async with db_pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE user_polyvictimization_layers
               SET active = TRUE, set_by_clinician_id = $3
             WHERE id = $1 AND user_id = $2 AND active = FALSE
            """,
            layer_id,
            user_id,
            actor_id,
        )
    changed = 0
    try:
        changed = int(result.split()[-1])
    except (ValueError, IndexError):
        changed = 0
    if not changed:
        raise HTTPException(404, detail={"reason": "polyvictim_layer_not_found"})
    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=actor_id,
        actor_role=principal.get("role", "COACH"),
        mutation_kind="polyvictim_layer_activated",
        additional_fields_redacted={"id": layer_id},
    )
    return {"ok": True, "id": layer_id}


@coach_router.delete("/{user_id}/polyvictim-layer/{layer_id}")
async def deactivate_polyvictim_layer(
    user_id: str,
    layer_id: int,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    async with db_pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE user_polyvictimization_layers
               SET active = FALSE
             WHERE id = $1 AND user_id = $2 AND active = TRUE
            """,
            layer_id,
            user_id,
        )
    changed = 0
    try:
        changed = int(result.split()[-1])
    except (ValueError, IndexError):
        changed = 0
    if not changed:
        raise HTTPException(404, detail={"reason": "polyvictim_layer_not_found"})
    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=principal.get("username", ""),
        actor_role=principal.get("role", "COACH"),
        mutation_kind="polyvictim_layer_deactivated",
        additional_fields_redacted={"id": layer_id},
    )
    return {"ok": True, "id": layer_id}


@coach_router.delete("/{user_id}/polyvictim-layer/{layer_id}/dismiss-suggestion")
async def dismiss_polyvictim_layer_suggestion(
    user_id: str,
    layer_id: int,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    """Hard-delete a pending system-suggested row the clinician determined
    is not clinically applicable. Scoped to rows that are still `active=FALSE`
    AND still carry the system sentinel `set_by_clinician_id` — this can
    never remove a clinician-entered or clinician-activated layer, only an
    un-reviewed suggestion.
    """
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    async with db_pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM user_polyvictimization_layers
             WHERE id = $1 AND user_id = $2 AND active = FALSE
               AND set_by_clinician_id = 'system_auto_suggested_pending_review'
            """,
            layer_id,
            user_id,
        )
    changed = 0
    try:
        changed = int(result.split()[-1])
    except (ValueError, IndexError):
        changed = 0
    if not changed:
        raise HTTPException(404, detail={"reason": "polyvictim_layer_suggestion_not_found"})
    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=principal.get("username", ""),
        actor_role=principal.get("role", "COACH"),
        mutation_kind="polyvictim_layer_suggestion_dismissed",
        additional_fields_redacted={"id": layer_id},
    )
    return {"ok": True, "id": layer_id}


# ------- COACH: legal status --------------------------------------------------


@coach_router.post("/{user_id}/legal-status")
async def add_legal_status(
    user_id: str,
    body: LegalStatusCreate,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    _raise_if_pii("attorney_contact_redacted", body.attorney_contact_redacted)

    actor_id = principal.get("username", "") or principal.get("user_id", "")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO user_legal_status (
                user_id, case_type, case_status, next_event_date,
                attorney_contact_redacted, set_by_case_manager_id, active
            ) VALUES ($1, $2, $3, $4, $5, $6, TRUE)
            RETURNING id
            """,
            user_id,
            body.case_type,
            body.case_status,
            body.next_event_date,
            body.attorney_contact_redacted,
            actor_id,
        )
    new_id = int(row["id"])
    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=actor_id,
        actor_role=principal.get("role", "COACH"),
        mutation_kind="legal_status_added",
        additional_fields_redacted={
            "id": new_id,
            "case_type": body.case_type,
            "case_status": body.case_status,
            "next_event_date": (
                body.next_event_date.isoformat() if body.next_event_date else None
            ),
        },
    )
    return {"ok": True, "id": new_id}


@coach_router.patch("/{user_id}/legal-status/{legal_id}")
async def patch_legal_status(
    user_id: str,
    legal_id: int,
    body: LegalStatusPatch,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    _raise_if_pii("attorney_contact_redacted", body.attorney_contact_redacted)

    sets: List[str] = []
    args: List[Any] = []
    if body.case_status is not None:
        args.append(body.case_status)
        sets.append(f"case_status = ${len(args)}")
    if body.next_event_date is not None:
        args.append(body.next_event_date)
        sets.append(f"next_event_date = ${len(args)}")
    if body.attorney_contact_redacted is not None:
        args.append(body.attorney_contact_redacted)
        sets.append(f"attorney_contact_redacted = ${len(args)}")
    if not sets:
        raise HTTPException(422, detail={"reason": "no_fields_to_patch"})

    args.append(legal_id)
    args.append(user_id)
    sql = (
        "UPDATE user_legal_status SET "
        + ", ".join(sets)
        + f", set_at = NOW() WHERE id = ${len(args) - 1} AND user_id = ${len(args)} AND active = TRUE"
    )
    async with db_pool.acquire() as conn:
        result = await conn.execute(sql, *args)
    changed = 0
    try:
        changed = int(result.split()[-1])
    except (ValueError, IndexError):
        changed = 0
    if not changed:
        raise HTTPException(404, detail={"reason": "legal_status_not_found"})
    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=principal.get("username", ""),
        actor_role=principal.get("role", "COACH"),
        mutation_kind="legal_status_patched",
        additional_fields_redacted={
            "id": legal_id,
            "fields_patched": [s.split(" =")[0] for s in sets],
        },
    )
    return {"ok": True, "id": legal_id}


# ------- COACH: parts registry ------------------------------------------------


class PartRegistryCreate(BaseModel):
    part_name: str = Field(..., min_length=1, max_length=64)
    part_number: Optional[int] = Field(default=None, ge=1, le=999)
    part_category: str = Field(..., min_length=1, max_length=32)
    addiction_link: Optional[str] = Field(default=None, max_length=32)
    description: Optional[str] = Field(default=None, max_length=1000)
    protected_exile_part_id: Optional[int] = Field(default=None)

    @validator("part_category")
    def _v_category(cls, v):
        allowed = {
            "protector", "exile", "firefighter", "manager",
            "self_energy", "addict_part", "inner_critic",
            "caretaker", "dissociative_part", "other",
        }
        if v not in allowed:
            raise ValueError(
                "part_category must be one of " + "|".join(sorted(allowed))
            )
        return v


class PartRegistryPatch(BaseModel):
    part_name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    part_number: Optional[int] = Field(default=None, ge=1, le=999)
    part_category: Optional[str] = Field(default=None, min_length=1, max_length=32)
    ifs_role: Optional[str] = Field(default=None, max_length=20)
    ilm_archetype_base: Optional[str] = Field(default=None, max_length=32)
    addiction_link: Optional[str] = Field(default=None, max_length=32)
    description: Optional[str] = Field(default=None, max_length=1000)
    protected_exile_part_id: Optional[int] = Field(default=None)
    coaching_status: Optional[str] = Field(default=None, max_length=24)
    coaching_status_notes: Optional[str] = Field(default=None, max_length=1000)

    @validator("part_category")
    def _v_category(cls, v):
        if v is None:
            return v
        return PartRegistryCreate._v_category(v)

    @validator("coaching_status")
    def _v_coaching_status(cls, v):
        if v is None:
            return v
        allowed = {"APPROVED", "PENDING_APPROVAL", "HOLD", "REJECTED"}
        if v not in allowed:
            raise ValueError("coaching_status must be one of " + "|".join(sorted(allowed)))
        return v


@coach_router.post("/{user_id}/parts-registry")
async def add_part(
    user_id: str,
    body: PartRegistryCreate,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    _raise_if_pii("description", body.description)

    actor_id = principal.get("username", "") or principal.get("user_id", "")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO user_parts_registry (
                user_id, part_name, part_number, part_category,
                addiction_link, description, protected_exile_part_id,
                is_active, created_by
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, TRUE, $8)
            ON CONFLICT (user_id, part_name) DO UPDATE
               SET is_active = TRUE,
                   part_number = EXCLUDED.part_number,
                   part_category = EXCLUDED.part_category,
                   addiction_link = EXCLUDED.addiction_link,
                   description = EXCLUDED.description,
                   protected_exile_part_id = EXCLUDED.protected_exile_part_id,
                   retired_at = NULL
            RETURNING id
            """,
            user_id,
            body.part_name,
            body.part_number,
            body.part_category,
            body.addiction_link,
            body.description,
            body.protected_exile_part_id,
            actor_id,
        )
    new_id = int(row["id"])
    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=actor_id,
        actor_role=principal.get("role", "COACH"),
        mutation_kind="part_registered",
        additional_fields_redacted={
            "id": new_id,
            "part_name": body.part_name,
            "part_category": body.part_category,
            "addiction_link": body.addiction_link,
        },
    )
    return {"ok": True, "id": new_id, "part_name": body.part_name}


@coach_router.get("/{user_id}/parts-registry")
async def list_parts(
    user_id: str,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
    active_only: bool = True,
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    condition = " AND is_active = TRUE" if active_only else ""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, part_name, part_number, part_category,
                   addiction_link, description,
                   protected_exile_part_id, is_active,
                   ilm_archetype_base, ifs_role, thera_world_template_id,
                   activation_score, coaching_status, coaching_status_notes, origin,
                   created_at, created_by, retired_at
              FROM user_parts_registry
             WHERE user_id = $1{condition}
             ORDER BY part_number ASC NULLS LAST, part_name ASC
            """,
            user_id,
        )
    return {
        "ok": True,
        "parts": [dict(r) for r in rows],
    }


@coach_router.patch("/{user_id}/parts-registry/{part_id}")
async def update_part(
    user_id: str,
    part_id: int,
    body: PartRegistryPatch,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    _raise_if_pii("description", body.description)
    _raise_if_pii("coaching_status_notes", body.coaching_status_notes)

    updates = body.dict(exclude_unset=True)
    if not updates:
        raise HTTPException(422, detail={"reason": "no_fields_to_update"})

    allowed = {
        "part_name", "part_number", "part_category", "ifs_role", "ilm_archetype_base",
        "addiction_link", "description", "protected_exile_part_id",
        "coaching_status", "coaching_status_notes",
    }
    sets = []
    values: List[Any] = [part_id, user_id]
    for key, value in updates.items():
        if key not in allowed:
            continue
        values.append(value)
        sets.append(f"{key} = ${len(values)}")
    if not sets:
        raise HTTPException(422, detail={"reason": "no_valid_fields_to_update"})

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE user_parts_registry
               SET {", ".join(sets)}
             WHERE id = $1 AND user_id = $2 AND is_active = TRUE
             RETURNING id
            """,
            *values,
        )
    if row is None:
        raise HTTPException(404, detail={"reason": "part_not_found"})

    if body.coaching_status == "REJECTED":
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE user_parts_registry
                   SET is_active = FALSE, retired_at = NOW()
                 WHERE id = $1 AND user_id = $2
                """,
                part_id,
                user_id,
            )

    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=principal.get("username", ""),
        actor_role=principal.get("role", "COACH"),
        mutation_kind="part_updated",
        additional_fields_redacted={
            "id": part_id,
            "fields_patched": sorted(updates.keys()),
        },
    )
    return {"ok": True, "id": part_id}


@coach_router.delete("/{user_id}/parts-registry/{part_id}")
async def retire_part(
    user_id: str,
    part_id: int,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    async with db_pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE user_parts_registry
               SET is_active = FALSE, retired_at = NOW()
             WHERE id = $1 AND user_id = $2 AND is_active = TRUE
            """,
            part_id,
            user_id,
        )
    changed = 0
    try:
        changed = int(result.split()[-1])
    except (ValueError, IndexError):
        changed = 0
    if not changed:
        raise HTTPException(404, detail={"reason": "part_not_found_or_already_retired"})
    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=principal.get("username", ""),
        actor_role=principal.get("role", "COACH"),
        mutation_kind="part_retired",
        additional_fields_redacted={"id": part_id},
    )
    return {"ok": True, "id": part_id}


# ------- COACH: framework menu -----------------------------------------------


@coach_router.get("/{user_id}/framework-menu")
async def get_framework_menu(
    user_id: str,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    """Return the canonical framework list with per-client enabled/disabled state."""
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})

    from app.services.sensitive_clinical_bridge import _load_framework_menu

    canonical = _load_framework_menu().get("definitions", {})

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT profile_data->'sensitive_bridge'->'framework_preferences' AS prefs
              FROM users WHERE username = $1
            """,
            user_id,
        )
    stored_prefs: Dict[str, Any] = {}
    if row and row["prefs"]:
        import json as _json
        raw = row["prefs"]
        if isinstance(raw, str):
            try:
                stored_prefs = _json.loads(raw)
            except Exception:
                stored_prefs = {}
        elif isinstance(raw, dict):
            stored_prefs = raw

    menu = []
    for key, meta in canonical.items():
        menu.append({
            "key": key,
            "label": meta["label"],
            "applies_to": sorted(meta.get("applies_to", set())),
            "enabled": stored_prefs.get(key, True),
        })
    return {
        "ok": True,
        "menu": menu,
        "default_lens": stored_prefs.get("default_lens_for_today"),
        "crystal_knowledge_graph_opt_in": stored_prefs.get(
            "crystal_knowledge_graph_opt_in", False
        ),
    }


class FrameworkPreferencesUpdate(BaseModel):
    enabled_frameworks: Optional[Dict[str, bool]] = Field(
        default=None,
        description="Map of framework_key → enabled boolean.",
    )
    default_lens_for_today: Optional[str] = Field(
        default=None, max_length=64,
        description="Override: force this lens for all turns today.",
    )
    crystal_knowledge_graph_opt_in: Optional[bool] = Field(
        default=None,
        description="Opt-in to Crystal Knowledge Graph augmentation (default OFF).",
    )


@coach_router.put("/{user_id}/framework-menu")
async def update_framework_preferences(
    user_id: str,
    body: FrameworkPreferencesUpdate,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})

    from app.services.sensitive_clinical_bridge import _load_framework_menu

    canonical_keys = set(_load_framework_menu().get("definitions", {}).keys())

    prefs: Dict[str, Any] = {}
    if body.enabled_frameworks:
        for k, v in body.enabled_frameworks.items():
            if k not in canonical_keys:
                raise HTTPException(
                    422,
                    detail={"reason": f"unknown_framework_key: {k}"},
                )
            prefs[k] = bool(v)
    if body.default_lens_for_today is not None:
        if body.default_lens_for_today and body.default_lens_for_today not in canonical_keys:
            raise HTTPException(
                422,
                detail={"reason": f"unknown_framework_key: {body.default_lens_for_today}"},
            )
        prefs["default_lens_for_today"] = body.default_lens_for_today or None
    if body.crystal_knowledge_graph_opt_in is not None:
        prefs["crystal_knowledge_graph_opt_in"] = body.crystal_knowledge_graph_opt_in

    if not prefs:
        raise HTTPException(422, detail={"reason": "no_fields_to_update"})

    import json as _json

    actor_id = principal.get("username", "") or principal.get("user_id", "")
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE users
               SET profile_data = jsonb_set(
                   COALESCE(profile_data, '{}'::jsonb),
                   '{sensitive_bridge,framework_preferences}',
                   COALESCE(
                       profile_data->'sensitive_bridge'->'framework_preferences', '{}'::jsonb
                   ) || $2::jsonb,
                   true
               )
             WHERE username = $1
            """,
            user_id,
            _json.dumps(prefs),
        )
    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=actor_id,
        actor_role=principal.get("role", "COACH"),
        mutation_kind="framework_preferences_updated",
        additional_fields_redacted={
            "keys_updated": list(prefs.keys()),
        },
    )
    return {"ok": True, "updated_keys": list(prefs.keys())}


# ------- COACH: safe_silence_mode propose / cancel ---------------------------


@coach_router.post("/{user_id}/safe-silence/propose")
async def safe_silence_propose(
    user_id: str,
    body: SafeSilencePropose,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    """Step 1 of the two-step gate. Records the proposer's session token
    hash on the JSONB state. The admin's ``/approve`` endpoint compares
    against this on flip and refuses if it matches the approver's token
    hash (Risk #19).
    """
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    _raise_if_pii("reason_redacted", body.reason_redacted)

    proposer_token_hash = principal.get("_token_session_hash") or ""
    actor_id = principal.get("username", "") or principal.get("user_id", "")
    now_iso = datetime.now(timezone.utc).isoformat()

    async with db_pool.acquire() as conn:
        urow = await conn.fetchrow(
            "SELECT profile_data FROM users WHERE username = $1",
            user_id,
        )
        if urow is None:
            raise HTTPException(404, detail={"reason": "user_not_found"})
        pd = urow["profile_data"] or {}
        if isinstance(pd, str):
            try:
                pd = json.loads(pd)
            except Exception:
                pd = {}
        sss = pd.get("safe_silence_mode_state") or {}
        cur_state = sss.get("state") or SAFE_SILENCE_INACTIVE
        if cur_state == SAFE_SILENCE_ACTIVE:
            raise HTTPException(409, detail={"reason": "already_active"})
        if cur_state == SAFE_SILENCE_PENDING:
            raise HTTPException(409, detail={"reason": "already_pending"})

        proposal_id = secrets.token_hex(8)
        new_state = {
            "state": SAFE_SILENCE_PENDING,
            "proposer_id": actor_id,
            "proposer_token_hash": proposer_token_hash,
            "proposed_at": now_iso,
            "approver_id": None,
            "approved_at": None,
            "expires_at": None,
            "expiry_warning_sent_at": None,
            "auto_revert_eligible_at": None,
            "codeword_precondition_met": False,
            "reason_redacted": body.reason_redacted,
            "proposal_id": proposal_id,
        }
        await conn.execute(
            """
            UPDATE users
               SET profile_data = jsonb_set(
                       COALESCE(profile_data, '{}'::jsonb),
                       '{safe_silence_mode_state}',
                       $2::jsonb,
                       true
                   ),
                   updated_at = NOW()
             WHERE username = $1
            """,
            user_id,
            json.dumps(new_state),
        )

    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=actor_id,
        actor_role=principal.get("role", "COACH"),
        mutation_kind="safe_silence_proposed",
        additional_fields_redacted={
            "proposal_id": proposal_id,
            "reason_present": bool(body.reason_redacted),
        },
        severity="moderate",
        event_type=EVT_SAFE_SILENCE_STATE_CHANGE,
    )
    return {
        "ok": True,
        "state": SAFE_SILENCE_PENDING,
        "proposal_id": proposal_id,
        "proposed_at": now_iso,
    }


@coach_router.delete("/{user_id}/safe-silence")
async def safe_silence_cancel(
    user_id: str,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    """Cancel a pending proposal (any assigned clinician) or revoke an active
    silence mode (ADMIN only; sole_lead requires revoke session ≠ propose and
    ≠ approve token sessions via persisted gate hashes — Priority 2a).

    Welcome-back follow-up is dispatched by ``nate_checkin_agent`` Pass C
    (fail-closed template), not inline here.
    """
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})

    actor_id = principal.get("username", "") or principal.get("user_id", "")
    role = (principal.get("role") or "COACH").upper()
    revoker_hash = principal.get("_token_session_hash") or ""

    async with db_pool.acquire() as conn:
        urow = await conn.fetchrow(
            "SELECT profile_data FROM users WHERE username = $1",
            user_id,
        )
        if urow is None:
            raise HTTPException(404, detail={"reason": "user_not_found"})
        pd = urow["profile_data"] or {}
        if isinstance(pd, str):
            try:
                pd = json.loads(pd)
            except Exception:
                pd = {}
        sss = pd.get("safe_silence_mode_state") or {}
        cur_state = sss.get("state") or SAFE_SILENCE_INACTIVE

        if cur_state == SAFE_SILENCE_PENDING:
            new_state = {
                "state": SAFE_SILENCE_INACTIVE,
                "proposer_id": None,
                "approver_id": None,
                "proposed_at": None,
                "approved_at": None,
                "expires_at": None,
                "expiry_warning_sent_at": None,
                "auto_revert_eligible_at": None,
                "codeword_precondition_met": False,
                "reason_redacted": None,
                "proposal_id": None,
                "approver_note_redacted": None,
                "proposer_token_hash": None,
                "gate_proposer_token_hash": None,
                "gate_approver_token_hash": None,
            }
            await conn.execute(
                """
                UPDATE users
                   SET profile_data = jsonb_set(
                           COALESCE(profile_data, '{}'::jsonb),
                           '{safe_silence_mode_state}',
                           $2::jsonb,
                           true
                       ),
                       updated_at = NOW()
                 WHERE username = $1
                """,
                user_id,
                json.dumps(new_state),
            )

            await _emit_profile_mutation_audit(
                db_pool,
                target_user_id=user_id,
                actor_id=actor_id,
                actor_role=principal.get("role", "COACH"),
                mutation_kind="safe_silence_cancelled",
                additional_fields_redacted={},
                severity="moderate",
                event_type=EVT_SAFE_SILENCE_STATE_CHANGE,
            )
            return {"ok": True, "state": SAFE_SILENCE_INACTIVE}

        if cur_state == SAFE_SILENCE_ACTIVE:
            if role != "ADMIN":
                raise HTTPException(
                    403,
                    detail={"reason": "admin_required_for_active_revocation"},
                )

            revoker_auth = await _lookup_clinician_authorization_type(
                conn, actor_id,
            )
            gate_p = (sss.get("gate_proposer_token_hash") or "").strip()
            gate_a = (sss.get("gate_approver_token_hash") or "").strip()
            if revoker_auth == CLIN_AUTH_SOLE_LEAD:
                if gate_p or gate_a:
                    if revoker_hash and (
                        (gate_p and hmac.compare_digest(revoker_hash, gate_p))
                        or (
                            gate_a
                            and hmac.compare_digest(revoker_hash, gate_a)
                        )
                    ):
                        raise HTTPException(
                            409,
                            detail={
                                "reason": "same_session_violation",
                                "message": (
                                    "Revoke must occur in a session "
                                    "different from propose or approve"
                                ),
                            },
                        )
                else:
                    logger.warning(
                        "sensitive_profile_api: sole_lead active revoke for "
                        "%s without gate hashes — session separation skipped "
                        "(legacy row)",
                        user_id,
                    )

            prior_proposer = (sss.get("proposer_id") or "").strip()
            prior_proposer_auth = await _lookup_clinician_authorization_type(
                conn, prior_proposer,
            )
            sole_flag = prior_proposer_auth == CLIN_AUTH_SOLE_LEAD

            revoked_at = datetime.now(timezone.utc).isoformat()
            new_state = {
                "state": SAFE_SILENCE_INACTIVE,
                "revoked_at": revoked_at,
                "revoked_by": actor_id,
                "revoke_reason": "manual_admin_revocation",
                "prior_proposer_id": sss.get("proposer_id"),
                "prior_approver_id": sss.get("approver_id"),
                "proposer_id": None,
                "approver_id": None,
                "proposed_at": None,
                "approved_at": None,
                "expires_at": None,
                "expiry_warning_sent_at": None,
                "auto_revert_eligible_at": None,
                "codeword_precondition_met": False,
                "reason_redacted": None,
                "proposal_id": None,
                "approver_note_redacted": None,
                "proposer_token_hash": None,
                "gate_proposer_token_hash": None,
                "gate_approver_token_hash": None,
            }
            await conn.execute(
                """
                UPDATE users
                   SET profile_data = jsonb_set(
                           COALESCE(profile_data, '{}'::jsonb),
                           '{safe_silence_mode_state}',
                           $2::jsonb,
                           true
                       ),
                       updated_at = NOW()
                 WHERE username = $1
                """,
                user_id,
                json.dumps(new_state),
            )

            await _emit_profile_mutation_audit(
                db_pool,
                target_user_id=user_id,
                actor_id=actor_id,
                actor_role="ADMIN",
                mutation_kind="safe_silence_active_revoked",
                additional_fields_redacted={
                    "transition": "active_to_inactive",
                    "revoke_trigger": "manual_admin_revocation",
                    "sole_clinician_override": sole_flag,
                    "revoker_authorization_type": revoker_auth,
                },
                severity="high",
                event_type=EVT_SAFE_SILENCE_STATE_CHANGE,
            )
            return {
                "ok": True,
                "state": SAFE_SILENCE_INACTIVE,
                "revoked_at": revoked_at,
                "revoked_by": actor_id,
            }

        raise HTTPException(
            409,
            detail={"reason": "no_active_or_pending_state"},
        )


# ------- COACH: activity log read --------------------------------------------


@coach_router.get("/{user_id}/log")
async def get_activity_log(
    user_id: str,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
    days: int = ACTIVITY_LOG_DEFAULT_DAYS,
    limit: int = 100,
    before_id: Optional[int] = None,
):
    """Read-only window over ``sensitive_bridge_log`` for one user.

    Caps the window at ``ACTIVITY_LOG_MAX_DAYS`` and ``ACTIVITY_LOG_MAX_ROWS``
    to keep payloads bounded for the Flutter screen. Per Note 3 the default
    window is 7 days; the screen exposes "show more" to bump up to a year.

    Plan Gap C / Phase 4b Note 2 — server-side ``access_classification``
    filter is enforced HERE, not at the client. A COACH principal NEVER
    receives ``admin_only_redacted`` rows regardless of window size; an
    ADMIN principal sees ``clinician_and_admin`` + ``admin_only_redacted``
    and the latter has its ``payload_json`` blanked to ``{}`` so admins
    see the row exists without reading clinician-only payload content.
    A bug or compromise in the Flutter renderer cannot exfiltrate data
    that never left PostgreSQL.

    Pagination: pass ``before_id`` (the lowest ``id`` from the previous
    fetch) to load older rows in the same window. The route returns at
    most ``limit`` rows per call (caller-enforced cap; the screen uses
    200 per Note 2(b)).
    """
    if days < 1 or days > ACTIVITY_LOG_MAX_DAYS:
        raise HTTPException(422, detail={"reason": "invalid_days_range"})
    if limit < 1 or limit > ACTIVITY_LOG_MAX_ROWS:
        raise HTTPException(422, detail={"reason": "invalid_limit_range"})

    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})

    # Server-side RBAC: classifications visible to this principal.
    role = (principal.get("role") or "").upper()
    if role == "ADMIN":
        allowed_classes = (
            ACCESS_CLINICIAN_AND_ADMIN,
            ACCESS_ADMIN_ONLY_REDACTED,
        )
    else:  # COACH (and is_audit / any other clinician-side caller)
        allowed_classes = (
            ACCESS_CLINICIAN_ONLY,
            ACCESS_CLINICIAN_AND_ADMIN,
        )

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with db_pool.acquire() as conn:
        if before_id is None:
            rows = await conn.fetch(
                """
                SELECT id, event_type, event_severity, payload_json,
                       decision_summary, occurred_at, recorded_by,
                       access_classification
                  FROM sensitive_bridge_log
                 WHERE user_id = $1
                   AND occurred_at >= $2
                   AND access_classification = ANY($3::text[])
                 ORDER BY occurred_at DESC, id DESC
                 LIMIT $4
                """,
                user_id,
                cutoff,
                list(allowed_classes),
                limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, event_type, event_severity, payload_json,
                       decision_summary, occurred_at, recorded_by,
                       access_classification
                  FROM sensitive_bridge_log
                 WHERE user_id = $1
                   AND occurred_at >= $2
                   AND access_classification = ANY($3::text[])
                   AND id < $4
                 ORDER BY occurred_at DESC, id DESC
                 LIMIT $5
                """,
                user_id,
                cutoff,
                list(allowed_classes),
                before_id,
                limit,
            )

    out_rows = []
    for r in rows:
        cls = r["access_classification"]
        # Defense-in-depth: even though the WHERE clause already excluded
        # admin_only_redacted for COACH principals, blank the payload at
        # serialization time too. Two independent layers; bug in one
        # cannot leak through the other.
        if cls == ACCESS_ADMIN_ONLY_REDACTED:
            payload_out: Any = {}
        else:
            payload_out = r["payload_json"]
        out_rows.append(
            {
                "id": r["id"],
                "event_type": r["event_type"],
                "event_severity": r["event_severity"],
                "payload_json": payload_out,
                "decision_summary": r["decision_summary"],
                "occurred_at": (
                    r["occurred_at"].isoformat() if r["occurred_at"] else None
                ),
                "recorded_by": r["recorded_by"],
                "access_classification": cls,
            }
        )

    return {
        "user_id": user_id,
        "days": days,
        "limit": limit,
        "before_id": before_id,
        "next_before_id": out_rows[-1]["id"] if out_rows else None,
        "rows": out_rows,
    }


# ------- COACH: Path-C self-enrollment (M215+M216) ---------------------------


@coach_router.post("/{user_id}/enroll")
async def coach_initiated_enroll(
    user_id: str,
    body: CoachInitiatedEnrollment,
    request: Request,
    principal: Dict = Depends(require_clinician_for_user),
):
    """Path C — coach-initiated self-enrollment surface.

    Authorization layering (defense in depth — all four must hold):

      1. ``require_clinician_for_user`` already verified COACH/ADMIN role
         AND that this coach is on the client's clinician chain.
      2. ``coach_sensitive_bridge_authorized = TRUE`` on
         ``coach_profiles``. If FALSE, return **404 not_found**, NOT 403.
         The 404 deliberately mimics a missing endpoint so an unauthorized
         coach cannot infer that Path C exists. (The Flutter dialog only
         renders the "Enroll this client" button when the GET response
         has ``coach_sensitive_bridge_authorized=true``, so the 404 is a
         tamper-only path.)
      3. ``informed_consent_confirmed = true`` in the body. Server refuses
         on False with 422 ``consent_required``.
      4. For minor_survivor / transitioning_youth_16_to_21:
         ``users.profile_data->>'guardian_dual_approval_on_file' = 'true'``.
         Otherwise 409 ``requires_guardian_consent`` — the existing
         guardian-consent flow runs separately under admin.

    Idempotency:

      • Refuses if a ``sensitive_bridge_enrollment`` row already exists
        for ``user_id`` (409 ``already_enrolled``). The Flutter dialog
        surfaces a Refresh modal on this code; the user re-loads the
        profile and proceeds.

    Side effects on success:

      a. INSERT row into ``sensitive_bridge_enrollment`` with
         ``cohort_label = body.cohort_label``,
         ``gap_features_enabled = FULL_ACTIVATION_GAP_FEATURES`` (all 16
         ``gap_*`` + 7 ``v1_4_*`` keys TRUE — enrollment activates full
         v1.3+v1.4 bridge surface per ``enrollment-equals-activation`` rule),
         ``enrolled_by = current_coach_username``,
         ``enrolled_at = NOW()``.

      b. UPDATE ``users.profile_data`` to set ``population_type``. Uses
         ``jsonb_set`` to preserve other keys (per
         ``bridge-cache-db-sovereignty.mdc``).

      c. EMIT ``enrollment_created`` audit event to
         ``sensitive_bridge_log`` with severity ``moderate``,
         classification ``clinician_and_admin``, payload
         ``{cohort_label, population_type, enrolled_by,
         informed_consent_timestamp}``. Payload runs through the
         standard ``_emit_profile_mutation_audit`` PII screen.

    Explicit non-actions:

      • Does NOT flip ``app_settings.sensitive_bridge_master_enabled``.
      • Does NOT set any clinical fields (embodiment_phase, thresholds,
        codewords). The coach configures those via the existing scalar
        setters after enrollment.
      • Does NOT modify any admin-side enrollment surface.
    """
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})

    coach_username = principal.get("username") or principal.get("user_id") or ""

    # ---- Gate 2: coach_sensitive_bridge_authorized -------------------------
    # Auditor probes can bypass this without leaking that the feature
    # exists. The require_clinician_for_user dep returned an is_audit
    # principal already if the bearer matched the audit token. We honor
    # that by treating it as authorized so the auditor can exercise the
    # full happy/failure paths.
    is_audit = bool(principal.get("is_audit"))
    role = (principal.get("role") or "").upper()
    coach_authorized = is_audit or role == "ADMIN"

    if not coach_authorized:
        try:
            async with db_pool.acquire() as conn:
                cp_row = await conn.fetchrow(
                    """
                    SELECT coach_sensitive_bridge_authorized
                      FROM coach_profiles
                     WHERE username = $1
                    """,
                    coach_username,
                )
            coach_authorized = bool(
                cp_row is not None
                and cp_row["coach_sensitive_bridge_authorized"]
            )
        except Exception as e:
            logger.warning(
                "sensitive_profile_api: coach auth lookup failed for %s: %s",
                coach_username, e,
            )
            coach_authorized = False

    if not coach_authorized:
        # Mimic missing route — do NOT 403. The auditor check
        # `enrollment_endpoint_requires_coach_authorization` asserts this
        # exact response shape.
        raise HTTPException(
            404,
            detail={"reason": "not_found"},
        )

    # ---- Gate 3: informed_consent_confirmed --------------------------------
    if not body.informed_consent_confirmed:
        raise HTTPException(
            422,
            detail={"reason": "consent_required"},
        )

    # ---- Gate 4: guardian consent for minors -------------------------------
    requires_guardian = body.population_type in POPULATION_TYPES_REQUIRING_GUARDIAN_CONSENT

    async with db_pool.acquire() as conn:
        urow = await conn.fetchrow(
            "SELECT profile_data FROM users WHERE username = $1",
            user_id,
        )
        if urow is None:
            # require_clinician_for_user already 404'd on missing user,
            # but defensive in case of a TOCTOU race.
            raise HTTPException(404, detail={"reason": "user_not_found"})
        pd = urow["profile_data"] or {}
        if isinstance(pd, str):
            try:
                pd = json.loads(pd)
            except Exception:
                pd = {}

        if requires_guardian:
            guardian_ok = pd.get("guardian_dual_approval_on_file")
            # Accept bool True or string "true" — profile_data is JSONB
            # but legacy paths sometimes write strings.
            if not (
                guardian_ok is True
                or (isinstance(guardian_ok, str) and guardian_ok.lower() == "true")
            ):
                raise HTTPException(
                    409,
                    detail={
                        "reason": "requires_guardian_consent",
                        "message": (
                            "Minor enrollment requires guardian consent flow. "
                            "Contact admin."
                        ),
                    },
                )

        # ---- Idempotency: 409 if already enrolled --------------------------
        existing = await conn.fetchrow(
            "SELECT cohort_label FROM sensitive_bridge_enrollment WHERE user_id = $1",
            user_id,
        )
        if existing is not None:
            raise HTTPException(
                409,
                detail={
                    "reason": "already_enrolled",
                    "cohort_label": existing["cohort_label"],
                },
            )

        # ---- Side effect (a): INSERT enrollment row ------------------------
        consent_ts = datetime.now(timezone.utc)
        await conn.execute(
            """
            INSERT INTO sensitive_bridge_enrollment (
                user_id, cohort_label, gap_features_enabled,
                enrolled_at, enrolled_by, last_modified_at, last_modified_by
            ) VALUES (
                $1, $2, $3::jsonb, NOW(), $4, NOW(), $4
            )
            """,
            user_id,
            body.cohort_label,
            json.dumps(FULL_ACTIVATION_GAP_FEATURES),
            coach_username,
        )

        # ---- Side effect (b): mirror population_type into profile_data -----
        # jsonb_set is required to preserve other keys (see
        # bridge-cache-db-sovereignty.mdc — the bridge will overwrite a
        # full-profile_data replacement on its next save cycle).
        await conn.execute(
            """
            UPDATE users
               SET profile_data = jsonb_set(
                   COALESCE(profile_data, '{}'::jsonb),
                   '{population_type}',
                   to_jsonb($2::text),
                   true
               )
             WHERE username = $1
            """,
            user_id,
            body.population_type,
        )
        # QUANTUM-CRYSTAL-ARCH: optional occupational population (crisis-line routing)
        _occ = (body.occupational_population or "").strip().lower()
        if _occ:
            from app.services.population_profile import VALID_POPULATIONS as _OCC_POPS
            if _occ in _OCC_POPS:
                _shield = _occ != "general"
                await conn.execute(
                    """
                    UPDATE users SET profile_data = jsonb_set(
                        jsonb_set(
                            COALESCE(profile_data, '{}'::jsonb),
                            '{population}',
                            to_jsonb($2::text),
                            true
                        ),
                        '{population_shielded}',
                        to_jsonb($3::boolean),
                        true
                    )
                    WHERE username = $1
                    """,
                    user_id,
                    _occ,
                    _shield,
                )

    # ---- Side effect (c): emit enrollment_created audit event --------------
    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=coach_username,
        actor_role=role or "COACH",
        mutation_kind="enrollment_created",
        additional_fields_redacted={
            "cohort_label": body.cohort_label,
            "population_type": body.population_type,
            "enrolled_by_hash": _hash_actor_id(coach_username),
            "informed_consent_timestamp": consent_ts.isoformat(),
        },
        severity="moderate",
        event_type=EVT_ENROLLMENT_CREATED,
        access_classification=ACCESS_CLINICIAN_AND_ADMIN,
    )

    # QUANTUM-CRYSTAL-ARCH: refresh bridge cache after profile_data population writes
    try:
        from app.services.api_server import _get_auth_redis
        _rr = await _get_auth_redis()
        if _rr:
            await _rr.publish("nate:user_reload", json.dumps({"username": user_id}))
    except Exception:
        pass

    # QUANTUM-CRYSTAL-ARCH — PGSD live_activation on enroll
    try:
        from app.services.pgsd_triggers import notify_user_async

        await notify_user_async(db_pool, user_id, source="live_activation")
    except Exception:
        pass

    return {
        "ok": True,
        "user_id": user_id,
        "cohort_label": body.cohort_label,
        "population_type": body.population_type,
        "occupational_population": (body.occupational_population or "").strip().lower() or None,
        "enrolled_by": coach_username,
        "enrolled_at": consent_ts.isoformat(),
        "informed_consent_timestamp": consent_ts.isoformat(),
    }


# ------- ADMIN: safe_silence_mode approve ------------------------------------


@admin_router.post("/{user_id}/safe-silence/approve")
async def safe_silence_approve(
    user_id: str,
    body: SafeSilenceApprove,
    request: Request,
    principal: Dict = Depends(require_admin_with_session_token),
):
    """Step 2 of the two-step gate (Note 2 — BLOCKING).

    Refuses to flip ``state='active'`` unless ALL preconditions hold:

      (a) ``proposer_token_hash != approver_token_hash``  → else 409
          ``same_session_violation`` (Risk #19).
      (b) At least one ``user_safety_codewords`` row with ``active=TRUE``
          for ``user_id``  → else 409 ``requires_codeword``. Checked
          BEFORE the state flip — never after; otherwise a race window
          exists where the user is silenced without a safety net.
      (c) Current state is ``pending_approval`` AND ``proposal_id`` matches
          the body  → else 409 ``stale_state``.

    Approval extends to ``approved_at + SAFE_SILENCE_APPROVAL_TTL_DAYS``.
    The 25-day warning + 30-day auto-revert scheduler lives in
    ``nate_checkin_agent`` (Phase 3); this endpoint only writes the
    timestamps.
    """
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    _raise_if_pii("approver_note_redacted", body.approver_note_redacted)

    approver_token_hash = principal.get("_token_session_hash") or ""
    approver_id = principal.get("username", "") or principal.get("user_id", "")
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=SAFE_SILENCE_APPROVAL_TTL_DAYS)

    async with db_pool.acquire() as conn:
        urow = await conn.fetchrow(
            "SELECT profile_data FROM users WHERE username = $1",
            user_id,
        )
        if urow is None:
            raise HTTPException(404, detail={"reason": "user_not_found"})
        pd = urow["profile_data"] or {}
        if isinstance(pd, str):
            try:
                pd = json.loads(pd)
            except Exception:
                pd = {}
        sss = pd.get("safe_silence_mode_state") or {}
        cur_state = sss.get("state") or SAFE_SILENCE_INACTIVE

        # Precondition (c): pending + matching proposal_id.
        if cur_state != SAFE_SILENCE_PENDING:
            raise HTTPException(
                409,
                detail={"reason": "stale_state", "current_state": cur_state},
            )
        stored_proposal_id = sss.get("proposal_id")
        if stored_proposal_id != body.proposal_id:
            raise HTTPException(
                409,
                detail={"reason": "proposal_id_mismatch"},
            )

        # Precondition (a): same-session violation (Risk #19). Compare
        # token hashes BEFORE the codeword check so a same-session attempt
        # never even sees whether codewords are configured. This rule applies
        # universally — sole_lead clinicians get NO relief here. The
        # session-separation enforcement is the load-bearing safeguard for
        # the sole-clinician exemption (audited as
        # ``sole_clinician_session_separation_enforced``).
        proposer_token_hash = sss.get("proposer_token_hash") or ""
        if (
            proposer_token_hash
            and approver_token_hash
            and hmac.compare_digest(proposer_token_hash, approver_token_hash)
        ):
            raise HTTPException(
                409,
                detail={"reason": "same_session_violation"},
            )

        # Precondition (a-bis): in the default (multi_clinician_team) mode,
        # also require a *different actor* — same-person, two-session
        # self-approval defeats the multi-clinician intent. Look up the
        # PROPOSER's authorization type, NOT the approver's: the exemption
        # is a property of the practice the proposal originated in, not of
        # the admin who happens to push the button.
        proposer_id = (sss.get("proposer_id") or "").strip()
        proposer_auth_type = await _lookup_clinician_authorization_type(
            conn, proposer_id,
        )
        sole_clinician_override = False
        if proposer_auth_type == CLIN_AUTH_SOLE_LEAD:
            # sole_lead: same-actor approval is permitted because the
            # session-separation check above already requires a fresh login
            # session. The 30-day auto-revert (Plan Gap M) and codeword
            # precondition (b) below remain in force — those are not relaxed
            # by this exemption. We flag the audit row so a reviewer sees
            # the deviation explicitly.
            sole_clinician_override = (proposer_id == approver_id)
        else:
            # multi_clinician_team: enforce different actor (username).
            if proposer_id and approver_id and proposer_id == approver_id:
                raise HTTPException(
                    409,
                    detail={
                        "reason": "multi_clinician_required",
                        "proposer_authorization_type": proposer_auth_type,
                    },
                )

        # Precondition (b): codeword precondition. MUST run BEFORE the flip
        # so a zero-codeword user is never silenced without a safety net.
        cw_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM user_safety_codewords
             WHERE user_id = $1 AND active = TRUE
            """,
            user_id,
        )
        if not cw_count:
            raise HTTPException(
                409,
                detail={"reason": "requires_codeword"},
            )

        # All preconditions met — flip to active. Wipe proposer_token_hash
        # so a future leak of this row cannot replay the same-session check.
        new_state = {
            "state": SAFE_SILENCE_ACTIVE,
            "proposer_id": sss.get("proposer_id"),
            # Persist gate hashes for sole_lead admin revoke session separation
            # after proposer_token_hash is cleared (Priority 2a).
            "gate_proposer_token_hash": proposer_token_hash or None,
            "gate_approver_token_hash": approver_token_hash or None,
            "proposer_token_hash": None,
            "approver_id": approver_id,
            "proposed_at": sss.get("proposed_at"),
            "approved_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "expiry_warning_sent_at": None,
            "auto_revert_eligible_at": expires_at.isoformat(),
            "codeword_precondition_met": True,
            "reason_redacted": sss.get("reason_redacted"),
            "proposal_id": stored_proposal_id,
            "approver_note_redacted": body.approver_note_redacted,
        }
        await conn.execute(
            """
            UPDATE users
               SET profile_data = jsonb_set(
                       COALESCE(profile_data, '{}'::jsonb),
                       '{safe_silence_mode_state}',
                       $2::jsonb,
                       true
                   ),
                   updated_at = NOW()
             WHERE username = $1
            """,
            user_id,
            json.dumps(new_state),
        )

    await _emit_profile_mutation_audit(
        db_pool,
        target_user_id=user_id,
        actor_id=approver_id,
        actor_role="ADMIN",
        mutation_kind="safe_silence_approved",
        additional_fields_redacted={
            "approver_note_present": bool(body.approver_note_redacted),
            "expires_at": expires_at.isoformat(),
            "approval_ttl_days": SAFE_SILENCE_APPROVAL_TTL_DAYS,
            "active_codeword_count": int(cw_count),
            "proposer_authorization_type": proposer_auth_type,
            "sole_clinician_override": bool(sole_clinician_override),
        },
        severity="high",
        event_type=EVT_SAFE_SILENCE_STATE_CHANGE,
    )
    return {
        "ok": True,
        "state": SAFE_SILENCE_ACTIVE,
        "approved_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "approval_ttl_days": SAFE_SILENCE_APPROVAL_TTL_DAYS,
        "proposer_authorization_type": proposer_auth_type,
        "sole_clinician_override": bool(sole_clinician_override),
    }


# ------- ADMIN: redacted profile read ----------------------------------------


@admin_router.get("/{user_id}/redacted")
async def get_admin_redacted_profile(
    user_id: str,
    request: Request,
    principal: Dict = Depends(require_admin),
):
    """Admin-redacted view of the profile. Strips clinician-only narrative
    (notes_redacted, reason_redacted, attorney_contact_redacted) so the
    admin sees structural state without leaking clinical detail.
    """
    db_pool = request.app.state.db_pool
    if db_pool is None:
        raise HTTPException(503, detail={"reason": "database_unavailable"})
    full = await _load_profile_data(db_pool, user_id)

    # Redact clinician narrative fields. The admin still sees that the
    # field is present (length > 0) so they can ask the clinician for
    # context if needed, but the text never leaves the clinician_only
    # access tier.
    def _redact_text(item, key):
        val = item.get(key)
        if val:
            item[key] = "[REDACTED]"
            item[f"{key}_present"] = True
        else:
            item[f"{key}_present"] = False

    for td in full.get("trigger_dates", []):
        _redact_text(td, "notes_redacted")
    for pv in full.get("polyvictim_layers", []):
        _redact_text(pv, "notes_redacted")
    for ls in full.get("legal_status", []):
        _redact_text(ls, "attorney_contact_redacted")
    sss = full.get("safe_silence_mode_state") or {}
    if sss.get("reason_redacted"):
        sss["reason_redacted"] = "[REDACTED]"
        sss["reason_redacted_present"] = True
    if sss.get("approver_note_redacted"):
        sss["approver_note_redacted"] = "[REDACTED]"
        sss["approver_note_redacted_present"] = True
    full["safe_silence_mode_state"] = sss
    full["_admin_redacted"] = True
    return full


# =============================================================================
# Auditor self-check — runs at module import; structural-only (no DB)
# =============================================================================


def _auditor_self_check() -> Dict[str, bool]:
    """Module-load checks that don't need DB connectivity. Failures raise
    ``RuntimeError`` so the router refuses to import — main.py wraps the
    import in try/except and logs a fail-soft warning, leaving the rest
    of the v1.3 stack running.

    Phase 5's ``sensitive_bridge_auditor`` will additionally run runtime
    DB-backed synthetic tests (same-session 409, codeword 409, orchestrator
    can't mutate). Those checks live there because they need a writable
    test fixture.
    """
    results: Dict[str, bool] = {}

    # Check 1: phase4b_all_coach_endpoints_use_require_clinician_for_user
    # Static parse of this very file. Greps every coach_router decorator
    # block for the dependency declaration. If a developer adds a new
    # /api/coach/sensitive-profile/... route without the dep, the import
    # fails — the trust auditor only catches it at the next window, but
    # this catch is at boot time which is faster.
    try:
        src_path = os.path.abspath(__file__)
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()

        # Find every @coach_router.<verb>(...) decorator and the lines
        # following it until the def body opens.
        decorator_pattern = re.compile(
            r"@coach_router\.(get|post|put|patch|delete)\([^)]*\)"
        )
        check_pattern = re.compile(
            r"Depends\(require_clinician_for_user\)"
        )
        bad_routes: List[str] = []
        for m in decorator_pattern.finditer(src):
            # Look at the next ~20 lines for the dependency declaration.
            window = src[m.end(): m.end() + 2000]
            # Stop scanning at the next decorator or the next blank-line
            # gap of 2+ lines (heuristic for end of route).
            window_end = window.find("\n\n\n")
            if window_end > 0:
                window = window[:window_end]
            if not check_pattern.search(window):
                bad_routes.append(m.group(0))
        results["phase4b_all_coach_endpoints_use_require_clinician_for_user"] = (
            len(bad_routes) == 0
        )
        if bad_routes:
            raise RuntimeError(
                "sensitive_profile_api: missing require_clinician_for_user "
                f"dep on routes: {bad_routes}"
            )
    except RuntimeError:
        raise
    except Exception as e:  # pragma: no cover
        logger.warning("auditor self-check 1 failed: %s", e)
        results["phase4b_all_coach_endpoints_use_require_clinician_for_user"] = False

    # Check 2: safe_silence_orchestrator_cannot_mutate
    # Static grep on the orchestrator file for forbidden write patterns.
    try:
        from app.services import sensitive_clinical_bridge as _scb_mod

        scb_path = _scb_mod.__file__ or ""
        if scb_path and os.path.exists(scb_path):
            with open(scb_path, "r", encoding="utf-8") as f:
                scb_src = f.read()
            forbidden = re.compile(
                r"(UPDATE\s+users[^;]*safe_silence_mode_state)"
                r"|(jsonb_set\s*\(\s*[^)]*safe_silence_mode_state)",
                re.IGNORECASE,
            )
            if forbidden.search(scb_src):
                results["safe_silence_orchestrator_cannot_mutate"] = False
                raise RuntimeError(
                    "sensitive_clinical_bridge.py contains a forbidden "
                    "safe_silence_mode_state mutation. The orchestrator must "
                    "only emit recommendation events; the portal router is "
                    "the sole writer."
                )
            results["safe_silence_orchestrator_cannot_mutate"] = True
        else:
            results["safe_silence_orchestrator_cannot_mutate"] = True
    except RuntimeError:
        raise
    except Exception as e:  # pragma: no cover
        logger.warning("auditor self-check 2 failed: %s", e)
        results["safe_silence_orchestrator_cannot_mutate"] = False

    # Check 3: contract_version_pinned
    # Sanity that the version constant is set; the trust auditor will
    # compare it against the trust_baseline row in Phase 5.
    results["contract_version_pinned"] = bool(CONTRACT_VERSION)

    # Check 4: pii_screen_helper_present
    # Confirm the lazy import resolves so we don't only learn at runtime.
    try:
        screen, _exc = _import_pii_screen()
        results["pii_screen_helper_present"] = callable(screen)
    except Exception as e:  # pragma: no cover
        logger.warning("auditor self-check 4 failed: %s", e)
        results["pii_screen_helper_present"] = False

    return results


AUDITOR_SELF_CHECK_RESULTS: Dict[str, bool] = _auditor_self_check()
"""Module-level snapshot of the boot-time auditor checks. Phase 5's
``sensitive_bridge_auditor`` reads this dict during its tab evaluation."""


__all__ = [
    "coach_router",
    "admin_router",
    "require_clinician_for_user",
    "require_admin_with_session_token",
    "CONTRACT_VERSION",
    "SAFE_SILENCE_APPROVAL_TTL_DAYS",
    "AUDITOR_SELF_CHECK_RESULTS",
]
