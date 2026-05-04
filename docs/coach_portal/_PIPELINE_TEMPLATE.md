# Coach Portal — <TAB_NAME>

> Status: <DRAFT | ACTIVE | DEPRECATED>
> Last full review: <YYYY-MM-DD>
> Next review due: <YYYY-MM-DD> (weekly cadence)
> Owner: Nathan
> Steve Jobs UX score: <not yet assessed | needs work | shipped>

---

## 1. Purpose (1 sentence)

<What this tab does for the coach. One sentence. If it takes more than one sentence, the tab is doing too much.>

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
- [ ] <add tab-specific criteria here>

---

## 3. UI Components

| Component | Location | Purpose | Notes |
|---|---|---|---|
| <ComponentName> | <file:line> | <purpose> | <accessibility/edge case notes> |

---

## 4. Files (canonical references)

### Mobile
- `mobile/lib/updated_screens.dart:LINE_RANGE` — <what's in this range>
- `mobile/lib/screens/<screen>.dart` — <if separate>

### Backend handler
- `backend/app/websocket/bridge_server.py:LINE_RANGE` — <handler name>
- `backend/app/routers/<router>.py` — <if REST>

### Backend service
- `backend/app/services/<service>.py` — <business logic class>

### Storage
- Migration: `backend/migrations/NNN_<schema>.sql`
- Tables: `<table_1>`, `<table_2>`
- Read paths: <list service methods>
- Write paths: <list service methods>

---

## 5. State Variables

State that lives across renders. Document every set/reset point. Missing reset = stuck UI bug (see classroom.md known bugs).

| Variable | Type | Set true at | Set false at | Default |
|---|---|---|---|---|
| `_<name>` | bool | line X | lines Y, Z | false |

---

## 6. WebSocket Messages

| Direction | Type | Trigger | State change | Failure handling |
|---|---|---|---|---|
| → | <message_type> | <user action> | <state set> | <what cancels> |
| ← | <message_type> | <backend trigger> | <state reset> | <error path> |

**Critical pairings (must always co-occur):**
- Every state-set message MUST have a state-reset message OR a timeout
- Every error path MUST reset analyzing/loading flags
- Every onError/onDone WebSocket handler MUST reset flags

---

## 7. Database Schema

```sql
-- Tables this tab reads/writes
-- Include the columns this tab cares about
```

**Approval gates:** <if any rows require coach approval before surfacing>
**Soft delete:** <yes/no, which column>

---

## 8. Known Bugs (Resolved)

| Date | Commit | Bug | Fix |
|---|---|---|---|
| YYYY-MM-DD | <hash> | <one-line bug> | <one-line fix> |

---

## 9. Anti-Patterns (Reject Without Investigation)

These are mistakes already made. If a code proposal contains any of these, reject before reading further.

- ❌ <pattern>
- ❌ <pattern>

**Why this section exists:** every entry below was a real bug that wasted a Cursor session diagnosing it. Treat this list as battle-tested rules.

---

## 10. Daily Health Checks (run by `coach_portal_daily_check.sh`)

- [ ] All file references in section 4 still exist
- [ ] All anti-patterns in section 9 still absent (grep checks)
- [ ] Service `<name>` listed in `_service_checks` registry
- [ ] No new TODO markers added since last review
- [ ] WebSocket handler reset paths still match section 6 table

---

## 11. Investigation Cache

When Cursor needs to work on this tab, it should:

1. Read THIS FILE FIRST (skip discovery)
2. Open the files in section 4 by exact line numbers
3. Check section 9 anti-patterns BEFORE proposing changes
4. Update section 8 if a new bug is fixed
5. Update section 11 with the date of investigation

**Last full investigation:** YYYY-MM-DD by <session>
**Cost-saved estimate:** <tokens skipped because this doc existed>

---

## 12. Steve Jobs Review

Apply quarterly. The standard is "would Steve ship this."

- [ ] Does the first interaction feel inevitable?
- [ ] Is anything on this screen unnecessary?
- [ ] Could a non-technical user complete the primary action without instruction?
- [ ] Does the empty state teach the value of the tab?
- [ ] Does the error state preserve trust?
- [ ] Is the most important thing the most prominent thing?

If any answer is "no" — log it as UX debt with a target ship date.

---

## 13. Cloning This Template (For New Tabs)

To create a spec for a new tab:

```bash
cp docs/coach_portal/_PIPELINE_TEMPLATE.md docs/coach_portal/<new_tab>.md
```

Then:
1. Replace every `<...>` placeholder with concrete data
2. Delete sections that don't apply (e.g., "WebSocket Messages" if tab is REST-only)
3. Fill in section 9 anti-patterns by reviewing recent git log for that tab's files: `git log --oneline mobile/lib/updated_screens.dart | head -20`
4. Set "Last full review" to today's date
5. Schedule next review for 7 days out
6. Run `coach_portal_daily_check.sh` and verify the new spec passes

**The first version of any new tab spec should focus on UX/UI only (sections 1, 2, 3, 12).** Code mechanics (sections 4-7, 9, 11) get filled in during the first real investigation of that tab. This avoids documentation drift — you only document mechanics you've actually verified.

---

## 14. Adapter Comments For Cursor

When invoking Cursor on this tab, prefix the prompt with:

```
Read docs/coach_portal/<tab>.md before any investigation.
The file contains:
- Exact line numbers for files in this tab
- Anti-patterns to reject without analysis
- Known bug history with commits

Skip discovery. Use the doc as ground truth. If the doc is stale,
update it as part of your fix and report the divergence.
```

This single instruction can save 50-200k tokens per session.
