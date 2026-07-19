-- Little Nate Dispatch gap fixes — additive only
-- QUANTUM-CRYSTAL-ARCH

ALTER TABLE newsletter_issues
    ADD COLUMN IF NOT EXISTS learned_at TIMESTAMPTZ;

ALTER TABLE newsletter_issues
    ADD COLUMN IF NOT EXISTS library_html_path TEXT;

ALTER TABLE newsletter_issues
    ADD COLUMN IF NOT EXISTS library_r2_key TEXT;

CREATE INDEX IF NOT EXISTS idx_newsletter_issues_learned
    ON newsletter_issues (learned_at)
    WHERE learned_at IS NULL AND status = 'sent';

UPDATE trust_baseline
SET parameter_value = jsonb_set(
    COALESCE(parameter_value, '{}'::jsonb),
    '{expected}',
    '12'
)
WHERE parameter_key = 'newsletter_check_count';
