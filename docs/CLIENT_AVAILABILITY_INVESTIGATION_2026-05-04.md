# Client availability / WebSocket investigation — 2026-05-04

Read-only investigation per request. Source of truth for portal wiring: `docs/coach_portal/_FOUNDATIONAL_SPEC.md`. Scope: why **client** flow shows **“No published hours for this date”** while **CoachN** has recurring availability in PostgreSQL.

---

## Section A — WebSocket failure (URL, path, parity with coach)

### A.1 URLs (grep-equivalent findings)

| Artifact | Location | Value |
|----------|----------|--------|
| Default WS URL (web + native fallback) | `mobile/lib/main.dart` ~`81–98` | `wss://api.sovereignsanctuary.net/ws` when host is `app.*` / `coach.*` or localhost fallback |
| Client schedule screen | `mobile/lib/main.dart` `_ClientScheduleScreenState` ~`10325` | `final String _serverUrl = defaultWsUrl;` — **same URL pattern as coach** when served from `app.sovereignsanctuary.net` |
| Legacy constant | `mobile/lib/updated_screens.dart` ~`67` | Same production host/path |

**Conclusion:** Clients and coaches are intended to use the **same** bridge path **`/ws`** on **`api.sovereignsanctuary.net`**, not `/api/ws`. Any console error on `wss://api.sovereignsanctuary.net/ws` is not explained by “wrong path”; investigate TLS, CF routing to primary (WS must hit primary VPS per load-balancer rules), network, or handshake/auth.

### A.2 Auth pattern (client vs coach)

| Step | Client (`ClientScheduleScreen`) | Coach (`CoachDashboardScreenV2`) |
|------|----------------------------------|-------------------------------------|
| Connect | `WebSocketChannel.connect(Uri.parse(_serverUrl))` ~`10399–10401` | `_connectToBridge()` opens same `defaultWsUrl` pattern |
| First message | `login_request` + `expected_role: "CLIENT"` ~`10405–10409` | `login_request` + `expected_role: "COACH"` (see foundational spec) |

Token-on-connect: **not used** for initial handshake — credentials go in `login_request`, consistent with coach flow.

### A.3 Symptom interpretation

Browser console reports (**from user**): repeated WS failures, uncaught errors, service worker timeout (~4000ms). Those indicate **connect/listen broke before or during login/message handling**. That aligns with bridge logs seen in related work (`pool is closed` immediately after container restart): transient empty/error responses; also aligns with **Cloudflare edge / SW** issues independent of availability SQL.

---

## Section B — Availability fetch flow (UI → bridge → UI)

### B.1 Entry (“View Availability & Book Session”)

- Settings row: `mobile/lib/settings_screen.dart` ~`2960` — navigates to scheduling UX (same product surface).
- Primary implementation: **`ClientScheduleScreen`** in `mobile/lib/main.dart` ~`10308+`.

### B.2 Client state

| Field | Role |
|-------|------|
| `_coachId` | Initialized from `widget.currentUserProfile?['assigned_coach_id']` ~`10392` — **hardware_id string** expected by bridge |
| `_availableSlots` | Filled only from WS message type **`coach_availability`** ~`10441–10445` |
| `_selectedDate` | Set in `_requestAvailability` when user picks/taps a date ~`10534–10536` |

### B.3 Messages

**Outbound**

```json
{"type":"client_get_coach_availability","coach_id":"<_coachId>","date":"YYYY-MM-DD"}
```

(`main.dart` ~`10534–10540`)

**Inbound (success shape)**

- `type`: **`coach_availability`**
- Client reads **`available_slots`** only (~`10441–10445`); server also sends `availability`, `booked_slots`, etc. (`bridge_server.py` ~`12268–12275`)

### B.4 Why “No published hours for this date” is misleading

UI logic (`main.dart` ~`11137–11161`):

- Shows **“No published hours for this date”** when **`_selectedDate != null`** AND **`_availableSlots.isEmpty`**.
- **`_requestAvailability`** sets `_selectedDate` **before** the WS round-trip (~`10534–10536`).
- If **WebSocket never delivers** `coach_availability` (connection failure, login failure, server exception), slots stay empty → **same copy as “coach never published”** even when PostgreSQL has rows.

**Secondary:** Server builds hourly slots and drops any slot with `slot_start <= datetime.datetime.now()` (`bridge_server.py` ~`12265–12266`) using **naive** `target_dt` from `fromisoformat(date)` (~`12188`). That can incorrectly suppress “today’s” slots near timezone midnight server vs client; **not** the primary explanation for a future date like 2026-05-05.

---

## Section C — Database state (CoachN + “client_001”)

Commands run on production pattern: `docker exec nate_postgres psql -U nate_admin -d little_nate` (role **`postgres`** is not the documented production DB user in workspace rules).

### C.1 CoachN identity

| username | hardware_id | users.id (UUID) |
|----------|-------------|-----------------|
| CoachN | COACH_COACHN_ID | `bb431ef1-d9b3-4bc9-bcda-c00683982656` |

### C.2 `coach_availability` rows for CoachN (recurring)

Four recurring rows (non-blocked, `specific_date` NULL), e.g. Mon/Tue/Wed/Fri style coverage with `day_of_week` **0,1,2,4** and wide Tue window **07:00–21:30**.

So **CoachN does have published recurring availability** in the table the bridge reads.

### C.3 Client assignment (“client_001” nuance)

Exact username **`client_001`** returned **no rows**. Rows that match the story (**hardware id CLIENT_001**, assigned CoachN):

| username | hardware_id | profile `assigned_coach_id` |
|----------|-------------|-----------------------------|
| client1 | CLIENT_001 | COACH_COACHN_ID |
| client1b | CLIENT_001B | COACH_COACHN_ID |

**Conclusion:** Assignment for the CLIENT_001 hardware account in prod is **`client1`**, not literal `client_001`. **`assigned_coach_id` is the hardware id string** `COACH_COACHN_ID`, which matches what `client_get_coach_availability` resolves to UUID (`bridge_server.py` ~`12164–12166`).

---

## Section D — Schema status (`coach_availability`)

### D.1 Production `\d coach_availability` (summary)

- **`coach_id`**: **`uuid`**, **NOT NULL**, **FK → `users(id)`**
- **`day_of_week`**: integer 0–6 (check constraint)
- **`start_time` / `end_time`**: `time without time zone`
- **`specific_date`**, **`is_blocked`**, **`recurring`**, etc.
- **No `is_published` column** on production (investigation SQL in the prompt referencing `is_published` does not match live schema).

### D.2 Migration nuance (documented split)

| Migration | Declared shape |
|-----------|----------------|
| `backend/migrations/001_schema.sql` ~`357–374` | `coach_id UUID` → `users(id)`; comment says **0 = Sunday** for `day_of_week` |
| `backend/migrations/081_coach_portal_enhancements.sql` ~`191–201` | **`coach_id TEXT`** alternate shape |
| `backend/migrations/093_schedule_consolidation.sql` | Reconciliation / indexes |

**Active production:** **UUID `coach_id`** — aligned with **`001` + consolidation**, not the TEXT-only **`081`** table definition. Bridge code correctly uses **`SELECT id FROM users WHERE hardware_id = $1`** then queries **`coach_availability` with UUID** (`bridge_server.py` ~`12164–12176`, mirrored in `coach_get_my_availability` ~`13935–13947`).

### D.3 `day_of_week` semantic risk (cross-stack)

Bridge maps integers to names with:

`_DAY_INT_TO_NAME = {0: "monday", 1: "tuesday", ...}` (`bridge_server.py` ~`12162`)

That mapping matches **Python `weekday()` Mon=0 … Sun=6**, **not** the **`001_schema` comment “0=Sunday”`**.

Coach-side inserts use the same UUID-based queries; CoachN’s live rows **do** include Tuesday coverage (`day_of_week = 1`), which matches `strftime("%A").lower() == "tuesday"` for **2026-05-05**. So for this investigation, **schema mismatch is not the blocker** — data and naming align for Tuesday slots **if** the handler runs.

---

## Section E — Recommended fix scope (no code here)

**Primary:** Restore reliable **WebSocket connectivity and login** for clients on `app.sovereignsanctuary.net` (CF WS routing, origin health, bridge/db_pool readiness); update **`ClientScheduleScreen`** messaging so **WS/availability errors** are not shown as **“coach has not published hours.”**

**Secondary:** Align **`client_get_coach_availability`** booked-session query with **`scheduled_start::date`** (not only **`scheduled_at::date`**) when both columns exist, so busy masking matches real session days (`coaching_sessions` has both columns in production; sample rows show **`scheduled_at`** and **`scheduled_start`** can differ by calendar date).

---

## Section F — Service worker note (non-blocking)

Flutter web service worker / `prepareServiceWorker` timeout (~4000ms) indicates **slow or flaky bootstrap**; treat as **separate** from availability SQL. It can compound perceived failures if JS errors abort the app before WS connects.

---

## File references (quick index)

| Topic | File:region |
|-------|-------------|
| Foundational coach WS + schedule handlers | `docs/coach_portal/_FOUNDATIONAL_SPEC.md` |
| Client availability handler | `backend/app/websocket/bridge_server.py` ~`12151–12279` |
| Client UI | `mobile/lib/main.dart` `ClientScheduleScreen` ~`10308–11667` |
| Coach availability write/read parity | `bridge_server.py` `update_availability` ~`13909+`, `coach_get_my_availability` ~`13927+` |
