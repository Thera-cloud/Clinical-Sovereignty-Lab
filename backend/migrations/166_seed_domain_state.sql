-- Migration 166: Seed nevedal_domain_state with actual crystal counts
-- The ExaCrystallizationHook requires domain rows to exist before it can
-- track milestones or report real ExaFLOPS status. Without these rows,
-- get_exa_status() returns "not_initialized" and _check_milestones() exits early.

-- Seed coding domain with live crystal count (will be updated by nevedal_engine on each CEE)
INSERT INTO nevedal_domain_state (domain, C_emo, p_ent, gamma_env, crystal_count, updated_at)
VALUES (
    'coding',
    0.0,
    0.0,
    0.80,
    (SELECT COUNT(*) FROM nate_intelligence_crystals WHERE scope != 'archived' AND superseded_by IS NULL),
    NOW()
)
ON CONFLICT (domain) DO UPDATE SET
    crystal_count = EXCLUDED.crystal_count,
    updated_at = NOW();

-- Seed general domain (used by voice calls and chat sessions)
INSERT INTO nevedal_domain_state (domain, C_emo, p_ent, gamma_env, crystal_count, updated_at)
VALUES (
    'general',
    0.0,
    0.0,
    0.80,
    (SELECT COUNT(*) FROM nate_intelligence_crystals WHERE scope != 'archived' AND superseded_by IS NULL),
    NOW()
)
ON CONFLICT (domain) DO UPDATE SET
    crystal_count = EXCLUDED.crystal_count,
    updated_at = NOW();

-- Seed clinical domain (used by therapy sessions)
INSERT INTO nevedal_domain_state (domain, C_emo, p_ent, gamma_env, crystal_count, updated_at)
VALUES (
    'clinical',
    0.0,
    0.0,
    0.80,
    (SELECT COUNT(*) FROM nate_intelligence_crystals WHERE domain = 'clinical' AND scope != 'archived' AND superseded_by IS NULL),
    NOW()
)
ON CONFLICT (domain) DO UPDATE SET
    crystal_count = EXCLUDED.crystal_count,
    updated_at = NOW();
