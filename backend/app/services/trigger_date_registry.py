"""
Sensitive Clinical Bridge — Trigger Date Registry (Gap 5)
==========================================================

Clinician-set significant dates carrying trauma loading: escape anniversaries,
first exploitation, legal outcomes, related deaths, custody outcomes, court
appearances, medical anniversaries.

On a matching date (±1 day UTC, with annual recurrence), the orchestrator:
  1. Shifts default register to `predictability_continuity` (Gap 4)
  2. Forces Thalamic Novelty Gate ON regardless of computed signal values
  3. Dispatches a pre-emptive coach alert at 00:00 UTC (scheduler hook)
  4. Proactively appends a resource block to the first warm message of the day
  5. Allows `nate_checkin_agent` ONE soft outreach regardless of safe_silence_mode

Authoritative spec: `docs/plan_backups/sensitive_clinical_bridge_v1.3.backup.2026-05-08-1402.plan.md`
  - Gap 5 (lines 534-577)
Schema: `backend/migrations/205_user_trigger_dates.sql`
Clinical authority: `docs/SENSITIVE_CLINICAL_BRIDGE_GUIDELINES_2026-05-08.md`

DESIGN INVARIANTS
-----------------
1. `notes_redacted` MUST pass the PII screen before insert. The migration
   declares the screen is the application's job — this module enforces it.
   On a hit we raise `PIIScreenViolation` (subclass of ValueError) carrying
   `pattern_matched` and `field_position` so the Phase 4 REST layer can
   surface a 422 with an actionable, clinician-friendly message instead of
   a raw stack trace. Public contract — do not downgrade to bare ValueError.
2. Match window is fixed at ±1 day UTC. Adjusting the window requires
   updating both this module AND the auditor's test fixtures.
3. Recurring matches compare (month, day) only — never year. The trigger
   date's year is preserved as the original event year for clinical context.
4. Inactive (`active=FALSE`) dates are excluded from all match queries. They
   are NEVER hard-deleted — clinicians may need to reactivate or audit history.
5. All write methods require `set_by_clinician_id` for audit traceability.
   Caller is responsible for verifying the actor has clinician authority.
6. False negatives are worse than false positives here — see Gap 5 plan note.
   When in doubt, lean toward matching (e.g., timezone edge cases).

INTEGRATION POINTS
------------------
- `sensitive_clinical_bridge.py` step 8 (Trigger date check) — calls
  `is_trigger_date_active_today(user_id)` and `find_active_matches(...)`.
- `coach_override_protocol.escalate_acuity(tier='trigger_date_proactive', ...)`
  — driven by daily scheduler iterating `find_all_matches_for_date(today)`.
- `cycle_detection_engine` — correlates `sensitive_bridge_log.event_type =
  'trigger_date_active'` events with downstream signal shifts.

NOT IN SCOPE FOR THIS MODULE
----------------------------
- The 00:00 UTC scheduler itself lives in Phase 4 (`coach_override_protocol`
  or `nate_checkin_agent` cycle). This module exposes the query primitives.
- Crystal-recall filtering (no Gap 6 embodiment_phase logic here).
- Audit log writes (orchestrator writes `trigger_date_active`, not us).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Module version — bump on schema or matching-logic mutation. Audited.
REGISTRY_VERSION = "1.0.0-2026-05-08"

# Match window in days (each side). Hard-coded per plan Gap 5.
MATCH_WINDOW_DAYS = 1

# CHECK constraint values from migration 205. Mirror here for input validation
# so we surface a clear error before round-tripping to Postgres.
VALID_DATE_TYPES = frozenset({
    "escape_anniversary",
    "first_exploitation",
    "legal_outcome",
    "related_death",
    "custody_outcome",
    "court_appearance",
    "medical_anniversary",
    "other",
})

VALID_SEVERITIES = frozenset({"low", "moderate", "high", "critical"})


# ---------------------------------------------------------------------------
# PII screen for notes_redacted
# ---------------------------------------------------------------------------

# Conservative patterns. False positives here block a clinician note from
# being stored — that's the correct trade-off; the alternative is a coach
# seeing PII the survivor never consented to share.
_PII_PATTERNS: Sequence[Tuple[str, "re.Pattern[str]"]] = (
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("ssn_no_dashes", re.compile(r"(?<!\d)\d{9}(?!\d)")),
    ("phone_us", re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # Common street-address shapes: "123 Main St", "4567 Oak Ave"
    (
        "street_address",
        re.compile(
            r"\b\d{1,6}\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+"
            r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Ln|Lane|Dr|Drive|Ct|Court|Pl|Place|Way|Pkwy|Hwy)\b"
        ),
    ),
)


class PIIScreenViolation(ValueError):
    """Raised when `notes_redacted` contains a PII pattern.

    Carries structured detail for the Phase 4 REST layer to map onto a 422
    response with an actionable message ("remove SSN from notes"). Subclass
    of ValueError so existing `except ValueError` paths still catch it; the
    REST layer should branch on `isinstance(e, PIIScreenViolation)` to access
    the structured fields.

    Attributes
    ----------
    pattern_matched
        Label of the pattern that fired (e.g., 'ssn', 'phone_us'). Stable
        across versions; safe to expose to the clinician portal.
    field_position
        Zero-based start index of the match in the offending string. Lets
        the portal underline the offending substring inline.
    field_name
        The model field name that failed the screen ('notes_redacted' here;
        kept as a parameter for forward compatibility with other PII-bearing
        fields added in later phases).
    """

    __slots__ = ("pattern_matched", "field_position", "field_name")

    def __init__(
        self,
        pattern_matched: str,
        field_position: int,
        field_name: str = "notes_redacted",
    ) -> None:
        self.pattern_matched = pattern_matched
        self.field_position = field_position
        self.field_name = field_name
        super().__init__(
            f"PII pattern '{pattern_matched}' detected in {field_name} "
            f"at position {field_position}. Sanitize before submission."
        )


def _screen_notes_for_pii(text: Optional[str]) -> Optional[Tuple[str, int]]:
    """Return (pattern_label, match_start_index) if PII detected, else None.

    Conservative on purpose; clinician notes for trigger dates should be
    sanitized at intake. Per Gap 5 spec: "notes_redacted MUST be sanitized;
    no event details that could re-traumatize on coach view."
    """
    if not text:
        return None
    for label, pattern in _PII_PATTERNS:
        match = pattern.search(text)
        if match:
            return (label, match.start())
    return None


# ---------------------------------------------------------------------------
# Domain dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TriggerDate:
    """Immutable view of a row in `user_trigger_dates`."""

    id: int
    user_id: str
    trigger_date: date
    date_type: str
    severity: str
    recurring_annually: bool
    notes_redacted: Optional[str]
    set_by_clinician_id: str
    set_at: datetime
    active: bool


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TriggerDateRegistry:
    """Async DB-backed registry for `user_trigger_dates`.

    Construct once with the asyncpg pool; safe to share across coroutines.
    All methods are async and acquire a connection per call. No internal
    caching — clinician edits propagate on next call.
    """

    def __init__(self, db_pool=None) -> None:
        self._db_pool = db_pool

    # ---- write path ----

    async def add_trigger_date(
        self,
        *,
        user_id: str,
        trigger_date: date,
        date_type: str,
        set_by_clinician_id: str,
        severity: str = "high",
        recurring_annually: bool = True,
        notes_redacted: Optional[str] = None,
    ) -> int:
        """Insert a trigger date and return its `id`.

        Raises
        ------
        ValueError
            If `date_type` or `severity` is outside the CHECK constraint set,
            if `notes_redacted` fails the PII screen, or if required IDs are
            empty.
        RuntimeError
            If `db_pool` is not configured.
        """
        if not self._db_pool:
            raise RuntimeError(
                "TriggerDateRegistry: db_pool not configured. "
                "Wire it via app_state at orchestrator construction."
            )
        if not user_id:
            raise ValueError("user_id is required")
        if not set_by_clinician_id:
            raise ValueError("set_by_clinician_id is required for audit")
        if date_type not in VALID_DATE_TYPES:
            raise ValueError(
                f"date_type {date_type!r} not in {sorted(VALID_DATE_TYPES)}"
            )
        if severity not in VALID_SEVERITIES:
            raise ValueError(
                f"severity {severity!r} not in {sorted(VALID_SEVERITIES)}"
            )

        pii_hit = _screen_notes_for_pii(notes_redacted)
        if pii_hit is not None:
            label, position = pii_hit
            # Typed exception carrying structured detail for the REST layer
            # (Phase 4) to render an actionable 422 response. Subclass of
            # ValueError, so legacy `except ValueError` still catches it.
            raise PIIScreenViolation(
                pattern_matched=label,
                field_position=position,
                field_name="notes_redacted",
            )

        async with self._db_pool.acquire() as conn:
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
                trigger_date,
                date_type,
                severity,
                recurring_annually,
                notes_redacted,
                set_by_clinician_id,
            )
        new_id = int(row["id"])
        logger.info(
            "trigger_date_registry: added id=%s user=%s type=%s severity=%s "
            "recurring=%s set_by=%s",
            new_id, user_id, date_type, severity, recurring_annually,
            set_by_clinician_id,
        )
        return new_id

    async def deactivate_trigger_date(
        self,
        *,
        trigger_date_id: int,
        deactivated_by_clinician_id: str,
    ) -> bool:
        """Soft-delete by setting `active=FALSE`. Returns True iff a row changed.

        Hard delete is intentionally NOT exposed — clinical history is
        retained for cycle-detection longitudinal analysis.
        """
        if not self._db_pool:
            raise RuntimeError("TriggerDateRegistry: db_pool not configured")
        if not deactivated_by_clinician_id:
            raise ValueError("deactivated_by_clinician_id is required for audit")

        async with self._db_pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE user_trigger_dates SET active = FALSE WHERE id = $1 AND active = TRUE",
                trigger_date_id,
            )
        # asyncpg returns "UPDATE n" — parse the count.
        try:
            changed = int(result.split()[-1])
        except (ValueError, IndexError):
            changed = 0
        if changed:
            logger.info(
                "trigger_date_registry: deactivated id=%s by=%s",
                trigger_date_id, deactivated_by_clinician_id,
            )
        return changed > 0

    # ---- read path ----

    async def list_user_trigger_dates(
        self,
        user_id: str,
        *,
        active_only: bool = True,
    ) -> List[TriggerDate]:
        """All trigger dates for a user, newest set_at first.

        Used by the clinician portal (Phase 5) to render the management UI.
        """
        if not self._db_pool:
            raise RuntimeError("TriggerDateRegistry: db_pool not configured")
        if not user_id:
            return []

        sql = """
            SELECT id, user_id, trigger_date, date_type, severity,
                   recurring_annually, notes_redacted, set_by_clinician_id,
                   set_at, active
              FROM user_trigger_dates
             WHERE user_id = $1
        """
        if active_only:
            sql += " AND active = TRUE"
        sql += " ORDER BY set_at DESC"

        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(sql, user_id)
        return [self._row_to_dataclass(r) for r in rows]

    async def find_active_matches(
        self,
        user_id: str,
        *,
        when: Optional[date] = None,
    ) -> List[TriggerDate]:
        """Active trigger dates for `user_id` matching `when` ±1 day UTC.

        Recurring entries match by (month, day); non-recurring entries match
        by absolute date in the window. Default `when` is today (UTC).

        Used by the orchestrator at evaluate_disclosure() step 8.
        """
        if not self._db_pool:
            raise RuntimeError("TriggerDateRegistry: db_pool not configured")
        if not user_id:
            return []

        target = when or _today_utc()
        window = _window_dates(target)

        # Two predicates ORed:
        #   recurring_annually=TRUE matches when (month,day) of trigger_date ∈
        #     {(m,d) for d in window}
        #   recurring_annually=FALSE matches when trigger_date ∈ window
        # Build the (month,day) predicate as repeated args.
        md_pairs = [(d.month, d.day) for d in window]
        # Flatten to ($2,$3,$4,$5,$6,$7) etc., paired up.
        md_predicate = " OR ".join(
            f"(EXTRACT(MONTH FROM trigger_date) = ${2 + i*2}::int "
            f"AND EXTRACT(DAY FROM trigger_date) = ${3 + i*2}::int)"
            for i in range(len(md_pairs))
        )
        params: List[object] = [user_id]
        for m, d in md_pairs:
            params.extend([m, d])

        # The non-recurring predicate uses the next two slots as range bounds.
        nonrecur_lo_idx = 2 + len(md_pairs) * 2
        nonrecur_hi_idx = nonrecur_lo_idx + 1
        params.append(window[0])
        params.append(window[-1])

        sql = f"""
            SELECT id, user_id, trigger_date, date_type, severity,
                   recurring_annually, notes_redacted, set_by_clinician_id,
                   set_at, active
              FROM user_trigger_dates
             WHERE active = TRUE
               AND user_id = $1
               AND (
                     (recurring_annually = TRUE AND ({md_predicate}))
                  OR (recurring_annually = FALSE
                      AND trigger_date BETWEEN ${nonrecur_lo_idx} AND ${nonrecur_hi_idx})
                   )
             ORDER BY severity DESC, set_at DESC
        """

        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [self._row_to_dataclass(r) for r in rows]

    async def is_trigger_date_active_today(
        self,
        user_id: str,
        *,
        when: Optional[date] = None,
    ) -> bool:
        """Convenience predicate for the orchestrator's per-disclosure path.

        Equivalent to `bool(await find_active_matches(user_id, when=when))`
        but does a `SELECT 1 ... LIMIT 1` for the hot path.
        """
        if not self._db_pool or not user_id:
            return False

        target = when or _today_utc()
        window = _window_dates(target)
        md_pairs = [(d.month, d.day) for d in window]
        md_predicate = " OR ".join(
            f"(EXTRACT(MONTH FROM trigger_date) = ${2 + i*2}::int "
            f"AND EXTRACT(DAY FROM trigger_date) = ${3 + i*2}::int)"
            for i in range(len(md_pairs))
        )
        params: List[object] = [user_id]
        for m, d in md_pairs:
            params.extend([m, d])
        nonrecur_lo_idx = 2 + len(md_pairs) * 2
        nonrecur_hi_idx = nonrecur_lo_idx + 1
        params.append(window[0])
        params.append(window[-1])

        sql = f"""
            SELECT 1
              FROM user_trigger_dates
             WHERE active = TRUE
               AND user_id = $1
               AND (
                     (recurring_annually = TRUE AND ({md_predicate}))
                  OR (recurring_annually = FALSE
                      AND trigger_date BETWEEN ${nonrecur_lo_idx} AND ${nonrecur_hi_idx})
                   )
             LIMIT 1
        """
        async with self._db_pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)
        return row is not None

    async def find_all_matches_for_date(
        self,
        when: Optional[date] = None,
    ) -> List[TriggerDate]:
        """ALL active matches across ALL users for `when` ±1 day UTC.

        Driver for the 00:00 UTC scheduler hook that fires
        `coach_override_protocol.escalate_acuity(tier='trigger_date_proactive')`.

        Returns rows ordered by user_id, then severity DESC. Caller is
        responsible for batching and per-user de-duplication.
        """
        if not self._db_pool:
            raise RuntimeError("TriggerDateRegistry: db_pool not configured")

        target = when or _today_utc()
        window = _window_dates(target)
        md_pairs = [(d.month, d.day) for d in window]
        md_predicate = " OR ".join(
            f"(EXTRACT(MONTH FROM trigger_date) = ${1 + i*2}::int "
            f"AND EXTRACT(DAY FROM trigger_date) = ${2 + i*2}::int)"
            for i in range(len(md_pairs))
        )
        params: List[object] = []
        for m, d in md_pairs:
            params.extend([m, d])
        nonrecur_lo_idx = 1 + len(md_pairs) * 2
        nonrecur_hi_idx = nonrecur_lo_idx + 1
        params.append(window[0])
        params.append(window[-1])

        sql = f"""
            SELECT id, user_id, trigger_date, date_type, severity,
                   recurring_annually, notes_redacted, set_by_clinician_id,
                   set_at, active
              FROM user_trigger_dates
             WHERE active = TRUE
               AND (
                     (recurring_annually = TRUE AND ({md_predicate}))
                  OR (recurring_annually = FALSE
                      AND trigger_date BETWEEN ${nonrecur_lo_idx} AND ${nonrecur_hi_idx})
                   )
             ORDER BY user_id, severity DESC, set_at DESC
        """
        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [self._row_to_dataclass(r) for r in rows]

    # ---- helpers ----

    @staticmethod
    def _row_to_dataclass(row) -> TriggerDate:
        return TriggerDate(
            id=int(row["id"]),
            user_id=row["user_id"],
            trigger_date=row["trigger_date"],
            date_type=row["date_type"],
            severity=row["severity"],
            recurring_annually=bool(row["recurring_annually"]),
            notes_redacted=row["notes_redacted"],
            set_by_clinician_id=row["set_by_clinician_id"],
            set_at=row["set_at"],
            active=bool(row["active"]),
        )


# ---------------------------------------------------------------------------
# Pure helpers (importable by tests + auditor without a DB pool)
# ---------------------------------------------------------------------------


def _today_utc() -> date:
    """Today as a UTC date. Centralized so tests can monkeypatch."""
    return datetime.now(tz=timezone.utc).date()


def _window_dates(center: date) -> Tuple[date, ...]:
    """Return the (center-1, center, center+1) date tuple."""
    from datetime import timedelta
    return tuple(
        center + timedelta(days=delta)
        for delta in range(-MATCH_WINDOW_DAYS, MATCH_WINDOW_DAYS + 1)
    )


def matches_recurring(
    trigger: date,
    target: Optional[date] = None,
    *,
    window_days: int = MATCH_WINDOW_DAYS,
) -> bool:
    """Pure predicate: does `trigger` (annually-recurring) match `target` ±window?

    Compares (month, day) only. Useful for tests and auditor coverage that
    don't want to spin up a DB.
    """
    target = target or _today_utc()
    from datetime import timedelta
    window = {
        (target + timedelta(days=delta)).timetuple()[1:3]
        for delta in range(-window_days, window_days + 1)
    }
    return (trigger.month, trigger.day) in window


# ---------------------------------------------------------------------------
# Auditor hooks (Phase 6 — sensitive_bridge_auditor.py)
# ---------------------------------------------------------------------------


def _auditor_self_check() -> dict:
    """Static facts the auditor maps to checks. Does NOT touch DB.

    Audited check IDs that consume this output:
      - trigger_date_registry_loaded
      - trigger_date_window_days_locked
      - trigger_date_pii_screen_present
    """
    return {
        "registry_version": REGISTRY_VERSION,
        "match_window_days": MATCH_WINDOW_DAYS,
        "valid_date_types": sorted(VALID_DATE_TYPES),
        "valid_severities": sorted(VALID_SEVERITIES),
        "pii_pattern_count": len(_PII_PATTERNS),
        "pii_pattern_labels": [label for label, _ in _PII_PATTERNS],
    }


__all__ = [
    "REGISTRY_VERSION",
    "MATCH_WINDOW_DAYS",
    "VALID_DATE_TYPES",
    "VALID_SEVERITIES",
    "TriggerDate",
    "TriggerDateRegistry",
    "PIIScreenViolation",
    "matches_recurring",
]
