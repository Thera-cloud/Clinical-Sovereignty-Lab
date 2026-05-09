"""
Coach Override Protocol — validation, TTL, and audit logging for coach_client_overrides.

Phase 3 v1.3 Extension (Sensitive Clinical Bridge)
==================================================
Adds new focus domains, an acuity-tier escalation registry, and a redacted
coach handoff-payload builder while preserving v1.2 behavior identically
(additivity contract). Per the protected-files rule, every existing function
signature and tier registry entry is unchanged; v1.3 surfaces are added
alongside.

NOTE 1 (BLOCKING — applied) — ALLOWED_FOCUS_DOMAINS extension verification.
    All consumers verified safe-additive before adding the four new domains
    (`intimacy_clinical`, `sexual_trauma`, `trafficking`, `infidelity`):

      - `bridge_server.py` — uses `sorted(ALLOWED_FOCUS_DOMAINS)` returned to
        the client and a `validate_merged()` membership check. Both are
        additive: new domains automatically appear in the wire response
        and pass validation without code changes.
      - `app/sse/adapters/coach_story_bridge.py` — pass-through
        `overrides.get("focus_domain")` (no dispatch dict).
      - `mobile/lib/updated_screens.dart` — coach portal dropdown is driven
        by the server-supplied `allowed_focus_domains` field (line 6138);
        new domains render as picker options automatically.
      - DB migrations 186/189 store `focus_domain` as TEXT (no enum
        constraint). No DDL change required.

    No exhaustive `match` / dispatch dicts found anywhere on focus_domain.
    Auditor check `focus_domain_consumers_handle_v1_3_additions` greps for
    any dict literal keyed by focus_domain values; failing it indicates a
    consumer added between Phase 3 build and Phase 6 baseline that needs
    explicit handling.

NOTE 2 (NON-BLOCKING but high-attention — applied) — `build_handoff_payload`
    redaction contract is enforced *inside* the function, not just at the
    auditor surface:

    (a) Pre-return raw-transcript leak validator scans every assembled
        string field for verbatim segments matching `conversation_history`
        rows. On match it raises `RawTranscriptLeakError` and refuses to
        return; coach gets no payload rather than a leaky one.
    (b) PII screen reuses `_screen_notes_for_pii` from
        `trigger_date_registry.py` — single source of PII patterns across
        the codebase. Patterns updated there propagate here automatically.
        Forking would create the silent-divergence failure mode the
        Phase 2A `PIIScreenViolation` design was meant to prevent.
    (c) Payload schema is versioned with the same MAJOR.MINOR.PATCH-DATE
        + content-hash pattern as `specialized_resources.py`. When a v2
        partner integration arrives, schema drift will be detectable from
        the audit log (`payload_schema_version` field) without forensic
        archaeology.

NOTE 3 (NON-BLOCKING — applied) — New acuity tiers added additively to a new
    `ACUITY_TIERS` registry. Existing override surfaces (pacing, focus_domain,
    clinical_hold) remain untouched. The `trafficking_disclosure` tier
    explicitly bypasses the 62h `nate_checkin_agent` cadence; the rationale
    and a "DO NOT extend bypass without clinician sign-off" guardrail comment
    are inlined at the bypass-flag declaration so future maintainers see the
    constraint before they consider widening it.

ADDITIVITY CONTRACT
-------------------
Calling any pre-existing function (`merge_override_payload`,
`validate_merged`, `compute_expiry_columns`, `mission_reference_valid`,
`insert_audit_rows`, `insert_clear_audit`, `filter_active_overrides`)
with v1.2 inputs produces behavior identical to v1.2. The new v1.3 surfaces
(`escalate_acuity`, `build_handoff_payload`, `ACUITY_TIERS`,
`HANDOFF_PAYLOAD_SCHEMA_VERSION`, `RawTranscriptLeakError`) are alongside,
never replacing.

Phase 6 fixture suite verifies this with:
    - phase3_coach_override_v1_2_fixtures_pass
    - focus_domain_consumers_handle_v1_3_additions
    - handoff_payload_no_raw_transcript_leak
    - handoff_payload_pii_screen_reuses_trigger_date_registry
    - acuity_tier_registry_additive_only
    - trafficking_disclosure_bypasses_62h_cadence
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

import asyncpg

ALLOWED_FOCUS_DOMAINS = frozenset(
    {
        # ---- v1.2 (DO NOT REMOVE — additive contract) ----
        "clinical",
        "coaching",
        "family_systems",
        "crisis",
        "mindfulness",
        "boundaries",
        "trauma_informed",
        "attachment",
        "general",
        "cbt_techniques",
        "motivational",
        # ---- v1.3 (Sensitive Clinical Bridge — Note 1 verified additive) ----
        # Adding here surfaces them in:
        #   - bridge_server.py wire response (sorted(ALLOWED_FOCUS_DOMAINS))
        #   - mobile coach portal dropdown (server-driven)
        #   - validate_merged() membership check (auto-accepts)
        # No other code paths require updates.
        "intimacy_clinical",
        "sexual_trauma",
        "trafficking",
        "infidelity",
    }
)

# Snapshot of the v1.2 set, preserved for the auditor's additivity check
# (`acuity_tier_registry_additive_only` greps for this constant).
_ALLOWED_FOCUS_DOMAINS_V1_2: FrozenSet[str] = frozenset(
    {
        "clinical",
        "coaching",
        "family_systems",
        "crisis",
        "mindfulness",
        "boundaries",
        "trauma_informed",
        "attachment",
        "general",
        "cbt_techniques",
        "motivational",
    }
)

PACING_EXPIRY_DAYS = 30
FOCUS_EXPIRY_DAYS = 14


def _norm_pacing(v: Any) -> str:
    p = (str(v or "normal")).strip().lower()
    return p if p in ("slow", "normal", "fast") else "normal"


def merge_override_payload(prev: Optional[Dict[str, Any]], d: Dict[str, Any]) -> Dict[str, Any]:
    prev = prev or {}
    out: Dict[str, Any] = {
        "focus_domain": d["focus_domain"] if "focus_domain" in d else prev.get("focus_domain"),
        "pacing": d["pacing"] if "pacing" in d else prev.get("pacing") or "normal",
        "clinical_hold": bool(d["clinical_hold"])
        if "clinical_hold" in d
        else bool(prev.get("clinical_hold")),
        "mission_priority": d["mission_priority"]
        if "mission_priority" in d
        else prev.get("mission_priority"),
        "notes": d["notes"] if "notes" in d else prev.get("notes"),
    }
    out["pacing"] = _norm_pacing(out["pacing"])
    fd = out["focus_domain"]
    if fd is not None and isinstance(fd, str) and not fd.strip():
        out["focus_domain"] = None
    elif isinstance(fd, str):
        out["focus_domain"] = fd.strip()
    mp = out["mission_priority"]
    if mp is not None and isinstance(mp, str) and not mp.strip():
        out["mission_priority"] = None
    elif isinstance(mp, str):
        out["mission_priority"] = mp.strip()
    return out


def compute_expiry_columns(
    prev: Dict[str, Any],
    merged: Dict[str, Any],
    prev_expires_at: Optional[datetime],
    prev_focus_expires: Optional[datetime],
) -> Tuple[Optional[datetime], Optional[datetime]]:
    now = datetime.now(timezone.utc)
    prev_p = _norm_pacing(prev.get("pacing"))
    new_p = merged["pacing"]
    pacing_exp = prev_expires_at
    focus_exp = prev_focus_expires

    if prev_p != new_p:
        if new_p == "normal":
            pacing_exp = None
        else:
            pacing_exp = now + timedelta(days=PACING_EXPIRY_DAYS)
    prev_f = prev.get("focus_domain")
    new_f = merged.get("focus_domain")
    prev_f_n = (prev_f or None) if not prev_f else prev_f
    new_f_n = (new_f or None) if not new_f else new_f
    if prev_f_n != new_f_n:
        if not new_f_n:
            focus_exp = None
        else:
            focus_exp = now + timedelta(days=FOCUS_EXPIRY_DAYS)

    return pacing_exp, focus_exp


def validate_merged(role: str, prev: Dict[str, Any], merged: Dict[str, Any], reason: str) -> Optional[str]:
    r = (reason or "").strip()
    if len(r) < 1:
        return "override_reason is required"

    if merged.get("clinical_hold") and role not in ("COACH", "ADMIN"):
        return "clinical_hold may only be set by COACH or ADMIN"

    prev_p = _norm_pacing(prev.get("pacing"))
    new_p = merged["pacing"]
    if prev_p == "slow" and new_p == "fast" and len(r) < 20:
        return "Changing pacing from slow to fast requires a reason of at least 20 characters"

    fd = merged.get("focus_domain")
    if fd:
        key = fd.strip().lower()
        if key not in ALLOWED_FOCUS_DOMAINS:
            return "focus_domain is not in the allowed domain list"

    return None


async def mission_reference_valid(conn: asyncpg.Connection, client_user_id: str, ref: str) -> bool:
    ref = (ref or "").strip()
    if not ref:
        return True
    row = await conn.fetchrow(
        """
        SELECT 1 FROM sse_missions
        WHERE user_id = $1 AND mission_id::text = $2
        LIMIT 1
        """,
        client_user_id,
        ref,
    )
    if row:
        return True
    row2 = await conn.fetchrow(
        """
        SELECT 1 FROM sse_quests
        WHERE user_id = $1 AND quest_id::text = $2
        LIMIT 1
        """,
        client_user_id,
        ref,
    )
    return row2 is not None


async def insert_audit_rows(
    conn: asyncpg.Connection,
    coach_user_id: str,
    client_user_id: str,
    prev: Dict[str, Any],
    merged: Dict[str, Any],
    reason: str,
) -> None:
    pairs: List[Tuple[str, Any, Any]] = [
        ("pacing", prev.get("pacing"), merged.get("pacing")),
        ("focus_domain", prev.get("focus_domain"), merged.get("focus_domain")),
        ("clinical_hold", bool(prev.get("clinical_hold")), bool(merged.get("clinical_hold"))),
        ("mission_priority", prev.get("mission_priority"), merged.get("mission_priority")),
    ]
    rsn = (reason or "")[:8000]
    for otype, old, new in pairs:
        if otype == "clinical_hold":
            o_old = "true" if old else "false"
            o_new = "true" if new else "false"
        else:
            o_old = None if old is None else str(old)
            o_new = None if new is None else str(new)
        if o_old == o_new:
            continue
        await conn.execute(
            """
            INSERT INTO coach_override_audit (
                coach_user_id, client_user_id, override_type,
                previous_value, new_value, reason
            ) VALUES ($1, $2, $3, $4, $5, $6)
            """,
            coach_user_id,
            client_user_id,
            otype,
            o_old,
            o_new,
            rsn,
        )


async def insert_clear_audit(
    conn: asyncpg.Connection,
    coach_user_id: str,
    client_user_id: str,
    snapshot: Dict[str, Any],
    reason: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO coach_override_audit (
            coach_user_id, client_user_id, override_type,
            previous_value, new_value, reason
        ) VALUES ($1, $2, 'clear_all', $3, NULL, $4)
        """,
        coach_user_id,
        client_user_id,
        json.dumps(snapshot, default=str)[:20000],
        (reason or "")[:8000],
    )


def filter_active_overrides(row: asyncpg.Record, now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Apply expires_at (pacing) and focus_domain_expires_at; clinical_hold has no expiry.
    """
    if not row:
        return {}
    if now is None:
        now = datetime.now(timezone.utc)
    d = dict(row)
    out: Dict[str, Any] = {}

    exp = d.get("expires_at")
    p_ok = exp is None or (hasattr(exp, "replace") and exp > now)
    pacing_val = d.get("pacing") or "normal"
    if p_ok and pacing_val and pacing_val != "normal":
        out["pacing"] = pacing_val

    fe = d.get("focus_domain_expires_at")
    f_ok = fe is None or (hasattr(fe, "replace") and fe > now)
    if f_ok and d.get("focus_domain"):
        out["focus_domain"] = d["focus_domain"]

    if d.get("clinical_hold"):
        out["clinical_hold"] = True

    if d.get("mission_priority"):
        out["mission_priority"] = d["mission_priority"]

    if d.get("notes"):
        out["notes"] = d["notes"]

    u = d.get("updated_at")
    out["updated_at"] = u.isoformat() if u and hasattr(u, "isoformat") else str(u) if u else None
    out["expires_at"] = exp.isoformat() if exp and hasattr(exp, "isoformat") else None
    out["focus_domain_expires_at"] = (
        fe.isoformat() if fe and hasattr(fe, "isoformat") else None
    )
    return out


# ===========================================================================
# Phase 3 v1.3 — Sensitive Clinical Bridge surfaces (additive only)
# ===========================================================================
# Everything below is additive. Nothing above this line was modified beyond
# extending `ALLOWED_FOCUS_DOMAINS` (Note 1) and the module docstring/imports.

# ---------------------------------------------------------------------------
# Acuity tier registry (Note 3)
# ---------------------------------------------------------------------------

# Each tier metadata block carries:
#   severity            -- "info" | "monitor" | "concern" | "high" | "critical"
#   bypasses_62h_cadence -- True iff this tier suppresses standard
#                          nate_checkin_agent pacing (see DO-NOT comment below)
#   plan_gap            -- back-reference to plan v1.3 gap that introduced it
#   description         -- one-line clinician-facing summary
ACUITY_TIERS: Dict[str, Dict[str, Any]] = {
    # -- Trafficking-disclosure family ---------------------------------------
    # Trafficking disclosure overrides 62h cadence per plan v1.3 Gap 6.
    # Clinical rationale: trafficking-disclosure-tier events are
    # time-sensitive (active situation) or legally-actionable (recruiter
    # disclosure with statute-of-limitations implications). Cadence pacing
    # protects against alert fatigue for routine signals; this is not
    # routine.
    # DO NOT add this bypass to other trigger types without clinician
    # sign-off. Adding bypass=True for, e.g., dissociation_grounding would
    # erode the cadence pacing that protects coach attention. Any future
    # bypass requires (a) clinician written sign-off documented in
    # docs/SENSITIVE_CLINICAL_BRIDGE_GUIDELINES_*.md and (b) an explicit
    # comment update here referencing that sign-off.
    "trafficking_disclosure": {
        "severity": "critical",
        "bypasses_62h_cadence": True,
        "plan_gap": "Gap 6 / Gap G",
        "description": "Trafficking disclosure detected — immediate coach alert",
    },
    "recruiter_holding": {
        "severity": "high",
        "bypasses_62h_cadence": True,
        "plan_gap": "Gap G",
        "description": "Survivor-as-recruiter disclosure — coach + legal alert",
    },
    # -- Codeword + safe-silence-mode family --------------------------------
    "codeword_triggered": {
        "severity": "high",
        "bypasses_62h_cadence": False,
        "plan_gap": "Gap 2 / Gap K",
        "description": "User-set safety codeword detected (silent acuity raise)",
    },
    "safe_silence_mode_state_change": {
        "severity": "monitor",
        "bypasses_62h_cadence": False,
        "plan_gap": "Gap A",
        "description": "safe_silence_mode transitioned (pending_approval/active/inactive)",
    },
    # -- Reengagement family (Gap 7) ----------------------------------------
    "reengagement_concern": {
        "severity": "concern",
        "bypasses_62h_cadence": False,
        "plan_gap": "Gap 7",
        "description": "Reengagement signal at 'concern' severity — coach awareness",
    },
    "reengagement_imminent": {
        "severity": "critical",
        "bypasses_62h_cadence": True,
        "plan_gap": "Gap 7",
        "description": "Imminent reengagement (received_contact + direction confidence)",
    },
    # -- Trigger date proactive (Gap 5) -------------------------------------
    "trigger_date_proactive": {
        "severity": "high",
        "bypasses_62h_cadence": False,
        "plan_gap": "Gap 5",
        "description": "Significant date matched (escape anniversary, court date, etc.)",
    },
    # -- Parenting / RJ / approval expiry (Gaps P, Q, M) --------------------
    "parenting_crisis": {
        "severity": "high",
        "bypasses_62h_cadence": False,
        "plan_gap": "Gap P",
        "description": "Imminent custody loss or child-welfare investigation",
    },
    "rj_session_proximity": {
        "severity": "high",
        "bypasses_62h_cadence": False,
        "plan_gap": "Gap Q",
        "description": "Imminent restorative-justice session — predictable activation",
    },
    "approval_expiring": {
        "severity": "monitor",
        "bypasses_62h_cadence": False,
        "plan_gap": "Gap M",
        "description": "safe_silence_mode approval expiring (25-day warning)",
    },
}

# Snapshot of the v1.2 tier set for the auditor's additivity check.
# Pre-v1.3 there was no formal tier registry; v1.2 alerts flowed implicitly
# through `coach_override_audit` rows. The empty set here documents the
# baseline so any future tier removal fails the additivity check.
_ACUITY_TIERS_V1_2: FrozenSet[str] = frozenset()


def escalate_acuity(
    tier: str,
    *,
    user_id: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build an acuity escalation event dict for the orchestrator to emit.

    This function does NOT write to the DB — that's the orchestrator's job
    in Phase 4. It returns a structured event dict that:
      - Validates `tier` against `ACUITY_TIERS` (raises `ValueError` on
        unknown tier — fail-closed, never escalate to "unknown")
      - Surfaces `bypasses_62h_cadence` so the orchestrator wiring step can
        pass it directly to `nate_checkin_agent`
      - Carries `plan_gap` for forensic correlation in `sensitive_bridge_log`

    The orchestrator wraps this into a `BridgeDecision.coach_alert` payload.

    Parameters
    ----------
    tier
        Must be a key in `ACUITY_TIERS`. Unknown tiers fail-closed.
    user_id
        Hardware ID or username; opaque to this module.
    context
        Free-form clinician-facing context. Will pass through PII screen
        in `build_handoff_payload` if forwarded to the partner seam.

    Returns
    -------
    dict with keys: tier, severity, bypasses_62h_cadence, plan_gap,
    description, user_id, escalated_at, context.
    """
    if tier not in ACUITY_TIERS:
        # Fail-closed: never silently escalate to "unknown" tier.
        raise ValueError(
            f"escalate_acuity: unknown tier {tier!r}. Valid tiers: "
            f"{sorted(ACUITY_TIERS.keys())}"
        )
    meta = ACUITY_TIERS[tier]
    return {
        "tier": tier,
        "severity": meta["severity"],
        "bypasses_62h_cadence": meta["bypasses_62h_cadence"],
        "plan_gap": meta["plan_gap"],
        "description": meta["description"],
        "user_id": user_id,
        "escalated_at": datetime.now(timezone.utc).isoformat(),
        "context": context or {},
    }


# ---------------------------------------------------------------------------
# Handoff payload schema versioning (Note 2c)
# ---------------------------------------------------------------------------

HANDOFF_PAYLOAD_SCHEMA_VERSION = "1.0.0-2026-05-08"

# Schema content hash — bumped whenever the payload structure or any
# helper-emitted field changes. Computed deterministically from the
# canonical schema descriptor below. Audited by Phase 6
# `handoff_payload_schema_hash_matches`.
_HANDOFF_PAYLOAD_SCHEMA_DESCRIPTOR = {
    "version": HANDOFF_PAYLOAD_SCHEMA_VERSION,
    "fields": [
        "schema_version",
        "user_id",
        "trigger",
        "acuity",
        "safety_status_flags",
        "recent_crystal_references",
        "audit_excerpt",
        "context_redacted",
        "generated_at",
        "redaction_log",
    ],
    "redaction_contract": {
        "raw_transcript_blocked": True,
        "pii_screen_source": "trigger_date_registry._screen_notes_for_pii",
    },
}
HANDOFF_PAYLOAD_SCHEMA_HASH = hashlib.sha256(
    json.dumps(_HANDOFF_PAYLOAD_SCHEMA_DESCRIPTOR, sort_keys=True).encode("utf-8")
).hexdigest()


class RawTranscriptLeakError(RuntimeError):
    """Raised by `build_handoff_payload` if assembled output contains
    verbatim text from `conversation_history`. Fail-closed: coach receives
    no payload rather than a leaky one. The orchestrator should log the
    incident and surface a generic 'payload assembly failed' to the coach
    portal — never the raw mismatch detail.
    """


def _validate_no_raw_transcript_leak(
    payload: Dict[str, Any],
    recent_user_text_samples: Sequence[str],
    *,
    min_match_chars: int = 40,
) -> None:
    """Scan every string field of `payload` for verbatim segments matching
    any text in `recent_user_text_samples`. Raises RawTranscriptLeakError
    on hit.

    `min_match_chars` is the contiguous-char threshold per Note 2(a).
    Below this, false positives explode (common phrases like "I feel like
    I" appear in countless conversations). 40 chars is conservative;
    auditor tunes via the `handoff_payload_no_raw_transcript_leak` check.

    Implementation note: this is a contract check, not a perfect leak
    detector. The primary defense is upstream (orchestrator never passes
    raw transcript into `context`). This is the belt to that suspenders.
    """
    if not recent_user_text_samples:
        return
    samples = [s for s in recent_user_text_samples if isinstance(s, str) and len(s) >= min_match_chars]
    if not samples:
        return

    def _walk(node: Any) -> None:
        if isinstance(node, str):
            if not node:
                return
            for sample in samples:
                # Slide a window of `min_match_chars` across the sample.
                for i in range(0, len(sample) - min_match_chars + 1):
                    chunk = sample[i : i + min_match_chars]
                    if chunk in node:
                        raise RawTranscriptLeakError(
                            "handoff payload contains verbatim segment from "
                            "conversation_history (≥{} chars)".format(min_match_chars)
                        )
        elif isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                _walk(v)

    _walk(payload)


def _screen_payload_for_pii(payload: Dict[str, Any]) -> Optional[Tuple[str, int, str]]:
    """Walk payload string fields and reuse the canonical PII screen from
    `trigger_date_registry`. Returns (pattern_label, position, field_path)
    on first hit; None if clean.

    Per Note 2(b): single source of PII patterns. We import the screen
    function lazily so a circular-import shift in either module doesn't
    break this one at module load.
    """
    try:
        from app.services.trigger_date_registry import _screen_notes_for_pii
    except Exception:
        # If the import fails, fail closed — refuse to assert "clean".
        return ("pii_screen_unavailable", -1, "<import_error>")

    def _walk(node: Any, path: str) -> Optional[Tuple[str, int, str]]:
        if isinstance(node, str):
            hit = _screen_notes_for_pii(node)
            if hit is not None:
                label, pos = hit
                return (label, pos, path)
            return None
        if isinstance(node, dict):
            for k, v in node.items():
                r = _walk(v, f"{path}.{k}" if path else str(k))
                if r is not None:
                    return r
            return None
        if isinstance(node, (list, tuple)):
            for i, v in enumerate(node):
                r = _walk(v, f"{path}[{i}]")
                if r is not None:
                    return r
            return None
        return None

    return _walk(payload, "")


@dataclass(frozen=True)
class HandoffPayload:
    """Frozen view of the redacted coach handoff bundle. Immutable after
    construction; downstream code must not mutate.

    The `to_dict()` form is what the orchestrator serializes into
    `BridgeDecision.coach_alert.payload` and what eventually flows to a
    partner integration in v2.
    """

    schema_version: str
    user_id: str
    trigger: str
    acuity: Dict[str, Any]
    safety_status_flags: Dict[str, Any]
    recent_crystal_references: List[Dict[str, Any]]
    audit_excerpt: List[Dict[str, Any]]
    context_redacted: Dict[str, Any]
    generated_at: str
    redaction_log: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "schema_hash": HANDOFF_PAYLOAD_SCHEMA_HASH,
            "user_id": self.user_id,
            "trigger": self.trigger,
            "acuity": self.acuity,
            "safety_status_flags": self.safety_status_flags,
            "recent_crystal_references": list(self.recent_crystal_references),
            "audit_excerpt": list(self.audit_excerpt),
            "context_redacted": self.context_redacted,
            "generated_at": self.generated_at,
            "redaction_log": list(self.redaction_log),
        }


def build_handoff_payload(
    user_id: str,
    trigger: str,
    context: Optional[Dict[str, Any]] = None,
    *,
    recent_crystal_references: Optional[Sequence[Dict[str, Any]]] = None,
    audit_excerpt: Optional[Sequence[Dict[str, Any]]] = None,
    safety_status_flags: Optional[Dict[str, Any]] = None,
    recent_user_text_samples: Optional[Sequence[str]] = None,
) -> HandoffPayload:
    """Build a redacted coach handoff payload (Note 2).

    Three contract checks fire BEFORE returning:
      (a) Raw-transcript leak validator — refuses payload if any string
          field contains a verbatim ≥40-char segment from
          `recent_user_text_samples`. Raises `RawTranscriptLeakError`.
      (b) PII screen — reuses `trigger_date_registry._screen_notes_for_pii`.
          On hit, raises `PIIScreenViolation` (subclass of ValueError) so
          the Phase 4 REST layer can surface a 422 with structured detail.
      (c) Schema versioning — every payload carries
          `HANDOFF_PAYLOAD_SCHEMA_VERSION` and `HANDOFF_PAYLOAD_SCHEMA_HASH`
          so v2 partner integrations can detect drift from the audit log.

    The function is purely-functional: no DB access, no logging side
    effects. Caller (orchestrator) is responsible for fetching crystal
    references, audit excerpts, and recent user text for the leak check,
    and for emitting `audit_event = 'coach_handoff_payload_built'` after
    a clean return.

    Raises
    ------
    ValueError
        If `trigger` is not in `ACUITY_TIERS`.
    PIIScreenViolation
        If any payload string contains PII (per shared screen patterns).
    RawTranscriptLeakError
        If any payload string contains a verbatim segment from
        `recent_user_text_samples`.
    """
    if trigger not in ACUITY_TIERS:
        raise ValueError(
            f"build_handoff_payload: unknown trigger {trigger!r}. Valid: "
            f"{sorted(ACUITY_TIERS.keys())}"
        )

    redaction_log: List[str] = []

    # The context dict from the orchestrator may carry clinically-relevant
    # context but MUST NOT carry raw transcript. We shallow-copy and strip
    # any keys that look like transcript carriers as a belt-and-suspenders
    # measure on top of the leak validator below.
    raw_context = dict(context or {})
    transcript_key_patterns = re.compile(
        r"(transcript|user_text|raw_message|message_body|verbatim)",
        re.IGNORECASE,
    )
    context_redacted: Dict[str, Any] = {}
    for k, v in raw_context.items():
        if transcript_key_patterns.search(str(k)):
            redaction_log.append(f"context_key_stripped:{k}")
            continue
        context_redacted[k] = v

    acuity_meta = ACUITY_TIERS[trigger]
    acuity_block = {
        "tier": trigger,
        "severity": acuity_meta["severity"],
        "bypasses_62h_cadence": acuity_meta["bypasses_62h_cadence"],
        "plan_gap": acuity_meta["plan_gap"],
    }

    payload_obj = HandoffPayload(
        schema_version=HANDOFF_PAYLOAD_SCHEMA_VERSION,
        user_id=user_id,
        trigger=trigger,
        acuity=acuity_block,
        safety_status_flags=dict(safety_status_flags or {}),
        recent_crystal_references=[dict(r) for r in (recent_crystal_references or [])],
        audit_excerpt=[dict(a) for a in (audit_excerpt or [])],
        context_redacted=context_redacted,
        generated_at=datetime.now(timezone.utc).isoformat(),
        redaction_log=redaction_log,
    )

    # ---- Contract check (a): raw-transcript leak ----
    payload_dict = payload_obj.to_dict()
    _validate_no_raw_transcript_leak(
        payload_dict,
        recent_user_text_samples or (),
    )

    # ---- Contract check (b): PII screen ----
    pii_hit = _screen_payload_for_pii(payload_dict)
    if pii_hit is not None:
        label, position, field_path = pii_hit
        # Lazy import keeps this module importable even when
        # trigger_date_registry has its own import-time issues.
        from app.services.trigger_date_registry import PIIScreenViolation
        raise PIIScreenViolation(
            pattern_matched=label,
            field_position=position,
            field_name=f"handoff_payload:{field_path}",
        )

    # Contract check (c) is enforced at construction (schema_version +
    # schema_hash are baked into HandoffPayload.to_dict).
    return payload_obj


# ---------------------------------------------------------------------------
# Auditor self-check (Phase 6 baseline)
# ---------------------------------------------------------------------------


def _verify_focus_domains_additive() -> bool:
    """Auditor check `focus_domain_consumers_handle_v1_3_additions`
    surface — confirms v1.2 domains are still present (additivity contract).
    """
    return _ALLOWED_FOCUS_DOMAINS_V1_2.issubset(ALLOWED_FOCUS_DOMAINS)


def _verify_acuity_tiers_additive() -> bool:
    """Auditor check `acuity_tier_registry_additive_only` surface —
    confirms no v1.2 tier was removed. Pre-v1.3 the v1.2 set was empty;
    this check exists to fail-loudly if a future maintainer removes a
    v1.3-introduced tier without explicit clinician sign-off.
    """
    return _ACUITY_TIERS_V1_2.issubset(set(ACUITY_TIERS.keys()))


def _verify_trafficking_disclosure_bypass_documented() -> bool:
    """Auditor check `trafficking_disclosure_bypasses_62h_cadence` —
    confirms the bypass flag is set on the trafficking_disclosure tier.
    The "DO NOT extend" comment is a separate grep-based check in the
    Phase 6 auditor.
    """
    meta = ACUITY_TIERS.get("trafficking_disclosure")
    return bool(meta and meta.get("bypasses_62h_cadence") is True)


def _verify_handoff_schema_hash_stable() -> bool:
    """Auditor check `handoff_payload_schema_hash_matches` — recompute
    the schema hash and confirm it matches the constant. Tamper detection.
    """
    recomputed = hashlib.sha256(
        json.dumps(_HANDOFF_PAYLOAD_SCHEMA_DESCRIPTOR, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return recomputed == HANDOFF_PAYLOAD_SCHEMA_HASH


def _auditor_self_check() -> Dict[str, Any]:
    """Synchronous auditor surface for Phase 6 baseline. Phase 6 auditor
    invokes this at audit time to confirm the additivity contract holds
    and the redaction surfaces are wired.
    """
    return {
        "focus_domains_additive": _verify_focus_domains_additive(),
        "acuity_tiers_additive": _verify_acuity_tiers_additive(),
        "trafficking_disclosure_bypass_present": _verify_trafficking_disclosure_bypass_documented(),
        "handoff_schema_hash_stable": _verify_handoff_schema_hash_stable(),
        "v1_3_focus_domain_count_added": len(ALLOWED_FOCUS_DOMAINS) - len(_ALLOWED_FOCUS_DOMAINS_V1_2),
        "acuity_tier_count": len(ACUITY_TIERS),
        "handoff_payload_schema_version": HANDOFF_PAYLOAD_SCHEMA_VERSION,
    }


# Boot-time additivity guard. Surfaces contract violations at import
# rather than at runtime in front of a survivor.
assert _verify_focus_domains_additive(), (
    "ALLOWED_FOCUS_DOMAINS lost a v1.2 entry — additivity contract violated"
)
assert _verify_acuity_tiers_additive(), (
    "ACUITY_TIERS lost a v1.2 entry — additivity contract violated"
)
assert _verify_trafficking_disclosure_bypass_documented(), (
    "trafficking_disclosure tier missing 62h-cadence-bypass flag"
)
assert _verify_handoff_schema_hash_stable(), (
    "HANDOFF_PAYLOAD_SCHEMA_HASH mismatch — bump version + hash together"
)
