-- Migration 234: Persist LinkedIn organization URN for company-page posting
-- Allows Little Nate to post to both personal profile and company pages.

ALTER TABLE skyeye_platform_tokens
    ADD COLUMN IF NOT EXISTS org_urn TEXT DEFAULT NULL;

COMMENT ON COLUMN skyeye_platform_tokens.org_urn IS
    'LinkedIn organization URN (urn:li:organization:XXXX) for company-page posting. '
    'Populated automatically on OAuth callback when user admins a company page.';
