# Coach Portal — Feature Breakdown & Client Connection Map

**Purpose:** Internal review document for Coach Portal marketability. Maps every production feature to its tab, explains what it does for coaches, and shows how it connects to client accounts.

**Production surface:** `coach.sovereignsanctuary.net` — Flutter web app branded **Coach Command**  
**Primary implementation:** `CoachDashboardScreenV2` in `mobile/lib/updated_screens.dart`  
**Auth:** WebSocket bridge login with `expected_role: "COACH"`; REST calls use bearer token from profile  
**Last verified against codebase:** July 2026

---

## Executive Summary

The Coach Portal is a 10-tab command center for licensed therapists and practice owners. It unifies caseload management, scheduling, AI-assisted clinical intelligence, adversarial training (DOJO), session review (Classroom), practice financials, secure file management, and assistant supervision into one surface.

**The marketable differentiator:** Every client-facing feature is wired to a real client account in PostgreSQL — not a generic CRM row. Assignment fields, session history, Nevedal emotional coherence metrics, conversation memory, Sensitive Clinical Bridge enrollment, and billing all share the same identity spine. Coaches see one truth; clients experience continuity across chat, sessions, and crisis pathways.

---

## Portal Architecture at a Glance

| Layer | What it is |
|-------|------------|
| **UI** | 10 tabs + Settings (gear) + live-session overlays |
| **Real-time** | WebSocket bridge (`coach_*` handlers) |
| **REST** | FastAPI routers under `/api/coach`, `/api/sessions`, `/api/classroom` |
| **Client identity** | `users.username` + `hardware_id` + `profile_data` JSONB |
| **Assignment spine** | `coach_id`, `assigned_coach_id`, `assigned_coach` (all three must align) |

### Shared filters (Clients, Insights, Briefings)

| Filter | Shows |
|--------|-------|
| **All** | Full roster grouped by family / company; individuals separate |
| **Clients** | Every client as an individual row |
| **Family** | Only clients with `family_id`, grouped |
| **Coach-Only** | `COACH_ONLY` tier clients |
| **Company** | Corporate-assigned clients, grouped by `company_id` |

---

## Tab-by-Tab Feature Inventory

### Tab 0 — CLIENTS

**Purpose:** At-a-glance caseload command — who is assigned, how they are grouped, and who needs attention first.

| Feature | What it does | Why coaches care |
|---------|--------------|------------------|
| **Folder-grouped roster** | Clients organized by family, company, group, or as individuals | Mirrors how therapists actually think about caseloads (couples, EAP cohorts, corporate groups) |
| **Risk badges** | Visual indicator from Nevedal `risk_level` | Triage without opening every chart |
| **Subscription / plan badges** | Tier and plan visibility per client | Billing and feature-gate awareness at roster level |
| **Nevedal snapshot** | C_emo, GAP, coherence fields on each card | Objective emotional signal — not just "client seemed better" |
| **Search & filter bar** | Five filter modes (shared with Insights/Briefings) | One mental model across tabs |
| **Open Folder** | Jump to FOLDER tab for selected entity | Roster → documents in one click |
| **Empty state** | Clear messaging when no clients assigned | Surfaces assignment/config issues early |

**Client connection:** `coach_get_clients` (WebSocket) returns only clients matching the logged-in coach via `profile_data.coach_id` (primary), `assigned_coach_id`, `assigned_coach` (username), or prior `coaching_sessions` history.

---

### Tab 1 — SCHEDULE

**Purpose:** Full session lifecycle — availability, booking, live sessions, Zoom integration, and consultation enforcement.

| Feature | What it does | Why coaches care |
|---------|--------------|------------------|
| **Calendar** (month/week/day) | Visual schedule with `fetch_coach_calendar` | Single source of truth for the week |
| **Create Session** | Types: Client, Coach (assistant), Family, Group, Corporate, Consultation; duration, notes, free-consult toggle, Zoom | One workflow for every session shape the practice runs |
| **Set My Hours** | Weekly availability editor | Clients book only when the coach is actually open |
| **Block / unblock time** | Availability exceptions | Protects admin time and PTO |
| **Inbound client requests** | Accept / decline / message prospects | Pipeline before assignment |
| **Pending bookings** | Approve or decline client-initiated requests | Coach retains gatekeeping over calendar |
| **Scheduled session cards** | Start Live Session, Zoom menu | Session day operations in one card |
| **Live session lifecycle** | Start/end live session, live notes, dictation | Real-time documentation during the call |
| **Session Assistant overlay** | PMB reconsolidation, crisis baseline, shame index, F-codes, Nate mode toggle | Clinical co-pilot during live work — not post-hoc guessing |
| **Consultation timer** | Countdown for free consultations | Enforces limits; protects coach time |
| **Zoom menu** | Resend link, recording status, archive transcript, pull summary to folder, delete meeting | Recording → Classroom pipeline starts here |
| **Session types** | Family, group, corporate metadata on session row | Multi-member billing and notes stay structured |

**Client connection:** Every scheduled session is keyed to `client_id` (individual hardware ID). Family/group/company IDs are metadata — live work always ties to a person. Availability and booking gates are coach-scoped; session approval triggers billing fields on `coaching_sessions`.

---

### Tab 2 — INSIGHTS

**Purpose:** AI-assisted clinical oversight — per-client Nate modes, therapeutic overrides, and coach↔Nate chat for caseload thinking.

| Feature | What it does | Why coaches care |
|---------|--------------|------------------|
| **AI MODES** | Per-client Nate mode (observe / suggest / challenge) | Coach governs how AI supports each dyad |
| **NEVEDAL REPORT** | Dialog with full quantum emotional coherence report | Objective progress narrative for supervision and outcomes |
| **Insights chat box** | Coach ↔ Little Nate via `/api/coach/nate-chat` | Think through caseload with AI that knows client context |
| **Stats grid** | Total clients, high risk, sessions today, breakthroughs | Practice pulse without exporting spreadsheets |
| **Therapeutic Overrides** | Set/renew/clear pacing, focus domain, clinical hold, mission priority | Coach-level governance over AI behavior per client |
| **Override history** | Audit trail of override changes | Supervision and compliance documentation |
| **Client overview cards** | C_emo, GAP, risk per filtered client; tap to focus | Drill-down from aggregate to individual |

**Client connection:** `_focusedClientId` (hardware_id) drives AI modes, overrides, and chat context. Overrides are per coach–client dyad. Metrics come from `nevedal_metrics` / vault via `coach_get_clients`.

---

### Tab 3 — BRIEFINGS

**Purpose:** Pre-session intelligence — the highest-value client-connected tab for marketability. Everything a coach needs before the client walks in (or joins Zoom).

| Feature | What it does | Why coaches care |
|---------|--------------|------------------|
| **Folder browser** | Split-pane (desktop) or drill-down (mobile) by family/company/client | Same grouping as CLIENTS — no context switching |
| **Coach Briefing header** | Refresh folder-level notes | Shared context for couples/family work |
| **Family members list** | Per-member cards with C_emo / GAP / Quantum | See the whole system, not just the identified patient |
| **View Brief** | Bottom sheet: Nevedal metrics, mood, topics, conversation log, F-codes, intake, Zoom insights | Replaces 20 minutes of chart review |
| **Sensitive Profile pill** | States: hidden, enroll_available, active | Gates Path-C clinical depth without exposing unenrolled clients |
| **Intake button** | Progress dots; opens Intake Form coach panel | Section 1 (client) + Section 2 (coach) completion tracking |
| **Message Client** | Direct coach→client messaging | In-portal outreach without personal SMS |
| **Session notes** | Folder-scoped add/list notes | Annotations persist per family/company folder |
| **Nate's Memory** | Session memory snippets for folder members | What Nate remembers from prior conversations |

**Client connection:** `get_presession_brief` / `/api/coach/presession-brief/{client_id}` requires coach ownership via assignment fields. Brief pulls `conversation_history`, crystals, intake, F-codes, Zoom enrichment, and family members by `family_id`. Sensitive Profile uses **username** as canonical ID (`sensitive_bridge_enrollment`, 16 clinical sections).

---

### Tab 4 — DOJO (Night School)

**Purpose:** Adversarial training ground — sharpen skills on simulated clients before real sessions. Coach development, not client-facing.

| Feature | What it does | Why coaches care |
|---------|--------------|------------------|
| **Embedded Night School DOJO** | WebView/iframe → `night_school_dojo.html` with coach auth | Full DOJO UI without leaving Coach Command |
| **Native fallback** | Persona chips: HOSTILE, CRISIS, SKEPTICAL, MINOR, MANIPULATION | Training when embed unavailable |
| **DOJO tools** | PDF assessments, secure search, case upload, session logs | Case prep and documentation |
| **Judge DOJO extras** | Courtroom debate, LexisNexis case law (Judge tier) | Legal/forensic coach specialization |
| **Ethics gate** | `coach_ethics_version == v1.0_2026` required for mesh/training | Ensures informed consent before advanced tools |

**Client connection:** DOJO sessions are coach-scoped (hardware_id + token). Not linked to live client accounts — but skills trained here directly improve outcomes on assigned clients. DOJO subscriptions surface again under FINANCIALS.

---

### Tab 5 — CLASSROOM

**Purpose:** Session review and professional development — upload or archive session video, run AI analysis, track presence scores.

| Feature | What it does | Why coaches care |
|---------|--------------|------------------|
| **Progress card** | Sessions reviewed, avg presence score, assignments completed/pending | PD tracking for licensure and supervision |
| **Session selector** | Coach's sessions with transcripts (Zoom archive or upload) | Pick which session to learn from |
| **Video upload** | R2 direct multipart upload (large files bypass backend) | Review recording without IT friction |
| **Analysis pipeline** | Transcript analysis, AI synthesis, results display | Objective feedback on therapist presence |
| **Analysis history** | Past classroom analyses | Growth over time |

**Client connection:** Session list filtered by `coach_id`; each row includes `client_id` so analysis ties to a specific dyad. Transcripts often originate from SCHEDULE → Zoom → archive. Videos stored at `classroom_videos/{coach_id}/` in R2.

---

### Tab 6 — TRAINING

**Purpose:** Master/assistant coach development — BLE coaching mesh, supervised hours, and community wisdom.

| Feature | What it does | Why coaches care |
|---------|--------------|------------------|
| **Start Training Session** | Master creates BLE coaching mesh session | Structured associate training with AI evaluation |
| **Join Training Session** | Assistant joins active mesh | Live supervised practice |
| **Community Circle** | Nate-to-Nate peer group wisdom (BLE/NFC mesh) | Peer learning beyond 1:1 supervision |
| **Recent sessions** | REST mesh session history | Audit trail for training hours |
| **21 DOJO training methods** | IPR review, scenario practice, rubric-scored evaluation | Standardized skill development |

**Client connection:** Mesh sessions use `coaching_mesh_sessions` + participants — not client accounts. Supervised hours logged on session end feed `coach_log_hours` / `coach_attest_hours` (licensure). Ethics gate blocks access until coach accepts ethics version.

---

### Tab 7 — FINANCIALS

**Purpose:** Practice revenue — session billing, platform fees, Stripe Connect payouts, DOJO subscriptions, tax compliance.

| Feature | What it does | Why coaches care |
|---------|--------------|------------------|
| **Earnings overview** | Month/YTD earnings, platform fees, net payout, sessions billed | Real money visibility |
| **Coaching rate** | Set fee per session | Default for new sessions |
| **Payment mode** | Coach handles vs platform handles collection | Flexibility for solo vs group practice |
| **Stripe Connect** | Express payout setup | Get paid without invoicing manually |
| **DOJO subscriptions** | Manage DOJO tier subscriptions (7 DOJOs) | Training access billing |
| **Transaction ledger** | Per-session fee breakdown | Dispute resolution and accounting |
| **W-9 submission** | Tax compliance tracking | 1099 threshold readiness |

**Client connection:** `coach_get_financials` aggregates `coaching_sessions` where `coach_id` + `client_id` match approved/billed rows (`coach_fee`, `platform_fee`, `coach_payout`). Rate/mode live in `profile_data`. **Note:** QuickBooks coach integration exists in backend (`/api/coach/quickbooks`) but is not yet surfaced in V2 FINANCIALS UI.

---

### Tab 8 — FOLDER (File Manager)

**Purpose:** Secure document hub — per-client, family, group, and company folders with upload, preview, and client-initiated shares.

| Feature | What it does | Why coaches care |
|---------|--------------|------------------|
| **Folder sections** | Personal, Client, Family, Group, Company | Matches caseload mental model |
| **Auto-population** | Folders created from assigned clients | Zero setup for new assignments |
| **Create folder** | Manual folder creation | Ad-hoc projects and referrals |
| **File upload / preview** | PDFs, images, docs per folder | HIPAA-aligned sharing (R2-backed) |
| **Pending pulls** | Client-requested file shares | Client can push docs to coach securely |
| **Pull summary from Zoom** | From SCHEDULE session menu | Session artifacts land in the right folder |

**Client connection:** REST `/api/coach/folders` — `entity_id` = client `hardware_id` or family/company UUID. Requires assignment via `coach_get_clients`. Files stored in R2 via `folder_api.py`.

---

### Tab 9 — ASSISTANTS

**Purpose:** Master coach oversight — supervise associates, view their caseload metrics, and chat with Nate about hierarchy performance.

| Feature | What it does | Why coaches care |
|---------|--------------|------------------|
| **Assistant metrics cards** | Per-assistant client count, sessions (30d), avg coherence | Supervision without shadowing every session |
| **Assistant chat box** | Nate chat scoped to hierarchy oversight | AI-assisted supervision conversations |
| **Overview stats** | Total assistants, clients, sessions, avg coherence | Practice-wide associate health |
| **Empty state** | Shown when no assistants | Clear UX for solo coaches |

**Client connection:** REST `/api/coach/hierarchy/assistant-metrics` and `assistant-clients/{username}` aggregate across assistants' assigned clients. Invite/revoke via `coach_hierarchy` table. Master coaches also manage invites in **Settings → Hierarchy**.

---

## Settings (Gear Icon) — Cross-Cutting Features

Not a tab, but essential for marketability completeness.

| Section | Features | Client connection |
|---------|----------|-------------------|
| **Profile** | Email, phone, emergency, timezone, specialties, Zoom link, coaching style, auto-accept bookings | Coach profile drives client booking UX and session Zoom links |
| **Practice** | Fee, payment mode | Same fields as FINANCIALS tab |
| **Notifications** | New client, session reminders, crisis alerts, Night School | Crisis alerts tie to client risk events |
| **Biometric login** | Device-local hardware identity | Faster re-auth between sessions |
| **Hierarchy** | Invite assistant, view master, supervised hours export, request master status | `coach_hierarchy` — assistants inherit visibility into master's clients |
| **Google Calendar** | OAuth sync | External calendar parity |
| **Payment methods** | Stripe customer payment methods | Client billing infrastructure |

---

## Live Session Overlays (Cross-Tab)

| Overlay | Trigger | Purpose | Client link |
|---------|---------|---------|-------------|
| **Session Assistant** | Live session from SCHEDULE | Real-time PMB, crisis, F-code, shame, Nate toggle | `session_id` + `client_id` |
| **Consultation timer** | Free consultation session | Enforces consult limits per client username | REST consultation-status |
| **View Brief sheet** | BRIEFINGS → View Brief | Full presession brief without leaving flow | `client_id` |
| **SensitiveClinicalProfileScreen** | Sensitive Profile pill | 16 sections: embodiment, thresholds, addictions, codewords, triggers, legal, activity log | `username` (Sensitive Bridge) |
| **IntakeFormCoachPanel** | Briefings intake button | Coach-editable intake Section 2 | Client username |

---

## Sensitive Clinical Profile — 16 Sections

Opened from Briefings when enrollment is active. Marketable as **Path-C clinical depth** — beyond generic EHR fields.

1. Embodiment Phase  
2. Thresholds (novelty/arousal vs population preset)  
3. Substance Status  
4. Sex Addiction  
5. Gambling  
6. Gaming  
7. Spending Compulsion  
8. Food Compulsion  
9. Work Compulsion  
10. Codependency  
11. Codewords  
12. Trigger Dates  
13. Polyvictim Layers  
14. Legal Status  
15. Safe Silence Mode  
16. Activity Log  

Plus: Framework menu, Path-C enrollment dialog, population type banner.  
API: `/api/coach/sensitive-profile/{username}/...`

---

## Client Account Connection Tree

How Coach Portal features anchor to the client record — and why that matters for marketing.

```
CLIENT ACCOUNT (PostgreSQL users + profile_data)
│
├── IDENTITY
│   ├── username ..................... REST sensitive-profile, conversation_history, voice
│   ├── hardware_id (CLIENT_*_ID) .... WebSocket briefs, sessions, folders, overrides
│   └── profile_data (JSONB) ......... Assignment, family, tier, fees, overrides, intake
│
├── ASSIGNMENT SPINE (why coaches see clients at all)
│   ├── coach_id ..................... Primary — coach_get_clients checks FIRST
│   ├── assigned_coach_id ............ Legacy hardware ID fallback
│   ├── assigned_coach ............... Username fallback (e.g. "CoachN")
│   └── coaching_sessions.coach_id ... Historical fallback if profile fields missing
│       └── ⚠ Marketing point: Triple-field consistency = zero "invisible clients"
│
├── GROUPING (how roster/folders/briefings organize)
│   ├── family_id .................... Couples/family briefings, family sessions, folder
│   ├── group_id ..................... Group sessions (e.g. AA-Meeting101)
│   ├── company_id / company_name .... Corporate EAP cohorts
│   └── subscription_plan / tier ..... COACH_ONLY filter, feature gates
│
├── CLINICAL SIGNAL (objective outcomes story)
│   ├── nevedal_metrics / vault metrics.json
│   │   └── CLIENTS risk badges → INSIGHTS reports → BRIEFINGS View Brief
│   ├── conversation_history ......... BRIEFINGS conversation log, Nate memory
│   ├── nate_intelligence_crystals ... Crystal recall in briefs and Nate chat
│   └── sensitive_bridge_enrollment .. BRIEFINGS Sensitive Profile pill → 16 sections
│
├── SESSION LIFECYCLE (revenue + continuity)
│   ├── coaching_sessions
│   │   ├── client_id (required) ..... Every live session → one person
│   │   ├── coach_id ................. FINANCIALS ledger, CLASSROOM list
│   │   ├── family_id / group_id / company_id ... Multi-member session types
│   │   └── Zoom archive ............. SCHEDULE → CLASSROOM transcript pipeline
│   └── coach_get_pending_bookings ... SCHEDULE approval queue
│
├── COACH GOVERNANCE (AI safety per dyad)
│   ├── therapeutic_overrides ........ INSIGHTS overrides per client
│   ├── coach_ethics_version ......... Gates DOJO + TRAINING
│   └── intake_summary ............... BRIEFINGS intake progress dots
│
└── DOCUMENTS & BILLING
    ├── folder entity_id = hardware_id or family/company UUID
    ├── coaching_fee / payment_mode on coach profile → session defaults
    └── F-codes in brief .............. Billing + clinical coding suggestions
```

---

## Feature → Client Connection Matrix (Marketing Quick Reference)

| Coach Portal feature | Client account touchpoint | Why it matters (marketable value) |
|---------------------|---------------------------|----------------------------------|
| Client roster | `coach_id` + assignment fields | Coaches only see *their* caseload — no CRM clutter |
| Risk / C_emo badges | `nevedal_metrics`, vault | **Objective outcomes** — not subjective notes alone |
| View Brief | `client_id`, `conversation_history`, crystals | **AI prep** — walk in informed |
| Sensitive Profile | `username`, `sensitive_bridge_enrollment` | **Clinical depth** for complex cases (addictions, trauma, legal) |
| Schedule session | `client_id` on `coaching_sessions` | Sessions bill correctly; history stays with the person |
| Live Session Assistant | `session_id` + `client_id` | **In-session AI** — crisis/PMB/F-code at the moment of care |
| Family briefings | `family_id` → all members | **Systemic therapy** — see the whole family field |
| Corporate filter | `company_id` | **EAP / corporate** practice segment |
| Folder per client | `entity_id` = `hardware_id` | Documents follow the client, not the coach's laptop |
| Financials ledger | Billed `coaching_sessions` | **Transparent revenue** per client session |
| Classroom analysis | `client_id` on session row | PD tied to real dyads coaches actually run |
| Assistant metrics | Assistants' assigned clients | **Scale the practice** without losing oversight |
| Therapeutic overrides | Per `client_id` | Coach controls AI — **sovereignty**, not black-box automation |
| Intake panel | Client + coach sections | Structured onboarding — **faster time-to-value** |

---

## What Is NOT Client-Linked (Coach-Only)

| Feature | Scope | Marketing framing |
|---------|-------|-------------------|
| DOJO / Night School | Coach `hardware_id` | **Train before you treat** — adversarial scenarios |
| TRAINING mesh | `coaching_mesh_sessions` | **Supervise associates** with rubric-scored AI |
| Community Circle | BLE peer mesh | Peer wisdom — coach community |
| DOJO subscriptions | Coach Stripe | Professional development investment |
| W-9 / Stripe Connect | Coach profile | Practice infrastructure |

---

## Suggested Marketing Themes by Tab

| Tab | Headline angle | Proof point |
|-----|----------------|-------------|
| CLIENTS | "Your caseload, objectively prioritized" | Nevedal risk + coherence on every card |
| SCHEDULE | "One calendar for every session shape" | Individual, family, group, corporate, consult |
| INSIGHTS | "AI that answers to you, not the other way around" | Therapeutic overrides per client |
| BRIEFINGS | "Walk in knowing what happened since last session" | Conversation log + crystals + Zoom insights |
| DOJO | "Spar before the real session" | 7 DOJO tiers, adversarial personas |
| CLASSROOM | "Review your presence, not just your notes" | AI session analysis + presence scores |
| TRAINING | "Scale supervision without losing quality" | Mesh + supervised hours attestation |
| FINANCIALS | "Session revenue without spreadsheet chaos" | Per-session ledger + Stripe Connect |
| FOLDER | "Client documents that stay with the client" | R2-secured, assignment-gated folders |
| ASSISTANTS | "See your practice through your associates" | Aggregate coherence across assistant caseloads |

---

## Gaps & Roadmap Notes (for honest marketing)

| Item | Status | Implication |
|------|--------|-------------|
| QuickBooks coach UI | Backend ready; not in V2 FINANCIALS tab | Mention as "coming" or backend-only |
| Legacy 5-tab `CoachPortalScreen` | Superseded; not routed from login | Ignore for marketing — V2 is production |
| Admin coach tools (`the_eye_coaches.html`) | Sovereign Command only | Not part of coach-facing portal |

---

## Appendix: Primary API Surfaces

### WebSocket (`coach_*` — selection)

- Roster: `coach_get_clients`
- Brief: `get_presession_brief`, `coach_get_client_briefing`
- Schedule: `fetch_coach_calendar`, `coach_get_pending_bookings`, `coach_start_live_session`, `coach_end_live_session`
- Availability: `coach_get_my_availability`, `update_availability`, `coach_block_time`
- Financials: `coach_get_financials`, `coach_set_fee`, `coach_set_payment_mode`
- Hierarchy: `coach_invite_assistant`, `coach_log_hours`, `coach_attest_hours`
- Overrides: `coach_set_client_override`, `coach_get_client_override`
- Session assistant: `session_assistant_open`, `session_assistant_checkin`

### REST (selection)

- `/api/coach/presession-brief/{client_id}`
- `/api/coach/sensitive-profile/{username}/...`
- `/api/coach/folders/...`
- `/api/coach/nate-chat`
- `/api/coach/hierarchy/...`
- `/api/coach/mesh/...`
- `/api/sessions/schedule`, `/api/sessions/{id}/zoom/...`
- `/api/classroom/...`

---

*Document prepared for Coach Portal marketability review. Update when tabs or assignment logic changes.*
