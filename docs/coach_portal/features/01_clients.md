# Coach Portal — CLIENTS (Tab 0)

> Status: ACTIVE  
> Last full review: 2026-05-04  
> Next review due: 2026-05-11 (weekly cadence)  
> Owner: Nathan  
> Steve Jobs UX score: needs work  

---

## 1. Purpose (1 sentence)

The CLIENTS tab is the coach’s caseload surface: search, filter, and open per-client context (including folder handoff) using the roster returned from `coach_get_clients` / `coach_clients`.

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
- [ ] Search updates the visible list immediately from local `_clientSearchQuery` (no extra round-trip)  
- [ ] Filter chips (All / Clients / Families / Coach-Only / Company) switch views without losing connection state  
- [ ] Clear-search control resets the query and restores the full filtered cohort  
- [ ] Empty roster differentiates “no assigned clients” from “still loading” / “auth failed”  
- [ ] App bar refresh re-runs `_fetchDashboard()` / `coach_get_clients` without orphaning filter or search state  

---

## 3. UI Components

| Component | Location | Purpose | Notes |
|---|---|---|---|
| Clients tab scaffold | `mobile/lib/updated_screens.dart:7710–7832` (`_buildClientsTab`) | Tab layout for caseload | Tab 0 body |
| Search field | `mobile/lib/updated_screens.dart:10944–10976` | Filter list by query | Writes `_clientSearchQuery` |
| Clear search control | `mobile/lib/updated_screens.dart:10952–10957` | Reset search | Local only |
| Filter chips | `mobile/lib/updated_screens.dart:11001–11018` | All / Clients / Families / Coach-Only / Company | Sets `_clientFilterMode` |
| Open client folder action | `mobile/lib/updated_screens.dart:7809–7823` | Jump to briefings + folder flow | Known debt: lands on BRIEFINGS (index 3), not FOLDER (index 8) |

---

## 4. Files (canonical references)

### Mobile
- `mobile/lib/updated_screens.dart:7710–7832` — `_buildClientsTab()` (tab shell + open-folder wiring)  
- `mobile/lib/updated_screens.dart:10944–11018` — search, clear, filter chips  
- `mobile/lib/updated_screens.dart:4144–4158` — `CoachDashboardScreenV2` widget  
- `mobile/lib/updated_screens.dart:4160–17688` — `_CoachDashboardScreenV2State` (shared dashboard state; CLIENTS uses filter/search fields at `4201–4203`)  

### Backend handler
- `backend/app/websocket/bridge_server.py:17176–17379` — `coach_get_clients` (assignment resolution + payload shape)  
- `bridge_server.py:17252–17260` — assignment predicates (`coach_id`, `assigned_coach_id`, `assigned_coach`, session history)  
- `bridge_server.py:17298–17319` — fields returned per client  

### Backend REST (alternative path)
- `backend/app/routers/coach.py:106–114` — `GET /api/coach/clients`  
- `backend/app/routers/coach.py:117–231` — `GET /api/coach/clients/{coach_id}`  

### Storage
- Tables: `users` (registry / PG), `sessions.json` (session-based inclusion), `coach_hierarchy` (assistant context per bridge logic), parietal metrics; `coach_assignments` (inventory — migration `083`, used by coach surfaces per foundational spec)  
- Read paths: WebSocket `coach_get_clients`; REST `get_assigned_clients` / PG session loads on `{coach_id}` route  

---

## 5. State Variables

| Variable | Type | Set true at | Set false at | Default |
|---|---|---|---|---|
| `_clientFilterMode` | enum-like (chip selection) | filter `onSelected` `11001–11018` | switching chip | per implementation |
| `_clientSearchQuery` | String | search `onChanged` `10944+` | clear control `10952–10957` | `''` |
| `_isLoading` | bool | app bar refresh `7466–7471`; `_fetchDashboard` entry | `login_success` / fetch completion paths | false |

*Full dashboard has 131 `setState` sites (`4161–4357` range per spec); CLIENTS-specific mutations are concentrated in search/filter handlers above.*

---

## 6. WebSocket Messages

| Direction | Type | Trigger | State change | Failure handling |
|---|---|---|---|---|
| → | `coach_get_clients` | `_fetchDashboard()` (`4565–4577`) after login / refresh | loading flags via parent `_fetchDashboard` | Must align with global `_isLoading` / retry via reconnect policy |
| ← | `coach_clients` | Bridge response (`6041+`) | populates `_clients` (shared list) | Empty vs error must be distinguished in UI (see criteria) |

**Critical pairings (must always co-occur):**
- Every `coach_get_clients` must be paired with UI clearing `_isLoading` on success or structured error  
- Reconnect (`_scheduleWsReconnect`) must eventually re-issue `coach_get_clients` through `_fetchDashboard`  
- Search/filter state should not reset on transient socket errors unless explicitly coded  

---

## 7. Database Schema

```sql
-- Primary: users (coach assignment in profile_data + columns per bridge rules)
-- coach_assignments: migration 083 (coach portal inventory)
-- coach_hierarchy: 068 (assistant/master relationships — bridge considers for roster)
-- Session history may pull from sessions store / coaching_sessions per REST path
```

**Approval gates:** none specific to roster display; assignment is server-resolved.  
**Soft delete:** not tab-specific; follow `users` / session store policies.

---

## 8. Known Bugs (Resolved)

| Date | Commit | Bug | Fix |
|---|---|---|---|
| — | `0125b5b` | Assistant coaches inherited master’s full client roster (privacy / scope leak) | Removed assistant→master client roster inheritance |
| — | `42b2416` | IDOR-style exposure via `/api/coach/clients/{coach_id}` and stats route | Closed IDOR on coach client + stats paths |
| — | `f5c618e` | Clients stuck showing `NOT_ASSIGNED_COACH` / assignment gaps in roster | Backfilled `coach_assignments` |

---

## 9. Anti-Patterns (Reject Without Investigation)

These are mistakes already surfaced in git history for this surface or its immediate API. If a code proposal contains any of these, reject before reading further.

- ❌ **Assistant sees another coach’s full roster without explicit hierarchy + scope rules** — landed as `0125b5b`.  
- ❌ **Trusting caller-supplied `coach_id` on `/clients/{coach_id}` or coach stats without server-side identity binding** — landed as `42b2416`.  
- ❌ **Leaving `NOT_ASSIGNED_COACH` / assignment holes that make clients vanish from the portal** — remediation `f5c618e`; don’t reintroduce silent assignment drift.  
- ❌ **Client-side “is master coach” trust for privileged coach chat or roster mutations** — server must verify (`ff224c8` pattern: verify master on coach nate-chat).  

**Why this section exists:** every entry above was a real bug or security fix that burned review time. Treat this list as battle-tested rules.

---

## 10. Daily Health Checks (run by `coach_portal_daily_check.sh`)

- [ ] All file references in section 4 still exist  
- [ ] All anti-patterns in section 9 still absent (grep checks)  
- [ ] WebSocket `coach_get_clients` / `coach_clients` pair still documented in bridge  
- [ ] No new TODO markers added since last review  
- [ ] Filter + search handlers still co-located near `10944–11018`  

---

## 11. Investigation Cache

When Cursor needs to work on this tab, it should:

1. Read THIS FILE FIRST (skip discovery)  
2. Open the files in section 4 by exact line numbers  
3. Check section 9 anti-patterns BEFORE proposing changes  
4. Update section 8 if a new bug is fixed  
5. Update section 11 with the date of investigation  

**Last full investigation:** 2026-05-04 (spec-only pass from `_FOUNDATIONAL_SPEC.md` Tab 0)  
**Cost-saved estimate:** TBD after first code-level pass  

---

## 12. Steve Jobs Review

Apply quarterly. The standard is "would Steve ship this."

- [ ] Does the first interaction feel inevitable? **— UX debt:** refresh-dependent roster vs instant mental model of “my clients”  
- [ ] Is anything on this screen unnecessary? **— Debt:** duplicate conceptual home for files (Open Folder vs FOLDER tab)  
- [ ] Could a non-technical user complete the primary action without instruction? **— Debt:** filter modes (Families / Company) need lay labels or onboarding  
- [ ] Does the empty state teach the value of the tab? **— Debt:** must spell why roster is empty (assignments vs filters)  
- [ ] Does the error state preserve trust? **— Debt:** WebSocket failures must not look like “you have no clients”  
- [ ] Is the most important thing the most prominent thing? **— Debt:** search vs filters compete for attention on small screens  

### Logged UX debt (target ship dates)

| Item | Issue | Target |
|------|--------|--------|
| SJ-1 | “Open Folder” jumps to **BRIEFINGS (tab index 3)** instead of **FOLDER (index 8)** — breaks “files live in one place” mental model (`7809–7823`) | 2026-06-15 |
| SJ-2 | **No pagination** — entire roster in one `coach_clients` payload; large practices will hit latency / memory / scroll cost on cellular | 2026-09-01 |
| SJ-3 | **Dual transport truth** — roster via WebSocket (`coach_get_clients`) vs REST (`/api/coach/clients*`) risks subtle drift for future features | 2026-07-01 |

---

## 13. Cloning This Template (For New Tabs)

See `docs/coach_portal/_PIPELINE_TEMPLATE.md` §13.

---

## 14. Adapter Comments For Cursor

```
Read docs/coach_portal/features/01_clients.md before any investigation.
The file contains:
- Exact line numbers for files in this tab (from foundational spec Tab 0)
- Anti-patterns to reject without analysis (from git log)
- Known bug history with commits

Skip discovery against bridge/Flutter except to verify line drift. Ground truth: docs/coach_portal/_FOUNDATIONAL_SPEC.md Tab 0.
If the doc is stale, update it as part of your fix and report the divergence.
```
