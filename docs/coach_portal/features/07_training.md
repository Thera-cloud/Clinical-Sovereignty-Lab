# Coach Portal — TRAINING (Tab 6)

> Status: ACTIVE  
> Last full review: 2026-05-04  
> Next review due: 2026-05-11 (weekly cadence)  
> Owner: Nathan  
> Steve Jobs UX score: needs work  

---

## 1. Purpose (1 sentence)

The TRAINING tab is a **launcher** for **Coaching Mesh** (start/join as master or participant) and **Community Circle** (`CommunityMeshScreen`), plus a **recent sessions** strip whose backing REST is still **TBD** in the foundational spec — all heavy mesh I/O happens on **separate screens** over WebSocket messages handled at **`bridge_server.py:29125+`**.

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
- [ ] **Start Training Session** (`15786–15795`, `CoachingMeshScreen(isMaster: true)`) is visually distinct from **Join** (`15800–15809`, `CoachingMeshScreen(isMaster: false)`) — no accidental wrong role  
- [ ] **Community Circle** (`15819–15828` → `CommunityMeshScreen`) is labeled so coaches don’t conflate it with mesh training  
- [ ] Returning from a pushed mesh screen restores the Training tab **without** zombie navigators or duplicate `CoachingMeshScreen` instances  
- [ ] **Recent sessions** (`15838+`, `_fetchRecentTrainingSessions()`) shows explicit **empty**, **error**, or **loading** — not a silent blank while REST remains **TBD**  
- [ ] Mesh WebSocket failures on child screens surface **recoverable** copy (retry, return to dashboard), not infinite spinners  
- [ ] Coaches with **hierarchy** data (master/assistant) are not shown **incomplete** roster/metrics lists due to API filter gaps (`e16d143` class)  
- [ ] Session identity inputs sent toward hierarchy/mesh APIs accept **UUID, hardware_id, or username** consistently server-side (`327ad92` class) — client must not guess wrong shape  

---

## 3. UI Components

| Component | Location | Purpose | Notes |
|---|---|---|---|
| Training tab scaffold | `mobile/lib/updated_screens.dart:15774–15872` (`_buildTrainingTab`) | Launcher UI | Tab 6 |
| Start Training (master) | `mobile/lib/updated_screens.dart:15786–15795` | `CoachingMeshScreen(isMaster: true)` | Separate route |
| Join Training | `mobile/lib/updated_screens.dart:15800–15809` | `CoachingMeshScreen(isMaster: false)` | Separate route |
| Community Circle | `mobile/lib/updated_screens.dart:15819–15828` | `CommunityMeshScreen` | BLE/mesh community UX (product) |
| Recent sessions | `mobile/lib/updated_screens.dart:15838+` | `_fetchRecentTrainingSessions()` | REST **TBD** per spec |

---

## 4. Files (canonical references)

### Mobile
- `mobile/lib/updated_screens.dart:15774–15872` — `_buildTrainingTab()`  
- `mobile/lib/updated_screens.dart:15786–15795` — start mesh (master)  
- `mobile/lib/updated_screens.dart:15800–15809` — join mesh  
- `mobile/lib/updated_screens.dart:15819–15828` — community circle entry  
- `mobile/lib/updated_screens.dart:15838+` — recent sessions fetch  

### Backend WebSocket (`bridge_server.py`)
- `coaching_mesh_create` / `join` / `leave` / `end` / `message` / `quiz` / `scores` — **`29125+`** (dispatch into `CoachingMeshEngine` per foundational spec)  

### Backend services / REST
- `backend/app/services/coaching_mesh_engine.py` — `CoachingMeshEngine` (`create_session`, `join_session`, `leave_session`, `end_session`, `post_message`, `push_quiz`, `get_session_scores`)  
- `backend/app/routers/coach_hierarchy_api.py` — assistant/master REST used by broader coach portal (Tab 6 adjacent)  

### Storage / DB (mesh)
- `coaching_mesh_sessions` — migration `068:46–59`  
- `coaching_mesh_participants` — `068:68–77`  
- `coaching_mesh_messages` — `068:84–94`  

---

## 5. State Variables

| Variable | Type | Set true at | Set false at | Default |
|---|---|---|---|---|
| *(recent list)* | `List` / async | `_fetchRecentTrainingSessions()` `15838+` | response / error | `[]` or loading sentinel |
| *(child screens)* | — | `CoachingMeshScreen` / `CommunityMeshScreen` | `Navigator.pop` | — |

*Foundational spec does not pin tab-local booleans for Tab 6; mesh session state primarily lives on the **pushed** routes and server rows.*

---

## 6. WebSocket Messages

| Direction | Type | Trigger | State change | Failure handling |
|---|---|---|---|---|
| → | `coaching_mesh_create` | Master starts — child screen | new `session_id` | surface error to user |
| → | `coaching_mesh_join` | Participant joins | participant row | same |
| → | `coaching_mesh_leave` | Leave | `left_at` set server-side | same |
| → | `coaching_mesh_end` | End session | session closed | same |
| → | `coaching_mesh_message` | Chat / flow | message append | same |
| → | `coaching_mesh_quiz` | Quiz push | quiz state | same |
| → | `coaching_mesh_scores` | Scores fetch | scoreboard | same |

**Critical pairings (must always co-occur):**
- Every **join** must have a matching **leave** or **end** path on disconnect (client + server)  
- **Quiz/score** pushes must tolerate **late joiners** without corrupting session state (engine responsibility)  
- **Recent list** fetches must not assume REST exists while spec marks **TBD**  

---

## 7. Database Schema

```sql
-- coaching_mesh_sessions — 068:46–59
-- coaching_mesh_participants — 068:68–77
-- coaching_mesh_messages — 068:84–94
```

**Approval gates:** mesh quizzes/scores may be auditable; follow engine + migration 068 constraints.  
**Soft delete:** `left_at` on participants — follow `CoachingMeshEngine` semantics.  

---

## 8. Known Bugs (Resolved)

| Date | Commit | Bug | Fix |
|---|---|---|---|
| — | `327ad92` | `coach_hierarchy_api` unsafe `session_data` casts + identity resolver too narrow | SQL-safe casts; resolver accepts uuid / hardware_id / username |
| — | `e16d143` | Assistant-metrics REST lists **omitted `pending_admin`** | Include `pending_admin` in assistant-metrics aggregation |
| — | `f2c9b49` | NateCheckIn agent **DOJO / mesh score** context drift vs `dojo_mentor` schema | Aligned agent context with mesh + schema |

---

## 9. Anti-Patterns (Reject Without Investigation)

- ❌ **Narrow identity types** (username-only) on hierarchy/mesh-adjacent APIs when participants arrive as **UUID or hardware id** — `327ad92`.  
- ❌ **Incomplete assistant/admin visibility** in metrics lists — `e16d143`.  
- ❌ **Downstream agents assuming mesh/DOJO fields** without schema lockstep — `f2c9b49`.  
- ❌ **Shipping “recent training sessions” UI** with **no stable REST contract** while marking fetch **TBD** in spec — guaranteed blank/flicker regressions.  

**Why this section exists:** Tab 6 is a **router** into high-velocity group sessions; small API drift strands participants or masters.

---

## 10. Daily Health Checks (run by `coach_portal_daily_check.sh`)

- [ ] `_buildTrainingTab` line range `15774–15872` still valid  
- [ ] Bridge dispatch **`29125+`** still references all seven `coaching_mesh_*` types  
- [ ] `coaching_mesh_engine.py` imports / engine methods still match §6 service names  
- [ ] Migration **068** tables still present in repo  
- [ ] `_fetchRecentTrainingSessions()` either implemented with real REST or clearly feature-flagged off  

---

## 11. Investigation Cache

1. Read THIS FILE FIRST  
2. When editing mesh protocol, open **`bridge_server.py:29125+`** + `coaching_mesh_engine.py` in same change  
3. Reject §9 patterns before expanding hierarchy REST surface  
4. If **recent sessions** REST lands, replace **TBD** in foundational spec + update §2/§5 here  
5. Update §8 when mesh/hierarchy regressions ship with commit hash  

**Last full investigation:** 2026-05-04 (spec-only from `_FOUNDATIONAL_SPEC.md` Tab 6)  
**Cost-saved estimate:** TBD after first code-level pass  

---

## 12. Steve Jobs Review

Apply quarterly. The standard is "would Steve ship this."

- [ ] Does the first interaction feel inevitable? **— Debt:** tab is three doors; no single “start here” story  
- [ ] Is anything on this screen unnecessary? **— Debt:** recent list without API is ornament, not utility  
- [ ] Could a non-technical user complete the primary action without instruction? **— Debt:** master vs join vs community needs one sentence each, always visible  
- [ ] Does the empty state teach the value of the tab? **— Debt:** TBD REST makes empty likely — must teach “create session”  
- [ ] Does the error state preserve trust? **— Debt:** mesh failures must not feel like coach credential failure  
- [ ] Is the most important thing the most prominent thing? **— Debt:** master start vs join — pick a default persona bias  

### Logged UX debt (target ship dates)

| Item | Issue | Target |
|------|--------|--------|
| SJ-1 | **Recent sessions** backed by **REST TBD** — list is non-authoritative | 2026-06-01 |
| SJ-2 | **Real session UX lives off-tab** (two mesh screens) — Training tab feels like a lobby, not the experience | 2026-08-01 |
| SJ-3 | **Three entry points** (master, join, community) without guided **first-run** copy | 2026-05-25 |

---

## 13. Cloning This Template (For New Tabs)

See `docs/coach_portal/_PIPELINE_TEMPLATE.md` §13.

---

## 14. Adapter Comments For Cursor

```
Read docs/coach_portal/features/07_training.md before any investigation.
Source: docs/coach_portal/_FOUNDATIONAL_SPEC.md Tab 6 (TRAINING).
Mesh WS: bridge_server.py:29125+ → CoachingMeshEngine in coaching_mesh_engine.py.
Recent sessions: _fetchRecentTrainingSessions is REST TBD — do not fake data.
Honor identity flexibility (327ad92) on any hierarchy-adjacent change.
```
