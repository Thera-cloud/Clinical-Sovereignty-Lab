# Client Portal — Schedule (book a session with assigned coach)

> Status: `ACTIVE`
> Last full review: `2026-05-05`
> Next review due: `2026-05-12` (weekly cadence)
> Owner: Nathan
> Steve Jobs UX score: `needs work`

**Naming note:** Spec file prefix `16_` is documentation order; `_FOUNDATIONAL_SPEC.md` §3 inventory index for this surface is **row 10** ("Client schedule"). Phase 3 plan: `_PHASE_3_PLAN.md` § B row 16 — unblocked after **Fix F+D+E** (and follow-ups **Fix G'+H**, plus **SCHEDULE-AVAILABILITY-FIX**) landed on `main` 2026-05-05.

---

## 1. Purpose (1 sentence)

Let the signed-in **CLIENT** view their assigned coach's recurring availability on a month calendar, pick a date, see remaining open hourly slots for that day, and book or cancel a single session — all over the shared `_ClientWsHub` channel that was authenticated at lobby login.

---

## 2. UX acceptance criteria (client perspective)

> Grounded in `_FOUNDATIONAL_SPEC.md` §3 row 10, §4.A, §5, §6 (point 5), §7, §10. Reject changes that break any item without updating this spec.

- [ ] First meaningful action ("pick a date → see slots → Book") is reachable without hunting (no coach roster noise) — `_PIPELINE_TEMPLATE.md` §2; entry from settings tile `settings_screen.dart:2960–2970`
- [ ] Loading states resolve or surface a **retry** within 30s for both `client_get_coach_month_overview` and `client_get_coach_availability` — template §2; bridge handlers `bridge_server.py:14092`, `12152`
- [ ] Errors state **what failed** and **what to do next** — e.g. "Session expired. Return to home and reopen Schedule." — `main.dart:10447–10454` (Fix E `d95faf8`)
- [ ] No silent empty states when the server returned an error — `_FOUNDATIONAL_SPEC.md` §7 cites `bridge_server.py:12153–12157`, `12271–12282` debug logs as evidence the bridge logs but the UI must also surface
- [ ] Touch targets ≥ 44pt on **Book**, day cells, and month chevrons — template §2
- [ ] **WebSocket:** Schedule reuses the **already-authenticated** `_ClientWsHub.channel` and does **not** open a second WS or fire a second `login_request` — `main.dart:10419–10427` (hub reuse) and `_FOUNDATIONAL_SPEC.md` §6 point 5
- [ ] **Dual-socket flows:** when entered from **Settings** without a password (Settings has no plaintext password), navigation must **not strand** the user — `settings_screen.dart:2964–2968` + `main.dart:10419–10454` (Fix D `6fbd33e`, Fix F `d0e905f`)
- [ ] **`login_request` defensive guard:** `_connect()` must refuse to send `login_request` with empty username **or** empty password (silent bridge auth fail = `uid=GUEST` on subsequent sends) — `main.dart:10441+` (Fix E `d95faf8`)
- [ ] **Calendar dots match server truth:** green dot iff `recurring_days` from `client_get_coach_month_overview` contains `(d.weekday - 1) % 7` AND date is not in `blocked_dates` AND not in the past — `main.dart:10720–10839` (calendar render); bridge `bridge_server.py:14112–14137`
- [ ] **Today's slots stay visible:** selecting today before the coach's local end-of-day must not return an empty list because the bridge container clock is UTC — `bridge_server.py:12189+` slot loop; SCHEDULE-AVAILABILITY-FIX `d268bc4`
- [ ] **Minute-precise coach hours** are honored: a coach window of `09:30–12:00` yields slots starting at `10:00` (start rounds **up**), and `07:00–21:30` truncates to whole-hour cap (end rounds **down**) — `bridge_server.py:12250+`; `d268bc4`
- [ ] **No-coach-assigned** path: when `assigned_coach_id`/`coach_id` is empty, screen shows an actionable message ("No coach assigned — contact support") instead of an empty calendar with no errors — `main.dart:10418`, `bridge_server.py:12158–12159`
- [ ] **COACH_ONLY tier** clients land here as their primary post-login screen with no Nate chat affordance leaking — `main.dart:6748–6756` (post-Fix F branch); `_PHASE_3_PLAN.md` §C "Coach alternate routing"

---

## 3. UI components

| Component | Location | Purpose | Notes |
|-----------|----------|---------|-------|
| `ClientScheduleScreen` (Stateful) | `main.dart:11084` (build) | Whole schedule surface | Constructed from Lobby (Fix F branch) and from Settings (Fix D handoff) |
| `_ClientWsHub` (static) | `main.dart:10316–10328` | Shared authenticated WS + broadcast tee | Owned-stream pattern after Fix G' (`72af178`); single source of truth for inbound for Lobby, Schedule, NeuralInterfaceV2 (Fix H `718a537`) |
| Month calendar | `main.dart:10720–10839` | Date picker grid; green dot when `_calRecurringDays.contains(_dowMonZero(d))` | `_dowMonZero(d) = (d.weekday - 1) % 7` — Mon=0..Sun=6 |
| `_dowMonZero(DateTime d)` | `main.dart:10661` | Map Dart `weekday` (Mon=1..Sun=7) to bridge `day_of_week` (Mon=0..Sun=6) | Must stay in sync with `bridge_server.py:12164` `_DAY_INT_TO_NAME` |
| Available Time Slots list | `main.dart` (renders `_availableSlots`) | Hourly `Book` rows for selected date | List length must equal `len(available_slots)` returned by bridge |
| `_connect()` | `main.dart:10441+` | Fallback path when hub channel is null | After Fix E `d95faf8`: hard-fails on empty creds rather than sending `login_request` |

---

## 4. Files (canonical references)

### Mobile

- `mobile/lib/main.dart:10316–10328` — `_ClientWsHub` definition (shared authenticated channel + broadcast inbound stream owned-by-hub after Fix G' `72af178`)
- `mobile/lib/main.dart:10350–10363` — schedule state (`_upcomingSessions`, `_availableSlots`, `_coachId`, calendar sets per `_FOUNDATIONAL_SPEC.md` §3 row 10)
- `mobile/lib/main.dart:10419–10436` — `initState` hub reuse path (preferred) vs `_connect()` fallback
- `mobile/lib/main.dart:10441+` — `_connect()` (Fix E `d95faf8`: refuses empty creds)
- `mobile/lib/main.dart:10549` — `_handleMessage` `coach_month_overview` branch → populates `_calRecurringDays`
- `mobile/lib/main.dart:10598` — sends `client_get_upcoming_sessions`
- `mobile/lib/main.dart:10608` — sends `client_get_coach_availability`
- `mobile/lib/main.dart:10619` — sends `client_get_coach_month_overview`
- `mobile/lib/main.dart:10649` — `_requestMonthOverview`
- `mobile/lib/main.dart:10661` — `_dowMonZero` (calendar day-of-week mapping)
- `mobile/lib/main.dart:10720–10839` — calendar grid + dot logic (`_calRecurringDays.contains(_dowMonZero(d)) && !isBlocked && !isPast`)
- `mobile/lib/main.dart:11004` — sends `client_book_session`
- `mobile/lib/main.dart:11015` — sends `client_cancel_session`
- `mobile/lib/main.dart:11084` — `build`
- `mobile/lib/main.dart:6748–6787` — post-login CLIENT branch with `_ClientWsHub.attach` for ALL clients (Fix F `d0e905f`); routes COACH_ONLY / `!can_access_nate` directly to `ClientScheduleScreen`
- `mobile/lib/screens/settings_screen.dart:2960–2970` — Settings → Schedule handoff (no password passed; relies on hub) — Fix D `6fbd33e`

### Bridge (WebSocket)

- `backend/app/websocket/bridge_server.py:12152–12291` — `client_get_coach_availability` handler (`role == "CLIENT"` gate at `12154`; SCHEDULE-AVAILABILITY-FIX block `d268bc4` at `12189+` and `12250+`)
- `backend/app/websocket/bridge_server.py:12164` — `_DAY_INT_TO_NAME` (Mon=0..Sun=6) — must match `_dowMonZero` in Flutter
- `backend/app/websocket/bridge_server.py:12166–12178` — UUID resolve for `coach_availability` query
- `backend/app/websocket/bridge_server.py:12206–12210` — booked-sessions query (uses `coach_id` hardware id — see §7 hazard)
- `backend/app/websocket/bridge_server.py:12330` — `client_book_session` (`role == "CLIENT"` at `12331`)
- `backend/app/websocket/bridge_server.py:13067–13088` — `client_cancel_session` (`role == "CLIENT"` at `13068`; `SESSIONS_FILE` JSON)
- `backend/app/websocket/bridge_server.py:13105–13109` — `client_get_upcoming_sessions` (`role == "CLIENT"` at `13106`; `SESSIONS_FILE` JSON)
- `backend/app/websocket/bridge_server.py:14092–14149` — `client_get_coach_month_overview` (**no `role == "CLIENT"` guard** in handler body — see §12 review item)

### REST (FastAPI)

- Coach metadata for the header card uses **REST** `GET .../api/client/coach-info/$coachId` from settings — `settings_screen.dart:476–481` (`_FOUNDATIONAL_SPEC.md` §4.A note); not `client_get_coach_info`

### Storage

- Tables: `users` (hardware → UUID), `coach_availability` (recurring + specific blocked dates), `coaching_sessions` (booked masking — see hazard), `google_external_busy` (Google Calendar overlay) — `_FOUNDATIONAL_SPEC.md` §5
- File: `SESSIONS_FILE` JSON for client-facing booked/cancelled state (`bridge_server.py:13075–13088`, `13109`, `12383+`) — `_FOUNDATIONAL_SPEC.md` §5
- Migrations: schema-bound to whichever migration created `coach_availability` (TBD exact NNN)

---

## 5. State variables

| Variable | Type | Set at | Clear at | Default |
|----------|------|--------|----------|---------|
| `_socket` | `WebSocketChannel?` | hub reuse `main.dart:10421` OR `_connect()` `main.dart:10441+` | `dispose` (do NOT close hub channel) | `null` |
| `_hubSub` | `StreamSubscription?` | `main.dart:10422` (when hub reused) | `dispose` (cancel) | `null` |
| `_isLoading` | `bool` | before each request | `_handleMessage` reply / `onError` / `onDone` / Fix E error path | `true` |
| `_coachAvailErr` / `_coachAvailDetail` | `String?` | error responses + Fix E empty-creds path | next successful response | `null` |
| `_calRecurringDays` | `Set<int>` (Mon=0..Sun=6) | `coach_month_overview` reply `main.dart:10549` | new month load | `{}` |
| `_calBlockedDates` | `Set<DateTime>` | `coach_month_overview` reply | new month load | `{}` |
| `_availableSlots` | list | `coach_availability` reply | date change / new request | `[]` |
| `_upcomingSessions` | list | `client_get_upcoming_sessions` reply | refresh / cancel | `[]` |
| `_coachId` | `String?` | from `currentUserProfile['assigned_coach_id']` / `coach_id` | session end | `null` |
| `_hasCoach` | `bool` | initState (derived from `_coachId`) | session end | `false` |

**Rule:** every `setState` that sets `_isLoading` MUST clear on **error**, **timeout**, **`onDone`**, **`dispose`**, AND on the Fix E empty-creds bail-out — missing clear = stuck spinner. Hub channel must NOT be closed on `dispose` (other client surfaces use it).

---

## 6. WebSocket messages

| Direction | Type | Flutter `file:line` | Bridge `file:line` | Notes |
|-----------|------|---------------------|---------------------|-------|
| → | `login_request` | `main.dart:10441+` (only on `_connect()` fallback path; **must** have non-empty creds — Fix E) | shared auth pipeline | `expected_role`: `"CLIENT"`. Hub-reuse path skips this entirely. |
| → | `client_get_coach_month_overview` | `main.dart:10619` (via `_requestMonthOverview` `10649`) | `bridge_server.py:14092` | Returns `{recurring_days: int[], blocked_dates: ISO[]}`. **No CLIENT role check** in handler. |
| → | `client_get_coach_availability` | `main.dart:10608` | `bridge_server.py:12152` | Returns `{availability, available_slots, booked_slots, date}`. Slot generation is TZ-aware + minute-precise after `d268bc4`. |
| → | `client_get_upcoming_sessions` | `main.dart:10598` | `bridge_server.py:13105` | Reads `SESSIONS_FILE` JSON. |
| → | `client_book_session` | `main.dart:11004` | `bridge_server.py:12330` | Writes `SESSIONS_FILE`; checks PG `sessions` for limit at `12355–12359`. |
| → | `client_cancel_session` | `main.dart:11015` | `bridge_server.py:13067` | Writes `SESSIONS_FILE`. |
| ← | `coach_month_overview` | `main.dart:10549` | `bridge_server.py:14139–14145` | Populates `_calRecurringDays`, `_calBlockedDates`. |
| ← | `coach_availability` | `_handleMessage` (general) | `bridge_server.py:12272–12279` | Populates `_availableSlots`. |
| ← | `coach_availability_error` | `_handleMessage` | `bridge_server.py:12286–12290` | Sent when `role != CLIENT` (`auth_role_mismatch`). Surface the detail string. |
| ← | `error` | `_handleMessage` | various (e.g. `12159` no coach, `12161` no db_pool, `12283` op failed) | Generic — the spec's UX criterion #3 demands these be turned into actionable text. |

**Critical pairings**

- Every optimistic UI set MUST have timeout OR matching server ack handler (template §6).
- `client_*` handlers assume `current_profile["role"] == "CLIENT"` — verified for **5 of 6** (book, cancel, upcoming, availability, info). **`client_get_coach_month_overview` is NOT gated** — see §12.
- Hub reuse means `coach_*` responses arrive on the broadcast inbound stream — never assume the handler runs on a private socket. Multiple subscribers (Lobby, Schedule, NeuralInterfaceV2) may see the same frame; dedupe by `request_id` if added later.

---

## 7. Database tables touched

- **Read:** `users` (hardware → UUID resolve), `coach_availability` (recurring slots + `specific_date IS NULL` filter, blocked dates), `coaching_sessions` (booked masking for selected date), `google_external_busy` (calendar overlay).
- **Read/Write JSON file:** `SESSIONS_FILE` for upcoming/book/cancel.
- **Read PG:** `sessions` for booking limit check.

**Cross-feature hazards**

- `coach_availability.coach_id` is queried by **UUID** (`_coach_uuid`) — `bridge_server.py:12173–12178`, `14114`.
- `coaching_sessions.coach_id` is queried by **hardware id string** (`coach_id` variable) — `bridge_server.py:12206–12210`. `_FOUNDATIONAL_SPEC.md` §5 documents the asymmetry — verify `coaching_sessions.coach_id` actual column type before relying on the booked-mask result. If it is UUID in PG, the mask returns 0 rows (false negative — over-shows free slots).
- `google_external_busy.user_id` is the coach **username** (resolved from registry) — `bridge_server.py:12233–12237` — registry lookup must succeed or external busy windows are silently skipped.

---

## 8. Edge cases

- **Offline / flaky network:** distinguish from server errors; hub reuse path means a network blip on the shared socket affects chat and schedule simultaneously — see learned-integration #13 (no auto-redirect loops on dashboard pages).
- **Auth lost mid-session:** `onDone` on hub channel — Schedule should surface "Session expired" rather than reconnect silently (Fix E pattern at `main.dart:10447–10454`).
- **No coach assigned:** `assigned_coach_id` empty → bridge sends `error: "No coach assigned"` (`12159`); UI must show actionable text and a way to contact support, not blank calendar.
- **COACH_ONLY tier:** post-Fix F, hub is attached for ALL clients before COACH_ONLY routing — schedule is the primary screen — `main.dart:6748–6756`.
- **Settings entry without password:** Fix D handoff (`6fbd33e`) passes only the username; Fix E backstop refuses to send `login_request` with empty password if hub is somehow null — `main.dart:10441+`.
- **Today's window after EDT evening:** before `d268bc4`, naive `datetime.now()` (UTC inside Docker) made today's local hours appear "in the past" → 0 slots returned. Post-fix uses `datetime.now(_tz)` in coach TZ.
- **Minute-precise availability:** `09:30–12:00` (start has `:30`) → `start_h` rounds UP to `10` → 2 slots; `07:00–21:30` (end has `:30`) → `end_h` rounds DOWN to `21` → 14 slots. Pre-fix, both bugs silently misrepresented coach availability.
- **Specific-date block:** `coach_availability.is_blocked = true` for a date → `client_get_coach_availability` returns `day_slots = []` (`bridge_server.py:12205`) AND `coach_month_overview.blocked_dates` includes the ISO date → calendar renders red dot (legend at `main.dart` calendar block).
- **Booked masking timezone:** `coaching_sessions.scheduled_at` is timestamptz; `slot_start` is now TZ-aware after `d268bc4` so the `slot_start < be and slot_end > bs` overlap check no longer raises `TypeError` from naive vs aware mixing.
- **`client_get_coach_month_overview` un-gated:** any authenticated bridge socket can request another coach's recurring days/blocked dates — privacy review item (§12).

---

## 9. Anti-patterns from git history (reject without investigation)

≥3 commits, mix of foundational §9 list and tonight's client-schedule work. Reject any change that contradicts a lesson here without first updating this spec.

| Commit | Lesson for client schedule |
|--------|----------------------------|
| `38158cc` | Shared authenticated app WS + schedule availability error handling — do not regress hub attach or error surfacing |
| `2145c9d` | Attach post-login WS to `_ClientWsHub` — schedule must reuse it; do not open a parallel socket |
| `8c2a768` / `c43b9a3` | Diagnostic logging on `client_get_coach_availability` silent drop — never swallow WS errors without UI affordance + logs |
| `ea68dd3` | Tighten `client_get_upcoming_sessions` filter (duplicate AI rows) — schedule UI must not show ghost sessions |
| `d7ec21a` | Bridge WS control-flow bugs (UnboundLocalError / datetime shadowing) — fragile `elif` chains break schedule paths first because they are deepest in the dispatch |
| `d0e905f` (Fix F) | `_ClientWsHub.attach` MUST run for **all** CLIENT post-login paths, not only inside the `COACH_ONLY` branch — keeping it inside leaves Schedule (and other hub consumers) without an authenticated channel |
| `6fbd33e` (Fix D) | Navigating to `ClientScheduleScreen` from Settings MUST NOT pass a password (it isn't stored); rely on the hub-shared channel — passing an empty password caused `uid=GUEST` silent auth failure |
| `d95faf8` (Fix E) | `_connect()` MUST refuse to send `login_request` with empty username or password — silent server-side fail produced GUEST sockets that then served zero data |
| `72af178` (Fix G') | The hub owns the **raw** WS stream; Lobby / Neural / Schedule consume via the broadcast `inbound`/`errors`/`done` — never re-listen on the raw socket from a consumer (causes the "single-listener" StreamController exception) |
| `718a537` (Fix H) | `NeuralInterfaceV2` reuses `ClientWsHub` instead of opening its own socket — eliminates double-`login_request` eviction (the second login bumped the first off the bridge, breaking schedule mid-session) |
| `d268bc4` (SCHEDULE-AVAILABILITY-FIX) | Slot generation MUST parse `start_time`/`end_time` with minute precision (round start up, end down) and MUST compare `slot_start` against `datetime.now(_tz)` in coach timezone — naive UTC `now()` silently empties "today" after EDT evening |

**Reject proposals that:**

- ❌ Open a second WebSocket from `ClientScheduleScreen` instead of reusing `_ClientWsHub.channel` (cf. distress beacon — `_FOUNDATIONAL_SPEC.md` §3 row 16 — separate WS is documented per-feature; Schedule is **not** in that category).
- ❌ Navigate to `ClientScheduleScreen` from any caller without proving either (a) `_ClientWsHub.channel != null` OR (b) non-empty `username` + `password` constructor args.
- ❌ Add a new `client_*` bridge branch for schedule without a `current_profile.get("role") == "CLIENT"` guard (existing `client_get_coach_month_overview` gap is a known review item — do not propagate it).
- ❌ Drop minute precision on `start_time`/`end_time` parsing (revert `d268bc4`'s `datetime.time.fromisoformat` block to a bare `int(split(":")[0])`).
- ❌ Compare `slot_start` against bare `datetime.datetime.now()` (no `_tz` argument) — re-introduces the "today vanishes after 8pm EDT" bug.
- ❌ Listen directly on `_ClientWsHub.channel.stream` from a consumer — Fix G' enforces broadcast-only consumption.

---

## 10. Known bugs

### Open

| ID | Symptom | Evidence | Owner |
|----|---------|----------|-------|
| OB-SCHED-01 | `client_get_coach_month_overview` is callable without `role == "CLIENT"` check; an authenticated CLIENT can probe another coach's recurring days by passing a different `coach_id` | `bridge_server.py:14092–14100` (handler body), `_FOUNDATIONAL_SPEC.md` §4.A row 3 | TBD |
| OB-SCHED-02 | Booked-session masking may return 0 rows if `coaching_sessions.coach_id` is UUID in PG (query passes hardware id string) — over-shows free slots when there are real bookings | `bridge_server.py:12206–12210` vs `12173–12178`; `_FOUNDATIONAL_SPEC.md` §5 mismatch note | TBD |
| OB-SCHED-03 | Hourly-only slot UI: a coach window of `9:00–12:30` silently truncates the trailing `:30` (end rounds down). Coach declared 3.5h but client sees 3h. Acceptable today; revisit when 30-min slots are needed. | `bridge_server.py:12250+` post-`d268bc4`; design constraint | TBD |
| OB-SCHED-04 | If the coach registry lookup fails, Google external busy windows are silently skipped (no UI signal) — coach may appear free during a real Google calendar conflict | `bridge_server.py:12222–12249` | TBD |

### Resolved

| Date | Commit | Bug | Fix |
|------|--------|-----|-----|
| 2026-05-05 | `d0e905f` | `_ClientWsHub` only attached inside `COACH_ONLY` branch — full-Nate clients had no hub channel for Schedule | Move `attach()` above the branch so all CLIENT post-login paths populate the hub |
| 2026-05-05 | `6fbd33e` | Settings → Schedule passed empty `password` (Settings has no plaintext) → bridge silent auth fail → `uid=GUEST` | Drop password arg; rely on hub-shared channel (Option D1) |
| 2026-05-05 | `d95faf8` | `_connect()` sent `login_request` regardless of credential validity → silent server-side fail → stuck loading | Validate non-empty `username` + `password` before send; surface "Session expired" on failure |
| 2026-05-05 | `72af178` | Multiple consumers tried to listen on the same `WebSocketChannel.stream` → "Stream has already been listened to" exception | Hub owns raw stream; consumers subscribe to broadcast `inbound`/`errors`/`done` |
| 2026-05-05 | `718a537` | `NeuralInterfaceV2` opened its own socket and sent a second `login_request`, evicting the lobby/Schedule session on the bridge | Reuse `_ClientWsHub` channel; skip the second login |
| 2026-05-05 | `d268bc4` | `client_get_coach_availability` returned 0 slots for "today" after ~8pm EDT (naive `datetime.now()` is UTC inside Docker) AND silently dropped minute-precise endpoints (`21:30` → `21`) | Parse `target_date` in coach TZ; compare `slot_start` against `datetime.now(_tz)`; round start UP / end DOWN with `datetime.time.fromisoformat` |

---

## 11. Steve Jobs UX debt (dated)

Pull from `_FOUNDATIONAL_SPEC.md` §10 (rows applicable to Schedule) plus Schedule-specific items surfaced tonight.

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-05 | High | **Schedule from Settings** depends on invisible `_ClientWsHub` state — if the hub is somehow null (e.g. user deep-linked into Settings without going through Lobby), the user sees "Session expired" and must go back to Home. The first-class fix is a passwordless re-auth handoff, not a friendly error string — `settings_screen.dart:2964–2968`, `main.dart:10447–10454` (`_FOUNDATIONAL_SPEC.md` §10 row 2) | Q3 |
| 2026-05-05 | High | **Hourly slots only.** Coach can declare `7:00–21:30`, but client UI offers 14 hourly blocks ending `20:00–21:00`. The 30-minute slot type doesn't exist; the calendar implies precision the system doesn't deliver — `bridge_server.py:12250+`, OB-SCHED-03 | Q3 |
| 2026-05-05 | Medium | **No "next available" CTA.** A client with no upcoming session lands on today's date even when today has zero available slots; they must hunt across the calendar to find the first day with a green dot — `main.dart:10720–10839` | Q4 |
| 2026-05-05 | Medium | **Booking confirmation is implicit.** No modal review step before `client_book_session` fires — a misclick on Book commits the slot. Cancel is one tap from Upcoming, but the asymmetry favors fat-finger errors — `main.dart:11004` | Q3 |
| 2026-05-05 | Low | **Calendar legend is below the fold** on small screens; "Available / Booked / Pending / Blocked" colors aren't explained until the user scrolls past the grid — `main.dart:10720–10839` | Q4 |
| 2026-05-05 | Low | **Coach timezone is invisible to the client.** Slots render in the client's device locale assuming the bridge already converted; if the client and coach are in different zones, the displayed times look right but the relationship to the coach's "9 AM" is opaque — `bridge_server.py:12185` (`avail_data["timezone"]`) is sent but the client doesn't display it | Q4 |

Minimum 3 rows met (6 listed).

---

## 12. Security boundaries

- **Client may see:** their **assigned** coach's recurring availability, blocked dates, hourly open slots for a chosen date, and their own upcoming/booked sessions (`SESSIONS_FILE`).
- **Must stay server-side:** other clients' bookings (the booked-mask query returns only `start`/`end` ranges, not client identifiers — verify any new field added to `booked_slots` does not leak names/IDs — `bridge_server.py:12212–12219`).
- **Must stay coach-side:** coach roster, internal session notes, financials — these live in coach dashboard codepaths (`updated_screens.dart:4566+` per `_FOUNDATIONAL_SPEC.md` §8) and are not reachable from `ClientScheduleScreen`.
- **REST vs WS:** Schedule is WS-only on the hub. Coach metadata for the header card uses REST `GET /api/client/coach-info/$coachId` — `settings_screen.dart:476–481`. Never log Bearer tokens.
- **Bridge review item:** `client_get_coach_month_overview` lacks an explicit `role == "CLIENT"` gate — `bridge_server.py:14092–14100`. File a security review to add the same check used by sibling handlers, then update §6 critical pairings.
- **Hub reuse implication:** because Lobby, Schedule, and `NeuralInterfaceV2` share the same authenticated channel after Fix F+G'+H, any handler that responds with a fan-out frame (e.g. global broadcasts) is visible to all currently-mounted screens. New broadcast types must be evaluated for cross-screen interaction (e.g. a chat-only payload arriving in Schedule's `_handleMessage`).

---

## 13. Manual test scenarios

1. **Lobby → full-Nate client → Schedule via Neural drawer / Settings**: hub is attached at `main.dart:6751–6752` (Fix F path); Schedule reuses hub at `main.dart:10419–10422`; no second `login_request` appears in `nate_bridge` logs.
2. **Lobby → COACH_ONLY client**: post-login routes directly to `ClientScheduleScreen` (`main.dart:6748–6756`); calendar loads with month overview; selecting today shows non-zero slots if before coach end-of-day.
3. **Settings → "View Availability & Book Session" (Fix D path)**: navigation passes only `username`; Schedule reuses hub; no "Session expired" error appears.
4. **"Today" boundary regression (`d268bc4`)**: select today's date after 9pm local EDT; expected slot count > 0 if coach's local end-of-day is later; bridge log shows `returning N open slots` where N matches remaining whole hours.
5. **Minute-precise window (`d268bc4`)**: with a coach configured `09:30–12:00`, expected 2 slots starting `10:00`; with `07:00–21:30`, expected 14 slots ending `20:00–21:00`. Verify `bridge_server.py:12250+` `start_h`/`end_h` calculation matches.
6. **No coach assigned**: temporarily clear `assigned_coach_id` for a test client → bridge replies `error: "No coach assigned"` → UI shows actionable text (criterion #11).
7. **Specific-date block**: coach blocks a date → that date renders red on calendar AND `available_slots` is empty for it.
8. **Booking + cancel**: book a slot → it disappears from `available_slots` for that date and appears in Upcoming; cancel from Upcoming → slot returns to availability after refresh.
9. **Hub stress (Fix G' + H)**: open Lobby → Schedule → switch to Chat → back to Schedule; verify no "Stream has already been listened to" exception and no duplicate inbound deliveries.
10. **Empty creds (Fix E)**: synthetically launch `ClientScheduleScreen` with empty `password` and no hub channel (debug-only); verify `_connect()` does NOT send `login_request` and surfaces the Fix E error.

---

## 14. Foundational spec cross-reference

- **Inventory row:** `_FOUNDATIONAL_SPEC.md` §3 table **row 10** (Client schedule); doc filename `16_client_schedule.md` maps here.
- **Entry / routing:** §2 table "Schedule"; §6 auth lifecycle points 1, 3, 5 (and the post-Fix-F generalization of point 2).
- **WS inventory:** §4.A all 6 `client_*` rows; §4.C allowlist.
- **DB / schema:** §5 (Schedule is the most-cited path) and the **mismatch note** about UUID vs hardware id on `coaching_sessions.coach_id`.
- **Privacy / coach vs client:** §8 `assigned_coach_id` paragraph.
- **Known debt:** §7 (in-flight schedule logging, month-overview auth gap, UUID mismatch); §10 Steve Jobs register rows 1 and 2 (Family Sanctuary close-and-reconnect is adjacent; row 2 is the schedule-from-settings password-omit item).
- **Phase 3 unblock:** `_PHASE_3_PLAN.md` § B row 16 — gating commits **Fix F `d0e905f`**, **Fix D `6fbd33e`**, **Fix E `d95faf8`** all landed 2026-05-05; this spec is now ACTIVE.

---

## 15. Daily health checks

`client_portal_daily_check.sh` — **TBD.** Manual:

- `git log -1 --format='%H %s' -- backend/app/websocket/bridge_server.py` should show `d268bc4` or later for the SCHEDULE-AVAILABILITY-FIX block (regression check after rebases).
- `grep -nE "datetime.datetime.now\(\)" backend/app/websocket/bridge_server.py | grep -A1 -B1 "client_get_coach_availability"` should return 0 hits within the slot loop (must be `datetime.now(_tz)`).
- `grep -nE "int\(_st_str.split\(\":\"\)\[0\]\)" backend/app/websocket/bridge_server.py` should be inside the `except Exception:` fallback only, never the primary parse path.
- Bridge log spot check: `docker logs nate_bridge --since 5m 2>&1 | grep AVAILABILITY-DEBUG | tail` — `returning N open slots` where N matches expected for a current Tue/Wed before 9pm EDT.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05` (template + foundational + tonight's commits `d0e905f`, `6fbd33e`, `d95faf8`, `72af178`, `718a537`, `d268bc4`).
**Tokens saved (estimate):** `TBD`

---

## 17. Cursor prefix

```
Read docs/client_portal/features/16_client_schedule.md + docs/client_portal/_FOUNDATIONAL_SPEC.md §3 row 10 + §4.A + §5 mismatch note + §6 point 5 before editing ClientScheduleScreen, _ClientWsHub, or any client_get_coach_* / client_book_session / client_cancel_session bridge handler. §4 = line truth; §9 = reject list (includes Fix F/D/E/G'/H + SCHEDULE-AVAILABILITY-FIX).
```

---

*Spec derived from `docs/client_portal/_FOUNDATIONAL_SPEC.md` + `docs/client_portal/_PIPELINE_TEMPLATE.md` + `_PHASE_3_PLAN.md` § B row 16 + git log of 2026-05-05 schedule fixes — 2026-05-05.*

---

## 18. Chat-scheduling path (main chat — `NeuralInterfaceV2`)

> Status: `ADDED 2026-06-01`. Feature-flagged via `ENABLE_CHAT_SCHEDULING`. Booking reuses the **same** `client_book_session` writer as the Schedule screen — there is no second booking implementation.

### Components

| Layer | File | Role |
|---|---|---|
| Shared slot engine | `backend/app/services/coach_slot_engine.py` | `compute_available_slots(db_pool, coach_hw_id, date)` — single source of truth for open hourly slots. Also used by the REST endpoint and (logically) the availability handler. Fixes the `coaching_sessions.coach_id` UUID-vs-hardware-id mask by casting both sides to text (`coach_id::text IN ($1,$2)`). |
| Scheduling brain | `backend/app/services/client_scheduling_assistant.py` | `detect_intent`, `resolve_coach` (`coach_id` then `assigned_coach_id`), `parse_target_date`, `handle_turn(profile,text,db_pool) -> {handled,response,payload}`. Never invents times — slots come only from the engine. Import-safe; degrades to `handled=False` on any error. |
| Bridge hook | `backend/app/websocket/bridge_server.py` (`nate_query`) | Thin `ENABLE_CHAT_SCHEDULING`-gated block: on handled scheduling intent emits `nate_response` + a `scheduling_slots` frame and `continue`s; otherwise falls through to `process_interaction` unchanged. |
| Booking gate | `bridge_server.py` (`client_book_session`) | Sovereign Covenant consent check (`COVENANT_REQUIRED` if `consent_version != REQUIRED_CONSENT_VERSION`) + explicit coach resolution (payload `coach_id` → profile `coach_id` → `assigned_coach_id`). Shared by chat and Schedule screen. |
| Prompt rule | `bridge_server.py` (~9145 client system prompt) | Additive "SCHEDULING (system-assisted, accuracy rule)" block: times are system-provided only; say "requested" until confirmed. |
| Flutter UI | `mobile/lib/updated_screens.dart` (`NeuralInterfaceV2`) | `_handleSocketMessage` branches for `scheduling_slots` (slot-chip bottom sheet, `surface == "chat"` filter), `session_booked` (system line + SnackBar), and `error` codes `COVENANT_REQUIRED` / `SESSION_LIMIT_REACHED` / `Time slot conflict`. Book-on-tap sends `client_book_session` with ISO `scheduled_start`/`scheduled_end` from the payload + explicit `coach_id`. |

### UX flow tree

```
client types in main chat
└─ "book my coach" / "what times are open"
   └─ nate_query → bridge hook (ENABLE_CHAT_SCHEDULING)
      └─ client_scheduling_assistant.handle_turn
         ├─ no scheduling intent ─────────────→ fall through to process_interaction (normal chat)
         ├─ no coach assigned ───────────────→ nate_response: "no coach assigned, contact support" (no payload)
         ├─ intent but no date ──────────────→ nate_response: "which day — today, tomorrow, a weekday?"
         ├─ date, no open slots ─────────────→ nate_response: "none open on <date>, try another day?" + scheduling_slots(slots=[])
         └─ date with slots ─────────────────→ nate_response: lists times + scheduling_slots(slots=[…], surface=chat)
            └─ Flutter shows slot-chip bottom sheet (surface==chat only)
               └─ tap slot → client_book_session(coach_id, scheduled_start, scheduled_end)
                  ├─ COVENANT_REQUIRED ──────→ error → red SnackBar + system line
                  ├─ SESSION_LIMIT_REACHED ──→ error → red SnackBar + system line
                  ├─ Time slot conflict ─────→ error → red SnackBar + system line
                  └─ ok → session_booked
                     ├─ status pending_approval → "Session requested … pending your coach's approval."
                     └─ status scheduled ──────→ "Session booked for <when>."
```

### Tests

`backend/tests/test_chat_scheduling_assistant.py` — 22 cases: intent positive/negative, coach resolution precedence, date parsing (ISO/today/tomorrow/absent), `handle_turn` (fall-through, needs-date, no-coach, slots-present, no-slots), and booking error-code contract (`COVENANT_REQUIRED`, `SESSION_LIMIT_REACHED`, `Time slot conflict`).
