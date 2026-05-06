# Client Portal — Onboarding paid (`OnboardingPaidScreen`)

> Status: `DRAFT` (outbound sends + inner-builder WebSocket paths **TBD** in foundational pass)  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_FOUNDATIONAL_SPEC.md` §3 **row 4**; file prefix `04_`.

---

## 1. Purpose (1 sentence)

Present the **paid-tier** onboarding walkthrough (`OnboardingPaidScreen`) over **HTTP** with an optional pre-existing WebSocket in the ctor (`onboarding_paid_screen.dart:20–29`), with UI rooted at **`build`** — `onboarding_paid_screen.dart:149`.

---

## 2. UX acceptance criteria (client perspective)

> Source: `_FOUNDATIONAL_SPEC.md` §2 (Paid onboarding row), §3 row 4; `_PIPELINE_TEMPLATE.md` §2.

- [ ] First meaningful action is reachable without hunting — template §2
- [ ] Loading states resolve or surface a **retry** within 30s — template §2
- [ ] Errors state **what failed** and **what to do next** — template §2
- [ ] No silent empty states when the server returned an error — template §2
- [ ] Touch targets ≥ 44pt on primary CTAs — template §2
- [ ] **WebSocket / REST timing:** authenticated REST calls do not race bridge token propagation where Bearer is expected — `_FOUNDATIONAL_SPEC.md` §6 + template §2
- [ ] **Optional socket ctor:** parity with Threshold pattern — reuse vs duplicate connection must match product rules when `existingSocket` (or equivalent) is threaded — `_FOUNDATIONAL_SPEC.md` §3 compares row 4 to row 3 (HTTP + optional socket pattern)
- [ ] **`Tokens` presentation state (`onboarding_paid_screen.dart:38–46`)** stays coherent with **`subscription_plan` / tier** truth from server (**TBD** binding — no REST table row in foundational §5)
- [ ] Inner builders’ WebSocket story is **TBD** (`§2` “**TBD** inner builders”); slides must not open orphan sockets silently
- [ ] Do not confuse with **trial** onboarding — row **3** — `onboarding_threshold_screen.dart:196`; or **tutorial** completion — row **5** — `mark_onboarding_complete` at `updated_screens.dart:356`

---

## 3. UI components

| Component | Location | Purpose | Notes |
|-----------|----------|---------|-------|
| `OnboardingPaidScreen` | `onboarding_paid_screen.dart:14–34` | Stateful paid onboarding | §2 row |
| `build` | `onboarding_paid_screen.dart:149` | Primary UI | §3 row 4 |
| Inner builders | **`TBD`** (§2 inner builders — no line besides class range) | Per-step UI | WebSocket **TBD** |

---

## 4. Files (canonical references)

### Mobile
- `onboarding_paid_screen.dart:14–34` — class `OnboardingPaidScreen`
- `onboarding_paid_screen.dart:20–29` — constructor (**HTTP + optional socket**)
- `onboarding_paid_screen.dart:38–46` — `Tokens` (+ related state snippet per §3 row 4 label)
- `onboarding_paid_screen.dart:149` — `build`
- **TBD:** navigator call site after `login_success` — **not** cited in foundational for this widget

### Bridge (WebSocket)
- **TBD** — foundational §4 has no onboarding-paid-specific types; row 4 “Sends / calls **TBD**”

### REST (FastAPI)
- **TBD** — HTTP asserted without concrete path names in foundational §5 for paid onboarding

### Storage
- **TBD** — `has_seen_paid_onboarding` / equivalents not listed in foundational §5 for row 4 (see onboarding chain only in `_FOUNDATIONAL_SPEC.md` §1 generally)

---

## 5. State variables

| Variable | Type | Set at | Clear at | Default |
|----------|------|--------|----------|---------|
| `Tokens` (+ related UI state label in §3) | **see `onboarding_paid_screen.dart:38–46`** | **TBD** per field names | **TBD** | **TBD** |

---

## 6. WebSocket messages

| Direction | Type | Flutter `file:line` | Bridge `file:line` | Notes |
|-----------|------|---------------------|----------------------|-------|
| → | **TBD** | **TBD** (inner builders) | **TBD** | §2 + §3 row 4 |
| → *(optional ctor path)* | **TBD** | `onboarding_paid_screen.dart:20–29` | **TBD** | Optional socket threading |

**Contrast:** compulsory tutorial WS uses `mark_onboarding_complete` — **row 5**, `updated_screens.dart:356` / `bridge_server.py:25481` (`_FOUNDATIONAL_SPEC.md` §3 row 5, §4.B) — **not** row 4.

---

## 7. Database tables touched

- **TBD** — no paid-onboarding entry in foundational §5.

---

## 8. Edge cases

- **Paid vs trial routing:** orthogonal surfaces — `_FOUNDATIONAL_SPEC.md` §3 rows **3 vs 4**; branching logic lines **not** in foundational (`**TBD**`)
- **Optional socket ctor:** disposal / shared ownership **TBD** — analogous risk to row 3 (`onboarding_threshold_screen.dart:19–26`)
- **Inner builders WebSocket:** **TBD** per §2
- **Tier display drift:** `_FOUNDATIONAL_SPEC.md` §28 in workspace notes uppercase `tier`/`subscription_status`; UI must reflect server CHECK values — enforcement **TBD** for this file (not enumerated in foundational)

---

## 9. Anti-patterns from git history (reject without investigation)

≥3 commits from `_FOUNDATIONAL_SPEC.md` §9 (summaries verbatim from spec).

| Commit | Summary (foundational) |
|--------|-------------------------|
| `38158cc` | Client schedule: shared authenticated app WS + availability error handling |
| `2145c9d` | Attach `NeuralInterface` WS to `_ClientWsHub` after `login_success` |
| `8c2a768` | Gate diagnostic for `client_get_coach_availability` silent drop |
| `c43b9a3` | Diagnostic logging on `client_get_coach_availability` |
| `ea68dd3` | Tighten `client_get_upcoming_sessions` filter (duplicate AI rows) |
| `d7ec21a` | Bridge WebSocket `UnboundLocalError` / datetime shadowing fix |

---

## 10. Known bugs

### Open

| ID | Symptom | Evidence | Owner |
|----|---------|----------|-------|
| OB-OP-01 | Sends / inner-builder WS / REST URLs **all TBD** | `_FOUNDATIONAL_SPEC.md` §3 row 4; §2 | TBD |

### Resolved

| Date | Commit | Bug | Fix |
|------|--------|-----|-----|
| — | — | — | — |

---

## 11. Steve Jobs UX debt (dated)

≥3 rows from `_FOUNDATIONAL_SPEC.md` §10; §7 row where it extends the shell story.

| Date | Severity | Friction (foundational §10 unless noted) | Applicability (row 4) |
|------|----------|------------------------------------------|------------------------|
| 2026-05-05 | High | Opening **Family Sanctuary** **closes** the primary chat socket — `updated_screens.dart:3701–3703` | **Indirect:** paid onboarding sits before steady-state hubs; regressions here affect perceived “cold start.” |
| 2026-05-05 | High | **Schedule from settings** omits password — `settings_screen.dart:2964–2968` | **Indirect:** post-onboarding journeys that jump to schedule without resilient auth. |
| 2026-05-05 | Medium | **Distress beacon** opens a **second** WebSocket — `distress_beacon_screen.dart:75–78` | **Contrast:** optional ctor on row 4 must not silently duplicate hubs (pattern risk). |
| 2026-05-05 | Medium | **Weekly brief** uses `X-User-Id` without Bearer — `settings_screen.dart:6321–6323` | **Direct:** precedent for weaker auth symmetry on REST; any paid-onboarding REST must audit parity. |
| 2026-05-05 | Low | Legacy **`NeuralInterface`** alongside **`NeuralInterfaceV2`** — `main.dart:1339` vs `updated_screens.dart:1183` | **Maintenance:** onboarding routing must land on the canonical chat surface post-flow. |

**§7 supplement (shell / web):** Service worker / web quirks — **TBD** (no log excerpt) — `_FOUNDATIONAL_SPEC.md` §7 (“Service worker / web quirks”).

---

## 12. Security boundaries

- **Paid entitlements messaging** must not over-promise Stripe/subscription guarantees — stripe paths **not** enumerated for row 4 in foundational
- **`Tokens` UI:** no raw tokens in analytics logs — hygiene (not foundational detail)
- **Client-only scope** — `_FOUNDATIONAL_SPEC.md` §8 opener

---

## 13. Manual test scenarios

1. Reach **Paid onboarding** from post-login (**nav line TBD** in foundational).
2. Walk happy path assuming HTTP success — **URLs TBD**
3. ctor **with vs without** optional socket — `onboarding_paid_screen.dart:20–29`
4. Force HTTP error — observe recovery — **endpoint TBD**
5. Regression: completes without accidentally firing **`mark_onboarding_complete`** tutorial message (row **5**) — cite separation in §6

---

## 14. Foundational spec cross-reference

- **Inventory:** §3 **row 4**
- **Entry table:** §2 “Paid onboarding”
- **Auth shell:** §6 (no paid-specific bullet listed)
- **WS catalog:** §4 (no dedicated row-4 rows)
- **Debt:** §7, §10

---

## 15. Daily health checks

Manual: confirm canonical lines (`14–34`, `20–29`, `38–46`, `149`); grep §9 when modifying `onboarding_paid_screen.dart`. Script **TBD**.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05` (foundational only)  
**Tokens saved:** `TBD`

---

## 17. Cursor prefix

```
Read docs/client_portal/features/04_onboarding_paid.md + _FOUNDATIONAL_SPEC.md §3 row 4 + §2 (Paid onboarding).
Do not conflate with row 3 (trial) or row 5 (tutorial / mark_onboarding_complete).
```

---

*Spec from `docs/client_portal/_FOUNDATIONAL_SPEC.md` + `_PIPELINE_TEMPLATE.md` only — 2026-05-05.*
