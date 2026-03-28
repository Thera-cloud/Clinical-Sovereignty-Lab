---
name: Dual-CLI unified master plan
overview: Single master plan for the dual-CLI (CLI-Cloud / CLI-Mac) architecture: operational and source-code repair, admin approval, zero-cost rule, Admin Terminal UI in SkyEye, and second YubiKey gate for the Command Terminal tab. CLI code lives in separate repos; this repo holds shared schema, dashboard/API, and the Command Terminal tab. No overlay with dual-brain or hallucination defense.
todos:
  - id: migration-136
    title: Migration 136 — repair_proposals, approval_decisions, source_repair_requests, autonomous_executions
    status: done
  - id: admin-api
    title: Admin API — GET /pending, POST /approve, GET /history, POST /corrective-request
    status: done
  - id: command-terminal-ui
    title: Command Terminal tab + second YubiKey gate in skyeye.html
    status: done
  - id: cli-auth
    title: CLI service tokens (CLI_CLOUD_TOKEN, CLI_MAC_TOKEN) — env-based scoped auth
    status: done
  - id: cli-api
    title: CLI-facing endpoints — submit-proposal, submit-source-request, approval-status, completion-report, log-execution
    status: done
  - id: cli-notify
    title: Admin email notification on new proposals, source requests, and conflicts
    status: done
  - id: cli-blob
    title: R2 blob storage — build reports (cli-builds/), daily backups (nate-cli-backups/)
    status: done
  - id: cli-conflict
    title: Disagreement protocol — same-target conflict detection, both proposals → conflict status
    status: done
  - id: cli-deploy
    title: Deploy migration, router, main.py, .env tokens to production — all verified live
    status: done
isProject: false
supersedes: "admin_terminal_ui_dual-cli (Sec 13), admin_terminal_ui_yubikey_gate (Sec 13.2), gaps_and_zero-cost (Sec 5/8), cli_dual-governance (Sec 3/4/6), admin-authorized_source_code (Sec 2/3.2), lln-cli_land (Sec 2/5/7)"
---

# Dual-CLI Unified Master Plan

This plan is the single reference for the Little Nate dual-CLI (CLI-Cloud + CLI-Mac) build. It consolidates prior directions so they work together without duplicate or conflicting scope.

**Prior directions merged here:**

| Prior direction | What it contributed | Where in this plan |
|-----------------|----------------------|---------------------|
| LLN-CLI research-grade oversight | Lockout prevention, Command Terminal concept, zero-cost inference, red zone | Section 2, 5, 7 |
| Admin-authorized source code and cross-CLI | Admin direct read/write/execute; either CLI can target the other when admin-authorized | Section 3, 2 |
| CLI dual-governance mutual repair | Read-only own code, cross-CLI repair flow, completion report, history + blob, daily backup, internet search with other-CLI approval, admin email + SkyEye + corrective request | Section 3, 4, 6 |
| Gaps and zero-cost definition | Zero-cost = owner pays nothing unless admin approves; allowlists, approval schema, corrective path, identity, concurrency, red zone, history SOT | Section 5, 7, 8 |
| Admin Terminal UI (dual-CLI) | Tab in SkyEye, CLI toggle, pending/history, corrective request, API | Section 13 |
| Admin Terminal UI YubiKey gate | Second YubiKey required to enter Command Terminal tab after entering SkyEye | Section 13 |

**Out of scope (no overlay):**

- **Dual-brain mutual repair** ([dual-brain_mutual_repair_d336f8f1.plan.md](.cursor/plans/dual-brain_mutual_repair_d336f8f1.plan.md)): Edge/Sovereign R2 heartbeats, edge-queue, crystals. CLIs may read R2/Redis state read-only.
- **Hallucination defense** ([hallucination_defense_architecture_9f29b639.plan.md](.cursor/plans/hallucination_defense_architecture_9f29b639.plan.md)): 10-layer defense. Unchanged; CLIs do not implement it.

---

## 1. Architecture and code location

- **CLI-Cloud** and **CLI-Mac** (CLI-Land) code live in **separate repos**. They share only the **DB/Redis contract** defined in this repo.
- **This repo** owns: PostgreSQL schema (`repair_proposals`, `autonomous_executions`, `source_repair_requests`, `approval_decisions`); Redis key contracts; Admin dashboard and **Command Terminal** tab in SkyEye; admin notification; backend API for CLIs.
- **Dual-brain** remains unchanged; CLIs may consume its R2/Redis outputs read-only.

---

## 2. Authority and approval (admin vs CLIs)

- **Admin (Big Nate):** Only human who can approve permanent or paid changes. Reads all proposals and source-code requests; approves or rejects via **approval_decisions**. Can send corrective requests via Command Terminal. Cannot be locked out; red zone never writable by CLIs.
- **CLI-Cloud / CLI-Mac:** Propose repairs; cannot approve their own changes. Autonomous actions (reversible, zero-cost) logged in `autonomous_executions`; still tied to approval when pre-approved.
- **Connective tissue:** **approval_decisions** references either `repair_proposal_id` or `source_repair_request_id`.

---

## 3. Two flows, two tables, one approval table

### 3.1 Operational repair flow

- **Tables:** `repair_proposals`, `autonomous_executions`.
- **Flow:** Watchers propose or execute autonomous actions; proposals get a row; admin approval recorded in **approval_decisions** (with `repair_proposal_id`). Executor runs repair and updates status.

### 3.2 Source-code repair flow (cross-CLI, admin-authorized)

- **Table:** `source_repair_requests` (or `build_requests`). Fields: id, requester_cli, executor_cli, target, scope, plan, status, completion_report, combined_report, build_id, parent_build_id, timestamps.
- **Flow:** Requester CLI sends request to executor; executor builds plan, writes row, creates **approval_decisions** row; admin approves; executor executes; requester sends completion report; executor writes combined report. History + blob; admin email with link to SkyEye.
- **Approval:** Same **approval_decisions** table; one row per decision with either `repair_proposal_id` or `source_repair_request_id` set.

---

## 4. Shared schema (this repo)

- **repair_proposals** — operational only; add `approval_decision_id` FK when decided.
- **autonomous_executions** — unchanged; optional `approval_decision_id` for pre-approved actions.
- **source_repair_requests** — source-code flow; requester_cli, executor_cli, target, plan, status, completion_report, combined_report, build_id, parent_build_id.
- **approval_decisions** — shared: id, repair_proposal_id (nullable), source_repair_request_id (nullable), approved, decided_at, decided_by, admin_note. Exactly one FK non-null.

Migrations in this repo. CLIs in separate repos use the same DB/Redis contracts.

---

## 5. Zero-cost definition (canonical)

- **Owner cost is infinitely zero** unless admin explicitly approves a paid change.
- **CLIs cannot** spin up paid infra; any such proposal requires admin approval and a cost flag.
- **Allowed without approval:** Existing infra, free tiers (Workers AI, R2 within allowance, sovereign Ollama, home GPU), cache-dump, containers on existing hosts, blob within current buckets.
- **Approval digest:** Surfaces pending approvals so admin can reject paid proposals.

---

## 6. History, blob, daily backup, admin notification

- **History:** Build list and status in DB; full report in **blob** (e.g. `cli-builds/{build_id}/report.json`). Recall by build_id.
- **Daily mutual backup:** Each CLI backs up the **other** side to protected blob (`nate-cli-backups/land/`, `nate-cli-backups/cloud/`). Restore requires **admin approval**.
- **Admin email:** To **admin_nevedalnj@sovereignsanctuary.net** with link to **SkyEye > Command Terminal** (folder of change). **Corrective request:** Admin uses Command Terminal to send request to executor CLI; new source_repair_request with parent_build_id; same approval flow.

---

## 7. Red zone and allowlists

- **Red zone:** Admin identity, roles, credentials, MFA (users table, profile_data auth, webauthn, TOTP, Redis auth keys). No repair may touch these. Enforce allowlists in CLIs and backend.
- **Own-code read allowlist:** CLI-Mac may read allowlisted land paths; CLI-Cloud may read allowlisted cloud paths. Requester may read **target** side for building/verifying requests; only executor writes after approval.

---

## 8. Gaps closure (concise)

- **Requester read access:** Requester has read-only access to target’s allowlisted code.
- **Approval payload:** Standard fields: target, scope, rationale, diff/manifest optional, rollback.
- **Corrective path:** Admin sends corrective to **executor** CLI; new source_repair_request with parent_build_id.
- **Identity:** Document system identity or scoped tokens for CLI-Cloud and CLI-Mac; no red-zone access.
- **Concurrency:** One approved source-code repair per target at a time; completion and history write before next.
- **Internet search:** Other CLI approves query (and optionally result set); plan may cite only approved results.
- **History SOT:** DB for list and status; blob for full report; recall by build_id.

---

## 9. Disagreement protocol

When CLI-Cloud and CLI-Mac propose **conflicting** repairs (same target, incompatible actions): both get conflicts_with set; neither executes until admin resolves via approval_decisions. Conflict rate = governance health metric.

---

## 10. Files and ownership

| Item | Owner | Location |
|------|--------|----------|
| repair_proposals, autonomous_executions, source_repair_requests, approval_decisions | This repo | backend/migrations/ |
| Redis key contract (mac:*, cf:*, cli-cloud:*, cli-mac:*) | This repo | .cursor/rules or doc |
| Admin summary, dashboard widget, email, **Command Terminal tab** | This repo | backend + dashboard (SkyEye) |
| CLI-Cloud watchers/repairers/reporters | Separate repo | sovereign-cli-cloud |
| CLI-Mac watchers/repairers/reporters | Separate repo | sovereign-cli-mac |
| Blob write/recall for builds and daily backups | This repo (API) + CLIs | backend + R2 |

---

## 11. Order of implementation (this repo first)

1. Migration: **approval_decisions**, extend **repair_proposals** with approval_decision_id, add **source_repair_requests**.
2. Backend API for CLIs: submit proposal, submit source_repair_request, read approval status, write completion_report/combined_report.
3. **Admin Terminal UI and second YubiKey gate** (Section 13): tab, CLI toggle, pending/history, corrective request, **second YubiKey required to enter tab**.
4. Admin notification: email with link to SkyEye > Command Terminal.
5. Blob: write/recall for build reports and daily backup keys; restore gated by admin.
6. Command Terminal: corrective request creates new source_repair_request with parent_build_id.

Then implement in **sovereign-cli-cloud** and **sovereign-cli-mac** repos.

---

## 12. Cross-reference summary

- **Dual-brain:** Read-only input; do not duplicate.
- **Hallucination defense:** Unchanged; CLIs do not implement it.
- **Zero-cost and gaps:** Sections 5, 7, 8.
- **Admin-authorized and dual-governance:** Sections 3.2, 4, 6.

---

## 13. Admin Terminal UI and second YubiKey gate (single source of truth)

This section merges the Admin Terminal UI (dual-CLI) spec and the second YubiKey gate. Implement once; no separate plans needed for the tab or the gate.

### 13.1 Where the admin terminal lives

- **Page:** [dashboard/skyeye.html](dashboard/skyeye.html). Admin reaches it via Sovereign Command → SkyEye, then selects the **Command Terminal** tab in the SkyEye sidebar.
- **New tab:** Nav item `data-tab="command-terminal"` (label "Command Terminal" or "CLI Terminal"). Section `<section class="tab-content" id="tab-command-terminal">` with CLI toggle, pending list, history list, corrective request UI; optional chat + preview pane (Claude/Cursor hybrid).

### 13.2 Second YubiKey gate (required before showing tab)

- **Flow:** (1) Admin taps YubiKey to enter Sovereign Command tabs. (2) Admin enters SkyEye. (3) Admin clicks **Command Terminal** tab. (4) **Second YubiKey tap required** to enter that tab. (5) Then show Command Terminal content.
- **Implementation (skyeye.html):**
  - When user clicks Command Terminal nav item, do **not** call `switchTab('command-terminal', this)` directly.
  - Check **separate** session storage key: `last_yubikey_admin_terminal_at` and TTL (e.g. `YUBIKEY_ADMIN_TERMINAL_GATE_MS` = 2 hours or 30 minutes).
  - If missing or expired: show modal "Tap YubiKey to enter Admin Terminal"; run same WebAuthn flow as Sovereign Command: `POST /api/admin/webauthn/auth-options`, `navigator.credentials.get`, `POST /api/admin/webauthn/auth-verify`. On success: set `sessionStorage.last_yubikey_admin_terminal_at`, close modal, then `switchTab('command-terminal', this)`. On failure: do not show tab.
  - Reuse existing webauthn endpoints; no new backend. Use SkyEye auth headers for API calls.
- **Modal:** Add in skyeye.html e.g. `id="yubikeyGateAdminTerminalModal"`. Style from [dashboard/command.html](dashboard/command.html) (`.yubikey-gate-modal`). Copy: "Tap YubiKey to enter Admin Terminal" and "Touch your security key to open the CLI terminal. Timer restarts for [X] minutes."
- **Logout/session clear:** Clear `last_yubikey_admin_terminal_at` when admin logs out or session is cleared so both gates are required again.
- **Optional:** After second YubiKey success, call `POST /api/admin/audit/tab-entry` with `{ tab: "Admin Terminal" }` for compliance.

### 13.3 CLI toggle (required)

- **Control:** Toggle or segmented control: **CLI-Cloud** | **CLI-Mac** (CLI-Land). Selection drives which CLI’s pending proposals, history, and corrective targets are shown.
- **Persistence:** e.g. `sessionStorage.sc_cli_terminal_active`; default CLI-Cloud or last used.

### 13.4 Core UI blocks in the Command Terminal tab

| Block | Purpose |
|-------|--------|
| **CLI toggle** | Switch between CLI-Cloud and CLI-Mac; all data below scoped to selected CLI. |
| **Pending approvals** | List from repair_proposals and source_repair_requests (status pending, selected CLI involved); Approve / Reject; backend writes approval_decisions. |
| **Build / repair history** | Past repairs and builds; filter by selected CLI; link to report or blob recall by build_id. |
| **Corrective request** | For a completed build, admin sends corrective request to executor CLI (new source_repair_request with parent_build_id). |

Optional (Claude/Cursor hybrid): request type (agent / plan / ask / debug), terminal chat (PhD full-stack coder mode), preview pane for outputs.

### 13.5 Backend / API (this repo)

- **List pending:** e.g. `GET /api/nate-agent/pending?cli=cloud|mac` (repair_proposals + source_repair_requests for that CLI).
- **Approve / reject:** e.g. `POST /api/nate-agent/approve`, `POST /api/nate-agent/reject` (proposal id or source_repair_request id); backend writes approval_decisions and updates status.
- **History:** e.g. `GET /api/nate-agent/history?cli=cloud|mac&limit=50`.
- **Corrective request:** e.g. `POST /api/nate-agent/corrective-request` (parent_build_id, description); backend creates new source_repair_request.
- **Terminal chat (optional):** Reuse `POST /api/skyeye/chat` with terminal_cli / context (e.g. cli=cloud|mac, mode=cli_coder).

All endpoints require admin auth (`require_admin`).

### 13.6 Files to add or change

| File | Change |
|------|--------|
| [dashboard/skyeye.html](dashboard/skyeye.html) | Add nav item `data-tab="command-terminal"`; add section `id="tab-command-terminal"` with CLI toggle, pending list, history list, corrective request UI; add **second YubiKey gate**: modal `yubikeyGateAdminTerminalModal`, intercept in switchTab for `command-terminal`, check `last_yubikey_admin_terminal_at`, run auth-options + auth-verify, then show tab; optional chat + preview. Wire load functions when tab shown. |
| Backend router (nate-agent or admin) | Routes: pending, approve, reject, history, corrective-request; schema repair_proposals, source_repair_requests, approval_decisions. |

### 13.7 Summary

- **Tab:** Command Terminal in SkyEye; `id="tab-command-terminal"`.
- **Entry:** **Second YubiKey** required after first YubiKey (Sovereign Command tab entry) and after entering SkyEye. Same webauthn endpoints; separate session key and TTL.
- **CLI toggle:** CLI-Cloud | CLI-Mac; all lists and actions scoped to selected CLI.
- **Content:** Pending approvals, build/repair history, corrective request; optionally request types, terminal chat, preview pane.

This section is the single source of truth for the Admin Terminal UI and the second YubiKey gate. Do not duplicate in separate plan files.
