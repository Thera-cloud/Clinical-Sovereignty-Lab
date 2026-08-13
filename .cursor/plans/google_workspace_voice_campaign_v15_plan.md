# Google Workspace Pairing + Voice Campaign Engine — Build Plan (v1.5.2)

**Source spec:** Unified Single-Push Spec v1.5 (2026-08-11)  
**Plan date:** 2026-08-12 · **Amended:** 2026-08-12 (v1.5.1 review + v1.5.2 pipeline gaps)  
**Release model:** One push, feature-flagged, one Queens GREEN gate  
**Repo reality baseline:** migration 183 (Google Calendar), 068 (coach hierarchy), 296 (`marketing_content`), unified `users` + `coaching_sessions`

**v1.5.1 deltas:** envelope encryption on write path; single-consent held until verification; canonical `hardware_id`; audio tickets; golden set week one; AC1–AC33 full bar.

**v1.5.2 deltas:** split coach vs client Google OAuth apps; bounded ciphertext inventory; per-coach LinkedIn token; Zoom stays + Meet on Google event; `hardware_id` UNIQUE; Gmail History poll; `client_envelope_cipher`; consent_records; AC27 ops track; Day N = seam order.

---

## 0. Binding rewrite rules (before any DDL)

Do **not** implement the spec DDL literally. Spec names express intent; production identity is:

| Spec | Production |
|------|------------|
| `coaches` / `clients` | `users` (`role` = COACH / CLIENT) |
| Coach/client FK on **all new tables** | **`users.hardware_id` VARCHAR** — canonical (see §0.1) |
| `sessions` | `coaching_sessions` (`session_id` VARCHAR) |
| `google_credentials` | **Extend** `google_calendar_connection` (183); TokenCipher TEXT encryption |
| `calendar_links` | **Already on** `coaching_sessions` (`google_event_id`, `sync_state`, …) |
| `supervision_links` | **Map to** `coach_hierarchy` (068; already `hardware_id`) |
| `supervision_hours` | **Map to** `supervised_hours` |
| `marketing_campaigns` | **New** coach-scoped campaign table (do not overload SkyEye `campaigns` / `storytelling_campaigns`) |
| `marketing_content` | **Extend** existing table (296) — widen CHECKs + columns |
| Crystal `domain` | Keep 7 canonical values; additive allowlist only (see §0.2). Add `source_type` column. |

Queens RED if any workstream creates a parallel `coaches`/`clients` table, stores Google tokens outside TokenCipher + connection table, wraps DEKs with TokenCipher, expands 183 scopes onto clients, falls back to SkyEye LinkedIn, or uses a mixed identity key on new tables.

### 0.1 Canonical identifier (binding)

**All new tables** key coach and client as `hardware_id VARCHAR NOT NULL` (same string as `coaching_sessions.coach_id` / `client_id` and `coach_hierarchy.master_coach_id` / `assistant_id`).

`effective_scope(coach_hardware_id)` takes **only** this key. No username overloads on new FKs.

**Legacy mapping view** (ships in the same migration):

```sql
CREATE VIEW workspace_identity AS
SELECT hardware_id,
       username,
       id AS user_uuid,
       role
FROM users;
```

`google_calendar_connection.user_id` stays **username** (183). `googleSvc` methods accept `hardware_id` and resolve username via `workspace_identity` before calling 183 code. Never store username on new campaign/draft/task/library/clinical tables.

**UNIQUE required:** `users.hardware_id` is not unique today (unique is `username`). Same migration: `CREATE UNIQUE INDEX IF NOT EXISTS uq_users_hardware_id ON users (hardware_id) WHERE hardware_id IS NOT NULL AND hardware_id <> '';` Dedup before index if any collisions. New FKs are not keys without this.

### 0.2 Crystal domain (NG15 verified)

`nate_intelligence_crystals.domain` is `VARCHAR(50)` **with no DB CHECK** (`119_nate_intelligence_crystals.sql`). App allowlist (crystallizer + `.cursor/rules/crystal-intelligence-integrity.mdc`) is exactly seven: `clinical`, `coaching`, `marketing`, `research`, `culture`, `defense`, `general`.

| Spec §12.3 name | Production key |
|-----------------|----------------|
| therapeutic | **`clinical`** (do not rename) |
| marketing | **`marketing`** (already canonical — budgets can key here) |
| product | **additive** `product` |
| coding | **additive** `coding` |
| operational | **additive** `operational` |

NG15 stands: do not replace or rename the seven. Additive allowlist expansion (`product`, `coding`, `operational`) **must** update crystallizer, all 6 domain agents, analytics API, and `crystal-intelligence-integrity.mdc` in the same commit. Per-domain crystal budgets (§12.3b) key on this expanded allowlist; `marketing` volume cannot crowd `clinical`.

### 0.3 Two Google OAuth apps (binding — do not share scopes)

183 already OAuths **CLIENT and COACH** through one client ID and calendar-only `GOOGLE_SCOPES` (`google_calendar_client.py`). Expanding that string to Gmail+Drive would put Gmail on **client** Connect Calendar. Forbidden.

| App | Env | Who | Scopes |
|-----|-----|-----|--------|
| Calendar (keep 183) | `GOOGLE_CLIENT_ID` / `SECRET` / `REDIRECT_URI` | CLIENT + existing calendar-only coaches | calendar.events, calendar.readonly, calendar.freebusy, openid, email |
| Coach Workspace (new) | `GOOGLE_WS_CLIENT_ID` / `SECRET` / `REDIRECT_URI` | COACH only, after O9 | calendar.* + gmail.compose + gmail.readonly + drive.file; `incremental=false`; one grant = Vault-consent |

Coach Workspace tokens live on `google_calendar_connection` **or** a sibling row keyed by username with `workspace_features`; never mix refresh tokens across apps. Client calendar connect **never** requests Gmail/Drive.

### 0.4 Ciphertext inventory (bounded — Correction 1 still holds)

Envelope encryption is **on for listed stores only**. Do **not** encrypt `coaching_sessions.client_name`, schedule list columns, or bridge calendar merge payloads — those stay plaintext + `vault_sync` redaction (initials). Encrypting them without a decrypt layer in every reader breaks Coach Schedule.

| Encrypted under client DEK | Not encrypted (redact / scope instead) |
|----------------------------|----------------------------------------|
| `email_drafts` body (Vault-resident) | `coaching_sessions` display fields used by Schedule |
| R2 voice recordings + transcripts for that client | `google_event_id`, sync_state, zoom ids |
| Drive Doc/Sheet **bytes** for vault_sync=TRUE clients | Campaign/marketing copy (coach-scoped, not client DEK) |
| `client_data_keys` wrapped DEK | Coach Voice Profile, `marketing_content` |

Module: **`client_envelope_cipher`** — only DEK unwrap. **Do not** reuse `TokenCipher` / `SKYEYE_TOKEN_ENCRYPTION_KEY` (`pii_cipher.py` already shares that key). AC10 remains: only WS-A decrypts **Google** refresh tokens.

### 0.5 LinkedIn publisher (binding)

Coach campaigns publish with the **coach’s** LinkedIn token, not SkyEye/Nate’s. New or extend per-coach LinkedIn OAuth (distinct from `skyeye_platform_tokens` platform=`linkedin`). If the coach has no LinkedIn connection, review-queue items stay `approved`/`scheduled` and do not publish; UI: “Connect LinkedIn”. No silent fallback to Nate’s page.

### 0.6 Zoom and Meet (binding)

**Both.** `ENABLE_ZOOM` session join (Start Zoom, `zoom_meeting_id`) is unchanged. Sanctuary→Google upsert **also** sets `conferenceData` Meet (AC11). Calendar event may show Meet; Coach Command session card still shows Zoom. Do not delete Zoom because Meet exists. Clients are never Google attendees (B4); Meet link on a vault_sync=FALSE event carries no client PII in conference metadata.

---

## 1. Open items — resolutions (flagged for Queens)

| ID | Resolution |
|----|------------|
| **O1 Gmail scope** | Use `gmail.readonly` (not `gmail.metadata`). Compose = `gmail.compose`; never `gmail.send`. **Reply ingest = Gmail History poll** (183-style), not `users.watch`+Pub/Sub in this push. Watch is a later ticket; AC4 5-minute window via ≤5 min poll. |
| **O2 Draft sent/discarded** | Best-effort via Gmail History API; status may stay `pushed` if undetectable — UI labels “In Gmail (status unknown)”. |
| **O3 Schema** | Resolved in §0 + §4. |
| **O4 Chat** | Spec-resolved: Chat webhook primary; mobile push fallback. |
| **O5 Studio secret UX** | Coach Settings → Integrations → “Studio webhook secret” (show-once + rotate). Hash-only verify + rotate; no plaintext recovery. |
| **O6 Retention matrix** | **Counsel gate** — ship schema + configurable JSON; values placeholder until counsel sign-off. **`ENABLE_CLINICAL_ERASURE` (request UI + key destruction) OFF until O6 filled.** Envelope encryption is **not** gated on O6 — see §1.1. |
| **O7 EU residency** | **Counsel gate** — default SCC posture; no region pin in v1.5 push unless already decided. Does **not** gate envelope encryption. |
| **O8 On-call** | Per-pod schedule table + Twilio SMS for crisis class only; config stub OK if Chat escalation works. |
| **O9 Google verification** | **Day-1 parallel track.** Decision **(a)** on **`GOOGLE_WS_*` only**. 183 client-calendar OAuth stays live and calendar-only. |
| **O10 Integration order** | §3 = **seam order**, not elapsed calendar days. CASA + golden set + AC33 will outlast “Day 9”. |

### 1.1 Envelope encryption vs erasure workflow (Correction 1)

These are **not** the same gate.

| Piece | Ships in the push? | Flag |
|-------|--------------------|------|
| Per-client DEK + envelope encryption on **every new write** of client-identifiable content (DB fields, R2 objects, draft bodies) | **YES — write-path, day 1 of data** | none (always on for new writes) |
| Keystore + Ring 2/3 encrypted key mirrors | **YES** | none |
| Erasure **request UI**, identity-verify flow, legal-hold check, Admin approval, **key destruction** | Schema yes; **workflow OFF** | `ENABLE_CLINICAL_ERASURE` until O6/O7 |
| AC30 staging drill (destroy test-client key; prove live/PITR/Ring2 unreadable; anonymized crystals persist) | **YES — staging, flag OFF** | n/a |

Counsel owns retention **values** and the **erasure request** workflow. Counsel does **not** own whether §0.4 stores are encrypted. Skipping that inventory is the retrofit trap. Session display columns are **intentionally** out of inventory (Schedule readers).

Existing pre-push rows outside §0.4: out of scope; backfill is a separate ticket.

### 1.2 OAuth consent — decision (a) (Correction 2)

**Decision: (a) hold coach-facing Google connect until the app is verified for the full scope set. One grant, `incremental=false`. The grant is the Vault-consent event (§5.A / P4 / §15.8).**

Rejected: L1 calendar-only coach-facing connect followed by L2 Gmail re-consent. Incremental re-consent is the worst-converting OAuth UX and splits the Vault-consent event.

**What still happens before CASA clears:**

- Full scope set is requested in **test-user / unverified** mode (Google Cloud test users, internal coaches only).
- Calendar, Meet, busy, drafts, Drive are built and Queens-tested against those test users.
- Coach-facing Settings “Connect Google Workspace” stays hidden (`ENABLE_WS_OAUTH` OFF in production) until verification + CASA on **`GOOGLE_WS_*`**.
- Client **Connect Calendar** (183) stays available; calendar-only scopes.
- NG13: do not incremental-scope Gmail onto the 183 client ID.

**Override:** operator may flip to **(b)** in writing: one-time re-consent for an early calendar cohort, with `consent_records` versioned per §15.8 and an explicit re-consent ticket. Until that override, (a) is binding.

---

## 2. Feature flags (env + optional `app_settings` mirror)

Pattern: `ENABLE_*` env (growth/LN7 style), default OFF in prod until Queens GREEN, then ON.

| Flag | Workstream |
|------|------------|
| `ENABLE_WS_OAUTH` | A — coach-facing **Workspace** connect (`GOOGLE_WS_*`); OFF in prod until O9 |
| `ENABLE_WS_CALENDAR_SYNC` | A — 183 client+coach calendar poll/push (unchanged app) |
| `ENABLE_COACH_LINKEDIN` | C — per-coach LinkedIn publish; no SkyEye fallback |
| `ENABLE_WS_GMAIL_DRAFTS` | A+B |
| `ENABLE_WS_DRIVE_DELIVERY` | A |
| `ENABLE_VOICE_CAMPAIGN` | C |
| `ENABLE_CAMPAIGN_NUDGES` | C |
| `ENABLE_AUDIO_BRIEFS` | C / audio — Morning Audio Brief + shared TTS |
| `ENABLE_STUDIO_WEBHOOKS` | D |
| `ENABLE_PAGE_COMMENT_READS` | D optional — default OFF |
| `ENABLE_COACH_NEWSLETTER` | C §12 |
| `ENABLE_COACH_TASKS` | §13 |
| `ENABLE_SUPERVISION_VIEW` | §13 UX |
| `ENABLE_PRACTICE_LIBRARIES` | §14 |
| `ENABLE_CLINICAL_ERASURE` | §15 — request UI + key destruction only; OFF until O6 |
| `ENABLE_CRISIS_ESCALATION` | §15 |

Killing a flag = graceful “temporarily unavailable”; never drop queue rows. Killing `ENABLE_CLINICAL_ERASURE` must **not** disable envelope encryption on writes.

---

## 3. Integration order inside the single push (O10)

**Day N labels are seam order, not a 9-day calendar.** Queens does not treat “Day 9” as a deadline.

Wire and test seams in this order so risk surfaces early:

```
Week 1    H0  HUMAN: golden-set authorship starts (AC33) — master coaches + operator
          O9  Create GOOGLE_WS_* Cloud project; start CASA; leave 183 app as-is
Seam 0    K0  client_data_keys + client_envelope_cipher on §0.4 inventory only
Seam 0    A0  Freeze googleSvc; Workspace OAuth (test users, full scopes, separate client)
Seam 1    A1  Calendar upsert/remove + Meet conferenceData + vault_sync title rules (Zoom join unchanged)
Seam 2    A2  Free/busy into LN booking (B1); no tentative Google holds (B2)
          Bridge: prefer REST / bridge_handlers_v2 — 50-line cap on bridge_server.py
Seam 3    B0  email_drafts + createDraft + VaultBlocked
Seam 3    C0  Voice record → R2 → transcript → Voice Profile (no publish)
Seam 3    Au  audio_synthesis_service + morning_brief_composer
Seam 4    C1  Campaign generation → review queue
Seam 5    C2  Per-coach LinkedIn URN + post_nudges; SendGrid drip markers
Seam 5    Dr  docs_formatter + sheets_engagement_appender
Seam 5    A3  Gmail History poll → warm_reply + campaign_engagements (no Pub/Sub watch)
Seam 6    D0  Studio HMAC hooks (engagement idempotent first)
Seam 6    UI  Coach Command cards — Connect Workspace hidden in prod
Seam 7    §13 effective_scope(hardware_id); Supervision tab = active coach_hierarchy (no new role enum required)
Seam 7    §12 Newsletter + content_topics + source_type + additive domains
Seam 8    §14 Libraries (canonical R2)
Seam 8    §15 Credentials + crisis + injection; consent_records; erasure UI OFF; AC30 drill ON
Seam 9    Staging rehearsal AC1–AC33
Queens    GREEN bar = full AC1–AC33. AC27 = parallel ops track (does not block code GREEN if Ring2 drill scheduled).
```

**Hard seam tests (must pass before declaring push ready):**

1. A1→booking: ACCEPT creates Meet event; pending never creates event.  
2. B0 VaultBlocked: no Google call with client PII. Same leak test on **183 client calendar** upsert (title/attendees/description).  
3. C2→A3: SendGrid reply → engagement row + Gmail draft within 5m (staging).  
4. D0 bad HMAC → 401.  
5. Flag kill matrix: each flag OFF leaves others green; write-path encryption survives `ENABLE_CLINICAL_ERASURE=off`.  
6. AC30 staging: test-client key destroy → unreadable copies; crystals anonymized.

---

## 4. Migration map (one additive set — suggested filename `3xx_google_workspace_voice_campaign.sql`)

### 4.1 Extend Workspace connection (not new `google_credentials`)

```text
ALTER google_calendar_connection:
  + consent_recorded_at TIMESTAMPTZ
  + revoked_at TIMESTAMPTZ
  + chat_webhook_url TEXT
  + workspace_features JSONB
  + token_app TEXT  -- 'calendar_183' | 'workspace_ws'
  Keep: TokenCipher on access/refresh; user_id = username (legacy)
CREATE UNIQUE INDEX uq_users_hardware_id ...  -- §0.1
CREATE VIEW workspace_identity AS ...
```

Workspace OAuth uses `GOOGLE_WS_*`. 183 calendar OAuth keeps `GOOGLE_*`. Do not overwrite a calendar-only row with Workspace scopes.

### 4.2 Client Vault exposure (CLIENT rows; query by hardware_id)

```text
users columns (CLIENT role):
  vault_sync BOOLEAN DEFAULT false
  app_enabled BOOLEAN DEFAULT true
  relationship_class TEXT DEFAULT 'coaching'
  client_jurisdiction TEXT
```

Columns, not JSONB-only, for queryability. Backfill false.

### 4.3 Calendar watch (optional later)

This push keeps **5-min poll** (183 agent). `calendar_watch_channels` may ship empty/unused. Gmail: **History poll**, not Pub/Sub `users.watch`.

### 4.4 Drafts + engagements + campaigns

```text
email_drafts.coach_id / client_id     = hardware_id VARCHAR
coach_marketing_campaigns.coach_id    = hardware_id
campaign_engagements.coach_id         = hardware_id
post_nudges.content_id                = BIGINT  -- marketing_content.id is BIGSERIAL, not UUID
ALTER marketing_content:
  + campaign_id, post_urn, post_url, coach_id (hardware_id)
  DROP existing content_type CHECK; ADD CHECK including
    linkedin_post, drip_touch, newsletter_issue
  (DROP+ADD is the only PG way to widen CHECK — not a column drop)
```

### 4.5 Tasks / supervision gaps

```text
coach_client_tasks + task_progress     -- NOT ln7_tasks; assignee_id = hardware_id
care_plan_reviews, supervision_guidance, supervision_access_audit
-- reuse coach_hierarchy / supervised_hours
-- Supervision tab: active coach_hierarchy row = master; no users.role='master_coach' required
-- Optional later: profile_data.coach_grade Admin-gated (spec 13.2) — not launch-blocking
```

### 4.6 Libraries + clinical + envelope keys

```text
practice_templates, org_library
coach_credentials, legal_holds
consent_records (version, document_ref, coach/client hardware_id)  -- §15.8
client_data_keys (DEK id, wrapped key, destroyed_at)
nate_intelligence_crystals.source_type TEXT
content_topics
```

DEK wrap/unwrap: **`client_envelope_cipher`** (not TokenCipher). Destruction of keys is flag-gated; encryption of new §0.4 writes is not.

No destructive DDL. No hard-delete application paths.

---

## 5. Workstream decomposition (LN7)

### WS-A — Google integration layer (freeze interface day 1)

**Files to extend:**  
`google_calendar_api.py`, `google_calendar_client.py`, `google_calendar_session_sync.py`, `google_calendar_sync_agent.py`  
**New:** `google_workspace_service.py` (facade), `gmail_draft_service.py`, `gmail_reply_listener.py`, `drive_workspace_writer.py`, `google_chat_notifier.py`

**Frozen interface** (`coachId` = `hardware_id`):

```text
googleSvc.calendar.upsertSession(coachId, sessionId)
googleSvc.calendar.removeSession(coachId, sessionId)
googleSvc.gmail.createDraft(coachId, {to, subject, body}) -> gmail_draft_id
googleSvc.gmail.onCampaignReply(callback)
googleSvc.drive.writeClientFile(...)  # VaultBlocked if vault_sync=false
googleSvc.status(coachId) -> {connected, scopes, revoked}
```

**Calendar rules (bind to existing booking):** B1–B5 from spec; Meet via `conferenceData`; vault_sync=false → `"Session — {initials}"`, no attendees, no description PII. Clients never Google attendees.

**Queens:** Only this package imports TokenCipher decrypt for Google refresh tokens.

### WS-B — Unified drafting

**New:** `email_draft_pipeline.py`  
Triggers: session note close; Gmail campaign reply; inbound inquiry (crisis screen first).  
Never auto-send. Status machine per AC3/AC4. Bodies envelope-encrypted under client DEK when `client_id` set.

### WS-C — Voice campaign engine

**New:** recorder API + R2 prefix `coach_voice_campaigns/`; `coach_voice_profile`; campaign generator → review queue → publishers.  
**LinkedIn:** per-coach OAuth (`ENABLE_COACH_LINKEDIN`); token store distinct from `skyeye_platform_tokens`. No SkyEye/Nate fallback. Missing token → stay in review queue + “Connect LinkedIn”.  
SendGrid drip uses campaign markers (not Gmail send).  
Extend growth review patterns; do **not** use therapy Twilio voice as ingestion (NG5).  
Newsletter = fourth content type behind `ENABLE_COACH_NEWSLETTER`.

### WS-Audio / Drive formatters (Gap 1 — named tickets)

| Ticket | Deliverable | Flag / consumer |
|--------|-------------|-----------------|
| `audio_synthesis_service` | Shared Azure TTS wrapper (not Twilio therapy pipeline) | `ENABLE_AUDIO_BRIEFS` |
| `morning_brief_composer` | Per-coach Morning Audio Brief: tasks (§13.1), G1 guidance weave, campaign day-N | G1, AC23, AC24 |
| `docs_formatter` | Docs API `batchUpdate` headings + habit checklist (vault_sync=TRUE only) | AC14 |
| `sheets_engagement_appender` | Per-campaign Sheet; row on every `campaign_engagements` insert | AC12 |

T4 Industry Reporter remains Studio config, external-only, never Sanctuary data (NG12 / §12.3c).

### WS-D — Studio webhooks

`POST /api/v1/hooks/{intake-analysis,engagement,client-digest}` — HMAC per coach, idempotency on engagement. Templates = config post-launch.

### WS-UI — Coach Command (single launch surface)

- Settings: **Connect Google Workspace** (`GOOGLE_WS_*`, hidden in prod until O9); **Connect LinkedIn** (coach token); vault_sync per client; Studio secret; Chat webhook  
- Client Settings: 183 **Connect Calendar** stays (calendar-only)  
- Dashboard: connection badge, calendar strip, Drafts waiting, campaign day-N card  
- Supervision tab: active `coach_hierarchy` row = master (`ENABLE_SUPERVISION_VIEW`); no `role='master_coach'`

### WS-§13–15 — Parallel after A0 freeze

`effective_scope(hardware_id)` consumed by B/C/D digests.  
§14 libraries + §15 clinical schema in the same migration.  
Envelope encryption **on**. Erasure UI **off** until counsel. AC30 staging drill **on**.

### WS-H — Golden set (Gap 2 — week 1, human-led)

Not a code ticket. Operator + master coaches author golden transcripts with known-correct briefs, extracted tasks, and summaries (both `relationship_class` values) starting **week one**, in parallel with A0. Eval harness (`AC33`) consumes this set; prompt/model changes replay it. If authorship slips, the Queens gate waits — do not shrink AC33.

---

## 6. Acceptance criteria → test ownership

| ACs | Owner | Notes |
|-----|-------|-------|
| AC1–2, AC11, AC15 | A | Test-user OAuth until O9; Meet + booking ACCEPT |
| AC3, AC8, AC32 | B | VaultBlocked + no Gmail send for drip |
| AC4–6, AC16–18 | C (+A listener) | Staging SendGrid + LinkedIn sandbox |
| AC12, AC14 | `sheets_engagement_appender`, `docs_formatter` | Drive.file only |
| AC13 | A Chat + C nudges | |
| AC7 | D | HMAC/idempotency |
| AC9–10 | Queens | Flag matrix + import audit |
| AC19–24 | §13 + `morning_brief_composer` | G1 weave; Gmail task channel vault_sync gate |
| AC25–26, AC28 | §14 | Soft-delete + circuit breaker stubs |
| AC27 | Ops / Queens track | PITR + Ring2 restore drill — scheduled, not LN7 code gate |
| AC29 | §15 credentials | |
| AC30 | Key architecture | **Staging drill with `ENABLE_CLINICAL_ERASURE=off`** |
| AC31 | Crisis | |
| AC33 | Eval harness | Golden set from WS-H; blocks deploy on drift |

**Queens bar = AC1–AC33 in full.** Seam-9 staging may mark items *blocked by O6/O9* (erasure UI, prod Workspace OAuth) but those ACs still run in staging (AC30, test-user AC1). A “subset” is not the gate. AC27 may be *scheduled* with a named ops owner.

Offline CI: unit/contract tests only. Live Google/LinkedIn/SendGrid = staging + Queens GREEN checklist.

---

## 7. Explicit non-goals (enforce in review)

NG1–NG12 from spec stand. Additionally:

- **NG13:** Do not expand 183 `GOOGLE_SCOPES` to Gmail/Drive. Coach Workspace is a **second** app (`GOOGLE_WS_*`). Do not incremental-scope a calendar-only production cohort (decision a).  
- **NG14:** Do not put campaign drip on Gmail.  
- **NG15:** Do not redefine or rename the seven crystal domains; additive `product`/`coding`/`operational` only, with the four-file update. Map `therapeutic` → `clinical`.  
- **NG16:** Do not use `ln7_tasks` for client habits.  
- **NG17:** Do not skip envelope encryption on §0.4 writes pending counsel. Do not encrypt Schedule display columns.  
- **NG18:** Do not wrap client DEKs with TokenCipher / `SKYEYE_TOKEN_ENCRYPTION_KEY`. Use `client_envelope_cipher`.  
- **NG19:** Do not publish coach campaigns via SkyEye/Nate LinkedIn tokens.  
- **NG20:** Do not remove Zoom join because Meet exists.  
- **NG21:** Do not rewrite `bridge_server.py` past the 50-line protected-file cap; booking seams go through REST / `bridge_handlers_v2`.

---

## 8. Queens GREEN gate (single review)

Checklist delta beyond spec §9:

1. Schema uses `users`/`coaching_sessions`/`google_calendar_connection`; **new FKs = hardware_id**; UNIQUE on `hardware_id`; `workspace_identity` view present.  
2. **Two OAuth apps:** 183 calendar-only still live for clients; `GOOGLE_WS_*` never mixed into client Connect Calendar.  
3. O1 (`gmail.readonly`) + Gmail History poll (no Pub/Sub this push).  
4. O9: coach-facing Connect Workspace OFF until CASA on **Workspace app**; test-user path proven. 183 client calendar stays.  
5. Vault-toggle leak: Workspace calendar/drafts/Drive **and** client-owned **183** calendar path (titles, attendees, description).  
6. Ciphertext inventory: §0.4 encrypted; Schedule columns plaintext; `client_envelope_cipher` ≠ TokenCipher.  
7. LinkedIn: per-coach token; no SkyEye fallback.  
8. Zoom join still works; Google upsert sets Meet `conferenceData`.  
9. Supervision leak peer-test (AC22); `effective_scope` keyed only on hardware_id; master = `coach_hierarchy`.  
10. Rollback = flags only; migration forward-only; **write-path encryption is not flag-killable**.  
11. Counsel O6/O7: `ENABLE_CLINICAL_ERASURE=false` in prod; **AC30 passed in staging**.  
12. **All 33 ACs** executed or recorded as staging-blocked (O6/O9) or ops-scheduled (AC27). No silent subset.

---

## 9. Launch slices (code ships together; coach-facing OAuth is not sliced)

| Slice | Meaning | Coach-facing? |
|-------|---------|----------------|
| Internal / test-user | Full scopes, calendar+Gmail+Drive+campaigns against Google test users | No |
| Prod L3–L5 | Voice campaign, Studio, tasks, supervision — do not require Google | Yes, Google-independent |
| Prod Google connect | `ENABLE_WS_OAUTH` ON after O9 | Yes — **one** consent, full scopes |
| Prod L6 erasure UI | `ENABLE_CLINICAL_ERASURE` after O6/O7 | Yes |

There is **no** production L1 calendar-only OAuth. Internal calendar work is not a second consent event.

---

## 10. Immediate next actions

1. Queens confirm §0.1 (`hardware_id` UNIQUE), §0.3 (split OAuth), §0.4 inventory, §1.1, §1.2 **(a)**. Override to (b) must be written.  
2. Kick `GOOGLE_WS_*` Cloud project + CASA **day one**. Leave 183 live.  
3. Start WS-H golden-set authorship **week one**.  
4. Freeze `googleSvc` stubs + `client_envelope_cipher` + `client_data_keys` (first §0.4 writes encrypted).  
5. Author migration `3xx` from §4 (additive only; CHECK widen = DROP+ADD).  
6. LN7 spawn: A / B / C / Audio / D / UI after A0 interface freeze.  
7. Counsel: O6/O7 ticket parallel — does not block encryption.

**Do not start** the client-facing erasure request UI or key-destruction workflow until counsel returns. **Do** encrypt from the first write.
