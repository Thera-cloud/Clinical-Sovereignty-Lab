-- LN7 Close Sentinel — versioned percent registry + digest log.
-- QUANTUM-CRYSTAL-ARCH
-- Constitution: sentinel is read-only for system state; writes only its own
-- digest/envelope rows. Formula changes are dated registry decisions only.

CREATE TABLE IF NOT EXISTS ln7_close_item_registry (
    item_id           TEXT PRIMARY KEY,
    tier              TEXT NOT NULL CHECK (tier IN ('CLOSE', 'CRANK', 'HUMAN')),
    title             TEXT NOT NULL,
    owner             TEXT NOT NULL CHECK (
        owner IN ('queens', 'cursor', 'ceo', 'clinician', 'calendar', 'external')
    ),
    weight            NUMERIC(6, 3) NOT NULL DEFAULT 1.0,
    formula_version   INT NOT NULL DEFAULT 1,
    formula_kind      TEXT NOT NULL,
    formula_params    JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_uri      TEXT,
    decided_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decision_note     TEXT,
    active            BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS ln7_close_digest_snapshots (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    day_index         INT NOT NULL,
    overall_pct       NUMERIC(6, 2),
    digest_text       TEXT NOT NULL,
    items_json        JSONB NOT NULL DEFAULT '[]'::jsonb,
    blocked_json      JSONB NOT NULL DEFAULT '[]'::jsonb,
    alerts_json       JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_refs     JSONB NOT NULL DEFAULT '[]'::jsonb,
    yellow_verify     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ln7_close_digest_created
    ON ln7_close_digest_snapshots (created_at DESC);

INSERT INTO ln7_feature_flags (key, enabled, notes) VALUES
    (
      'LN7_CLOSE_SENTINEL_ENABLED',
      FALSE,
      'Close sentinel daily digest — read-only reporter; never advances state'
    )
ON CONFLICT (key) DO NOTHING;

-- Seed formulas (frozen at ship). Pilot-path double weight: #5,#6,#7,#8,#17.
INSERT INTO ln7_close_item_registry
  (item_id, tier, title, owner, weight, formula_kind, formula_params, evidence_uri, decision_note)
VALUES
  ('#1', 'CRANK', 'v7 held-out kappa', 'clinician', 1.0, 'kappa_v7_milestones',
   '{"stems_authored":30,"scored":60,"v7_frozen":80,"kappa_run":100,"screener_permanent_branch":100}'::jsonb,
   'evidence:six_quotient_judge_kappa_evidence;docs/ln7/TRUST_LEDGER.md#Entry-40',
   '2026-08-07 ship: CRANK milestones; human gold unlocks progress'),
  ('#2', 'CRANK', 'Safety veto misses = 0', 'queens', 1.0, 'veto_zero_streak',
   '{}'::jsonb,
   'evidence_id:11;safety_veto_ok',
   'Monitored; any miss → 0 + alert'),
  ('#3', 'HUMAN', 'Inter-clinician subsample', 'external', 1.0, 'inter_clinician_na',
   '{"mid_band_low":0.55,"mid_band_high":0.70}'::jsonb,
   NULL,
   'N/A=100 unless latest kappa in mid-band'),
  ('#4', 'CRANK', 'Reliability recheck', 'ceo', 1.0, 'reliability_recheck',
   '{"tolerance_registered":40,"recheck_run":100}'::jsonb,
   'docs/ln7/TRUST_LEDGER.md#v7-freeze-log',
   'Tolerance must be pre-registered in v7 freeze log'),
  ('#5', 'CRANK', 'Floor FN = 0', 'cursor', 2.0, 'floor_fn',
   '{"gate_shipped":40,"replay_run":80,"fn_zero":100}'::jsonb,
   'docs/ln7/evidence/floor_replay_115_20260807.json',
   'Pilot-path double weight; address-gate before widened replay'),
  ('#6', 'CRANK', 'Floor FP ≤ threshold', 'ceo', 2.0, 'floor_fp',
   '{"threshold_set":30,"fix_shipped":60,"measured_pass":100}'::jsonb,
   'docs/ln7/evidence/floor_replay_115_20260807.json',
   'Pilot-path double weight; RED review sets threshold'),
  ('#7', 'HUMAN', 'Crisis GT n ≥ 30 + gold', 'clinician', 2.0, 'crisis_gt_human',
   '{"target_n":30}'::jsonb,
   NULL,
   'Pilot-path double weight; epistemic anchor — human only'),
  ('#8', 'CRANK', 'Enforce-with-alert observation week', 'ceo', 2.0, 'observation_week',
   '{"flip":30,"per_clean_day":10}'::jsonb,
   NULL,
   'Pilot-path double weight; flip is human/CEO'),
  ('#9', 'CLOSE', 'Data budget gates', 'queens', 1.0, 'data_budget',
   '{"per_domain":300,"total":1500}'::jsonb,
   'table:ln7_fuel_snapshots|ln7_coding_outcomes',
   'Queens-owned CLOSE'),
  ('#10', 'CLOSE', 'Canary / Gini / GGUF streak', 'queens', 1.0, 'canary_gini',
   '{"points_per_win":50,"wins_required":2}'::jsonb,
   'table:ln7_canary_state',
   'Instant 0 on held-out leak'),
  ('#11', 'CRANK', 'Living-pack dose-response verdict', 'queens', 1.0, 'pack_verdict',
   '{}'::jsonb,
   'docs/ln7/DOSE_RESPONSE_V2_PACK_ACCEPTANCE_BRIEF.md',
   'Backfill evidence_uri when grid evidence_id lands'),
  ('#12', 'CRANK', 'Perspective inversion → ~0', 'clinician', 1.0, 'inversion_census',
   '{"census_wired":40,"rate_pass":100,"stall_max_pct":10}'::jsonb,
   NULL,
   'Stall threshold pre-set ≤10%'),
  ('#13', 'HUMAN', 'CEO memos 2/2', 'ceo', 1.0, 'ceo_memos',
   '{"required":2}'::jsonb,
   NULL,
   'Signatures only — sentinel never advances'),
  ('#14a', 'CLOSE', 'Flag semantic audit', 'queens', 1.0, 'flag_audit',
   '{}'::jsonb,
   'flags:WEEKLY_LIVE,LN7_MUST_SEQUENCE_PACK_LIVE,DUAL_COO_MECHANICAL_PROMOTE,SIX_QUOTIENT_VETO_SCREEN',
   'Nightly scan; mismatch → 0 + alert'),
  ('#15', 'HUMAN', 'PRE6 fuel ≥ 300', 'ceo', 1.0, 'pre6_fuel',
   '{"target":300}'::jsonb,
   'table:ln7_fuel_snapshots',
   'Funded fuel; display count/300'),
  ('#16', 'CLOSE', 'CI green at every promote', 'queens', 1.0, 'ci_at_promote',
   '{}'::jsonb,
   'ci:pre-push|github actions',
   'Rolling AND across close-sequence promotes'),
  ('#17', 'HUMAN', 'Pilot pre-reg + first cohort', 'ceo', 2.0, 'pilot_human',
   '{}'::jsonb,
   NULL,
   'Pilot-path double weight; constitutionally human'),
  ('R4', 'CLOSE', 'Residual R4 DoD', 'queens', 0.5, 'residual_binary',
   '{}'::jsonb,
   NULL,
   'Equal-weighted residual; UNKNOWN until DoD evidence URI'),
  ('W', 'CLOSE', 'Residual W-series DoD', 'queens', 0.5, 'residual_binary',
   '{}'::jsonb,
   NULL,
   'Equal-weighted residual; UNKNOWN until DoD evidence URI')
ON CONFLICT (item_id) DO NOTHING;
