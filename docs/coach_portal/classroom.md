# Coach Portal — Classroom

> Status: ACTIVE
> Last full review: 2026-05-04
> Next review due: 2026-05-11
> Owner: Nathan
> Steve Jobs UX score: needs work (see section 12)

---

## 1. Purpose

The Classroom tab lets a coach analyze a recorded therapy session — uploading a video, running AI analysis, and reviewing structured feedback before sharing notes with the family.

---

## 2. UX Acceptance Criteria

- [ ] Loads in under 2 seconds on cellular
- [ ] Upload progress visible at all times during analysis
- [ ] Analysis can be canceled by the coach without orphaning the session
- [ ] Failed analyses show what failed and how to retry, not just "error"
- [ ] If WebSocket disconnects mid-analysis, UI state recovers within 5 seconds (FIX e40900e)
- [ ] Long analyses (30+ min) show estimated remaining time
- [ ] Completed analysis is one tap away from share-with-family

---

## 3. UI Components

| Component | Location | Purpose | Notes |
|---|---|---|---|
| Session list | mobile/lib/updated_screens.dart (CoachDashboardScreenV2) | Browse past + active classroom sessions | |
| Analyze button | calls `_analyzeSelectedSession` line 15301 | Triggers backend AI analysis | sets `_classroomAnalyzing=true` |
| Live analysis button | calls `_analyzeLiveSession` line 15354 | For in-progress sessions | sets `_classroomLiveAnalyzing=true` |
| Progress polling | `_startClassroomVideoAnalysisPoll` line 15230 | UI heartbeat during analysis | 30-min ceiling at line 15254 |
| Error snackbar | shown via `_handleSocketMessage` error branch | Displays backend errors | Now resets analyzing flags after fix e40900e |

---

## 4. Files

### Mobile
- `mobile/lib/updated_screens.dart` — `CoachDashboardScreenV2` (the entire ~28k-line dashboard file is currently monolithic; classroom-specific code is intermixed)
  - `_handleSocketMessage`: lines 6001–6845
  - WebSocket connection handlers: `_connectToBridge` lines 4383–4391
  - `_analyzeSelectedSession`: line 15301
  - `_analyzeLiveSession`: line 15354
  - `_startClassroomVideoAnalysisPoll`: line 15230

### Backend handler
- `backend/app/websocket/bridge_server.py` — classroom message types
  - `classroom_analyze_session` handler
  - `classroom_analyze_live` handler
  - `classroom_analysis_complete` emitter
  - `classroom_live_analysis` emitter

### Backend service
- `backend/app/services/classroom_*.py` — classroom analysis service (verify path during next investigation)
- `backend/app/services/lived_wisdom.py` lines 66–77 — extracts wisdom from completed sessions (wired in commit 44fb707)

### Storage
- Tables: `classroom_sessions`, `wisdom_extractions`
- Read paths: `LivedWisdomService.get_client_wisdom`, `get_family_wisdom` (filter `approved=TRUE`)
- Write paths: `LivedWisdomService._store_wisdom` (defaults `approved=FALSE`)

---

## 5. State Variables

| Variable | Type | Set true at | Set false at | Default |
|---|---|---|---|---|
| `_classroomAnalyzing` | bool | 6470 (`classroom_analysis_started`), 6579 (with pipeline_stage), 15230 (poll start), 15301 (analyze trigger) | 6496 (complete success), 6525 (complete error), 6553 (analysis with `_isClassroomSessionAnalysisComplete`), 15254 (poll timeout 30min), **6806–6839 error handler (FIX e40900e)**, **4383–4391 onError/onDone (FIX e40900e)** | false |
| `_classroomLiveAnalyzing` | bool | 15354 (live analyze trigger) | 6627 (live analysis handler — both success/fail paths), **6806–6839 error handler (FIX e40900e)**, **4383–4391 onError/onDone (FIX e40900e)** | false |

**Critical invariant:** every state-set must have a guaranteed reset path. Bug e40900e was caused by missing resets in error handlers.

---

## 6. WebSocket Messages

| Direction | Type | Trigger | State change | Failure handling |
|---|---|---|---|---|
| → | `classroom_analyze_session` | Coach taps Analyze | `_classroomAnalyzing=true` | Reset on `error` type, onError, onDone, or 30-min poll timeout |
| → | `classroom_analyze_live` | Coach taps Live Analyze | `_classroomLiveAnalyzing=true` | Reset on `classroom_live_analysis` (any result) or onError/onDone |
| ← | `classroom_analysis_started` | Backend acks | UI shows starting | — |
| ← | `classroom_analysis` | Progress update | UI shows pipeline_stage | — |
| ← | `classroom_analysis_complete` | Backend done | `_classroomAnalyzing=false`, show results | hasErr branch also resets flag |
| ← | `classroom_live_analysis` | Live result | `_classroomLiveAnalyzing=false` | Same handler covers success and failure |
| ← | `error` (generic) | Any backend error | **Now resets BOTH flags (FIX e40900e)** | Snackbar message + flag reset |
| onError/onDone | (transport) | Connection lost | **Now resets BOTH flags (FIX e40900e)** | `_scheduleWsReconnect()` |

---

## 7. Database Schema

```sql
-- classroom_sessions (existing — verify schema during next session)
-- columns of interest: id, family_id, status, video_url, analysis_result, created_at

-- wisdom_extractions (migration 015)
CREATE TABLE wisdom_extractions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID,
    family_id UUID,
    member_id UUID,
    source TEXT,           -- 'session', 'sanctuary'
    text TEXT,
    approved BOOLEAN DEFAULT FALSE,  -- gate for read paths
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Approval gate:** `_store_wisdom` does NOT set `approved`. Default is FALSE. Coach review UI required to flip to TRUE before wisdom appears in `get_*_wisdom` results.

---

## 8. Known Bugs (Resolved)

| Date | Commit | Bug | Fix |
|---|---|---|---|
| 2026-05-04 | e40900e | Analyzing flag stuck on WebSocket error / disconnect | Added `_classroomAnalyzing=false` and `_classroomLiveAnalyzing=false` to error handler (lines 6806–6839) and onError/onDone (lines 4383–4391) |
| 2026-05-04 | 44fb707 | Lived wisdom extraction not wired to sanctuary_complete | Added `LivedWisdomService.extract_sanctuary_wisdom` call in `bridge_server.py:27169` with try/except guard |

---

## 9. Anti-Patterns (Reject Without Investigation)

- ❌ Setting `_classroomAnalyzing` true without verifying ALL reset paths exist (success, error, transport failure, timeout)
- ❌ Adding new error branches in `_handleSocketMessage` without resetting analyzing flags
- ❌ Setting `wisdom_extractions.approved=TRUE` automatically during extraction (must wait for coach review)
- ❌ Using "wisdom" data in surfaces without filtering on `approved=TRUE`
- ❌ Modifying `bridge_server.py` lines without `# QUANTUM-CRYSTAL-ARCH` or `# SOVEREIGN-VOICE` marker (protected file convention)
- ❌ Single commit larger than 50 lines on `bridge_server.py` (protected file rule)
- ❌ Calling `extract_sanctuary_wisdom` synchronously without try/except (extraction failure must not block sanctuary_complete response)
- ❌ Translating message field as `m["text"]` directly when bridge uses `m["content"]` (use `m.get("content", m.get("text", ""))`)

---

## 10. Daily Health Checks

- [ ] `mobile/lib/updated_screens.dart` exists and contains line 6806 in error handler
- [ ] `grep -n "_classroomAnalyzing = false" mobile/lib/updated_screens.dart | wc -l` returns at least 6 (success, complete, error, timeout, transport-error, transport-done)
- [ ] `grep -n "SANCTUARY-WISDOM-WIRE" backend/app/websocket/bridge_server.py` returns line 27169
- [ ] `grep "approved=TRUE\|approved = TRUE" backend/app/services/lived_wisdom.py` returns 0 results in `_store_wisdom` function
- [ ] Production health: `STARTUP COMPLETE: 114/114 services healthy`
- [ ] No new TODO markers in classroom-related files since last review

---

## 11. Investigation Cache

**Last full investigation:** 2026-05-04 (Coach Classroom WebSocket bug + Lived Wisdom wire-up)
**Investigation duration:** ~3 hours
**Sessions involved:** 1 ChatGPT/Claude session
**Cost-saved estimate (next session):** ~50-100k tokens by reading this doc instead of grep/cat across 28k-line file

**Current open questions:**
- Verify exact path of `classroom_*.py` analysis service (not located during last session)
- Verify `classroom_sessions` table schema
- Build coach review UI for `wisdom_extractions.approved` flip

---

## 12. Steve Jobs Review

Last reviewed: 2026-05-04

- [ ] Does the first interaction feel inevitable? **NO** — coaches must understand "Live" vs "Recorded" analysis distinction with no UX explanation
- [ ] Is anything on this screen unnecessary? **TBD** — full UX audit pending
- [ ] Could a non-technical user complete the primary action without instruction? **TBD**
- [x] Does the empty state teach the value of the tab? **Likely no**
- [ ] Does the error state preserve trust? **NOW YES** (post-e40900e — error no longer leaves UI stuck, which destroyed trust)
- [ ] Is the most important thing the most prominent thing? **TBD**

**UX debt log:**
- 2026-05-04: Live vs Recorded distinction unclear — needs visual hierarchy review
- 2026-05-04: 30-min poll ceiling silently times out — should show estimated remaining time

---

## 13. Cloning This Template

This file IS the template-fill for Classroom. To create a new tab spec:

```bash
cp docs/coach_portal/_PIPELINE_TEMPLATE.md docs/coach_portal/<new_tab>.md
```

Don't copy classroom.md — it's filled in. Use the blank template.

---

## 14. Adapter Comments For Cursor

When invoking Cursor on this tab, prefix the prompt with:

```
Read docs/coach_portal/classroom.md before any investigation.
The file contains:
- Exact line numbers for updated_screens.dart and bridge_server.py
- 8 anti-patterns to reject without analysis
- 2 resolved bugs with their fix commits

Skip discovery. Use the doc as ground truth. If the doc is stale,
update it as part of your fix and report the divergence in section 8.
```
