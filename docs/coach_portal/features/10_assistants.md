# Coach Portal — ASSISTANTS (Tab 9)

> Status: ACTIVE  
> Last full review: 2026-05-04  
> Next review due: 2026-05-11 (weekly cadence)  
> Owner: Nathan  
> Steve Jobs UX score: needs work  

---

## 1. Purpose (1 sentence)

The ASSISTANTS tab lets a **master coach** manage **assistant relationships**, **supervised hours**, **assistant-scoped metrics**, **Coach Nate chat** (`assistant_inquiry`), and **free consultation** requests — via **REST** (`coach_hierarchy_api.py`) and **WebSocket** (`bridge_server.py`) against **`coach_hierarchy`** and **`supervised_hours`** (migration **068**).

---

## 2. UX Acceptance Criteria

These are the conditions a redesign must satisfy. If a code change breaks any of these, reject the change.

- [ ] Loads in under 2 seconds on cellular  
- [ ] First action a coach can take is visible without scrolling  
- [ ] No more than 3 primary CTAs visible at once  
- [ ] Error states have a clear next step (not just "something went wrong")  
- [ ] Loading states never persist beyond 30 seconds without user feedback  
- [ ] Touch targets are at least 44pt  
- [ ] Critical flows work offline or with clear offline state  
- [ ] **Refresh** (`10416–10421`, `_loadAssistantMetrics`, `GET …/assistant-metrics` `9869–9871`) clears **`_assistantsTabLoading`** (`4346`) on **all** outcomes  
- [ ] **Assistant Coach Nate chat** uses **`POST /api/coach/nate-chat`** with mode **`assistant_inquiry`** (`9990–9998`), not Insights’ `inquiry`  
- [ ] **Free consultation** (`_startConsultation` `9913–9945`) sends **`master_consultation_request`** (`9935–9939`) and surfaces success/failure without a silent hang  
- [ ] **Accordion** expansion (`_expandedAssistant`, `4347`) makes one assistant primary; collapsing does not orphan in-flight requests  
- [ ] **`_assistantChatLoading`** (`4352`) pairs with send completion and error paths for assistant chat  
- [ ] **Assistant metrics** distinguish **empty roster** vs **pending** relationships (server lists include pending where applicable — `e16d143`)  
- [ ] **REST hierarchy** calls rely on **server-resolved** coach identity for path params (`327ad92`, `309825c`); client must not assume raw ids grant cross-coach data  
- [ ] **Invite / accept / revoke / hours / attest** flows stay consistent with **`coach_hierarchy`** + **`supervised_hours`** row states (WS handlers `28852`–`29103` region per foundational map)  

---

## 3. UI Components

| Component | Location | Purpose | Notes |
|---|---|---|---|
| Assistants tab scaffold | `mobile/lib/updated_screens.dart:10368–10502` (`_buildAssistantsTab`) | Master/assistant shell | Tab 9 |
| Metrics refresh | `mobile/lib/updated_screens.dart:10416–10421` | `_loadAssistantMetrics` | REST |
| Assistant chat send | `mobile/lib/updated_screens.dart:9990–9998` | `_sendAssistantChat` | `assistant_inquiry` |
| Free consultation | `mobile/lib/updated_screens.dart:9913–9945` | `_startConsultation` | WS consult |
| Accordion / expand | `mobile/lib/updated_screens.dart:4347` | `_expandedAssistant` | Per-assistant focus |

---

## 4. Files (canonical references)

### Mobile
- `mobile/lib/updated_screens.dart:10368–10502` — `_buildAssistantsTab()`  
- `mobile/lib/updated_screens.dart:10416–10421` — refresh metrics  
- `mobile/lib/updated_screens.dart:9869–9871` — `GET …/assistant-metrics?days=30` call site anchor  
- `mobile/lib/updated_screens.dart:9913–9945` — `_startConsultation`  
- `mobile/lib/updated_screens.dart:9935–9939` — `master_consultation_request` send  
- `mobile/lib/updated_screens.dart:9990–9998` — `_sendAssistantChat` → `assistant_inquiry`  
- `mobile/lib/updated_screens.dart:4346` — `_assistantsTabLoading`  
- `mobile/lib/updated_screens.dart:4347` — `_expandedAssistant`  
- `mobile/lib/updated_screens.dart:4352` — `_assistantChatLoading`  

### WebSocket (`bridge_server.py` — handler line anchors from foundational spec)
- `coach_invite_assistant` — `28852`  
- `coach_accept_invitation` — `28899`  
- `coach_list_assistants` — `28928`  
- `coach_get_master` — `28962`  
- `coach_revoke_assistant` — `28996`  
- `coach_log_hours` / `coach_get_hours` / `coach_export_hours` — `29014+`  
- `coach_attest_hours` — `29103`  
- `master_consultation_request` — `12862` (also referenced `9935–9939` Flutter send)  

### REST (`coach_hierarchy_api.py`)
- `POST /api/coach/hierarchy/invite` — `181`  
- `POST /api/coach/hierarchy/accept` — `206`  
- `GET /api/coach/hierarchy/assistants/{id}` — `225`  
- `POST /api/coach/hierarchy/revoke` — `254`  
- `POST /api/coach/hierarchy/hours/log` — `271`  
- `GET /api/coach/hierarchy/hours/{id}` — `291`  
- `GET /api/coach/hierarchy/hours/export/{id}` — `324`  
- `POST /api/coach/hierarchy/hours/attest` — `359`  
- `GET /api/coach/hierarchy/assistant-metrics` — `435`  
- `GET /api/coach/hierarchy/assistant-clients/{username}` — `522`  
- `GET /api/coach/hierarchy/assistant-sessions/{username}` — `575`  

### Coach Nate chat (shared)
- `POST /api/coach/nate-chat` — `coach.py:770+` — modes: **`inquiry`** (Insights), **`assistant_inquiry`** (Assistants); service verifies master via `coach_hierarchy`  

### Storage
- Migration: `backend/migrations/068_coach_hierarchy.sql`  
- Tables: **`coach_hierarchy`**, **`supervised_hours`**  
- Related persistence: **`coach_nate_chat_history`** (090), **`coach_nate_progress`** (078) — used with INSIGHTS + ASSISTANTS per global table map  

---

## 5. State Variables

| Variable | Type | Set true at | Set false at | Default |
|---|---|---|---|---|
| `_assistantsTabLoading` | bool | metrics refresh start `10416+` | metrics request complete / error | false |
| `_expandedAssistant` | String? / expansion key | accordion tap | collapse / switch | null |
| `_assistantChatLoading` | bool | assistant chat send | response / error | false |

*Consultation-in-progress flags (if any) should live next to `_startConsultation` `9913+` — confirm in code when extending §5.*  

---

## 6. WebSocket Messages

| Direction | Type | Trigger | State change | Failure handling |
|---|---|---|---|---|
| → | `coach_invite_assistant` | Invite flow | — | reset loading; show error |
| → | `coach_accept_invitation` | Accept invite | — | same |
| → | `coach_list_assistants` | List refresh | — | same |
| → | `coach_get_master` | Resolve master | — | same |
| → | `coach_revoke_assistant` | Revoke | — | same |
| → | `coach_log_hours` | Log supervised time | — | same |
| ← / → | `coach_get_hours` / export / attest | Hours UI | — | pair with `_assistantsTabLoading` or local busy |
| → | `master_consultation_request` | Free consultation `9935–9939` | — | must not leave UI pending forever |

**Critical pairings (must always co-occur):**
- Every **`_assistantsTabLoading`** set MUST clear on REST completion for `assistant-metrics`  
- Every **`_assistantChatLoading`** set MUST clear on chat REST success/failure  
- **`master_consultation_request`** MUST have user-visible outcome (timeout or response)  

---

## 7. Database Schema

```sql
-- coach_hierarchy — 068:7–17
-- id, master_coach_id, assistant_id, status, invited_at, accepted_at, revoked_at, created_at

-- supervised_hours — 068:25–38
-- id, assistant_id, master_coach_id, activity_type, dojo_type, duration_minutes,
-- session_date, notes, attestation_status, attested_at, mesh_session_id, created_at
```

**Approval gates:** attestation flows — **`attestation_status`** / **`coach_attest_hours`** (`29103`).  
**Soft delete:** relationships use **`revoked_at`** / status on `coach_hierarchy`; follow API semantics.  

---

## 8. Known Bugs (Resolved)

| Date | Commit | Bug | Fix |
|---|---|---|---|
| — | `309825c` | **IDOR** on hierarchy path-id endpoints (assistants, metrics, clients, hours) | Server-side binding / authorization closure |
| — | `327ad92` | **`coach_hierarchy_api`** brittle identity + SQL casts on session data | SQL-safe casts + resolver accepts uuid/hardware_id/username |
| — | `e16d143` | **`assistant-metrics`** REST lists omitted **pending_admin** rows | Include pending in metrics aggregation |

---

## 9. Anti-Patterns (Reject Without Investigation)

- ❌ **Trusting URL/path `{id}` or `{username}` for another coach’s data** without server-enforced master/assistant binding — caused **IDOR** (`309825c`).  
- ❌ **`assistant-metrics` or roster APIs** that drop **pending** hierarchy rows — coaches see false “zero assistants” (`e16d143`).  
- ❌ **Calling `POST /api/coach/nate-chat` with `inquiry` from Assistants tab** — must be **`assistant_inquiry`**; breaks `SkyEyeChatService` master verification (cross-tab dependency table).  
- ❌ **Assuming a single id format** (username vs hardware_id vs UUID) in hierarchy clients — resolver and SQL casts must stay aligned (`327ad92`).  

**Why this section exists:** hierarchy bugs are **authorization** bugs; one wrong assumption leaks another coach’s assistant roster or hours.

---

## 10. Daily Health Checks (run by `coach_portal_daily_check.sh`)

- [ ] `_buildAssistantsTab` range `10368–10502` still valid  
- [ ] `coach_hierarchy_api.py` routes in §4 still present at cited lines (spot-check after edits)  
- [ ] Grep: Flutter does not call `nate-chat` from Assistants without **`assistant_inquiry`**  
- [ ] Bridge handlers `28852`–`29103` still registered (no rename without doc update)  
- [ ] Migration **068** tables unchanged or doc updated  

---

## 11. Investigation Cache

1. Read THIS FILE FIRST  
2. Open **`updated_screens.dart:10368+`** + **`coach_hierarchy_api.py`** + bridge **28852+** for any hierarchy change  
3. Verify **IDOR** regression tests / path param handling after touching `assistants/{id}` or `assistant-clients/{username}`  
4. Update §8 when a metrics or chat-mode regression ships with commit hash  
5. Keep **Insights** vs **Assistants** Nate mode strings in sync with `coach.py` contract  

**Last full investigation:** 2026-05-04 (spec-only from `_FOUNDATIONAL_SPEC.md` Tab 9)  
**Cost-saved estimate:** TBD after first code-level pass  

---

## 12. Steve Jobs Review

Apply quarterly. The standard is "would Steve ship this."

- [ ] Does the first interaction feel inevitable? **— Debt:** “assistants” competes with **Clients** mental model (same people, different role)  
- [ ] Is anything on this screen unnecessary? **— Debt:** **WS + REST + consultation** in one tab without a single clear story arc  
- [ ] Could a non-technical user complete the primary action without instruction? **— Debt:** invite vs accept vs attest vocabulary is administrative  
- [ ] Does the empty state teach the value of the tab? **— Debt:** zero assistants should explain *why* hierarchy exists (supervision, hours)  
- [ ] Does the error state preserve trust? **— Debt:** auth failures must not imply assistant “deleted” roster  
- [ ] Is the most important thing the most prominent thing? **— Debt:** metrics refresh vs chat vs consultation — priority unclear  

### Logged UX debt (target ship dates)

| Item | Issue | Target |
|------|--------|--------|
| SJ-1 | **Triple transport** (WS hierarchy + REST metrics/chat + consultation WS) — one coherent narrative | 2026-07-15 |
| SJ-2 | **Docs/rules drift** — legacy **8-tab** rule omits ASSISTANTS (and TRAINING); coaches reading internal docs get wrong map | 2026-06-01 |
| SJ-3 | **Shared Coach Nate** — `inquiry` vs `assistant_inquiry` is invisible; mis-wire reads as “Nate is dumb” not “wrong mode” | 2026-06-20 |

---

## 13. Cloning This Template (For New Tabs)

See `docs/coach_portal/_PIPELINE_TEMPLATE.md` §13.

---

## 14. Adapter Comments For Cursor

```
Read docs/coach_portal/features/10_assistants.md before any investigation.
Source: docs/coach_portal/_FOUNDATIONAL_SPEC.md Tab 9 (ASSISTANTS).
Flutter: updated_screens.dart _buildAssistantsTab 10368–10502; loading 4346; accordion 4347; assistant chat 4352; metrics 9869–9871; nate-chat assistant_inquiry 9990–9998; consultation 9913–9945 / master_consultation_request 9935–9939.
REST: coach_hierarchy_api.py invite through assistant-sessions. WS: bridge_server.py 28852–29103, master_consultation 12862.
Anti-patterns: no IDOR regressions on path ids (309825c); include pending in metrics (e16d143); never use inquiry mode from this tab.
```
