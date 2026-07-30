-- 304_ln7_backfill_authored_license.sql
-- G4 follow-up fix: 3 pre-existing "authored" packs (asyncpg_cast, catch_all_routes,
-- env_redis_prefix) were seeded before the FIRST-PARTY SPDX convention existed and have
-- an empty spdx_license. license_allowed_for_training() rejects empty/NULL licenses by
-- design, so passing outcomes on these packs can never promote to ln7_learning_artifacts.
--
-- These are first-party authored fixtures (same origin/trust level as the 15 authored
-- packs added in migration 296, which already carry FIRST-PARTY). Backfilling is safe.
--
-- Deliberately scoped to source='authored' only. Never touch source='mined' — those
-- packs have unknown provenance/license and must stay excluded from training by default.

UPDATE ln7_tasks
SET spdx_license = 'FIRST-PARTY'
WHERE source = 'authored'
  AND (spdx_license IS NULL OR spdx_license = '');
