# Coach Portal — BRIEFINGS (Tab 3)

> Status: ACTIVE  
> Last full review: 2026-05-04  
> Next review due: 2026-05-11 (weekly cadence)  
> Owner: Nathan  
> Steve Jobs UX score: needs work  

---

## 1. Purpose (1 sentence)

The BRIEFINGS tab is where coaches pick a **briefings folder**, manage **session notes**, and pull **sanctuary**, **client**, and **presession** briefs — via WebSocket handlers in the bridge plus REST for notes and presession HTTP reads.

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
- [ ] Folder selection (`10696+`, `_selectedFolderId` `4191–4195`) restores a sensible default (auto-select first) and survives tab revisit without orphaned selection  
- [ ] Session notes load (`coach_get_session_notes` `5999–6020`) and new notes (`coach_add_session_note`) show success/error without duplicate rows in the list  
- [ ] REST notes (`POST/GET /api/coach/notes`, `coach.py:460–546`) stay consistent with what the coach sees from WS-backed note flows (no silent drift)  
- [ ] Sanctuary briefing (`coach_get_briefing` `20219`) vs client briefing (`coach_get_client_briefing` `20308`) are distinguishable in UI copy — not two mystery buttons  
- [ ] Presession brief (`get_presession_brief` `17382` + `GET /api/coach/presession-brief/{client_id}` `233–380`) handles sparse data (FCodes, crystals, sessions) without a blank screen  
- [ ] `_notesLoading` (`4196`) clears on every exit path (success, empty, error)  
- [ ] Note approval workflow (DB: `coach_notes` — per foundational table blurb) is reflected if notes can be pending/approved/rejected in product rules  

---

## 3. UI Components

| Component | Location | Purpose | Notes |
|---|---|---|---|
| Briefings tab scaffold | `mobile/lib/updated_screens.dart:10687+` (`_buildBriefingsTab`) | Tab shell | Tab 3 |
| Folder picker / list | `mobile/lib/updated_screens.dart:10696+` | Sets `_selectedFolderId` | Auto-select first folder |
| Session notes UI | — | list + add | WS `coach_get_session_notes`, `coach_add_session_note` |
| Sanctuary briefing | — | fetch | WS `coach_get_briefing` |
| Client briefing | — | fetch | WS `coach_get_client_briefing` |
| Presession brief | — | fetch | WS `get_presession_brief` + REST presession route |

---

## 4. Files (canonical references)

### Mobile
- `mobile/lib/updated_screens.dart:10687+` — `_buildBriefingsTab()`  
- `mobile/lib/updated_screens.dart:10696+` — folder selection, `_selectedFolderId`  
- `mobile/lib/updated_screens.dart:4191–4195` — `_selectedFolderId` field declarations  
- `mobile/lib/updated_screens.dart:4196` — `_notesLoading`  

### Backend WebSocket (`bridge_server.py`)
- `coach_get_session_notes` / `coach_add_session_note` — `5999–6020`  
- `coach_get_briefing` — `20219`  
- `coach_get_client_briefing` — `20308`  
- `get_presession_brief` — `17382`  

### Backend REST
- `backend/app/routers/coach.py:460–503` — `POST /api/coach/notes`  
- `backend/app/routers/coach.py:505–546` — `GET /api/coach/notes/{client_id}`  
- `backend/app/routers/coach.py:233–380` — `GET /api/coach/presession-brief/{client_id}`  

### Storage (tables)
- `coach_notes` — `001:230–256` (session notes; approval workflow per foundational)  
- `coach_briefings` — `027:118–128`  
- `family_sanctuary_sessions`, registry — sanctuary briefing path  
- `coaching_sessions` — client briefing path  
- `client_fcodes`, `nate_intelligence_crystals`, SSE-backed tables — presession brief composition per spec  

---

## 5. State Variables

| Variable | Type | Set true at | Set false at | Default |
|---|---|---|---|---|
| `_selectedFolderId` | String? / id | folder tap `10696+`; auto-select first | folder deleted / clear logic | first folder or null |
| `_notesLoading` | bool | notes fetch / add | response handled | false |

---

## 6. WebSocket Messages

| Direction | Type | Trigger | State change | Failure handling |
|---|---|---|---|---|
| → | `coach_get_session_notes` | Open notes / refresh | populates list | Clear `_notesLoading`; show error state |
| → | `coach_add_session_note` | Add note | append / refresh | Same |
| → | `coach_get_briefing` | Request sanctuary brief | briefing panel | Distinguish empty vs error |
| → | `coach_get_client_briefing` | Request client brief | briefing panel | Same |
| → | `get_presession_brief` | Presession action | presession content | Same; long queries need timeout copy |

**Critical pairings (must always co-occur):**
- Every notes fetch/add must reset `_notesLoading` on **all** branches  
- Briefing fetches that hit **multiple** backing stores (FCodes, crystals, sessions, SSE) must not display **partial** content as **authoritative** without labeling gaps  
- Do not add `coach_request_briefing` callers until a real handler exists (see §9)  

---

## 7. Database Schema

```sql
-- coach_notes — coach_id, client_id, session_id; approval workflow (001)
-- coach_briefings — 027:118–128
-- family_sanctuary_sessions + registry — coach_get_briefing
-- coaching_sessions — coach_get_client_briefing
-- client_fcodes, nate_intelligence_crystals, coaching_sessions, SSE — get_presession_brief / REST presession
```

**Approval gates:** `coach_notes` may include approval workflow — UI must match actual columns/workflow in product.  
**Soft delete:** follow `coach_notes` / briefing storage conventions; no speculative deletes from this spec.

---

## 8. Known Bugs (Resolved)

| Date | Commit | Bug | Fix |
|---|---|---|---|
| — | `bb81cb6` | Coach notes pipeline broken (pending get/approve/reject/redact not wired through bridge) | Bridge aliases wired for get_pending_notes / approve / reject / redact |
| — | `3ed97d1` | Coach-only verification failures including **briefing intake note** + PG session write gaps | Multi-fix rollout (briefing intake note + session write among 7 items) |
| — | `a475ec2` | Briefing missing crystal memory / intake notes; classroom session lookup gaps | Briefing crystal memory + intake notes + PG session lookup + wisdom snapshot handlers |

---

## 9. Anti-Patterns (Reject Without Investigation)

- ❌ **`coach_request_briefing` referenced or Sentinel-skipped without an implemented handler** — listed in `_FOUNDATIONAL_SPEC.md` Implementation Gaps (`bridge_server.py:10933` skip vs missing handler).  
- ❌ **Split-brain notes**: REST `/api/coach/notes` and WS `coach_get_session_notes` / `coach_add_session_note` returning divergent truth without a single reconciliation rule — class of pain that preceded `bb81cb6`-style wiring fixes.  
- ❌ **Shipping briefing enrichment (Phase 3/4)/UI that assumes SSE + wisdom + metrics are live** when bridge/backend paths are incomplete — addressed by `893b0b5`, `b5fe897` wiring work; don’t regress to half-connected briefings.  
- ❌ **Treating presession brief as “always full”** when inputs (FCodes, crystals, sessions) can be empty — causes false “broken app” reports.  

**Why this section exists:** briefings sit between **clinical prep** and **compliance**; silent failure is worse than an explicit error.

---

## 10. Daily Health Checks (run by `coach_portal_daily_check.sh`)

- [ ] Section 4 WS line anchors (`5999–6020`, `17382`, `20219`, `20308`) still valid  
- [ ] REST notes + presession routes still at `coach.py` ranges cited  
- [ ] No new `coach_request_briefing` sends without handler implementation  
- [ ] `_selectedFolderId` still documented vs `_coachActiveFolderId` (FOLDER tab) — no accidental merge  
- [ ] `coach_briefings` / `coach_notes` migrations still present in repo  

---

## 11. Investigation Cache

1. Read THIS FILE FIRST  
2. Open `updated_screens.dart:10687+` and bridge blocks in §4  
3. Reject §9 patterns before adding new briefing message types  
4. Update §8 when a briefing/notes regression is fixed with commit hash  
5. If CLIENTS “Open Folder” behavior changes (Tab 0 debt), re-verify briefings entry context  

**Last full investigation:** 2026-05-04 (spec-only from `_FOUNDATIONAL_SPEC.md` Tab 3)  
**Cost-saved estimate:** TBD after first code-level pass  

---

## 12. Steve Jobs Review

Apply quarterly. The standard is "would Steve ship this."

- [ ] Does the first interaction feel inevitable? **— Debt:** three briefing sources without one obvious “what to open before session”  
- [ ] Is anything on this screen unnecessary? **— Debt:** overlapping REST + WS for notes increases cognitive load  
- [ ] Could a non-technical user complete the primary action without instruction? **— Debt:** folder model vs separate FOLDER tab uses **two** active folder IDs in the app (`_selectedFolderId` vs `_coachActiveFolderId`)  
- [ ] Does the empty state teach the value of the tab? **— Debt:** presession brief empties must teach “nothing on file yet” vs error  
- [ ] Does the error state preserve trust? **— Debt:** intake / PG write failures (`3ed97d1` class) must not look like coach error  
- [ ] Is the most important thing the most prominent thing? **— Debt:** notes vs briefs compete; hero action unclear  

### Logged UX debt (target ship dates)

| Item | Issue | Target |
|------|--------|--------|
| SJ-1 | **Two folder-selection variables** for Briefings vs File Manager (`_selectedFolderId` vs `_coachActiveFolderId`) — cross-tab confusion | 2026-07-01 |
| SJ-2 | **Dual notes path** (WebSocket + REST) — one mental model needed | 2026-08-01 |
| SJ-3 | **Three briefing transports** (sanctuary WS, client WS, presession WS + REST) — consolidate behind one coach-facing “Brief for this session” | 2026-09-01 |

---

## 13. Cloning This Template (For New Tabs)

See `docs/coach_portal/_PIPELINE_TEMPLATE.md` §13.

---

## 14. Adapter Comments For Cursor

```
Read docs/coach_portal/features/04_briefings.md before any investigation.
Source: docs/coach_portal/_FOUNDATIONAL_SPEC.md Tab 3 (BRIEFINGS).
Do not invoke coach_request_briefing until a handler exists (Implementation Gaps).
Keep _selectedFolderId separate from FOLDER tab’s _coachActiveFolderId unless intentionally unifying UX.
```
