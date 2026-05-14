-- Migration 219: TMC cycle_detections column alignment (Predictive Cycle Engine)
-- TMC._gather_signals selects is_first_break from cycle_detections; migration 129
-- created the table without this column (Case 3C / spec drift).

ALTER TABLE cycle_detections
ADD COLUMN IF NOT EXISTS is_first_break BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN cycle_detections.is_first_break IS
    'First detected cycle break for user/domain semantics; populated when writers emit it; TMC reads for first_time_pattern_break signal.';
