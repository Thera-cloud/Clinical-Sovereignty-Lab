# Coach Portal — INSIGHTS (Tab 2)

> Status: ACTIVE  
> Last full review: 2026-05-04  
> Next review due: 2026-05-11 (weekly cadence)  
> Owner: Nathan  
> Steve Jobs UX score: needs work  

---

## 1. Purpose (1 sentence)

The INSIGHTS tab combines AI mode control, Nevedal report generation, coach–Nate chat (`inquiry`), **coach client override** (with audit), **override history**, and **panel insights** fetch — shipped **partially**, with some headline metrics still **hardcoded**.

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
- [ ] AI Modes picker (`10525–10544`) shows the active mode after `_activateCoachAiMode` / `ai_mode_activate` succeeds or fails visibly  
- [ ] Nevedal Report (`10549–10557` → `7049–7059`) shows progress or explicit failure — never a silent no-op  
- [ ] Insights chat send (`9847–9851` → `9700–9711`) handles 401/timeout with recoverable messaging (token / connection)  
- [ ] Coach override section (`10610` / `_buildCoachOverrideInsightsSection`) makes **who** is being overridden and **audit consequence** obvious before commit  
- [ ] Override history (`coach_get_override_history`, Flutter send sites `5525–5526`) is readable (time-ordered, no raw JSON wall)  
- [ ] `coach_get_client_panel_insights` (`17680`) loading does not block unrelated tab interactions unless intentionally full-screen  
- [ ] Any metric still **not** backed by the backend must **not** read as live data (no false precision — see Known UX Debt)  

---

## 3. UI Components

| Component | Location | Purpose | Notes |
|---|---|---|---|
| Insights tab scaffold | `mobile/lib/updated_screens.dart:10515–10684` (`_buildInsightsTab`) | Tab shell | Tab 2; partial/hardcoded metrics |
| AI Modes picker | `mobile/lib/updated_screens.dart:10525–10544` | `_showCoachAiModePicker` → `_activateCoachAiMode` | WS `ai_mode_activate` |
| Nevedal Report | `mobile/lib/updated_screens.dart:10549–10557` | `_showNevedalReportDialog` | REST `7049–7059` |
| High Risk / Breakthroughs (stub) | `mobile/lib/updated_screens.dart:10585–10595` | Display headline counts | **Hardcoded `"0"`** per spec |
| Insights chat | `mobile/lib/updated_screens.dart:9847–9851` | `_sendInsightsChat` | REST `9700–9711`, `mode=inquiry` |
| Coach override section | — | `_buildCoachOverrideInsightsSection` (invoked `10610`) | WS override family |
| Override history | — | (history UI + `coach_get_override_history`) | Send sites `5525–5526` |

---

## 4. Files (canonical references)

### Mobile
- `mobile/lib/updated_screens.dart:10515–10684` — `_buildInsightsTab()`  
- `mobile/lib/updated_screens.dart:10525–10544` — AI modes  
- `mobile/lib/updated_screens.dart:10549–10557` — Nevedal report dialog  
- `mobile/lib/updated_screens.dart:10585–10595` — hardcoded High Risk / Breakthroughs  
- `mobile/lib/updated_screens.dart:9847–9851` — `_sendInsightsChat`  
- `mobile/lib/updated_screens.dart:9700–9711` — REST `POST /api/coach/nate-chat` (`inquiry`)  
- `mobile/lib/updated_screens.dart:7049–7059` — `POST /api/research/nevedal/reports/generate`  
- `mobile/lib/updated_screens.dart:5525–5526` — `coach_get_override_history` (Flutter → WS)  
- `mobile/lib/updated_screens.dart:4322` — `_insightsChatLoading` (shared dashboard state per foundational “Loading flags”)  

### Backend WebSocket (`bridge_server.py`)
- `ai_mode_activate` — `6958–6963`  
- `coach_set_client_override` / `coach_get_client_override` / `coach_clear_client_override` / `coach_get_override_history` / `coach_renew_override` — `17903` (grouped per foundational spec)  
- `coach_get_client_panel_insights` — `17680`  

### Backend modules
- `backend/app/routers/coach.py` — coach Nate chat and related coach REST (see foundational “Coach Nate Chat”; `770+` region in global inventory)  
- `backend/app/services/coach_override_protocol.py` — override protocol logic (per Tab 2 file list)  

### Storage
- `coach_client_overrides`, `coach_override_audit` — WebSocket override family  
- `coach_nate_chat_history` — migration `090` (global inventory)  
- SSE-related tables — `coach_get_client_panel_insights` per spec  

---

## 5. State Variables

| Variable | Type | Set true at | Set false at | Default |
|---|---|---|---|---|
| `_insightsChatLoading` | bool | insights chat send path | send complete / error | false |
| *(override UI)* | — | set/reset in override section builders | must pair WS acks | — |

*Override flows span **five** WS message types; every “apply override” path should clear busy flags on error (see section 6).*

---

## 6. WebSocket Messages

| Direction | Type | Trigger | State change | Failure handling |
|---|---|---|---|---|
| → | `ai_mode_activate` | Mode picker | mode state / server flags | User-visible error |
| → | `coach_set_client_override` | Override UI | pending → saved | Audit must record; rollback messaging |
| → | `coach_get_client_override` | Load current | displays active override | Distinguish “none” vs “error” |
| → | `coach_clear_client_override` | Clear action | clears row | Confirm destructive |
| → | `coach_get_override_history` | History load | list | `5525–5526` send sites |
| → | `coach_renew_override` | Renew | extends / updates | Expiration handling |
| → | `coach_get_client_panel_insights` | Panel refresh | insights cards | SSE / empty states |

**Critical pairings (must always co-occur):**
- Override **set/clear/renew** ↔ `coach_override_audit` expectation (spec: audit trail)  
- Chat send ↔ `_insightsChatLoading` cleared on **all** exit paths  
- Panel insights fetch must not assume non-empty SSE backing data  

---

## 7. Database Schema

```sql
-- coach_client_overrides — active overrides (186 / foundational)
-- coach_override_audit — append-only audit (189)
-- coach_nate_chat_history — coach Nate chat persistence (090)
-- SSE-backed tables — panel insights (handler 17680)
```

**Approval gates:** overrides are clinical/legal sensitive; audit trail is non-optional for governance.  
**Soft delete:** follow override tables’ semantics; do not “quietly” delete audit rows from UI actions.

---

## 8. Known Bugs (Resolved)

| Date | Commit | Bug | Fix |
|---|---|---|---|
| — | `ff224c8` | Coach `nate-chat` trusted client-supplied master-coach identity | Server-side `is_master_coach` verification |
| — | `4c05677` | Layer 9 paths (overrides, panel insights, related) not fully wired to bridge handlers | Wired coach override / panel insight / related handlers |
| — | `169bd6c` | Override protocol lacked structured validation, expiration, audit surfacing in UI | #23 Coach Override Protocol (audit, validation, expiration, Flutter) |

---

## 9. Anti-Patterns (Reject Without Investigation)

- ❌ **Trusting the client payload for coach hierarchy / master authority on Nate chat** — fixed `ff224c8`; any new “trust the app” shortcut reopens abuse.  
- ❌ **Shipping “risk” or insights visuals with broken data binding or nesting** — class addressed in `c0a14e7`, `02a5f22` (crisis watchlist / related Eye display); INSIGHTS tab still has **hardcoded** risk counters — do not pretend they are live.  
- ❌ **Override or panel-insight UI without matching bridge persistence + audit** — pre-`4c05677` / `169bd6c` failure mode.  
- ❌ **Adding a sixth divergent transport for the same override state** without collapsing the five WS types — spec already flags complexity.  

**Why this section exists:** insights touch **clinical posture** and **chat**; bugs here erode trust faster than cosmetic UI issues.

---

## 10. Daily Health Checks (run by `coach_portal_daily_check.sh`)

- [ ] `10585–10595` still clearly marked stub OR replaced with live data  
- [ ] `coach_override_protocol.py` imports cleanly; override WS handlers still at `17903` grouping  
- [ ] `coach_get_client_panel_insights` still documented at `17680`  
- [ ] Coach nate-chat still uses server-side master verify (`ff224c8` invariant)  
- [ ] No new “trust client for role” patterns in `coach.py` / bridge  

---

## 11. Investigation Cache

1. Read THIS FILE FIRST  
2. Open section 4 line ranges; confirm stub metrics vs backend  
3. Reject section 9 patterns before proposing new override/chat features  
4. Update section 8 when a production bug is fixed with commit hash  
5. If wired metrics replace `10585–10595`, update criteria §2 and §3 in same PR  

**Last full investigation:** 2026-05-04 (spec-only from `_FOUNDATIONAL_SPEC.md` Tab 2)  
**Cost-saved estimate:** TBD after first code-level pass  

---

## 12. Steve Jobs Review

Apply quarterly. The standard is "would Steve ship this."

- [ ] Does the first interaction feel inevitable? **— Debt:** tab bundles AI mode + reports + chat + overrides + panel — no single hero story  
- [ ] Is anything on this screen unnecessary? **— Debt:** hardcoded **High Risk** / **Breakthroughs** are visual noise until real data lands  
- [ ] Could a non-technical user complete the primary action without instruction? **— Debt:** five WS override operations exceed working memory  
- [ ] Does the empty state teach the value of the tab? **— Debt:** stub `0` rows teach the wrong lesson (false calm)  
- [ ] Does the error state preserve trust? **— Debt:** chat + report generation must never look like “Nate is ignoring me”  
- [ ] Is the most important thing the most prominent thing? **— Debt:** override vs chat vs report compete without clear priority  

### Logged UX debt (target ship dates)

| Item | Issue | Target |
|------|--------|--------|
| SJ-1 | **"High Risk" / "Breakthroughs" show hardcoded `"0"`** (`10585–10595`) — reads as real telemetry | 2026-06-01 |
| SJ-2 | **Override surface uses five WebSocket types** + audit — power-user only without progressive disclosure | 2026-07-15 |
| SJ-3 | **Tab status: “Shipped (partial)”** — mixed live/stub erodes confidence; ship honest labeling or gate the tab | 2026-05-30 |

---

## 13. Cloning This Template (For New Tabs)

See `docs/coach_portal/_PIPELINE_TEMPLATE.md` §13.

---

## 14. Adapter Comments For Cursor

```
Read docs/coach_portal/features/03_insights.md before any investigation.
Source tab: docs/coach_portal/_FOUNDATIONAL_SPEC.md Tab 2 (INSIGHTS).
Do not treat 10585–10595 counts as real. Reject client-trusted coach authority (ff224c8).
Override changes require audit + handler parity at bridge_server.py:17903 family.
```
