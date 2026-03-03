-- Migration 088: Performance indexes for company-scoped analytics
-- These indexes accelerate the Corporate Command analytics queries
-- (wellness, trends, coach-team, coach-roi) which join nevedal_metrics,
-- sessions, and client_metrics filtered by company employee IDs.

CREATE INDEX IF NOT EXISTS idx_nevedal_metrics_user_recorded
  ON nevedal_metrics(user_id, recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_sessions_coach_started
  ON sessions(coach_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_client_metrics_hardware
  ON client_metrics(hardware_id);

CREATE INDEX IF NOT EXISTS idx_users_company_role
  ON users(company_id, role) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_coach_assignments_company
  ON coach_assignments(entity_id) WHERE entity_type = 'company';
