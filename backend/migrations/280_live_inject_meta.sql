-- Capability-track inject telemetry (crisis classifier + guide slot IDs).
-- Additive only. Does not alter judge-track columns.

ALTER TABLE six_quotient_human_gold
  ADD COLUMN IF NOT EXISTS live_inject_meta JSONB;

COMMENT ON COLUMN six_quotient_human_gold.live_inject_meta IS
  'Live-stack generation trace: crisis_class_fired, guide_ids/classes, audit, pre_fix snapshot.';
