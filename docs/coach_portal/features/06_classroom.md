# Coach Portal — CLASSROOM (Tab 5)

> Status: ACTIVE  
> Last full review: 2026-05-04  
> Next review due: 2026-05-11 (weekly cadence)  
> Owner: Nathan  
> Steve Jobs UX score: needs work  

---

## 1. Purpose (1 sentence)

The CLASSROOM tab lets coaches list **classroom sessions**, inspect **progress** and **analysis**, **analyze** recordings (including **live** analysis), **check recording** status, **submit reflections**, and **upload video** — primarily through WebSocket messages to `bridge_server.py` plus **`/api/classroom/upload-video/*`** on `sessions.py`.

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
- [ ] `_classroomAnalyzing` / `_classroomLiveAnalyzing` (`4274–4285`) **always** clear on **WebSocket error**, completion, and cancel — never stuck “analyzing” (`e40900e` class)  
- [ ] `_classroomVideoPollTimer` (`4210`) is bounded: if processing stalls, the coach sees **stale-state copy + retry**, not silence  
- [ ] Switching tabs **preserves** in-progress video/upload context where the product promises continuity (`999ee75` class — no silent loss)  
- [ ] Selected session (`_classroomSelectedSessionId`, `4279`) remains consistent with the visible analysis panel after refresh and reconnect  
- [ ] Browser/Flutter **upload** paths (`POST /api/classroom/upload-video/*`, `1682+`) show **auth** and **compat** errors plainly — no opaque `403` / `ArrayBuffer` crashes (`1d4af73` class)  
- [ ] **Live** vs **batch** analyze affordances are visually distinct so coaches don’t trigger the wrong pipeline  
- [ ] When analysis runs, coaches see **stages / progress** (polling or pushed updates), not a frozen spinner (`2c302d8` class)  

---

## 3. UI Components

| Component | Location | Purpose | Notes |
|---|---|---|---|
| Classroom tab scaffold | `mobile/lib/updated_screens.dart:13142+` (`_buildClassroomTab`) | Tab shell | Session list, analysis, upload UX |
| Session selection | tied to `_classroomSelectedSessionId` (`4279`) | Focus one session | Drives analysis/reflection context |
| Analysis / live analysis | `_classroomAnalyzing` / `_classroomLiveAnalyzing` | Busy gates | Must reset on all paths |
| Video processing poll | `_classroomVideoPollTimer` (`4210`) | Post-upload / transcode polling | Bound timers + user feedback |

---

## 4. Files (canonical references)

### Mobile
- `mobile/lib/updated_screens.dart:13142+` — `_buildClassroomTab()`  
- `mobile/lib/updated_screens.dart:4210` — `_classroomVideoPollTimer`  
- `mobile/lib/updated_screens.dart:4274–4285` — `_classroomAnalyzing` / `_classroomLiveAnalyzing`  
- `mobile/lib/updated_screens.dart:4279` — `_classroomSelectedSessionId`  

### Backend WebSocket (`bridge_server.py`)
- `classroom_get_sessions` / `classroom_get_progress` / `classroom_get_analysis` — `6434–6676+`  
- `classroom_analyze_session` / `classroom_submit_reflection` / `classroom_check_recording` / `classroom_analyze_live` — `15325–15403`  

### Backend REST
- `backend/app/routers/sessions.py:1682+` — `POST /api/classroom/upload-video/*` (`_require_auth`)  
- `sessions.py` — **classroom_router** integration (per foundational Tab 5 file list)  

### Storage / DB
- `classroom_session_analyses` — analysis rows (WS table column in spec)  
- **`classroom_sessions.json`** — shared bridge/backend session index (see `fd4dc6c`: collapsed to one source)  

---

## 5. State Variables

| Variable | Type | Set true at | Set false at | Default |
|---|---|---|---|---|
| `_classroomAnalyzing` | bool | analyze batch path | success / error / timeout | false |
| `_classroomLiveAnalyzing` | bool | live analyze path | success / error / timeout | false |
| `_classroomSelectedSessionId` | String? | user picks session | clear / no rows | null |
| `_classroomVideoPollTimer` | `Timer?` | upload / processing poll | cancel on dispose / final state | null |

---

## 6. WebSocket Messages

| Direction | Type | Trigger | State change | Failure handling |
|---|---|---|---|---|
| → | `classroom_get_sessions` | Tab load / refresh | session list | Show empty vs error |
| → | `classroom_get_progress` | progress UI | progress model | same |
| → | `classroom_get_analysis` | open analysis | analysis body | same |
| → | `classroom_analyze_session` | analyze action | `_classroomAnalyzing` | **Clear flag on WS error** |
| → | `classroom_submit_reflection` | reflection form | local pending → sent | Retry + field preservation |
| → | `classroom_check_recording` | recording probe | status chips | same |
| → | `classroom_analyze_live` | live session | `_classroomLiveAnalyzing` | **Clear flag on WS error** |

**Critical pairings (must always co-occur):**
- Every `classroom_analyze_*` must **clear** `_classroomAnalyzing` / `_classroomLiveAnalyzing` on **error paths** (`e40900e`)  
- Poll timer must be **cancelled** in `dispose()` and on tab teardown — no orphaned timers  
- Upload REST success must eventually align **bridge** view of `classroom_sessions.json` / PG row (`3648b9d`, `fd4dc6c` classes)  

---

## 7. Database Schema

```sql
-- classroom_session_analyses — per foundational Tab 5 (WS handlers read/write)
-- coaching_sessions.session_data — PG path for unified session list (3b33482, 5c756ff)
-- classroom_sessions.json — coordinator file between bridge + backend (fd4dc6c)
```

**Approval gates:** reflections and analyses may be sensitive; respect tier/ACL as enforced server-side.  
**Soft delete:** follow classroom session + analysis retention policy in `sessions` / maintenance agents.

---

## 8. Known Bugs (Resolved)

| Date | Commit | Bug | Fix |
|---|---|---|---|
| — | `e40900e` | Coach Classroom **`_classroomAnalyzing` stuck on WebSocket error** | Reset analyzing flag on WS error path |
| — | `1d4af73` | **Upload-from-Device** `403` + **ArrayBuffer** crash on web | Auth + web compat fix |
| — | `999ee75` | **Video state lost** switching tabs + data dir permission failures | Persist state across tab switches; fix data dir perms |
| — | `3b33482` | Session list from **broken `load_sessions()`** | PG query on `coaching_sessions.session_data` |
| — | `fd4dc6c` | **Split** `classroom_sessions.json` truth between bridge/backend | Collapse to **one** shared file |

---

## 9. Anti-Patterns (Reject Without Investigation)

- ❌ **Leaving `_classroomAnalyzing` / `_classroomLiveAnalyzing` true after WebSocket errors** — `e40900e`.  
- ❌ **Web upload assuming full file in memory** (`ArrayBuffer`) without server/token alignment — `1d4af73`.  
- ❌ **Dual session-list sources** (stale JSON helper vs PG) — `3b33482`, `87ca9d2` class “unified list” work.  
- ❌ **Divergent `classroom_sessions.json` copies** for bridge vs backend — `fd4dc6c`.  
- ❌ **Unbounded `_classroomVideoPollTimer` loops** without user-visible stall detection.  

**Why this section exists:** classroom touches **large media**, **long jobs**, and **cross-process JSON** — the failure mode is always “it says analyzing forever” or “upload worked but list is empty.”

---

## 10. Daily Health Checks (run by `coach_portal_daily_check.sh`)

- [ ] Handler split still matches: **list/progress** `6434–6676+` vs **mutations** `15325–15403`  
- [ ] `sessions.py:1682+` upload route still mounted as `/api/classroom/upload-video/*`  
- [ ] `_classroomAnalyzing` reset grep passes (no new early `return` without flag clear)  
- [ ] `classroom_session_analyses` table exists in deployed migrations  
- [ ] `classroom_sessions.json` still **single** canonical path post-`fd4dc6c`  

---

## 11. Investigation Cache

1. Read THIS FILE FIRST  
2. Open **`13142+`** + bridge **`6434–6676+`** / **`15325–15403`** before proposing new `classroom_*` types  
3. Re-run §9 grep checks when touching analyzing flags or timers  
4. Update §8 when a classroom regression ships with commit hash  
5. If R2 multipart / presigned upload contract changes, update §4 REST notes in the same PR  

**Last full investigation:** 2026-05-04 (spec-only from `_FOUNDATIONAL_SPEC.md` Tab 5)  
**Cost-saved estimate:** TBD after first code-level pass  

---

## 12. Steve Jobs Review

Apply quarterly. The standard is "would Steve ship this."

- [ ] Does the first interaction feel inevitable? **— Debt:** session list + analyze + upload competes for first attention  
- [ ] Is anything on this screen unnecessary? **— Debt:** dual analyzing flags increase complexity  
- [ ] Could a non-technical user complete the primary action without instruction? **— Debt:** live vs recorded analyze must read as different verbs  
- [ ] Does the empty state teach the value of the tab? **— Debt:** “no sessions” should teach upload/scheduling entry points  
- [ ] Does the error state preserve trust? **— Debt:** long pipelines must not imply coach fault on infra 403/5xx  
- [ ] Is the most important thing the most prominent thing? **— Debt:** polling-based progress feels secondary to the actual video  

### Logged UX debt (target ship dates)

| Item | Issue | Target |
|------|--------|--------|
| SJ-1 | **Two analyzing booleans** (`_classroomAnalyzing` + `_classroomLiveAnalyzing`) — easy to desync in UI copy | 2026-06-15 |
| SJ-2 | **Timer-based video processing** (`_classroomVideoPollTimer`) — feels laggy vs push/progress channel | 2026-08-01 |
| SJ-3 | **Heavy pipeline surface in one tab** (upload, analyze, reflection, live) — needs progressive disclosure | 2026-07-01 |

---

## 13. Cloning This Template (For New Tabs)

See `docs/coach_portal/_PIPELINE_TEMPLATE.md` §13.

---

## 14. Adapter Comments For Cursor

```
Read docs/coach_portal/features/06_classroom.md before any investigation.
Source: docs/coach_portal/_FOUNDATIONAL_SPEC.md Tab 5 (CLASSROOM).
Analyzing flags MUST clear on WebSocket error (see e40900e).
Session list authority: PG + unified classroom_sessions.json — do not reintroduce duplicate JSON sources (fd4dc6c).
Upload: web compat + auth (1d4af73); REST at sessions.py:1682+.
```
