-- Migration 091: Normalize coach_hierarchy status values
-- 'accepted' (from admin REST) → 'active' (standard)

UPDATE coach_hierarchy SET status = 'active' WHERE status = 'accepted';
