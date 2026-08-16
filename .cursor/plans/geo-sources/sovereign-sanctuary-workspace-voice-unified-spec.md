# Sovereign Sanctuary — Google Workspace Pairing + Voice Campaign Engine
## Unified Single-Push Specification (Plan-Agent Handoff)

**Version:** 1.5 · **Date:** 2026-08-11 · **Release model:** Single push, feature-flagged, one Queens GREEN gate · **v1.1:** §11 Google maximization · **v1.2:** §12 newsletter + crystals · **v1.3:** §13 tasks + supervision · **v1.4:** §14 libraries + backup/anti-deletion · **v1.5:** §15 clinical compliance & safety (dual-jurisdiction EU+US; dual-track certified/licensed)
**Builder:** LN7 (workstream decomposition below) · **Governance:** CLI-Queens GREEN/YELLOW/RED · **Intelligence layer:** Little Nate

---

## 1. Mission

Ship, in one release, the full pairing between Coach Command and each coach's Google Workspace, plus the voice-to-campaign marketing engine, so that:

1. A coach OAuths Google once and gains two-way calendar sync, LN-drafted Gmail messages, and Drive delivery of client materials.
2. A coach records a ~12-minute voice session and receives a 36-day campaign (~15 LinkedIn posts + 8–10 email drip touches) generated in their voice, gated by their approval, published via SendGrid and the LinkedIn publisher.
3. Engagement flows back into the platform (email replies → LN-drafted warm responses in the coach's Gmail; Studio webhook events → `campaign_engagements` ledger) so each campaign trains the next.
4. Clinical data never leaves the Sovereign Vault except under recorded per-coach consent and per-client sync settings.

All code deploys in one push. Every capability sits behind an independent server-side kill flag (§7). There is exactly one database migration set (§4), one OAuth consent event per coach (§5.A), and one Queens GREEN review (§9).

## 2. Architecture principles (binding)

- **P1 — Intelligence stays server-side.** All generation (briefs, drafts, campaigns) happens in the Sovereign Sanctuary backend via Little Nate. Google surfaces are delivery/ingest only. Workspace Studio flows are thin: trigger → call our API → deliver result.
- **P2 — SendGrid sends at volume; Gmail sends 1:1.** The campaign drip ships exclusively through SendGrid. The coach's Gmail is used only for individually reviewed drafts (session follow-ups, warm replies). No bulk or automated sending through Gmail, ever.
- **P3 — One token store, one interface.** All Google API access goes through a single credentials service (Workstream A). Workstreams B–D consume its interface; none touch Google auth directly.
- **P4 — Vault consent is explicit and granular.** The OAuth grant screen is the recorded coach-level consent event. Client-level exposure is governed by a per-client `vault_sync` boolean. Vault-only clients are represented outside the platform by initials only, receive no Drive folders, and never appear in email draft bodies.
- **P5 — Coach approval gates all outbound content.** Nothing publishes to LinkedIn or sends via SendGrid without passing the in-platform review queue. Gmail drafts are queued as drafts, never auto-sent.
- **P6 — Human-native LinkedIn engagement.** The platform never auto-comments or auto-replies on LinkedIn on the coach's behalf. It deep-links the coach to the live post on a timed schedule.
- **P7 — Queens govern every trust boundary.** Token storage, scope usage, webhook auth, and Vault-toggle enforcement are logged and reviewable. Any scope violation logs RED.

## 3. Explicit non-goals (do NOT build)

- NG1: Bulk email sending through Gmail or the Gmail API. (See P2.)
- NG2: Polling or scraping comments/reactions on personal-profile LinkedIn posts. The `r_member_social` read permission is closed to new applicants; do not design around obtaining it. Engagement counts for personal posts are coach-entered or omitted. (Company-page comment reads via `r_organization_social` are permitted **only** where a coach admins a page — optional, flag-gated, not launch-blocking.)
- NG3: Auto-posting comments or replies on LinkedIn via `w_member_social`. Publishing original scheduled posts only.
- NG4: Campaign review/approval in Google Docs or Sheets. The review queue lives in Coach Command only (preserves the approve/reject/rewrite loop into `marketing_content`). A read-only calendar export to Sheets is permitted, low priority.
- NG5: A Google Meet / Drive-upload ingestion path for voice recordings. The in-app recorder with guided prompt cards is the sole ingestion path.
- NG6: Any browser localStorage/sessionStorage dependence in coach-facing UI.
- NG7: Storing Google tokens unencrypted, or in any store other than the schema in §4.

## 4. Database migration (one set, ships together)

Target: existing PostgreSQL. All tables get standard `created_at` / `updated_at` and RLS consistent with current coach-scoping model.

```sql
-- 4.1 Coach Google credentials
CREATE TABLE google_credentials (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  coach_id        UUID NOT NULL REFERENCES coaches(id) ON DELETE CASCADE,
  refresh_token   BYTEA NOT NULL,            -- encrypted at rest (KMS/libsodium sealed box)
  granted_scopes  TEXT[] NOT NULL,
  google_sub      TEXT NOT NULL,             -- Google account subject id
  consent_recorded_at TIMESTAMPTZ NOT NULL,  -- doubles as Vault-consent event
  revoked_at      TIMESTAMPTZ,
  UNIQUE (coach_id)
);

-- 4.2 Per-client Vault exposure control
ALTER TABLE clients ADD COLUMN vault_sync BOOLEAN NOT NULL DEFAULT FALSE;
-- FALSE = Vault-only (initials-only externally); TRUE = Workspace-sync permitted

-- 4.3 Calendar sync bookkeeping
CREATE TABLE calendar_links (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  coach_id        UUID NOT NULL REFERENCES coaches(id),
  google_event_id TEXT NOT NULL,
  sync_state      TEXT NOT NULL CHECK (sync_state IN ('synced','pending','error')),
  UNIQUE (session_id)
);
CREATE TABLE calendar_watch_channels (
  coach_id        UUID PRIMARY KEY REFERENCES coaches(id) ON DELETE CASCADE,
  channel_id      TEXT NOT NULL,
  resource_id     TEXT NOT NULL,
  expires_at      TIMESTAMPTZ NOT NULL
);

-- 4.4 Draft queue (both draft types share one service)
CREATE TABLE email_drafts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  coach_id        UUID NOT NULL REFERENCES coaches(id),
  client_id       UUID REFERENCES clients(id),        -- NULL for prospect warm replies
  draft_type      TEXT NOT NULL CHECK (draft_type IN ('session_followup','warm_reply')),
  source_ref      UUID,                               -- session_id or campaign engagement id
  gmail_draft_id  TEXT,                               -- set once pushed to Gmail
  status          TEXT NOT NULL DEFAULT 'generated'
                  CHECK (status IN ('generated','pushed','sent','discarded','blocked_vault')),
  body_hash       TEXT NOT NULL                       -- for audit; body itself stays in Vault
);

-- 4.5 Campaign engagement ledger (written by Gmail listener AND Studio webhook)
CREATE TABLE campaign_engagements (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id     UUID NOT NULL REFERENCES marketing_campaigns(id),
  coach_id        UUID NOT NULL REFERENCES coaches(id),
  prospect_email  TEXT,
  channel         TEXT NOT NULL CHECK (channel IN ('email_reply','chat_alert','booked_call','manual','page_comment')),
  source          TEXT NOT NULL CHECK (source IN ('gmail_listener','studio_webhook','coach_entry','booking_flow')),
  payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
  occurred_at     TIMESTAMPTZ NOT NULL
);
CREATE INDEX ON campaign_engagements (campaign_id, occurred_at);

-- 4.6 Post deep-link + golden-hour nudges (extends existing campaign content rows)
ALTER TABLE marketing_content
  ADD COLUMN post_urn  TEXT,     -- from LinkedIn publish response
  ADD COLUMN post_url  TEXT;     -- https://www.linkedin.com/feed/update/{urn}/
CREATE TABLE post_nudges (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content_id      UUID NOT NULL REFERENCES marketing_content(id) ON DELETE CASCADE,
  fire_at         TIMESTAMPTZ NOT NULL,     -- T+0 and T+40m rows written at publish
  nudge_kind      TEXT NOT NULL CHECK (nudge_kind IN ('live_now','check_replies')),
  delivered_at    TIMESTAMPTZ
);
```

Encryption: `refresh_token` encrypted with a key held outside the DB; decryption only inside the credentials service (Workstream A). Queens verify no other service imports the decryption module.

## 5. Workstream contracts (build in parallel; A's interface freezes first)

### Workstream A — Google integration layer (foundation)
**Deliverables:** OAuth 2.0 authorization-code flow with incremental=false single consent; token refresh + rotation; revocation handling (Google-side revoke → mark `revoked_at`, disable dependent features gracefully); Calendar two-way sync engine; Drive writer; Gmail draft writer + reply listener.

**Scopes requested (exactly these, single grant):**
- `https://www.googleapis.com/auth/calendar.events`
- `https://www.googleapis.com/auth/gmail.compose` (draft creation)
- `https://www.googleapis.com/auth/gmail.metadata` or `gmail.readonly` — choose the narrowest scope that supports campaign-thread reply detection via the `history`/`watch` API; document the choice and justify to Queens.
- `https://www.googleapis.com/auth/drive.file` (app-created files only)

**Calendar sync rules:**
- Sanctuary → Google: on session create/update/cancel, upsert event; store mapping in `calendar_links`. Event title for `vault_sync=FALSE` clients: `"Session — {initials}"`, no description, no attendees. For `vault_sync=TRUE`: client first name + link back to Coach Command session page.
- Google → Sanctuary: `events.watch` channel per coach (renew before `expires_at`, table 4.3); inbound changes to Sanctuary-tagged events update the session; changes to non-Sanctuary events are ignored.
- Conflict rule: Sanctuary is source of truth for session substance; Google wins only on time changes made by the coach.

**Booking-flow integration (existing LN scheduling approval process — binding rules):**
The existing client→LN availability inquiry and coach accept/deny/counter approval flow remains the sole booking state machine; Workspace surfaces attach to it, never replace it.
- B1: Availability answers = intersection of declared coach availability (internal schedule, authoritative for what may be offered) AND Google free/busy (when connected). No Google connection → internal schedule alone, as today.
- B2: Google Calendar events are created only on coach ACCEPT. Pending/countered requests never create Google events (no tentative holds).
- B3: Coach approval requests are delivered via existing email AND (when configured) the Chat rail with Accept/Deny/Propose actions; both converge on the same approval endpoint; first response resolves, the other is invalidated.
- B4: Clients are NEVER attendees on Google events and never receive Google invites; client-facing scheduling communication flows exclusively through LN in-app messaging (Vault requirement, independent of vault_sync).
- B5: A coach-side time change on a booked Google event is treated as a reschedule request: sync detects the move, LN notifies the client in-app, client confirmation completes the reschedule in the state machine. Deletion of a Sanctuary-tagged event triggers a cancellation-confirm prompt to the coach in-app/Chat, not a silent cancel.

**Interface (frozen day 1, consumed by B/C):**
```
googleSvc.calendar.upsertSession(coachId, sessionId)
googleSvc.calendar.removeSession(coachId, sessionId)
googleSvc.gmail.createDraft(coachId, {to, subject, body}) -> gmail_draft_id
googleSvc.gmail.onCampaignReply(callback({coachId, threadRef, prospectEmail}))
googleSvc.drive.writeClientFile(coachId, clientId, {name, mime, bytes}) -> file_id  // throws VaultBlocked if vault_sync=FALSE
googleSvc.status(coachId) -> {connected, scopes, revoked}
```

### Workstream B — Unified drafting service
One service, two draft types, one pipeline: context assembly → LN generation → `email_drafts` row → push to Gmail as draft → surface in Coach Command "Drafts waiting" card.

- `session_followup`: triggered when coach closes a session note. Context = session note + client history (scope-filtered). Contains recap + habit assignment. Hard-blocked (`blocked_vault`) for `vault_sync=FALSE` clients.
- `warm_reply`: triggered by `googleSvc.gmail.onCampaignReply`. Context = prospect thread + Coach Voice Profile + originating campaign touch. Also writes a `campaign_engagements` row (`channel='email_reply'`, `source='gmail_listener'`).
- `inbound_inquiry`: triggered by the Gmail listener on non-campaign inbound mail that reads as a question about the coach's practice or the platform. Context = per-coach practice FAQ corpus (rates, offerings, logistics; Ask-LN corpus pattern, coach-scoped) + Voice Profile. MANDATORY pre-step: crisis/clinical screen — any message with clinical or distress weight produces NO FAQ draft and instead a flagged coach alert (Chat rail + dashboard) for human response. Logs `campaign_engagements` (`channel='inbound_inquiry'`). Add `inbound_inquiry` to the `email_drafts.draft_type` CHECK and `inbound_inquiry` to the `campaign_engagements.channel` CHECK.
- Never auto-send. `status` transitions: generated → pushed → (coach acts in Gmail) → sent/discarded, detected best-effort.

### Workstream C — Voice campaign engine
Recorder (existing MediaRecorder UI, 12-min cap, guided prompt cards) → R2 storage → Azure transcription → Coach Voice Profile upsert → LN campaign generation (36-day arc: ~15 LinkedIn posts across content pillars + 8–10 SendGrid drip touches) → rows in `marketing_content` → coach review queue (approve / reject / rewrite-with-note; rewrites loop through LN) → publishers.

**Publish-time additions (new in this spec):**
1. LinkedIn publish response URN → write `post_urn` and constructed `post_url` to the content row.
2. Write two `post_nudges` rows: `live_now` at T+0, `check_replies` at T+40m. Nudge delivery = push/Chat notification containing `post_url` deep link. Nudge copy references first-hour engagement per Standing Orders.
3. SendGrid drip sends tag messages with `campaign_id` + a reply-detectable thread marker so Workstream A's listener can match replies.

Booking-flow completions attributable to a campaign write `campaign_engagements` (`channel='booked_call'`, `source='booking_flow'`).

### Workstream D — Inbound webhook endpoints (Studio-facing)
Three authenticated endpoints (HMAC-signed shared secret per coach, rotatable; reject unsigned):
- `POST /api/v1/hooks/intake-analysis` — form payload in → LN intake analysis → response for Studio to place in coach's Sheet.
- `POST /api/v1/hooks/engagement` — writes `campaign_engagements` (`source='studio_webhook'`). Idempotency key required.
- `POST /api/v1/hooks/client-digest` — returns LN weekly caseload digest (scope-filtered; excludes `vault_sync=FALSE` client detail beyond counts).

Studio flow **templates** are configuration, not code: authored post-launch, shareable across the coach team. Their absence never blocks this release.

## 6. Coach-facing surface (single launch)

Dashboard adds, in one release: Google connection status badge; today's synced calendar strip with LN-brief links and Vault-only indicators; "Drafts waiting in your Gmail" card (both draft types); voice campaign card (day N of 36, today's post + deep link, engagement counts from `campaign_engagements` only — no fabricated LinkedIn metrics for personal posts). Settings adds: Google connect/disconnect; per-client Vault-sync toggle with plain-language explanation of exactly what syncing exposes.

## 7. Feature flags (kill switches, not phases)

All code deploys together; each flag is server-side, per-environment, kill-capable without redeploy, and defaults ON at launch after the gate:
`ws_oauth`, `ws_calendar_sync`, `ws_gmail_drafts`, `ws_drive_delivery`, `voice_campaign`, `campaign_nudges`, `studio_webhooks`, `page_comment_reads` (default OFF; optional NG2 exception).
Flag semantics: killing a flag degrades gracefully with a coach-visible "temporarily unavailable" state; it never corrupts state or strands drafts/queues.

## 8. Acceptance criteria (testable; the plan agent must generate tests for each)

- AC1: A coach completes OAuth in one grant; `google_credentials` row exists with `consent_recorded_at`; disconnect revokes at Google and sets `revoked_at`; all dependent UI degrades gracefully.
- AC2: Creating/moving/canceling a session in Coach Command reflects on the coach's Google Calendar within 60s, and vice versa for time changes; `vault_sync=FALSE` client events show initials only — verified by inspecting the raw Google event resource.
- AC3: Closing a session note for a `vault_sync=TRUE` client yields a Gmail draft in the coach's account and an `email_drafts` row; same action for a `vault_sync=FALSE` client yields `blocked_vault` and no Google API call containing client content.
- AC4: A reply to a SendGrid campaign email produces (a) a `campaign_engagements` row and (b) a warm-reply Gmail draft in the coach's voice, within 5 minutes.
- AC5: A recorded 12-minute session produces a reviewable 36-day campaign; nothing publishes without queue approval; a rejected item with a note returns a redraft.
- AC6: LinkedIn publish stores a valid `post_urn`/`post_url`; the URL opens the exact post; nudges fire at T+0 and T+40m containing that link.
- AC7: Studio webhook calls with a bad signature are rejected 401 and logged; valid `engagement` calls are idempotent under retry.
- AC8: Zero Gmail API sends of campaign drip content (audit query over Gmail API call log must return none).
- AC9: Killing any single flag leaves all other capabilities functional and no queued state corrupted.
- AC10: No service other than the credentials service can decrypt `refresh_token` (verified by dependency audit).

## 9. Queens GREEN gate (one review, whole surface)

Checklist: scope minimality justification (esp. the Gmail read scope choice in §5.A); token encryption + key custody; webhook HMAC + rotation; Vault-toggle leak test (attempt to exfiltrate a Vault-only client through every surface: calendar, drafts, Drive, digest, Studio responses); rate-limit and quota handling for Google APIs and LinkedIn (~100 calls/day/member publish budget); RED-logging on any scope violation; rollback plan = flags, with DB migration forward-only and additive (it is — verify no destructive statements). Budget this as a real review, not a formality: it is the only gate.

## 10. Open items for the plan agent to resolve (flag, don't guess)

- O1: Exact Gmail scope for reply detection (`gmail.metadata` vs `gmail.readonly`) — pick narrowest workable; justify.
- O2: Sent/discarded detection fidelity for Gmail drafts (best-effort via history API vs. omit).
- O3: Whether existing `sessions`/`clients`/`marketing_content`/`marketing_campaigns` table names match production schema — reconcile against live schema before writing the migration; the DDL above expresses intent, not final names.
- O4: RESOLVED in v1.1 — Google Chat is the primary nudge/alert rail (§11.3); mobile push is fallback for coaches without Chat.
- O5: Studio webhook shared-secret provisioning UX (per-coach secret surfaced where?).

---

## 11. v1.1 addendum — Google-surface maximization (no new OAuth scopes)

Design rule M0: add a Google app only if LN's intelligence flows through it as a chain step. Decorative surface area is rejected (see exclusions, §11.6).

### 11.1 Meet links on all synced sessions (Workstream A)
Every Sanctuary→Google calendar upsert sets `conferenceData` so each session event carries a Google Meet link. No additional scope (rides on `calendar.events`). Strategic note for the builder: Meet-hosted sessions make LN-Observer screen-share one click; surface a "Observe with LN" affordance next to the Meet link on the session page (admin-gated as per existing LN-Observer rules). Vault rule unchanged: `vault_sync=FALSE` events remain initials-only; the Meet link itself carries no client data.

### 11.2 Living Sheets + formatted Docs via drive.file (Workstreams A + B + C)
The already-requested `drive.file` scope authorizes Sheets API and Docs API calls on files the app creates. Therefore:
- **Campaign engagement Sheet** (per campaign, per coach): created at campaign launch; a row auto-appends for every `campaign_engagements` insert (worker consumes the same event that feeds the dashboard). Columns: occurred_at, channel, prospect (email or '—'), payload summary. Coach-visible real-time funnel in a familiar surface.
- **Session summaries as formatted Docs**, not flat files: headings (Recap / Patterns / Habit assignment as checklist) via Docs API `batchUpdate`. Applies only to `vault_sync=TRUE` clients; `VaultBlocked` behavior identical to §5.A.
- Existing "read-only Sheet calendar export" (NG4 note) is superseded by the engagement Sheet; content-calendar export remains optional/low priority.

### 11.3 Google Chat as the primary notification rail (Workstream A + C)
During onboarding (post-OAuth), provision a "Sovereign Sanctuary" Chat space via incoming webhook (coach pastes webhook URL — no additional OAuth scope) or Studio-delivered Chat step. All coach notifications route here: golden-hour nudges (`post_nudges` delivery), warm-reply alerts, intake alerts, digest delivery notices. Mobile push is fallback when no Chat webhook is configured. Nudge messages always include the `post_url` deep link.

### 11.4 Deep-chain Studio templates (post-launch configuration; endpoints unchanged)
Studio limits (~100 agents, 20 steps) make flows the scarce resource: ship few, deep templates rather than many shallow ones.
- **T1 Intake mega-chain (~8 steps):** Form submitted → POST /intake-analysis → append engagement Sheet row → create Doc brief → Chat alert with Doc link → create Calendar consult hold → POST /engagement (idempotent). Ships with a copyable Google Forms intake template (§11.5).
- **T2 Friday digest (~4 steps):** schedule trigger → POST /client-digest → write Doc → Chat notice.
- **T3 Golden-hour companion (~3 steps):** time trigger from content calendar → Chat message with post_url → POST /engagement (channel='chat_alert').
- **T4 Industry Reporter (~4 steps, external-only):** schedule trigger → Gemini researches curated coaching/wellness industry topics and sources → summary Doc → Gemini native TTS audio for commute listening. BOUNDARY: this template consumes EXTERNAL sources only and is never connected to Sanctuary endpoints or data — internal audio intelligence (Morning Audio Brief) is exclusively LN/Azure TTS. Complements, never replaces, the Morning Brief: Reporter = outside world, Brief = inside world.
- **T5 Inbox Labeler (~3 steps, organize-only):** on new email → Gemini classifies → applies label. GUARDRAILS (binding, written into the shipped template prompt): organizational labels only (e.g. Admin, Vendors, Receipts, Newsletters, Speaking/Media) plus a single catch-all "Personal — review" for messages that read as an individual writing personally; the agent must NEVER apply urgency/priority rankings to personal messages and must never draft, reply, archive, or delete. Safety layering: LN's inbound listener + crisis screen (Workstream B) fire independently of any label — a Gemini label cannot suppress an LN alert. Coach education line: labels organize; LN alerts prioritize.
Templates are configuration; their absence never blocks the release (unchanged from §5.D).

### 11.5 Google Forms intake template
A copyable Forms template whose fields map 1:1 to the /intake-analysis payload schema. Deliverable is a documented template + field-mapping doc, not code. Payload schema in Workstream D must be frozen before the template is authored.

### 11.6 Evaluated and excluded (binding, appended to §3 in spirit)
- NG8: Google Tasks / Keep for habit assignments — assignments live in the follow-up email + summary Doc; a third surface fragments the client experience.
- NG9: Google Contacts sync — `contacts` write scope is a high-friction consent line for marginal benefit.
- NG10: Sites / Slides integrations — no LN chain step flows through them.
- NG11: Apps Script as an automation runtime — Studio + Sanctuary webhooks are the sole automation layers; a second runtime doubles the governance surface.
- NG12: Studio/Gemini email auto-responders (the "Personalized Customer Responder" pattern) on any inbox receiving client or prospect mail. All inbound client/prospect email response drafting is exclusively Workstream B (LN), which is crisis-screened, Vault-scoped, and engagement-logged. Studio templates shipped to coaches must not include email-drafting flows, and coach education materials must state this explicitly.

### 11.7 Acceptance criteria added
- AC11: Synced session events contain a working Meet link; Vault-only events remain initials-only with no client data in conference metadata.
- AC12: An engagement-ledger insert appears as a new row in the campaign's Sheet within 60s; Sheet/Doc creation uses only `drive.file` (scope audit).
- AC13: With a configured Chat webhook, T+0 and T+40m nudges arrive in the coach's Chat space containing the correct post deep link; without one, mobile push fires instead.
- AC14: Session-summary Docs render headings and checklist formatting and are never created for `vault_sync=FALSE` clients.
- AC15: End-to-end booking test — client asks LN for availability; offered slots exclude times busy on the coach's Google Calendar; no Google event exists while the request is pending; coach ACCEPT (via email or Chat action) creates the event with Meet link and no client attendee; coach-side event drag triggers an LN client notification and does not finalize until client confirms.

---

## 12. v1.2 addendum — Coach newsletter + learning/crystal capture

### 12.1 Coach newsletter (fourth output of the content engine; Workstream C extension)
- New `marketing_content` content type: `newsletter_issue` (configurable cadence, e.g. biweekly/monthly). Assembled by LN from: Coach Voice Profile + active campaign pillars + coach-flagged topics (12.2). Same approval queue, same rewrite loop. Sent exclusively via SendGrid (bulk rule P2 applies; never Gmail). Opens/clicks/replies write `campaign_engagements` (add `channel='newsletter'` to the CHECK constraint); replies feed the existing warm-reply draft pipeline unchanged.

### 12.2 Topic capture pipeline (Reporter → coach → LN authorship)
- A "flag topic" affordance in Coach Command (and optionally a T4 follow-up Chat action) writes coach-flagged topics/sources to a `content_topics` table (coach_id, topic, source_url, flagged_at, used_in content_id NULL).
- BOUNDARY (binding): Gemini Reporter output is inspiration only. LN authors all published content from grounded retrieval of original sources; Gemini-generated text is never republished, quoted, or used as source material in any coach-published artifact.

### 12.3 Learning & crystal capture map (Workstreams B/C/D → crystal pipeline)
Capture (crystal-eligible, all via existing index_wisdom() vectorize path):
- Voice recording transcripts → coach-scoped wisdom crystals (philosophy, methods, client-pattern articulation). Highest-value new ore in this build.
- Review-queue decisions (approve/reject/rewrite notes) → coach preference/voice crystals.
- campaign_engagements outcomes → marketing-domain crystals (what converts, per niche).
- Ask-LN product questions + resolutions → product-domain crystals; unanswered questions queue KB improvements.
- Build-phase operational knowledge (OAuth patterns, webhook fixes, deployment recipes) → coding-domain crystals via Blue Harvester (existing channel; benefits LN7/Queens).

Prerequisites (ship in the single migration / ORANGE config):
- 12.3a: ADD COLUMN source_type TEXT and domain TEXT (CHECK IN ('therapeutic','marketing','product','coding','operational')) to nate_intelligence_crystals — resolves the known missing-column gap; all producers must populate both.
- 12.3b: Extend the ORANGE Stage 1 filter (Qwen) domain-aware prompt to recognize marketing and product knowledge as crystal-worthy (same class of fix previously applied for coding content); define per-domain crystal budgets so marketing volume cannot crowd therapeutic capacity.
- 12.3c: EXCLUSION (binding): Gemini/T4 Reporter content is never ingested into crystal production or LN memory. Coach-flagged topic signals (12.2) may crystallize as coach-interest metadata; third-party model text may not.
- 12.3d: All capture respects existing Vault scoping: coach-scoped crystals stay coach-scoped; client-derived material follows existing clinical crystal rules unchanged.

### 12.4 Acceptance criteria added
- AC16: A published newsletter_issue exists only after queue approval, sends only via SendGrid, and its engagement events appear in campaign_engagements with channel='newsletter'.
- AC17: A coach-flagged topic produces a content_topics row and is traceable to the content it seeded (used_in linkage).
- AC18: New crystals from voice transcripts, review decisions, and Ask-LN carry correct source_type + domain; a scope audit shows zero crystals with Gemini/T4-derived text; per-domain budget caps enforced.

---

## 13. v1.3 addendum — Task system + master/assistant supervision hierarchy

### 13.1 In-platform task system (NG8 stands: no Google Tasks/Keep surface)
```sql
CREATE TABLE tasks (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_by    TEXT NOT NULL CHECK (created_by IN ('ln','coach','master_coach')),
  assignee_type TEXT NOT NULL CHECK (assignee_type IN ('coach','client','assistant_coach')),
  assignee_id   UUID NOT NULL,
  client_id     UUID REFERENCES clients(id),        -- context client, nullable
  source_ref    UUID,                               -- session_id / content_id / care_plan_review_id
  title         TEXT NOT NULL,
  detail        TEXT,
  due_at        TIMESTAMPTZ,
  status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','done','dismissed')),
  completed_at  TIMESTAMPTZ
);
```
- LN extraction: post-session synthesis emits structured tasks alongside the summary — coach tasks + client habit tasks. Client tasks are gated by the existing follow-up approval (coach blesses before delivery) and delivered EXCLUSIVELY via LN in-app messaging (B4 logic; clients never touch Google surfaces). Coach tasks surface in dashboard, Morning Audio Brief, and Chat digest — no new surfaces.
- **Dual authorship:** client habit tasks may be LN-extracted (coach-approved) OR coach-authored directly (created_by='coach'); both enter the identical delivery + monitoring stream.
- **Care-plan linkage:** client tasks link to the client's care plan trajectory; task history constitutes the implementation record reviewed in care_plan_reviews and summarized in supervision digests.
- **LN monitoring (binding):** delivered client tasks enter LN's working awareness — conversational check-ins, progress capture, and adherence surfaced in the coach's next pre-session brief. Progress writes to task_progress regardless of channel.
- **Email channel for app-less clients:** clients without the app receive habit task lists via the coach's Gmail follow-up (thread-marked); inbound client replies on habit threads are parsed by LN into task_progress (following/struggling/completed/needs_help), 'needs_help' items alert the coach via Chat rail, and a coach reply draft may be queued. MANDATORY: the inbound crisis screen (Workstream B) runs before any task parsing. CONSTRAINT: the email channel requires vault_sync=TRUE; Vault-only app-less clients have no automated task channel by design (in-session + in-platform record only).
```sql
CREATE TABLE task_progress (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  reported_via TEXT NOT NULL CHECK (reported_via IN ('in_app','email','coach')),
  status TEXT NOT NULL CHECK (status IN ('following','struggling','completed','needs_help')),
  note TEXT,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE clients ADD COLUMN app_enabled BOOLEAN NOT NULL DEFAULT TRUE;  -- routes task delivery: app vs email
```
- Master coaches may create tasks for assistant coaches (mentorship tasks; assignee_type='assistant_coach').

### 13.2 Supervision hierarchy (master coach → assistant coach)
```sql
CREATE TABLE supervision_links (
  master_coach_id    UUID NOT NULL REFERENCES coaches(id),
  assistant_coach_id UUID NOT NULL REFERENCES coaches(id),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at   TIMESTAMPTZ,
  PRIMARY KEY (master_coach_id, assistant_coach_id, started_at)
);
CREATE TABLE care_plan_reviews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id UUID NOT NULL REFERENCES clients(id),
  assistant_coach_id UUID NOT NULL REFERENCES coaches(id),
  master_coach_id UUID NOT NULL REFERENCES coaches(id),
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','submitted','approved','needs_changes')),
  notes TEXT, reviewed_at TIMESTAMPTZ
);
CREATE TABLE supervision_hours (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  master_coach_id UUID NOT NULL REFERENCES coaches(id),
  assistant_coach_id UUID NOT NULL REFERENCES coaches(id),
  client_id UUID REFERENCES clients(id),
  activity TEXT NOT NULL CHECK (activity IN ('care_plan_review','session_review','mentorship','case_consult')),
  minutes INTEGER NOT NULL CHECK (minutes > 0),
  logged_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```
- **Scope resolution (ships in the push; consumed by every workstream):** effective_scope(coach) = own clients ∪ (via active supervision_links) assistants' clients as READ/REVIEW access. Assistant remains primary author of care. LN queries, dashboards, and digests resolve through this one function.
- **Supervision is OBSERVATORY and non-blocking (binding):** no supervision state — including care_plan_reviews status 'needs_changes' — ever blocks, delays, or gates an assistant's session delivery or client communication. 'needs_changes' produces guidance (13.4) and an assistant task, nothing more.
- **Supervision access is a second internal trust boundary:** every master access to assistant-scoped client data writes a distinct supervision_access audit log (Queens-reviewable). Gate includes supervision leak-testing peer to the Vault-toggle tests.
- **Supervision digests (LN-generated, flag `supervision_view`):** per-assistant high-level synthesis — caseload summary, session cadence, open/completed task implementation rates, care plan review statuses, notable LN-flagged patterns. In-platform + Chat-rail notice; never delivered to the master's Google surfaces beyond initials-level notices.
- **Placement + role gating:** the supervision dashboard is a dedicated "Supervision" TAB inside Coach Command, rendered only for coaches with role='master_coach' (explicit `coaches.role` column, admin-assigned — a Queens-auditable governance act) AND server-side authorization on every supervision route; assistant sessions never receive supervision routes or data (UI reflects the boundary, never enforces it). Masters retain their full standard coach experience for their own caseload; LN queries from the Supervision tab default to assistant scope, queries from standard chat default to own-caseload scope, either may cross explicitly.
- **LN-Observer alignment:** masters may review assistants' observed sessions under existing admin gating; supervision insights crystallize (domain='therapeutic', mentorship-tagged).
- **Consent:** client-facing consent language discloses supervising-master oversight access; recorded per client. Independent of vault_sync (which governs Google exposure only).
- **Google boundary:** a master's OAuth/calendar sync covers their OWN sessions only; supervision review blocks may create events on the master's calendar titled with assistant initials + activity, never client identity.

### 13.4 Supervision guidance system (master → assistant, via LN + Workspace rails)
```sql
CREATE TABLE supervision_guidance (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  master_coach_id UUID NOT NULL REFERENCES coaches(id),
  assistant_coach_id UUID NOT NULL REFERENCES coaches(id),
  client_id UUID REFERENCES clients(id),            -- NULL = general mentorship
  source TEXT NOT NULL CHECK (source IN ('care_plan_review','session_review','observer_session','general')),
  body TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  acknowledged_at TIMESTAMPTZ
);
```
Delivery rules (binding):
- G1 — Brief weaving: client-specific guidance is woven by LN into the assistant's NEXT pre-session brief for that client, and mentioned in the assistant's Morning Audio Brief. Guidance lands in context, not in a separate supervision inbox.
- G2 — Chat rail doorbell: assistant receives a Chat notification with master name + client initials only + deep link to Coach Command. Full guidance content is never rendered on Google surfaces when client_id is set.
- G3 — General mentorship (client_id NULL): may be produced as a shared Google Doc via drive.file (master's app-created Doc, assistant added as reader), enabling Docs' native listen feature for commute consumption. LN may compose these Docs from the master's notes.
- G4 — Observer insight packaging: master annotations on LN-Observer-reviewed sessions are packaged by LN into supervision_guidance rows (source='observer_session') and crystallize per 13.2 (mentorship-tagged).
- G5 — Nothing in this system blocks care (see observatory rule, 13.2); guidance may auto-create an assistant task (13.1) but the task is advisory.

### 13.5 Flags + acceptance criteria
Flags added: `tasks`, `supervision_view` (dashboard UX may mature post-launch behind this flag; schema + scope resolution ship in the push regardless).
- AC19: Closing a session yields LN-extracted coach tasks and client task candidates; client tasks reach the client in-app only after coach approval; NG8 audit shows zero Google Tasks/Keep API usage.
- AC20: A master coach can query LN about a linked assistant's client and receive a scope-filtered answer; the same query from a non-linked coach is refused; both outcomes appear in the supervision_access audit log.
- AC21: care_plan_reviews transitions (submitted → approved / needs_changes) notify the assistant via Chat/dashboard and are immutable once approved; supervision_hours entries are append-only and exportable per master.
- AC22: Supervision leak test — no path (dashboard, LN answer, digest, Chat notice, Google surface) exposes an assistant's client detail to a coach without an active supervision_link; master Google surfaces never contain client identity from supervised caseloads.
- AC23: Guidance flow test — master guidance on a client appears woven into the assistant's next pre-session brief for that client and in their Morning Audio Brief; the Chat notification carries initials + link only; a general-mentorship guidance (client_id NULL) produces a shared Doc readable by the assistant; a 'needs_changes' care plan review measurably does NOT delay or block the assistant's next session delivery or client messaging.
- AC24: Task lifecycle test — an LN-extracted and a coach-authored habit task both reach an app_enabled client in-app after approval; an app-less vault_sync=TRUE client receives the list via thread-marked Gmail follow-up, and their email reply updates task_progress with 'needs_help' items alerting the coach; the same reply containing distress content triggers the crisis alert and NO task parsing; an app-less vault_sync=FALSE client generates zero outbound task emails; adherence appears in the coach's next pre-session brief.

---

## 14. v1.4 addendum — Template & best-practices libraries + backup/anti-deletion architecture

### 14.1 Practice Template Library (pod-scoped, pull not push)
```sql
CREATE TABLE practice_templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  author_coach_id UUID NOT NULL REFERENCES coaches(id),   -- master coach
  scope TEXT NOT NULL DEFAULT 'pod' CHECK (scope IN ('pod','org')),
  kind TEXT NOT NULL CHECK (kind IN ('intake','treatment_plan','session_structure','worksheet','guidance_doc','other')),
  title TEXT NOT NULL,
  body_ref TEXT NOT NULL,             -- R2 object / structured content ref (CANONICAL copy)
  version INTEGER NOT NULL DEFAULT 1,
  superseded_by UUID REFERENCES practice_templates(id),
  archived BOOLEAN NOT NULL DEFAULT FALSE               -- soft-delete only
);
```
- CANONICAL RULE (binding): the master copy of every template lives in Sanctuary (DB + R2). Google Drive holds rendered COPIES only (shared pod folder via drive.file, ACs as readers, Docs listen-enabled); Drive loss/revocation never affects the library.
- ACs pull from the pod library on demand; MC never "sends" per use. LN instantiates templates contextually (e.g., new client → LN generates the pod's intake from the current template version, delivered as Doc or in-app per vault rules).
- Versioning: edits create a new version row; prior versions persist (superseded_by linkage). Hard DELETE is not exposed in any application path.
- **Editing flow (binding):** editing = authoring a successor version, in-platform or via LN conversationally (LN drafts revision → MC reviews → publish). Drive renders are READ-ONLY; edits to Drive copies never propagate. On publish of vN+1: library serves vN+1, LN instantiates vN+1 for new clients, Drive re-renders. Already-instantiated documents are immutable SNAPSHOTS of the version used (clinical record integrity). ACs see current version only; full version chains visible to author + Admin. Drafts are freely mutable until first publication.
- **Org library revisions:** a revision to a published org entry is a PROPOSAL (author MC or Admin drafts vN+1) entering the Admin review queue like a new nomination; only Admin approval publishes. Admin's own edits also flow through versioning (unbroken audit chain).

### 14.2 Organization Best-Practices Library (admin-curated, org-wide)
```sql
CREATE TABLE org_library (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_kind TEXT NOT NULL CHECK (source_kind IN ('template','guidance','care_plan_pattern','observer_insight','other')),
  source_ref UUID,
  title TEXT NOT NULL,
  body_ref TEXT NOT NULL,
  nominated_by UUID REFERENCES coaches(id),   -- or LN (NULL + note)
  status TEXT NOT NULL DEFAULT 'nominated' CHECK (status IN ('nominated','admin_review','published','archived')),
  version INTEGER NOT NULL DEFAULT 1,
  published_at TIMESTAMPTZ, archived_at TIMESTAMPTZ
);
```
- Promotion pipeline: MC nomination or LN pattern-flagging (recurring effective practices across pods) → Admin review queue → published org-wide (all pods pull; ACs see org + own-pod libraries merged).
- IMMUTABILITY (binding): published entries are append-only versioned; no in-place edits; no hard delete in any application path; archive requires Admin approval and preserves the row. Published practices crystallize as org-level mentorship wisdom (domain per 12.3, org-scoped).

### 14.3 Backup & anti-deletion architecture (Queens-owned; Admin-held keys)
- **Ring 1 — PITR:** PostgreSQL continuous WAL archiving; restore-to-any-minute capability, restore drill quarterly.
- **Ring 2 — Object-locked offsite:** nightly encrypted snapshots (DB + R2 objects incl. template/library bodies, voice recordings, audio) to a SEPARATE cloud account/bucket with object-lock/WORM retention (recommended ≥30 days); backup credentials exist NOWHERE in production infrastructure and are held by Admin alone — a fully compromised production node has no deletion path to backups.
- **Ring 3 — Admin master file:** scheduled export of org_library + practice_templates + critical registries, CLIENT-SIDE ENCRYPTED before upload, to Admin's personal business-grade cloud (OneDrive/Drive acceptable at this ring because content is ciphertext). Plaintext client data never syncs to consumer cloud storage.
- **Mass-deletion circuit breaker:** Queens monitor for bulk delete/archive patterns across clients, files, coaches, and library tables; threshold breach → immediate RED alert + operation hold pending Admin confirmation. Deletion of organizational memory must be loud and slow, never silent and fast.
- All application-layer "deletes" across client files, coach files, MC materials, and libraries are soft-deletes with tombstones; hard deletion is a DBA-level act outside application paths, logged.

### 14.5 Insider-threat & compromised-account protections (MC/coach "system wipe" defense)
- **INVARIANT (binding):** no role below Admin possesses a hard-delete primitive anywhere in the application layer. Supervision access to assistant-scoped data is READ/REVIEW only — no write/delete endpoints exist on that scope (absence of verbs, not permission checks). Destructive capability of a hostile MC is limited to own-caseload soft operations and soft-archive flags, all reversible and tripwired.
- **Per-role bulk-operation quotas:** velocity limits on archive, soft-delete, export, and supervision-read verbs; threshold breach → automatic operation hold + RED alert + Queens review (extends the 14.3 circuit breaker beyond deletion).
- **Step-up authentication:** fresh MFA required for bulk archives, caseload-level soft deletes, large exports, and Google disconnect/reconnect. Stolen session tokens cannot perform damage alone.
- **Role governance:** coaches.role changes occur through a single Admin-gated route only; no self-service or MC-reachable path; dual-logged (actor, subject, timestamp). Compromise of Admin itself is answered by Ring 2 (object-locked backups, production-blind credentials).
- **Behavioral anomaly detection (Queens duty):** new device/geo → step-up; off-hours mass supervision reads → YELLOW; export/read volume spikes → RED. supervision_access and all sensitive-verb logs are actively monitored, not merely written.
- **Offboarding:** ending supervision_links + role revocation collapses access immediately; authored materials (templates, guidance, library contributions) persist — the organization owns content, not the account.
- **Google surface note:** a hostile/compromised account wiping Drive renders or Chat spaces causes zero canonical loss; all renders rebuild from Sanctuary (14.1 canonical rule).

### 14.6 Acceptance criteria added
- AC25: An MC template publishes once and is instantly pullable by all pod ACs; LN instantiates the current version for a new client; a Drive folder wipe or OAuth revocation leaves the canonical library intact and re-renderable.
- AC26: A published org_library entry cannot be hard-deleted or edited in place via any application path (attempted delete produces a soft-archive request requiring Admin approval); versions chain correctly.
- AC27: Restore drill — a simulated mass-delete triggers the Queens circuit breaker + RED alert; PITR restores the database to pre-event state; Ring 2 backups are verifiably immutable within retention and inaccessible with production credentials; Ring 3 export decrypts only with Admin-held keys.
- AC28: MC red-team test — a test MC account attempting (a) any write/delete on assistant-scoped client data receives 404/absent-endpoint, not 403; (b) bulk template archiving beyond quota is auto-held with RED alert; (c) any role-change API call from a non-Admin session fails with no state change; (d) bulk operations without fresh MFA are refused; (e) full Drive-render + Chat-space wipe by the account results in complete re-render from canonical with zero data loss.

---

## 15. v1.5 addendum — Clinical compliance & safety (EU + US; certified/licensed dual-track)

### 15.1 Credential registry & relationship classification (drives everything below)
```sql
CREATE TABLE coach_credentials (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  coach_id UUID NOT NULL REFERENCES coaches(id),
  credential_class TEXT NOT NULL CHECK (credential_class IN ('licensed_clinical','certified_coach')),
  credential_type TEXT NOT NULL,            -- e.g. LMFT, LCSW, PhD-Lic, ICF-PCC
  jurisdiction TEXT NOT NULL,               -- state/country of license or cert body
  identifier TEXT NOT NULL,
  verified_at TIMESTAMPTZ NOT NULL,         -- pre-account verification record (existing policy)
  verified_by UUID NOT NULL,                -- admin actor
  expires_at TIMESTAMPTZ,
  UNIQUE (coach_id, credential_type, jurisdiction)
);
ALTER TABLE clients ADD COLUMN relationship_class TEXT NOT NULL DEFAULT 'coaching'
  CHECK (relationship_class IN ('coaching','clinical'));
ALTER TABLE clients ADD COLUMN client_jurisdiction TEXT;   -- EU member state / US state
```
- Account activation requires ≥1 verified, unexpired credential (codifies existing verification policy). Expiry → automated re-verification workflow; lapsed credential → account suspended from client-facing activity (not deleted), Chat + Admin alert.
- relationship_class is set at client intake from the coach's credential_class and service agreement; it drives vocabulary, retention, disclaimers, and compliance track per relationship. VOCABULARY RULE (binding): 'treatment plan' and clinical terminology render only for relationship_class='clinical'; coaching relationships use 'care plan'/'coaching plan' across ALL surfaces (UI, LN outputs, Docs, emails).

### 15.2 Erasure architecture — crypto-shredding (resolves the 14.x immutability ↔ GDPR Art. 17 conflict)
- Per-client data-encryption keys (envelope encryption): all client-identifiable content — DB fields, R2 objects (voice transcripts, docs, audio), email_draft bodies — encrypts under the client's key; keys stored in a dedicated keystore, mirrored (encrypted) in Ring 2/3.
- Erasure = key destruction + tombstone: renders every copy (live, PITR, object-locked backups, Ring 3) permanently unreadable WITHOUT touching immutable/backup architecture. Erasure requests: identity-verified → legal-hold + retention check (15.3) → Admin approval → key destruction, completed within jurisdictional windows (GDPR: 30 days default).
- Crystals: client-derived crystals are ANONYMIZED AT CREATION (Stage filter enforces: no names, no re-identifiable specifics survive crystallization); anonymized crystals fall outside personal data and survive erasure. Crystals failing the anonymization check are rejected, not stored. Coach-derived crystals (voice/philosophy) key under the coach.
- US track: erasure honors CCPA/state-law requests under the same machinery; clinical-class records check retention first (15.3).

### 15.3 Retention schedule & legal hold
```sql
CREATE TABLE legal_holds (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scope_type TEXT NOT NULL CHECK (scope_type IN ('client','coach','matter')),
  scope_id UUID NOT NULL, reason TEXT NOT NULL,
  placed_by UUID NOT NULL, placed_at TIMESTAMPTZ NOT NULL DEFAULT now(), released_at TIMESTAMPTZ
);
```
- Retention matrix (config, per relationship_class × jurisdiction): clinical-class records retain per applicable state/EU minimums (commonly 6–10 yrs US, state-dependent; configured per jurisdiction, reviewed by counsel — O6); coaching-class defaults to contract + configurable period.
- Precedence (binding): active legal_hold > retention minimum > erasure request (GDPR Art. 17(3)(b) legal-obligation exemption applies only where a genuine retention duty exists; otherwise erasure proceeds). Holds freeze key destruction and archival purges for their scope; placement/release is Admin-gated and Queens-logged.

### 15.4 Crisis response protocol (completes the crisis screen)
- Acknowledgment SLAs: crisis alert unacknowledged by assigned coach within T1 (config, e.g. 15 min) → escalate to master coach; T2 → Admin/on-call. Escalation rides the Chat rail + phone/SMS fallback for crisis class only.
- After-hours: per-pod on-call schedule (config); LN always delivers jurisdiction-appropriate crisis resources to the client immediately (in-app or email reply template per channel) while human escalation proceeds — scripts are admin-approved content, versioned in the org library.
- Mandated reporting: for licensed_clinical coaches, abuse/neglect disclosures trigger a guided reporting workflow (jurisdiction-specific duty documentation, timestamps, coach attestation); records auto-placed under legal hold. Certified-coach track surfaces guidance to escalate to licensed/master oversight.
- All crisis events, acks, escalations, and reports are append-only audit records.

### 15.5 Inbound email injection defense (closes the channel created in 13.1/5.B)
- Email bodies are DATA-ONLY to all parsers: structured extraction prompts that cannot execute instructions found in content; extraction output is schema-validated before any DB write.
- Any LN draft generated from inbound content is (already) human-review-gated — now treated as a TESTED defense: injection suite (instruction-smuggling, task-state manipulation, disclosure elicitation, HTML/attachment vectors) runs at the gate and in CI on prompt changes.

### 15.6 LN clinical-output evaluation harness (Queens-owned)
- Golden set: curated transcripts/sessions with known-correct briefs, extracted tasks, and summaries (both relationship classes).
- Regression: every LN prompt/model change replays the golden set; drift beyond thresholds blocks deploy (YELLOW) — accuracy of briefs/tasks, fabrication rate on client-facing drafts (services, prices, claims), vocabulary-rule compliance (15.1).
- Live sampling: small % of coach-approved outputs periodically re-scored; trends reported to Admin.

### 15.7 Processor/vendor map (binding routing rules)
- Google Workspace (DPA + BAA where applicable), Azure (BAA), Cloudflare, DigitalOcean: approved for respective flows per existing architecture.
- SendGrid: PROSPECT MARKETING ONLY (campaign drips, newsletters to non-clients/prospects). All CLIENT-directed email (habit tasks, follow-ups, newsletters to active clients) routes via the coach's Gmail (1:1, human-approved) — consistent with P2 and avoiding a non-BAA processor learning clinical relationships. Newsletter lists therefore segment client vs prospect at send time.
- Per-coach sending domains: SendGrid domain authentication (SPF/DKIM) is a coach-onboarding step with guided setup; unauthenticated coaches send from a Sanctuary-authenticated subdomain until complete.
- EU data residency: assess EU-region pinning for EU-client data (O7).

### 15.8 Consent versioning + client-experience guards
- consent_records gain version + document_ref; consent-language changes trigger re-consent flows (grandfathering rules per counsel); supervising-master disclosure (13.2) and Google-exposure consent (P4) are versioned instruments.
- Client nudge-frequency caps: LN task check-ins rate-limited per client (config) — monitoring must never become pestering; clients can mute check-ins without losing task delivery.

### 15.9 Open items added (flag, don't guess)
- O6: Retention matrix values per jurisdiction — counsel review required before launch.
- O7: EU data-residency decision (region pinning vs SCCs posture).
- O8: On-call scheduling mechanics (per-pod vs org-wide) and SMS provider for crisis-class escalation.
- O9: LAUNCH GATE / START IMMEDIATELY IN PARALLEL — Google OAuth restricted-scope verification for Gmail scopes (app verification + CASA security assessment; weeks-to-months on Google's clock; development proceeds in test mode meanwhile, but coach-facing launch is blocked until cleared). Initiate at build day one.
- O10: The plan agent's decomposition must include an internal integration order within the single push (which workstream seams wire and test first) so integration risk surfaces early despite the single release moment.

### 15.10 Acceptance criteria added
- AC29: A verified-credential coach activates; a lapsed credential suspends client-facing activity with alerts; vocabulary audit shows zero clinical terminology on any surface of a coaching-class relationship.
- AC30: Erasure drill — key destruction renders the test client's data unreadable in live DB, PITR restore, and Ring 2 backup; anonymized crystals persist and contain no re-identifiable content; erasure completes inside the jurisdictional window; an active legal hold correctly blocks the same request.
- AC31: Crisis drill — unacknowledged alert escalates per SLA chain to Admin; client receives jurisdiction-appropriate resources immediately on both channels; mandated-reporting workflow produces a complete, held, append-only record.
- AC32: Injection suite — smuggled instructions in inbound email produce no unauthorized DB writes, no task-state manipulation, no disclosure content in drafts; all malicious samples land in human review or rejection.
- AC33: Eval harness — golden-set regression runs and blocks on threshold breach; fabrication checks pass on client-facing draft samples.
