# YubiKey Tab Gate + 2h Timer + Recent Activity — Verification Before Build

## 1. What You Asked For (Clarified)

- **Option A timer**: Per tab. When admin enters a tab (after YubiKey tap), a **120-minute timer** starts. They can leave before 120 mins; pressing YubiKey to re-enter **any** tab **restarts the timer**. So: one 120-min window that restarts on each YubiKey-gated entry.
- **YubiKey required**: To open any of these from the Command landing page: My Clients, Calendar, Crisis Center, Users, System, Marketplace, SkyEye, PMB, Token Lab, GKM, Discounts, QuickBooks, Pre-Session Brief, Live Sanctuary Brief, Ask Little Nate, User Management, Coach Approvals, Family Management, View All Tabs, Refresh Tabs, Settings gear. No YubiKey → stay on landing (or push back to Command).
- **Recent Activity (live ticker)**: Show admin tab activity so you can see who opened which tab, when, and from which IP. If you’re in SkyEye and never opened System, but the ticker shows System being viewed at the same time, you can treat that as suspicious. Since you’re the only admin, another IP = possible compromise. You want to be able to **click a recent activity row and activate HELIX defense** if Hive didn’t already catch it.
- **Failed YubiKey (2+)**: If Hive Defense (or the backend) sees **more than two failed YubiKey attempts**, **do not freeze** — instead **push that user out to login again** and require YubiKey at login. So: 2+ failed WebAuthn verifications → force logout (revoke session, redirect to login), not Sentinel freeze.

---

## 2. Current State (Verified in Codebase)

### 2.1 Command landing page and tab navigation

- **command.html** is the main dashboard. It has:
  - In-page tabs: Command (dashboard), Clients, Calendar, Crisis (via `switchTab('command'|'clients'|'calendar'|'crisis')`).
  - **navTo()** opens other pages: `my_clients.html`, `calendar.html`, `crisis_center.html`, `users.html`, `system.html`, `skyeye.html`, `pmb_reports.html`, `token_lab.html`, `gkm.html`, `discounts.html`, `quickbooks.html`, `presession_brief.html`, `ask_nate.html`, `coach_approvals.html`, `family_merge.html`, etc.
- There is **no** YubiKey gate before opening any tab or before calling `navTo()`. Implementing the gate means: intercepting every tab click / navTo (and “View all”, “Refresh”, Settings gear), showing a “Tap YubiKey to enter” step, calling `/api/admin/webauthn/auth-options` then `/api/admin/webauthn/auth-verify`; only on success navigate and start the 2h timer.

### 2.2 Recent Activity / live ticker

- **command.html** has a “Recent Activity” card with `id="activityFeed"`. It currently shows **only** a static line: “Dashboard initialized”. It is **not** wired to any live data.
- **Audit log**: The bridge has `admin_get_audit_log` (bridge_server.py ~12148); it reads from **audit_log** and returns `audit_log_data` with `entries`. The dashboard renders that in **auditLogBody** via `renderAuditLog()`, **not** in `activityFeed`. So:
  - **activityFeed** = currently static; can be repurposed for “live” admin tab activity.
  - **audit_log** table exists (001_schema.sql): `logged_at`, `admin_id`, `admin_username`, `admin_role`, `ip_address`, `action_type`, `target_type`, `target_id`, `description`, etc. The bridge query uses `action_type`, `admin_id`, `target_id`, `description`, `ip_address`, `logged_at`.
- **action_type** has a CHECK constraint (019 + later migrations). Values used elsewhere include e.g. `ACCOUNT_FROZEN`, `ADMIN_DELETE_USER`, `ADMIN_PII_EXTRACTION_ATTEMPT`. To log tab entry we need a new allowed value (e.g. `ADMIN_TAB_ENTRY`) and a migration to add it.
- There is **no** existing “live ticker” that pushes or polls admin tab views with admin name + IP. So we need:
  - **Backend**: When an admin passes the YubiKey gate and enters a tab, write a row (e.g. to `audit_log` with `action_type = 'ADMIN_TAB_ENTRY'`, or a dedicated table) with admin identifier, tab/page name, timestamp, IP.
  - **Dashboard**: Either poll (e.g. `admin_get_audit_log` filtered to tab entries, or a new endpoint) or receive a WebSocket push so that the **activityFeed** (or a dedicated “live ticker” area) shows recent admin tab activity with admin + IP. Display should be “live” enough that you can see concurrent use (e.g. “System” opened while you were in SkyEye).

### 2.3 “Click recent activity → activate HELIX defense”

- **HELIX** in this codebase = **Trinity Helix** (rotation, containment) and **Projected Helix** (offensive wrap; requires human approval via SMS/email). There is **no** existing UI that lets you “click a recent activity row and activate HELIX defense.”
- So this is **new behavior** to define and implement. Options (product decision):
  - **A)** From a recent-activity row (admin + tab + IP), a button/link “Activate defense” that e.g. opens Hive Defense (SkyEye → Hive Defense) with that IP or session in context.
  - **B)** Call an API to escalate DEFCON or propose containment for that IP/session.
  - **C)** Trigger a “Projected Helix” or other response (e.g. alert, ban IP) as defined by your security playbook.
- Implementation will follow whatever product choice you make (e.g. new REST or WebSocket action + dashboard handler).

### 2.4 Hive Defense and failed YubiKey attempts

- **Sentinel** (bridge_server.py + sentinel.py) scores anomalies and **freezes** the session when the score exceeds a threshold. Unfreeze is via **WebAuthn auth-verify** (YubiKey tap). There is **no** logic that says “after 2+ failed YubiKey attempts, don’t freeze — force logout instead.”
- **WebAuthn auth-verify** lives in **backend/app/routers/admin.py** (`POST /api/admin/webauthn/auth-verify`). On failure it raises `HTTPException(400, "No matching credential found")`. There is **no** per-admin or per-session counter for failed WebAuthn attempts and **no** “force_logout” response.
- So “Hive Defense notices more than two failed YubiKey attempts” must be implemented as follows (backend + dashboard, not a separate Hive worker):
  - **Backend**: In `webauthn_auth_verify`, on verification failure:
    - Increment a “failed webauthn attempts” counter (per admin or per session; store in Redis or in-memory with short TTL).
    - If counter **≥ 2**:
      - Clear the counter.
      - Invalidate the admin’s session (e.g. revoke token in Redis so subsequent API calls get 401).
      - Return a structured response the dashboard can interpret, e.g. `{ "force_logout": true, "reason": "too_many_failed_yubikey" }` (and do **not** freeze Sentinel).
    - If counter < 2, return 400 as today (and optionally include `failed_attempts: 1` so the UI can show “1 failed attempt; one more will log you out”).
  - **Dashboard**: On receiving `force_logout: true`, clear local session and redirect to login (command.html or the admin login flow). Do **not** trigger Sentinel freeze UI.

---

## 3. Summary: What Exists vs What Must Be Built

| Piece | Exists? | Notes |
|-------|--------|--------|
| Command landing + tab list + navTo | Yes | command.html; all targets you listed are present |
| YubiKey gate before opening any tab | No | Must add: intercept tab/navTo → auth-options → auth-verify → then navigate and start timer |
| 120-min timer, restart on re-entry | No | Must add: per-session or per-tab timer; on expiry push back to Command landing; on new YubiKey-gated entry restart timer |
| Recent Activity as live ticker (admin + tab + IP) | No | activityFeed is static; audit_log exists but no ADMIN_TAB_ENTRY; need logging + feed (poll or push) |
| Click activity row → “activate HELIX defense” | No | Need product definition then implementation (e.g. open Hive with IP, or call escalate/contain API) |
| 2+ failed YubiKey → force logout (no freeze) | No | auth-verify has no failure counter; no force_logout response; need counter + session revocation + dashboard redirect |

---

## 4. Recommended Implementation Order

1. **Backend: failed WebAuthn handling**  
   In `admin.py` `webauthn_auth_verify`: add failure counter (e.g. Redis key by admin/session), on ≥2 failures revoke session and return `force_logout: true`; dashboard on that response redirects to login.

2. **Backend: log tab entry**  
   When dashboard (or bridge) records “admin X passed YubiKey and entered tab Y”, write to `audit_log` (or dedicated table). Add `ADMIN_TAB_ENTRY` to `audit_log.action_type` CHECK via migration.

3. **Dashboard: YubiKey gate for tabs**  
   Intercept every “enter tab” (in-page switch + navTo + View all, Refresh, Settings). Require auth-options → auth-verify; on success allow navigation and start/restart 120-min timer.

4. **Dashboard: 120-min timer**  
   Single 120-min timer that restarts on each YubiKey-gated entry. On expiry, redirect to Command landing and require YubiKey again to open any tab.

5. **Dashboard: Recent Activity live ticker**  
   Populate activityFeed from tab-entry events (poll `admin_get_audit_log` filtered to tab entries, or new endpoint/WebSocket). Show admin (name/username), tab, time, IP. Optional: “Activate defense” per row once that action is defined.

6. **“Activate HELIX defense” from activity row**  
   After product decision (e.g. “open Hive Defense with this IP” or “escalate DEFCON for this session”), add the button and the API/route.

---

## 5. Schema / Constraint Change

- **audit_log**: Add `'ADMIN_TAB_ENTRY'` to the `action_type` CHECK constraint (new migration). When logging tab entry, set e.g. `description = "Tab: SkyEye"`, `target_id` or metadata as needed, `ip_address` = request IP, `admin_id` / `admin_username` = current admin.

This verification is complete. Implementation can proceed in the order above once you confirm.

---

## 6. Implemented (Mar 2026)

- **Backend**: Failed WebAuthn counter in Redis (`webauthn_fail:{hw_id}`), on ≥2 failures session revoked and `422` body `{ force_logout: true, reason: "too_many_failed_yubikey" }`; dashboard redirects to command.
- **Migration**: `109_audit_log_admin_tab_entry.sql` adds `ADMIN_TAB_ENTRY` to `audit_log.action_type` CHECK.
- **Backend**: `POST /api/admin/audit/tab-entry`, `GET /api/admin/audit/tab-activity`; `POST /api/hive-defense/v4/defense/activate-from-activity` (human-approved DEFCON escalation + optional containment for IP).
- **Dashboard**: command.html — YubiKey gate before any `navTo()` (2h window, restart on re-entry), tab-entry logging, Recent Activity live ticker (poll 20s), "Activate defense" button calls activate-from-activity (level 4, deploy_containment for IP). 2h expiry clears `last_yubikey_at` on Command; skyeye.html has 2h redirect back to command. Settings gear gated via `navTo('settings.html')`.
