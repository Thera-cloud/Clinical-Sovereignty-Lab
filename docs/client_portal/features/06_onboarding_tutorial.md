# Client Portal — Onboarding tutorial (`OnboardingTutorialScreen`)

> Status: `DRAFT` (tutorial slide/content line map **TBD** beyond **`build`** anchor)  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_FOUNDATIONAL_SPEC.md` §3 **row 5**, §2 (Mandatory tutorial); `_TAB_INVENTORY_2026-05-05.md` **§C C7**; `_PHASE_3_PLAN.md` **spec 06** (**`mark_onboarding_complete`** cross-ref §4.B). Prefix **`06_`**.

---

## 1. Purpose (1 sentence)

Serve the **mandatory** client tutorial (`OnboardingTutorialScreen`) over a dedicated **`_socket`** in the same state class (**`updated_screens.dart:84–85`**), finalize progress with **`mark_onboarding_complete`** (**`updated_screens.dart:353–356`**), after auto-routing when **`!onboardingDone && role != 'ADMIN'`** — **`main.dart:6730–6737`** (**C7**).

---

## 2. UX acceptance criteria (client perspective)

> Source: `_FOUNDATIONAL_SPEC.md` §3 row **5**, §6; `_TAB_INVENTORY_2026-05-05.md` §C **C7**, §**H** (tier/onboarding guards); `_PIPELINE_TEMPLATE.md` §2.

- [ ] Tutorial **`build`** reachable without dead-end — **`updated_screens.dart:425`**  
- [ ] **`_socketReady`** gate respected before **`mark_onboarding_complete`** (**state** **`75–79`** — do not fire on stale socket)
- [ ] **`_pageController`** carousel / paging behaves predictably (**`75–79`**); final step completion path **TBD** slide lines  
- [ ] **`ADMIN`** role **skips** mandatory tutorial per gate — **`6730–6737`** (**C7**)  
- [ ] Completing tutorial transitions client toward **`NeuralInterfaceV2`** / consent stack without orphan **`_socket`** (**TBD** dispose map)  
- [ ] Contrasts **trial** (**row 3**) & **paid** (**row 4**) — HTTP/optional-socket onboarding **must not** send **`mark_onboarding_complete`** in their place (**04**/**03** specs)  
- [ ] Loading / retry: if **`_socket`** drops mid-tutorial, surface **retry** vs silent stall (**TBD**)  
- [ ] Touch targets ≥ 44pt — template  
- [ ] **Contrast chat `login_request`**: tutorial socket is **not** the **`NeuralInterfaceV2`** connect **`1472`** — avoids duplicate-login confusion (**§3 row 7**)  
- [ ] Errors: completion failure leaves user with **explicit** next step (**TBD** bridge error mapping)  

---

## 3. UI components

| Component | Location | Purpose | Notes |
|-----------|----------|---------|-------|
| **`OnboardingTutorialScreen`** | `updated_screens.dart:58` (**C7** class anchor) | Stateful tutorial shell | Inventory |
| **`build`** | `updated_screens.dart:425` | Primary UI | §3 row **5** |
| **`_socket`** | `updated_screens.dart:84–85` | WS transport | Same class as tutorial |
| **Pager controller** | state **`updated_screens.dart:75–79`** | Slide navigation | `_pageController` |

---

## 4. Files (canonical references)

### Mobile
- `updated_screens.dart:58` — **`OnboardingTutorialScreen`** (**C7**)
- `updated_screens.dart:75–79` — **`_pageController`, `_socketReady`** (representative state)
- `updated_screens.dart:84–85` — **`_socket`**
- `updated_screens.dart:353–356` — completion send (**includes `356`**)
- `updated_screens.dart:425` — **`build`**
- `main.dart:6730–6737` — auto-route predicate (**C7**)

### Bridge (WebSocket)
- **`mark_onboarding_complete`** handler — **`bridge_server.py:25481`** — `_FOUNDATIONAL_SPEC.md` §4.B

### REST (FastAPI)
- **N/A** for completion path on row **5** (WS-only in foundational pass)

### Storage
- **`onboardingDone` / persistence** mechanism — **TBD** (§5 lacks tutorial row)

---

## 5. State variables

| Variable | Type | Set at | Clear at | Default |
|----------|------|--------|----------|---------|
| `_socket` | `WebSocketChannel` | ctor / connect **TBD** | dispose **TBD** | **TBD** |
| `_socketReady` | `bool` | handshake **TBD** | error / dispose | **`false`** |
| `_pageController` | `PageController` | `initState` **TBD** | dispose | **TBD** |

---

## 6. WebSocket messages

| Direction | Type | Flutter `file:line` | Bridge `file:line` | Notes |
|-----------|------|---------------------|---------------------|-------|
| → | **`mark_onboarding_complete`** | **`353–356`** (payload assembly **353–355**, send **`356`**) | **`25481`** | §4.B |
| *(TBD)* | warmup / handshake | **`84–85`** adjunct | — | **`_socketReady`** dependency |

---

## 7. Database tables touched

- **TBD** — completion likely updates **`users.profile_data`** (or equivalent) via bridge — **not** enumerated in foundational §5

---

## 8. Edge cases

- **`onboardingDone` true** but stale client cache → tutorial loop / skip fight (**TBD**)  
- **Biometric opt-in (`09`)** or **security modals (`08`)** fires while tutorial foreground — modal stack **TBD**  
- **`COACH_ONLY`** user may bypass chat but tutorial predicate uses **`6730–6737`** (**ADMIN** exempt only per inventory string) — verify product intent (**TBD**)  

---

## 9. Anti-patterns from git history (reject without investigation)

≥3 commits — `_FOUNDATIONAL_SPEC.md` §9 (verbatim).

| Commit | Summary (foundational) |
|--------|-------------------------|
| `38158cc` | Client schedule: shared authenticated app WS + availability error handling |
| `2145c9d` | Attach `NeuralInterface` WS to `_ClientWsHub` after `login_success` |
| `8c2a768` | Gate diagnostic for `client_get_coach_availability` silent drop |
| `c43b9a3` | Diagnostic logging on `client_get_coach_availability` |
| `ea68dd3` | Tighten `client_get_upcoming_sessions` filter (duplicate AI rows) |
| `d7ec21a` | Bridge WebSocket `UnboundLocalError` / datetime shadowing fix |

**Reject:** firing **`mark_onboarding_complete`** without **`_socket`** readiness; borrowing **`NeuralInterfaceV2`** socket for tutorial completion.

---

## 10. Known bugs

### Open

| ID | Symptom | Evidence | Owner |
|----|---------|----------|-------|
| OT-01 | Persistence field for **`onboardingDone`** — **TBD** | foundational §5 gap | TBD |

### Resolved

| Date | Commit | Bug | Fix |
|------|--------|-----|-----|
| — | — | — | — |

---

## 11. Steve Jobs UX debt (dated)

≥3 rows — `_FOUNDATIONAL_SPEC.md` §10 / §7 (applicability).

| Date | Severity | Friction | Applicability |
|------|----------|----------|----------------|
| 2026-05-05 | Medium | Legacy **`NeuralInterface`** vs **V2** dual stack — §10 | Wrong tutorial→chat nav if routing regresses post-**`mark_onboarding_complete`** |
| 2026-05-05 | High | **`login_success`** cascade density — §6 **`6656–6752`** | Tutorial sits inside gate ordering; flaky ordering = skipped slides or duplicate sockets |
| 2026-05-05 | Medium | Flutter **web SW** quirks — §7 **TBD** | Tutorial WS may appear “stuck” on Safari if bootstrap cache stale |
| 2026-05-05 | Low | **Family Sanctuary** socket close pattern — §10 | Post-tutorial user entering sanctuary hits reconnect latency independent of this spec |

---

## 12. Security boundaries

- Tutorial WS should not expose **other users’** data (**TBD** bridge payload audit).  
- **`mark_onboarding_complete`** must be **authenticated** on bridge (**handler `25481`** assumes prior auth — **verify** on change).  
- **`ADMIN`** exemption — **`6730–6737`** — security posture: admin never forced through client marketing/tutorial content.  

---

## 13. Manual test scenarios

1. New **CLIENT** with **`!onboardingDone`** → **`C7`** lands on tutorial **`425`**.  
2. Walk final slide → **`356`** fires → bridge **`25481`** ack → navigates forward (**TBD** destination assertion).  
3. **`ADMIN`** login → tutorial **not** forced (**`6730–6737`**).  
4. Kill bridge mid-tutorial → reconnect / retry UX (**TBD**).  
5. Regression: **paid** (**04**) and **trial** (**03**) flows never send **`mark_onboarding_complete`** prematurely.  

---

## 14. Foundational spec cross-reference

- **§3 row:** **5**  
- **§2:** Mandatory tutorial row  
- **§4.B:** **`mark_onboarding_complete`** (`356` / `25481`)  
- **§6:** post-login ordering  
- **Privacy:** §8  

---

## 15. Daily health checks

Manual: **`425`**, **`356`**, **`25481`**, **`6730–6737`** anchors unchanged after edits.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05` (foundational + inventory + phase plan only). **Tokens saved:** `TBD`.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/06_onboarding_tutorial.md +
_FOUNDATIONAL_SPEC.md §3 row 5 + §4.B mark_onboarding_complete.
Cross-ref 03_onboarding_trial.md and 04_onboarding_paid.md — different transport; do not merge completion messages.
```

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` only — 2026-05-05.*
