# Little Nate Dispatch

Weekly staged newsletter: topic → research (year ≥ 2024) → draft → critique → human `in_review` → approve → send → Story Library → learn +72h.

## Feature flags

| Env | Default | Purpose |
|---|---|---|
| `ENABLE_NEWSLETTER_AGENT` | false | Start 30-min orchestrator (GREEN only; skipped when `IS_CLONE`) |
| `ENABLE_NEWSLETTER_WARM_LEADS` | false | Mine trial/users/social for invite → double opt-in |
| `ENABLE_NEWSLETTER_HIVE` | false | Register Queen/Worker task kinds on CLI bus |
| `ENABLE_TRIAL_LIBRARY_EDITORIAL` | false | Allow editorial-only Library recall on 20Q (never generic global) |
| `NEWSLETTER_ALLOW_OPEN_SUBSCRIBE` | false | Dev: skip Turnstile on subscribe |
| `NEWSLETTER_TOKEN_SALT` | nate-dispatch | Confirm / rate / unsub token hashing |
| `NEWSLETTER_PUBLIC_BASE` | app.sovereignsanctuary.net | Library links |
| `API_PUBLIC_BASE` | api.sovereignsanctuary.net | Rate / unsub / confirm links |
| `NEWSLETTER_PHYSICAL_ADDRESS` | Stafford TX | CAN-SPAM footer |

## Hard locks

- No cold email without double opt-in confirm
- Sends only after human approve (`status=approved`)
- Clinical transcripts never feed topic engine raw
- Symbolic marketing rules never inject into therapy prompts
- Library cite only when recall hits; never invent a Dispatch issue
- SendGrid events with `custom_args.channel=newsletter` update newsletter ledger only (not prospects)

## Surfaces

- Public API: `/api/newsletter/*`
- Admin API: `/api/newsletter/admin/*` (`require_admin`)
- Story Library shell: `dashboard/nate_story_library.html`
- Per-issue static: `dashboard/library/{slug}.html`
- Trust auditor: `NewsletterAuditor` (10 checks, stagger 298s, baseline `newsletter_check_count`)

## Migration

`backend/migrations/252_little_nate_dispatch.sql`

## Deploy note

BLUE-only until migration applied on GREEN and `ENABLE_NEWSLETTER_AGENT=true` set. Do not enable on clone (`IS_CLONE`).
