# Coach Portal — DOJO (Tab 4)

> Status: ACTIVE  
> Last full review: 2026-05-04  
> Next review due: 2026-05-11 (weekly cadence)  
> Owner: Nathan  
> Steve Jobs UX score: needs work  

---

## 1. Purpose (1 sentence)

The DOJO tab **embeds** Night School as `night_school_dojo.html` inside a **WebView/iframe**, passing `token`, `hw`, and `ws` query params — all live product interaction is **HTML**, while **native Flutter DOJO UI is dead code** (`_buildDojoTabNative`).

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
- [ ] WebView/iframe **successfully resolves** `night_school_dojo.html` and shows a non-blank surface (or explicit “can’t load DOJO” with retry)  
- [ ] Bootstrap query string includes **`token`**, **`hw`**, **`ws`** (`12553–12576`) — if any are missing, block with a coach-actionable message (not an infinite spinner)  
- [ ] Session handoff to the embedded app preserves **coach role** expectations (no client-only surfaces inside the shell)  
- [ ] Zoom/back gesture / in-app navigation inside WebView does not strand the user without a Flutter-visible **back to dashboard** path  
- [ ] Failures from `/api/dojo/*` (`dojo_api.py:17–19`) surface in the embedded UI or an overlay — never silent 403/500  
- [ ] Legacy bridge messages (`dojo_start` / `dojo_end` / `dojo_test_message` / `dojo_share_learning`, `4459–4532`) are **not** marketed as the primary DOJO UX path; HTML shell is canonical  
- [ ] No feature work lands in **`_buildDojoTabNative()`** (`12645+`) until that code path is deleted or reactivated deliberately  

---

## 3. UI Components

| Component | Location | Purpose | Notes |
|---|---|---|---|
| DOJO tab scaffold | `mobile/lib/updated_screens.dart:12546–12624` (`_buildDojoTab`) | Hosts embedded Night School | Production path |
| Embedded WebView / iframe | `mobile/lib/updated_screens.dart:12553–12576` | Loads `night_school_dojo.html` | Query: `token`, `hw`, `ws` |
| Native DOJO (dead) | `mobile/lib/updated_screens.dart:12645+` (`_buildDojoTabNative`) | Legacy Flutter DOJO | **Never called** — remove or revive intentionally |

---

## 4. Files (canonical references)

### Mobile
- `mobile/lib/updated_screens.dart:12546–12624` — `_buildDojoTab()`  
- `mobile/lib/updated_screens.dart:12553–12576` — iframe/WebView URL build (`night_school_dojo.html` + params)  
- `mobile/lib/updated_screens.dart:12645+` — `_buildDojoTabNative()` (dead)  

### Backend REST
- `backend/app/routers/dojo_api.py:17–19` — `/api/dojo/*` (`require_coach`)  

### Backend services
- `backend/app/services/night_school_director.py` — Night School / DOJO server orchestration (per foundational Tab 4 file list)  

### Dashboard static
- `night_school_dojo.html` — embedded shell target (not line-anchored in foundational spec)  

### WebSocket (`bridge_server.py`) — **legacy native paths (still present)**
- `dojo_start`, `dojo_end`, `dojo_test_message`, `dojo_share_learning` — routed via `4459–4532` region (per Tab 4 spec)  

---

## 5. State Variables

| Variable | Type | Set true at | Set false at | Default |
|---|---|---|---|---|
| *(WebView/iframe)* | — | platform WebView controller | error / dispose | — |
| `_dojoBusy` | bool | `4301` (dashboard-wide) | DOJO-related actions complete | false |
| `_dojoSubsLoading` | bool | `4260` | subscription fetch done | false |

*Tab 4 is predominantly **HTML state** inside the embed. `_dojoBusy` / `_dojoSubsLoading` are shared dashboard fields (see `_FOUNDATIONAL_SPEC.md` loading table) and may interact with **DOJO subscription** flows in **FINANCIALS**; confirm coupling when changing either tab.*

---

## 6. WebSocket Messages

| Direction | Type | Trigger | State change | Failure handling |
|---|---|---|---|---|
| → / ← | `dojo_start` | Legacy native / tests | simulation lifecycle | **Not** primary Tab 4 UX — HTML is canonical |
| → / ← | `dojo_end` | Legacy native | end session | same |
| → / ← | `dojo_test_message` | Legacy native / adversarial scoring | scoring updates | `e6716d6` class: must match real protocol |
| → / ← | `dojo_share_learning` | Legacy native | share path | same |

**Critical pairings (must always co-occur):**
- HTML embed **must** receive valid **`ws`** URL + auth **`token`** + **`hw`** — partial params = broken trust  
- Any change to legacy `dojo_*` handlers (`4459–4532`) must keep **embed + server** contract in sync  
- Do not add native-only DOJO UI without removing dead `_buildDojoTabNative` or switching the tab builder to call it  

---

## 7. Database Schema

```sql
-- Tab 4 spec delegates persistence to Night School / DOJO backends.
-- Authoritative REST: /api/dojo/* (dojo_api.py).
-- Legacy bridge dojo_* paths: see bridge_server.py:4459–4532 region.
-- Related product data also flows through night_school_director.py and PG migrations
-- referenced elsewhere (e.g. Night School wisdom — not re-derived here).
```

**Approval gates:** follow DOJO / Night School business rules in `dojo_api` and director service.  
**Soft delete:** follow Night School content rules; not expanded in Tab 4 spec slice.

---

## 8. Known Bugs (Resolved)

| Date | Commit | Bug | Fix |
|---|---|---|---|
| — | `771bae9` | Bridge crash on **Night School init** | Defensive Night School initialization in bridge |
| — | `e6716d6` | DOJO **simulation** not wired to real **`dojo_start` / `dojo_test_message` / `dojo_end`** + adversarial scoring | Wired simulation to real protocol |
| — | `f2c9b49` | **NateCheckInAgent** DOJO context drift vs **mesh score + `dojo_mentor` schema** | Aligned agent context with schema |

---

## 9. Anti-Patterns (Reject Without Investigation)

- ❌ **Bridge / `night_school_director` startup without defensive init** — class fixed `771bae9`; crashes take down **all** coach WS traffic.  
- ❌ **DOJO “simulation” or mentor path that doesn’t speak the real `dojo_*` protocol** — class fixed `e6716d6`.  
- ❌ **Downstream agents (check-in, scoring) assuming DOJO schema fields that don’t match `dojo_mentor` / mesh** — class fixed `f2c9b49`.  
- ❌ **Shipping new UX in `_buildDojoTabNative()` (`12645+`) while Tab 4 still calls only the WebView builder** — doubles maintenance and lies to QA (“which surface is live?”).  

**Why this section exists:** DOJO is split across **embed**, **REST**, and **legacy WS** — the failure mode is always “it looks fine in Flutter but nothing happens in HTML.”

---

## 10. Daily Health Checks (run by `coach_portal_daily_check.sh`)

- [ ] `_buildDojoTab()` still embeds `night_school_dojo.html` at `12553–12576`  
- [ ] `dojo_api.py` router still mounted with `require_coach`  
- [ ] `_buildDojoTabNative` still **uncalled** OR merge plan executed (remove or wire)  
- [ ] Bridge `dojo_*` region `4459–4532` still exists if legacy clients depend on it  
- [ ] No query-logging of full `token=` bootstrap URLs in production logs  

---

## 11. Investigation Cache

1. Read THIS FILE FIRST  
2. Treat **HTML** as product; Flutter as thin shell unless `12645+` revival is explicitly approved  
3. Reject §9 patterns before touching bridge `dojo_*` or Night School init  
4. Cross-check **FINANCIALS** DOJO subscription tiles if `_dojoSubsLoading` / `_dojoBusy` regress  
5. Update §8 when a DOJO embed or protocol regression is fixed with commit hash  

**Last full investigation:** 2026-05-04 (spec-only from `_FOUNDATIONAL_SPEC.md` Tab 4)  
**Cost-saved estimate:** TBD after first code-level pass  

---

## 12. Steve Jobs Review

Apply quarterly. The standard is "would Steve ship this."

- [ ] Does the first interaction feel inevitable? **— Debt:** hybrid stack (Flutter chrome + HTML app) breaks single-app feel  
- [ ] Is anything on this screen unnecessary? **— Debt:** dead `_buildDojoTabNative` is pure payload  
- [ ] Could a non-technical user complete the primary action without instruction? **— Debt:** WebView failures look like “broken app,” not “reload DOJO”  
- [ ] Does the empty state teach the value of the tab? **— Debt:** blank iframe teaches nothing  
- [ ] Does the error state preserve trust? **— Debt:** token/ws bootstrap errors must not imply account compromise  
- [ ] Is the most important thing the most prominent thing? **— Debt:** embedded HTML owns UX; Flutter adds no obvious hero affordance  

### Logged UX debt (target ship dates)

| Item | Issue | Target |
|------|--------|--------|
| SJ-1 | **Dead native DOJO** (`_buildDojoTabNative` `12645+`) — confuses engineers and inflates binary | 2026-06-01 |
| SJ-2 | **100% WebView product surface** — inconsistent accessibility, gestures, and offline story vs native tabs | 2026-09-01 |
| SJ-3 | **Dual stack** (live HTML + legacy `dojo_*` WS `4459–4532`) — only one should be “the story” in docs and support | 2026-07-15 |

---

## 13. Cloning This Template (For New Tabs)

See `docs/coach_portal/_PIPELINE_TEMPLATE.md` §13.

---

## 14. Adapter Comments For Cursor

```
Read docs/coach_portal/features/05_dojo.md before any investigation.
Canonical DOJO UX: WebView night_school_dojo.html (token, hw, ws) at updated_screens.dart:12553–12576.
Do not implement features in _buildDojoTabNative (12645+) unless explicitly reviving that path.
Legacy dojo_* WS lives in bridge_server.py ~4459–4532 — keep protocol parity with any simulation work.
```
