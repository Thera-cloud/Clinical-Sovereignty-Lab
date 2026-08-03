-- Quartet dose-response v2 condition labels (must-sequence pack format hypothesis).
-- Additive: expands CHECK on condition_label; does not alter v1 rows.

ALTER TABLE quartet_dose_response_queue
  DROP CONSTRAINT IF EXISTS quartet_dose_response_queue_condition_label_check;

ALTER TABLE quartet_dose_response_queue
  ADD CONSTRAINT quartet_dose_response_queue_condition_label_check
  CHECK (condition_label IN (
    'before_no_affinity',
    'after_affinity_fix',
    'before_compound_must',
    'after_must_sequence_pack'
  ));

COMMENT ON COLUMN quartet_dose_response_queue.condition_label IS
  'v1: before_no_affinity|after_affinity_fix. '
  'v2: before_compound_must (affinity+compound MUST baseline) | '
  'after_must_sequence_pack (same path with LN7_MUST_SEQUENCE_PACK_LIVE).';
