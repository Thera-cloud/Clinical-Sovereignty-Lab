# Coach Portal Foundational Spec

> **Generated:** 2026-05-04 — read-only investigation of shipped code.
> **Source of truth for:** per-tab pipeline specs.
> Every claim cites `file:line`. Items marked **TBD** are unverified.

---

## Architecture

### Entry Point & Routing

| Path | Source |
|------|--------|
| Lobby `login_success` → `role == 'COACH'` | `main.dart:6740–6749` |
| Post-onboarding tutorial | `updated_screens.dart:370–373` |
| Post-consent (ReConsentScreen) | `main.dart:9859–9864` |
| Post-ethics acceptance | `main.dart:9966–9970` |

**Widget:** `CoachDashboardScreenV2` — `updated_screens.dart:4144–4158`
**State class:** `updated_screens.dart:4160–17688` (~13.5k lines)

**Constructor:**
```dart
CoachDashboardScreenV2({
  required Map<String, dynamic> currentUserProfile,
  required String username,
  required String password,
})
```

### WebSocket Connection Lifecycle

1. `initState` → `TabController(length: 10)` + `_connectToBridge()` — `4360–4372`
2. `_connectToBridge()` — `4375–4418`: opens `WebSocketChannel`, sends `login_request` with `expected_role: "COACH"` — `4409–4414`
3. On `login_success` — `6031–6037`: stores `_authToken`, `_coachHardwareId`, calls `_fetchDashboard()`
4. `_fetchDashboard()` — `4565–4577`: fires `coach_get_clients`, `fetch_coach_calendar`, `coach_get_inbound_requests`, `coach_get_my_availability`, plus financials/classroom/assistant helpers
5. Reconnect: `_scheduleWsReconnect()` with exponential backoff — per `endpoint-websocket-sustainability.mdc`

### Shared State (`_CoachDashboardScreenV2State`)

**Declared fields:** `4161–4357` — 131 `setState` call sites across the class.

**Loading flags:**

| Flag | Line | Purpose |
|------|------|---------|
| `_isLoading` | 4197 | Gates entire dashboard body |
| `_notesLoading` | 4196 | Session notes fetch |
| `_financialsLoading` | 4231 | Financials tab |
| `_connectLoading` / `_connectOnboarding` | 4252–4253 | Stripe Connect |
| `_dojoSubsLoading` | 4260 | DOJO subscription list |
| `_dojoBusy` | 4301 | DOJO action in progress |
| `_classroomAnalyzing` / `_classroomLiveAnalyzing` | 4274–4285 | Classroom video analysis |
| `_assistantsTabLoading` | 4346 | Assistants tab |
| `_insightsChatLoading` | 4322 | Insights Nate chat |
| `_assistantChatLoading` | 4352 | Assistant Nate chat |
| `_coachFoldersLoading` | 17203 | Folder tab |

**Selection / filter state:**

| Variable | Line | Purpose |
|----------|------|---------|
| `_clientFilterMode` / `_clientSearchQuery` | 4201–4203 | Client list filtering |
| `_calMonth` / `_calSelectedDay` / `_calView` / `_calFocusedDate` | 4241–4244 | Calendar state |
| `_selectedFolderId` | 4191–4195 | Briefings folder selection |
| `_coachActiveFolderId` | 17201 | Folder tab active folder |
| `_expandedAssistant` | 4347 | Assistants accordion |
| `_classroomSelectedSessionId` | 4279 | Classroom selected session |

**No pagination cursors found** — all lists use full arrays from WS/REST responses.

---

## Tab Inventory

**Tab mechanism:**
- Desktop: `TabBar` in AppBar.bottom — `7440–7457`
- Mobile: popup menu via `_buildMobileNavDropdown()` — `7622–7707`
- Body: `TabBarView(controller: _tabController)` — `7515–7524`

**Documentation drift:** `.cursor/rules/coach-dashboard-tab-sync.mdc` lists 8 tabs; code has **10** (`TabController(length: 10)` at `4362`).

---

### Tab 0: CLIENTS

**Status:** Shipped
**Builder:** `_buildClientsTab()` — `7710–7832`
**Files:** `updated_screens.dart` (Flutter), `bridge_server.py` (WS handler), `coach.py` (REST)

#### Primary Actions

| Action | Line | Handler | Transport |
|--------|------|---------|-----------|
| Search clients | 10944–10976 | `onChanged` | Local `_clientSearchQuery` |
| Clear search | 10952–10957 | `onPressed` | Local |
| Filter chips (All/Clients/Families/Coach-Only/Company) | 11001–11018 | `onSelected` | Local `_clientFilterMode` |
| Open client folder | 7809–7823 | anonymous | `_openFolder(...)` → jumps to BRIEFINGS (index 3) |

#### WebSocket Messages

| Type | Direction | Handler line (bridge) | DB tables |
|------|-----------|----------------------|-----------|
| `coach_get_clients` | → server | 17176 | `users` (registry), `sessions.json`, `coach_hierarchy`, parietal metrics |
| `coach_clients` | ← server | 6041+ | — |

#### Backend Detail (`coach_get_clients` — `bridge_server.py:17176–17379`)

**Assignment resolution (non-admin):** `bridge_server.py:17252–17260`
- `profile_data.coach_id == coach_hardware_id` OR
- `profile_data.assigned_coach_id == coach_hardware_id` OR
- `profile_data.assigned_coach == coach_username` OR
- `hardware_id in session_client_ids` (from `sessions.json`)

**Per-client payload:** `bridge_server.py:17298–17319`
- `id`, `name`, `tier`, `subscription_plan`, `last_login`, `assigned_coach`, `family_id`, `group_id`, `company_id`, `company_name`, `can_access_nate`, `recording_consent`, `metrics`, `nevedal_state`, `total_sessions`

**REST alternative:** `GET /api/coach/clients` — `coach.py:106–114` (delegates to `get_assigned_clients`)
`GET /api/coach/clients/{coach_id}` — `coach.py:117–231` (PG `users` + `load_sessions_pg`)

#### Known UX Debt
- "Open Folder" jumps to BRIEFINGS (index 3), not FOLDER (index 8) — `7809–7823`
- No pagination; full client list loaded in one WS message

---

### Tab 1: SCHEDULE

**Status:** Shipped
**Builder:** `_buildScheduleTab()` — `7834+`
**Files:** `updated_screens.dart`, `bridge_server.py`, `schedule_api.py`, `sessions.py`

#### Primary Actions

| Action | Line | Handler | Transport |
|--------|------|---------|-----------|
| Accept inbound request | 7914–7918 | anonymous | WS `coach_accept_request` |
| Decline request | 7921–7931 | `_showCoachDeclineDialog` | WS `coach_decline_request` |
| Message requester | 7921–7931 | `_showCoachMessageDialog` | WS `coach_send_message` |
| Approve/decline booking | 15601, 15609 | anonymous | WS `coach_approve_booking` / `coach_decline_booking` |
| Calendar navigation | 7844–7848 | `setState` | Local `_calView` / `_calFocusedDate` |
| Block/unblock time | — | — | WS `coach_block_time` / `coach_unblock_time` |
| Create session | dialog ~4957+ | `_openCreateSessionDialog` | REST `POST /api/sessions/schedule` (`sessions.py:651+`) |
| Create consultation | 4907–4916 | anonymous | WS `coach_create_consultation` |
| Start Zoom | 8238–8247 | `_launchZoomMeeting` | External URL launch; REST for Zoom API (`4741–4822`) |

#### WebSocket Messages

| Type | Direction | Handler line | DB tables |
|------|-----------|-------------|-----------|
| `coach_get_inbound_requests` | → | 12631 | `coach_requests` |
| `coach_accept_request` | → | 12665 | `coach_requests`, `users`, notifications |
| `coach_decline_request` | → | 12735 | `coach_requests` |
| `coach_send_message` | → | 12770 | `coach_messages` |
| `coach_approve_booking` | → | 13169 | `coaching_sessions` |
| `coach_decline_booking` | → | 13681 | `coaching_sessions` |
| `coach_create_consultation` | → | 13290 | `coach_consultations` |
| `coach_cancel_consultation` | → | 13545 | `coach_consultations` |
| `coach_get_pending_bookings` | → | 13724 | `coaching_sessions` |
| `coach_get_my_availability` | → | 13927 | `coach_availability` |
| `coach_block_time` / `coach_unblock_time` | → | 13982 / 14035 | `coach_availability` |
| `update_availability` | → | 13844 | `coach_availability` |
| `fetch_coach_calendar` | → | 19309 | Schedule store / PG |
| `fetch_coach_sessions` | → | 19425 | Schedule store / PG |
| `coach_cancel_session` | → | 19435 | `coaching_sessions` |

#### REST Endpoints

| Method | Path | File:line | Auth |
|--------|------|-----------|------|
| POST | `/api/sessions/schedule` | `sessions.py:651+` | `_require_auth` |
| GET | `/api/sessions/coach/{coach_id}` | `sessions.py:839–852` | `_require_auth` |
| GET | `/api/sessions/upcoming/{user_id}` | `sessions.py:854–878` | `_require_auth` |
| GET | `/api/sessions/available-slots/{coach_id}` | `sessions.py:1579+` | `_require_auth` |
| Various | `/api/coach/schedule/*` | `schedule_api.py:19–241` | `require_coach` |

#### Known UX Debt
- Calendar state uses 4 separate variables (`_calMonth`, `_calSelectedDay`, `_calView`, `_calFocusedDate`) — complex state interaction

---

### Tab 2: INSIGHTS

**Status:** Shipped (partial — some metrics hardcoded)
**Builder:** `_buildInsightsTab()` — `10515–10684`
**Files:** `updated_screens.dart`, `bridge_server.py`, `coach.py`, `coach_override_protocol.py`

#### Primary Actions

| Action | Line | Handler | Transport |
|--------|------|---------|-----------|
| AI Modes picker | 10525–10544 | `_showCoachAiModePicker` → `_activateCoachAiMode` | WS `ai_mode_activate` (`6958–6963`) |
| Nevedal Report | 10549–10557 | `_showNevedalReportDialog` | REST `POST /api/research/nevedal/reports/generate` (`7049–7059`) |
| Insights chat send | 9847–9851 | `_sendInsightsChat` | REST `POST /api/coach/nate-chat` mode=`inquiry` (`9700–9711`) |
| Coach override set | — | `_buildCoachOverrideInsightsSection` (called `10610`) | WS `coach_set_client_override` |
| Override history | — | — | WS `coach_get_override_history` (`5525–5526`) |

#### WebSocket Messages

| Type | Direction | Handler line | DB tables |
|------|-----------|-------------|-----------|
| `ai_mode_activate` | → | 6958–6963 | — |
| `coach_set_client_override` | → | 17903 | `coach_client_overrides`, `coach_override_audit` |
| `coach_get_client_override` | → | 17903 | `coach_client_overrides` |
| `coach_clear_client_override` | → | 17903 | `coach_client_overrides`, `coach_override_audit` |
| `coach_get_override_history` | → | 17903 | `coach_override_audit` |
| `coach_renew_override` | → | 17903 | `coach_client_overrides`, `coach_override_audit` |
| `coach_get_client_panel_insights` | → | 17680 | SSE tables |

#### Known UX Debt
- "High Risk" and "Breakthroughs" show hardcoded `"0"` — `10585–10595` — not wired to backend
- Override feature is complex (5 WS message types) with audit trail

---

### Tab 3: BRIEFINGS

**Status:** Shipped
**Builder:** `_buildBriefingsTab()` — `10687+`
**Files:** `updated_screens.dart`, `bridge_server.py`, `coach.py`

#### Primary Actions

| Action | Line | Handler | Transport |
|--------|------|---------|-----------|
| Select folder | 10696+ | auto-select first | Local `_selectedFolderId` |
| Session notes | — | — | WS `coach_get_session_notes` (`5999–6020`) |
| Add note | — | — | WS `coach_add_session_note` |
| Get briefing (sanctuary) | — | — | WS `coach_get_briefing` (`20219`) |
| Get client briefing | — | — | WS `coach_get_client_briefing` (`20308`) |
| Presession brief | — | — | WS `get_presession_brief` (`17382`) |

#### WebSocket Messages

| Type | Handler line | DB tables |
|------|-------------|-----------|
| `coach_get_session_notes` | 5999–6020 | `coach_notes` |
| `coach_add_session_note` | 5999–6020 | `coach_notes` |
| `coach_get_briefing` | 20219 | `family_sanctuary_sessions`, registry |
| `coach_get_client_briefing` | 20308 | `coaching_sessions` |
| `get_presession_brief` | 17382 | `client_fcodes`, `nate_intelligence_crystals`, `coaching_sessions`, SSE tables |

#### REST Endpoints

| Method | Path | File:line |
|--------|------|-----------|
| POST | `/api/coach/notes` | `coach.py:460–503` |
| GET | `/api/coach/notes/{client_id}` | `coach.py:505–546` |
| GET | `/api/coach/presession-brief/{client_id}` | `coach.py:233–380` |

---

### Tab 4: DOJO

**Status:** Shipped (WebView/iframe — native Flutter fallback is dead code)
**Builder:** `_buildDojoTab()` — `12546–12624`
**Files:** `updated_screens.dart`, `dojo_api.py`, `night_school_director.py`

#### Implementation Detail
- **Production:** Embedded iframe/WebView loading `night_school_dojo.html` with `token`, `hw`, `ws` query params — `12553–12576`
- **Dead code:** `_buildDojoTabNative()` at `12645+` — defined but never called

#### WebSocket Messages (legacy native — still in bridge)

| Type | Handler line | Notes |
|------|-------------|-------|
| `dojo_start` | via `4459–4532` | Legacy native helpers |
| `dojo_end` | via `4459–4532` | Legacy native helpers |
| `dojo_test_message` | via `4459–4532` | Legacy native helpers |
| `dojo_share_learning` | via `4459–4532` | Legacy native helpers |

#### REST Endpoints

| Method | Path | File:line | Auth |
|--------|------|-----------|------|
| Various | `/api/dojo/*` | `dojo_api.py:17–19` | `require_coach` |

#### Known UX Debt
- Native DOJO UI (`_buildDojoTabNative`) is dead code — should be removed
- All DOJO interaction is inside HTML WebView, not native Flutter

---

### Tab 5: CLASSROOM

**Status:** Shipped
**Builder:** `_buildClassroomTab()` — `13142+`
**Files:** `updated_screens.dart`, `bridge_server.py`, `sessions.py` (classroom_router)

#### WebSocket Messages

| Type | Handler line | DB tables |
|------|-------------|-----------|
| `classroom_get_sessions` | 6434–6676+ | `classroom_session_analyses` |
| `classroom_get_progress` | 6434–6676+ | — |
| `classroom_get_analysis` | 6434–6676+ | `classroom_session_analyses` |
| `classroom_analyze_session` | 15325–15403 | `classroom_session_analyses` |
| `classroom_submit_reflection` | 15325–15403 | — |
| `classroom_check_recording` | 15325–15403 | — |
| `classroom_analyze_live` | 15325–15403 | — |

#### REST Endpoints

| Method | Path | File:line | Auth |
|--------|------|-----------|------|
| POST | `/api/classroom/upload-video/*` | `sessions.py:1682+` | `_require_auth` |

#### State
- `_classroomAnalyzing` / `_classroomLiveAnalyzing` — `4274–4285`
- `_classroomSelectedSessionId` — `4279`
- `_classroomVideoPollTimer` — `4210` (polling for video processing status)

---

### Tab 6: TRAINING

**Status:** Shipped
**Builder:** `_buildTrainingTab()` — `15774–15872`
**Files:** `updated_screens.dart`, `coaching_mesh_engine.py`, `coach_hierarchy_api.py`

#### Primary Actions

| Action | Line | Handler | Transport |
|--------|------|---------|-----------|
| Start Training Session | 15786–15795 | Navigator → `CoachingMeshScreen(isMaster: true)` | Separate screen |
| Join Training Session | 15800–15809 | Navigator → `CoachingMeshScreen(isMaster: false)` | Separate screen |
| Community Circle | 15819–15828 | Navigator → `CommunityMeshScreen` | Separate screen |
| Recent sessions list | 15838+ | `_fetchRecentTrainingSessions()` | REST **TBD** |

#### WebSocket Messages (via CoachingMeshScreen, not this tab directly)

| Type | Handler line | Service |
|------|-------------|---------|
| `coaching_mesh_create` | 29125+ | `CoachingMeshEngine.create_session` |
| `coaching_mesh_join` | 29125+ | `CoachingMeshEngine.join_session` |
| `coaching_mesh_leave` | 29125+ | `CoachingMeshEngine.leave_session` |
| `coaching_mesh_end` | 29125+ | `CoachingMeshEngine.end_session` |
| `coaching_mesh_message` | 29125+ | `CoachingMeshEngine.post_message` |
| `coaching_mesh_quiz` | 29125+ | `CoachingMeshEngine.push_quiz` |
| `coaching_mesh_scores` | 29125+ | `CoachingMeshEngine.get_session_scores` |

#### Database Tables
- `coaching_mesh_sessions` — `068:46–59`
- `coaching_mesh_participants` — `068:68–77`
- `coaching_mesh_messages` — `068:84–94`

---

### Tab 7: FINANCIALS

**Status:** Shipped
**Builder:** `_buildFinancialsTab()` — `16148+`
**Files:** `updated_screens.dart`, `bridge_server.py`

#### Primary Actions

| Action | Line | Handler | Transport |
|--------|------|---------|-----------|
| Refresh | 16171 | `_requestFinancials()` | WS `coach_get_financials` (`15485`) |
| Update Rate | 16237–16254 | `_setCoachFee` | WS `coach_set_fee` (`14141`) |
| Payment mode tiles | 16286–16333 | `_setPaymentMode` | WS `coach_set_payment_mode` (`14167`) |
| W-9 submit | — | — | WS `coach_submit_w9` (`14459`) |
| DOJO subscriptions | `_buildDojoSubscriptionsSection` (`16499+`) | — | WS `get_dojo_subscriptions`, `cancel_dojo_subscription`, `add_dojo_subscription` (`15574–15594`) |

#### WebSocket Messages

| Type | Handler line | DB tables |
|------|-------------|-----------|
| `coach_get_financials` | 14383 | `coaching_sessions`, `coach_w9_vault`, profile |
| `coach_set_fee` | 14141 | profile_data |
| `coach_set_payment_mode` | 14167 | profile_data |
| `coach_submit_w9` | 14459 | `coach_w9_vault` |
| `get_dojo_subscriptions` | 15574 | Stripe / subscriptions |
| `cancel_dojo_subscription` | 15574 | Stripe |
| `add_dojo_subscription` | 15594 | Stripe |

---

### Tab 8: FOLDER (File Manager)

**Status:** Shipped
**Builder:** `_buildFolderTab()` — `17205–17687`
**Files:** `updated_screens.dart`, `folder_api.py`

#### Primary Actions

| Action | Line | Handler | Transport |
|--------|------|---------|-----------|
| Pull refresh | 17207 | `_coachFetchFolders()` | REST `GET /api/coach/folders` (`17609`) |
| New Folder | 17235–17238 | `_coachCreateFolder` | REST `POST /api/coach/folders/create` (`17677–17678`) |
| Folder card tap | 17307–17314 | `_coachFetchFolderFiles` | REST `GET /api/coach/folders/$id/files` (`17629–17634`) |
| Upload file | 17363–17380 | `_coachPickAndUploadFile` (`17507+`) | REST multipart |

#### REST Endpoints

| Method | Path | File:line | Auth |
|--------|------|-----------|------|
| GET | `/api/coach/folders` | `folder_api.py:24–28` | `require_coach` |
| POST | `/api/coach/folders/create` | `folder_api.py` | `require_coach` |
| GET | `/api/coach/folders/{id}/files` | `folder_api.py` | `require_coach` |
| POST | `/api/coach/folders/{id}/upload` | `folder_api.py` | `require_coach` |

#### Database Tables
- `coach_folders` — `081:13–21`
- `coach_folder_files` — `081:26–36`

---

### Tab 9: ASSISTANTS

**Status:** Shipped
**Builder:** `_buildAssistantsTab()` — `10368–10502`
**Files:** `updated_screens.dart`, `bridge_server.py`, `coach_hierarchy_api.py`

#### Primary Actions

| Action | Line | Handler | Transport |
|--------|------|---------|-----------|
| Refresh | 10416–10421 | `_loadAssistantMetrics` | REST `GET /api/coach/hierarchy/assistant-metrics?days=30` (`9869–9871`) |
| Assistant chat | — | `_sendAssistantChat` | REST `POST /api/coach/nate-chat` mode=`assistant_inquiry` (`9990–9998`) |
| Free consultation | `_startConsultation` (`9913–9945`) | — | WS `master_consultation_request` (`9935–9939`) |

#### WebSocket Messages

| Type | Handler line | DB tables |
|------|-------------|-----------|
| `coach_invite_assistant` | 28852 | `coach_hierarchy` |
| `coach_accept_invitation` | 28899 | `coach_hierarchy` |
| `coach_list_assistants` | 28928 | `coach_hierarchy` |
| `coach_get_master` | 28962 | `coach_hierarchy` |
| `coach_revoke_assistant` | 28996 | `coach_hierarchy` |
| `coach_log_hours` | 29014 | `supervised_hours` |
| `coach_get_hours` | 29014+ | `supervised_hours` |
| `coach_export_hours` | 29014+ | `supervised_hours` |
| `coach_attest_hours` | 29103 | `supervised_hours` |
| `master_consultation_request` | 12862 | `coach_consultations` |

#### REST Endpoints

| Method | Path | File:line |
|--------|------|-----------|
| POST | `/api/coach/hierarchy/invite` | `coach_hierarchy_api.py:181` |
| POST | `/api/coach/hierarchy/accept` | `coach_hierarchy_api.py:206` |
| GET | `/api/coach/hierarchy/assistants/{id}` | `coach_hierarchy_api.py:225` |
| POST | `/api/coach/hierarchy/revoke` | `coach_hierarchy_api.py:254` |
| POST | `/api/coach/hierarchy/hours/log` | `coach_hierarchy_api.py:271` |
| GET | `/api/coach/hierarchy/hours/{id}` | `coach_hierarchy_api.py:291` |
| GET | `/api/coach/hierarchy/hours/export/{id}` | `coach_hierarchy_api.py:324` |
| POST | `/api/coach/hierarchy/hours/attest` | `coach_hierarchy_api.py:359` |
| GET | `/api/coach/hierarchy/assistant-metrics` | `coach_hierarchy_api.py:435` |
| GET | `/api/coach/hierarchy/assistant-clients/{username}` | `coach_hierarchy_api.py:522` |
| GET | `/api/coach/hierarchy/assistant-sessions/{username}` | `coach_hierarchy_api.py:575` |

#### Database Tables
- `coach_hierarchy` — `068:7–17` (master/assistant relationships)
- `supervised_hours` — `068:25–38`

---

## Global App Bar Actions

| Action | Line | Handler | Effect |
|--------|------|---------|--------|
| Connection info | 7461–7465 | `_showConnectionInfo` | Dialog only |
| Refresh | 7466–7471 | anonymous | `_isLoading=true; _fetchDashboard()` |
| Settings | 7473–7487 | anonymous | `Navigator → CoachSettingsScreen` |
| Logout | 7489–7496 | anonymous | Close socket; `pushReplacement → LobbyScreen` |

---

## Non-Tab Features (Overlays / Dialogs)

### Live Session Assistant
- WS types: `coach_start_live_session`, `coach_live_note`, `coach_live_biometric_update`, `coach_end_live_session` — `bridge_server.py:18536`
- Also: `session_assistant_*`, `session_service_mode_change`, `save_recording_consent` — `5960–12379` region

### Coach Nate Chat (shared by Insights + Assistants)
- REST: `POST /api/coach/nate-chat` — `coach.py:770+`
- Modes: `inquiry` (Insights), `assistant_inquiry` (Assistants)
- Service: `SkyEyeChatService` — verifies master via `coach_hierarchy`

---

## Database Tables (Coach-Specific)

### Core Coach Tables

| Table | Migration | Columns | Purpose | Used by tabs |
|-------|-----------|---------|---------|-------------|
| `coach_hierarchy` | `068:7–17` | id, master_coach_id, assistant_id, status, invited_at, accepted_at, revoked_at, created_at | Master/assistant relationships | ASSISTANTS |
| `supervised_hours` | `068:25–38` | id, assistant_id, master_coach_id, activity_type, dojo_type, duration_minutes, session_date, notes, attestation_status, attested_at, mesh_session_id, created_at | Supervised hours tracking | ASSISTANTS |
| `coaching_mesh_sessions` | `068:46–59` | id, session_id, master_coach_id, session_type, title, topic_tags, dojo_context, started_at, ended_at, participant_count, nate_participation, created_at | Training mesh sessions | TRAINING |
| `coaching_mesh_participants` | `068:68–77` | id, session_id (FK), user_id, role, joined_at, left_at, ble_device_id | Mesh participants | TRAINING |
| `coaching_mesh_messages` | `068:84–94` | id, session_id (FK), sender_id, message_type, content, metadata, parent_message_id, score, created_at | Mesh messages | TRAINING |
| `coach_folders` | `081:13–21` | Standard CRUD | File folders | FOLDER |
| `coach_folder_files` | `081:26–36` | Standard CRUD | Folder files | FOLDER |
| `coach_form_templates` | `081:44–55` | Standard CRUD | Form templates | **TBD** |
| `coach_availability` | `001:357–374`, `081:191–201`, `093:5–19` | coach_id, day_of_week, start_time, end_time, slot_duration, etc. | Recurring availability | SCHEDULE |
| `coach_signup_codes` | `081:209–222` | Standard CRUD | Signup/referral codes | **TBD** |
| `coaching_sessions` | `013:27–42` + many ALTERs | id, client_id, coach_id, scheduled_at, price_cents, status, family_id, session_type, zoom fields, notes, etc. | Therapy sessions | SCHEDULE, BRIEFINGS |
| `coach_notes` | `001:230–256` | coach_id, client_id, session_id, approval workflow | Session notes | BRIEFINGS |
| `coach_profiles` | `182:7–24` | Coach-only experience profile | Coach profile | Settings |
| `coach_requests` | `182:51–64` | Coach request pipeline | SCHEDULE |
| `coach_messages` | `182:82–90` | Coach messaging | SCHEDULE |
| `coach_client_overrides` | `186:3–16` | Coach clinical overrides | INSIGHTS |
| `coach_override_audit` | `189:3–12` | Audit trail for overrides | INSIGHTS |
| `coach_w9_vault` | `041:51–60` | W-9 tax document storage | FINANCIALS |
| `coach_nate_chat_history` | `090:5–13` | Coach Nate chat persistence | INSIGHTS, ASSISTANTS |
| `coach_nate_progress` | `078:19–35` | Coach Nate progress tracking | ASSISTANTS |
| `coach_assignments` | `083:6–15` | Coach-client assignment log | CLIENTS |
| `coach_consultations` | `093:22–33` | Consultation sessions | SCHEDULE |
| `coach_escalation_notifications` | `153:83–93` | Voice escalation alerts | **TBD** |
| `coach_metrics` | `052:143–162` | Coach performance metrics | INSIGHTS |
| `coach_briefings` | `027:118–128` | Pre-session briefings | BRIEFINGS |
| `coach_recruitment_campaigns` | `027:165–178` | Recruitment pipeline | **TBD** |
| `coach_assessment_results` | `027:180–190` | Assessment results | **TBD** |
| `coach_member_assignments` | `031:502–508` | Group member assignments | **TBD** |

### QuickBooks Coach Tables

| Table | Migration | Purpose |
|-------|-----------|---------|
| `qb_coach_connection` | `086:64–79` | Coach QB OAuth connection |
| `qb_coach_sync_log` | `086:81–93` | Sync history |
| `qb_coach_account_mapping` | `086:95–107` | Account mapping |

---

## Cross-Tab Dependencies

| Shared Resource | Tabs |
|----------------|------|
| `_socket` (WebSocket channel) | All tabs |
| `_authToken` / `_coachHardwareId` | All tabs making REST calls |
| Client list (`_clients`) | CLIENTS, SCHEDULE, INSIGHTS, BRIEFINGS, CLASSROOM |
| `_selectedFolderId` | BRIEFINGS, FOLDER (different variables — `_selectedFolderId` vs `_coachActiveFolderId`) |
| Coach Nate chat service | INSIGHTS (`mode: inquiry`), ASSISTANTS (`mode: assistant_inquiry`) |
| `coaching_sessions` table | SCHEDULE, BRIEFINGS, FINANCIALS, CLASSROOM |
| `coach_hierarchy` table | ASSISTANTS, TRAINING, Nate chat auth |
| `profile_data` (coach fields) | FINANCIALS (fee, payment mode), CLIENTS (assignment), Settings |

---

## Services Inventory

| Service | File | Used by |
|---------|------|---------|
| `CoachingMeshEngine` | `coaching_mesh_engine.py` | TRAINING tab (mesh sessions) |
| `CallCoachingEngine` | `call_coaching_engine.py` | Live call coaching (overlay) |
| `LiminalCoachingEngine` | `liminal_coaching_engine.py` | External conversation coaching |
| `CoachRecruitmentService` | `coach_recruitment.py` | Recruitment pipeline (**TBD** tab coverage) |
| `CoachMatcher` | `coach_matcher.py` | `/api/coach/matchmaker` endpoint |
| `SessionInterface` | `coach_experience/session_interface.py` | Live session notifications |
| `BriefingRenderer` | `coach_experience/briefing_renderer.py` | Pre-session briefings |
| `CaseloadManager` | `coach_experience/caseload_manager.py` | Client caseload queries |
| `CoachIntegrityShield` | `coach_integrity_shield.py` | Defense layer |
| `SkyEyeChatService` | `skyeye_chat.py` | Coach Nate chat |

---

## Implementation Gaps

### Features with Dead / Stub Code
- `_buildDojoTabNative()` — `updated_screens.dart:12645+` — defined, never called (native DOJO UI)
- "High Risk" / "Breakthroughs" metrics — `updated_screens.dart:10585–10595` — hardcoded `"0"`, not wired to backend
- `coach_request_briefing` — in `_SENTINEL_SKIP` set (`bridge_server.py:10933`) but no handler exists
- `coach_form_templates` table — created by `081:44–55`, no tab or UI references found

### Features in DB but Tab Coverage TBD
- `coach_escalation_notifications` — `153:83–93` — no direct tab UI found
- `coach_recruitment_campaigns` / `coach_assessment_results` — `027:165–190` — no tab UI found
- `coach_member_assignments` — `031:502–508` — no direct tab UI found
- `coach_signup_codes` — `081:209–222` — no tab UI found

### Documentation Drift
- `.cursor/rules/coach-dashboard-tab-sync.mdc` lists **8 tabs**; code has **10** (`TabController(length: 10)` at `4362`)
- Tabs TRAINING (6) and ASSISTANTS (9) appear to be the additions not reflected in the rule

### Known Architectural Concerns
- `_CoachDashboardScreenV2State` is ~13,500 lines — single monolithic state class
- No pagination on any list endpoint
- Client list fetched via WS (`coach_get_clients`) and REST (`/api/coach/clients`) with different resolution logic
- "Open Folder" in CLIENTS tab jumps to BRIEFINGS (index 3), not FOLDER (index 8)
- `coach_availability` has two competing `CREATE TABLE` definitions across migrations (`001` UUID-typed, `081` TEXT-typed; reconciled by `093`)
