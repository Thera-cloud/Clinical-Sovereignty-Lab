# Little Nate Dispatch

Weekly staged newsletter: topic → research (year ≥ 2024) → draft → critique → human `in_review` → approve → send → Story Library → learn +72h.

## Feature flags

| Env | Default | Purpose |
|---|---|---|
| `ENABLE_NEWSLETTER_AGENT` | false | Weekly auto-compose orchestrator (GREEN only; skipped when `IS_CLONE`) |
| `ENABLE_NEWSLETTER_LEARNING` | true (default) | +72h learning loop + replicate sweep (starts even if compose off) |
| `ENABLE_NEWSLETTER_WARM_LEADS` | false | Mine trial/users + send double-opt-in invites |
| `ENABLE_NEWSLETTER_HIVE` | false | Queen/Worker patrol on CLI task kinds |
| `ENABLE_NEWSLETTER_LLM_DRAFT` | false | Optional inference-router compose (template fallback) |
| `ENABLE_NEWSLETTER_SMS` | true | SMS link to active subscribers with `phone_e164` |
| `ENABLE_NEWSLETTER_HERO_IMAGE` | true | Topic still: Grok Imagine → Gemini fallback (`XAI_*` and/or `GEMINI_API_KEY`) |
| `ENABLE_TRIAL_LIBRARY_EDITORIAL` | false | Editorial-only Library recall on 20Q (never generic global) |
| `NEWSLETTER_ALLOW_OPEN_SUBSCRIBE` | false | Dev: skip Turnstile on subscribe |
| `NEWSLETTER_TOKEN_SALT` | nate-dispatch | Confirm / rate / unsub token hashing (must match email + `/rate`) |
| `NEWSLETTER_PUBLIC_BASE` | app.sovereignsanctuary.net | Story Library shell host |
| `API_PUBLIC_BASE` | api.sovereignsanctuary.net | Rate / unsub / confirm / **HTML library pages** |
| `NEWSLETTER_PHYSICAL_ADDRESS` | Stafford TX | CAN-SPAM footer |

## Hard locks

- No cold email without double opt-in confirm
- Sends only after human approve (`status=approved`)
- Clinical transcripts never feed topic engine raw (signals from feedback/library/hive only)
- Symbolic marketing rules never inject into therapy prompts
- Library cite only when recall hits; never invent a Dispatch issue
- SendGrid events with `custom_args.channel=newsletter` update newsletter ledger only

## Surfaces

- Public API: `/api/newsletter/*`
- HTML issue pages: `GET /api/newsletter/library/{slug}/page` (no nginx static required)
- Admin API: `/api/newsletter/admin/*` (`require_admin`)
- Admin UI: `dashboard/newsletter_dispatch.html`
- Story Library shell: `dashboard/nate_story_library.html`
- Local archive: `$DATA_DIR/newsletter_library/` (writable) + R2/Azure via blob_storage
- Optional host sync: `bash scripts/sync_newsletter_library.sh`
- Trust auditor: `NewsletterAuditor` (12 checks, stagger 298s, `newsletter_check_count`)

## Migrations

- `252_little_nate_dispatch.sql` — core tables + baseline 10
- `253_newsletter_gap_fixes.sql` — `learned_at`, library paths, baseline → 12
- `254_newsletter_hero_image.sql` — `hero_image_*` columns for topic stills (Grok → Gemini)
- `255_newsletter_wiring_gaps.sql` — feedback uniqueness + open-issue indexes

## Wiring notes (post-gap fix)

- Email/library bodies render markdown links + headings; Sources block from `citations`
- `/rate` verifies subscriber or library token; idempotent per subscriber / IP+day
- SendGrid newsletter events join on `provider_message_id` **or** `custom_args.issue_id` / email
- Pipeline skips compose when an open issue exists this UTC week; never overwrites `sent`/`approved` slugs
- `POST /api/newsletter/admin/issues/reject-replicates` + agent sweep reject same-hash / same-day-topic clones
- Dispatch UI **Insights** tab: ratings, opens, library stats, force learning

## Deploy

```bash
# On GREEN after pull
docker exec -i nate_postgres psql -U nate_admin -d little_nate < backend/migrations/253_newsletter_gap_fixes.sql
# Ensure ENABLE_NEWSLETTER_AGENT=true in .env (not on clone)
bash scripts/safe_deploy.sh backend
# Bridge if bridge_server Story Library recall changed
bash scripts/safe_deploy.sh bridge
# Dashboard shells
rsync -av dashboard/nate_story_library.html dashboard/newsletter_dispatch.html \
  /var/www/sovereign-command/
rsync -av dashboard/nate_story_library.html /var/www/sovereignsanctuary-web/
bash scripts/sync_newsletter_library.sh   # optional static /library/ mirror
```
