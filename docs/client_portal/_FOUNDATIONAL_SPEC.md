# Client Portal Foundational Spec

> **Generated:** 2026-05-05 — read-only investigation of shipped Flutter + bridge code.  
> **Source of truth for:** per-feature pipeline specs (Phase 3).  
> Every claim cites `file:line`. **TBD** = not verified in this pass.

---

## § 1 — Purpose and scope

**What:** The **client portal** is the end-user experience for accounts with `role == 'CLIENT'` after lobby authentication: onboarding gates, primary chat (`NeuralInterfaceV2`), scheduling, settings/tools, family sanctuary, and satellite screens reached from settings or post-login routing.

**Who:** Clients (and mixed flows where the same person uses coach/admin elsewhere — those portals are **out of scope** here except where shared widgets appear).

**Code anchor — post-login CLIENT branch:** `main.dart:6748–6787` (`_ClientWsHub.attach`, `COACH_ONLY` / `can_access_nate`, `AiConsentScreen` vs `NeuralInterfaceV2`).

---

## § 2 — Entry points (how clients reach the app)

| Surface | Widget / class | `build` (or primary UI) | WebSocket created | Notes |
|--------|----------------|---------------------------|---------------------|-------|
| App bootstrap | `_InitialRouteWidget` | `main.dart:215` (MaterialApp child) | — | Resolves to `LobbyScreen` — `main.dart:247–318` |
| Lobby (role chooser + login) | `LobbyScreen` / `_LobbyScreenState` | `main.dart:7405` | `WebSocketChannel.connect` — `main.dart:6315` | `initState` → `_connectToBridge()` — `main.dart:6257–6259` |
| Re-consent gate | `ReConsentScreen` | `main.dart:9897` | **TBD** (screen opens before full client nav; WS in `_send` not enumerated here) | Routed when `consent_update_needed` — `main.dart:6660–6681` |
| Trial onboarding | `OnboardingThresholdScreen` | `onboarding_threshold_screen.dart:196` | **TBD** per-slide inner builders (`554+`) | Class — `onboarding_threshold_screen.dart:15–31` |
| Paid onboarding | `OnboardingPaidScreen` | `onboarding_paid_screen.dart:149` | **TBD** inner builders | Class — `onboarding_paid_screen.dart:14–34` |
| Mandatory tutorial | `OnboardingTutorialScreen` | `updated_screens.dart:425` | `_socket` in same state class — `updated_screens.dart:84–85` | Completes with `mark_onboarding_complete` — `updated_screens.dart:353–356` |
| AI consent (pre-chat) | `AiConsentScreen` | `ai_consent_screen.dart:96` | — | REST `POST /api/client/ai-consent` — `ai_consent_screen.dart:55–65` |
| Primary chat | `NeuralInterfaceV2` | `updated_screens.dart:3663` | `WebSocketChannel.connect` — `updated_screens.dart:1472`; `login_request` — `updated_screens.dart:1488–1493` | Class — `updated_screens.dart:1183–1192` |
| Legacy chat (still in tree) | `NeuralInterface` | `main.dart:1931` | `_socket` — `main.dart:1354`; connect path **TBD** for all branches | Class — `main.dart:1339–1348` |
| Settings (client) | `ClientSettingsScreen` | `settings_screen.dart:2236` | Optional `widget.socket` — `settings_screen.dart:204–214` | State + fields — `settings_screen.dart:220–269` |
| Schedule | `ClientScheduleScreen` | `main.dart:11084` | Hub reuse `_ClientWsHub.channel` — `main.dart:10419–10422` OR `_connect()` — `main.dart:10442–10468` | Hub definition — `main.dart:10316–10328` |

---

## § 3 — Tab / feature inventory (from code, not assumptions)

Each row: **feature**, **primary `build`**, **transport**, **key outbound messages / calls**, **representative state**.

| # | Feature | `build` / entry | Transport | Sends / calls | Owned state (representative) |
|---|--------|-----------------|-----------|----------------|------------------------------|
| 1 | Lobby & login | `main.dart:7405` | WS `main.dart:6315` | `login_request` (e.g. biometric `main.dart:6407–6412`; registration follow-up `main.dart:8173–8178`) | `_channel`, `_isConnected`, `_tempUser`/`_tempPass` — `main.dart:6216–6227` |
| 2 | Re-consent | `main.dart:9897` | **TBD** | **TBD** | **TBD** |
| 3 | Onboarding trial | `onboarding_threshold_screen.dart:196` | HTTP + optional `existingSocket` ctor — `onboarding_threshold_screen.dart:19–26` | **TBD** slide-level | Design tokens + animation state — `onboarding_threshold_screen.dart:35–46` |
| 4 | Onboarding paid | `onboarding_paid_screen.dart:149` | HTTP + optional socket — `onboarding_paid_screen.dart:20–29` | **TBD** | Tokens — `onboarding_paid_screen.dart:38–46` |
| 5 | Onboarding tutorial | `updated_screens.dart:425` | WS `_socket` — `updated_screens.dart:84–85` | `mark_onboarding_complete` — `updated_screens.dart:356` | `_pageController`, `_socketReady` — `updated_screens.dart:75–79` |
| 6 | AI consent gate | `ai_consent_screen.dart:96` | REST | `POST .../api/client/ai-consent` — `ai_consent_screen.dart:58–65` | `_agreed`, `_submitting` — `ai_consent_screen.dart:42–43` |
| 7 | Neural chat (v2) | `updated_screens.dart:3663` | WS | `login_request` `1488–1493`; `nate_query` `3205–3209`; `get_profile` `1426`; `get_pending_nudges` `1540`; `get_metrics` `2145`; `search_consent_approved` `1615–1618`; `ai_mode_activate` / `deactivate` `1877–1889`; `export_completed` `3289–3294`; `nudge_mark_opened` / `nudge_dismiss` `1775–1782` | `_socket`, `_chatHistory`, `_connectionStatus`, `_pendingNudges`, `_metrics` — `updated_screens.dart:1222–1271` (subset) |
| 8 | Nevedal biometrics | (service, no `build`) | WS via chat socket | `biometric_update` every 2s — `nevedal_flutter.dart:471–516` | `_updateTimer`, `_sessionId` — `nevedal_flutter.dart:444–448` |
| 9 | Family Sanctuary | `main.dart:5684` | WS `_channel` — `main.dart:2667–2668` | `sanctuary_*` types — e.g. `main.dart:3604`, `main.dart:3882+` (handler switch) | `_sanctuaryId`, `_members`, `_messages` — `main.dart:2671–2678` |
| 10 | Client schedule | `main.dart:11084` | WS hub or dedicated | `client_get_upcoming_sessions` `10598`; `client_get_coach_availability` `10608`; `client_get_coach_month_overview` `10619`; `client_book_session` `11004`; `client_cancel_session` `11015` | `_upcomingSessions`, `_availableSlots`, `_coachId`, calendar sets — `main.dart:10350–10363` |
| 11 | Client settings hub | `settings_screen.dart:2236` | REST + optional WS (`widget.socket`) | `_refreshProfileFromServer` ephemeral WS `auth` — `settings_screen.dart:327–331`; coach REST `settings_screen.dart:476–481`; `_sendWs` → `update_profile` / prefs — `settings_screen.dart:2846–2849`, `1337+` | `_profile`, notification toggles, `_familyMembers` — `settings_screen.dart:221–249` |
| 12 | Your tools (client) | (section inside `build`) `settings_screen.dart:2872–2899` | REST | Nav to `QuizScreen`, `NevedalReportsScreen`, `SecureSearchScreen`, `DistressBeaconScreen` — `settings_screen.dart:2876–2897` | Gated by `!_isCoachOnly` — `settings_screen.dart:2872` |
| 13 | Weekly brief | `settings_screen.dart:6345` | REST | `GET .../api/research/nevedal/reports/brief` + `X-User-Id` — `settings_screen.dart:6321–6323` | `_loading`, `_briefText`, `_moodSummary` — `settings_screen.dart:6305–6309` |
| 14 | Coherence reports | `nevedal_reports_screen.dart:130` | REST | `GET .../api/coherence/report/$hwId` — `nevedal_reports_screen.dart:69–79` | `_report`, `_selectedRange` — `nevedal_reports_screen.dart:37–43` |
| 15 | Memory search | `secure_search_screen.dart:249` | REST | `GET .../api/client/memory/search/$hwId` — `secure_search_screen.dart:120–123` | `_results`, `_tabController` — `secure_search_screen.dart:52–71` |
| 16 | Distress beacon | `distress_beacon_screen.dart:212` | WS **separate** connection | New socket `distress_beacon_screen.dart:77–78`; payload `distress_beacon_screen.dart:173–178` | `_ownSocket`, `_beaconActivated` — `distress_beacon_screen.dart:49–52` |
| 17 | Assessments | `quiz_screen.dart:234` | **TBD** (not traced) | **TBD** | **TBD** |
| 18 | Coaching mesh | `coaching_mesh_screen.dart:669` | **TBD** | **TBD** | **TBD** |
| 19 | Community mesh | `community_mesh_screen.dart:570` | **TBD** | **TBD** | **TBD** |
| 20 | Subscription & billing | (inside client settings `build`) `settings_screen.dart:2520–2605` | REST / Stripe | `PaymentMethodsScreen` — `settings_screen.dart:2580–2582`; portal / plan UI `_showChangePlanSheet`, `_openBillingPortal` — **TBD** line | Token/plan display — `settings_screen.dart:2237–2241` |
| 21 | Family management | `billing_screens.dart:1149` | REST + WS | `sanctuary_get_members` — `billing_screens.dart:900` | `_members`, `_loading` — `billing_screens.dart:857–859` |
| 22 | Coaching packs | `billing_screens.dart:1635` | REST | `GET .../coaching/packs`, `.../sessions` — `billing_screens.dart:1430–1447` | `_packs`, `_sessions` — `billing_screens.dart:1406–1409` |
| 23 | Voice therapy prefs | `settings_screen.dart:2608+` | REST | Balance fetch **TBD** exact line in same file | `_voiceBalanceMinutes` — `settings_screen.dart:242–244` |
| 24 | Check-in widget | `checkin_screen.dart:48` | REST | `POST .../api/sse-client/checkin` — `checkin_screen.dart:25–31` | `_submitted`, `_responseMsg` — `checkin_screen.dart:16–17` |

**Explicit non-findings (requested “common” items):**

- **Wisdom / discipline tracker (WS `get_user_discipline`)**: bridge allowlists `get_user_discipline` — `bridge_server.py:10923`; **no** `get_user_discipline` string in `mobile/lib/**/*.dart` (repo search). Treat as **server/bridge capability without a dedicated client Flutter surface** unless added later.
- **Night School UI**: `NightSchoolScreen` appears under **coach** settings (`CoachSettingsScreen`) — `settings_screen.dart:5247–5250`, **not** under `ClientSettingsScreen` sections read (`2872–3021`).
- **Coach-only “AI Modes”** (`AIModesSelectorScreen`): coach tools — `settings_screen.dart:5252–5255`.

**Phase 3 per-feature files:** map §3 table rows **1–24** to `01_*.md` … `24_*.md` (stub or defer rows marked **TBD**).

---

## § 4 — WebSocket message inventory (client-relevant)

### 4.A Explicit `client_*` types (Flutter → bridge)

| Message | Flutter `file:line` | Bridge handler `file:line` | Auth / role |
|---------|---------------------|------------------------------|-------------|
| `client_get_upcoming_sessions` | `main.dart:10598` | `bridge_server.py:13105` | `current_profile.get("role") == "CLIENT"` — `13106` |
| `client_get_coach_availability` | `main.dart:10608` | `bridge_server.py:12152` | `role == "CLIENT"` — `12154`; else error — `12284–12290` |
| `client_get_coach_month_overview` | `main.dart:10619` | `bridge_server.py:14092` | **No `role == "CLIENT"` guard** in handler body — `14092–14100` (only param + `db_pool` checks) |
| `client_book_session` | `main.dart:11004` | `bridge_server.py:12330` | `role == "CLIENT"` — `12331` |
| `client_cancel_session` | `main.dart:11015` | `bridge_server.py:13067` | `role == "CLIENT"` — `13068` |
| `client_get_coach_info` | **Not sent from schedule/settings in traced paths** | `bridge_server.py:12293` | `role == "CLIENT"` — `12294` |

Coach info from **client** settings uses **REST** `GET .../api/client/coach-info/$coachId` — `settings_screen.dart:476–481`, not `client_get_coach_info`.

### 4.B Other WS types used on authenticated client chat socket (`NeuralInterfaceV2`)

| Message | Flutter `file:line` | Bridge handler `file:line` | Notes |
|---------|---------------------|------------------------------|-------|
| `login_request` | `updated_screens.dart:1488–1493` | (shared auth pipeline — **TBD** single `elif` line) | `expected_role`: `"CLIENT"` |
| `nate_query` | `updated_screens.dart:3205–3209` | `bridge_server.py:12052` | Inside authenticated branch — `12052+` |
| `get_profile` | `updated_screens.dart:1426`, `1764` | **TBD** handler line | |
| `get_metrics` | `updated_screens.dart:2145` | `bridge_server.py:14734` | |
| `get_pending_nudges` | `updated_screens.dart:1540` | `bridge_server.py:28200` | |
| `search_consent_approved` | `updated_screens.dart:1615–1618` | **TBD** | |
| `ai_mode_activate` / `ai_mode_deactivate` | `updated_screens.dart:1877–1889` | **TBD** | |
| `export_completed` | `updated_screens.dart:3289–3294` | **TBD** | |
| `nudge_mark_opened` / `nudge_dismiss` | `updated_screens.dart:1775–1782` | **TBD** | |
| `mark_onboarding_complete` | `updated_screens.dart:356` | `bridge_server.py:25481` | |
| `biometric_update` | `nevedal_flutter.dart:508–516` | `bridge_server.py:19922–19924` | Delegates to `nevedal_handler.handle_biometric_update` |
| `distress_beacon` | `distress_beacon_screen.dart:173–178` | `bridge_server.py:28663` | **No explicit `role == "CLIENT"`** in shown handler body |

### 4.C Allowlisted client-adjacent types (bridge pre-dispatch)

Non-exhaustive slice of shared allowlist including client flows — `bridge_server.py:10914–10930` (`get_metrics`, `get_history`, `get_profile`, `client_get_*`, etc.).

### 4.D `get_history` (memory) handler detail

`get_history` requires truthy `current_profile` only — `bridge_server.py:14765–14768` (no explicit `CLIENT` string check in this block).

---

## § 5 — Database tables touched (per feature, high level)

| Feature / path | Tables / files (verified in bridge or REST path) |
|----------------|---------------------------------------------------|
| `client_get_coach_availability` | `users` (hardware → UUID), `coach_availability`, `coaching_sessions` (booked query), `google_external_busy` — `bridge_server.py:12166–12237` |
| `client_get_coach_month_overview` | `users`, `coach_availability` — `bridge_server.py:14112–14137` |
| `client_book_session` | Session limit: `sessions` PG — `bridge_server.py:12355–12359`; writes **`SESSIONS_FILE` JSON** — `bridge_server.py:12383+` |
| `client_get_upcoming_sessions` / `client_cancel_session` | **`SESSIONS_FILE` JSON** — `bridge_server.py:13109`, `13075–13088` |
| Coherence report screen | Endpoint path `/api/coherence/report/{hwId}` — **TBD** router table list |
| Memory search | `/api/client/memory/search/{hwId}` — **TBD** backing tables |
| Weekly brief | `/api/research/nevedal/reports/brief` — **TBD** backing tables |
| AI consent | `/api/client/ai-consent` — **TBD** column mapping |
| Distress beacon | `swarm_relay.request(...)` — `bridge_server.py:28669–28675` (**TBD** persistence) |

### Schema mismatch risk (documented)

`client_get_coach_availability` resolves coach UUID `_coach_uuid` for `coach_availability` — `12166–12178`, but the **booked** query uses `coach_id = $1` with **`coach_id` variable** (hardware id) — `12206–12210` vs `_coach_uuid` on lines `12173–12178`. **Risk:** `coaching_sessions.coach_id` type may be UUID in PG while `coach_id` here is hardware id — verify schema; cited lines show the asymmetry.

---

## § 6 — Auth and connection lifecycle

1. **Lobby:** `_connectToBridge()` opens `_channel` — `main.dart:6306–6315`.
2. **`login_success`:** deferred navigation — `main.dart:6656–6787`; for clients with chat access, **`_ClientWsHub.attach(_channel!)`** — `6751–6752`, then `NeuralInterfaceV2` or `AiConsentScreen` / schedule variants.
3. **`_ClientWsHub`:** static shared channel + broadcast tee — `main.dart:10316–10328`.
4. **Neural chat:** new socket + `login_request` with `expected_role: "CLIENT"` — `updated_screens.dart:1467–1493`.
5. **Settings → schedule without password:** `ClientScheduleScreen` constructed **without** `password` — `settings_screen.dart:2964–2968`; relies on hub — `main.dart:10419–10427` or shows error path in `_connect()` — `main.dart:10447–10454`.
6. **Family Sanctuary:** closes parent chat socket before push — `updated_screens.dart:3701–3712`; reconnect on return — `3712`.
7. **Distress beacon:** **separate** `WebSocketChannel.connect` — `distress_beacon_screen.dart:75–78` (**no** `login_request` in traced snippet).

---

## § 7 — Known UX / reliability debt

| Item | Evidence |
|------|----------|
| Schedule / availability in flight | Debug logging on bridge path — `bridge_server.py:12153–12157`, `12271–12282`; Flutter schedule error UX — `main.dart:10410–10411`, `_connect` empty creds — `10447–10454` |
| Coach month overview auth gap | Handler lacks `role == "CLIENT"` — `bridge_server.py:14092–14100` |
| `coaching_sessions` query vs UUID | See §5 mismatch — `12206–12210` |
| Nevedal biometric volume | Timer **2s** — `nevedal_flutter.dart:471–472` |
| Service worker / web quirks | **TBD** (no log excerpt in this pass); see workspace rules on Safari / SW |
| Distress socket without login in snippet | `distress_beacon_screen.dart:75–78` sends `distress_beacon` without shown `login_request` |

---

## § 8 — Security and privacy boundaries

- **Client vs coach data:** Coach roster & overrides live in coach dashboard codepaths — e.g. `updated_screens.dart:4566+` (**not** client default route). Client schedule uses `assigned_coach_id` — `main.dart:10418`.
- **`assigned_coach_id` / `coach_id`:** Settings coach header prefers `coach_id` then `assigned_coach_id` — `settings_screen.dart:468`; bridge `client_get_coach_availability` uses `assigned_coach_id` — `bridge_server.py:12155`.
- **AI consent:** `AiConsentScreen` + profile keys — `ai_consent_screen.dart:21–35`, `main.dart:6761–6779`.
- **Family sanctuary:** member list + messages local state — `main.dart:2671–2678`; server message types `sanctuary_*` — `main.dart:3604+` (switch cases).
- **`client_get_coach_month_overview`:** callable without CLIENT role check in §4 — treat as **review item**.

**`recording_consent`:** Flutter grep in `settings_screen.dart` hits **coach help text** only — `settings_screen.dart:5786`; client-facing consent storage **TBD** for this spec.

---

## § 9 — Anti-patterns from git history (examples)

| Commit | Summary |
|--------|---------|
| `38158cc` | Client schedule: shared authenticated app WS + availability error handling |
| `2145c9d` | Attach `NeuralInterface` WS to `_ClientWsHub` after `login_success` |
| `8c2a768` | Gate diagnostic for `client_get_coach_availability` silent drop |
| `c43b9a3` | Diagnostic logging on `client_get_coach_availability` |
| `ea68dd3` | Tighten `client_get_upcoming_sessions` filter (duplicate AI rows) |
| `d7ec21a` | Bridge WebSocket `UnboundLocalError` / datetime shadowing fix |

---

## § 10 — “Steve Jobs” UX debt register (dated)

| Date | Severity | Friction |
|------|----------|----------|
| 2026-05-05 | High | Opening **Family Sanctuary** **closes** the primary chat socket — `updated_screens.dart:3701–3703` — user must tolerate reconnect latency. |
| 2026-05-05 | High | **Schedule from settings** omits password on `ClientScheduleScreen` — `settings_screen.dart:2964–2968` — depends on invisible hub state; failure mode strings in `_connect()` — `main.dart:10447–10454`. |
| 2026-05-05 | Medium | **Distress beacon** opens a **second** WebSocket without an obvious `login_request` in the same file — `distress_beacon_screen.dart:75–78` — identity/session story is unclear to the user. |
| 2026-05-05 | Medium | **Weekly brief** uses `X-User-Id` without Bearer token — `settings_screen.dart:6321–6323` — weaker alignment with other authenticated client calls. |
| 2026-05-05 | Low | **Legacy `NeuralInterface`** still exists alongside `NeuralInterfaceV2` — `main.dart:1339` vs `updated_screens.dart:1183` — increases cognitive load for maintainers. |

---

*End of foundational spec.*
