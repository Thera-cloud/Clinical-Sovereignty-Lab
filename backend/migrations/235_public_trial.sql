-- Migration 235: Public Trial Funnel (Phase 1-4)
-- Adds bridge-trial columns to public_summon_usage, jailbreak/misuse review
-- table, email-capture lead table, TRIAL_FREE upgrade audit column, and the
-- funnel analytics view.

ALTER TABLE public_summon_usage ADD COLUMN IF NOT EXISTS turns_used INT DEFAULT 0;
ALTER TABLE public_summon_usage ADD COLUMN IF NOT EXISTS trial_history JSONB DEFAULT '[]';
ALTER TABLE public_summon_usage ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ;
ALTER TABLE public_summon_usage ADD COLUMN IF NOT EXISTS trial_started_at TIMESTAMPTZ;
ALTER TABLE public_summon_usage ADD COLUMN IF NOT EXISTS gated_at TIMESTAMPTZ;
ALTER TABLE public_summon_usage ADD COLUMN IF NOT EXISTS converted_at TIMESTAMPTZ;
ALTER TABLE public_summon_usage ADD COLUMN IF NOT EXISTS converted BOOLEAN DEFAULT FALSE;
ALTER TABLE public_summon_usage ADD COLUMN IF NOT EXISTS converted_username VARCHAR(255);

-- Gap 1 + row-identity fix: device_uuid_hash (UUID-only) is the trial row's actual
-- identity, not device_fingerprint (the ip|ua composite). UNIQUE (not plain) index:
-- public_trial_start upserts ON CONFLICT (device_uuid_hash), so turns_used/trial_history
-- live on exactly one row per device regardless of IP/UA drift across the trial session,
-- and Phase 3's conversion UPDATE ... WHERE device_uuid_hash=$1 can only ever match one
-- row (no fragmented trial_history across duplicate rows). device_fingerprint stays on
-- the row purely as the latest-seen abuse-analytics value; it is NEVER a lookup key.
ALTER TABLE public_summon_usage ADD COLUMN IF NOT EXISTS device_uuid_hash VARCHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS idx_public_summon_usage_device_uuid_hash ON public_summon_usage(device_uuid_hash) WHERE device_uuid_hash IS NOT NULL;
-- Do NOT backfill ip_address; new trial code paths omit ip writes

-- P0.1 jailbreak/misuse review table (referenced below; created here so migration
-- 235 is the single source for every new trial-related schema object)
CREATE TABLE IF NOT EXISTS public_trial_flagged_turns (
  id BIGSERIAL PRIMARY KEY,
  fp_hash VARCHAR(64) NOT NULL,
  direction VARCHAR(8) NOT NULL,   -- 'in' | 'out'
  text TEXT,                        -- purged to NULL after 30 days, see retention
  reason TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_public_trial_flagged_turns_created_at ON public_trial_flagged_turns(created_at);

-- Email-capture cross-device conversion path (closes the remaining merge gap
-- for desktop->phone, delayed-organic, incognito/cleared-storage journeys —
-- see "Realistic merge coverage" note in Phase 3). Token is the identity that
-- travels with the person, not the device.
CREATE TABLE IF NOT EXISTS public_trial_leads (
  id BIGSERIAL PRIMARY KEY,
  fp_hash VARCHAR(64) NOT NULL,            -- abuse/lookup reference only
  device_uuid_hash VARCHAR(64) NOT NULL,   -- same key Phase 3 conversion uses; captured once, reused for token lookup
  email VARCHAR(255),                      -- purged to NULL 45 days after capture regardless of outcome, see retention (nullable for that reason)
  token_hash VARCHAR(64) NOT NULL,         -- sha256(raw_token); raw token exists ONLY in the emailed URL, never stored
  consent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL,         -- created_at + 30 days; expired tokens fail merge gracefully (see signup-never-fail rule)
  email_sent_at TIMESTAMPTZ,
  follow_up_sent_at TIMESTAMPTZ,           -- set at most once; NULL means eligible for the single re-engagement email
  converted BOOLEAN NOT NULL DEFAULT FALSE,
  converted_username VARCHAR(255),
  converted_at TIMESTAMPTZ,
  unsubscribed_at TIMESTAMPTZ              -- honored by both the first email and the follow-up
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_public_trial_leads_token_hash ON public_trial_leads(token_hash);
CREATE INDEX IF NOT EXISTS idx_public_trial_leads_fp_hash ON public_trial_leads(fp_hash);
CREATE INDEX IF NOT EXISTS idx_public_trial_leads_followup ON public_trial_leads(converted, unsubscribed_at, email_sent_at, follow_up_sent_at);

-- Phase 3.5: audit trail only for TRIAL_FREE -> card-based TRIAL upgrades.
-- Never read for gating logic; registration_type/token_balance/trial_end on
-- the users row itself remain the source of truth for plan state.
ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_free_upgraded_at TIMESTAMPTZ;

-- Phase 4: minimal funnel analytics view.
CREATE OR REPLACE VIEW public_trial_funnel_daily AS
SELECT date_trunc('day', trial_started_at)::date AS day,
  count(*) FILTER (WHERE trial_started_at IS NOT NULL) AS starts,
  count(*) FILTER (WHERE turns_used >= 5) AS reached_5,
  count(*) FILTER (WHERE turns_used >= 15) AS reached_15,
  count(*) FILTER (WHERE gated_at IS NOT NULL) AS gated,
  count(*) FILTER (WHERE converted) AS converted
FROM public_summon_usage
GROUP BY 1;
