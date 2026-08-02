-- Migration 321: widen principal_review_library.source_kind CHECK to admit
-- 'live_scored' -- required by the harvest-notes endpoint (TRUST_LEDGER.md
-- Entry 18).
--
-- Additive in effect: the existing 6 allowed values (gold_scored,
-- coach_dojo, principal_authored, generated_pair, night_school, sandbox)
-- from migration 274 are preserved verbatim; only 'live_scored' is added.
-- Postgres has no ALTER CONSTRAINT to append a value, so this drops and
-- recreates the CHECK -- no data is touched, no existing row can violate
-- the new (strictly wider) constraint.
--
-- Why: POST /api/admin/principal-review/gold/live-track/harvest-notes
-- inserts principal_review_library rows with source_kind='live_scored' to
-- distinguish live-track (capability-session) harvested notes from
-- judge-track 'gold_scored' notes, so dedup lookups
-- (WHERE source_kind = 'gold_scored' AND source_ref = ...) never collide
-- across the two provenances. Discovered via a live 500
-- (CheckViolationError) on first real invocation, 2026-08-02 -- this
-- migration was not anticipated in Entry 18's original write-up and is
-- logged there as a same-day follow-up, not a separate finding.

ALTER TABLE principal_review_library
  DROP CONSTRAINT IF EXISTS principal_review_library_source_chk;

ALTER TABLE principal_review_library
  ADD CONSTRAINT principal_review_library_source_chk
  CHECK (source_kind IN (
    'gold_scored',
    'coach_dojo',
    'principal_authored',
    'generated_pair',
    'night_school',
    'sandbox',
    'live_scored'
  ));
