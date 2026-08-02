-- Migration 319: six_quotient_judge_role -- certification-vs-screener role
-- state per LLM judge. Additive only (new table).
--
-- Why (TRUST_LEDGER.md Entry 12, CEO flag decision 2026-08-02): grok-judge-v5
-- fails quality-scorer certification on its fresh held-out set (kappa=0.189,
-- n=40, evidence_id=9 -- see Entry 11) against the pre-registered 0.70
-- threshold, even though the disagreement is range-restricted and mostly
-- within-one, not incoherent. Its safety-veto component has never missed:
-- 0-for-49 across the two held-out runs (n=9 Entry 5 + n=40 Entry 11), and
-- 0 misses in all 7 on-gold certification-track runs (evidence ids 1-7 --
-- the same locked 50-item set re-scored across the v1->v4 prompt
-- iterations, not 7 independent samples). Decision: certify v5 ONLY as a
-- safety-veto screener,
-- explicitly labeled, with two conditions:
--   (1) auto-revert -- any future veto miss suspends the screener role
--       pending human review (this table + apply_veto_auto_revert() in
--       tier1_gold_evidence.py are the mechanism, not a manual reminder);
--   (2) every judge output must carry an uncertified-quality disclaimer so
--       no downstream surface (dashboards, six_quotient ability/theta
--       tracking, exports) quietly treats primary/accuracy/naturalness as
--       a certified signal (six_quotient_auto_judge.JUDGE_QUALITY_CERTIFIED
--       / JUDGE_ROLE constants, threaded into every _llm_judge() return).
--
-- This table is the durable, queryable record of that decision -- not a
-- comment. It is read by dashboards/audits and written by
-- tier1_gold_evidence.apply_veto_auto_revert() on every future
-- kappa-evidence insert.

CREATE TABLE IF NOT EXISTS six_quotient_judge_role (
    judge_id TEXT PRIMARY KEY,
    role TEXT NOT NULL DEFAULT 'unrated',
    quality_certified BOOLEAN NOT NULL DEFAULT false,
    veto_screener_certified BOOLEAN NOT NULL DEFAULT false,
    veto_check_total INT NOT NULL DEFAULT 0,
    veto_miss_total INT NOT NULL DEFAULT 0,
    suspended_at TIMESTAMPTZ,
    suspended_reason TEXT,
    last_evidence_id INT,
    decided_at TIMESTAMPTZ,
    decided_by TEXT,
    notes TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT six_quotient_judge_role_role_check
        CHECK (role IN ('unrated', 'quality_scorer', 'safety_veto_screener_only', 'suspended'))
);

COMMENT ON TABLE six_quotient_judge_role IS
  'Certification-vs-screener role state per judge_id. See TRUST_LEDGER.md '
  'Entry 12. role=safety_veto_screener_only + quality_certified=false means '
  'the judge may flag candidate safety failures for human review but its '
  'primary/accuracy/naturalness scalars are NOT a certified quality signal. '
  'role=suspended means an auto-revert fired on a veto miss -- do not use '
  'for screening until manually reviewed and reset.';

-- Seed grok-judge-v5's decision (TRUST_LEDGER Entry 12, 2026-08-02 CEO call):
-- safety-veto screener only, not a certified quality scorer.
INSERT INTO six_quotient_judge_role
    (judge_id, role, quality_certified, veto_screener_certified,
     veto_check_total, veto_miss_total, last_evidence_id, decided_at,
     decided_by, notes)
VALUES
    ('grok-judge-v5', 'safety_veto_screener_only', false, true,
     49, 0, 9, now(), 'CEO',
     'Fresh held-out kappa=0.189 (n=40, evidence_id=9) fails the '
     'pre-registered 0.70 quality threshold -- range-restricted (21/40 '
     'exact, 40/40 within-1, mean signed delta +0.075) but the threshold '
     'was pre-registered precisely so the number could not be argued '
     'past; v5 is not a quality scorer. Safety veto 0-for-49 across both '
     'held-out runs (n=9 + n=40) and 0 misses across all 7 on-gold '
     'certification-track runs; that component has genuinely generalized. '
     'v6 path (not started): full-range calibration -- score locked '
     'canonicals as 3-anchors and distractors as 0-anchors (the judge has '
     'never seen a 3 in its scored corpus), grid-then-scalars protocol so '
     'both raters run one instrument, revise with a rationale log, hold '
     'the fresh held-out for dose-response v2 rows (do not re-touch this '
     'n=40 set). See TRUST_LEDGER.md Entry 12.')
ON CONFLICT (judge_id) DO NOTHING;
