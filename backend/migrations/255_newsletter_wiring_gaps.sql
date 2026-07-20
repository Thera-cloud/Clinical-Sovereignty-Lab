-- Little Nate Dispatch — rating idempotency + duplicate guards
-- Additive only. QUANTUM-CRYSTAL-ARCH

-- One rating row per subscriber per issue (re-tap updates score)
CREATE UNIQUE INDEX IF NOT EXISTS uq_newsletter_feedback_issue_sub
    ON newsletter_feedback (issue_id, subscriber_id)
    WHERE subscriber_id IS NOT NULL;

-- One anonymous / library rating fingerprint per issue
CREATE UNIQUE INDEX IF NOT EXISTS uq_newsletter_feedback_issue_token
    ON newsletter_feedback (issue_id, rating_token_hash)
    WHERE rating_token_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_newsletter_issues_content_hash
    ON newsletter_issues (content_hash)
    WHERE content_hash IS NOT NULL
      AND status IN ('draft', 'in_review', 'approved', 'sent');

CREATE INDEX IF NOT EXISTS idx_newsletter_issues_open_week
    ON newsletter_issues (created_at DESC)
    WHERE status IN (
        'draft', 'researching', 'composing', 'critiquing',
        'in_review', 'approved'
    );
