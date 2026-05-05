# Client Portal — `<FEATURE_NAME>`

> Status: `<DRAFT | ACTIVE | DEPRECATED>`  
> Last full review: `<YYYY-MM-DD>`  
> Next review due: `<YYYY-MM-DD>` (weekly cadence)  
> Owner: Nathan  
> Steve Jobs UX score: `<not yet assessed | needs work | shipped>`

---

## 1. Purpose (1 sentence)

`<What this feature does for the client in one sentence. If it needs two sentences, split the feature.>`

---

## 2. UX acceptance criteria (client perspective)

Reject changes that break any unchecked item after manual verification on **client** role (`expected_role: CLIENT` on `login_request` — see `docs/client_portal/_FOUNDATIONAL_SPEC.md` §6).

- [ ] First meaningful action is reachable without hunting (coach vs client IA differs — no coach roster noise)
- [ ] Loading states resolve or surface a **retry** within 30s (REST timeouts e.g. weekly brief `35s` — `settings_screen.dart:6324`)
- [ ] Errors state **what failed** and **what to do next** (not generic “something went wrong”)
- [ ] No silent empty states when the server returned an error (log + UI affordance)
- [ ] Touch targets ≥ 44pt on primary CTAs
- [ ] **WebSocket:** after `login_success`, no REST calls fire before token is usable where backend expects Bearer (race with Redis propagation — workspace trust rules)
- [ ] **Dual-socket flows** (e.g. schedule-from-settings via `_ClientWsHub`) do not strand the user if hub channel is null — `main.dart:10419–10454`
- [ ] **Family / chat transitions** that close the parent socket document reconnect UX — `updated_screens.dart:3701–3712`
- [ ] `<8+ total: add 1+ feature-specific criteria here>`

---

## 3. UI components

| Component | Location | Purpose | Notes |
|-----------|----------|---------|-------|
| `<Widget>` | `<file:line>` | `<purpose>` | `<a11y / edge>` |

---

## 4. Files (canonical references)

### Mobile
- `mobile/lib/<path>:LINE_RANGE` — `<widget / flow>`
- `mobile/lib/updated_screens.dart:LINE_RANGE` — `<NeuralInterfaceV2 / shared>`
- `mobile/lib/main.dart:LINE_RANGE` — `<Lobby, ClientScheduleScreen, FamilySanctuary, _ClientWsHub>`

### Bridge (WebSocket)
- `backend/app/websocket/bridge_server.py:LINE_RANGE` — `<elif msg_type == "..."> handler`

### REST (FastAPI)
- `backend/app/routers/<router>.py` — `<endpoint path>`

### Storage
- Tables: `<table_1>`, `<table_2>` (or `SESSIONS_FILE` JSON where applicable — foundational §5)
- Migration (if schema-bound): `backend/migrations/NNN_<name>.sql`

---

## 5. State variables

| Variable | Type | Set at | Clear at | Default |
|----------|------|--------|----------|---------|
| `_loading` | `bool` | `before request` | `then/catch/finally` | `false` |

**Rule:** every `setState` that sets `_loading` / `_analyzing` / `_sending` MUST clear on **error**, **timeout**, **`onDone`**, and **`dispose`**. Missing clear = stuck UI (coach template rule applies to client).

---

## 6. WebSocket messages

| Direction | Type | Trigger | Expected response / side effect | Failure handling |
|-----------|------|---------|----------------------------------|------------------|
| → | `<type>` | `<user action>` | `<response type or HTTP N/A>` | `<reset flags / show error>` |
| ← | `<type>` | `<server push>` | `<state update>` | `<dedupe / ignore stale>` |

**Critical pairings**
- Every optimistic UI set MUST have timeout OR matching server ack handler
- `client_*` handlers assume `current_profile["role"] == "CLIENT"` where enforced — verify per handler (`_FOUNDATIONAL_SPEC.md` §4)
- Do not assume `client_get_coach_month_overview` is CLIENT-gated — verify `bridge_server.py:14092+` before treating as private

---

## 7. Database tables touched

`<Bullet list or short table: read vs write. If unknown, TBD until traced in router + bridge.>`

**Cross-feature hazards**
- `coach_availability` vs `coaching_sessions.coach_id` typing (UUID vs hardware id) — see `_FOUNDATIONAL_SPEC.md` §5 mismatch note (`bridge_server.py:12166–12210`)

---

## 8. Edge cases

- **Offline / flaky network:** show distinguishable offline vs server error (`SocketException` vs 5xx)
- **Auth lost mid-session:** WebSocket `onDone` / 401 on REST — no auto-redirect loops on dashboard-style pages; client app should prefer **manual refresh** after WS auth failure (pattern: learned integration #13)
- **No coach assigned:** `assigned_coach_id` / `coach_id` empty — schedule and coach header paths (`main.dart:10418`, `settings_screen.dart:468`)
- **COACH_ONLY tier:** routed to `ClientScheduleScreen` without full Nate — `main.dart:6748–6756` — feature may be N/A; document “hidden” vs “error”
- **TBD:** `<feature-specific>`

---

## 9. Anti-patterns from git history (reject without investigation)

Cite **≥3** real commits touching client surfaces. Replace `<...>` with feature-specific `git log` results; starters from shared client/schedule work:

| Commit | Lesson |
|--------|--------|
| `38158cc` | Shared app WebSocket + schedule availability — do not regress hub attach / error surfacing |
| `2145c9d` | Attach post-login socket to `_ClientWsHub` — avoid orphan channels |
| `ea68dd3` | `client_get_upcoming_sessions` filtering — avoid duplicate or stale session rows in UI |
| `8c2a768` / `c43b9a3` | Diagnostics for `client_get_coach_availability` silent failure — do not swallow errors |
| `d7ec21a` | Bridge WS control-flow bugs — avoid shadowing builtins / fragile `elif` chains |

**Reject proposals that:**
- ❌ Open a second WebSocket for the same user session **without** documenting auth + lifecycle (cf. distress beacon pattern — `_FOUNDATIONAL_SPEC.md` §3 row 16)
- ❌ Navigate to `ClientScheduleScreen` without password **and** without hub channel when hub is required
- ❌ Add `client_*` bridge branches without `role == "CLIENT"` guard (except where intentionally public — then document in §11)

---

## 10. Known bugs

### Open
| ID | Symptom | Evidence | Owner |
|----|---------|----------|-------|
| OB-001 | `<one line>` | `<file:line>` | TBD |

### Resolved
| Date | Commit | Bug | Fix |
|------|--------|-----|-----|
| YYYY-MM-DD | `<hash>` | `<one line>` | `<one line>` |

---

## 11. Steve Jobs UX debt (dated)

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| YYYY-MM-DD | High/Med/Low | `<one line>` | `<quarter or TBD>` |

Minimum **3** rows per mature feature spec (pull initial set from `_FOUNDATIONAL_SPEC.md` §10 when relevant).

---

## 12. Security boundaries

- **What the client may see:** `<PII scope, own family, own sessions, …>`
- **What must stay server-only / coach-only:** `<no other clients’ …>`
- **REST vs WS:** never log bearer tokens; headers must match backend expectations (`X-User-Id` alone is weaker than Bearer — call out in §11 if this feature uses header-only auth)
- **Bridge:** if handler lacks explicit CLIENT gate, file a security review item (see `client_get_coach_month_overview` — `_FOUNDATIONAL_SPEC.md` §4)

---

## 13. Manual test scenarios

1. `<Step 1 — login as CLIENT on lobby>`
2. `<Step 2 — primary happy path>`
3. `<Step 3 — refresh / background / reconnect>`
4. `<Step 4 — permission denied / wrong role if applicable>`
5. `<Step 5 — empty data>`

---

## 14. Foundational spec cross-reference

- **Inventory row:** `_FOUNDATIONAL_SPEC.md` §3 table row `<N>`
- **Entry / routing:** §2, §6 as applicable
- **WS inventory:** §4
- **DB / schema notes:** §5
- **Privacy:** §8

---

## 15. Daily health checks

`client_portal_daily_check.sh` — **TBD.** Manual: §4 paths still valid; grep §9 patterns on changed files; no silent empty `catch` on network paths.

---

## 16. Investigation cache

Read this spec + `_FOUNDATIONAL_SPEC.md` §3 row `<N>` first → open §4 by line → run §13 after edits → log §10 fixes. **Last investigation:** `<YYYY-MM-DD>` **Tokens saved:** `<TBD>`

---

## 17. Cloning + Cursor prefix

```bash
cp docs/client_portal/_PIPELINE_TEMPLATE.md docs/client_portal/features/NN_<snake_case_feature>.md
```

Replace `<...>`; drop §6 if REST-only; `git log --oneline -- mobile/lib/main.dart mobile/lib/updated_screens.dart mobile/lib/screens/ | head -25` for §9. First draft: §1–§3, §11–§14; mechanics after first trace.

**Cursor:** `Read docs/client_portal/features/NN_<file>.md + _FOUNDATIONAL_SPEC.md §3 row <N>. Section 4 = line truth; section 9 = reject list. Update spec if code diverges.`

---

*Template: 2026-05-05 (client Phase 2).*
