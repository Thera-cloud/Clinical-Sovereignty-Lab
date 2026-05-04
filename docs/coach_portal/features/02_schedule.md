# Coach Portal — SCHEDULE (Tab 1)

> Status: ACTIVE  
> Last full review: 2026-05-04  
> Next review due: 2026-05-11 (weekly cadence)  
> Owner: Nathan  
> Steve Jobs UX score: needs work  

---

## 1. Purpose (1 sentence)

The SCHEDULE tab is the coach’s command center for inbound requests, pending bookings, calendar navigation, availability blocks, session/consultation creation, Zoom launch, and session cancellation—wired through WebSocket handlers plus REST for core scheduling.

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
- [ ] Accept / decline / message on an inbound request gives explicit outcome feedback and updates the pending list  
- [ ] Approve / decline booking updates the UI without stale rows or duplicate session entries  
- [ ] Calendar navigation (`_calView` / `_calFocusedDate`) keeps the visible month/day consistent (no “jumped” selection)  
- [ ] Create session (`POST /api/sessions/schedule`) surfaces validation errors in human language and preserves form draft where possible  
- [ ] Create consultation (`coach_create_consultation`) completes with clear success; optional Zoom path does not silently no-op  
- [ ] Start Zoom (`_launchZoomMeeting`) only opens externally after a valid join URL is available (or explains why not)  
- [ ] Block / unblock time (`coach_block_time` / `coach_unblock_time`) reflects in the calendar after server ack  

---

## 3. UI Components

| Component | Location | Purpose | Notes |
|---|---|---|---|
| Schedule tab scaffold | `mobile/lib/updated_screens.dart:7834+` (`_buildScheduleTab`) | Tab layout for scheduling | Entry for Tab 1 |
| Calendar navigation | `mobile/lib/updated_screens.dart:7844–7848` | Change view / focused date | Drives `_calView`, `_calFocusedDate` |
| Inbound request actions | `mobile/lib/updated_screens.dart:7914–7918` | Accept | WS `coach_accept_request` |
| Decline / message | `mobile/lib/updated_screens.dart:7921–7931` | Decline, message requester | Dialogs + `coach_decline_request` / `coach_send_message` |
| Booking approve/decline | `mobile/lib/updated_screens.dart:15601`, `15609` | Pending bookings | WS `coach_approve_booking` / `coach_decline_booking` |
| Create consultation | `mobile/lib/updated_screens.dart:4907–4916` | Consultation flow | WS `coach_create_consultation` |
| Create session dialog | `mobile/lib/updated_screens.dart:~4957+` (`_openCreateSessionDialog`) | Schedule session | REST `POST /api/sessions/schedule` |
| Start Zoom | `mobile/lib/updated_screens.dart:8238–8247` | `_launchZoomMeeting` | External URL; REST Zoom helpers `4741–4822` |

---

## 4. Files (canonical references)

### Mobile
- `mobile/lib/updated_screens.dart:7834+` — `_buildScheduleTab()`  
- `mobile/lib/updated_screens.dart:7844–7848` — calendar `setState` navigation  
- `mobile/lib/updated_screens.dart:7914–7931` — inbound accept / decline / message  
- `mobile/lib/updated_screens.dart:4907–4916` — consultation create  
- `mobile/lib/updated_screens.dart:~4957+` — `_openCreateSessionDialog`  
- `mobile/lib/updated_screens.dart:8238–8247` — `_launchZoomMeeting`  
- `mobile/lib/updated_screens.dart:4741–4822` — Zoom-related REST usage (per foundational spec)  
- `mobile/lib/updated_screens.dart:15601`, `15609` — booking approve / decline  
- `mobile/lib/updated_screens.dart:4241–4244` — `_calMonth`, `_calSelectedDay`, `_calView`, `_calFocusedDate`  

### Backend WebSocket (`bridge_server.py`)
- `coach_get_inbound_requests` — `12631`  
- `coach_accept_request` — `12665`  
- `coach_decline_request` — `12735`  
- `coach_send_message` — `12770`  
- `coach_approve_booking` — `13169`  
- `coach_decline_booking` — `13681`  
- `coach_create_consultation` — `13290`  
- `coach_cancel_consultation` — `13545`  
- `coach_get_pending_bookings` — `13724`  
- `coach_get_my_availability` — `13927`  
- `coach_block_time` / `coach_unblock_time` — `13982` / `14035`  
- `update_availability` — `13844`  
- `fetch_coach_calendar` — `19309`  
- `fetch_coach_sessions` — `19425`  
- `coach_cancel_session` — `19435`  

### Backend REST
- `backend/app/routers/sessions.py:651+` — `POST /api/sessions/schedule`  
- `backend/app/routers/sessions.py:839–852` — `GET /api/sessions/coach/{coach_id}`  
- `backend/app/routers/sessions.py:854–878` — `GET /api/sessions/upcoming/{user_id}`  
- `backend/app/routers/sessions.py:1579+` — `GET /api/sessions/available-slots/{coach_id}`  
- `backend/app/routers/schedule_api.py:19–241` — `/api/coach/schedule/*` (`require_coach`)  

### Storage (tables this tab touches)
- `coach_requests`, `coach_messages`, `coaching_sessions`, `coach_consultations`, `coach_availability` — per foundational Tab 1 WS table  

---

## 5. State Variables

| Variable | Type | Set at | Reset / pairing | Default |
|---|---|---|---|---|
| `_calMonth` | int (typ.) | calendar navigation | `7844–7848` + other calendar handlers | per implementation |
| `_calSelectedDay` | DateTime? / int | calendar selection | paired with month/view | per implementation |
| `_calView` | enum-like | `7844–7848` | must stay consistent with `_calFocusedDate` | per implementation |
| `_calFocusedDate` | DateTime | `7844–7848` | **known debt:** 4-way interaction across all four vars | per implementation |
| `_isLoading` | bool | app bar refresh / `_fetchDashboard` | login_success / fetch complete | false |

*Dashboard-wide loading and reconnect behavior: see `_FOUNDATIONAL_SPEC.md` “WebSocket Connection Lifecycle” and `_fetchDashboard()` `4565–4577` (fires `fetch_coach_calendar`, `coach_get_inbound_requests`, `coach_get_my_availability`).*

---

## 6. WebSocket Messages

| Direction | Type | Trigger | State change | Failure handling |
|---|---|---|---|---|
| → | `coach_get_inbound_requests` | Dashboard fetch | populates inbound list | Must not duplicate with stale merge |
| → | `coach_accept_request` | Accept tap `7914–7918` | remove/update request row | Dialog + retry path |
| → | `coach_decline_request` | Decline flow | same | same |
| → | `coach_send_message` | Message flow | same | same |
| → | `coach_approve_booking` | Approve `15601` | updates bookings / sessions | Must not leave duplicate session rows client-side |
| → | `coach_decline_booking` | Decline `15609` | same | same |
| → | `coach_create_consultation` | Consultation `4907–4916` | consultation list/calendar | User-visible success/failure |
| → | `coach_cancel_consultation` | (tab-related flows) | clears consultation | — |
| → | `coach_get_pending_bookings` | refresh / polling pattern | pending UI | Timeout + message |
| → | `coach_get_my_availability` | availability section | blocks display | — |
| → | `coach_block_time` / `coach_unblock_time` | block UI | local + server mirror | Rollback UI if NACK |
| → | `update_availability` | recurring availability edits | same | — |
| → | `fetch_coach_calendar` | `_fetchDashboard` / refresh | calendar model | Reconnect must re-fetch |
| → | `fetch_coach_sessions` | session list | session rows | same |
| → | `coach_cancel_session` | cancel flow | removes session | Confirm destructive |

**Critical pairings (must always co-occur):**
- Calendar fetch (`fetch_coach_calendar`) and session fetch (`fetch_coach_sessions`) must stay logically consistent after any booking approve/cancel  
- Every approve/create path must guard against **duplicate visible rows** (server filter discipline + client list merge)  
- Zoom launch must not fire without a resolved URL; errors surface in-tab  

---

## 7. Database Schema

```sql
-- coach_requests — inbound pipeline
-- coach_messages — messaging requester
-- coaching_sessions — bookings, scheduled sessions, Zoom fields
-- coach_consultations — consultation lifecycle
-- coach_availability — blocks + recurring availability
-- Migrations: coach_availability spread across 001/081/093 per global spec
```

**Approval gates:** booking approval mutates `coaching_sessions`; inbound accept touches `coach_requests` + notifications per handler lines above.  
**Soft delete:** follow each table’s pattern; not tab-specific in foundational spec.

---

## 8. Known Bugs (Resolved)

| Date | Commit | Bug | Fix |
|---|---|---|---|
| — | `ea68dd3` | Duplicate “AI” / spurious rows in client upcoming sessions (filter too loose) | Tightened `client_get_upcoming_sessions` filter |
| — | `885a0bd` | Calendar visibility gaps; Zoom link delivery UX | Calendar visibility fix; auto-send Zoom link + resend control |
| — | `c559934` | SSE / scheduled work duplicated (clone + primary both scheduling) | Clone scheduler gate + unique constraint |

---

## 9. Anti-Patterns (Reject Without Investigation)

- ❌ **Loose session/upcoming filters** that let duplicate or phantom rows into coach or client calendars — class repaired in `ea68dd3`.  
- ❌ **Assuming calendar UI reflects server truth** without post-mutation refresh — historically tied to visibility / sync bugs (`885a0bd`).  
- ❌ **Dual schedulers or unconstrained cron on clone + primary** causing duplicate timed delivery — `c559934`, `365f5a9`.  
- ❌ **Letting consultation + session flows diverge on Zoom handoff** without explicit success path — `5816cb4` “optional Zoom path” deploy notes imply prior rough edges.  

**Why this section exists:** schedule is high-stakes; these patterns already shipped as incidents or hotfixes.

---

## 10. Daily Health Checks (run by `coach_portal_daily_check.sh`)

- [ ] Section 4 line anchors still exist in `updated_screens.dart` / `bridge_server.py` / routers  
- [ ] `fetch_coach_calendar` + `fetch_coach_sessions` still paired after mutations  
- [ ] No regression of duplicate-row filters on upcoming/session queries (grep guard vs old patterns)  
- [ ] `schedule_api.py` router still mounted under `/api/coach/schedule`  
- [ ] WebSocket handler line table in section 6 still matches bridge (spot-check on edit)  

---

## 11. Investigation Cache

1. Read THIS FILE FIRST (skip discovery)  
2. Open files in section 4 at listed lines  
3. Reject proposals matching section 9 before deep reading  
4. Update section 8 when a schedule bug is fixed with commit hash  
5. Bump “Last full review” when calendar state or booking flow changes  

**Last full investigation:** 2026-05-04 (spec-only pass from `_FOUNDATIONAL_SPEC.md` Tab 1)  
**Cost-saved estimate:** TBD after first code-level pass  

---

## 12. Steve Jobs Review

Apply quarterly. The standard is "would Steve ship this."

- [ ] Does the first interaction feel inevitable? **— Debt:** four calendar variables make “where am I in time?” feel fragile  
- [ ] Is anything on this screen unnecessary? **— Debt:** WS + REST split for overlapping concepts (create session vs consultation)  
- [ ] Could a non-technical user complete the primary action without instruction? **— Debt:** block/unblock + availability vs bookings need plain-language grouping  
- [ ] Does the empty state teach the value of the tab? **— Debt:** “no requests” vs “nothing scheduled” must read differently  
- [ ] Does the error state preserve trust? **— Debt:** Zoom URL missing must not feel like user error  
- [ ] Is the most important thing the most prominent thing? **— Debt:** inbound requests vs calendar compete for attention  

### Logged UX debt (target ship dates)

| Item | Issue | Target |
|------|--------|--------|
| SJ-1 | **Four correlated calendar state variables** (`_calMonth`, `_calSelectedDay`, `_calView`, `_calFocusedDate`) — high bug surface, hard to reason about | 2026-07-01 |
| SJ-2 | **Mixed transport model** — many scheduling actions on WebSocket, core “create session” on REST; harder to reason about failure & retry | 2026-08-01 |
| SJ-3 | **Consultation vs session + optional Zoom** — two creation paths (`4907–4916` vs `~4957+`) risk “which one do I use?” without guided choice | 2026-06-15 |

---

## 13. Cloning This Template (For New Tabs)

See `docs/coach_portal/_PIPELINE_TEMPLATE.md` §13.

---

## 14. Adapter Comments For Cursor

```
Read docs/coach_portal/features/02_schedule.md before any investigation.
The file contains:
- Tab 1 line anchors from docs/coach_portal/_FOUNDATIONAL_SPEC.md
- Anti-patterns tied to real git fixes (duplicates, calendar visibility, dual schedulers)
- Calendar state debt called out explicitly

Skip code rediscovery unless verifying line drift. Update this file when behavior changes.
```
