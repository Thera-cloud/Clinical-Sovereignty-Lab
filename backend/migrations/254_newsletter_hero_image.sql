-- Little Nate Dispatch — topic hero images (Grok Imagine)
-- QUANTUM-CRYSTAL-ARCH — additive only

ALTER TABLE newsletter_issues
    ADD COLUMN IF NOT EXISTS hero_image_url TEXT;

ALTER TABLE newsletter_issues
    ADD COLUMN IF NOT EXISTS hero_image_r2_key TEXT;

ALTER TABLE newsletter_issues
    ADD COLUMN IF NOT EXISTS hero_image_prompt TEXT;

ALTER TABLE newsletter_issues
    ADD COLUMN IF NOT EXISTS hero_image_generated_at TIMESTAMPTZ;
