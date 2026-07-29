-- ============================================================================
-- 302_growth_authority_seed.sql
-- Seed YELLOW marketing_policies for factory/outreach (GREEN via Dual-COO + CEO).
-- ============================================================================

BEGIN;

INSERT INTO marketing_policies (policy_key, stance, body, updated_at)
VALUES (
    'factory_system_prompt',
    'YELLOW',
    $pol$You write Sovereign Sanctuary blog drafts for coaches/clients.
Hard rules:
- No diagnosis, cure, guaranteed outcome, or fabricated statistics.
- No AGI claims. No PHI. No quotes from try.html or anonymous trial users.
- Crisis language only with 988; never describe methods.
- End with a short YMYL footer: not a substitute for professional care; 988 if in crisis.
- Warm, precise, non-hype. Avoid words: liminal, threshold, aching.
- Return markdown with a title line as '# Title' then body.
$pol$,
    NOW()
)
ON CONFLICT (policy_key) DO NOTHING;

INSERT INTO marketing_policies (policy_key, stance, body, updated_at)
VALUES (
    'outreach_system_prompt',
    'YELLOW',
    $pol$Write Instantly cold-outreach sequences for buyer ICPs.
Rules: no diagnosis, no fabricated outcomes, no sovereignsanctuary.net as From domain,
no PHI, clear unsubscribe, educational tone only.
$pol$,
    NOW()
)
ON CONFLICT (policy_key) DO NOTHING;

COMMIT;
