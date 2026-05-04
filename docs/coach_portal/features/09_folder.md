# Coach Portal — FOLDER (Tab 8)

> Status: ACTIVE  
> Last full review: 2026-05-04  
> Next review due: 2026-05-11 (weekly cadence)  
> Owner: Nathan  
> Steve Jobs UX score: needs work  

---

## 1. Purpose (1 sentence)

The FOLDER tab is the coach **file manager**: **pull-to-refresh** folders, **create** folders, **open** a folder to list files, and **upload** via multipart REST — backed by **`folder_api.py`** (`require_coach`) and tables **`coach_folders`** / **`coach_folder_files`** (migration **081**).

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
- [ ] **Pull refresh** (`17207`, `_coachFetchFolders()`, `GET /api/coach/folders` `17609`) clears **`_coachFoldersLoading`** (`17203`) on **all** outcomes  
- [ ] **New Folder** (`17235–17238`, `POST .../create` `17677–17678`) confirms creation and inserts the new card without requiring an app restart  
- [ ] **Folder card tap** (`17307–17314`, `GET .../folders/{id}/files` `17629–17634`) shows **empty folder** vs **load error** differently  
- [ ] **Upload** (`17363–17380`, `_coachPickAndUploadFile` `17507+`, `POST .../upload`) sends **`Authorization: Bearer`** on **every** platform, including **Flutter Web** (`5c756ff` class)  
- [ ] Upload shows **progress** or **indeterminate busy** for large files; completion refreshes file list or appends row  
- [ ] Active folder id (`_coachActiveFolderId`, `17201`) stays in sync with the folder whose file list is visible  
- [ ] Storage fields returned by API (`azure_blob_url` / `storage_url` / R2 key patterns) remain **consistent** with DB columns after migrations (`b1f973d` / migration **196** class)  

---

## 3. UI Components

| Component | Location | Purpose | Notes |
|---|---|---|---|
| Folder tab scaffold | `mobile/lib/updated_screens.dart:17205–17687` (`_buildFolderTab`) | File manager shell | Tab 8 |
| Pull refresh | `mobile/lib/updated_screens.dart:17207` | `_coachFetchFolders()` | REST list |
| New Folder | `mobile/lib/updated_screens.dart:17235–17238` | `_coachCreateFolder` | POST create |
| Folder card | `mobile/lib/updated_screens.dart:17307–17314` | `_coachFetchFolderFiles` | Opens file list |
| Upload | `mobile/lib/updated_screens.dart:17363–17380` | pick → `_coachPickAndUploadFile` `17507+` | Multipart POST |

---

## 4. Files (canonical references)

### Mobile
- `mobile/lib/updated_screens.dart:17205–17687` — `_buildFolderTab()`  
- `mobile/lib/updated_screens.dart:17207` — refresh folders  
- `mobile/lib/updated_screens.dart:17235–17238` — create folder  
- `mobile/lib/updated_screens.dart:17307–17314` — open folder → files  
- `mobile/lib/updated_screens.dart:17363–17380` / `17507+` — upload pipeline  
- `mobile/lib/updated_screens.dart:17201` — `_coachActiveFolderId`  
- `mobile/lib/updated_screens.dart:17203` — `_coachFoldersLoading`  

### Backend REST
- `backend/app/routers/folder_api.py:24–28` — `GET /api/coach/folders`  
- `folder_api.py` — `POST /api/coach/folders/create` (referenced `17677–17678` in Flutter)  
- `folder_api.py` — `GET /api/coach/folders/{id}/files`  
- `folder_api.py` — `POST /api/coach/folders/{id}/upload` (multipart)  
- **Auth:** `require_coach` on all routes above (per foundational spec)  

### Storage / DB
- `coach_folders` — `081:13–21`  
- `coach_folder_files` — `081:26–36`  
- **Object storage:** unified blob chain (R2 → Azure → local) per platform architecture — keys/paths surfaced in `coach_folder_files` columns (see `b1f973d` alignment)  

---

## 5. State Variables

| Variable | Type | Set true at | Set false at | Default |
|---|---|---|---|---|
| `_coachActiveFolderId` | String? | folder card tap `17307–17314` | back / deselect | null |
| `_coachFoldersLoading` | bool | `_coachFetchFolders()` | response handled | false |

*Upload-in-progress flags (if any) should live next to `17507+` pick/upload helpers — confirm in code when extending §5.*  

---

## 6. WebSocket Messages

*N/A for Tab 8 in foundational spec — this tab is **REST-only**. If hybrid messaging is added later, replace this section and bump “Last full review.”*

**Critical pairings (REST equivalent):**
- Every **GET** must pair **loading flag** + **error UI** (`_coachFoldersLoading`)  
- **Upload POST** must pair **list refresh** or **optimistic insert** + **rollback** on failure  

---

## 7. Database Schema

```sql
-- coach_folders — 081:13–21
-- coach_folder_files — 081:26–36
-- Migration 196 — align coach_folder_files storage URL columns (b1f973d)
```

**Approval gates:** none listed in Tab 8 slice; follow coach data retention policy for client-linked files.  
**Soft delete:** follow `folder_api` + table conventions; avoid orphaning blob keys.  

---

## 8. Known Bugs (Resolved)

| Date | Commit | Bug | Fix |
|---|---|---|---|
| — | `5c756ff` | **Folder upload** missing / wrong **auth token** on web; related upload compat | Token + web upload compat fixes |
| — | `b1f973d` | **`coach_folder_files`** columns **`azure_blob_url` / `storage_url`** drift vs `folder_api` writes | Migration **196** + `folder_api` alignment |

---

## 9. Anti-Patterns (Reject Without Investigation)

- ❌ **Upload or folder REST calls without `Authorization: Bearer`** — `5c756ff`.  
- ❌ **Inserting folder file rows** without matching **storage URL / R2 key** columns after schema changes — `b1f973d`.  
- ❌ **Conflating Briefings folder selection (`_selectedFolderId`) with File Manager (`_coachActiveFolderId`)** — foundational cross-tab dependency table.  
- ❌ **Multipart upload without size/duration feedback** on slow cellular — users assume failure and double-submit.  

**Why this section exists:** coach files often hold **clinical artifacts**; silent upload failure is a compliance story, not just UX.

---

## 10. Daily Health Checks (run by `coach_portal_daily_check.sh`)

- [ ] `folder_api.py` still exports all four coach routes in §4  
- [ ] `_buildFolderTab` range `17205–17687` still valid  
- [ ] Grep: no `http.post` to `/api/coach/folders` without auth headers (Flutter)  
- [ ] Migration **196** + `081` tables still in repo baseline  
- [ ] Blob facade still resolves uploads written by `folder_api`  

---

## 11. Investigation Cache

1. Read THIS FILE FIRST  
2. Open **`updated_screens.dart:17205+`** + **`folder_api.py`** together for any folder feature  
3. Verify **storage column** names against `coach_folder_files` after migrations (§7)  
4. Update §8 when an upload/auth regression is fixed with commit hash  
5. If adding WebSocket cache sync for folders, reintroduce §6 with pairings  

**Last full investigation:** 2026-05-04 (spec-only from `_FOUNDATIONAL_SPEC.md` Tab 8)  
**Cost-saved estimate:** TBD after first code-level pass  

---

## 12. Steve Jobs Review

Apply quarterly. The standard is "would Steve ship this."

- [ ] Does the first interaction feel inevitable? **— Debt:** “files live here” competes with **Briefings** folder mental model  
- [ ] Is anything on this screen unnecessary? **— Debt:** two folder concepts in one app without wayfinding  
- [ ] Could a non-technical user complete the primary action without instruction? **— Debt:** upload vs create folder must be unambiguous  
- [ ] Does the empty state teach the value of the tab? **— Debt:** empty root should teach “create first folder”  
- [ ] Does the error state preserve trust? **— Debt:** 403 must read as auth/config, not “your files were deleted”  
- [ ] Is the most important thing the most prominent thing? **— Debt:** upload often matters most; may be buried  

### Logged UX debt (target ship dates)

| Item | Issue | Target |
|------|--------|--------|
| SJ-1 | **Dual folder mental models** — Briefings `_selectedFolderId` vs FOLDER `_coachActiveFolderId` | 2026-07-01 |
| SJ-2 | **REST-only tab** in a **WebSocket-first** dashboard — refresh/sync story differs from other tabs | 2026-06-15 |
| SJ-3 | **Large file multipart** uploads without **resumable** or **clear ceiling** copy | 2026-08-01 |

---

## 13. Cloning This Template (For New Tabs)

See `docs/coach_portal/_PIPELINE_TEMPLATE.md` §13.

---

## 14. Adapter Comments For Cursor

```
Read docs/coach_portal/features/09_folder.md before any investigation.
Source: docs/coach_portal/_FOUNDATIONAL_SPEC.md Tab 8 (FOLDER).
REST only: folder_api.py (require_coach). Flutter anchors 17205–17687.
Upload must send bearer token on web (5c756ff). Keep coach_folder_files columns aligned with API (196/b1f973d).
Do not merge _selectedFolderId (Briefings) with _coachActiveFolderId without a product decision.
```
